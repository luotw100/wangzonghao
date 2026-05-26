from sqlalchemy import text


def test_health(studio):
    r = studio.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_login_returns_token_and_account(account, studio):
    r = studio.post(
        "/api/auth/login",
        json={"username": account.username, "password": account.password},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["account"]["id"] == account.id
    assert body["account"]["username"] == account.username
    assert body["account"]["status"] == "active"


def test_login_wrong_password_401(account, studio):
    r = studio.post(
        "/api/auth/login",
        json={"username": account.username, "password": "wrong"},
    )
    assert r.status_code == 401


def test_me_with_token(account):
    r = account.http.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["id"] == account.id


def test_me_without_token_401(studio):
    r = studio.get("/api/auth/me")
    assert r.status_code == 401


def test_logout_invalidates_token(account):
    r = account.http.post("/api/auth/logout")
    assert r.status_code == 204
    r = account.http.get("/api/auth/me")
    assert r.status_code == 401


def test_login_creates_session_row(account, db):
    # Each login made by account_factory wrote an auth.auth_sessions row.
    n = db.execute(
        text("SELECT count(*) FROM auth.auth_sessions WHERE account_id = :aid"),
        {"aid": account.id},
    ).scalar_one()
    assert n >= 1


def test_change_password_revokes_all_sessions(account, studio):
    new_password = "fresh-secret-1234"
    r = account.http.put(
        "/api/auth/password",
        json={"current_password": account.password, "new_password": new_password},
    )
    assert r.status_code == 204
    # Old token now invalid.
    r = account.http.get("/api/auth/me")
    assert r.status_code == 401
    # New password works.
    r = studio.post(
        "/api/auth/login",
        json={"username": account.username, "password": new_password},
    )
    assert r.status_code == 200


def test_change_password_wrong_current_400(account):
    r = account.http.put(
        "/api/auth/password",
        json={"current_password": "nope", "new_password": "xxxxxxxx"},
    )
    assert r.status_code == 400
