"""Hardcoded endpoints and per-session state-directory resolution.

No defaults, no environment variables. The state directory comes from
exactly one of: the ``--state`` launch argument, or the in-REPL
``/state <path>`` command. Until one is provided, the CLI runs in
no-state mode and refuses every command that touches disk.
"""

from __future__ import annotations

from pathlib import Path

# The two service endpoints are fixed. There is no base-URL input anywhere.
CHAT_BASE_URL = "https://chat.laborster.com"
STUDIO_BASE_URL = "https://studio.laborster.com"

_state_dir: Path | None = None


class NoStateError(RuntimeError):
    """Raised when a command needs the state directory but none is set."""


def set_state_dir(path: str) -> Path:
    p = Path(path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    if not p.is_dir():
        raise NoStateError(f"{p} is not a directory")
    global _state_dir
    _state_dir = p.resolve()
    return _state_dir


def has_state_dir() -> bool:
    return _state_dir is not None


def state_dir() -> Path:
    if _state_dir is None:
        raise NoStateError(
            "no state directory — relaunch with --state <path> or run /state <path>"
        )
    return _state_dir


def state_file() -> Path:
    return state_dir() / "laborster.json"


def db_file() -> Path:
    return state_dir() / "messages.db"
