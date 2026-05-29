"""Unit tests for the in-memory log ring + state snapshot."""

from __future__ import annotations

import threading

from laborster_bridge.events import Events


def test_log_and_tail() -> None:
    ev = Events()
    ev.log("daemon", "info", "one")
    ev.log("daemon", "err", "two")

    lines = ev.tail(10)
    assert [ln["msg"] for ln in lines] == ["one", "two"]
    assert lines[1]["level"] == "err"


def test_tail_returns_last_n() -> None:
    ev = Events()
    for i in range(5):
        ev.log("d", "info", str(i))
    assert [ln["msg"] for ln in ev.tail(2)] == ["3", "4"]


def test_ring_capacity_drops_oldest() -> None:
    ev = Events(capacity=3)
    for i in range(5):
        ev.log("d", "info", str(i))
    # deque(maxlen=3) keeps only the newest three.
    assert [ln["msg"] for ln in ev.tail(10)] == ["2", "3", "4"]


def test_snapshot_is_a_copy() -> None:
    ev = Events()
    ev.set_state({"status": "online", "channels": ["a"]})
    snap = ev.snapshot()
    snap["status"] = "mutated"
    # Mutating the snapshot must not affect internal state.
    assert ev.snapshot()["status"] == "online"


def test_follow_yields_new_lines_then_stops() -> None:
    ev = Events()
    ev.log("d", "info", "before")  # pre-existing line, should NOT be yielded

    stop = threading.Event()
    seen: list[str] = []

    def _consume() -> None:
        for ln in ev.follow(stop):
            seen.append(ln["msg"])

    t = threading.Thread(target=_consume)
    t.start()
    ev.log("d", "info", "after-1")
    ev.log("d", "info", "after-2")
    # Give the follower a moment to drain, then stop it.
    t_join = threading.Event()
    while not t_join.wait(0.05):
        if {"after-1", "after-2"}.issubset(seen):
            break
    stop.set()
    t.join(timeout=2.0)

    assert "before" not in seen
    assert seen == ["after-1", "after-2"]
