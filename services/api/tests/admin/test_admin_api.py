import uuid

from sqlalchemy import text


def test_list_providers(admin, seed_provider_id):
    r = admin.get("/api/admin/providers")
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert seed_provider_id in ids


def test_allowed_base_urls(admin):
    r = admin.get("/api/admin/allowed-base-urls")
    assert r.status_code == 200
    urls = r.json()
    assert "https://api.openai.com/v1" in urls


def test_create_provider_invalid_base_url_400(admin):
    r = admin.post(
        "/api/admin/providers",
        json={
            "name": f"bad-{uuid.uuid4().hex[:6]}",
            "base_url": "https://evil.example.com/v1",
            "api_key": "sk-x",
            "model": "m",
        },
    )
    assert r.status_code == 400


def test_create_and_delete_provider(admin, db):
    name = f"tmp-{uuid.uuid4().hex[:8]}"
    r = admin.post(
        "/api/admin/providers",
        json={
            "name": name,
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-x",
            "model": "gpt-x",
        },
    )
    assert r.status_code == 201
    pid = r.json()["id"]
    n = db.execute(
        text("SELECT count(*) FROM studio.provider_configs WHERE id = :i"), {"i": pid}
    ).scalar_one()
    assert n == 1
    # Duplicate name 409.
    dup = admin.post(
        "/api/admin/providers",
        json={
            "name": name,
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-x",
            "model": "gpt-x",
        },
    )
    assert dup.status_code == 409
    # Delete.
    assert admin.delete(f"/api/admin/providers/{pid}").status_code == 204


def test_list_accounts_contains_created(admin, account):
    rows = admin.get("/api/admin/accounts").json()
    assert any(r["id"] == account.id for r in rows)


def test_admin_reset_password(admin, account, studio):
    new = "reset-pass-1234"
    r = admin.post(f"/api/admin/accounts/{account.id}/reset-password", json={"password": new})
    assert r.status_code == 204
    # Old password fails.
    assert studio.post(
        "/api/auth/login", json={"username": account.username, "password": account.password}
    ).status_code == 401
    # New password works.
    assert studio.post(
        "/api/auth/login", json={"username": account.username, "password": new}
    ).status_code == 200


def test_admin_create_account_duplicate_username(admin, account):
    r = admin.post(
        "/api/admin/accounts",
        json={"username": account.username, "password": "x", "display_name": "y"},
    )
    assert r.status_code == 409
