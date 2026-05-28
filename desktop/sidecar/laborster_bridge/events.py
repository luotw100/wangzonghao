"""Thread-safe in-memory log ring + daemon-state snapshot.

The REPL (main thread) reads snapshots and tails logs from here; the
daemon worker threads only write. Replaces the Electron IPC push.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Iterator


class Events:
    def __init__(self, capacity: int = 1000) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._log: deque[dict] = deque(maxlen=capacity)
        self._seq = 0
        self._state: dict[str, Any] = {"status": "idle", "channels": []}

    def log(self, src: str, level: str, msg: str) -> None:
        line = {"t": time.strftime("%H:%M:%S"), "src": src, "level": level, "msg": msg}
        with self._cond:
            self._seq += 1
            line["_seq"] = self._seq
            self._log.append(line)
            self._cond.notify_all()

    def set_state(self, state: dict) -> None:
        with self._lock:
            self._state = state

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)

    def tail(self, n: int) -> list[dict]:
        with self._lock:
            return list(self._log)[-n:]

    def follow(self, stop: threading.Event) -> Iterator[dict]:
        """Yield log lines as they arrive until `stop` is set."""
        with self._lock:
            last = self._seq
        while not stop.is_set():
            with self._cond:
                self._cond.wait(timeout=0.5)
                new = [ln for ln in self._log if ln["_seq"] > last]
                if new:
                    last = new[-1]["_seq"]
            for ln in new:
                yield ln
