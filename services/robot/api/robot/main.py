import logging
import tempfile
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from robot.auth_utils import hash_token, new_session_token, verify_password
from robot.db import ensure_database, get_db, utc_now
from robot.distill.ingest import ingest_archive
from robot.models import (
    Account,
    AuthSession,
    Character,
    ChatArchive,
    Contact,
    DistillJob,
    ProviderConfig,
)
from robot.schemas import (
    CharacterCreate,
    CharacterUpdate,
    ContactUpdate,
    LoginRequest,
    ProviderConfigCreate,
    ProviderConfigUpdate,
)

logger = logging.getLogger(__name__)

ensure_database()

app = FastAPI(title="Laborster Robot API")

DbDep = Annotated[Session, Depends(get_db)]


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def get_auth_session(
    db: DbDep,
    authorization: Annotated[Optional[str], Header()] = None,
) -> AuthSession:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少登录令牌"
        )
    token = authorization.removeprefix("Bearer ").strip()
    auth_session = (
        db.query(AuthSession)
        .filter(AuthSession.id == hash_token(token))
        .first()
    )
    if not auth_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效"
        )
    account = db.query(Account).filter(Account.id == auth_session.account_id).first()
    if not account or account.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效"
        )
    auth_session.last_seen_at = utc_now()
    db.commit()
    return auth_session


AuthSessionDep = Annotated[AuthSession, Depends(get_auth_session)]


def current_account(auth_session: AuthSessionDep, db: DbDep) -> Account:
    return db.query(Account).filter(Account.id == auth_session.account_id).first()


CurrentAccountDep = Annotated[Account, Depends(current_account)]


# ---------------------------------------------------------------------------
# Helpers / serializers
# ---------------------------------------------------------------------------

def new_id(prefix: str, size: int = 8) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:size]}"


def mask_api_key(api_key: Optional[str]) -> Optional[str]:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def serialize_provider_config(provider_config: ProviderConfig) -> Dict[str, Any]:
    return {
        "id": provider_config.id,
        "name": provider_config.name,
        "base_url": provider_config.base_url,
        "default_model": provider_config.default_model,
        "has_api_key": bool(provider_config.api_key),
        "api_key_preview": mask_api_key(provider_config.api_key),
        "created_at": provider_config.created_at,
        "updated_at": provider_config.updated_at,
    }


def serialize_character(ch: Character, db: Session) -> Dict[str, Any]:
    pc = None
    if ch.provider_config_id:
        pc = db.query(ProviderConfig).filter(ProviderConfig.id == ch.provider_config_id).first()
    return {
        "id": ch.id,
        "account_id": ch.account_id,
        "name": ch.name,
        "persona_md": ch.persona_md,
        "wechat_wxid_self": ch.wechat_wxid_self,
        "provider_config_id": ch.provider_config_id,
        "provider_config": serialize_provider_config(pc) if pc else None,
        "status": ch.status,
        "created_at": ch.created_at,
        "updated_at": ch.updated_at,
    }


def serialize_contact(contact: Contact) -> Dict[str, Any]:
    return {
        "id": contact.id,
        "character_id": contact.character_id,
        "display_name": contact.display_name,
        "wechat_wxid": contact.wechat_wxid,
        "card_md": contact.card_md,
        "status": contact.status,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }


def serialize_archive(archive: ChatArchive) -> Dict[str, Any]:
    return {
        "id": archive.id,
        "character_id": archive.character_id,
        "filename": archive.filename,
        "self_wxid": archive.self_wxid,
        "message_count": archive.message_count,
        "contact_count": archive.contact_count,
        "uploaded_at": archive.uploaded_at,
    }


def serialize_distill_job(job: DistillJob) -> Dict[str, Any]:
    return {
        "id": job.id,
        "character_id": job.character_id,
        "status": job.status,
        "progress": job.progress or {},
        "error_message": job.error_message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def serialize_account(acc: Account) -> Dict[str, Any]:
    return {
        "id": acc.id,
        "username": acc.username,
        "display_name": acc.display_name,
        "status": acc.status,
        "created_at": acc.created_at,
        "last_login_at": acc.last_login_at,
    }


def get_provider_config_or_404(db: Session, provider_config_id: str) -> ProviderConfig:
    pc = db.query(ProviderConfig).filter(ProviderConfig.id == provider_config_id).first()
    if not pc:
        raise HTTPException(status_code=404, detail="Provider Config 不存在")
    return pc


def get_character_or_404(db: Session, character_id: str) -> Character:
    ch = db.query(Character).filter(Character.id == character_id).first()
    if not ch:
        raise HTTPException(status_code=404, detail="Character 不存在")
    return ch


def get_contact_or_404(db: Session, contact_id: str) -> Contact:
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact 不存在")
    return contact


def ensure_character_owner(account: Account, character: Character) -> None:
    if character.account_id != account.id:
        raise HTTPException(status_code=403, detail="无权访问该 Character")


def ensure_contact_owner(account: Account, contact: Contact, db: Session) -> None:
    ch = db.query(Character).filter(Character.id == contact.character_id).first()
    if not ch or ch.account_id != account.id:
        raise HTTPException(status_code=403, detail="无权访问该 Contact")


# ---------------------------------------------------------------------------
# Health + Auth endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(login_in: LoginRequest, db: DbDep):
    account = db.query(Account).filter(Account.username == login_in.username).first()
    if not account or account.status != "active":
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(login_in.password, account.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = new_session_token()
    now = utc_now()
    auth_session = AuthSession(
        id=hash_token(token),
        account_id=account.id,
        created_at=now,
        last_seen_at=now,
    )
    account.last_login_at = now
    account.updated_at = now
    db.add(auth_session)
    db.commit()
    db.refresh(account)
    return {"token": token, "account": serialize_account(account)}


@app.post("/api/auth/logout")
def logout(auth_session: AuthSessionDep, db: DbDep):
    db.delete(auth_session)
    db.commit()
    return {"status": "ok"}


@app.get("/api/auth/me")
def me(account: CurrentAccountDep):
    return serialize_account(account)


# ---------------------------------------------------------------------------
# Provider Configs (shared across all logged-in accounts)
# ---------------------------------------------------------------------------

@app.post("/api/provider-configs")
def create_provider_config(
    provider_in: ProviderConfigCreate,
    db: DbDep,
    _account: CurrentAccountDep,
):
    now = utc_now()
    pc = ProviderConfig(
        id=new_id("p"),
        name=provider_in.name,
        base_url=provider_in.base_url.rstrip("/"),
        api_key=provider_in.api_key,
        default_model=provider_in.default_model,
        created_at=now,
        updated_at=now,
    )
    db.add(pc)
    db.commit()
    db.refresh(pc)
    return serialize_provider_config(pc)


@app.get("/api/provider-configs")
def list_provider_configs(db: DbDep, _account: CurrentAccountDep):
    items = db.query(ProviderConfig).order_by(ProviderConfig.updated_at.desc()).all()
    return [serialize_provider_config(p) for p in items]


@app.put("/api/provider-configs/{provider_config_id}")
def update_provider_config(
    provider_config_id: str,
    provider_update: ProviderConfigUpdate,
    db: DbDep,
    _account: CurrentAccountDep,
):
    pc = get_provider_config_or_404(db, provider_config_id)
    fields = provider_update.model_fields_set
    if "name" in fields and provider_update.name is not None:
        pc.name = provider_update.name
    if "base_url" in fields and provider_update.base_url is not None:
        pc.base_url = provider_update.base_url.rstrip("/")
    if "api_key" in fields:
        pc.api_key = provider_update.api_key
    if "default_model" in fields and provider_update.default_model is not None:
        pc.default_model = provider_update.default_model
    pc.updated_at = utc_now()
    db.commit()
    db.refresh(pc)
    return serialize_provider_config(pc)


@app.delete("/api/provider-configs/{provider_config_id}")
def delete_provider_config(
    provider_config_id: str,
    db: DbDep,
    _account: CurrentAccountDep,
):
    pc = get_provider_config_or_404(db, provider_config_id)
    db.delete(pc)
    db.commit()
    return {"status": "deleted", "id": provider_config_id}


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------

@app.post("/api/characters")
def create_character(
    character_in: CharacterCreate,
    db: DbDep,
    account: CurrentAccountDep,
):
    if character_in.provider_config_id:
        get_provider_config_or_404(db, character_in.provider_config_id)
    now = utc_now()
    ch = Character(
        id=new_id("ch"),
        account_id=account.id,
        name=character_in.name,
        wechat_wxid_self=character_in.wechat_wxid_self,
        provider_config_id=character_in.provider_config_id,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return serialize_character(ch, db)


@app.get("/api/characters")
def list_characters(db: DbDep, account: CurrentAccountDep):
    items = (
        db.query(Character)
        .filter(Character.account_id == account.id)
        .order_by(Character.created_at.desc())
        .all()
    )
    return [serialize_character(o, db) for o in items]


@app.get("/api/characters/{character_id}")
def get_character(character_id: str, db: DbDep, account: CurrentAccountDep):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)
    return serialize_character(ch, db)


@app.put("/api/characters/{character_id}")
def update_character(
    character_id: str,
    ch_update: CharacterUpdate,
    db: DbDep,
    account: CurrentAccountDep,
):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)
    fields = ch_update.model_fields_set
    if "name" in fields and ch_update.name is not None:
        ch.name = ch_update.name
    if "persona_md" in fields:
        ch.persona_md = ch_update.persona_md
    if "wechat_wxid_self" in fields:
        ch.wechat_wxid_self = ch_update.wechat_wxid_self
    if "provider_config_id" in fields:
        if ch_update.provider_config_id is not None:
            get_provider_config_or_404(db, ch_update.provider_config_id)
        ch.provider_config_id = ch_update.provider_config_id
    if "status" in fields and ch_update.status is not None:
        ch.status = ch_update.status
    ch.updated_at = utc_now()
    db.commit()
    db.refresh(ch)
    return serialize_character(ch, db)


@app.delete("/api/characters/{character_id}")
def delete_character(
    character_id: str,
    db: DbDep,
    account: CurrentAccountDep,
):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)
    ch.status = "deleted"
    ch.updated_at = utc_now()
    db.commit()
    return {"status": "deleted", "id": character_id}


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

@app.get("/api/characters/{character_id}/contacts")
def list_contacts(character_id: str, db: DbDep, account: CurrentAccountDep):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)
    items = (
        db.query(Contact)
        .filter(Contact.character_id == character_id)
        .order_by(Contact.created_at.desc())
        .all()
    )
    return [serialize_contact(c) for c in items]


@app.get("/api/contacts/{contact_id}")
def get_contact(contact_id: str, db: DbDep, account: CurrentAccountDep):
    contact = get_contact_or_404(db, contact_id)
    ensure_contact_owner(account, contact, db)
    return serialize_contact(contact)


@app.put("/api/contacts/{contact_id}")
def update_contact(
    contact_id: str,
    contact_update: ContactUpdate,
    db: DbDep,
    account: CurrentAccountDep,
):
    contact = get_contact_or_404(db, contact_id)
    ensure_contact_owner(account, contact, db)
    fields = contact_update.model_fields_set
    if "display_name" in fields and contact_update.display_name is not None:
        contact.display_name = contact_update.display_name
    if "card_md" in fields:
        contact.card_md = contact_update.card_md
    if "status" in fields and contact_update.status is not None:
        contact.status = contact_update.status
    contact.updated_at = utc_now()
    db.commit()
    db.refresh(contact)
    return serialize_contact(contact)


# ---------------------------------------------------------------------------
# Chat Archives
# ---------------------------------------------------------------------------

@app.post("/api/characters/{character_id}/chat-archives")
async def upload_chat_archive(
    character_id: str,
    db: DbDep,
    account: CurrentAccountDep,
    self_wxid: str = Form(...),
    file: UploadFile = File(...),
):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    try:
        archive = await ingest_archive(
            db=db,
            character=ch,
            self_wxid=self_wxid,
            src_path=tmp_path,
            original_filename=file.filename or tmp_path.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)

    return serialize_archive(archive)


@app.get("/api/characters/{character_id}/chat-archives")
def list_archives(character_id: str, db: DbDep, account: CurrentAccountDep):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)
    items = (
        db.query(ChatArchive)
        .filter(ChatArchive.character_id == character_id)
        .order_by(ChatArchive.uploaded_at.desc())
        .all()
    )
    return [serialize_archive(a) for a in items]


# ---------------------------------------------------------------------------
# Distill Jobs
# ---------------------------------------------------------------------------

@app.post("/api/characters/{character_id}/distill-jobs")
def create_distill_job(character_id: str, db: DbDep, account: CurrentAccountDep):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)
    if not ch.provider_config_id:
        raise HTTPException(status_code=400, detail="Character 未配置 Provider Config，无法蒸馏")
    pending = (
        db.query(DistillJob)
        .filter(
            DistillJob.character_id == character_id,
            DistillJob.status.in_(["pending", "running"]),
        )
        .first()
    )
    if pending:
        raise HTTPException(status_code=409, detail=f"已有进行中的蒸馏任务 {pending.id}")
    job = DistillJob(
        id=new_id("dj"),
        character_id=character_id,
        status="pending",
        progress={},
        created_at=utc_now(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return serialize_distill_job(job)


@app.get("/api/characters/{character_id}/distill-jobs")
def list_distill_jobs(character_id: str, db: DbDep, account: CurrentAccountDep):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)
    jobs = (
        db.query(DistillJob)
        .filter(DistillJob.character_id == character_id)
        .order_by(DistillJob.created_at.desc())
        .all()
    )
    return [serialize_distill_job(j) for j in jobs]


@app.get("/api/distill-jobs/{job_id}")
def get_distill_job(job_id: str, db: DbDep, account: CurrentAccountDep):
    job = db.query(DistillJob).filter(DistillJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Distill Job 不存在")
    ch = get_character_or_404(db, job.character_id)
    ensure_character_owner(account, ch)
    return serialize_distill_job(job)
