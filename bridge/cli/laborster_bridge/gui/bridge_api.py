"""js_api bridge: structured methods over commands.* + a log stream.

Surface design:

* Mutations that already have a CLI counterpart (login/logout, account
  use/remove, channel rm/relogin, studio set/reset) are thin wrappers
  around ``commands.*`` so the daemon reconcile logic stays in one place.
* Channel binding goes through a generic flow runner
  (``flow_begin/submit/poll/cancel/persist``) that drives
  :class:`adapters.LoginFlow` directly. Single-step (chat password) and
  multi-step (future QR / OAuth) flows share the same dispatch — the GUI
  modal only needs to render the current ``Step``.
* Read-only views (status, accounts, channels) return JSON the GUI can
  paint without further round-trips.

bridge is a relay: this layer never invents state. Everything it returns
is either a thin projection of ``commands.Context`` (i.e. the local
store + daemon snapshot) or a Studio-derived value freshly read on
demand.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from urllib.parse import urlencode

from .. import adapters, commands, config
from .. import store as store_mod
from ..events import Events

# ---- module-level types ------------------------------------------------

# Maximum age of an in-flight LoginFlow before we drop it from memory.
_FLOW_TTL_S = 600


def _noprompt(_: str) -> str:
    return ""


def _step_payload(step: adapters.Step) -> dict:
    """Serialize an adapters.Step for the JS modal."""
    if isinstance(step, adapters.PromptInput):
        return {
            "kind": "prompt",
            "title": step.title,
            "error": step.error,
            "fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "secret": f.secret,
                    "placeholder": f.placeholder,
                }
                for f in step.fields
            ],
        }
    if isinstance(step, adapters.WaitForExternal):
        # qr_png is base64-encoded so the modal can render <img src="data:...">.
        import base64

        return {
            "kind": "wait",
            "title": step.title,
            "poll_after_ms": step.poll_after_ms,
            "qr_png_b64": (
                base64.b64encode(step.qr_png).decode("ascii")
                if step.qr_png else None
            ),
            "open_url": step.open_url,
            "hint": step.hint,
        }
    if isinstance(step, adapters.Done):
        return {"kind": "done"}
    if isinstance(step, adapters.Failed):
        return {"kind": "failed", "reason": step.reason}
    return {"kind": "failed", "reason": f"未知 step: {type(step).__name__}"}


class Api:
    def __init__(self) -> None:
        self._events = Events()
        self._ctx = commands.Context(self._events, _noprompt, _noprompt)
        # _window is the log-pump target (Studio window once it exists,
        # otherwise the local window). _local_window is the *settings*
        # window — kept around even when Studio takes the stage so the
        # "设置" menu can re-show it for channel binding / account
        # switching.
        self._window = None
        self._local_window = None
        self._log_stop = threading.Event()
        self._log_thread: threading.Thread | None = None

        # In-flight LoginFlow registry. Keyed by an opaque flow_id.
        # Each value is (flow, platform, created_at_monotonic).
        self._flows: dict[str, tuple[adapters.LoginFlow, str, float]] = {}
        self._flows_lock = threading.Lock()

    # --- lifecycle wiring -------------------------------------------------

    def attach_window(self, window) -> None:
        self._window = window

    def attach_local_window(self, window) -> None:
        """Register the local settings window so the menu can re-show it
        after the user has been swapped into the Studio console."""
        self._local_window = window

    def show_local_window(self) -> None:
        """Bring the local settings window back. Called by the native
        menu so logged-in users can still reach channel binding,
        account switching and daemon logs from inside Studio."""
        w = self._local_window
        if w is None:
            return
        try:
            w.show()
        except Exception:
            pass

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

    # --- platform metadata ----------------------------------------------

    def platforms(self) -> list[dict]:
        """Available channel platforms — drives the binding modal's <select>."""
        return [{"id": p, "label": _platform_label(p)} for p in adapters.platforms()]

    # --- views (read-only) ------------------------------------------------

    def account(self) -> dict:
        """Active account view — the one the daemon is bridging right now."""
        store = self._ctx.store
        if store is None:
            return {
                "logged_in": False,
                "account_id": None,
                "display_name": None,
                "machine_id": None,
                "studio_url": config.STUDIO_BASE_URL,
                "studio_url_overridden": (
                    config.STUDIO_BASE_URL != config.DEFAULT_STUDIO_BASE_URL
                ),
                "has_channels": False,
            }
        return {
            "logged_in": store.kv_get("studio_token") is not None,
            "account_id": self._ctx.account_id,
            "display_name": store.kv_get("display_name"),
            "machine_id": store.kv_get("machine_id"),
            "studio_url": config.STUDIO_BASE_URL,
            "studio_url_overridden": (
                config.STUDIO_BASE_URL != config.DEFAULT_STUDIO_BASE_URL
            ),
            "has_channels": bool(store.channels()),
        }

    def accounts(self) -> list:
        """Every account stored locally (drives the header picker)."""
        if not config.has_state_root():
            return []
        out = store_mod.list_accounts(config.state_root())
        active = self._ctx.account_id
        for a in out:
            a["active"] = a["account_id"] == active
        return out

    def channels(self) -> list[dict]:
        """Bound channels with their last-known live state from the daemon snapshot.

        We merge two sources:
          • store.channels() — durable list of bindings (id + platform).
          • events.snapshot().channels — daemon worker states keyed by id.

        Platform self_id is NOT re-resolved here (would do an HTTP call
        per channel on every poll). The daemon's snapshot already carries
        the resolved id once the worker is online.
        """
        store = self._ctx.store
        if store is None:
            return []
        snap = self._events.snapshot()
        live_by_id = {c.get("channel_id"): c for c in snap.get("channels", [])}
        out: list[dict] = []
        for c in store.channels():
            live = live_by_id.get(c.id) or {}
            out.append(
                {
                    "channel_id": c.id,
                    "platform": c.platform,
                    "platform_label": _platform_label(c.platform),
                    "self_id": live.get("platform_self_id"),
                    "state": live.get("state") or "idle",
                    "online": bool(live.get("online")),
                    "conv_count": live.get("conv_count") or 0,
                    "last_error": live.get("last_error"),
                }
            )
        return out

    def status(self) -> dict:
        """Top-line daemon snapshot for the status strip."""
        snap = self._events.snapshot()
        running = bool(self._ctx.runtime and self._ctx.runtime.is_running())
        return {
            "running": running,
            "status": snap.get("status", "idle"),
            "in_count_5m": snap.get("in_count_5m", 0),
            "outbound_pending": snap.get("outbound_pending", 0),
            "last_error": snap.get("last_error"),
            "studio_url": snap.get("studio_url") or config.STUDIO_BASE_URL,
            "studio_url_overridden": (
                config.STUDIO_BASE_URL != config.DEFAULT_STUDIO_BASE_URL
            ),
        }

    def logs(self, n: int = 200) -> list:
        return self._events.tail(int(n))

    # --- account mutations ----------------------------------------------

    def login(self, username: str, password: str) -> dict:
        r = commands.cmd_login(self._ctx, [username, password])
        if "error" not in r:
            # First login succeeded — swap the local login UI out for the
            # embedded Studio console. From here on the user lives inside
            # the Studio web app; the local UI only re-appears after a
            # logout (which clears studio_token and forces a relaunch).
            self._open_studio_window()
        return r

    def logout(self) -> dict:
        return commands.cmd_logout(self._ctx, [])

    def use_account(self, account_id: str) -> dict:
        return commands.cmd_account(self._ctx, ["use", account_id])

    def remove_account(self, account_id: str) -> dict:
        return commands.cmd_account(self._ctx, ["remove", account_id])

    def set_studio_url(self, url: str) -> dict:
        return commands.cmd_studio(self._ctx, ["set", url])

    def reset_studio_url(self) -> dict:
        return commands.cmd_studio(self._ctx, ["reset"])

    # --- channel mutations ----------------------------------------------

    def channel_rm(self, channel_id: int) -> dict:
        store = self._ctx.store
        if store is None:
            return {"error": "请先登录 Studio"}
        # commands.cmd_channel uses 1-based positional indexes. Translate
        # the stable channel_id back into the current 1-based index so the
        # CLI helper can stay simple.
        for i, c in enumerate(store.channels()):
            if c.id == int(channel_id):
                return commands.cmd_channel(self._ctx, ["rm", str(i + 1)])
        return {"error": f"未找到 channel {channel_id}"}

    # --- LoginFlow runner -----------------------------------------------
    # The same three methods drive both new channels (flow_begin without
    # channel_id, persist creates a fresh row) and relogin (begin with
    # channel_id, persist updates that row's credential in-place).

    def flow_begin(
        self,
        platform: str,
        extras: dict | None = None,
        channel_id: int | None = None,
    ) -> dict:
        """Start a LoginFlow. Returns {flow_id, step, channel_id}.

        ``extras`` are forwarded as kwargs to ``factory.begin_login`` —
        chat consumes ``base_url`` here. For relogin (channel_id given),
        if the caller doesn't supply ``base_url`` we fish it out of the
        existing credential so the user doesn't have to retype it.
        """
        try:
            factory = adapters.get(platform)
        except KeyError as exc:
            return {"error": str(exc)}

        extras = dict(extras or {})
        if channel_id is not None and self._ctx.store is not None:
            for c in self._ctx.store.channels():
                if c.id == int(channel_id) and c.platform == platform:
                    if platform == "chat" and "base_url" not in extras:
                        url = c.credential.get("base_url")
                        if url:
                            extras["base_url"] = url
                    break

        try:
            flow = factory.begin_login(**extras)
        except adapters.TransientError as exc:
            return {"error": f"启动登录失败: {exc}"}
        except TypeError as exc:
            return {"error": f"参数不支持: {exc}"}

        flow_id = secrets.token_urlsafe(12)
        with self._flows_lock:
            self._prune_flows_locked()
            self._flows[flow_id] = (flow, platform, time.monotonic())
        return {
            "flow_id": flow_id,
            "channel_id": channel_id,
            "step": _step_payload(flow.current()),
        }

    def flow_submit(self, flow_id: str, answers: dict) -> dict:
        flow, _platform, _ = self._get_flow(flow_id) or (None, None, None)
        if flow is None:
            return {"error": "flow 已过期，请重试"}
        try:
            step = flow.submit(answers or {})
        except adapters.TransientError as exc:
            return {"error": f"网络错误: {exc}"}
        return {"step": _step_payload(step)}

    def flow_poll(self, flow_id: str) -> dict:
        flow, _, _ = self._get_flow(flow_id) or (None, None, None)
        if flow is None:
            return {"error": "flow 已过期"}
        try:
            step = flow.poll()
        except adapters.TransientError as exc:
            return {"error": f"网络错误: {exc}"}
        return {"step": _step_payload(step)}

    def flow_cancel(self, flow_id: str) -> dict:
        entry = self._pop_flow(flow_id)
        if entry is None:
            return {}
        flow, _, _ = entry
        try:
            flow.cancel()
        except Exception:
            pass
        return {}

    def flow_persist(self, flow_id: str, channel_id: int | None = None) -> dict:
        """Commit a Done flow. New channel if channel_id is None, else relogin.

        Returns the same shape as commands._persist_channel:
          {lines: [...]} on success, {error: "..."} on failure.
        """
        entry = self._pop_flow(flow_id)
        if entry is None:
            return {"error": "flow 已过期"}
        flow, platform, _ = entry
        step = flow.current()
        if not isinstance(step, adapters.Done):
            return {"error": "flow 还未完成"}

        if self._ctx.store is None:
            return {"error": "请先登录 Studio"}

        if channel_id is None:
            return commands._persist_channel(self._ctx, platform, step.credential)

        # relogin path: update credential in-place and bounce the daemon
        # so the worker picks up the new token.
        for c in self._ctx.store.channels():
            if c.id == int(channel_id):
                commands._stop_daemon(self._ctx)
                self._ctx.store.update_channel_credential(c.id, step.credential)
                lines = [f"已更新 channel #{c.id} ({platform}) credential"]
                msg = commands._ensure(self._ctx)
                if msg:
                    lines.append(msg)
                return {"lines": lines}
        return {"error": f"channel {channel_id} 已不存在"}

    # --- flow registry internals ---------------------------------------

    def _get_flow(self, flow_id: str):
        with self._flows_lock:
            self._prune_flows_locked()
            return self._flows.get(flow_id)

    def _pop_flow(self, flow_id: str):
        with self._flows_lock:
            self._prune_flows_locked()
            return self._flows.pop(flow_id, None)

    def _prune_flows_locked(self) -> None:
        now = time.monotonic()
        stale = [k for k, (_, _, t) in self._flows.items() if now - t > _FLOW_TTL_S]
        for k in stale:
            self._flows.pop(k, None)

    # --- embedded Studio console ----------------------------------------

    def studio_url_for_active(self) -> str | None:
        """If the active account has a Studio token, build a token-bearing
        URL for the embedded webview. Returns None when no account is
        opened yet or the token has been cleared (logout / 401 / first
        run) — in those cases the local login UI stays visible.

        The token rides in the URL fragment so it never reaches the
        server (no access logs, no Referer). main.tsx scrubs it from
        history immediately after persisting to localStorage.
        """
        store = self._ctx.store
        if store is None:
            return None
        token = store.kv_get("studio_token")
        if not token:
            return None
        machine_id = store.kv_get("machine_id") or ""
        base = config.STUDIO_BASE_URL.rstrip("/")
        return f"{base}/#{urlencode({'token': token, 'machine': machine_id})}"

    def _open_studio_window(self) -> None:
        """Swap the current window for an embedded Studio console.

        The new window deliberately has no ``js_api``: remote Studio
        pages must never reach into local Python (XSS would otherwise
        own the daemon). Closing it quits the app — the daemon lives in
        this process, so window-close = full exit, matching the product
        decision.
        """
        url = self.studio_url_for_active()
        if not url:
            return
        try:
            import webview  # late import: webview only present in GUI build
        except ImportError:
            return
        new_win = webview.create_window(
            "Laborster",
            url=url,
            width=1200,
            height=800,
            min_size=(900, 600),
            background_color="#1b1d23",
        )
        new_win.events.closing += lambda: self.shutdown()
        # Re-target the log pump to the new window. Studio's React tree
        # doesn't define window.pushLog, so evaluate_js silently no-ops
        # there (the pump already swallows exceptions); logs remain
        # available via the daemon's state directory.
        self._window = new_win
        # Hide (not destroy) the local window: channel binding / account
        # switching still need to live somewhere, and the "设置" menu
        # item re-shows it on demand.
        if self._local_window is not None:
            try:
                self._local_window.hide()
            except Exception:
                pass

    # --- misc -----------------------------------------------------------

    def open_data_dir(self) -> dict:
        import subprocess
        import sys

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


def _platform_label(platform: str) -> str:
    return {"chat": "Chat 沙箱"}.get(platform, platform)
