"""Unit tests for state-root resolution + endpoint override.

config holds module-level globals; conftest's _reset_config_globals
fixture restores them around each test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laborster_bridge import config


def test_state_root_unset_raises() -> None:
    config._state_root = None
    assert config.has_state_root() is False
    with pytest.raises(config.NoStateError):
        config.state_root()


def test_set_state_root_creates_and_resolves(tmp_path: Path) -> None:
    root = tmp_path / "state"
    returned = config.set_state_root(str(root))
    assert config.has_state_root() is True
    assert returned == root.resolve()
    assert root.is_dir()  # created if missing


def test_path_layout(tmp_path: Path) -> None:
    config.set_state_root(str(tmp_path))
    acct = config.account_dir("acct-1")
    assert acct == tmp_path.resolve() / "acct-1"
    assert acct.is_dir()
    assert config.db_path("acct-1") == acct / "state.db"


def test_set_studio_base_url_strips_trailing_slash() -> None:
    config.set_studio_base_url("http://user-api:23456/")
    assert config.STUDIO_BASE_URL == "http://user-api:23456"
