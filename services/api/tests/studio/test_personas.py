from sqlalchemy import text


def test_create_persona(account, db):
    r = account.http.post(
        "/api/personas",
        json={"name": "alice", "persona_md": "# hi", "timezone": "Asia/Shanghai"},
    )
    assert r.status_code == 201
    p = r.json()
    assert p["name"] == "alice"
    assert p["persona_md"] == "# hi"
    assert p["timezone"] == "Asia/Shanghai"
    assert p["account_id"] == account.id

    row = db.execute(
        text("SELECT name, persona_md, timezone, account_id FROM studio.personas WHERE id = :i"),
        {"i": p["id"]},
    ).one()
    assert row.name == "alice"
    assert row.account_id == account.id


def test_duplicate_name_409(account):
    body = {"name": "dup", "persona_md": "", "timezone": "UTC"}
    assert account.http.post("/api/personas", json=body).status_code == 201
    assert account.http.post("/api/personas", json=body).status_code == 409


def test_invalid_timezone_422(account):
    r = account.http.post(
        "/api/personas",
        json={"name": "tz-bad", "persona_md": "", "timezone": "Mars/Olympus"},
    )
    assert r.status_code == 422


def test_list_only_own_personas(account_factory):
    a = account_factory()
    b = account_factory()
    a.http.post("/api/personas", json={"name": "p-a", "persona_md": "", "timezone": "UTC"})
    b.http.post("/api/personas", json={"name": "p-b", "persona_md": "", "timezone": "UTC"})
    names_a = {p["name"] for p in a.http.get("/api/personas").json()}
    names_b = {p["name"] for p in b.http.get("/api/personas").json()}
    assert "p-a" in names_a and "p-b" not in names_a
    assert "p-b" in names_b and "p-a" not in names_b


def test_patch_persona(account):
    pid = account.http.post(
        "/api/personas",
        json={"name": "orig", "persona_md": "x", "timezone": "UTC"},
    ).json()["id"]
    r = account.http.patch(f"/api/personas/{pid}", json={"persona_md": "updated"})
    assert r.status_code == 200
    assert r.json()["persona_md"] == "updated"


def test_delete_persona(account, db):
    pid = account.http.post(
        "/api/personas",
        json={"name": "togo", "persona_md": "", "timezone": "UTC"},
    ).json()["id"]
    r = account.http.delete(f"/api/personas/{pid}")
    assert r.status_code == 204
    n = db.execute(
        text("SELECT count(*) FROM studio.personas WHERE id = :i"), {"i": pid}
    ).scalar_one()
    assert n == 0


def test_get_others_persona_404(account_factory):
    a, b = account_factory(), account_factory()
    pid = a.http.post(
        "/api/personas", json={"name": "secret", "persona_md": "", "timezone": "UTC"}
    ).json()["id"]
    assert b.http.get(f"/api/personas/{pid}").status_code == 404
