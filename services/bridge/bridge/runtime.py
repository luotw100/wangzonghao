"""Bridge daemon runtime — producer-consumer inbound model.

Inbound (platform → Bridge → Studio):
  Producer per inbox: adapter.scan() → INSERT local_messages (dedup by local_hash)
  Consumer (global):  read unsent rows → check-or-presign for media → push incoming

Outbound (Studio → Bridge → platform): unchanged from prior design.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import mimetypes
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bridge.adapters.base import Adapter, IncomingMessage, build_adapter
from bridge.local_store import LocalMessage, LocalStore, canonical_sent_at, compute_local_hash
from bridge.state import BridgeState
from bridge.studio_client import StudioClient

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 15.0
OUTBOUND_LONG_POLL_TIMEOUT = 30
CONSUMER_SLEEP = 1.0         # seconds to sleep when no unsent messages
CONSUMER_BATCH = 50          # messages per consumer loop iteration
ANNOUNCE_INTERVAL = 60.0     # how often bridge reports peer list to Studio
ACTIVE_PEERS_INTERVAL = 10.0 # how often bridge refreshes active-peers from Studio


@dataclass(frozen=True)
class InboxClaim:
    platform: str
    raw: Dict[str, str]


@dataclass
class _AdapterEntry:
    inbox_id: str
    platform: str
    platform_self_id: str
    adapter: Adapter
    producer_task: Optional[asyncio.Task[Any]] = None


class BridgeRuntime:
    def __init__(
        self,
        *,
        studio: StudioClient,
        state: BridgeState,
        claims: List[InboxClaim],
        store: LocalStore,
        media_cache_dir: Path,
    ) -> None:
        self._studio = studio
        self._state = state
        self._claims = claims
        self._store = store
        self._media_cache_dir = media_cache_dir
        self._adapters: Dict[str, _AdapterEntry] = {}
        self._cursor: int = 0
        self._stop = asyncio.Event()
        self._loop_tasks: List[asyncio.Task[Any]] = []
        self._media_sem = asyncio.Semaphore(5)
        self._active_peers: frozenset[tuple[str, str]] = frozenset()

    async def run(self) -> None:
        # 1) Login each platform claim.
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

        # 2) Connect to Studio.
        handshake_payload = [
            {"platform": c.platform, "platform_self_id": self_id}
            for (c, _, self_id) in prelogged
        ]
        info = await self._connect(handshake_payload)
        if info is None:
            for _, adapter, _ in prelogged:
                with suppress(Exception):
                    await adapter.close()
            return
        self._state.machine_id = str(info["machine_id"])
        self._state.token = str(info["token"])
        self._cursor = int(info.get("cursor", 0))
        served_by_key = {
            (i["platform"], i["platform_self_id"]): i for i in info.get("inboxes", [])
        }
        logger.info(
            "handshake ok: bridge=%s machine_id=%s account=%s served=%d cursor=%d",
            info.get("bridge_id"), self._state.machine_id,
            info.get("account_id"), len(served_by_key), self._cursor,
        )

        # 3) Initialise local store.
        self._store.migrate()

        # 4) Bind adapters and start producers.
        loop = asyncio.get_running_loop()
        for claim, adapter, self_id in prelogged:
            assigned = served_by_key.get((claim.platform, self_id))
            if not assigned:
                logger.warning("platform=%s self=%s not served by Studio; dropping",
                               claim.platform, self_id)
                with suppress(Exception):
                    await adapter.close()
                continue
            inbox_id = assigned["id"]
            entry = _AdapterEntry(
                inbox_id=inbox_id,
                platform=claim.platform,
                platform_self_id=self_id,
                adapter=adapter,
            )
            cursors = self._store.get_cursors(inbox_id)
            entry.producer_task = loop.create_task(
                self._producer_loop(inbox_id, adapter, self_id, cursors),
                name=f"producer-{inbox_id}",
            )
            self._adapters[inbox_id] = entry
            logger.info("adapter up: inbox=%s platform=%s self=%s",
                        inbox_id, claim.platform, self_id)

        # 5) Main loops.
        self._loop_tasks = [
            loop.create_task(self._heartbeat_loop(), name="heartbeat"),
            loop.create_task(self._consumer_loop(), name="consumer"),
            loop.create_task(self._outbound_loop(), name="outbound"),
            loop.create_task(self._announce_loop(), name="announce"),
            loop.create_task(self._active_peers_loop(), name="active-peers"),
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

    # ------------------------------------------------------------------
    # Studio connection
    # ------------------------------------------------------------------

    async def _connect(self, handshake_payload: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        if self._state.token:
            self._studio.token = self._state.token
            try:
                hb = await self._studio.try_heartbeat()
            except Exception:
                hb = None
            if hb is not None:
                served_ids = {(i["platform"], i["platform_self_id"]) for i in hb.get("inboxes", [])}
                claim_ids = {(c["platform"], c["platform_self_id"]) for c in handshake_payload}
                if not claim_ids - served_ids:
                    logger.info("token reuse ok: machine_id=%s", self._state.machine_id)
                    hb.setdefault("machine_id", self._state.machine_id)
                    hb.setdefault("token", self._state.token)
                    hb.setdefault("cursor", 0)
                    return hb
                logger.info("new inbox claims detected, skipping token reuse")
        try:
            return await self._studio.handshake(
                machine_id=self._state.machine_id, inboxes=handshake_payload,
            )
        except Exception as exc:
            logger.error("handshake failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Adapter lifecycle
    # ------------------------------------------------------------------

    async def _stop_adapter(self, inbox_id: str) -> None:
        entry = self._adapters.pop(inbox_id, None)
        if not entry:
            return
        if entry.producer_task:
            entry.producer_task.cancel()
            with suppress(asyncio.CancelledError):
                await entry.producer_task
        with suppress(Exception):
            await entry.adapter.close()
        logger.info("adapter down: inbox=%s", inbox_id)

    async def _stop_all_adapters(self) -> None:
        for inbox_id in list(self._adapters.keys()):
            await self._stop_adapter(inbox_id)

    # ------------------------------------------------------------------
    # Producer loop (one per inbox)
    # ------------------------------------------------------------------

    async def _producer_loop(
        self,
        inbox_id: str,
        adapter: Adapter,
        platform_self_id: str,
        cursors: dict[str, str | None],
    ) -> None:
        try:
            async for msg in adapter.scan(cursors):
                local_msg = await self._to_local_message(inbox_id, adapter, msg)
                if local_msg is None:
                    continue
                inserted = self._store.insert_message(local_msg)
                if not inserted:
                    logger.debug("producer: local dedup inbox=%s peer=%s", inbox_id, msg.peer_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("producer crashed inbox=%s: %s", inbox_id, exc)

    async def _to_local_message(
        self,
        inbox_id: str,
        adapter: Adapter,
        msg: IncomingMessage,
    ) -> Optional[LocalMessage]:
        sent_at_str = canonical_sent_at(msg.sent_at)

        if msg.msg_type == "text":
            content = msg.content
            mime_type = None
        else:
            # Download from platform, compute sha256, cache locally.
            async with self._media_sem:
                try:
                    data, mime_type = await adapter.download_media(msg.content)
                except Exception as exc:
                    logger.error("media download failed inbox=%s peer=%s: %s",
                                 inbox_id, msg.peer_id, exc)
                    return None
            sha256hex = hashlib.sha256(data).hexdigest()
            cache_path = self._media_cache_dir / sha256hex
            if not cache_path.exists():
                cache_path.write_bytes(data)
            content = f"sha256:{sha256hex}"

        local_hash = compute_local_hash(
            inbox_id, msg.peer_id, msg.sender_id, sent_at_str, msg.msg_type, content,
        )
        return LocalMessage(
            inbox_id=inbox_id,
            peer_id=msg.peer_id,
            peer_display_name=msg.peer_display_name,
            platform_msg_id=msg.platform_msg_id,
            sender_id=msg.sender_id,
            sent_at=sent_at_str,
            msg_type=msg.msg_type,
            content=content,
            mime_type=mime_type,
            local_hash=local_hash,
        )

    # ------------------------------------------------------------------
    # Consumer loop (global)
    # ------------------------------------------------------------------

    async def _consumer_loop(self) -> None:
        while not self._stop.is_set():
            batch = self._store.get_unsent(limit=CONSUMER_BATCH, active_peers=self._active_peers)
            if not batch:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=CONSUMER_SLEEP)
                except asyncio.TimeoutError:
                    pass
                continue

            payload: List[Dict[str, Any]] = []
            payload_ids: List[int] = []
            permanent_skip_ids: List[int] = []

            for msg in batch:
                assert msg.id is not None
                try:
                    content, content_hash = await self._resolve_content(msg)
                    if content is None:
                        # Permanently unresolvable (e.g. cache deleted + platform gone).
                        permanent_skip_ids.append(msg.id)
                        continue
                    payload.append(self._to_incoming_payload(msg, content, content_hash))
                    payload_ids.append(msg.id)
                except Exception as exc:
                    # Transient failure — leave unsent, retry next round.
                    logger.warning("consumer: resolve failed id=%s: %s", msg.id, exc)

            for mid in permanent_skip_ids:
                self._store.mark_sent(mid)

            if not payload:
                continue

            try:
                res = await self._studio.push_incoming(payload)
                logger.info(
                    "consumer: pushed %d accepted=%s deduped=%s rejected=%s",
                    len(payload), res.get("accepted"), res.get("deduped"), res.get("rejected"),
                )
                for mid in payload_ids:
                    self._store.mark_sent(mid)
            except Exception as exc:
                logger.warning("consumer: push failed, will retry: %s", exc)

    async def _resolve_content(
        self, msg: LocalMessage
    ) -> Tuple[Optional[str], Optional[str]]:
        """Return (content_for_protocol, content_hash_for_protocol).

        For text: (plain_text, None).
        For media: (studio_storage_key, "sha256:xxx") — uploads if needed.
        Returns (None, None) if the message must be skipped permanently.
        """
        if msg.msg_type == "text":
            return msg.content, None

        content_hash = msg.content  # "sha256:xxx"
        sha256hex = content_hash.removeprefix("sha256:")
        ext = mimetypes.guess_extension(msg.mime_type or "") or ".bin"
        filename = f"media{ext}"
        mime_type = msg.mime_type or "application/octet-stream"

        status, storage_key, upload_url = await self._studio.check_or_presign_media(
            content_hash, filename, mime_type,
        )
        if status == "exists":
            return storage_key, content_hash

        # Need to upload.
        cache_path = self._media_cache_dir / sha256hex
        if not cache_path.exists():
            # Cache was manually deleted; try to re-download from platform.
            entry = self._adapters.get(msg.inbox_id)
            if entry is None:
                logger.warning(
                    "consumer: media cache missing and no adapter for inbox=%s; skipping id=%s",
                    msg.inbox_id, msg.id,
                )
                return None, None
            try:
                data, _ = await entry.adapter.download_media(
                    # We no longer have the platform key; the content field is now a sha256.
                    # This re-download path is best-effort only.
                    sha256hex,
                )
                cache_path.write_bytes(data)
            except Exception as exc:
                logger.warning(
                    "consumer: re-download failed id=%s: %s; skipping", msg.id, exc,
                )
                return None, None

        data = cache_path.read_bytes()
        r = await self._studio.http.put(
            upload_url, content=data, headers={"Content-Type": mime_type},
        )
        r.raise_for_status()
        return storage_key, content_hash

    @staticmethod
    def _to_incoming_payload(
        msg: LocalMessage,
        content: str,
        content_hash: Optional[str],
    ) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "inbox_id": msg.inbox_id,
            "peer_platform_id": msg.peer_id,
            "peer_display_name": msg.peer_display_name,
            "platform_msg_id": msg.platform_msg_id,
            "sender_id": msg.sender_id,
            "msg_type": msg.msg_type,
            "content": content,
            "sent_at": msg.sent_at,
        }
        if content_hash is not None:
            d["content_hash"] = content_hash
        return d

    # ------------------------------------------------------------------
    # Peer directory — announce known peers to Studio
    # ------------------------------------------------------------------

    async def _announce_loop(self) -> None:
        while not self._stop.is_set():
            for inbox_id, entry in list(self._adapters.items()):
                try:
                    peers = await entry.adapter.list_peers()
                    if peers:
                        await self._studio.report_peers(inbox_id, peers)
                        logger.debug("announced %d peers for inbox=%s", len(peers), inbox_id)
                except Exception as exc:
                    logger.warning("announce failed inbox=%s: %s", inbox_id, exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=ANNOUNCE_INTERVAL)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Active peers — poll Studio for which peers are taken over
    # ------------------------------------------------------------------

    async def _active_peers_loop(self) -> None:
        while not self._stop.is_set():
            try:
                peers = await self._studio.get_active_peers()
                self._active_peers = frozenset(
                    (p["inbox_id"], p["peer_platform_id"]) for p in peers
                )
                logger.debug("active peers refreshed: %d", len(self._active_peers))
            except Exception as exc:
                logger.warning("active peers refresh failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=ACTIVE_PEERS_INTERVAL)
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                resp = await self._studio.heartbeat()
                served = {ix["id"] for ix in resp.get("inboxes", [])}
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

    # ------------------------------------------------------------------
    # Outbound (unchanged logic)
    # ------------------------------------------------------------------

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
        msg_type = str(item.get("msg_type", "text"))
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
                outbound_id, result="failed", reason="missing peer_platform_id",
            )
            return
        if not content:
            await self._studio.ack_outbound(outbound_id, result="sent")
            return

        try:
            if msg_type == "text":
                msg_id = await entry.adapter.send_text(platform_peer_id, content)
            else:
                data, mime_type = await self._download_studio_media(content)
                if data is None:
                    await self._studio.ack_outbound(
                        outbound_id, result="failed",
                        reason=f"failed to download Studio media {content}",
                    )
                    return
                ext = mimetypes.guess_extension(mime_type) or ".bin"
                msg_id = await entry.adapter.upload_and_send_media(
                    platform_peer_id, msg_type, data, f"media{ext}", mime_type,
                )
        except Exception as exc:
            logger.error("outbound %d send failed inbox=%s: %s", outbound_id, inbox_id, exc)
            await self._studio.ack_outbound(
                outbound_id, result="failed", reason=str(exc)[:500],
            )
            return
        await self._studio.ack_outbound(outbound_id, result="sent", platform_msg_id=msg_id)

    async def _download_studio_media(self, storage_key: str) -> Tuple[Optional[bytes], str]:
        try:
            url = await self._studio.get_media_url(storage_key)
            r = await self._studio.http.get(url, follow_redirects=True)
            r.raise_for_status()
            return r.content, r.headers.get("content-type", "application/octet-stream")
        except Exception as exc:
            logger.error("failed to download Studio media %s: %s", storage_key, exc)
            return None, ""


def _redact(raw: Dict[str, str]) -> Dict[str, str]:
    return {k: ("***" if k.lower() == "password" else v) for k, v in raw.items()}
