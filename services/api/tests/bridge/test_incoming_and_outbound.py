import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import text


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _setup_inbox_and_conv(bridge, account, platform_self_id=None):
    claim = {
        "platform": "chat",
        "platform_self_id": platform_self_id or f"selfid-{uuid.uuid4().hex[:8]}",
        "display_name": "me",
    }
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
    return inbox_id, pcid


def test_incoming_persists_messages(bridge, account, db):
    inbox_id, pcid = _setup_inbox_and_conv(bridge, account)
    msg = {
        "inbox_id": inbox_id,
        "platform_conversation_id": pcid,
        "client_id": f"cid-{uuid.uuid4().hex}",
        "sender_id": "peer-x",
        "msg_type": "text",
        "content": "hello from peer",
        "sent_at": _now_iso(),
    }
    r = bridge.http.post("/api/bridge/incoming", json={"messages": [msg]})
    assert r.status_code == 200
    assert r.json() == {"accepted": 1, "deduped": 0, "rejected": 0}

    row = db.execute(
        text(
            "SELECT m.content, m.sender_id FROM studio.messages m "
            "JOIN studio.conversations c ON c.id = m.conversation_id "
            "WHERE c.inbox_id = :i AND c.platform_conversation_id = :p"
        ),
        {"i": inbox_id, "p": pcid},
    ).one()
    assert row.content == "hello from peer"
    assert row.sender_id == "peer-x"


def test_incoming_dedup_by_client_id(bridge, account):
    inbox_id, pcid = _setup_inbox_and_conv(bridge, account)
    cid = f"cid-{uuid.uuid4().hex}"
    msg = {
        "inbox_id": inbox_id,
        "platform_conversation_id": pcid,
        "client_id": cid,
        "sender_id": "peer-x",
        "msg_type": "text",
        "content": "dup",
        "sent_at": _now_iso(),
    }
    bridge.http.post("/api/bridge/incoming", json={"messages": [msg]})
    r2 = bridge.http.post("/api/bridge/incoming", json={"messages": [msg]})
    assert r2.json() == {"accepted": 0, "deduped": 1, "rejected": 0}


def test_incoming_rejects_unknown_inbox(bridge, account):
    msg = {
        "inbox_id": "ib_does_not_exist",
        "platform_conversation_id": "x",
        "client_id": "y",
        "sender_id": "p",
        "msg_type": "text",
        "content": "z",
        "sent_at": _now_iso(),
    }
    r = bridge.http.post("/api/bridge/incoming", json={"messages": [msg]})
    assert r.json()["rejected"] == 1
    assert r.json()["accepted"] == 0


def test_incoming_creates_placeholder_conversation(bridge, account, db):
    # /incoming arriving before /conversations should create a placeholder.
    claim = {
        "platform": "chat",
        "platform_self_id": f"selfid-{uuid.uuid4().hex[:8]}",
        "display_name": "me",
    }
    inbox_id = bridge.http.post(
        "/api/bridge/inboxes", json={"inboxes": [claim]}
    ).json()["inboxes"][0]["id"]
    pcid = f"pc-{uuid.uuid4().hex[:8]}"
    msg = {
        "inbox_id": inbox_id,
        "platform_conversation_id": pcid,
        "client_id": f"cid-{uuid.uuid4().hex}",
        "sender_id": "peer",
        "msg_type": "text",
        "content": "first",
        "sent_at": _now_iso(),
    }
    bridge.http.post("/api/bridge/incoming", json={"messages": [msg]})
    kind = db.execute(
        text(
            "SELECT kind FROM studio.conversations "
            "WHERE inbox_id = :i AND platform_conversation_id = :p"
        ),
        {"i": inbox_id, "p": pcid},
    ).scalar_one()
    assert kind == "unknown"


def test_outbound_seed_and_longpoll(account, bridge, db):
    inbox_id, pcid = _setup_inbox_and_conv(bridge, account)
    conv_id = db.execute(
        text(
            "SELECT id FROM studio.conversations "
            "WHERE inbox_id = :i AND platform_conversation_id = :p"
        ),
        {"i": inbox_id, "p": pcid},
    ).scalar_one()

    r = account.http.post(
        f"/api/conversations/{conv_id}/outbound",
        json={"msg_type": "text", "content": "hello world"},
    )
    assert r.status_code == 201

    # Long-poll: pending row should be visible immediately.
    rows = bridge.http.get("/api/bridge/outbound", params={"timeout": 0}).json()
    assert any(
        r["platform_conversation_id"] == pcid and r["content"] == "hello world"
        for r in rows
    )


def test_outbound_ack_via_inbound_from_self(account, bridge, db):
    inbox_id, pcid = _setup_inbox_and_conv(bridge, account)
    conv_id = db.execute(
        text(
            "SELECT id FROM studio.conversations "
            "WHERE inbox_id = :i AND platform_conversation_id = :p"
        ),
        {"i": inbox_id, "p": pcid},
    ).scalar_one()
    account.http.post(
        f"/api/conversations/{conv_id}/outbound",
        json={"msg_type": "text", "content": "auto-ack-me"},
    )
    # Status starts as pending.
    status = db.execute(
        text(
            "SELECT status FROM studio.outbound_messages "
            "WHERE conversation_id = :c AND content = 'auto-ack-me'"
        ),
        {"c": conv_id},
    ).scalar_one()
    assert status == "pending"

    # Bridge reports "I just sent this" by pushing an inbound with sender_id=None.
    bridge.http.post(
        "/api/bridge/incoming",
        json={
            "messages": [
                {
                    "inbox_id": inbox_id,
                    "platform_conversation_id": pcid,
                    "client_id": f"cid-{uuid.uuid4().hex}",
                    "sender_id": None,
                    "msg_type": "text",
                    "content": "auto-ack-me",
                    "sent_at": _now_iso(),
                }
            ]
        },
    )
    db.expire_all()
    status = db.execute(
        text(
            "SELECT status FROM studio.outbound_messages "
            "WHERE conversation_id = :c AND content = 'auto-ack-me'"
        ),
        {"c": conv_id},
    ).scalar_one()
    assert status == "delivered"


def test_outbound_longpoll_empty_returns_quickly(bridge):
    t0 = time.time()
    r = bridge.http.get("/api/bridge/outbound", params={"timeout": 2})
    elapsed = time.time() - t0
    assert r.status_code == 200
    assert r.json() == []
    assert elapsed < 5
