"""GUI entry point: fixed per-OS data dir, robust single-instance lock,
pywebview window, close = quit (minimize keeps the daemon running).

CLI behaviour is untouched: the fixed default data dir lives here, NOT
in config.py, so config.py keeps its "no default" invariant for the
Linux/CLI users who must still set /state explicitly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .. import config
from .bridge_api import Api

APP_NAME = "LaborsterBridge"
WINDOW_TITLE = "Laborster Bridge"

# Held for the whole process lifetime. The OS releases the underlying
# lock automatically when the process exits OR crashes OR is killed —
# so a dead instance never leaves a stale lock behind.
_lock_handle = None


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    # GUI is shipped only for Windows/macOS; this is a dev fallback.
    return Path.home() / f".{APP_NAME.lower()}"


def _acquire_single_instance(data_dir: Path) -> bool:
    """Return True if we got the lock, False if another instance holds it.

    The lock is tied to an open file handle, so the kernel frees it on
    process death — robust against crashes (never a permanent stale lock).
    """
    global _lock_handle
    lock_path = data_dir / ".singleton.lock"
    try:
        if sys.platform == "win32":
            import msvcrt

            fh = open(lock_path, "a+")
            if fh.tell() == 0:
                fh.write(" ")
                fh.flush()
            fh.seek(0)
            try:
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                fh.close()
                return False
            _lock_handle = fh
            return True
        else:
            import fcntl

            fh = open(lock_path, "a+")
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fh.close()
                return False
            _lock_handle = fh
            return True
    except Exception:
        # If locking itself errors, fail open: better to run than to
        # wrongly refuse to start.
        return True


def _web_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


def main() -> int:
    data_dir = _default_data_dir()
    try:
        config.set_state_root(str(data_dir))
    except Exception as exc:
        print(f"无法创建数据目录 {data_dir}: {exc}", file=sys.stderr)
        return 2

    if not _acquire_single_instance(data_dir):
        try:
            import webview

            webview.create_window(
                WINDOW_TITLE,
                html="<body style='font:14px sans-serif;background:#1b1d23;"
                "color:#e6e6e6;padding:2em'>Laborster Bridge 已在运行。"
                "请使用已打开的窗口。</body>",
                width=420,
                height=180,
            )
            webview.start()
        except Exception:
            print("Laborster Bridge 已在运行。", file=sys.stderr)
        return 0

    import webview
    from webview.menu import Menu, MenuAction

    api = Api()

    # Open the most-recent account (if any) before deciding window
    # layout. autostart() only touches local state + spawns daemon
    # threads — no UI dependency — so it's safe to run before
    # webview.start.
    api.autostart()

    studio_url = api.studio_url_for_active()

    # The local window is ALWAYS created. It owns channel binding,
    # account switching, Studio URL override and daemon logs — none of
    # which the Studio web console knows about yet. When the user has a
    # valid token, we start the local window hidden and raise Studio
    # on top; otherwise the local window is the only thing on screen
    # and hosts the login form.
    index = _web_dir() / "index.html"
    local_window = webview.create_window(
        f"{WINDOW_TITLE} — 设置",
        url=str(index),
        js_api=api,
        width=980,
        height=720,
        min_size=(760, 560),
        background_color="#1b1d23",
        hidden=bool(studio_url),
    )
    api.attach_local_window(local_window)

    # close = quit. The daemon lives in this process, so closing any
    # window stops bridging; matches the explicit product call (X =
    # full exit). Hiding the local window from the menu uses .hide()
    # which does not fire 'closing'.
    local_window.events.closing += lambda: api.shutdown()

    storage_path = None
    if studio_url:
        # Returning user: jump straight into the embedded Studio
        # console. storage_path is pinned to the active account dir so
        # cookies / localStorage / IndexedDB / http cache stay isolated
        # from the system browser and from other local accounts.
        storage_path = str(config.account_dir(api._ctx.account_id) / "webview")
        studio_window = webview.create_window(
            WINDOW_TITLE,
            url=studio_url,
            # No js_api: remote pages must not reach into local Python.
            width=1200,
            height=800,
            min_size=(900, 600),
            background_color="#1b1d23",
        )
        studio_window.events.closing += lambda: api.shutdown()
        # Log pump targets the visible window; the local one is hidden
        # and would silently no-op anyway.
        api.attach_window(studio_window)
    else:
        api.attach_window(local_window)

    # Native menu lets logged-in users summon the settings window for
    # channel binding / account switching while they're inside Studio.
    menu = [
        Menu(
            "Laborster",
            [MenuAction("设置", api.show_local_window)],
        ),
    ]

    if storage_path is not None:
        webview.start(menu=menu, storage_path=storage_path)
    else:
        webview.start(menu=menu)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
