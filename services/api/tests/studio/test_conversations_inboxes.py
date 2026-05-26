import uuid
from datetime import datetime, timezone

from sqlalchemy import text


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _make_inbox_with_conv(bridge, account, db):
    claim = {
        "platform": "chat",
        "platform_self_id": f"selfid-{uuid.uuid4().hex[:8]}",
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
    conv_id = db.execute(
        text(
            "SELECT id FROM studio.conversations "
            "WHERE inbox_id = :i AND platform_conversation_id = :p"
        ),
        {"i": inbox_id, "p": pcid},
    ).scalar_one()
    return inbox_id, conv_id, pcid


def test_inboxes_list_isolated_per_account(account_factory, bridge_factory):
    a = account_factory()
    b = account_factory()
    bridge_factory(a).http.post(
        "/api/bridge/inboxes",
        json={
            "inboxes": [{
                "platform": "chat",
                "platform_self_id": "a-self",
                "display_name": "Alice",
            }]
        },
    )
    assert any(i["display_name"] == "Alice" for i in a.http.get("/api/inboxes").json())
    assert not any(i["display_name"] == "Alice" for i in b.http.get("/api/inboxes").json())


def test_patch_conversation_takeover_and_reply_policy(account, bridge, db):
    inbox_id, conv_id, _ = _make_inbox_with_conv(bridge, account, db)
    pid = account.http.post(
        "/api/personas", json={"name": f"p-{uuid.uuid4().hex[:6]}", "persona_md": "", "timezone": "UTC"}
    ).json()["id"]
    r = account.http.patch(
        f"/api/conversations/{conv_id}",
        json={"takeover": True, "reply_policy": "autoreply", "persona_id": pid, "card_md": "hello"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["takeover"] is True
    assert body["reply_policy"] == "autoreply"
    assert body["persona_id"] == pid
    assert body["card_md"] == "hello"


def test_list_conversation_messages(account, bridge, db):
    inbox_id, conv_id, pcid = _make_inbox_with_conv(bridge, account, db)
    bridge.http.post(
        "/api/bridge/incoming",
        json={
            "messages": [
                {
                    "inbox_id": inbox_id,
                    "platform_conversation_id": pcid,
                    "client_id": "c1",
                    "sender_id": "peer-x",
                    "msg_type": "text",
                    "content": "msg-one",
                    "sent_at": _now_iso(),
                },
                {
                    "inbox_id": inbox_id,
                    "platform_conversation_id": pcid,
                    "client_id": "c2",
                    "sender_id": "peer-x",
                    "msg_type": "text",
                    "content": "msg-two",
                    "sent_at": _now_iso(),
                },
            ]
        },
    )
    msgs = account.http.get(f"/api/conversations/{conv_id}/messages").json()
    contents = [m["content"] for m in msgs]
    assert "msg-one" in contents and "msg-two" in contents


def test_other_account_cannot_see_conversation(account_factory, bridge_factory, db):
    a, b = account_factory(), account_factory()
    br = bridge_factory(a)
    inbox_id, conv_id, _ = _make_inbox_with_conv(br, a, db)
    assert b.http.get(f"/api/conversations/{conv_id}").status_code == 404


def test_delete_bridge_cancels_pending_outbound(account, bridge, db):
    inbox_id, conv_id, _ = _make_inbox_with_conv(bridge, account, db)
    account.http.post(
        f"/api/conversations/{conv_id}/outbound",
        json={"msg_type": "text", "content": "will-cancel"},
    )
    bridge_row_id = db.execute(
        text("SELECT id FROM studio.bridges WHERE machine_id = :m"),
        {"m": bridge.machine_id},
    ).scalar_one()
    r = account.http.delete(f"/api/bridges/{bridge_row_id}")
    assert r.status_code == 204
    db.expire_all()
    status = db.execute(
        text(
            "SELECT status FROM studio.outbound_messages "
            "WHERE conversation_id = :c AND content = 'will-cancel'"
        ),
        {"c": conv_id},
    ).scalar_one()
    assert status == "canceled"
    # Inbox unbound.
    bridge_id = db.execute(
        text("SELECT bridge_id FROM studio.inboxes WHERE id = :i"),
        {"i": inbox_id},
    ).scalar_one()
    assert bridge_id is None
