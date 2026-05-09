import asyncio
import logging
import tempfile
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from studio.auth_utils import hash_password, hash_token, new_session_token, verify_password
from studio.db import ensure_database, get_db, utc_now
from studio.distill.ingest import ingest_archive
from studio.enums import (
    AccountRole,
    AccountStatus,
    BridgeStatus,
    ContactStatus,
    DistillJobStatus,
    MessageRole,
    MessageSource,
    OutboundAckResult,
    OutboundStatus,
    PersonaStatus,
    ProviderScope,
    ProviderStatus,
)
from studio.models import (
    Account,
    Archive,
    AuthSession,
    Bridge,
    BridgeSession,
    Contact,
    DistillJob,
    Inbox,
    Message,
    OutboundMessage,
    Persona,
    ProviderConfig,
)
from studio.provider_policy import resolve_provider_config
from studio.schemas import (
    AccountCreate,
    AccountPasswordReset,
    AccountUpdate,
    BridgeHandshake,
    BridgeIncomingBatch,
    BridgeOutboundAck,
    ContactUpdate,
    DistillJobCreate,
    InboxCreate,
    InboxUpdate,
    LoginRequest,
    OwnPasswordChange,
    OutboundCreate,
    PersonaCreate,
    PersonaUpdate,
    ProviderConfigCreate,
    ProviderConfigUpdate,
)

logger = logging.getLogger(__name__)
ensure_database()

app = FastAPI(title="Laborster Studio API")

DbDep = Annotated[Session, Depends(get_db)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_id(prefix: str, size: int = 8) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:size]}"


def base_account_id(username: str) -> str:
    safe = "".join(ch for ch in username.lower() if ch.isalnum())[:12]
    return f"acc_{safe}" if safe else "acc_user"


def next_account_id(db: Session, username: str) -> str:
    account_id = base_account_id(username)
    suffix = 1
    while db.query(Account).filter(Account.id == account_id).first():
        suffix += 1
        account_id = f"{base_account_id(username)}_{suffix}"
    return account_id


def create_account_record(
    db: Session,
    *,
    username: str,
    password: str,
    display_name: Optional[str],
    role: AccountRole,
) -> Account:
    username = username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if not password:
        raise HTTPException(status_code=400, detail="密码不能为空")
    existing = db.query(Account).filter(Account.username == username).first()
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")
    now = utc_now()
    created = Account(
        id=next_account_id(db, username),
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
        status=AccountStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        last_login_at=None,
    )
    db.add(created)
    return created


def create_auth_session(db: Session, account: Account) -> str:
    token = new_session_token()
    now = utc_now()
    db.add(AuthSession(id=hash_token(token), account_id=account.id, created_at=now, last_seen_at=now))
    account.last_login_at = now
    account.updated_at = now
    return token


def extract_bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少令牌"
        )
    return authorization.removeprefix("Bearer ").strip()


# ---------------------------------------------------------------------------
# User auth dependency
# ---------------------------------------------------------------------------

def get_account(
    db: DbDep,
    authorization: Annotated[Optional[str], Header()] = None,
) -> Account:
    token = extract_bearer(authorization)
    s = db.query(AuthSession).filter(AuthSession.id == hash_token(token)).first()
    if not s:
        raise HTTPException(status_code=401, detail="登录已失效")
    account = db.query(Account).filter(Account.id == s.account_id).first()
    if not account or account.status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="登录已失效")
    s.last_seen_at = utc_now()
    db.commit()
    return account


CurrentAccountDep = Annotated[Account, Depends(get_account)]


def is_admin(account: Account) -> bool:
    return account.role == AccountRole.ADMIN


def require_admin(account: CurrentAccountDep) -> Account:
    if not is_admin(account):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return account


AdminAccountDep = Annotated[Account, Depends(require_admin)]


# ---------------------------------------------------------------------------
# Bridge auth dependency
# ---------------------------------------------------------------------------

def get_authed_bridge(
    db: DbDep,
    authorization: Annotated[Optional[str], Header()] = None,
) -> Bridge:
    token = extract_bearer(authorization)
    session = db.query(BridgeSession).filter(BridgeSession.id == hash_token(token)).first()
    if not session:
        raise HTTPException(status_code=401, detail="无效的 bridge 令牌")
    bridge = db.query(Bridge).filter(Bridge.id == session.bridge_id).first()
    if not bridge or bridge.status == BridgeStatus.REVOKED:
        raise HTTPException(status_code=401, detail="bridge 已被撤销")
    session.last_seen_at = utc_now()
    db.commit()
    return bridge


BridgeDep = Annotated[Bridge, Depends(get_authed_bridge)]


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def mask_api_key(api_key: Optional[str]) -> Optional[str]:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def s_account(a: Account) -> Dict[str, Any]:
    return {
        "id": a.id, "username": a.username, "display_name": a.display_name,
        "role": a.role, "status": a.status,
        "created_at": a.created_at, "last_login_at": a.last_login_at,
    }


def s_provider(p: ProviderConfig) -> Dict[str, Any]:
    return {
        "id": p.id, "owner_account_id": p.owner_account_id,
        "name": p.name, "base_url": p.base_url,
        "default_model": p.default_model,
        "scope": p.scope, "status": p.status, "is_default": p.is_default,
        "has_api_key": bool(p.api_key), "api_key_preview": mask_api_key(p.api_key),
        "created_at": p.created_at, "updated_at": p.updated_at,
    }


def s_persona(p: Persona) -> Dict[str, Any]:
    return {
        "id": p.id, "account_id": p.account_id, "name": p.name,
        "persona_md": p.persona_md, "status": p.status,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }


def s_bridge(b: Bridge) -> Dict[str, Any]:
    return {
        "id": b.id, "account_id": b.account_id, "display_name": b.display_name,
        "hostname": b.hostname, "status": b.status, "last_seen_at": b.last_seen_at,
        "created_at": b.created_at, "updated_at": b.updated_at,
    }


def s_inbox(i: Inbox) -> Dict[str, Any]:
    return {
        "id": i.id, "account_id": i.account_id, "bridge_id": i.bridge_id,
        "platform": i.platform, "display_name": i.display_name,
        "default_persona_id": i.default_persona_id,
        "reply_provider_config_id": i.reply_provider_config_id,
        "enabled": i.enabled, "platform_self_id": i.platform_self_id,
        "created_at": i.created_at, "updated_at": i.updated_at,
    }


def s_contact(c: Contact) -> Dict[str, Any]:
    return {
        "id": c.id, "inbox_id": c.inbox_id, "peer_platform_id": c.peer_platform_id,
        "display_name": c.display_name, "card_md": c.card_md,
        "persona_id": c.persona_id,
        "reply_provider_config_id": c.reply_provider_config_id,
        "autoreply_enabled": c.autoreply_enabled,
        "pending_reply": c.pending_reply,
        "status": c.status, "last_seen_platform_msg_id": c.last_seen_platform_msg_id,
        "created_at": c.created_at, "updated_at": c.updated_at,
    }


def s_message(m: Message) -> Dict[str, Any]:
    return {
        "id": m.id, "contact_id": m.contact_id, "archive_id": m.archive_id,
        "external_id": m.external_id, "source": m.source, "role": m.role,
        "sender_name": m.sender_name, "content": m.content,
        "timestamp": m.timestamp, "created_at": m.created_at,
    }


def s_archive(a: Archive) -> Dict[str, Any]:
    return {
        "id": a.id, "account_id": a.account_id, "inbox_id": a.inbox_id,
        "filename": a.filename, "self_wxid": a.self_wxid,
        "message_count": a.message_count, "contact_count": a.contact_count,
        "uploaded_at": a.uploaded_at,
    }


def s_distill_job(j: DistillJob) -> Dict[str, Any]:
    return {
        "id": j.id, "account_id": j.account_id,
        "source_inbox_id": j.source_inbox_id, "target_persona_id": j.target_persona_id,
        "provider_config_id": j.provider_config_id, "status": j.status,
        "progress": j.progress, "error_message": j.error_message,
        "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at,
    }


def s_outbound(o: OutboundMessage, *, peer_platform_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": o.id, "inbox_id": o.inbox_id, "contact_id": o.contact_id,
        "peer_platform_id": peer_platform_id,
        "chunks": o.chunks, "status": o.status, "created_at": o.created_at,
        "delivered_at": o.delivered_at, "failed_reason": o.failed_reason,
    }


# ---------------------------------------------------------------------------
# Lookups + ownership checks
# ---------------------------------------------------------------------------

def get_provider_or_404(db: Session, provider_id: str) -> ProviderConfig:
    p = db.query(ProviderConfig).filter(ProviderConfig.id == provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Provider Config 不存在")
    return p


def get_account_persona(db: Session, account: Account, persona_id: str) -> Persona:
    query = db.query(Persona).filter(Persona.id == persona_id)
    if not is_admin(account):
        query = query.filter(Persona.account_id == account.id)
    p = query.first()
    if not p:
        raise HTTPException(status_code=404, detail="Persona 不存在")
    return p


def get_account_bridge(db: Session, account: Account, bridge_id: str) -> Bridge:
    query = db.query(Bridge).filter(Bridge.id == bridge_id)
    if not is_admin(account):
        query = query.filter(Bridge.account_id == account.id)
    b = query.first()
    if not b:
        raise HTTPException(status_code=404, detail="Bridge 不存在")
    return b


def get_account_inbox(db: Session, account: Account, inbox_id: str) -> Inbox:
    query = db.query(Inbox).filter(Inbox.id == inbox_id)
    if not is_admin(account):
        query = query.filter(Inbox.account_id == account.id)
    i = query.first()
    if not i:
        raise HTTPException(status_code=404, detail="Inbox 不存在")
    return i


def get_account_contact(db: Session, account: Account, contact_id: str) -> Contact:
    query = db.query(Contact).join(Inbox, Inbox.id == Contact.inbox_id).filter(Contact.id == contact_id)
    if not is_admin(account):
        query = query.filter(Inbox.account_id == account.id)
    c = query.first()
    if not c:
        raise HTTPException(status_code=404, detail="Contact 不存在")
    return c


# ---------------------------------------------------------------------------
# Health + Auth
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(login_in: LoginRequest, db: DbDep):
    a = db.query(Account).filter(Account.username == login_in.username).first()
    if not a or a.status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(login_in.password, a.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_auth_session(db, a)
    db.commit()
    db.refresh(a)
    return {"token": token, "account": s_account(a)}


@app.post("/api/auth/logout")
def logout(account: CurrentAccountDep, db: DbDep, authorization: Annotated[Optional[str], Header()] = None):
    token = extract_bearer(authorization)
    db.query(AuthSession).filter(AuthSession.id == hash_token(token)).delete()
    db.commit()
    return {"status": "ok"}


@app.get("/api/auth/me")
def me(account: CurrentAccountDep):
    return s_account(account)


@app.put("/api/auth/password")
def change_own_password(payload: OwnPasswordChange, account: CurrentAccountDep, db: DbDep):
    if not verify_password(payload.current_password, account.password_hash):
        raise HTTPException(status_code=400, detail="当前密码错误")
    account.password_hash = hash_password(payload.new_password)
    account.updated_at = utc_now()
    db.query(AuthSession).filter(AuthSession.account_id == account.id).delete(synchronize_session=False)
    db.commit()
    return {"status": "updated"}


# ---------------------------------------------------------------------------
# Account admin
# ---------------------------------------------------------------------------

@app.get("/api/accounts")
def list_accounts(db: DbDep, account: AdminAccountDep):
    items = db.query(Account).order_by(Account.created_at.asc()).all()
    return [s_account(item) for item in items]


@app.post("/api/accounts")
def create_account(payload: AccountCreate, db: DbDep, account: AdminAccountDep):
    created = create_account_record(
        db,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        role=payload.role,
    )
    db.commit()
    db.refresh(created)
    return s_account(created)


@app.put("/api/accounts/{account_id}")
def update_account(account_id: str, payload: AccountUpdate, db: DbDep, account: AdminAccountDep):
    target = db.query(Account).filter(Account.id == account_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    fields = payload.model_fields_set
    if "display_name" in fields:
        target.display_name = payload.display_name
    if "role" in fields and payload.role is not None:
        target.role = payload.role
    if "status" in fields and payload.status is not None:
        target.status = payload.status
        if payload.status != AccountStatus.ACTIVE:
            db.query(AuthSession).filter(AuthSession.account_id == target.id).delete(synchronize_session=False)
    target.updated_at = utc_now()
    db.commit()
    db.refresh(target)
    return s_account(target)


@app.put("/api/accounts/{account_id}/password")
def reset_account_password(
    account_id: str, payload: AccountPasswordReset, db: DbDep, account: AdminAccountDep
):
    target = db.query(Account).filter(Account.id == account_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    target.password_hash = hash_password(payload.password)
    target.updated_at = utc_now()
    db.query(AuthSession).filter(AuthSession.account_id == target.id).delete(synchronize_session=False)
    db.commit()
    return {"status": "updated", "id": target.id}


# ---------------------------------------------------------------------------
# Admin overview — system-wide dashboard for SaaS operators
# ---------------------------------------------------------------------------

@app.get("/api/admin/overview")
def admin_overview(db: DbDep, account: AdminAccountDep):
    """Aggregated counters for the admin dashboard.

    Returns global totals plus per-account breakdown (everything except
    LLM logs and outbound queue, which are debug-grade).
    """
    accounts = db.query(Account).order_by(Account.created_at.asc()).all()

    bridge_counts: Dict[str, Dict[str, int]] = {}
    for account_id, status_value, count in (
        db.query(Bridge.account_id, Bridge.status, func.count(Bridge.id))
        .group_by(Bridge.account_id, Bridge.status)
        .all()
    ):
        bridge_counts.setdefault(account_id, {})[status_value] = count

    inbox_counts: Dict[str, int] = dict(
        db.query(Inbox.account_id, func.count(Inbox.id))
        .group_by(Inbox.account_id)
        .all()
    )
    persona_counts: Dict[str, int] = dict(
        db.query(Persona.account_id, func.count(Persona.id))
        .group_by(Persona.account_id)
        .all()
    )

    contact_rows = (
        db.query(Inbox.account_id, func.count(Contact.id))
        .join(Contact, Contact.inbox_id == Inbox.id)
        .group_by(Inbox.account_id)
        .all()
    )
    contact_counts: Dict[str, int] = dict(contact_rows)

    autoreply_rows = (
        db.query(Inbox.account_id, func.count(Contact.id))
        .join(Contact, Contact.inbox_id == Inbox.id)
        .filter(Contact.autoreply_enabled.is_(True))
        .group_by(Inbox.account_id)
        .all()
    )
    autoreply_counts: Dict[str, int] = dict(autoreply_rows)

    message_rows = (
        db.query(Inbox.account_id, func.count(Message.id))
        .join(Contact, Contact.inbox_id == Inbox.id)
        .join(Message, Message.contact_id == Contact.id)
        .group_by(Inbox.account_id)
        .all()
    )
    message_counts: Dict[str, int] = dict(message_rows)

    items: List[Dict[str, Any]] = []
    for a in accounts:
        bridges_for_account = bridge_counts.get(a.id, {})
        items.append({
            "account": s_account(a),
            "bridges_online": bridges_for_account.get(BridgeStatus.ONLINE, 0),
            "bridges_offline": bridges_for_account.get(BridgeStatus.OFFLINE, 0),
            "bridges_revoked": bridges_for_account.get(BridgeStatus.REVOKED, 0),
            "inboxes": inbox_counts.get(a.id, 0),
            "personas": persona_counts.get(a.id, 0),
            "contacts": contact_counts.get(a.id, 0),
            "contacts_autoreply": autoreply_counts.get(a.id, 0),
            "messages": message_counts.get(a.id, 0),
        })

    totals = {
        "accounts": len(accounts),
        "admins": sum(1 for a in accounts if a.role == AccountRole.ADMIN),
        "users": sum(1 for a in accounts if a.role == AccountRole.USER),
        "bridges_online": sum(b.get(BridgeStatus.ONLINE, 0) for b in bridge_counts.values()),
        "bridges_offline": sum(b.get(BridgeStatus.OFFLINE, 0) for b in bridge_counts.values()),
        "inboxes": sum(inbox_counts.values()),
        "personas": sum(persona_counts.values()),
        "contacts": sum(contact_counts.values()),
        "contacts_autoreply": sum(autoreply_counts.values()),
        "messages": sum(message_counts.values()),
        "providers": db.query(func.count(ProviderConfig.id)).scalar() or 0,
        "outbound_pending": db.query(func.count(OutboundMessage.id))
            .filter(OutboundMessage.status == OutboundStatus.PENDING)
            .scalar() or 0,
    }

    return {"totals": totals, "accounts": items}


# ---------------------------------------------------------------------------
# Provider Configs
# ---------------------------------------------------------------------------

@app.get("/api/provider-configs")
def list_providers(db: DbDep, account: AdminAccountDep):
    items = (
        db.query(ProviderConfig)
        .order_by(ProviderConfig.updated_at.desc())
        .all()
    )
    return [s_provider(p) for p in items]


@app.post("/api/provider-configs")
def create_provider(payload: ProviderConfigCreate, db: DbDep, account: AdminAccountDep):
    now = utc_now()
    db.query(ProviderConfig).filter(ProviderConfig.is_default.is_(True)).update(
        {ProviderConfig.is_default: False, ProviderConfig.updated_at: now},
        synchronize_session=False,
    )
    p = ProviderConfig(
        id=new_id("p"), owner_account_id=account.id,
        name=payload.name, base_url=payload.base_url.rstrip("/"),
        api_key=payload.api_key, default_model=payload.default_model,
        scope=ProviderScope.GLOBAL,
        status=ProviderStatus.ACTIVE,
        is_default=True,
        created_at=now, updated_at=now,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return s_provider(p)


@app.put("/api/provider-configs/{provider_id}")
def update_provider(
    provider_id: str, payload: ProviderConfigUpdate, db: DbDep, account: AdminAccountDep
):
    p = get_provider_or_404(db, provider_id)
    fields = payload.model_fields_set
    if "name" in fields and payload.name is not None: p.name = payload.name
    if "base_url" in fields and payload.base_url is not None: p.base_url = payload.base_url.rstrip("/")
    if "api_key" in fields: p.api_key = payload.api_key
    if "default_model" in fields and payload.default_model is not None: p.default_model = payload.default_model
    p.updated_at = utc_now()
    db.commit()
    db.refresh(p)
    return s_provider(p)


@app.delete("/api/provider-configs/{provider_id}")
def delete_provider(provider_id: str, db: DbDep, account: AdminAccountDep):
    p = get_provider_or_404(db, provider_id)
    db.delete(p)
    db.commit()
    return {"status": "deleted", "id": provider_id}


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

@app.get("/api/personas")
def list_personas(db: DbDep, account: CurrentAccountDep):
    query = db.query(Persona)
    if not is_admin(account):
        query = query.filter(Persona.account_id == account.id)
    items = query.order_by(Persona.created_at.desc()).all()
    return [s_persona(p) for p in items]


@app.post("/api/personas")
def create_persona(payload: PersonaCreate, db: DbDep, account: CurrentAccountDep):
    now = utc_now()
    p = Persona(
        id=new_id("ps"), account_id=account.id,
        name=payload.name, persona_md=payload.persona_md,
        status=PersonaStatus.ACTIVE, created_at=now, updated_at=now,
    )
    db.add(p); db.commit(); db.refresh(p)
    return s_persona(p)


@app.get("/api/personas/{persona_id}")
def get_persona(persona_id: str, db: DbDep, account: CurrentAccountDep):
    return s_persona(get_account_persona(db, account, persona_id))


@app.put("/api/personas/{persona_id}")
def update_persona(persona_id: str, payload: PersonaUpdate, db: DbDep, account: CurrentAccountDep):
    p = get_account_persona(db, account, persona_id)
    fields = payload.model_fields_set
    if "name" in fields and payload.name is not None: p.name = payload.name
    if "persona_md" in fields: p.persona_md = payload.persona_md
    if "status" in fields and payload.status is not None: p.status = payload.status
    p.updated_at = utc_now()
    db.commit(); db.refresh(p)
    return s_persona(p)


@app.delete("/api/personas/{persona_id}")
def delete_persona(persona_id: str, db: DbDep, account: CurrentAccountDep):
    p = get_account_persona(db, account, persona_id)
    in_use_inbox = db.query(Inbox).filter(Inbox.default_persona_id == p.id).first()
    if in_use_inbox:
        raise HTTPException(status_code=409, detail=f"Persona 仍被 inbox {in_use_inbox.id} 引用")
    in_use_contact = db.query(Contact).filter(Contact.persona_id == p.id).first()
    if in_use_contact:
        raise HTTPException(status_code=409, detail=f"Persona 仍被 contact {in_use_contact.id} 引用")
    db.delete(p); db.commit()
    return {"status": "deleted", "id": persona_id}


# ---------------------------------------------------------------------------
# Bridges (read-only from the UI; auto-provisioned on bridge handshake)
# ---------------------------------------------------------------------------

@app.get("/api/bridges")
def list_bridges(db: DbDep, account: CurrentAccountDep):
    query = db.query(Bridge).filter(Bridge.status != BridgeStatus.REVOKED)
    if not is_admin(account):
        query = query.filter(Bridge.account_id == account.id)
    items = query.order_by(Bridge.created_at.desc()).all()
    return [s_bridge(b) for b in items]


@app.delete("/api/bridges/{bridge_id}")
def delete_bridge(bridge_id: str, db: DbDep, account: CurrentAccountDep):
    """Revoke a bridge: marks it revoked, kills its sessions, unbinds inboxes,
    cancels pending outbound. Daemon will get 401 on next call.
    """
    b = get_account_bridge(db, account, bridge_id)
    inbox_ids = [r[0] for r in db.query(Inbox.id).filter(Inbox.bridge_id == b.id).all()]
    if inbox_ids:
        db.query(OutboundMessage).filter(
            OutboundMessage.inbox_id.in_(inbox_ids),
            OutboundMessage.status == OutboundStatus.PENDING,
        ).update({OutboundMessage.status: OutboundStatus.CANCELED}, synchronize_session=False)
        db.query(Inbox).filter(Inbox.bridge_id == b.id).update(
            {Inbox.bridge_id: None}, synchronize_session=False
        )
    db.query(BridgeSession).filter(BridgeSession.bridge_id == b.id).delete(
        synchronize_session=False
    )
    b.status = BridgeStatus.REVOKED
    b.updated_at = utc_now()
    db.commit()
    return {"status": BridgeStatus.REVOKED, "id": bridge_id}


# ---------------------------------------------------------------------------
# Inboxes
# ---------------------------------------------------------------------------

@app.get("/api/inboxes")
def list_inboxes(db: DbDep, account: CurrentAccountDep):
    query = db.query(Inbox)
    if not is_admin(account):
        query = query.filter(Inbox.account_id == account.id)
    items = query.order_by(Inbox.created_at.desc()).all()
    return [s_inbox(i) for i in items]


@app.post("/api/inboxes")
def create_inbox(payload: InboxCreate, db: DbDep, account: CurrentAccountDep):
    if payload.reply_provider_config_id is not None and not is_admin(account):
        raise HTTPException(status_code=403, detail="只有管理员可以指定 Provider")
    if payload.default_persona_id is not None:
        get_account_persona(db, account, payload.default_persona_id)
    if payload.bridge_id is not None:
        get_account_bridge(db, account, payload.bridge_id)
    if payload.reply_provider_config_id is not None:
        get_provider_or_404(db, payload.reply_provider_config_id)
    now = utc_now()
    inbox = Inbox(
        id=new_id("ib"), account_id=account.id,
        bridge_id=payload.bridge_id,
        platform=payload.platform, display_name=payload.display_name,
        default_persona_id=payload.default_persona_id,
        reply_provider_config_id=payload.reply_provider_config_id,
        enabled=payload.enabled,
        platform_self_id=None,
        created_at=now, updated_at=now,
    )
    db.add(inbox); db.commit(); db.refresh(inbox)
    return s_inbox(inbox)


@app.get("/api/inboxes/{inbox_id}")
def get_inbox(inbox_id: str, db: DbDep, account: CurrentAccountDep):
    return s_inbox(get_account_inbox(db, account, inbox_id))


@app.put("/api/inboxes/{inbox_id}")
def update_inbox(inbox_id: str, payload: InboxUpdate, db: DbDep, account: CurrentAccountDep):
    inbox = get_account_inbox(db, account, inbox_id)
    fields = payload.model_fields_set
    if "display_name" in fields and payload.display_name is not None:
        inbox.display_name = payload.display_name
    if "default_persona_id" in fields and payload.default_persona_id is not None:
        get_account_persona(db, account, payload.default_persona_id)
        inbox.default_persona_id = payload.default_persona_id
    if "bridge_id" in fields and payload.bridge_id is not None:
        get_account_bridge(db, account, payload.bridge_id)
        inbox.bridge_id = payload.bridge_id
    if payload.clear_bridge:
        inbox.bridge_id = None
    if ("reply_provider_config_id" in fields or payload.clear_reply_provider) and not is_admin(account):
        raise HTTPException(status_code=403, detail="只有管理员可以修改 Provider")
    if "reply_provider_config_id" in fields and payload.reply_provider_config_id is not None:
        get_provider_or_404(db, payload.reply_provider_config_id)
        inbox.reply_provider_config_id = payload.reply_provider_config_id
    if payload.clear_reply_provider:
        inbox.reply_provider_config_id = None
    if "enabled" in fields and payload.enabled is not None:
        inbox.enabled = payload.enabled
    inbox.updated_at = utc_now()
    db.commit(); db.refresh(inbox)
    return s_inbox(inbox)


@app.delete("/api/inboxes/{inbox_id}")
def delete_inbox(inbox_id: str, db: DbDep, account: CurrentAccountDep):
    inbox = get_account_inbox(db, account, inbox_id)
    db.query(OutboundMessage).filter(
        OutboundMessage.inbox_id == inbox.id, OutboundMessage.status == OutboundStatus.PENDING
    ).update({OutboundMessage.status: OutboundStatus.CANCELED}, synchronize_session=False)
    db.delete(inbox); db.commit()
    return {"status": "deleted", "id": inbox_id}


@app.get("/api/inboxes/{inbox_id}/contacts")
def list_inbox_contacts(inbox_id: str, db: DbDep, account: CurrentAccountDep):
    inbox = get_account_inbox(db, account, inbox_id)
    items = (
        db.query(Contact).filter(Contact.inbox_id == inbox.id)
        .order_by(Contact.updated_at.desc()).all()
    )
    return [s_contact(c) for c in items]


@app.post("/api/inboxes/{inbox_id}/outbound")
def seed_outbound(inbox_id: str, payload: OutboundCreate, db: DbDep, account: CurrentAccountDep):
    """Manual outbound seeding (debug / pre-LLM-brain)."""
    inbox = get_account_inbox(db, account, inbox_id)
    contact = get_account_contact(db, account, payload.contact_id)
    if contact.inbox_id != inbox.id:
        raise HTTPException(status_code=400, detail="Contact 不属于该 inbox")
    o = OutboundMessage(
        inbox_id=inbox.id, contact_id=contact.id,
        chunks=[c.model_dump() for c in payload.chunks],
        status=OutboundStatus.PENDING, delivered_at=None, failed_reason=None, created_at=utc_now(),
    )
    db.add(o); db.commit(); db.refresh(o)
    return s_outbound(o, peer_platform_id=contact.peer_platform_id)


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

@app.get("/api/contacts/{contact_id}")
def get_contact(contact_id: str, db: DbDep, account: CurrentAccountDep):
    return s_contact(get_account_contact(db, account, contact_id))


@app.get("/api/conversations")
def list_conversations(db: DbDep, account: CurrentAccountDep):
    query = db.query(Contact, Inbox).join(Inbox, Inbox.id == Contact.inbox_id)
    if not is_admin(account):
        query = query.filter(Inbox.account_id == account.id)
    rows = query.all()
    out: List[Dict[str, Any]] = []
    for contact, inbox in rows:
        latest = (
            db.query(Message)
            .filter(Message.contact_id == contact.id)
            .order_by(Message.timestamp.desc(), Message.id.desc())
            .first()
        )
        message_count = db.query(Message).filter(Message.contact_id == contact.id).count()
        out.append({
            "contact": s_contact(contact),
            "inbox": s_inbox(inbox),
            "latest_message": s_message(latest) if latest else None,
            "message_count": message_count,
        })
    out.sort(
        key=lambda item: (
            item["latest_message"]["timestamp"] if item["latest_message"] else item["contact"]["updated_at"],
            item["contact"]["id"],
        ),
        reverse=True,
    )
    return out


@app.get("/api/contacts/{contact_id}/messages")
def list_contact_messages(
    contact_id: str,
    db: DbDep,
    account: CurrentAccountDep,
    limit: int = Query(200, ge=1, le=500),
):
    contact = get_account_contact(db, account, contact_id)
    rows = (
        db.query(Message)
        .filter(Message.contact_id == contact.id)
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    return [s_message(m) for m in rows]


@app.put("/api/contacts/{contact_id}")
def update_contact(contact_id: str, payload: ContactUpdate, db: DbDep, account: CurrentAccountDep):
    c = get_account_contact(db, account, contact_id)
    fields = payload.model_fields_set
    if "display_name" in fields and payload.display_name is not None: c.display_name = payload.display_name
    if "card_md" in fields: c.card_md = payload.card_md
    if "persona_id" in fields and payload.persona_id is not None:
        get_account_persona(db, account, payload.persona_id)
        c.persona_id = payload.persona_id
    if ("reply_provider_config_id" in fields or payload.clear_reply_provider) and not is_admin(account):
        raise HTTPException(status_code=403, detail="只有管理员可以修改 Provider")
    if "reply_provider_config_id" in fields and payload.reply_provider_config_id is not None:
        get_provider_or_404(db, payload.reply_provider_config_id)
        c.reply_provider_config_id = payload.reply_provider_config_id
    if payload.clear_reply_provider:
        c.reply_provider_config_id = None
    if "autoreply_enabled" in fields and payload.autoreply_enabled is not None:
        c.autoreply_enabled = payload.autoreply_enabled
    if "status" in fields and payload.status is not None: c.status = payload.status
    c.updated_at = utc_now()
    db.commit(); db.refresh(c)
    return s_contact(c)


# ---------------------------------------------------------------------------
# Archives + Distill (unchanged from prior commit)
# ---------------------------------------------------------------------------

@app.get("/api/archives")
def list_archives(db: DbDep, account: CurrentAccountDep):
    query = db.query(Archive)
    if not is_admin(account):
        query = query.filter(Archive.account_id == account.id)
    items = query.order_by(Archive.uploaded_at.desc()).all()
    return [s_archive(a) for a in items]


@app.post("/api/archives")
async def upload_archive(
    db: DbDep, account: CurrentAccountDep,
    inbox_id: str = Form(...), self_wxid: str = Form(...), file: UploadFile = File(...),
):
    inbox = get_account_inbox(db, account, inbox_id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    try:
        archive = await ingest_archive(
            db=db, account_id=inbox.account_id, inbox=inbox,
            self_wxid=self_wxid, src_path=tmp_path,
            original_filename=file.filename or tmp_path.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)
    return s_archive(archive)


@app.get("/api/distill-jobs")
def list_distill_jobs(db: DbDep, account: CurrentAccountDep):
    query = db.query(DistillJob)
    if not is_admin(account):
        query = query.filter(DistillJob.account_id == account.id)
    items = query.order_by(DistillJob.created_at.desc()).all()
    return [s_distill_job(j) for j in items]


@app.post("/api/distill-jobs")
def create_distill_job(payload: DistillJobCreate, db: DbDep, account: CurrentAccountDep):
    inbox = get_account_inbox(db, account, payload.source_inbox_id)
    get_account_persona(db, account, payload.target_persona_id)
    if payload.provider_config_id is not None and not is_admin(account):
        raise HTTPException(status_code=403, detail="只有管理员可以指定 Provider")
    provider_config = resolve_provider_config(db, payload.provider_config_id)
    if not provider_config:
        raise HTTPException(status_code=409, detail="没有可用的全局默认 Provider")
    pending = (
        db.query(DistillJob).filter(
            DistillJob.account_id == inbox.account_id,
            DistillJob.target_persona_id == payload.target_persona_id,
            DistillJob.status.in_([DistillJobStatus.PENDING, DistillJobStatus.RUNNING]),
        ).first()
    )
    if pending:
        raise HTTPException(status_code=409, detail=f"该 persona 已有进行中的蒸馏任务 {pending.id}")
    j = DistillJob(
        id=new_id("dj"), account_id=inbox.account_id,
        source_inbox_id=payload.source_inbox_id,
        target_persona_id=payload.target_persona_id,
        provider_config_id=provider_config.id,
        status=DistillJobStatus.PENDING, progress={}, error_message=None,
        created_at=utc_now(), started_at=None, finished_at=None,
    )
    db.add(j); db.commit(); db.refresh(j)
    return s_distill_job(j)


@app.get("/api/distill-jobs/{job_id}")
def get_distill_job(job_id: str, db: DbDep, account: CurrentAccountDep):
    query = db.query(DistillJob).filter(DistillJob.id == job_id)
    if not is_admin(account):
        query = query.filter(DistillJob.account_id == account.id)
    j = query.first()
    if not j:
        raise HTTPException(status_code=404, detail="Distill Job 不存在")
    return s_distill_job(j)


# ---------------------------------------------------------------------------
# Bridge protocol (Bridge daemon ↔ Studio)
#
# A daemon authenticates on every handshake by sending its Studio account
# credentials + hostname. Studio upserts a Bridge row keyed by
# (account_id, hostname), wipes any prior session for that bridge, and mints
# a fresh BridgeSession token. The token is used for /api/bridge/heartbeat,
# /incoming, /outbound, /outbound/.../ack — that's the entire surface.
# ---------------------------------------------------------------------------

def _serialize_bridge_inbox_view(i: Inbox) -> Dict[str, Any]:
    """Compact inbox view for bridge consumption."""
    return {
        "id": i.id,
        "platform": i.platform,
        "platform_self_id": i.platform_self_id,
        "display_name": i.display_name,
        "enabled": i.enabled,
        "default_persona_id": i.default_persona_id,
    }


@app.post("/api/bridge/handshake")
def bridge_handshake(payload: BridgeHandshake, db: DbDep):
    """Login + register + report served inboxes, in one call.

    1. Verify Studio account credentials.
    2. Upsert Bridge by (account_id, hostname).
    3. Wipe prior BridgeSession rows for this bridge; mint a fresh token.
    4. Upsert an Inbox per (platform, platform_self_id) the bridge logged into.
    5. Return the token + authoritative inbox list + outbound cursor.
    """
    account = (
        db.query(Account).filter(Account.username == payload.username).first()
    )
    if not account or account.status != AccountStatus.ACTIVE or not verify_password(
        payload.password, account.password_hash
    ):
        raise HTTPException(status_code=401, detail="Studio 账号或密码错误")

    now = utc_now()
    bridge = (
        db.query(Bridge)
        .filter(Bridge.account_id == account.id, Bridge.hostname == payload.hostname)
        .first()
    )
    if bridge is None:
        bridge = Bridge(
            id=new_id("br"),
            account_id=account.id,
            hostname=payload.hostname,
            display_name=payload.hostname,
            status=BridgeStatus.ONLINE,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(bridge)
        db.flush()
    else:
        bridge.status = BridgeStatus.ONLINE
        bridge.last_seen_at = now
        bridge.updated_at = now

    db.query(BridgeSession).filter(BridgeSession.bridge_id == bridge.id).delete(
        synchronize_session=False
    )
    raw_token = new_session_token()
    db.add(BridgeSession(
        id=hash_token(raw_token),
        bridge_id=bridge.id,
        created_at=now,
        last_seen_at=now,
    ))

    default_persona = (
        db.query(Persona)
        .filter(Persona.account_id == account.id, Persona.status == PersonaStatus.ACTIVE)
        .order_by(Persona.created_at.asc())
        .first()
    )

    served: List[Inbox] = []
    for claim in payload.inboxes:
        inbox = (
            db.query(Inbox)
            .filter(
                Inbox.account_id == account.id,
                Inbox.platform == claim.platform,
                Inbox.platform_self_id == claim.platform_self_id,
            )
            .first()
        )
        if inbox:
            inbox.bridge_id = bridge.id
            inbox.updated_at = now
            served.append(inbox)
            continue

        inbox = Inbox(
            id=new_id("ib"),
            account_id=account.id,
            bridge_id=bridge.id,
            platform=claim.platform,
            display_name=f"{claim.platform_self_id}@{claim.platform}",
            default_persona_id=default_persona.id if default_persona else None,
            reply_provider_config_id=None,
            enabled=True,
            platform_self_id=claim.platform_self_id,
            created_at=now,
            updated_at=now,
        )
        db.add(inbox)
        db.flush()
        served.append(inbox)

    if served:
        last_outbound_id = (
            db.query(OutboundMessage.id)
            .filter(
                OutboundMessage.inbox_id.in_([i.id for i in served]),
                OutboundMessage.status != OutboundStatus.PENDING,
            )
            .order_by(OutboundMessage.id.desc())
            .first()
        )
        cursor = last_outbound_id[0] if last_outbound_id else 0
    else:
        cursor = 0
    db.commit()

    return {
        "token": raw_token,
        "bridge_id": bridge.id,
        "account_id": account.id,
        "inboxes": [_serialize_bridge_inbox_view(i) for i in served],
        "cursor": cursor,
        "no_persona": not default_persona,
    }


@app.post("/api/bridge/heartbeat")
def bridge_heartbeat(db: DbDep, bridge: BridgeDep):
    now = utc_now()
    bridge.last_seen_at = now
    if bridge.status != BridgeStatus.ONLINE:
        bridge.status = BridgeStatus.ONLINE
    db.commit()
    # Return current authoritative inbox set so daemon can sync (start /
    # stop adapters when UI bindings change).
    inboxes = db.query(Inbox).filter(Inbox.bridge_id == bridge.id).all()
    return {"inboxes": [_serialize_bridge_inbox_view(i) for i in inboxes]}


@app.post("/api/bridge/incoming")
def bridge_incoming(payload: BridgeIncomingBatch, db: DbDep, bridge: BridgeDep):
    accepted = 0
    deduped = 0
    rejected = 0
    now = utc_now()
    # Cache lookup of inbox by id within this request (most batches hit
    # the same inbox repeatedly).
    inbox_cache: Dict[str, Inbox] = {}
    for m in payload.messages:
        inbox = inbox_cache.get(m.inbox_id)
        if inbox is None:
            inbox = (
                db.query(Inbox).filter(
                    Inbox.id == m.inbox_id,
                    Inbox.bridge_id == bridge.id,
                    Inbox.account_id == bridge.account_id,
                ).first()
            )
            if not inbox:
                rejected += 1
                continue
            inbox_cache[m.inbox_id] = inbox

        contact = (
            db.query(Contact)
            .filter(Contact.inbox_id == inbox.id, Contact.peer_platform_id == m.peer_platform_id)
            .first()
        )
        if not contact:
            contact = Contact(
                id=new_id("ct"), inbox_id=inbox.id,
                peer_platform_id=m.peer_platform_id,
                display_name=m.peer_display_name or m.peer_platform_id,
                card_md=None, persona_id=inbox.default_persona_id,
                reply_provider_config_id=inbox.reply_provider_config_id,
                autoreply_enabled=False, pending_reply=False,
                status=ContactStatus.ACTIVE, last_seen_platform_msg_id=None,
                created_at=now, updated_at=now,
            )
            db.add(contact); db.flush()

        external_id = f"live:{m.platform_msg_id}"
        existing = (
            db.query(Message)
            .filter(Message.contact_id == contact.id, Message.external_id == external_id)
            .first()
        )
        if existing:
            deduped += 1
            continue

        ts = m.sent_at.replace(tzinfo=None) if m.sent_at.tzinfo else m.sent_at
        db.add(Message(
            contact_id=contact.id, archive_id=None,
            external_id=external_id, source=MessageSource.LIVE,
            role=m.role, sender_name=None, content=m.content,
            timestamp=ts, archive_msg_idx=None, created_at=now,
        ))
        contact.last_seen_platform_msg_id = m.platform_msg_id
        contact.updated_at = now
        if m.role == MessageRole.COUNTERPART and inbox.enabled and contact.autoreply_enabled:
            contact.pending_reply = True
        accepted += 1

    bridge.last_seen_at = now
    db.commit()
    return {"accepted": accepted, "deduped": deduped, "rejected": rejected}


@app.get("/api/bridge/outbound")
async def bridge_outbound(
    bridge: BridgeDep,
    cursor: int = Query(0, ge=0),
    timeout: int = Query(0, ge=0, le=60),
):
    deadline = time.time() + timeout
    while True:
        # Recompute every iteration (a fresh DB session per loop avoids
        # holding a transaction across asyncio.sleep).
        from studio.db import SessionLocal
        db = SessionLocal()
        try:
            inbox_ids = [
                r[0] for r in db.query(Inbox.id).filter(Inbox.bridge_id == bridge.id).all()
            ]
            if not inbox_ids:
                payload: List[Dict[str, Any]] = []
            else:
                rows = (
                    db.query(OutboundMessage)
                    .filter(
                        OutboundMessage.inbox_id.in_(inbox_ids),
                        OutboundMessage.id > cursor,
                        OutboundMessage.status == OutboundStatus.PENDING,
                    )
                    .order_by(OutboundMessage.id.asc())
                    .limit(50)
                    .all()
                )
                contact_ids = list({o.contact_id for o in rows})
                peer_map: Dict[str, str] = {}
                if contact_ids:
                    peers = db.query(Contact.id, Contact.peer_platform_id).filter(
                        Contact.id.in_(contact_ids)
                    ).all()
                    peer_map = {cid: peer for cid, peer in peers}
                payload = [s_outbound(o, peer_platform_id=peer_map.get(o.contact_id)) for o in rows]
        finally:
            db.close()
        if payload:
            return payload
        if time.time() >= deadline:
            return payload
        await asyncio.sleep(min(0.5, max(0.1, deadline - time.time())))


@app.post("/api/bridge/outbound/{outbound_id}/ack")
def bridge_outbound_ack(
    outbound_id: int, payload: BridgeOutboundAck, db: DbDep, bridge: BridgeDep
):
    o = (
        db.query(OutboundMessage)
        .join(Inbox, Inbox.id == OutboundMessage.inbox_id)
        .filter(OutboundMessage.id == outbound_id, Inbox.bridge_id == bridge.id)
        .first()
    )
    if not o:
        raise HTTPException(status_code=404, detail="Outbound 不存在")
    if o.status != OutboundStatus.PENDING:
        return {"status": o.status}
    now = utc_now()
    if payload.result == OutboundAckResult.SENT:
        o.status = OutboundStatus.DELIVERED
        o.delivered_at = now
    else:
        o.status = OutboundStatus.FAILED
        o.failed_reason = payload.reason
    db.commit()
    return {"status": o.status}
