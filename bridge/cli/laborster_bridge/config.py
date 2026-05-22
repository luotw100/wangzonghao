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

from pathlib import Path

DEFAULT_CHAT_BASE_URL = "https://chat.laborster.com"
DEFAULT_STUDIO_BASE_URL = "https://studio.laborster.com"

# Module-level mutable: `/studio set <url>` rewrites STUDIO_BASE_URL for
# the running process (never persisted). Restart restores the default.
CHAT_BASE_URL = DEFAULT_CHAT_BASE_URL
STUDIO_BASE_URL = DEFAULT_STUDIO_BASE_URL

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
