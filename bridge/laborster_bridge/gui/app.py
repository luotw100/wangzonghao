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

    api = Api()
    index = _web_dir() / "index.html"
    window = webview.create_window(
        WINDOW_TITLE,
        url=str(index),
        js_api=api,
        width=980,
        height=720,
        min_size=(760, 560),
        background_color="#1b1d23",
    )
    api.attach_window(window)

    # close = quit (stop daemon, exit). Minimize does NOT trigger this,
    # so minimizing keeps the daemon bridging in the background.
    def _on_closing():
        api.shutdown()

    window.events.closing += _on_closing

    def _on_start():
        api.autostart()

    webview.start(_on_start)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
