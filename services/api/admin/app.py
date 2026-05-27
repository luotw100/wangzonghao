"""Laborster Admin API.

No auth middleware here — auth is delegated to Cloudflare Access, which
verifies the user's identity at the edge before traffic reaches this service.
"""
import json
import os
import urllib.error
import urllib.request
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from studio.auth_utils import hash_password, hash_token
from studio.clients import ALLOWED_BASE_URLS
from studio.db import get_db, utc_now
from studio.deps import create_auth_session, new_id, pick_first_provider
from studio.enums import AccountStatus, HostedBridgeStatus
from studio.models import (
    Account,
    AuthSession,
    Bridge,
    Conversation,
    HostedBridge,
    Inbox,
    Persona,
    ProviderConfig,
)
from studio.routers.bridge_protocol import ensure_bridge_row

BRIDGE_HOST_URL = os.environ.get("BRIDGE_HOST_URL", "http://bridge-host:23458")
BRIDGE_HOST_STUDIO_URL = os.environ.get("BRIDGE_HOST_STUDIO_URL", "http://user-api:23456")

app = FastAPI(
    title="Laborster Admin API",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

DbDep = Annotated[Session, Depends(get_db)]


def _mask(key: str | None) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class AccountOut(BaseModel):
    id: str
    username: str
    display_name: str
    status: str
    distill_provider_id: str
    distill_provider_name: str
    created_at: str
    updated_at: str


class CreateAccountIn(BaseModel):
    username: str
    password: str
    display_name: str


class ResetPasswordIn(BaseModel):
    password: str


class SetDistillProviderIn(BaseModel):
    provider_id: str


@app.get("/api/admin/accounts", response_model=list[AccountOut])
def list_accounts(db: DbDep):
    rows = (
        db.query(Account, ProviderConfig.name)
        .join(ProviderConfig, ProviderConfig.id == Account.distill_provider_id)
        .order_by(Account.created_at.asc())
        .all()
    )
    return [
        AccountOut(
            id=a.id,
            username=a.username,
            display_name=a.display_name,
            status=a.status,
            distill_provider_id=a.distill_provider_id,
            distill_provider_name=pname,
            created_at=a.created_at.isoformat(),
            updated_at=a.updated_at.isoformat(),
        )
        for a, pname in rows
    ]


@app.post("/api/admin/accounts", response_model=AccountOut, status_code=201)
def create_account(body: CreateAccountIn, db: DbDep):
    if db.query(Account).filter(Account.username == body.username).first():
        raise HTTPException(409, "用户名已存在")
    provider = pick_first_provider(db)
    if not provider:
        raise HTTPException(409, "尚未配置任何 Provider，请先创建 Provider")
    now = utc_now()
    account = Account(
        id=new_id("acc"),
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        status=AccountStatus.ACTIVE,
        distill_provider_id=provider.id,
        created_at=now,
        updated_at=now,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return AccountOut(
        id=account.id,
        username=account.username,
        display_name=account.display_name,
        status=account.status,
        distill_provider_id=account.distill_provider_id,
        distill_provider_name=provider.name,
        created_at=account.created_at.isoformat(),
        updated_at=account.updated_at.isoformat(),
    )


@app.post("/api/admin/accounts/{account_id}/reset-password", status_code=204)
def reset_password(account_id: str, body: ResetPasswordIn, db: DbDep):
    a = db.query(Account).filter(Account.id == account_id).first()
    if not a:
        raise HTTPException(404, "账号不存在")
    a.password_hash = hash_password(body.password)
    a.updated_at = utc_now()
    db.commit()


@app.patch("/api/admin/accounts/{account_id}/distill-provider", status_code=204)
def set_distill_provider(account_id: str, body: SetDistillProviderIn, db: DbDep):
    a = db.query(Account).filter(Account.id == account_id).first()
    if not a:
        raise HTTPException(404, "账号不存在")
    p = db.query(ProviderConfig).filter(ProviderConfig.id == body.provider_id).first()
    if not p:
        raise HTTPException(404, "Provider 不存在")
    a.distill_provider_id = p.id
    a.updated_at = utc_now()
    db.commit()


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class ProviderOut(BaseModel):
    id: str
    name: str
    base_url: str
    model: str
    api_key_masked: str
    created_at: str
    updated_at: str


class CreateProviderIn(BaseModel):
    name: str
    base_url: str
    api_key: str | None = None
    model: str


class UpdateProviderIn(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


def _validate_base_url(url: str) -> str:
    normalized = url.rstrip("/")
    if normalized not in ALLOWED_BASE_URLS:
        raise HTTPException(400, f"base_url 不在白名单: {url!r}")
    return normalized


def _provider_out(p: ProviderConfig) -> ProviderOut:
    return ProviderOut(
        id=p.id,
        name=p.name,
        base_url=p.base_url,
        model=p.model,
        api_key_masked=_mask(p.api_key),
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
    )


@app.get("/api/admin/providers", response_model=list[ProviderOut])
def list_providers(db: DbDep):
    return [_provider_out(p) for p in db.query(ProviderConfig).order_by(ProviderConfig.created_at.asc()).all()]


@app.get("/api/admin/allowed-base-urls", response_model=list[str])
def allowed_base_urls():
    return sorted(ALLOWED_BASE_URLS)


@app.post("/api/admin/providers", response_model=ProviderOut, status_code=201)
def create_provider(body: CreateProviderIn, db: DbDep):
    if db.query(ProviderConfig).filter(ProviderConfig.name == body.name).first():
        raise HTTPException(409, "Provider 名称已存在")
    base_url = _validate_base_url(body.base_url)
    now = utc_now()
    p = ProviderConfig(
        id=new_id("p"),
        name=body.name,
        base_url=base_url,
        api_key=body.api_key,
        model=body.model,
        created_at=now,
        updated_at=now,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _provider_out(p)


@app.patch("/api/admin/providers/{provider_id}", response_model=ProviderOut)
def update_provider(provider_id: str, body: UpdateProviderIn, db: DbDep):
    p = db.query(ProviderConfig).filter(ProviderConfig.id == provider_id).first()
    if not p:
        raise HTTPException(404, "Provider 不存在")
    if body.name is not None:
        clash = db.query(ProviderConfig).filter(
            ProviderConfig.name == body.name, ProviderConfig.id != p.id
        ).first()
        if clash:
            raise HTTPException(409, "Provider 名称已被占用")
        p.name = body.name
    if body.base_url is not None:
        p.base_url = _validate_base_url(body.base_url)
    if body.api_key is not None:
        p.api_key = body.api_key
    if body.model is not None:
        p.model = body.model
    p.updated_at = utc_now()
    db.commit()
    db.refresh(p)
    return _provider_out(p)


@app.delete("/api/admin/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: str, db: DbDep):
    p = db.query(ProviderConfig).filter(ProviderConfig.id == provider_id).first()
    if not p:
        raise HTTPException(404, "Provider 不存在")
    conv_refs = db.query(Conversation).filter(Conversation.provider_id == p.id).count()
    acct_refs = db.query(Account).filter(Account.distill_provider_id == p.id).count()
    if conv_refs or acct_refs:
        raise HTTPException(
            409,
            f"Provider 被 {conv_refs} 个 Conversation 和 {acct_refs} 个 Account 引用，请先重新分配",
        )
    db.delete(p)
    db.commit()


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

class ConversationOut(BaseModel):
    id: str
    account_username: str
    inbox_platform: str
    inbox_display_name: str
    kind: str
    display_name: str
    persona_name: str | None
    provider_id: str
    provider_name: str
    reply_policy: str
    takeover: bool
    status: str
    created_at: str


class SetConversationProviderIn(BaseModel):
    provider_id: str


@app.get("/api/admin/conversations", response_model=list[ConversationOut])
def list_conversations(db: DbDep, account: str | None = Query(default=None)):
    q = (
        db.query(
            Conversation,
            Account.username,
            Inbox.platform,
            Inbox.display_name,
            Persona.name,
            ProviderConfig.name,
        )
        .join(Inbox, Inbox.id == Conversation.inbox_id)
        .join(Account, Account.id == Inbox.account_id)
        .join(ProviderConfig, ProviderConfig.id == Conversation.provider_id)
        .outerjoin(Persona, Persona.id == Conversation.persona_id)
    )
    if account:
        a = db.query(Account).filter(Account.username == account).first()
        if not a:
            raise HTTPException(404, f"账号不存在: {account}")
        q = q.filter(Inbox.account_id == a.id)
    q = q.order_by(Account.username.asc(), Inbox.display_name.asc(), Conversation.created_at.asc())
    return [
        ConversationOut(
            id=c.id,
            account_username=uname,
            inbox_platform=platform,
            inbox_display_name=iname,
            kind=c.kind,
            display_name=c.display_name,
            persona_name=pname,
            provider_id=c.provider_id,
            provider_name=prvname,
            reply_policy=c.reply_policy,
            takeover=c.takeover,
            status=c.status,
            created_at=c.created_at.isoformat(),
        )
        for c, uname, platform, iname, pname, prvname in q.all()
    ]


@app.patch("/api/admin/conversations/{conv_id}/provider", status_code=204)
def set_conversation_provider(conv_id: str, body: SetConversationProviderIn, db: DbDep):
    c = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not c:
        raise HTTPException(404, "Conversation 不存在")
    p = db.query(ProviderConfig).filter(ProviderConfig.id == body.provider_id).first()
    if not p:
        raise HTTPException(404, "Provider 不存在")
    c.provider_id = p.id
    c.updated_at = utc_now()
    db.commit()


# ---------------------------------------------------------------------------
# Hosted bridges (dogfood chat-only)
# ---------------------------------------------------------------------------

class HostedBridgeOut(BaseModel):
    account_id: str
    username: str
    display_name: str
    status: str
    machine_id: str | None
    last_started_at: str | None
    last_error: str


def _bridge_host_call(method: str, path: str, body: dict | None = None) -> dict:
    """Talk to the in-cluster bridge-host service. Raises 502 on failure."""
    url = f"{BRIDGE_HOST_URL.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise HTTPException(502, f"bridge-host {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise HTTPException(502, f"bridge-host 不可达: {exc.reason}")


# Heartbeat is every 15s; Studio considers a bridge offline at >45s. Same
# threshold here so the admin panel matches "Studio thinks this bridge is
# alive". Pure read-side derivation — DB row remains the operator's last
# *intent*; only the displayed `status` is overwritten when reality
# disagrees, so a Restart click still makes sense.
_HOSTED_STALE_S = 45


def _hosted_out(
    account: Account,
    row: HostedBridge | None,
    bridge_seen_at,
    now,
) -> HostedBridgeOut:
    if row is None:
        return HostedBridgeOut(
            account_id=account.id,
            username=account.username,
            display_name=account.display_name,
            status=HostedBridgeStatus.STOPPED,
            machine_id=None,
            last_started_at=None,
            last_error="",
        )
    display_status = row.status
    last_error = row.last_error
    if display_status in (HostedBridgeStatus.RUNNING, HostedBridgeStatus.STARTING):
        stale = (
            bridge_seen_at is None
            or (now - bridge_seen_at).total_seconds() > _HOSTED_STALE_S
        )
        if stale:
            display_status = HostedBridgeStatus.CRASHED
            if not last_error:
                last_error = "心跳超时（>45s 未收到 heartbeat）"
    return HostedBridgeOut(
        account_id=account.id,
        username=account.username,
        display_name=account.display_name,
        status=display_status,
        machine_id=row.machine_id,
        last_started_at=row.last_started_at.isoformat() if row.last_started_at else None,
        last_error=last_error,
    )


@app.get("/api/admin/hosted-bridges", response_model=list[HostedBridgeOut])
def list_hosted_bridges(db: DbDep):
    accounts = db.query(Account).order_by(Account.created_at.asc()).all()
    rows = {r.account_id: r for r in db.query(HostedBridge).all()}
    # Pull last_seen_at for every (account_id, machine_id) pair we care
    # about in a single query — Bridge is keyed by both, so a stale
    # machine_id from a prior incarnation can't accidentally satisfy us.
    keys = {(r.account_id, r.machine_id) for r in rows.values() if r.machine_id}
    seen: dict[tuple[str, str], object] = {}
    if keys:
        for b in db.query(Bridge.account_id, Bridge.machine_id, Bridge.last_seen_at).all():
            if (b.account_id, b.machine_id) in keys:
                seen[(b.account_id, b.machine_id)] = b.last_seen_at
    now = utc_now()
    out: list[HostedBridgeOut] = []
    for a in accounts:
        row = rows.get(a.id)
        seen_at = seen.get((a.id, row.machine_id)) if row and row.machine_id else None
        out.append(_hosted_out(a, row, seen_at, now))
    return out


def _get_or_create_hosted_row(db: Session, account_id: str) -> HostedBridge:
    row = db.query(HostedBridge).filter(HostedBridge.account_id == account_id).first()
    if row is not None:
        return row
    now = utc_now()
    row = HostedBridge(
        account_id=account_id,
        status=HostedBridgeStatus.STOPPED,
        machine_id=None,
        session_id=None,
        last_started_at=None,
        last_error="",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _revoke_hosted_session(db: Session, row: HostedBridge) -> None:
    """Delete just the hosted bridge's AuthSession — leaves any web /
    physical bridge sessions for the same account untouched.
    """
    if not row.session_id:
        return
    db.query(AuthSession).filter(AuthSession.id == row.session_id).delete(
        synchronize_session=False
    )
    row.session_id = None


@app.post("/api/admin/hosted-bridges/{account_id}/start", response_model=HostedBridgeOut)
def start_hosted_bridge(account_id: str, db: DbDep):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(404, "账号不存在")
    if account.status != AccountStatus.ACTIVE:
        raise HTTPException(409, "账号已禁用")

    row = _get_or_create_hosted_row(db, account.id)
    # Drop any previous session this hosted bridge held — we're about to
    # mint a fresh one. (Don't touch the user's other sessions.)
    _revoke_hosted_session(db, row)

    bridge = ensure_bridge_row(db, account.id, row.machine_id)
    token = create_auth_session(db, account)

    now = utc_now()
    row.status = HostedBridgeStatus.STARTING
    row.machine_id = bridge.machine_id
    row.session_id = hash_token(token)
    row.last_started_at = now
    row.last_error = ""
    row.updated_at = now
    db.commit()

    try:
        # Pre-flight: kill any subprocess bridge-host might still be
        # tracking for this account so /spawn never hits a 409. Makes
        # Start idempotent (effectively Restart when a stale process is
        # still alive). bridge-host /stop is a no-op when nothing is
        # tracked.
        _bridge_host_call("POST", "/stop", {"account_id": account.id})
        _bridge_host_call("POST", "/spawn", {
            "account_id": account.id,
            "token": token,
            "machine_id": bridge.machine_id,
            "studio_url": BRIDGE_HOST_STUDIO_URL,
            "display_name": account.display_name,
        })
    except HTTPException as exc:
        # bridge-host rejected spawn — roll status back, drop session.
        row = db.query(HostedBridge).filter(HostedBridge.account_id == account.id).first()
        if row:
            _revoke_hosted_session(db, row)
            row.status = HostedBridgeStatus.CRASHED
            row.last_error = str(exc.detail)[:500]
            row.updated_at = utc_now()
            db.commit()
        raise

    row = db.query(HostedBridge).filter(HostedBridge.account_id == account.id).first()
    row.status = HostedBridgeStatus.RUNNING
    row.updated_at = utc_now()
    db.commit()
    db.refresh(row)
    return _row_to_out(db, account, row)


@app.post("/api/admin/hosted-bridges/{account_id}/stop", response_model=HostedBridgeOut)
def stop_hosted_bridge(account_id: str, db: DbDep):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(404, "账号不存在")
    row = db.query(HostedBridge).filter(HostedBridge.account_id == account.id).first()
    if row is None:
        return _hosted_out(account, None, None, utc_now())

    # Best-effort: tell bridge-host to terminate the subprocess. Even if
    # bridge-host is down or doesn't know the account, we still revoke
    # the session and mark stopped so admin isn't stuck.
    try:
        _bridge_host_call("POST", "/stop", {"account_id": account.id})
    except HTTPException as exc:
        row.last_error = f"stop warning: {exc.detail}"[:500]

    _revoke_hosted_session(db, row)
    row.status = HostedBridgeStatus.STOPPED
    row.updated_at = utc_now()
    db.commit()
    db.refresh(row)
    return _row_to_out(db, account, row)


def _row_to_out(db: Session, account: Account, row: HostedBridge) -> HostedBridgeOut:
    """Single-row variant for start/stop responses: look up the live
    Bridge.last_seen_at on the fly so the returned status reflects
    current heartbeat health, same as the list endpoint.
    """
    seen_at = None
    if row.machine_id:
        b = (
            db.query(Bridge.last_seen_at)
            .filter(Bridge.account_id == account.id, Bridge.machine_id == row.machine_id)
            .first()
        )
        if b:
            seen_at = b[0]
    return _hosted_out(account, row, seen_at, utc_now())
