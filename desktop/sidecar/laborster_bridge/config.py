"""Hardcoded endpoints + state-root resolution.

State root is a directory holding one sub-directory per Studio account::

    <state_root>/<account_id>/state.db

This module only knows the root and the path layout. Choosing which
account is active is a runtime decision (see ``commands._open_account``).
No defaults, no environment variables: the root comes from ``--state``
or in-REPL ``/state <path>``. The GUI binary supplies its own per-OS
default (see ``gui/app.py``) without breaking this invariant.
"""

from __future__ import annotations

import json
from pathlib import Path

# The Studio API endpoint is resolved at startup, not hardcoded. The only
# baked-in constants are a discovery anchor (a static JSON on the brand
# domain, which outlives any backend topology) and a seed fallback used
# before the first successful discovery. ``resolve_studio_base_url`` (called
# once from GUI/REPL startup) overwrites ``STUDIO_BASE_URL`` from discovery,
# caching the last-known-good under the state root. This lets the API host
# move server-side without ever rebuilding shipped clients.
#
# Headless (hosted-bridge) is exempt: it runs inside docker and gets its URL
# injected by ``--studio-url`` via ``set_studio_base_url``; it must never
# call discovery. Chat sandbox shares the same host (API at /api/chat/*).
DISCOVERY_URL = "https://laborster.com/.well-known/laborster-api.json"
DEFAULT_API_BASE = "https://api.laborster.com"
STUDIO_BASE_URL = DEFAULT_API_BASE


def set_studio_base_url(url: str) -> None:
    """Override the Studio endpoint. Headless mode only."""
    global STUDIO_BASE_URL
    STUDIO_BASE_URL = url.rstrip("/")


def _api_cache_file() -> Path | None:
    """Where last-known-good api_base is cached. None until a state root is set
    (discovery then runs without a persistent cache — memory only)."""
    return (state_root() / "api-config.json") if has_state_root() else None


def resolve_studio_base_url() -> str:
    """Discover and apply the live Studio API base. GUI/REPL startup only.

    Tries the discovery anchor (fast, no retry); on success applies it and
    caches it. On failure falls back to the last-known-good cache, then to
    the baked-in seed. Always sets ``STUDIO_BASE_URL`` and returns it.
    """
    global STUDIO_BASE_URL
    from .http import try_get_json  # local import: avoids import cycle at module load

    data = try_get_json(DISCOVERY_URL)
    base = None
    if isinstance(data, dict) and isinstance(data.get("api_base"), str):
        base = data["api_base"].strip().rstrip("/")

    cache = _api_cache_file()
    if base:
        STUDIO_BASE_URL = base
        if cache is not None:
            try:
                cache.write_text(json.dumps({"api_base": base}))
            except OSError:
                pass
        return STUDIO_BASE_URL

    if cache is not None and cache.exists():
        try:
            cached = json.loads(cache.read_text()).get("api_base")
            if isinstance(cached, str) and cached.strip():
                STUDIO_BASE_URL = cached.strip().rstrip("/")
                return STUDIO_BASE_URL
        except (OSError, ValueError):
            pass

    STUDIO_BASE_URL = DEFAULT_API_BASE
    return STUDIO_BASE_URL


_state_root: Path | None = None


class NoStateError(RuntimeError):
    """Raised when a command needs the state root but none is set."""


def set_state_root(path: str) -> Path:
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    if not p.is_dir():
        raise NoStateError(f"{p} is not a directory")
    global _state_root
    _state_root = p.resolve()
    return _state_root


def has_state_root() -> bool:
    return _state_root is not None


def state_root() -> Path:
    if _state_root is None:
        raise NoStateError(
            "no state directory — relaunch with --state <path> or run /state <path>"
        )
    return _state_root


def account_dir(account_id: str) -> Path:
    d = state_root() / account_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path(account_id: str) -> Path:
    return account_dir(account_id) / "state.db"
