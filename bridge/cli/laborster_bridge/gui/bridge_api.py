"""js_api bridge: structured methods over commands.* + a log stream.

Mutations (login/logout/channel add/rm/account use) go through the
command handlers so the daemon reconcile logic is reused verbatim.
Display data (status, account, channel list) is read straight from the
active Store / Events so the frontend gets JSON.
"""

from __future__ import annotations

import json
import threading

from .. import adapters, commands, config
from .. import store as store_mod
from ..events import Events


def _noprompt(_: str) -> str:
    return ""


class Api:
    def __init__(self) -> None:
        self._events = Events()
        self._ctx = commands.Context(self._events, _noprompt, _noprompt)
        self._window = None
        self._log_stop = threading.Event()
        self._log_thread: threading.Thread | None = None

    # --- lifecycle wiring -------------------------------------------------

    def attach_window(self, window) -> None:
        self._window = window

    def autostart(self) -> None:
        """Open the most-recent account (if any) and start its daemon."""
        try:
            commands.autostart(self._ctx)
        except Exception as exc:
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
        self._log_stop.set()
        try:
            commands.cmd_quit(self._ctx, [])
        except Exception:
            pass

    # --- methods exposed to JS ------------------------------------------

    def account(self) -> dict:
        store = self._ctx.store
        if store is None:
            return {
                "logged_in": False,
                "account_id": None,
                "username": None,
                "machine_id": None,
                "studio_url": config.STUDIO_BASE_URL,
                "has_channels": False,
            }
        return {
            "logged_in": store.kv_get("studio_token") is not None,
            "account_id": self._ctx.account_id,
            "username": store.kv_get("display_name"),
            "machine_id": store.kv_get("machine_id"),
            "studio_url": config.STUDIO_BASE_URL,
            "has_channels": bool(store.channels()),
        }

    def accounts(self) -> list:
        """List every account stored under state_root (for the picker)."""
        if not config.has_state_root():
            return []
        out = store_mod.list_accounts(config.state_root())
        active = self._ctx.account_id
        for a in out:
            a["active"] = a["account_id"] == active
        return out

    def use_account(self, account_id: str) -> dict:
        return commands.cmd_account(self._ctx, ["use", account_id])

    def remove_account(self, account_id: str) -> dict:
        return commands.cmd_account(self._ctx, ["remove", account_id])

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
        """List bound channels with resolved platform_self_id for display."""
        out: list[dict] = []
        store = self._ctx.store
        if store is None:
            return out
        for i, c in enumerate(store.channels()):
            self_id = None
            try:
                self_id = (
                    adapters.get(c.platform).build(c.credential).platform_self_id
                )
            except Exception:
                self_id = None
            label = f"{c.platform}/{self_id}" if self_id else f"{c.platform}/-"
            out.append(
                {
                    "index": i + 1,
                    "platform": c.platform,
                    "self_id": self_id,
                    "label": label,
                }
            )
        return out

    def channel_add(self, username: str, password: str) -> dict:
        """Chat shortcut: single-shot username+password login flow."""
        return self.channel_add_generic(
            "chat", {"username": username, "password": password}
        )

    def channel_add_generic(self, platform: str, answers: dict) -> dict:
        """Run a single-step LoginFlow synchronously."""
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

        # Open the current account's dir if one is active, otherwise the root.
        if self._ctx.account_id:
            path = str(config.account_dir(self._ctx.account_id))
        else:
            path = str(config.state_root())
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
