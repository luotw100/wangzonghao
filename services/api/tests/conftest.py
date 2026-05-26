"""Shared fixtures for the in-container API test suite.

Runs inside the `test-runner` compose service: container shares the api
network so internal hostnames (`user-api`, `admin-api`, `db`, `minio`)
resolve. All tests hit the live stack — no mocks. Each test creates its
own account (and, where relevant, its own bridge) so the suite is safe
to run repeatedly without wiping the database.
"""

from __future__ import annotations

import os
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Iterator

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

STUDIO_URL = os.environ.get("STUDIO_BASE_URL", "http://user-api:23456")
ADMIN_URL = os.environ.get("ADMIN_BASE_URL", "http://admin-api:23457")
DATABASE_URL = os.environ["DATABASE_URL"]


# ---------------------------------------------------------------------------
# Stack readiness
# ---------------------------------------------------------------------------

def _wait_for(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code < 500:
                return
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(0.5)
    raise RuntimeError(f"service not ready at {url}: {last}")


@pytest.fixture(scope="session", autouse=True)
def _wait_for_stack() -> None:
    _wait_for(f"{STUDIO_URL}/api/health")
    _wait_for(f"{ADMIN_URL}/api/admin/providers")


# ---------------------------------------------------------------------------
# DB session (read-only assertions; tests do not write directly)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def db_engine():
    return create_engine(DATABASE_URL, future=True, pool_pre_ping=True)


@pytest.fixture()
def db(db_engine) -> Iterator[Session]:
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


# ---------------------------------------------------------------------------
# HTTP clients
# ---------------------------------------------------------------------------

@pytest.fixture()
def studio() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=STUDIO_URL, timeout=30.0) as c:
        yield c


@pytest.fixture()
def admin() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=ADMIN_URL, timeout=30.0) as c:
        yield c


# ---------------------------------------------------------------------------
# Provider pool — ensure at least one provider exists for account creation
# and conversation seeding.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def fake_llm_provider_id() -> str:
    """A ProviderConfig whose base_url points at the fake-llm container.
    Created once per session; reused across tests. Allows the live
    user-worker to drive a deterministic reply round.
    """
    name = "test-fake-llm"
    with httpx.Client(base_url=ADMIN_URL, timeout=10.0) as c:
        existing = c.get("/api/admin/providers").json()
        for p in existing:
            if p["name"] == name:
                return p["id"]
        body = {
            "name": name,
            "base_url": "http://fake-llm:8080/v1",
            "api_key": "sk-fake",
            "model": "fake-model",
        }
        r = c.post("/api/admin/providers", json=body)
        r.raise_for_status()
        return r.json()["id"]


@pytest.fixture(scope="session")
def seed_provider_id() -> str:
    """Ensure there is at least one ProviderConfig in the pool. Returns
    the id of the first (created_at asc) provider, i.e. the one
    pick_first_provider would return.
    """
    with httpx.Client(base_url=ADMIN_URL, timeout=10.0) as c:
        r = c.get("/api/admin/providers")
        r.raise_for_status()
        existing = r.json()
        if existing:
            return existing[0]["id"]
        body = {
            "name": f"test-seed-{uuid.uuid4().hex[:8]}",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test-not-used-by-tests",
            "model": "gpt-test",
        }
        r = c.post("/api/admin/providers", json=body)
        r.raise_for_status()
        return r.json()["id"]


# ---------------------------------------------------------------------------
# Account factory
# ---------------------------------------------------------------------------

@dataclass
class TestAccount:
    id: str
    username: str
    password: str
    token: str
    http: httpx.Client

    def close(self) -> None:
        self.http.close()


def _unique_username() -> str:
    return f"t-{uuid.uuid4().hex[:10]}"


def _make_account(admin_client: httpx.Client) -> tuple[str, str, str]:
    """Create an account via admin-api. Returns (account_id, username, password)."""
    username = _unique_username()
    password = secrets.token_urlsafe(12)
    r = admin_client.post(
        "/api/admin/accounts",
        json={"username": username, "password": password, "display_name": username},
    )
    r.raise_for_status()
    return r.json()["id"], username, password


def _login(studio_client: httpx.Client, username: str, password: str) -> str:
    r = studio_client.post("/api/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    return r.json()["token"]


@pytest.fixture()
def account_factory(seed_provider_id, admin, studio):
    created: list[TestAccount] = []

    def _make() -> TestAccount:
        acc_id, username, password = _make_account(admin)
        token = _login(studio, username, password)
        http = httpx.Client(
            base_url=STUDIO_URL,
            timeout=30.0,
            headers={"Authorization": f"Bearer {token}"},
        )
        a = TestAccount(id=acc_id, username=username, password=password, token=token, http=http)
        created.append(a)
        return a

    yield _make
    for a in created:
        a.close()


@pytest.fixture()
def account(account_factory) -> TestAccount:
    return account_factory()


# ---------------------------------------------------------------------------
# Bridge factory (for tests that need a registered bridge daemon view).
# ---------------------------------------------------------------------------

@dataclass
class BridgeSession:
    account_id: str
    machine_id: str
    token: str
    http: httpx.Client  # already carries Authorization + X-Machine-Id

    def close(self) -> None:
        self.http.close()


@pytest.fixture()
def bridge_factory(studio):
    created: list[BridgeSession] = []

    def _make(account: TestAccount) -> BridgeSession:
        r = studio.post(
            "/api/bridge/handshake",
            json={"username": account.username, "password": account.password},
        )
        r.raise_for_status()
        body = r.json()
        token = body["token"]
        machine_id = body["machine_id"]
        http = httpx.Client(
            base_url=STUDIO_URL,
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Machine-Id": machine_id,
            },
        )
        s = BridgeSession(
            account_id=body["account_id"],
            machine_id=machine_id,
            token=token,
            http=http,
        )
        created.append(s)
        return s

    yield _make
    for s in created:
        s.close()


@pytest.fixture()
def bridge(account, bridge_factory) -> BridgeSession:
    return bridge_factory(account)
