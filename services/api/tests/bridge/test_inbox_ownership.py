"""Per-channel inbox ownership mutex.

A platform identity (account, platform, platform_self_id) can be served by
at most one *online* bridge. A second online bridge claiming the same
identity is rejected with 409; a stale (offline) owner is taken over.
"""

import uuid

from sqlalchemy import text


def _claim(self_id, platform="chat", display="dev"):
    return {
        "platform": platform,
        "platform_self_id": self_id,
        "display_name": display,
    }


def _bridge_id_for(db, account_id, machine_id):
    return db.execute(
        text(
            "SELECT id FROM studio.bridges "
            "WHERE account_id = :a AND machine_id = :m"
        ),
        {"a": account_id, "m": machine_id},
    ).scalar_one()


def _inbox_owner(db, account_id, self_id):
    return db.execute(
        text(
            "SELECT bridge_id FROM studio.inboxes "
            "WHERE account_id = :a AND platform_self_id = :s"
        ),
        {"a": account_id, "s": self_id},
    ).scalar_one()


def test_second_online_bridge_is_rejected(account, bridge_factory, db):
    b1 = bridge_factory(account)
    b2 = bridge_factory(account)
    self_id = f"selfid-{uuid.uuid4().hex[:8]}"

    r1 = b1.http.post("/api/bridge/inboxes", json={"inboxes": [_claim(self_id)]})
    assert r1.status_code == 200

    r2 = b2.http.post("/api/bridge/inboxes", json={"inboxes": [_claim(self_id)]})
    assert r2.status_code == 409
    # The owning machine_id is surfaced so the client can build its UX message.
    assert b1.machine_id in r2.json()["detail"]

    # Ownership unchanged — still b1.
    assert _inbox_owner(db, account.id, self_id) == _bridge_id_for(
        db, account.id, b1.machine_id
    )


def test_different_channel_is_not_rejected(account, bridge_factory):
    """Mutex is per-channel: a second bridge claiming a *different*
    platform_self_id is fine even while the first is online.
    """
    b1 = bridge_factory(account)
    b2 = bridge_factory(account)

    r1 = b1.http.post(
        "/api/bridge/inboxes", json={"inboxes": [_claim(f"a-{uuid.uuid4().hex[:8]}")]}
    )
    assert r1.status_code == 200
    r2 = b2.http.post(
        "/api/bridge/inboxes", json={"inboxes": [_claim(f"b-{uuid.uuid4().hex[:8]}")]}
    )
    assert r2.status_code == 200


def test_stale_owner_is_taken_over(account, bridge_factory, db):
    b1 = bridge_factory(account)
    b2 = bridge_factory(account)
    self_id = f"selfid-{uuid.uuid4().hex[:8]}"

    assert (
        b1.http.post(
            "/api/bridge/inboxes", json={"inboxes": [_claim(self_id)]}
        ).status_code
        == 200
    )

    # Force b1 offline by aging its heartbeat well past the offline window.
    db.execute(
        text(
            "UPDATE studio.bridges SET last_seen_at = now() - interval '1 hour' "
            "WHERE account_id = :a AND machine_id = :m"
        ),
        {"a": account.id, "m": b1.machine_id},
    )
    db.commit()

    r2 = b2.http.post("/api/bridge/inboxes", json={"inboxes": [_claim(self_id)]})
    assert r2.status_code == 200
    # Inbox now belongs to b2.
    assert _inbox_owner(db, account.id, self_id) == _bridge_id_for(
        db, account.id, b2.machine_id
    )


def test_same_bridge_reregister_is_not_a_conflict(account, bridge_factory):
    """A bridge re-registering its own inbox must never 409 itself."""
    b1 = bridge_factory(account)
    self_id = f"selfid-{uuid.uuid4().hex[:8]}"
    assert (
        b1.http.post(
            "/api/bridge/inboxes", json={"inboxes": [_claim(self_id)]}
        ).status_code
        == 200
    )
    assert (
        b1.http.post(
            "/api/bridge/inboxes", json={"inboxes": [_claim(self_id, display="renamed")]}
        ).status_code
        == 200
    )
