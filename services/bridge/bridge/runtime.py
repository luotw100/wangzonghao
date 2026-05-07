"""Bridge runtime — three concurrent loops + handshake.

The bridge's only job at runtime is to act as a courier between platform A
(via an Adapter) and Robot (C). It owns no policy, no LLM, no persona.

Loops:
- heartbeat_loop: tells Robot "I'm alive" so the inbox stays online in UI.
- inbound_loop: streams messages from the adapter, batches them, POSTs to
  /api/bridge/incoming. Dedup is Robot's job (external_id collisions).
- outbound_loop: long-polls /api/bridge/outbound, sends each chunk via
  the adapter with a typing-speed delay, ACKs the outbound.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from bridge.adapters.base import Adapter, IncomingMessage
from bridge.robot_client import RobotClient

logger = logging.getLogger(__name__)


# Outbound pacing: simulate typing speed. Each chunk waits chars/CPS seconds
# (clamped) before sending; the first chunk also waits a small think-pause.
TYPING_CHARS_PER_SECOND = 6.0
TYPING_MIN_DELAY = 1.0
TYPING_MAX_DELAY = 12.0
THINK_DELAY = 1.5

HEARTBEAT_INTERVAL = 15.0
INBOUND_BATCH_LINGER = 0.4   # wait briefly to coalesce multi-msg arrivals
INBOUND_BATCH_MAX = 30
OUTBOUND_LONG_POLL_TIMEOUT = 30


@dataclass(frozen=True)
class RuntimeOptions:
    hostname: str


class BridgeRuntime:
    def __init__(self, *, robot: RobotClient, adapter: Adapter, options: RuntimeOptions) -> None:
        self._robot = robot
        self._adapter = adapter
        self._options = options
        self._cursor: int = 0
        self._tasks: List[asyncio.Task[Any]] = []
        self._stop = asyncio.Event()

    async def run(self) -> None:
        platform_self_id = await self._adapter.login()
        info = await self._robot.handshake(
            hostname=self._options.hostname,
            platform_self_id=platform_self_id,
        )
        self._cursor = int(info.get("last_seq", 0))
        logger.info("handshake ok: inbox=%s account=%s last_seq=%s",
                    info.get("inbox_id"), info.get("account_id"), self._cursor)

        # Push catch-up batch from the adapter (idempotent on Robot side).
        catchup = await self._adapter.list_initial_messages(since_ms=0)
        if catchup:
            await self._push_batch(catchup)

        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self._heartbeat_loop(), name="heartbeat"),
            loop.create_task(self._inbound_loop(), name="inbound"),
            loop.create_task(self._outbound_loop(), name="outbound"),
        ]
        try:
            await self._stop.wait()
        finally:
            for t in self._tasks:
                t.cancel()
            for t in self._tasks:
                with suppress(asyncio.CancelledError):
                    await t

    def stop(self) -> None:
        self._stop.set()

    # --- helpers --------------------------------------------------------

    @staticmethod
    def _to_payload(m: IncomingMessage) -> Dict[str, Any]:
        return {
            "peer_platform_id": m.peer_id,
            "peer_display_name": m.peer_display_name,
            "platform_msg_id": m.platform_msg_id,
            "role": m.role,
            "content": m.content,
            "sent_at": m.sent_at.isoformat(),
        }

    async def _push_batch(self, batch: List[IncomingMessage]) -> None:
        if not batch:
            return
        try:
            res = await self._robot.push_incoming([self._to_payload(m) for m in batch])
            logger.info("inbound: pushed %d (accepted=%s deduped=%s)",
                        len(batch), res.get("accepted"), res.get("deduped"))
        except Exception as exc:
            logger.error("inbound push failed: %s", exc)

    # --- loops ----------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._robot.heartbeat()
            except Exception as exc:
                logger.warning("heartbeat failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                pass

    async def _inbound_loop(self) -> None:
        batch: List[IncomingMessage] = []
        try:
            async for msg in self._adapter.stream_incoming():
                batch.append(msg)
                if len(batch) >= INBOUND_BATCH_MAX:
                    await self._push_batch(batch)
                    batch = []
                    continue
                # Linger briefly to coalesce simultaneous arrivals
                try:
                    await asyncio.wait_for(asyncio.sleep(INBOUND_BATCH_LINGER), timeout=INBOUND_BATCH_LINGER)
                except asyncio.TimeoutError:
                    pass
                if batch:
                    await self._push_batch(batch)
                    batch = []
        except asyncio.CancelledError:
            if batch:
                await self._push_batch(batch)
            raise

    async def _outbound_loop(self) -> None:
        while not self._stop.is_set():
            try:
                items = await self._robot.long_poll_outbound(
                    cursor=self._cursor, timeout_seconds=OUTBOUND_LONG_POLL_TIMEOUT,
                )
            except Exception as exc:
                logger.warning("outbound long-poll failed: %s", exc)
                await asyncio.sleep(2)
                continue

            for item in items:
                seq = int(item["seq"])
                if seq <= self._cursor:
                    continue  # already saw this
                await self._dispatch_outbound(item)
                self._cursor = seq

    async def _dispatch_outbound(self, item: Dict[str, Any]) -> None:
        outbound_id = item["id"]
        platform_peer_id = item.get("peer_platform_id")
        chunks = item.get("chunks", [])
        if not platform_peer_id:
            await self._robot.ack_outbound(
                outbound_id, result="failed",
                reason=f"missing peer_platform_id for contact {item.get('contact_id')}",
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
                last_msg_id = await self._adapter.send_text(platform_peer_id, content)
        except Exception as exc:
            logger.error("outbound %s send failed: %s", outbound_id, exc)
            await self._robot.ack_outbound(outbound_id, result="failed", reason=str(exc)[:500])
            return

        await self._robot.ack_outbound(outbound_id, result="sent", platform_msg_id=last_msg_id)

    @staticmethod
    def _chunk_delay(content: str, *, is_first: bool) -> float:
        n = max(1, len(content))
        delay = n / TYPING_CHARS_PER_SECOND
        if is_first:
            delay += THINK_DELAY
        if delay < TYPING_MIN_DELAY:
            delay = TYPING_MIN_DELAY
        if delay > TYPING_MAX_DELAY:
            delay = TYPING_MAX_DELAY
        return delay
