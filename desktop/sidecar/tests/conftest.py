"""Fixtures for the sidecar's local unit tests.

These cover the on-disk / in-memory state modules (store, events,
config) that never touch the network — real SQLite files in a tmp dir,
no mocks, no running Studio. The Studio-facing paths are exercised
separately against the live compose stack (see services/api/tests).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from laborster_bridge import config
from laborster_bridge.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    """A fresh Store backed by a real SQLite file under tmp_path."""
    s = Store(tmp_path / "acct" / "state.db")
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _reset_config_globals() -> Iterator[None]:
    """config keeps module-level globals (state root + Studio URL).

    Snapshot and restore them around every test so config tests can mutate
    freely without leaking into the next test.
    """
    saved_root = config._state_root
    saved_url = config.STUDIO_BASE_URL
    try:
        yield
    finally:
        config._state_root = saved_root
        config.STUDIO_BASE_URL = saved_url
