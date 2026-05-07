"""Bridge adapter contract.

Each adapter wraps one platform (chat sandbox, wechat, feishu, ...). The
runtime calls these methods; the adapter knows how to talk to the actual
platform client / API.

Conventions:
- A "thread" is a 1:1 conversation. peer_id identifies the other side.
- Time is reported as ISO-8601 UTC.
- platform_msg_id must be unique within (thread, direction). It's used by
  Robot for de-duplication on /api/bridge/incoming.
- Adapters do NOT implement typing-speed delay. The runtime sleeps between
  outbound chunks and only then calls send_text().
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, List


@dataclass(frozen=True)
class IncomingMessage:
    peer_id: str
    peer_display_name: str
    platform_msg_id: str
    role: str          # 'self' | 'counterpart'
    content: str
    sent_at: datetime  # naive UTC


class Adapter:
    """Abstract base."""

    platform: str = ""

    async def login(self) -> str:
        """Authenticate and return platform_self_id (the streamer's id on this platform)."""
        raise NotImplementedError

    async def list_initial_messages(self, since_ms: int) -> List[IncomingMessage]:
        """Snapshot any messages we missed before the live stream started.

        Implementations may return [] if catch-up is not needed (e.g. first run
        on a fresh inbox). Robot dedups by external_id so it's safe to over-yield.
        """
        raise NotImplementedError

    async def stream_incoming(self) -> AsyncIterator[IncomingMessage]:
        """Yield new messages as they arrive (long-poll under the hood)."""
        raise NotImplementedError
        yield  # type: ignore[unreachable]  # pragma: no cover

    async def send_text(self, peer_id: str, content: str) -> str:
        """Send one text message to a peer; return platform_msg_id of the sent msg."""
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError
