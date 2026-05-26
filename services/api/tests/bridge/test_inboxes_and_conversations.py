import uuid

from sqlalchemy import text


def _claim(platform="chat", display=None, self_id=None):
    return {
        "platform": platform,
        "platform_self_id": self_id or f"selfid-{uuid.uuid4().hex[:8]}",
        "display_name": display or f"display-{uuid.uuid4().hex[:6]}",
    }


def test_register_inboxes_creates_rows(bridge, db):
    claim = _claim()
    r = bridge.http.post("/api/bridge/inboxes", json={"inboxes": [claim]})
    assert r.status_code == 200
    inboxes = r.json()["inboxes"]
    assert len(inboxes) == 1
    ib = inboxes[0]
    assert ib["platform"] == "chat"
    assert ib["display_name"] == claim["display_name"]

    row = db.execute(
        text(
            "SELECT account_id, bridge_id, platform_self_id "
            "FROM studio.inboxes WHERE id = :i"
        ),
        {"i": ib["id"]},
    ).one()
    assert row.account_id == bridge.account_id


def test_register_inboxes_is_idempotent(bridge, db):
    claim = _claim()
    bridge.http.post("/api/bridge/inboxes", json={"inboxes": [claim]})
    bridge.http.post("/api/bridge/inboxes", json={"inboxes": [claim]})
    n = db.execute(
        text(
            "SELECT count(*) FROM studio.inboxes "
            "WHERE bridge_id = (SELECT id FROM studio.bridges WHERE machine_id = :m) "
            "AND platform_self_id = :psid"
        ),
        {"m": bridge.machine_id, "psid": claim["platform_self_id"]},
    ).scalar_one()
    assert n == 1


def test_get_inboxes_returns_bound_set(bridge):
    claim = _claim()
    bridge.http.post("/api/bridge/inboxes", json={"inboxes": [claim]})
    rows = bridge.http.get("/api/bridge/inboxes").json()["inboxes"]
    assert any(i["platform_self_id"] == claim["platform_self_id"] for i in rows)


def test_upsert_conversations_creates_and_members(bridge, db):
    claim = _claim()
    inbox_id = bridge.http.post(
        "/api/bridge/inboxes", json={"inboxes": [claim]}
    ).json()["inboxes"][0]["id"]

    pcid = f"pc-{uuid.uuid4().hex[:8]}"
    payload = {
        "inbox_id": inbox_id,
        "conversations": [
            {
                "platform_conversation_id": pcid,
                "kind": "group",
                "display_name": "the-group",
                "members": [
                    {"peer_platform_id": "peer-a", "display_name": "A"},
                    {"peer_platform_id": "peer-b", "display_name": "B"},
                ],
            }
        ],
    }
    r = bridge.http.post("/api/bridge/conversations", json=payload)
    assert r.status_code == 200
    assert r.json() == {"upserted": 1}

    conv_id = db.execute(
        text(
            "SELECT id FROM studio.conversations "
            "WHERE inbox_id = :i AND platform_conversation_id = :p"
        ),
        {"i": inbox_id, "p": pcid},
    ).scalar_one()
    members = db.execute(
        text(
            "SELECT peer_platform_id, display_name "
            "FROM studio.conversation_members WHERE conversation_id = :c "
            "ORDER BY peer_platform_id"
        ),
        {"c": conv_id},
    ).all()
    assert [(m.peer_platform_id, m.display_name) for m in members] == [
        ("peer-a", "A"),
        ("peer-b", "B"),
    ]

    # Re-upsert with a different member set replaces it.
    payload["conversations"][0]["members"] = [
        {"peer_platform_id": "peer-c", "display_name": "C"},
    ]
    bridge.http.post("/api/bridge/conversations", json=payload)
    db.expire_all()
    members = db.execute(
        text(
            "SELECT peer_platform_id FROM studio.conversation_members "
            "WHERE conversation_id = :c"
        ),
        {"c": conv_id},
    ).all()
    assert [m.peer_platform_id for m in members] == ["peer-c"]


def test_takeovers_filter(account, bridge, db):
    claim = _claim()
    inbox_id = bridge.http.post(
        "/api/bridge/inboxes", json={"inboxes": [claim]}
    ).json()["inboxes"][0]["id"]
    pcid = f"pc-{uuid.uuid4().hex[:8]}"
    bridge.http.post(
        "/api/bridge/conversations",
        json={
            "inbox_id": inbox_id,
            "conversations": [
                {
                    "platform_conversation_id": pcid,
                    "kind": "dm",
                    "display_name": "peer",
                    "members": [{"peer_platform_id": "peer-x", "display_name": "X"}],
                }
            ],
        },
    )

    # Not flipped yet: no takeover entries for this pcid.
    rows = bridge.http.get("/api/bridge/takeovers").json()["takeovers"]
    assert not any(r["platform_conversation_id"] == pcid for r in rows)

    conv_id = db.execute(
        text(
            "SELECT id FROM studio.conversations "
            "WHERE inbox_id = :i AND platform_conversation_id = :p"
        ),
        {"i": inbox_id, "p": pcid},
    ).scalar_one()
    r = account.http.patch(
        f"/api/conversations/{conv_id}", json={"takeover": True}
    )
    assert r.status_code == 200

    rows = bridge.http.get("/api/bridge/takeovers").json()["takeovers"]
    assert any(r["platform_conversation_id"] == pcid and r["inbox_id"] == inbox_id for r in rows)
