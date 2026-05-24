"""Per-worker Postgres LISTEN/NOTIFY broker.

One asyncpg connection per uvicorn worker holds every LISTEN this process
needs. Subscribers receive an ``asyncio.Queue``; NOTIFY → router → fan-out
to all queues registered for the channel. Slow consumers do not block
siblings — their queue overflows and the signal is dropped (a long-poll
that loses a wake-up just keeps waiting until the next NOTIFY or its
client-side timeout).

Channel naming (must be ≤ 63 bytes, Postgres ``NAMEDATALEN``):

  ob_<inbox_id>          outbound_messages for that inbox
  cm_<conversation_id>   new chat_messages for that conversation (chat svc)

Reference-counted LISTEN/UNLISTEN: the first subscriber to a channel
triggers ``LISTEN``, the last unsubscriber triggers ``UNLISTEN``. No lazy
recycle.

NOTIFY is emitted from the producer side via raw SQL inside the same
SQLAlchemy transaction:

    db.execute(text("SELECT pg_notify(:ch, '')").bindparams(ch=channel))
    db.commit()

so the notification is queued atomically and delivered on commit.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

logger = logging.getLogger(__name__)


def _asyncpg_dsn() -> str:
    url = os.environ["DATABASE_URL"]
    # SQLAlchemy DSN may include "+psycopg2"; asyncpg wants plain postgresql://
    return url.replace("postgresql+psycopg2://", "postgresql://")


class NotifyBroker:
    QUEUE_MAX = 64
    RECONNECT_DELAY_S = 1.0

    def __init__(self) -> None:
        self._conn: asyncpg.Connection | None = None
        self._subs: dict[str, set[asyncio.Queue[str]]] = {}
        self._lock = asyncio.Lock()
        self._closing = False
        self._reconnector: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await self._connect()

    async def stop(self) -> None:
        self._closing = True
        if self._reconnector and not self._reconnector.done():
            self._reconnector.cancel()
        if self._conn and not self._conn.is_closed():
            await self._conn.close()
        self._conn = None

    async def _connect(self) -> None:
        self._conn = await asyncpg.connect(_asyncpg_dsn())
        self._conn.add_termination_listener(self._on_disconnect)
        # Re-LISTEN whatever subscriptions survived a reconnect.
        for channel in list(self._subs):
            await self._conn.add_listener(channel, self._dispatch)

    def _on_disconnect(self, conn: asyncpg.Connection) -> None:
        if self._closing:
            return
        logger.warning("NotifyBroker: postgres connection terminated; reconnecting")
        self._reconnector = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        while not self._closing:
            try:
                await asyncio.sleep(self.RECONNECT_DELAY_S)
                await self._connect()
                logger.info("NotifyBroker: reconnected")
                return
            except Exception as exc:
                logger.warning("NotifyBroker: reconnect failed: %s", exc)

    def _dispatch(
        self,
        conn: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        for q in self._subs.get(channel, ()):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Lose the signal; consumer will catch up on its next poll.
                pass

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[asyncio.Queue[str]]:
        """Subscribe to ``channel`` for the lifetime of the ``async with`` block.

        Yields an ``asyncio.Queue`` that receives every NOTIFY payload.
        The first subscriber issues LISTEN; the last unsubscriber issues UNLISTEN.
        """
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=self.QUEUE_MAX)
        async with self._lock:
            first = channel not in self._subs
            self._subs.setdefault(channel, set()).add(q)
            if first and self._conn and not self._conn.is_closed():
                await self._conn.add_listener(channel, self._dispatch)
        try:
            yield q
        finally:
            async with self._lock:
                subs = self._subs.get(channel)
                if subs is not None:
                    subs.discard(q)
                    if not subs:
                        del self._subs[channel]
                        if self._conn and not self._conn.is_closed():
                            try:
                                await self._conn.remove_listener(channel, self._dispatch)
                            except Exception as exc:
                                logger.warning("UNLISTEN %s failed: %s", channel, exc)


_broker: NotifyBroker | None = None


def get_broker() -> NotifyBroker:
    if _broker is None:
        raise RuntimeError("NotifyBroker not initialized")
    return _broker


async def init_broker() -> None:
    global _broker
    _broker = NotifyBroker()
    await _broker.start()


async def shutdown_broker() -> None:
    global _broker
    if _broker is not None:
        await _broker.stop()
        _broker = None


# ---------------------------------------------------------------------------
# Channel name helpers — single source of truth, must match producer + consumer.
# ---------------------------------------------------------------------------

def outbound_channel(inbox_id: str) -> str:
    return f"ob_{inbox_id}"
