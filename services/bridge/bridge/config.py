"""Bridge config — Cloudflare-tunnel-style.

The Bridge daemon reads a TOML file at startup. The file contains:
- daemon-level: studio_url, token, hostname (optional)
- per-inbox blocks: which inboxes this daemon serves + the platform
  credentials Studio doesn't see (passwords, base URLs, etc.)

Studio is the source of truth for "which inbox is bound to which bridge"
(via Inbox.bridge_id, set in the UI). The TOML provides the credentials
keyed by inbox_id; the daemon only spawns adapters for inboxes Studio
actually returns from /handshake or /heartbeat.

Format (see ~/.bridge/config.toml.example):

    [bridge]
    studio_url = "http://localhost:23457"
    token = "..."
    hostname = "alice-mbp"   # optional

    [[inboxes]]
    inbox_id = "ib_xxx"
    platform = "chat"
    chat_base_url = "http://localhost:23456"
    chat_username = "alice"
    chat_password = "Alice123"

    [[inboxes]]
    inbox_id = "ib_yyy"
    platform = "wechat"
    # adapter-specific keys go here; chat needs creds, wechat hooks the
    # running desktop client and needs nothing extra.
"""

from __future__ import annotations

import os
import socket
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class InboxConfig:
    inbox_id: str
    platform: str
    raw: Dict[str, Any]   # adapter-specific extras (chat_base_url, chat_username, ...)


@dataclass(frozen=True)
class BridgeConfig:
    studio_url: str
    token: str
    hostname: str
    inboxes: List[InboxConfig]


def _load_toml(path: Path) -> Dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def load_config(path: Path) -> BridgeConfig:
    if not path.exists():
        raise SystemExit(f"bridge config not found: {path}")
    raw = _load_toml(path)
    bridge = raw.get("bridge") or {}
    studio_url = bridge.get("studio_url")
    token = bridge.get("token")
    if not studio_url or not token:
        raise SystemExit("config [bridge] requires studio_url + token")

    hostname = bridge.get("hostname") or os.environ.get("BRIDGE_HOSTNAME") or socket.gethostname()
    inboxes_raw = raw.get("inboxes") or []
    inboxes: List[InboxConfig] = []
    for entry in inboxes_raw:
        inbox_id = entry.get("inbox_id")
        platform = entry.get("platform")
        if not inbox_id or not platform:
            raise SystemExit(f"each [[inboxes]] block requires inbox_id + platform; got {entry!r}")
        inboxes.append(InboxConfig(
            inbox_id=str(inbox_id),
            platform=str(platform),
            raw=entry,
        ))
    return BridgeConfig(
        studio_url=str(studio_url).rstrip("/"),
        token=str(token),
        hostname=str(hostname),
        inboxes=inboxes,
    )


def default_config_path() -> Path:
    """Look for the config in this order:
    1. $BRIDGE_CONFIG (explicit override)
    2. ./bridge.toml (cwd, useful for docker compose mount)
    3. ~/.bridge/config.toml
    """
    explicit = os.environ.get("BRIDGE_CONFIG")
    if explicit:
        return Path(explicit)
    cwd_path = Path.cwd() / "bridge.toml"
    if cwd_path.exists():
        return cwd_path
    return Path.home() / ".bridge" / "config.toml"


def find_inbox(cfg: BridgeConfig, inbox_id: str) -> Optional[InboxConfig]:
    for ic in cfg.inboxes:
        if ic.inbox_id == inbox_id:
            return ic
    return None
