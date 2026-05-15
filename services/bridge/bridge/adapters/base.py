"""Bridge adapter contract.

Each adapter wraps one platform (chat sandbox, wechat, feishu, ...). The
runtime instantiates one adapter per inbox served by this Bridge daemon.

Conventions:
- A "thread" is a 1:1 conversation (or group). peer_id identifies the other
  side (group id for group chats).
- sender_id is the platform id of whoever sent the message. For 1:1 chats
  this is either the inbox owner (platform_self_id) or the peer. Storing
  sender_id instead of role keeps the contract neutral for group chats.
- Time is reported as UTC datetime (naive or aware — runtime normalizes).
- platform_msg_id is the platform's own message id for this adapter
  instance. It is used as an incremental scan cursor and is NOT expected
  to be stable across devices or imports. Studio uses msg_hash for dedup.
- For media messages, content is a platform-side storage key that the
  adapter knows how to download via download_media().
- One adapter instance owns one inbox. The runtime tags messages with
  inbox_id when storing locally (the adapter doesn't need to know its
  own inbox_id).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Dict, Optional


@dataclass(frozen=True)
class IncomingMessage:
    peer_id:            str
    peer_display_name:  str
    sender_id:          str          # platform id of the sender
    msg_type:           str          # 'text' | 'image' | 'audio' | 'video' | 'file'
    content:            str          # text→plain text; media→platform storage key
    sent_at:            datetime     # UTC (naive treated as UTC)
    platform_msg_id:    Optional[str] = None  # advisory; may be None


class Adapter:
    platform: str = ""

    async def login(self) -> str:
        """Authenticate and return platform_self_id (the account's id on this platform)."""
        raise NotImplementedError

    async def list_peers(self) -> list[dict[str, str]]:
        """Return currently known peers as [{"peer_platform_id": ..., "display_name": ...}].

        Called after login and periodically to refresh the peer directory reported to Studio.
        Default returns empty list; adapters should override.
        """
        return []

    async def scan(
        self,
        cursors: dict[str, str | None],
    ) -> AsyncIterator[IncomingMessage]:
        """Continuously yield messages — both historical and live — in one loop.

        cursors maps peer_id → last platform_msg_id already stored locally
        (None for peers seen for the first time). The adapter uses these to
        avoid re-fetching already-known messages and updates them in memory
        as it progresses.

        This method never returns; it loops forever until cancelled.
        """
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
        """
        raise NotImplementedError

    async def upload_and_send_media(
        self, peer_id: str, msg_type: str, data: bytes, filename: str, mime_type: str,
    ) -> str:
        """Upload binary to platform S3 and send a media message; return platform_msg_id."""
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Adapter factory registry — keyed by platform name.
# ---------------------------------------------------------------------------

AdapterFactory = "callable[[Dict[str, Any]], Adapter]"
_REGISTRY: Dict[str, Any] = {}


def register_adapter(platform: str, factory: Any) -> None:
    _REGISTRY[platform] = factory


def build_adapter(platform: str, raw_config: Dict[str, Any]) -> Adapter:
    factory = _REGISTRY.get(platform)
    if factory is None:
        raise SystemExit(f"unsupported platform: {platform!r}")
    return factory(raw_config)
