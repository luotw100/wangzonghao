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

# Single hardcoded endpoint. Chat sandbox shares the same host — its API is
# mounted at /api/chat/*. Runtime override exists only for the headless
# hosted-bridge path (set_studio_base_url, called from __main__ when
# --headless --studio-url is passed); GUI/REPL never call the setter, so
# end-user binaries always talk to this host.
STUDIO_BASE_URL = "https://api.laborster.com"


def set_studio_base_url(url: str) -> None:
    """Override the Studio endpoint. Headless mode only."""
    global STUDIO_BASE_URL
    STUDIO_BASE_URL = url.rstrip("/")


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
