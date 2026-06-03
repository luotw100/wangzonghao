"""Unit tests for StudioClient.handshake self-healing.

handshake is the one StudioClient call that owns the machine_id contract:
a revoked/stale machine_id makes Studio return 400 machine_id_invalid, and
the documented recovery is to drop the local id and retry without it. These
tests pin that retry (and its boundaries) by stubbing the module-level
``request_json`` — no network, no running Studio.
"""

from __future__ import annotations

import pytest

from laborster_bridge import config, studio_client
from laborster_bridge.http import HttpError, Unauthorized
from laborster_bridge.studio_client import StudioClient

_OK = {
    "token": "tok-new",
    "account_id": "ac_1",
    "username": "alice",
    "machine_id": "Wxyz",
}


@pytest.fixture(autouse=True)
def _base_url() -> None:
    config.set_studio_base_url("http://user-api:23456")


def _patch_request_json(monkeypatch, side_effects):
    """Replace request_json with one that returns/raises from a list in
    order, recording the body of each call."""
    calls: list[dict] = []
    seq = iter(side_effects)

    def fake(method, url, *, token=None, body=None, timeout=20.0, headers=None):
        # Snapshot: handshake reuses one body dict across the retry.
        calls.append(dict(body) if body is not None else None)
        outcome = next(seq)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(studio_client, "request_json", fake)
    return calls


def test_handshake_retries_without_machine_id_on_invalid(monkeypatch) -> None:
    calls = _patch_request_json(
        monkeypatch,
        [HttpError(400, '{"detail":"machine_id_invalid"}'), _OK],
    )

    r = StudioClient(get_token=lambda: None).handshake("alice", "pw", "Old1")

    assert r["machine_id"] == "Wxyz"
    # First attempt carried the stale id; the retry dropped it.
    assert [c["machine_id"] for c in calls] == ["Old1", None]


def test_handshake_no_retry_when_no_local_machine_id(monkeypatch) -> None:
    # Fresh login (machine_id=None): a 400 here is a real error, not the
    # revoked-device case — surface it, don't loop.
    calls = _patch_request_json(
        monkeypatch,
        [HttpError(400, '{"detail":"machine_id_invalid"}')],
    )

    with pytest.raises(HttpError):
        StudioClient(get_token=lambda: None).handshake("alice", "pw", None)

    assert len(calls) == 1


def test_handshake_does_not_swallow_unauthorized(monkeypatch) -> None:
    # Wrong password is 401, raised before the machine_id check — must not
    # trigger the retry.
    calls = _patch_request_json(monkeypatch, [Unauthorized()])

    with pytest.raises(Unauthorized):
        StudioClient(get_token=lambda: None).handshake("alice", "bad", "Old1")

    assert len(calls) == 1


def test_handshake_does_not_retry_other_400(monkeypatch) -> None:
    # A different 400 is not the revoked-device signal — propagate as-is.
    calls = _patch_request_json(
        monkeypatch,
        [HttpError(400, '{"detail":"something_else"}')],
    )

    with pytest.raises(HttpError):
        StudioClient(get_token=lambda: None).handshake("alice", "pw", "Old1")

    assert len(calls) == 1
