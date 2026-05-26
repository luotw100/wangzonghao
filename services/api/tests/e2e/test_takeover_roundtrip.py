"""End-to-end: simulated Bridge → Studio → Bridge round-trip.

We don't exercise the LLM reply worker (no fake provider is plumbed in
this test suite), but we do exercise every other moving piece:

  1. Bridge handshake + register inbox + upsert conversation.
  2. Inbound message from peer → persisted in studio.messages.
  3. Web UI flips takeover=true → /api/bridge/takeovers reflects it.
  4. Web UI seeds an outbound (mirrors what ReplyBrain would write).
  5. Bridge long-polls /api/bridge/outbound and gets it.
  6. Bridge "sends" → reports inbound from_self with same content.
  7. outbound_messages row flips PENDING → DELIVERED.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import text


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def test_full_takeover_round(account, bridge, db):
    # --- 1. register inbox + conversation
    self_id = f"self-{uuid.uuid4().hex[:8]}"
    ib = bridge.http.post(
        "/api/bridge/inboxes",
        json={
            "inboxes": [{
                "platform": "chat",
                "platform_self_id": self_id,
                "display_name": "MyBot",
            }]
        },
    ).json()["inboxes"][0]
    inbox_id = ib["id"]
    pcid = f"pc-{uuid.uuid4().hex[:8]}"
    bridge.http.post(
        "/api/bridge/conversations",
        json={
            "inbox_id": inbox_id,
            "conversations": [{
                "platform_conversation_id": pcid,
                "kind": "dm",
                "display_name": "peer-name",
                "members": [{"peer_platform_id": "peer-1", "display_name": "Peer"}],
            }],
        },
    )

    # --- 2. inbound from peer
    bridge.http.post(
        "/api/bridge/incoming",
        json={
            "messages": [{
                "inbox_id": inbox_id,
                "platform_conversation_id": pcid,
                "client_id": "peer-msg-1",
                "sender_id": "peer-1",
                "msg_type": "text",
                "content": "你好啊",
                "sent_at": _now_iso(),
            }]
        },
    )
    conv_id = db.execute(
        text(
            "SELECT id FROM studio.conversations "
            "WHERE inbox_id = :i AND platform_conversation_id = :p"
        ),
        {"i": inbox_id, "p": pcid},
    ).scalar_one()
    inbound_content = db.execute(
        text("SELECT content FROM studio.messages WHERE conversation_id = :c"),
        {"c": conv_id},
    ).scalar_one()
    assert inbound_content == "你好啊"

    # --- 3. web flips takeover
    account.http.patch(f"/api/conversations/{conv_id}", json={"takeover": True})
    takeovers = bridge.http.get("/api/bridge/takeovers").json()["takeovers"]
    assert any(t["platform_conversation_id"] == pcid for t in takeovers)

    # --- 4. seed outbound (stand-in for ReplyBrain output)
    reply_text = "你好，很高兴认识你"
    account.http.post(
        f"/api/conversations/{conv_id}/outbound",
        json={"msg_type": "text", "content": reply_text},
    )

    # --- 5. bridge long-polls and receives it
    out = bridge.http.get("/api/bridge/outbound", params={"timeout": 2}).json()
    assert any(o["content"] == reply_text and o["platform_conversation_id"] == pcid for o in out)

    # --- 6. bridge "sends" then reports from_self
    bridge.http.post(
        "/api/bridge/incoming",
        json={
            "messages": [{
                "inbox_id": inbox_id,
                "platform_conversation_id": pcid,
                "client_id": "self-echo-1",
                "sender_id": None,
                "msg_type": "text",
                "content": reply_text,
                "sent_at": _now_iso(),
            }]
        },
    )

    # --- 7. outbound row should now be DELIVERED
    db.expire_all()
    status, delivered_at = db.execute(
        text(
            "SELECT status, delivered_at FROM studio.outbound_messages "
            "WHERE conversation_id = :c AND content = :ct"
        ),
        {"c": conv_id, "ct": reply_text},
    ).one()
    assert status == "delivered"
    assert delivered_at is not None
