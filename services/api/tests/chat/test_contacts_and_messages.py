import uuid
import time

from sqlalchemy import text


def _make_contact(account, nickname="peer", username=None):
    body = {"nickname": nickname}
    if username:
        body["username"] = username
    r = account.http.post("/api/chat/contacts", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _conv_of(account, contact_id):
    convs = account.http.get("/api/chat/conversations").json()
    for c in convs:
        if c["contact_id"] == contact_id:
            return c
    raise AssertionError("conversation not auto-created")


def test_create_contact_autocreates_conversation(account, db):
    c = _make_contact(account, nickname="alice")
    assert c["nickname"] == "alice"
    assert c["account_id"] == account.id

    conv = _conv_of(account, c["id"])
    assert conv["contact"]["id"] == c["id"]

    n = db.execute(
        text("SELECT count(*) FROM chat.conversations WHERE contact_id = :c"),
        {"c": c["id"]},
    ).scalar_one()
    assert n == 1


def test_duplicate_username_409(account):
    uname = f"u-{uuid.uuid4().hex[:8]}"
    _make_contact(account, username=uname)
    r = account.http.post("/api/chat/contacts", json={"nickname": "x", "username": uname})
    assert r.status_code == 409


def test_contacts_isolated_per_account(account_factory):
    a, b = account_factory(), account_factory()
    _make_contact(a, nickname="alice-of-a")
    _make_contact(b, nickname="alice-of-b")
    a_names = {c["nickname"] for c in a.http.get("/api/chat/contacts").json()}
    b_names = {c["nickname"] for c in b.http.get("/api/chat/contacts").json()}
    assert "alice-of-a" in a_names and "alice-of-a" not in b_names


def test_send_messages_and_paginate(account, db):
    c = _make_contact(account)
    conv = _conv_of(account, c["id"])
    r = account.http.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={
            "messages": [
                {"sender_id": None, "msg_type": "text", "content": "hi"},
                {"sender_id": c["id"], "msg_type": "text", "content": "hey"},
            ]
        },
    )
    assert r.status_code == 200
    assert r.json()["count"] == 2

    rows = db.execute(
        text(
            "SELECT content, sender_id FROM chat.messages "
            "WHERE conversation_id = :c ORDER BY id ASC"
        ),
        {"c": conv["id"]},
    ).all()
    assert [(r.content, r.sender_id) for r in rows] == [
        ("hi", None),
        ("hey", c["id"]),
    ]


def test_send_message_invalid_sender_400(account):
    c = _make_contact(account)
    conv = _conv_of(account, c["id"])
    r = account.http.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={
            "messages": [
                {"sender_id": "ct_random_outsider", "msg_type": "text", "content": "x"}
            ]
        },
    )
    assert r.status_code == 400


def test_send_media_message_requires_account_prefix(account):
    c = _make_contact(account)
    conv = _conv_of(account, c["id"])
    r = account.http.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={
            "messages": [
                {"sender_id": None, "msg_type": "image", "content": "media/other/abc"}
            ]
        },
    )
    assert r.status_code == 400


def test_long_poll_after_returns_quickly_when_empty(account):
    c = _make_contact(account)
    conv = _conv_of(account, c["id"])
    t0 = time.time()
    r = account.http.get(
        f"/api/chat/conversations/{conv['id']}/messages/after",
        params={"last_id": 0, "timeout": 1},
    )
    elapsed = time.time() - t0
    assert r.status_code == 200
    assert r.json()["messages"] == []
    assert elapsed < 3


def test_long_poll_after_wakes_on_new_message(account):
    """Long-poll should wake immediately when a message is posted via NOTIFY."""
    import threading

    c = _make_contact(account)
    conv = _conv_of(account, c["id"])
    last_id = 0
    holder = {}

    def poll():
        r = account.http.get(
            f"/api/chat/conversations/{conv['id']}/messages/after",
            params={"last_id": last_id, "timeout": 10},
        )
        holder["resp"] = r

    th = threading.Thread(target=poll)
    th.start()
    time.sleep(0.5)
    account.http.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"messages": [{"sender_id": None, "msg_type": "text", "content": "wake"}]},
    )
    th.join(timeout=8)
    assert "resp" in holder
    r = holder["resp"]
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) >= 1
    assert msgs[-1]["content"] == "wake"


def test_uploads_presign(account):
    r = account.http.post(
        "/api/chat/uploads/presign",
        json={"filename": "x.jpg", "mime_type": "image/jpeg"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["storage_key"].startswith(f"media/{account.id}/")
    assert "upload_url" in body and "fields" in body


def test_uploads_presign_rejects_svg(account):
    r = account.http.post(
        "/api/chat/uploads/presign",
        json={"filename": "x.svg", "mime_type": "image/svg+xml"},
    )
    assert r.status_code == 400


def test_media_endpoint_rejects_other_account(account_factory):
    a, b = account_factory(), account_factory()
    key_a = a.http.post(
        "/api/chat/uploads/presign",
        json={"filename": "a.jpg", "mime_type": "image/jpeg"},
    ).json()["storage_key"]
    # b cannot fetch a's media (storage key prefix check).
    r = b.http.get(f"/api/chat/media/{key_a}", follow_redirects=False)
    assert r.status_code == 403
