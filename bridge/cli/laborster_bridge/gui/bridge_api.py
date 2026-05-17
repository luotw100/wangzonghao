"""js_api bridge: structured methods over commands.DISPATCH + a log stream.

Mutations (login/logout/channel add/rm) go through the existing command
handlers so daemon reconcile logic is reused verbatim. Display data
(status, account, channel list) is read straight from Events/state so
the frontend gets JSON instead of pre-rendered terminal lines.
"""

from __future__ import annotations

import json
import threading

from .. import commands, config, state
from ..events import Events


def _noprompt(_: str) -> str:
    # GUI never prompts; credentials always arrive as explicit args.
    # This placeholder exists only so Context is well-formed.
    return ""


class Api:
    def __init__(self) -> None:
        self._events = Events()
        self._ctx = commands.Context(self._events, _noprompt, _noprompt)
        self._window = None
        self._log_stop = threading.Event()
        self._log_thread: threading.Thread | None = None

    # --- lifecycle wiring (called from app.py) ---

    def attach_window(self, window) -> None:
        self._window = window

    def autostart(self) -> None:
        """Best-effort daemon start once the (fixed) state dir is set."""
        try:
            commands.autostart(self._ctx)
        except Exception as exc:  # never let a bad state file kill the UI
            self._events.log("core", "err", f"autostart 失败: {exc}")
        self._start_log_stream()

    def _start_log_stream(self) -> None:
        if self._log_thread is not None:
            return

        def pump() -> None:
            for ln in self._events.follow(self._log_stop):
                w = self._window
                if w is None:
                    continue
                try:
                    w.evaluate_js(f"window.pushLog({json.dumps(ln)})")
                except Exception:
                    pass

        self._log_thread = threading.Thread(
            target=pump, name="gui-log", daemon=True
        )
        self._log_thread.start()

    def shutdown(self) -> None:
        """Stop daemon + log stream. Idempotent; safe on crash paths."""
        self._log_stop.set()
        try:
            commands.cmd_quit(self._ctx, [])
        except Exception:
            pass

    # --- methods exposed to JS ---

    def account(self) -> dict:
        d = state.load()
        return {
            "logged_in": bool(d.get("studio_token")),
            "username": d.get("username"),
            "bridge_id": d.get("bridge_id"),
            "machine_id": d.get("machine_id"),
            "studio_url": config.STUDIO_BASE_URL,
            "has_channels": bool(d.get("channels")),
        }

    def status(self) -> dict:
        snap = self._events.snapshot()
        running = bool(self._ctx.runtime and self._ctx.runtime.is_running())
        return {"snapshot": snap, "running": running}

    def logs(self, n: int = 200) -> list:
        return self._events.tail(int(n))

    def login(self, username: str, password: str) -> dict:
        return commands.cmd_login(self._ctx, [username, password])

    def logout(self) -> dict:
        return commands.cmd_logout(self._ctx, [])

    def channel_list(self) -> list:
        return [
            {"index": i + 1, "username": c["username"]}
            for i, c in enumerate(state.load().get("channels", []))
        ]

    def channel_add(self, username: str, password: str) -> dict:
        return commands.cmd_channel(self._ctx, ["add", username, password])

    def channel_rm(self, index: int) -> dict:
        return commands.cmd_channel(self._ctx, ["rm", str(int(index))])

    def open_data_dir(self) -> dict:
        import subprocess
        import sys

        path = str(config.state_dir())
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            return {"error": str(exc)}
        return {"lines": [path]}
