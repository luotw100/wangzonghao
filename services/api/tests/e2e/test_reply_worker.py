"""End-to-end: live user-worker driving a reply round against fake-llm.

Pipeline exercised:
  bridge → /incoming peer msg
  scheduler picks (autoreply + persona + new msg from peer)
  ReplyBrain.maybe_reply → fake-llm → parse chunks → write OutboundMessage(s)
  + LlmLog + bump conversation.last_reply_round_at
  bridge long-poll → receives outbound → reports from_self → DELIVERED
"""

import time
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _wait_for(predicate, timeout=15.0, interval=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    return None


def _setup_autoreply_conv(account, bridge, admin, db, fake_llm_provider_id):
    pid = account.http.post(
        "/api/personas",
        json={"name": f"p-{uuid.uuid4().hex[:6]}", "persona_md": "你是测试助手", "timezone": "UTC"},
    ).json()["id"]

    inbox_id = bridge.http.post(
        "/api/bridge/inboxes",
        json={"inboxes": [{
            "platform": "chat",
            "platform_self_id": f"self-{uuid.uuid4().hex[:6]}",
            "display_name": "Bot",
        }]},
    ).json()["inboxes"][0]["id"]
    pcid = f"pc-{uuid.uuid4().hex[:8]}"
    bridge.http.post(
        "/api/bridge/conversations",
        json={
            "inbox_id": inbox_id,
            "conversations": [{
                "platform_conversation_id": pcid,
                "kind": "dm",
                "display_name": "peer",
                "members": [{"peer_platform_id": "peer-1", "display_name": "Peer"}],
            }],
        },
    )
    conv_id = db.execute(
        text(
            "SELECT id FROM studio.conversations "
            "WHERE inbox_id = :i AND platform_conversation_id = :p"
        ),
        {"i": inbox_id, "p": pcid},
    ).scalar_one()
    # Flip takeover/autoreply/persona via web API.
    r = account.http.patch(
        f"/api/conversations/{conv_id}",
        json={"takeover": True, "reply_policy": "autoreply", "persona_id": pid},
    )
    assert r.status_code == 200
    # Point the conversation's reply provider at fake-llm via admin.
    r = admin.patch(
        f"/api/admin/conversations/{conv_id}/provider",
        json={"provider_id": fake_llm_provider_id},
    )
    assert r.status_code == 204
    return inbox_id, conv_id, pcid


def test_worker_generates_reply_via_fake_llm(account, bridge, admin, db, fake_llm_provider_id):
    inbox_id, conv_id, pcid = _setup_autoreply_conv(
        account, bridge, admin, db, fake_llm_provider_id
    )

    peer_text = "你好啊"
    bridge.http.post(
        "/api/bridge/incoming",
        json={"messages": [{
            "inbox_id": inbox_id,
            "platform_conversation_id": pcid,
            "client_id": f"peer-{uuid.uuid4().hex}",
            "sender_id": "peer-1",
            "msg_type": "text",
            "content": peer_text,
            "sent_at": _now_iso(),
        }]},
    )

    def _check():
        db.expire_all()
        row = db.execute(
            text(
                "SELECT content FROM studio.outbound_messages "
                "WHERE conversation_id = :c ORDER BY id ASC LIMIT 1"
            ),
            {"c": conv_id},
        ).first()
        return row

    row = _wait_for(_check, timeout=15.0)
    assert row is not None, "worker did not produce an outbound row within 15s"
    # fake-llm returns synthetic filler (length-distributed), so we only assert
    # a non-empty reply was produced — not its content.
    assert isinstance(row.content, str) and row.content.strip()

    # last_reply_round_at must be bumped.
    last = db.execute(
        text("SELECT last_reply_round_at FROM studio.conversations WHERE id = :c"),
        {"c": conv_id},
    ).scalar_one()
    assert last is not None

    # llm_logs has an entry with the same model.
    log_row = db.execute(
        text(
            "SELECT model, response_raw FROM studio.llm_logs "
            "WHERE inbox_id = :i ORDER BY id DESC LIMIT 1"
        ),
        {"i": inbox_id},
    ).first()
    assert log_row is not None
    assert log_row.model == "fake-model"


def test_worker_outbound_typing_rhythm(account, bridge, admin, db, fake_llm_provider_id):
    """A reply is split into one or more OutboundMessage rows whose send_after
    is non-decreasing (typing rhythm). fake-llm picks the chunk count from a
    distribution, so we assert the rhythm invariant over however many rows it
    produces, not an exact count."""
    inbox_id, conv_id, pcid = _setup_autoreply_conv(
        account, bridge, admin, db, fake_llm_provider_id
    )
    bridge.http.post(
        "/api/bridge/incoming",
        json={"messages": [{
            "inbox_id": inbox_id,
            "platform_conversation_id": pcid,
            "client_id": f"rhythm-{uuid.uuid4().hex}",
            "sender_id": "peer-1",
            "msg_type": "text",
            "content": "在吗",
            "sent_at": _now_iso(),
        }]},
    )

    def _check():
        db.expire_all()
        rows = db.execute(
            text(
                "SELECT content, send_after FROM studio.outbound_messages "
                "WHERE conversation_id = :c ORDER BY id ASC"
            ),
            {"c": conv_id},
        ).all()
        return rows or None

    rows = _wait_for(_check, timeout=15.0)
    assert rows is not None, "worker did not produce any outbound row within 15s"
    assert all(isinstance(r.content, str) and r.content.strip() for r in rows)
    # send_after non-decreasing across chunks.
    for i in range(1, len(rows)):
        assert rows[i].send_after >= rows[i - 1].send_after
