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
from sqlalchemy.orm import Session

from studio.auth_utils import hash_token, new_session_token, verify_password
from studio.db import ensure_database, get_db, utc_now
from studio.distill.ingest import ingest_archive
from studio.models import (
    Account,
    Archive,
    AuthSession,
    Bridge,
    Contact,
    DistillJob,
    Inbox,
    Message,
    OutboundMessage,
    Persona,
    ProviderConfig,
)
from studio.schemas import (
    BridgeCreate,
    BridgeHandshake,
    BridgeIncomingBatch,
    BridgeOutboundAck,
    BridgeUpdate,
    ContactUpdate,
    DistillJobCreate,
    InboxCreate,
    InboxUpdate,
    LoginRequest,
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
    if not account or account.status != "active":
        raise HTTPException(status_code=401, detail="登录已失效")
    s.last_seen_at = utc_now()
    db.commit()
    return account


CurrentAccountDep = Annotated[Account, Depends(get_account)]


# ---------------------------------------------------------------------------
# Bridge auth dependency
# ---------------------------------------------------------------------------

def get_authed_bridge(
    db: DbDep,
    authorization: Annotated[Optional[str], Header()] = None,
) -> Bridge:
    token = extract_bearer(authorization)
    bridge = db.query(Bridge).filter(Bridge.token_hash == hash_token(token)).first()
    if not bridge or bridge.status == "revoked":
        raise HTTPException(status_code=401, detail="无效的 bridge 令牌")
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
        "status": a.status, "created_at": a.created_at, "last_login_at": a.last_login_at,
    }


def s_provider(p: ProviderConfig) -> Dict[str, Any]:
    return {
        "id": p.id, "name": p.name, "base_url": p.base_url,
        "default_model": p.default_model,
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
        "status": b.status, "hostname": b.hostname, "last_seen_at": b.last_seen_at,
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
        "persona_id": c.persona_id, "autoreply_enabled": c.autoreply_enabled,
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

def get_account_provider(db: Session, account_id: str, provider_id: str) -> ProviderConfig:
    p = db.query(ProviderConfig).filter(
        ProviderConfig.id == provider_id, ProviderConfig.account_id == account_id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Provider Config 不存在")
    return p


def get_account_persona(db: Session, account_id: str, persona_id: str) -> Persona:
    p = db.query(Persona).filter(
        Persona.id == persona_id, Persona.account_id == account_id
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Persona 不存在")
    return p


def get_account_bridge(db: Session, account_id: str, bridge_id: str) -> Bridge:
    b = db.query(Bridge).filter(
        Bridge.id == bridge_id, Bridge.account_id == account_id
    ).first()
    if not b:
        raise HTTPException(status_code=404, detail="Bridge 不存在")
    return b


def get_account_inbox(db: Session, account_id: str, inbox_id: str) -> Inbox:
    i = db.query(Inbox).filter(
        Inbox.id == inbox_id, Inbox.account_id == account_id
    ).first()
    if not i:
        raise HTTPException(status_code=404, detail="Inbox 不存在")
    return i


def get_account_contact(db: Session, account_id: str, contact_id: str) -> Contact:
    c = (
        db.query(Contact)
        .join(Inbox, Inbox.id == Contact.inbox_id)
        .filter(Contact.id == contact_id, Inbox.account_id == account_id)
        .first()
    )
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
    if not a or a.status != "active":
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(login_in.password, a.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = new_session_token()
    now = utc_now()
    db.add(AuthSession(id=hash_token(token), account_id=a.id, created_at=now, last_seen_at=now))
    a.last_login_at = now
    a.updated_at = now
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


# ---------------------------------------------------------------------------
# Provider Configs
# ---------------------------------------------------------------------------

@app.get("/api/provider-configs")
def list_providers(db: DbDep, account: CurrentAccountDep):
    items = (
        db.query(ProviderConfig)
        .filter(ProviderConfig.account_id == account.id)
        .order_by(ProviderConfig.updated_at.desc())
        .all()
    )
    return [s_provider(p) for p in items]


@app.post("/api/provider-configs")
def create_provider(payload: ProviderConfigCreate, db: DbDep, account: CurrentAccountDep):
    now = utc_now()
    p = ProviderConfig(
        id=new_id("p"), account_id=account.id,
        name=payload.name, base_url=payload.base_url.rstrip("/"),
        api_key=payload.api_key, default_model=payload.default_model,
        created_at=now, updated_at=now,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return s_provider(p)


@app.put("/api/provider-configs/{provider_id}")
def update_provider(
    provider_id: str, payload: ProviderConfigUpdate, db: DbDep, account: CurrentAccountDep
):
    p = get_account_provider(db, account.id, provider_id)
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
def delete_provider(provider_id: str, db: DbDep, account: CurrentAccountDep):
    p = get_account_provider(db, account.id, provider_id)
    db.delete(p)
    db.commit()
    return {"status": "deleted", "id": provider_id}


# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------

@app.get("/api/personas")
def list_personas(db: DbDep, account: CurrentAccountDep):
    items = (
        db.query(Persona).filter(Persona.account_id == account.id)
        .order_by(Persona.created_at.desc()).all()
    )
    return [s_persona(p) for p in items]


@app.post("/api/personas")
def create_persona(payload: PersonaCreate, db: DbDep, account: CurrentAccountDep):
    now = utc_now()
    p = Persona(
        id=new_id("ps"), account_id=account.id,
        name=payload.name, persona_md=payload.persona_md,
        status="active", created_at=now, updated_at=now,
    )
    db.add(p); db.commit(); db.refresh(p)
    return s_persona(p)


@app.get("/api/personas/{persona_id}")
def get_persona(persona_id: str, db: DbDep, account: CurrentAccountDep):
    return s_persona(get_account_persona(db, account.id, persona_id))


@app.put("/api/personas/{persona_id}")
def update_persona(persona_id: str, payload: PersonaUpdate, db: DbDep, account: CurrentAccountDep):
    p = get_account_persona(db, account.id, persona_id)
    fields = payload.model_fields_set
    if "name" in fields and payload.name is not None: p.name = payload.name
    if "persona_md" in fields: p.persona_md = payload.persona_md
    if "status" in fields and payload.status is not None: p.status = payload.status
    p.updated_at = utc_now()
    db.commit(); db.refresh(p)
    return s_persona(p)


@app.delete("/api/personas/{persona_id}")
def delete_persona(persona_id: str, db: DbDep, account: CurrentAccountDep):
    p = get_account_persona(db, account.id, persona_id)
    in_use_inbox = db.query(Inbox).filter(Inbox.default_persona_id == p.id).first()
    if in_use_inbox:
        raise HTTPException(status_code=409, detail=f"Persona 仍被 inbox {in_use_inbox.id} 引用")
    in_use_contact = db.query(Contact).filter(Contact.persona_id == p.id).first()
    if in_use_contact:
        raise HTTPException(status_code=409, detail=f"Persona 仍被 contact {in_use_contact.id} 引用")
    db.delete(p); db.commit()
    return {"status": "deleted", "id": persona_id}


# ---------------------------------------------------------------------------
# Bridges
# ---------------------------------------------------------------------------

@app.get("/api/bridges")
def list_bridges(db: DbDep, account: CurrentAccountDep):
    items = (
        db.query(Bridge).filter(Bridge.account_id == account.id)
        .order_by(Bridge.created_at.desc()).all()
    )
    return [s_bridge(b) for b in items]


@app.post("/api/bridges")
def create_bridge(payload: BridgeCreate, db: DbDep, account: CurrentAccountDep):
    now = utc_now()
    raw_token = new_session_token()
    b = Bridge(
        id=new_id("br"), account_id=account.id, display_name=payload.display_name,
        token_hash=hash_token(raw_token), status="paired_pending",
        hostname=None, last_seen_at=None, created_at=now, updated_at=now,
    )
    db.add(b); db.commit(); db.refresh(b)
    out = s_bridge(b)
    out["token"] = raw_token   # one-time display
    return out


@app.put("/api/bridges/{bridge_id}")
def update_bridge(bridge_id: str, payload: BridgeUpdate, db: DbDep, account: CurrentAccountDep):
    b = get_account_bridge(db, account.id, bridge_id)
    fields = payload.model_fields_set
    if "display_name" in fields and payload.display_name is not None:
        b.display_name = payload.display_name
    b.updated_at = utc_now()
    db.commit(); db.refresh(b)
    return s_bridge(b)


@app.post("/api/bridges/{bridge_id}/regenerate-token")
def regenerate_bridge_token(bridge_id: str, db: DbDep, account: CurrentAccountDep):
    b = get_account_bridge(db, account.id, bridge_id)
    raw_token = new_session_token()
    b.token_hash = hash_token(raw_token)
    b.status = "paired_pending"
    b.last_seen_at = None
    b.updated_at = utc_now()
    db.commit(); db.refresh(b)
    out = s_bridge(b)
    out["token"] = raw_token
    return out


@app.delete("/api/bridges/{bridge_id}")
def delete_bridge(bridge_id: str, db: DbDep, account: CurrentAccountDep):
    b = get_account_bridge(db, account.id, bridge_id)
    b.status = "revoked"
    b.updated_at = utc_now()
    # Detach inboxes; they become unbound until rebound.
    db.query(Inbox).filter(Inbox.bridge_id == b.id).update({Inbox.bridge_id: None})
    # Cancel any outbound for those inboxes.
    inbox_ids = [r[0] for r in db.query(Inbox.id).filter(Inbox.bridge_id == b.id).all()]
    if inbox_ids:
        db.query(OutboundMessage).filter(
            OutboundMessage.inbox_id.in_(inbox_ids),
            OutboundMessage.status == "pending",
        ).update({OutboundMessage.status: "canceled"}, synchronize_session=False)
    db.commit()
    return {"status": "revoked", "id": bridge_id}


# ---------------------------------------------------------------------------
# Inboxes
# ---------------------------------------------------------------------------

@app.get("/api/inboxes")
def list_inboxes(db: DbDep, account: CurrentAccountDep):
    items = (
        db.query(Inbox).filter(Inbox.account_id == account.id)
        .order_by(Inbox.created_at.desc()).all()
    )
    return [s_inbox(i) for i in items]


@app.post("/api/inboxes")
def create_inbox(payload: InboxCreate, db: DbDep, account: CurrentAccountDep):
    if payload.default_persona_id is not None:
        get_account_persona(db, account.id, payload.default_persona_id)
    if payload.bridge_id is not None:
        get_account_bridge(db, account.id, payload.bridge_id)
    if payload.reply_provider_config_id is not None:
        get_account_provider(db, account.id, payload.reply_provider_config_id)
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
    return s_inbox(get_account_inbox(db, account.id, inbox_id))


@app.put("/api/inboxes/{inbox_id}")
def update_inbox(inbox_id: str, payload: InboxUpdate, db: DbDep, account: CurrentAccountDep):
    inbox = get_account_inbox(db, account.id, inbox_id)
    fields = payload.model_fields_set
    if "display_name" in fields and payload.display_name is not None:
        inbox.display_name = payload.display_name
    if "default_persona_id" in fields and payload.default_persona_id is not None:
        get_account_persona(db, account.id, payload.default_persona_id)
        inbox.default_persona_id = payload.default_persona_id
    if "bridge_id" in fields and payload.bridge_id is not None:
        get_account_bridge(db, account.id, payload.bridge_id)
        inbox.bridge_id = payload.bridge_id
    if payload.clear_bridge:
        inbox.bridge_id = None
    if "reply_provider_config_id" in fields and payload.reply_provider_config_id is not None:
        get_account_provider(db, account.id, payload.reply_provider_config_id)
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
    inbox = get_account_inbox(db, account.id, inbox_id)
    db.query(OutboundMessage).filter(
        OutboundMessage.inbox_id == inbox.id, OutboundMessage.status == "pending"
    ).update({OutboundMessage.status: "canceled"}, synchronize_session=False)
    db.delete(inbox); db.commit()
    return {"status": "deleted", "id": inbox_id}


@app.get("/api/inboxes/{inbox_id}/contacts")
def list_inbox_contacts(inbox_id: str, db: DbDep, account: CurrentAccountDep):
    inbox = get_account_inbox(db, account.id, inbox_id)
    items = (
        db.query(Contact).filter(Contact.inbox_id == inbox.id)
        .order_by(Contact.updated_at.desc()).all()
    )
    return [s_contact(c) for c in items]


@app.post("/api/inboxes/{inbox_id}/outbound")
def seed_outbound(inbox_id: str, payload: OutboundCreate, db: DbDep, account: CurrentAccountDep):
    """Manual outbound seeding (debug / pre-LLM-brain)."""
    inbox = get_account_inbox(db, account.id, inbox_id)
    contact = get_account_contact(db, account.id, payload.contact_id)
    if contact.inbox_id != inbox.id:
        raise HTTPException(status_code=400, detail="Contact 不属于该 inbox")
    o = OutboundMessage(
        inbox_id=inbox.id, contact_id=contact.id,
        chunks=[c.model_dump() for c in payload.chunks],
        status="pending", delivered_at=None, failed_reason=None, created_at=utc_now(),
    )
    db.add(o); db.commit(); db.refresh(o)
    return s_outbound(o, peer_platform_id=contact.peer_platform_id)


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

@app.get("/api/contacts/{contact_id}")
def get_contact(contact_id: str, db: DbDep, account: CurrentAccountDep):
    return s_contact(get_account_contact(db, account.id, contact_id))


@app.get("/api/conversations")
def list_conversations(db: DbDep, account: CurrentAccountDep):
    rows = (
        db.query(Contact, Inbox)
        .join(Inbox, Inbox.id == Contact.inbox_id)
        .filter(Inbox.account_id == account.id)
        .all()
    )
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
    contact = get_account_contact(db, account.id, contact_id)
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
    c = get_account_contact(db, account.id, contact_id)
    fields = payload.model_fields_set
    if "display_name" in fields and payload.display_name is not None: c.display_name = payload.display_name
    if "card_md" in fields: c.card_md = payload.card_md
    if "persona_id" in fields and payload.persona_id is not None:
        get_account_persona(db, account.id, payload.persona_id)
        c.persona_id = payload.persona_id
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
    items = (
        db.query(Archive).filter(Archive.account_id == account.id)
        .order_by(Archive.uploaded_at.desc()).all()
    )
    return [s_archive(a) for a in items]


@app.post("/api/archives")
async def upload_archive(
    db: DbDep, account: CurrentAccountDep,
    inbox_id: str = Form(...), self_wxid: str = Form(...), file: UploadFile = File(...),
):
    inbox = get_account_inbox(db, account.id, inbox_id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    try:
        archive = await ingest_archive(
            db=db, account_id=account.id, inbox=inbox,
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
    items = (
        db.query(DistillJob).filter(DistillJob.account_id == account.id)
        .order_by(DistillJob.created_at.desc()).all()
    )
    return [s_distill_job(j) for j in items]


@app.post("/api/distill-jobs")
def create_distill_job(payload: DistillJobCreate, db: DbDep, account: CurrentAccountDep):
    get_account_inbox(db, account.id, payload.source_inbox_id)
    get_account_persona(db, account.id, payload.target_persona_id)
    get_account_provider(db, account.id, payload.provider_config_id)
    pending = (
        db.query(DistillJob).filter(
            DistillJob.account_id == account.id,
            DistillJob.target_persona_id == payload.target_persona_id,
            DistillJob.status.in_(["pending", "running"]),
        ).first()
    )
    if pending:
        raise HTTPException(status_code=409, detail=f"该 persona 已有进行中的蒸馏任务 {pending.id}")
    j = DistillJob(
        id=new_id("dj"), account_id=account.id,
        source_inbox_id=payload.source_inbox_id,
        target_persona_id=payload.target_persona_id,
        provider_config_id=payload.provider_config_id,
        status="pending", progress={}, error_message=None,
        created_at=utc_now(), started_at=None, finished_at=None,
    )
    db.add(j); db.commit(); db.refresh(j)
    return s_distill_job(j)


@app.get("/api/distill-jobs/{job_id}")
def get_distill_job(job_id: str, db: DbDep, account: CurrentAccountDep):
    j = (
        db.query(DistillJob)
        .filter(DistillJob.id == job_id, DistillJob.account_id == account.id)
        .first()
    )
    if not j:
        raise HTTPException(status_code=404, detail="Distill Job 不存在")
    return s_distill_job(j)


# ---------------------------------------------------------------------------
# Bridge protocol (Bridge daemon ↔ Studio)
#
# A Bridge daemon owns a token; it claims to serve a list of inboxes (defined
# in its local TOML). Handshake validates each inbox belongs to this bridge's
# account and rebinds them to this bridge (Inbox.bridge_id). Studio returns
# the authoritative list of inboxes the bridge should service, plus the
# starting outbound cursor.
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
def bridge_handshake(payload: BridgeHandshake, db: DbDep, bridge: BridgeDep):
    """Auto-upsert an Inbox per (platform, platform_self_id) the bridge logged into.

    Bridge no longer claims inbox_id — it just reports which platform identities
    it successfully authenticated as. Studio looks up an existing Inbox or
    creates one bound to this bridge. Persona/provider configuration is optional
    at discovery time; auto-reply remains disabled until the user configures it.
    """
    now = utc_now()
    bridge.hostname = payload.hostname
    bridge.last_seen_at = now
    bridge.status = "online"
    bridge.updated_at = now

    default_persona = (
        db.query(Persona)
        .filter(Persona.account_id == bridge.account_id, Persona.status == "active")
        .order_by(Persona.created_at.asc())
        .first()
    )

    served: List[Inbox] = []
    for claim in payload.inboxes:
        inbox = (
            db.query(Inbox)
            .filter(
                Inbox.account_id == bridge.account_id,
                Inbox.platform == claim.platform,
                Inbox.platform_self_id == claim.platform_self_id,
            )
            .first()
        )
        if inbox:
            # Existing identity — rebind to this bridge so UI never goes
            # stale when the user moves a login to a different machine.
            inbox.bridge_id = bridge.id
            inbox.updated_at = now
            served.append(inbox)
            continue

        inbox = Inbox(
            id=new_id("ib"),
            account_id=bridge.account_id,
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

    last_outbound_id = (
        db.query(OutboundMessage.id)
        .filter(
            OutboundMessage.inbox_id.in_([i.id for i in served]) if served else False,
            OutboundMessage.status != "pending",
        )
        .order_by(OutboundMessage.id.desc())
        .first()
    )
    cursor = last_outbound_id[0] if last_outbound_id else 0
    db.commit()

    return {
        "bridge_id": bridge.id,
        "account_id": bridge.account_id,
        "inboxes": [_serialize_bridge_inbox_view(i) for i in served],
        "cursor": cursor,
        "no_persona": not default_persona,
    }


@app.post("/api/bridge/heartbeat")
def bridge_heartbeat(db: DbDep, bridge: BridgeDep):
    now = utc_now()
    bridge.last_seen_at = now
    if bridge.status != "online":
        bridge.status = "online"
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
                autoreply_enabled=False, pending_reply=False,
                status="active", last_seen_platform_msg_id=None,
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
            external_id=external_id, source="live",
            role=m.role, sender_name=None, content=m.content,
            timestamp=ts, archive_msg_idx=None, created_at=now,
        ))
        contact.last_seen_platform_msg_id = m.platform_msg_id
        contact.updated_at = now
        if m.role == "counterpart" and inbox.enabled and contact.autoreply_enabled:
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
                        OutboundMessage.status == "pending",
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
    if o.status != "pending":
        return {"status": o.status}
    now = utc_now()
    if payload.result == "sent":
        o.status = "delivered"
        o.delivered_at = now
    else:
        o.status = "failed"
        o.failed_reason = payload.reason
    db.commit()
    return {"status": o.status}
