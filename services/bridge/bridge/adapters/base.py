"""Bridge adapter contract.

Each adapter wraps one platform (chat sandbox, wechat, feishu, ...). The
runtime instantiates one adapter per inbox served by this Bridge daemon.

Conventions:
- A "thread" is a 1:1 conversation. peer_id identifies the other side.
- Time is reported as naive UTC datetime.
- platform_msg_id must be unique within (thread, direction). Studio
  de-duplicates on /api/bridge/incoming using external_id='live:<msg_id>'.
- Adapters do NOT implement typing-speed delay. The runtime sleeps between
  outbound chunks and only then calls send_text().
- One adapter instance owns one inbox. The runtime tags messages with
  inbox_id when forwarding to Studio (the adapter doesn't need to know its
  own inbox_id).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List


@dataclass(frozen=True)
class IncomingMessage:
    peer_id: str
    peer_display_name: str
    platform_msg_id: str
    role: str          # 'self' | 'counterpart'
    content: str
    sent_at: datetime  # naive UTC


class Adapter:
    platform: str = ""

    async def login(self) -> str:
        """Authenticate and return platform_self_id (the streamer's id on this platform)."""
        raise NotImplementedError

    async def list_initial_messages(self, since_ms: int) -> List[IncomingMessage]:
        """Snapshot any messages we missed before the live stream started."""
        raise NotImplementedError

    async def stream_incoming(self) -> AsyncIterator[IncomingMessage]:
        """Yield new messages as they arrive."""
        raise NotImplementedError
        yield  # type: ignore[unreachable]  # pragma: no cover

    async def send_text(self, peer_id: str, content: str) -> str:
        """Send one text to a peer; return its platform_msg_id."""
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Adapter factory registry — keyed by platform name.
# Each entry constructs an Adapter from the InboxConfig.raw dict.
# ---------------------------------------------------------------------------

AdapterFactory = "callable[[Dict[str, Any]], Adapter]"  # informational
_REGISTRY: Dict[str, Any] = {}


def register_adapter(platform: str, factory: Any) -> None:
    _REGISTRY[platform] = factory


def build_adapter(platform: str, raw_config: Dict[str, Any]) -> Adapter:
    factory = _REGISTRY.get(platform)
    if factory is None:
        raise SystemExit(f"unsupported platform: {platform!r}")
    return factory(raw_config)
