"""Bridge adapter contract.

Each adapter wraps one platform (chat sandbox, wechat, feishu, ...). The
runtime instantiates one adapter per inbox served by this Bridge daemon.

Conventions:
- A "thread" is a 1:1 conversation. peer_id identifies the other side.
- Time is reported as UTC-aware datetime.
- platform_msg_id must be unique within (thread, direction). Studio
  de-duplicates on /api/bridge/incoming using external_id='live:<msg_id>'.
- Bridge is a pure forwarder: no pacing, no delay. Studio controls when each
  message becomes eligible for delivery.
- One adapter instance owns one inbox. The runtime tags messages with
  inbox_id when forwarding to Studio (the adapter doesn't need to know its
  own inbox_id).
- For media messages, content is a storage key (platform-specific on
  inbound, Studio S3 key on outbound in `send()`). The adapter handles
  download/upload between platform S3 and raw bytes.
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
    role: str              # 'self' | 'counterpart'
    msg_type: str          # 'text' | 'image' | 'audio' | 'video' | 'file'
    content: str            # text→plain text; media→platform storage key
    sent_at: datetime       # UTC-aware


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

    async def send(self, peer_id: str, msg_type: str, content: str) -> str:
        """Send one message to a peer; return its platform_msg_id.

        For text: content is plain text.
        For media: content has already been uploaded to platform S3 by the
        runtime; this method sends the platform message with the storage key.
        """
        if msg_type == "text":
            return await self.send_text(peer_id, content)
        raise NotImplementedError(f"send() not implemented for msg_type={msg_type}")

    async def send_text(self, peer_id: str, content: str) -> str:
        """Send one text message; return platform_msg_id. Default delegates to send()."""
        return await self.send(peer_id, "text", content)

    async def download_media(self, storage_key: str) -> tuple[bytes, str]:
        """Download media from the platform by its storage key.

        Returns (data, mime_type).
        Used by the runtime to pull media from the platform S3 so it can
        upload to Studio S3.
        """
        raise NotImplementedError

    async def upload_and_send_media(
        self, peer_id: str, msg_type: str, data: bytes, filename: str, mime_type: str,
    ) -> str:
        """Upload binary to platform S3 and send a media message; return platform_msg_id.

        The runtime downloads media from Studio S3, then calls this method
        to pipe the binary into the platform and send the message.
        """
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
