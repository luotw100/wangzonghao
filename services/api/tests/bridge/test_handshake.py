from sqlalchemy import text


def test_handshake_first_time_mints_machine_id(account, studio, db):
    r = studio.post(
        "/api/bridge/handshake",
        json={"username": account.username, "password": account.password},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["account_id"] == account.id
    assert body["username"] == account.username
    assert body["token"]
    assert len(body["machine_id"]) == 4

    row = db.execute(
        text(
            "SELECT account_id, machine_id FROM studio.bridges "
            "WHERE account_id = :a AND machine_id = :m"
        ),
        {"a": account.id, "m": body["machine_id"]},
    ).one()
    assert row.account_id == account.id


def test_handshake_echo_machine_id_reuses_row(account, studio, db):
    r1 = studio.post(
        "/api/bridge/handshake",
        json={"username": account.username, "password": account.password},
    ).json()
    r2 = studio.post(
        "/api/bridge/handshake",
        json={
            "username": account.username,
            "password": account.password,
            "machine_id": r1["machine_id"],
        },
    )
    assert r2.status_code == 200
    assert r2.json()["machine_id"] == r1["machine_id"]
    n = db.execute(
        text("SELECT count(*) FROM studio.bridges WHERE account_id = :a"),
        {"a": account.id},
    ).scalar_one()
    assert n == 1


def test_handshake_unknown_machine_id_400(account, studio):
    r = studio.post(
        "/api/bridge/handshake",
        json={
            "username": account.username,
            "password": account.password,
            "machine_id": "ZZZZ",
        },
    )
    assert r.status_code == 400


def test_handshake_wrong_password_401(account, studio):
    r = studio.post(
        "/api/bridge/handshake",
        json={"username": account.username, "password": "wrong"},
    )
    assert r.status_code == 401


def test_heartbeat_updates_last_seen(bridge, db):
    before = db.execute(
        text("SELECT last_seen_at FROM studio.bridges WHERE machine_id = :m"),
        {"m": bridge.machine_id},
    ).scalar_one()
    r = bridge.http.post("/api/bridge/heartbeat")
    assert r.status_code == 200
    db.expire_all()
    after = db.execute(
        text("SELECT last_seen_at FROM studio.bridges WHERE machine_id = :m"),
        {"m": bridge.machine_id},
    ).scalar_one()
    assert after >= before


def test_bridges_list_via_web_api(account, bridge):
    rows = account.http.get("/api/bridges").json()
    machines = {b["machine_id"] for b in rows}
    assert bridge.machine_id in machines
