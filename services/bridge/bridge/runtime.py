"""Bridge daemon runtime — multi-adapter, single connection to Studio.

The daemon is given an opaque list of platform login claims (e.g. chat
username/password tuples) on the CLI. It logs each one in to obtain a
`platform_self_id`, then handshakes Studio with `(platform, platform_self_id)`
pairs. Studio owns the inbox_id (auto-creating an Inbox if it's the first
time we've seen this self_id under this account) and returns the resolved
mapping. The daemon then opens an inbound stream per inbox and shares one
outbound long-poll across them.

Bridge is a pure message forwarder: receive from Studio, send to platform.
No pacing, no delay — Studio controls when each message becomes eligible
via the send_after field on OutboundMessage.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from bridge.adapters.base import Adapter, IncomingMessage, build_adapter
from bridge.studio_client import StudioClient

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15.0
INBOUND_BATCH_LINGER = 0.4
INBOUND_BATCH_MAX = 30
OUTBOUND_LONG_POLL_TIMEOUT = 30


@dataclass(frozen=True)
class InboxClaim:
    """One chat-platform login the user asked us to run."""
    platform: str
    raw: Dict[str, str]


@dataclass
class _AdapterEntry:
    inbox_id: str
    platform: str
    platform_self_id: str
    adapter: Adapter
    inbound_task: Optional[asyncio.Task[Any]] = None


class BridgeRuntime:
    def __init__(
        self,
        *,
        studio: StudioClient,
        hostname: str,
        claims: List[InboxClaim],
    ) -> None:
        self._studio = studio
        self._hostname = hostname
        self._claims = claims
        self._adapters: Dict[str, _AdapterEntry] = {}
        self._inbound_queue: asyncio.Queue[Tuple[str, IncomingMessage]] = asyncio.Queue()
        self._cursor: int = 0
        self._stop = asyncio.Event()
        self._loop_tasks: List[asyncio.Task[Any]] = []

    async def run(self) -> None:
        # 1) Log into each platform claim → get platform_self_id.
        prelogged: List[Tuple[InboxClaim, Adapter, str]] = []
        for claim in self._claims:
            adapter = build_adapter(claim.platform, claim.raw)
            try:
                self_id = await adapter.login()
            except Exception as exc:
                logger.error("login failed for platform=%s raw=%s: %s",
                             claim.platform, _redact(claim.raw), exc)
                with suppress(Exception):
                    await adapter.close()
                continue
            prelogged.append((claim, adapter, self_id))

        # 2) Handshake with Studio. It auto-upserts Inbox rows for any new
        # (platform, platform_self_id) under this account, and returns
        # the authoritative inbox_id for each.
        handshake_payload = [
            {"platform": claim.platform, "platform_self_id": self_id}
            for (claim, _adapter, self_id) in prelogged
        ]
        try:
            info = await self._studio.handshake(
                hostname=self._hostname, inboxes=handshake_payload,
            )
        except Exception as exc:
            logger.error("handshake failed: %s", exc)
            for _claim, adapter, _ in prelogged:
                with suppress(Exception):
                    await adapter.close()
            return

        self._cursor = int(info.get("cursor", 0))
        served = info.get("inboxes", [])  # [{id, platform, platform_self_id, display_name, enabled, ...}]
        served_by_key: Dict[Tuple[str, str], Dict[str, Any]] = {
            (i["platform"], i["platform_self_id"]): i for i in served
        }

        logger.info(
            "handshake ok: bridge=%s account=%s served=%d cursor=%d",
            info.get("bridge_id"), info.get("account_id"), len(served), self._cursor,
        )

        # 3) Bind each prelogged adapter to its assigned inbox_id; drop any
        # that Studio refused because the identity is invalid for this account.
        loop = asyncio.get_running_loop()
        for claim, adapter, self_id in prelogged:
            assigned = served_by_key.get((claim.platform, self_id))
            if not assigned:
                logger.warning(
                    "platform=%s self=%s not served by Studio; dropping adapter",
                    claim.platform, self_id,
                )
                with suppress(Exception):
                    await adapter.close()
                continue
            entry = _AdapterEntry(
                inbox_id=assigned["id"],
                platform=claim.platform,
                platform_self_id=self_id,
                adapter=adapter,
            )
            entry.inbound_task = loop.create_task(
                self._adapter_inbound_loop(entry.inbox_id, adapter),
                name=f"inbound-{entry.inbox_id}",
            )
            self._adapters[entry.inbox_id] = entry
            logger.info("adapter up: inbox=%s platform=%s self=%s display=%s",
                        entry.inbox_id, claim.platform, self_id, assigned.get("display_name"))

        # 4) Initial catch-up batch (idempotent on Studio side).
        await self._push_initial_catchup()

        # 5) Main loops.
        self._loop_tasks = [
            loop.create_task(self._heartbeat_loop(), name="heartbeat"),
            loop.create_task(self._inbound_pump_loop(), name="inbound-pump"),
            loop.create_task(self._outbound_loop(), name="outbound"),
        ]
        try:
            await self._stop.wait()
        finally:
            for t in self._loop_tasks:
                t.cancel()
            for t in self._loop_tasks:
                with suppress(asyncio.CancelledError):
                    await t
            await self._stop_all_adapters()

    def stop(self) -> None:
        self._stop.set()

    # --- adapter lifecycle ----------------------------------------------

    async def _stop_adapter(self, inbox_id: str) -> None:
        entry = self._adapters.pop(inbox_id, None)
        if not entry:
            return
        if entry.inbound_task:
            entry.inbound_task.cancel()
            with suppress(asyncio.CancelledError):
                await entry.inbound_task
        with suppress(Exception):
            await entry.adapter.close()
        logger.info("adapter down: inbox=%s", inbox_id)

    async def _stop_all_adapters(self) -> None:
        for inbox_id in list(self._adapters.keys()):
            await self._stop_adapter(inbox_id)

    # --- per-adapter inbound feed --------------------------------------

    async def _adapter_inbound_loop(self, inbox_id: str, adapter: Adapter) -> None:
        try:
            async for msg in adapter.stream_incoming():
                await self._inbound_queue.put((inbox_id, msg))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("adapter inbound loop crashed (inbox=%s): %s", inbox_id, exc)

    async def _push_initial_catchup(self) -> None:
        for inbox_id, entry in self._adapters.items():
            try:
                msgs = await entry.adapter.list_initial_messages(since_ms=0)
            except Exception as exc:
                logger.error("initial catchup failed for inbox=%s: %s", inbox_id, exc)
                continue
            if msgs:
                await self._push_batch([(inbox_id, m) for m in msgs])

    async def _push_batch(self, batch: List[Tuple[str, IncomingMessage]]) -> None:
        if not batch:
            return
        payload = [self._to_payload(inbox_id, m) for inbox_id, m in batch]
        try:
            res = await self._studio.push_incoming(payload)
            logger.info(
                "inbound: pushed %d (accepted=%s deduped=%s rejected=%s)",
                len(batch), res.get("accepted"), res.get("deduped"), res.get("rejected"),
            )
        except Exception as exc:
            logger.error("inbound push failed: %s", exc)

    @staticmethod
    def _to_payload(inbox_id: str, m: IncomingMessage) -> Dict[str, Any]:
        return {
            "inbox_id": inbox_id,
            "peer_platform_id": m.peer_id,
            "peer_display_name": m.peer_display_name,
            "platform_msg_id": m.platform_msg_id,
            "role": m.role,
            "content": m.content,
            "sent_at": m.sent_at.isoformat(),
        }

    # --- inbound pump --------------------------------------------------

    async def _inbound_pump_loop(self) -> None:
        while not self._stop.is_set():
            try:
                first = await self._inbound_queue.get()
            except asyncio.CancelledError:
                return
            batch: List[Tuple[str, IncomingMessage]] = [first]
            deadline_t = asyncio.get_running_loop().time() + INBOUND_BATCH_LINGER
            while len(batch) < INBOUND_BATCH_MAX:
                remaining = deadline_t - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    item = await asyncio.wait_for(self._inbound_queue.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                except asyncio.CancelledError:
                    break
                batch.append(item)
            await self._push_batch(batch)

    # --- heartbeat -----------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                resp = await self._studio.heartbeat()
                served = {ix["id"] for ix in resp.get("inboxes", [])}
                # If Studio dropped a binding (UI deleted the inbox), stop
                # the adapter; we don't auto-restart anything here — adding
                # a new login means restarting bridge with another --chat-inbox.
                for inbox_id in list(self._adapters.keys()):
                    if inbox_id not in served:
                        logger.info("inbox %s no longer served; stopping adapter", inbox_id)
                        await self._stop_adapter(inbox_id)
            except Exception as exc:
                logger.warning("heartbeat failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                pass

    # --- outbound ------------------------------------------------------

    async def _outbound_loop(self) -> None:
        while not self._stop.is_set():
            try:
                items = await self._studio.long_poll_outbound(
                    cursor=self._cursor, timeout_seconds=OUTBOUND_LONG_POLL_TIMEOUT,
                )
            except Exception as exc:
                logger.warning("outbound long-poll failed: %s", exc)
                await asyncio.sleep(2)
                continue
            for item in items:
                obid = int(item["id"])
                if obid <= self._cursor:
                    continue
                await self._dispatch_outbound(item)
                self._cursor = obid

    async def _dispatch_outbound(self, item: Dict[str, Any]) -> None:
        outbound_id = int(item["id"])
        inbox_id = str(item.get("inbox_id"))
        platform_peer_id = item.get("peer_platform_id")
        content = str(item.get("content", "")).strip()

        entry = self._adapters.get(inbox_id)
        if entry is None:
            await self._studio.ack_outbound(
                outbound_id, result="failed",
                reason=f"no live adapter for inbox {inbox_id}",
            )
            return
        if not platform_peer_id:
            await self._studio.ack_outbound(
                outbound_id, result="failed",
                reason="missing peer_platform_id",
            )
            return
        if not content:
            await self._studio.ack_outbound(
                outbound_id, result="sent",
            )
            return

        try:
            msg_id = await entry.adapter.send_text(platform_peer_id, content)
        except Exception as exc:
            logger.error("outbound %d send failed (inbox=%s): %s", outbound_id, inbox_id, exc)
            await self._studio.ack_outbound(
                outbound_id, result="failed", reason=str(exc)[:500]
            )
            return

        await self._studio.ack_outbound(
            outbound_id, result="sent", platform_msg_id=msg_id,
        )


def _redact(raw: Dict[str, str]) -> Dict[str, str]:
    return {k: ("***" if k.lower() == "password" else v) for k, v in raw.items()}
