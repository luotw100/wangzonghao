"""Laborster Admin API.

No auth middleware here — auth is delegated to Cloudflare Access, which
verifies the user's identity at the edge before traffic reaches this service.
"""
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from studio.auth_utils import hash_password
from studio.clients import ALLOWED_BASE_URLS
from studio.db import get_db, utc_now
from studio.deps import new_id, pick_first_provider
from studio.enums import AccountStatus
from studio.models import Account, Conversation, Inbox, Persona, ProviderConfig

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
