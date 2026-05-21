"""js_api bridge: structured methods over commands.* + a log stream.

Mutations (login/logout/channel add/rm) go through the command handlers
so daemon reconcile logic is reused verbatim. Display data (status,
account, channel list) is read straight from Events/state so the
frontend gets JSON instead of pre-rendered terminal lines.
"""

from __future__ import annotations

import json
import threading

from .. import adapters, commands, config, state
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
        """List bound channels with resolved platform_self_id for display.

        Each item: {index, platform, self_id, label}. ``self_id`` is None
        if the credential is currently unreachable (network or auth).
        """
        out: list[dict] = []
        for i, c in enumerate(state.load().get("channels", [])):
            platform = c.get("platform", "?")
            self_id = None
            try:
                self_id = (
                    adapters.get(platform).build(c["credential"]).platform_self_id
                )
            except Exception:
                self_id = None
            label = f"{platform}/{self_id}" if self_id else f"{platform}/-"
            out.append(
                {
                    "index": i + 1,
                    "platform": platform,
                    "self_id": self_id,
                    "label": label,
                }
            )
        return out

    def channel_add(self, username: str, password: str) -> dict:
        """Chat shortcut: single-shot username+password login flow.

        Kept as a thin wrapper so the existing GUI form keeps working.
        For non-chat platforms, prefer the generic begin/submit/poll API
        (to be added when the second platform lands).
        """
        return self.channel_add_generic(
            "chat", {"username": username, "password": password}
        )

    def channel_add_generic(self, platform: str, answers: dict) -> dict:
        """Run a single-step LoginFlow synchronously.

        Returns a normal {lines|error} dict. Only supports flows whose
        first step is a PromptInput that goes straight to Done after one
        submit (chat, and any future platform with a single-form login).
        Multi-step flows (QR / OAuth / OTP) need a stateful begin/submit
        API; that's the next iteration.
        """
        try:
            factory = adapters.get(platform)
        except KeyError as exc:
            return {"error": str(exc)}
        try:
            flow = factory.begin_login()
        except adapters.TransientError as exc:
            return {"error": f"启动登录失败: {exc}"}

        step = flow.current()
        if not isinstance(step, adapters.PromptInput):
            return {
                "error": f"{platform} 登录不是单步流，GUI 暂未支持多步登录"
            }
        try:
            step = flow.submit(answers)
        except adapters.TransientError as exc:
            return {"error": f"网络错误: {exc}"}

        if isinstance(step, adapters.PromptInput):
            return {"error": step.error or "登录失败"}
        if isinstance(step, adapters.Failed):
            return {"error": step.reason}
        if isinstance(step, adapters.Done):
            return commands._persist_channel(self._ctx, platform, step.credential)
        return {"error": f"未知 step 类型: {type(step).__name__}"}

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
