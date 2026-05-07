"""Bridge daemon runtime — multi-adapter, single connection to Studio.

One Bridge daemon runs N adapters in parallel (one per inbox listed in the
TOML config that Studio also confirms). All adapters' incoming streams are
multiplexed into one outbound POST queue; one outbound long-poll task
fan-outs to the right adapter based on inbox_id.

Loops:
- heartbeat_loop: pings Studio every N seconds; receives current
  authoritative inbox set, reconciles adapters (start new / stop dropped).
- per-adapter inbound loops: stream incoming → tag with inbox_id → push
  to a shared queue → batched POST to /api/bridge/incoming.
- inbound_pump_loop: drains the shared queue with brief coalescing.
- outbound_loop: long-polls /api/bridge/outbound (returns rows for ALL
  inboxes under this bridge), dispatches each to its inbox's adapter
  with typing-speed delay between chunks.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from bridge.adapters.base import Adapter, IncomingMessage, build_adapter
from bridge.config import BridgeConfig, InboxConfig, find_inbox
from bridge.studio_client import StudioClient

logger = logging.getLogger(__name__)


# Outbound pacing
TYPING_CHARS_PER_SECOND = 6.0
TYPING_MIN_DELAY = 1.0
TYPING_MAX_DELAY = 12.0
THINK_DELAY = 1.5

HEARTBEAT_INTERVAL = 15.0
INBOUND_BATCH_LINGER = 0.4
INBOUND_BATCH_MAX = 30
OUTBOUND_LONG_POLL_TIMEOUT = 30


@dataclass
class _AdapterEntry:
    inbox_id: str
    adapter: Adapter
    platform_self_id: Optional[str]
    inbound_task: Optional[asyncio.Task[Any]]


class BridgeRuntime:
    def __init__(self, *, studio: StudioClient, config: BridgeConfig) -> None:
        self._studio = studio
        self._config = config
        self._adapters: Dict[str, _AdapterEntry] = {}
        self._inbound_queue: asyncio.Queue[Tuple[str, IncomingMessage]] = asyncio.Queue()
        self._cursor: int = 0
        self._stop = asyncio.Event()
        self._loop_tasks: List[asyncio.Task[Any]] = []

    async def run(self) -> None:
        # Spin up an adapter per inbox declared in the local config and log in
        # to obtain platform_self_id. We hand the resulting list to handshake
        # so Studio can rebind Inbox.bridge_id → us and stamp platform_self_id.
        for inbox_cfg in self._config.inboxes:
            await self._spawn_adapter(inbox_cfg)

        info = await self._studio.handshake(
            hostname=self._config.hostname,
            inboxes=[
                {"inbox_id": e.inbox_id, "platform_self_id": e.platform_self_id or ""}
                for e in self._adapters.values()
                if e.platform_self_id is not None
            ],
        )
        self._cursor = int(info.get("cursor", 0))
        served_ids = {ix["id"] for ix in info.get("inboxes", [])}
        logger.info(
            "handshake ok: bridge=%s account=%s served=%d cursor=%d",
            info.get("bridge_id"), info.get("account_id"), len(served_ids), self._cursor,
        )

        # Drop adapters Studio refused to bind (e.g. inbox_id is bound to a
        # different bridge in the UI, or doesn't belong to this account).
        for inbox_id in list(self._adapters.keys()):
            if inbox_id not in served_ids:
                logger.warning("inbox %s not served by Studio; dropping local adapter", inbox_id)
                await self._stop_adapter(inbox_id)

        # Push catch-up batch from each adapter (idempotent on Studio side).
        await self._push_initial_catchup()

        loop = asyncio.get_running_loop()
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

    async def _spawn_adapter(self, inbox_cfg: InboxConfig) -> None:
        adapter = build_adapter(inbox_cfg.platform, inbox_cfg.raw)
        try:
            platform_self_id = await adapter.login()
        except Exception as exc:
            logger.error("adapter login failed for inbox %s (%s): %s",
                         inbox_cfg.inbox_id, inbox_cfg.platform, exc)
            with suppress(Exception):
                await adapter.close()
            return
        entry = _AdapterEntry(
            inbox_id=inbox_cfg.inbox_id,
            adapter=adapter,
            platform_self_id=platform_self_id,
            inbound_task=None,
        )
        loop = asyncio.get_running_loop()
        entry.inbound_task = loop.create_task(
            self._adapter_inbound_loop(inbox_cfg.inbox_id, adapter),
            name=f"inbound-{inbox_cfg.inbox_id}",
        )
        self._adapters[inbox_cfg.inbox_id] = entry
        logger.info("adapter up: inbox=%s platform=%s self=%s",
                    inbox_cfg.inbox_id, inbox_cfg.platform, platform_self_id)

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
            # Coalesce briefly
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

    # --- heartbeat + sync ----------------------------------------------

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                resp = await self._studio.heartbeat()
                served = {ix["id"] for ix in resp.get("inboxes", [])}
                await self._reconcile_adapters(served)
            except Exception as exc:
                logger.warning("heartbeat failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                pass

    async def _reconcile_adapters(self, served_ids: set[str]) -> None:
        """Stop adapters Studio no longer serves; (re)start ones that appeared."""
        # Stop dropped
        for inbox_id in list(self._adapters.keys()):
            if inbox_id not in served_ids:
                logger.info("inbox %s no longer served; stopping adapter", inbox_id)
                await self._stop_adapter(inbox_id)
        # Start newly-served ones (must have local config)
        for inbox_id in served_ids:
            if inbox_id in self._adapters:
                continue
            ic = find_inbox(self._config, inbox_id)
            if ic is None:
                logger.warning(
                    "inbox %s served by Studio but missing from local TOML; "
                    "add an [[inboxes]] block and reload bridge", inbox_id,
                )
                continue
            await self._spawn_adapter(ic)

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
        chunks = item.get("chunks", [])

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

        first = True
        last_msg_id: Optional[str] = None
        try:
            for chunk in chunks:
                content = str(chunk.get("content", "")).strip()
                if not content:
                    continue
                delay = self._chunk_delay(content, is_first=first)
                first = False
                await asyncio.sleep(delay)
                last_msg_id = await entry.adapter.send_text(platform_peer_id, content)
        except Exception as exc:
            logger.error("outbound %d send failed (inbox=%s): %s", outbound_id, inbox_id, exc)
            await self._studio.ack_outbound(
                outbound_id, result="failed", reason=str(exc)[:500]
            )
            return

        await self._studio.ack_outbound(
            outbound_id, result="sent", platform_msg_id=last_msg_id,
        )

    @staticmethod
    def _chunk_delay(content: str, *, is_first: bool) -> float:
        n = max(1, len(content))
        delay = n / TYPING_CHARS_PER_SECOND
        if is_first:
            delay += THINK_DELAY
        return max(TYPING_MIN_DELAY, min(TYPING_MAX_DELAY, delay))
