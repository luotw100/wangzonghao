import argparse
import asyncio
import logging
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy.orm import Session

from robot import auth as auth_lib
from robot.auth import (
    SESSION_COOKIE_NAME,
    CODE_TTL,
    CODE_MAX_ATTEMPTS,
    RateLimitError,
    check_request_code_rate_limits,
    clear_session_cookie,
    generate_code,
    get_current_account,
    hash_code,
    is_admin_email,
    issue_session,
    new_account_id,
    new_identity_id,
    require_admin,
    revoke_all_sessions_for_account,
    revoke_session_by_token,
    set_session_cookie,
)
from robot.clients import ChatAdapter
from robot.db import SessionLocal, ensure_database, get_db, utc_now
from robot.distill.ingest import ingest_archive
from robot.email_client import (
    ResendClient,
    ResendConfig,
    render_account_approved_email,
    render_login_code_email,
)
from robot.models import (
    Account,
    AccountIdentity,
    Character,
    ChatArchive,
    Contact,
    DistillJob,
    LoginCode,
    Message,
    ProviderConfig,
    SessionRecord,
)
from robot.schemas import (
    CharacterCreate,
    CharacterUpdate,
    ContactUpdate,
    ProviderConfigCreate,
    ProviderConfigUpdate,
    RequestCodeIn,
    VerifyCodeIn,
)

logger = logging.getLogger(__name__)

ensure_database()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    client = getattr(app.state, "resend_client", None)
    if client:
        await client.close()


app = FastAPI(title="Laborster Robot API", lifespan=lifespan)
app.state.chat_api_base_url = None
app.state.resend_client = None
app.state.admin_emails = []
app.state.cookie_secure = False


# --- Helpers ---

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
        "adapter_identities": ch.adapter_identities or {},
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
        "chat_user_id": contact.chat_user_id,
        "card_md": contact.card_md,
        "status": contact.status,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }


def serialize_session(session_record: SessionRecord) -> Dict[str, Any]:
    return {
        "id": session_record.id,
        "contact_id": session_record.contact_id,
        "adapter_type": session_record.adapter_type,
        "adapter_thread_id": session_record.adapter_thread_id,
        "status": session_record.status,
        "created_at": session_record.created_at,
        "updated_at": session_record.updated_at,
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


def serialize_account(acc: Account, db: Session, *, include_email: bool = True) -> Dict[str, Any]:
    email = None
    if include_email:
        ident = (
            db.query(AccountIdentity)
            .filter(AccountIdentity.account_id == acc.id, AccountIdentity.provider == "email")
            .first()
        )
        email = ident.identifier if ident else None
    return {
        "id": acc.id,
        "role": acc.role,
        "status": acc.status,
        "display_name": acc.display_name,
        "email": email,
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
    if account.role == "admin":
        return
    if character.account_id != account.id:
        raise HTTPException(status_code=403, detail="无权访问该 Character")


def ensure_contact_owner(account: Account, contact: Contact, db: Session) -> None:
    if account.role == "admin":
        return
    ch = db.query(Character).filter(Character.id == contact.character_id).first()
    if not ch or ch.account_id != account.id:
        raise HTTPException(status_code=403, detail="无权访问该 Contact")


def get_chat_api_base_url(request: Request) -> str:
    base_url = getattr(request.app.state, "chat_api_base_url", None)
    if not base_url:
        raise HTTPException(status_code=500, detail="Robot API 未配置 Chat API Base URL")
    return str(base_url)


async def get_adapter(request: Request) -> AsyncIterator[ChatAdapter]:
    adapter = ChatAdapter(get_chat_api_base_url(request))
    try:
        yield adapter
    finally:
        await adapter.close()


def get_resend(request: Request) -> ResendClient:
    client = getattr(request.app.state, "resend_client", None)
    if not client:
        raise HTTPException(status_code=500, detail="邮件服务未配置")
    return client


def client_ip(request: Request) -> Optional[str]:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def client_user_agent(request: Request) -> Optional[str]:
    return request.headers.get("user-agent")


# --- Auth endpoints ---

@app.post("/api/auth/request-code")
async def request_login_code(
    payload: RequestCodeIn,
    request: Request,
    db: Session = Depends(get_db),
):
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="邮箱格式不正确")

    try:
        check_request_code_rate_limits(db, email)
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    code = generate_code()
    now = utc_now()
    db.add(LoginCode(
        provider="email",
        identifier=email,
        code_hash=hash_code(code),
        expires_at=now + CODE_TTL,
        ip=client_ip(request),
        created_at=now,
    ))
    db.commit()

    resend = get_resend(request)
    html, text = render_login_code_email(code)
    try:
        await resend.send_email(
            to=email,
            subject="Laborster 登录验证码",
            html=html,
            text=text,
        )
    except httpx.HTTPStatusError as exc:
        logger.error("Resend send failed: %s", exc)
        raise HTTPException(status_code=502, detail="发送邮件失败，请稍后再试")

    return {"status": "ok", "expires_in_seconds": int(CODE_TTL.total_seconds())}


@app.post("/api/auth/verify-code")
def verify_login_code(
    payload: VerifyCodeIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    email = payload.email.strip().lower()
    code = payload.code.strip()
    if not email or not code:
        raise HTTPException(status_code=400, detail="邮箱和验证码不能为空")

    now = utc_now()
    candidate = (
        db.query(LoginCode)
        .filter(
            LoginCode.identifier == email,
            LoginCode.consumed_at.is_(None),
            LoginCode.expires_at > now,
        )
        .order_by(LoginCode.id.desc())
        .first()
    )
    if not candidate:
        raise HTTPException(status_code=400, detail="验证码已失效，请重新获取")

    if candidate.attempts >= CODE_MAX_ATTEMPTS:
        candidate.consumed_at = now  # burn it
        db.commit()
        raise HTTPException(status_code=429, detail="尝试次数过多，请重新获取验证码")

    if candidate.code_hash != hash_code(code):
        candidate.attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="验证码不正确")

    candidate.consumed_at = now
    db.flush()

    # Resolve or create the account+identity
    identity = (
        db.query(AccountIdentity)
        .filter(AccountIdentity.provider == "email", AccountIdentity.identifier == email)
        .first()
    )
    new_account_created = False
    if identity:
        account = db.query(Account).filter(Account.id == identity.account_id).first()
        if not account:
            raise HTTPException(status_code=500, detail="账号数据异常，请联系管理员")
    else:
        is_admin = is_admin_email(email, request.app.state.admin_emails)
        role = "admin" if is_admin else "operator_owner"
        status = "active" if is_admin else "pending"
        account = Account(
            id=new_account_id(),
            role=role,
            status=status,
            display_name=email.split("@")[0],
            created_at=now,
            updated_at=now,
        )
        db.add(account)
        db.add(AccountIdentity(
            id=new_identity_id(),
            account_id=account.id,
            provider="email",
            identifier=email,
            verified_at=now,
            created_at=now,
        ))
        db.flush()
        new_account_created = True

    # Per design: pending login is rejected at the gate, but the verified-code
    # itself is consumed (already done above) so they re-enter the request flow.
    if account.status == "disabled":
        db.commit()
        raise HTTPException(status_code=403, detail="账号已被停用")

    if account.status == "pending":
        db.commit()
        raise HTTPException(status_code=403, detail="账号待审批，请等待管理员通过后再登录")

    # Issue session
    token, _row = issue_session(
        db,
        account_id=account.id,
        user_agent=client_user_agent(request),
        ip=client_ip(request),
    )
    account.last_login_at = now
    db.commit()

    set_session_cookie(response, token, secure=request.app.state.cookie_secure)
    return {
        "status": "ok",
        "new_account": new_account_created,
        "account": serialize_account(account, db),
    }


@app.post("/api/auth/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        revoke_session_by_token(db, token)
    clear_session_cookie(response)
    return {"status": "ok"}


@app.get("/api/auth/me")
def get_me(
    account: Account = Depends(get_current_account),
    db: Session = Depends(get_db),
):
    return serialize_account(account, db)


# --- Admin endpoints ---

@app.get("/api/admin/accounts")
def admin_list_accounts(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _admin: Account = Depends(require_admin),
):
    q = db.query(Account)
    if status:
        q = q.filter(Account.status == status)
    accounts = q.order_by(Account.created_at.desc()).all()
    return [serialize_account(a, db) for a in accounts]


@app.post("/api/admin/accounts/{account_id}/approve")
async def admin_approve_account(
    account_id: str,
    request: Request,
    db: Session = Depends(get_db),
    adapter: ChatAdapter = Depends(get_adapter),
    _admin: Account = Depends(require_admin),
):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account 不存在")
    if acc.role == "admin":
        raise HTTPException(status_code=400, detail="管理员账号无需审批")
    if acc.status == "active":
        return serialize_account(acc, db)
    if acc.status == "disabled":
        raise HTTPException(status_code=400, detail="账号已被停用，无法审批通过")

    now = utc_now()
    acc.status = "active"
    acc.updated_at = now

    # Auto-create a default Character so the streamer has something on first login
    has_character = (
        db.query(Character).filter(Character.account_id == acc.id).first() is not None
    )
    if not has_character:
        default_name = acc.display_name or acc.id
        chat_user = await adapter.create_user(default_name)
        ch = Character(
            id=f"ch_{uuid.uuid4().hex[:8]}",
            account_id=acc.id,
            name=default_name,
            adapter_identities={"chat": chat_user["id"]},
            provider_config_id=None,
            status="active",
            created_at=now,
            updated_at=now,
        )
        db.add(ch)

    db.commit()
    db.refresh(acc)

    # Best-effort approval email (do not fail the API on email errors)
    ident = (
        db.query(AccountIdentity)
        .filter(AccountIdentity.account_id == acc.id, AccountIdentity.provider == "email")
        .first()
    )
    if ident:
        try:
            html, text = render_account_approved_email()
            await get_resend(request).send_email(
                to=ident.identifier,
                subject="账号已通过审批 — Laborster",
                html=html,
                text=text,
            )
        except Exception as exc:
            logger.warning("Failed to send approval email to %s: %s", ident.identifier, exc)

    return serialize_account(acc, db)


@app.post("/api/admin/accounts/{account_id}/reject")
def admin_reject_account(
    account_id: str,
    db: Session = Depends(get_db),
    _admin: Account = Depends(require_admin),
):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account 不存在")
    if acc.role == "admin":
        raise HTTPException(status_code=400, detail="不能拒绝管理员账号")
    acc.status = "disabled"
    acc.updated_at = utc_now()
    db.commit()
    revoke_all_sessions_for_account(db, acc.id)
    return serialize_account(acc, db)


@app.post("/api/admin/accounts/{account_id}/disable")
def admin_disable_account(
    account_id: str,
    db: Session = Depends(get_db),
    admin: Account = Depends(require_admin),
):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="Account 不存在")
    if acc.id == admin.id:
        raise HTTPException(status_code=400, detail="不能停用自己的账号")
    acc.status = "disabled"
    acc.updated_at = utc_now()
    db.commit()
    revoke_all_sessions_for_account(db, acc.id)
    return serialize_account(acc, db)


@app.get("/api/admin/characters")
def admin_list_characters(
    db: Session = Depends(get_db),
    _admin: Account = Depends(require_admin),
):
    items = db.query(Character).order_by(Character.created_at.desc()).all()
    return [serialize_character(c, db) for c in items]


# --- Provider Configs (shared, all logged-in accounts can see/edit) ---

@app.post("/api/provider-configs")
def create_provider_config(
    provider_in: ProviderConfigCreate,
    db: Session = Depends(get_db),
    _account: Account = Depends(get_current_account),
):
    now = utc_now()
    pc = ProviderConfig(
        id=f"p_{uuid.uuid4().hex[:8]}",
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
def list_provider_configs(
    db: Session = Depends(get_db),
    _account: Account = Depends(get_current_account),
):
    items = db.query(ProviderConfig).order_by(ProviderConfig.updated_at.desc()).all()
    return [serialize_provider_config(p) for p in items]


@app.put("/api/provider-configs/{provider_config_id}")
def update_provider_config(
    provider_config_id: str,
    provider_update: ProviderConfigUpdate,
    db: Session = Depends(get_db),
    _account: Account = Depends(get_current_account),
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
    db: Session = Depends(get_db),
    _account: Account = Depends(get_current_account),
):
    pc = get_provider_config_or_404(db, provider_config_id)
    db.delete(pc)
    db.commit()
    return {"status": "deleted", "id": provider_config_id}


# --- Characters ---

@app.post("/api/characters")
async def create_character(
    character_in: CharacterCreate,
    db: Session = Depends(get_db),
    adapter: ChatAdapter = Depends(get_adapter),
    account: Account = Depends(get_current_account),
):
    if account.role not in ("admin", "operator_owner"):
        raise HTTPException(status_code=403, detail="无权创建 Character")
    if character_in.provider_config_id:
        get_provider_config_or_404(db, character_in.provider_config_id)

    chat_user = await adapter.create_user(character_in.name)
    now = utc_now()
    ch = Character(
        id=f"ch_{uuid.uuid4().hex[:8]}",
        account_id=account.id,
        name=character_in.name,
        adapter_identities={"chat": chat_user["id"]},
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
def list_characters(
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    q = db.query(Character)
    if account.role != "admin":
        q = q.filter(Character.account_id == account.id)
    items = q.order_by(Character.created_at.desc()).all()
    return [serialize_character(o, db) for o in items]


@app.get("/api/characters/{character_id}")
def get_character(
    character_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)
    return serialize_character(ch, db)


@app.put("/api/characters/{character_id}")
def update_character(
    character_id: str,
    ch_update: CharacterUpdate,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)
    fields = ch_update.model_fields_set
    if "name" in fields and ch_update.name is not None:
        ch.name = ch_update.name
    if "persona_md" in fields:
        ch.persona_md = ch_update.persona_md
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
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)
    ch.status = "deleted"
    ch.updated_at = utc_now()
    db.commit()
    return {"status": "deleted", "id": character_id}


# --- Contacts ---

@app.get("/api/characters/{character_id}/contacts")
def list_contacts(
    character_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
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
def get_contact(
    contact_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    contact = get_contact_or_404(db, contact_id)
    ensure_contact_owner(account, contact, db)
    return serialize_contact(contact)


@app.put("/api/contacts/{contact_id}")
def update_contact(
    contact_id: str,
    contact_update: ContactUpdate,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
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


# --- Chat Archives ---

@app.post("/api/characters/{character_id}/chat-archives")
async def upload_chat_archive(
    character_id: str,
    self_wxid: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    adapter: ChatAdapter = Depends(get_adapter),
    account: Account = Depends(get_current_account),
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
            chat_adapter=adapter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)

    return serialize_archive(archive)


@app.get("/api/characters/{character_id}/chat-archives")
def list_archives(
    character_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)
    items = (
        db.query(ChatArchive)
        .filter(ChatArchive.character_id == character_id)
        .order_by(ChatArchive.uploaded_at.desc())
        .all()
    )
    return [serialize_archive(a) for a in items]


# --- Distill Jobs ---

@app.post("/api/characters/{character_id}/distill-jobs")
def create_distill_job(
    character_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
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
        id=f"dj_{uuid.uuid4().hex[:8]}",
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
def list_distill_jobs(
    character_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
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
def get_distill_job(
    job_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    job = db.query(DistillJob).filter(DistillJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Distill Job 不存在")
    ch = get_character_or_404(db, job.character_id)
    ensure_character_owner(account, ch)
    return serialize_distill_job(job)


# --- Sessions (read-only; created internally by ingest) ---

@app.get("/api/characters/{character_id}/sessions")
def list_sessions(
    character_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    ch = get_character_or_404(db, character_id)
    ensure_character_owner(account, ch)
    sessions = (
        db.query(SessionRecord)
        .join(Contact, Contact.id == SessionRecord.contact_id)
        .filter(Contact.character_id == character_id)
        .order_by(SessionRecord.created_at.desc())
        .all()
    )
    return [serialize_session(s) for s in sessions]


@app.get("/api/sessions/{session_id}")
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    account: Account = Depends(get_current_account),
):
    s = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session 不存在")
    contact = db.query(Contact).filter(Contact.id == s.contact_id).first()
    if contact:
        ensure_contact_owner(account, contact, db)
    return serialize_session(s)


# --- Planned Replies (long-poll) ---

@app.get("/api/sessions/{session_id}/planned-replies")
async def get_planned_replies(
    session_id: str,
    timeout: int = Query(0, ge=0),
    last_count: int = Query(-1),
    account: Account = Depends(get_current_account),
):
    start_time = time.time()

    while True:
        db = SessionLocal()
        try:
            s = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
            if not s:
                raise HTTPException(status_code=404, detail="Session 不存在")
            contact = db.query(Contact).filter(Contact.id == s.contact_id).first()
            if contact:
                ensure_contact_owner(account, contact, db)
            replies = (
                db.query(Message)
                .filter(
                    Message.contact_id == s.contact_id,
                    Message.source == "live",
                    Message.role == "self",
                    Message.status == "scheduled",
                )
                .order_by(Message.scheduled_for.asc())
                .all()
            )
            result = [
                {
                    "id": r.id,
                    "content": r.content,
                    "status": r.status,
                    "scheduled_for": r.scheduled_for.isoformat() if r.scheduled_for else None,
                }
                for r in replies
            ]
        finally:
            db.close()

        if last_count >= 0 and len(result) != last_count:
            return result
        if last_count < 0 and result:
            return result

        elapsed = time.time() - start_time
        if elapsed >= timeout:
            return result

        sleep_time = min(0.2, timeout - elapsed)
        await asyncio.sleep(sleep_time)


# --- Chat Conversations passthrough (for debug UI to pick threads) ---

@app.get("/api/conversations")
async def list_chat_conversations(
    adapter: ChatAdapter = Depends(get_adapter),
    _account: Account = Depends(get_current_account),
):
    try:
        return await adapter.list_conversations()
    except httpx.HTTPStatusError as err:
        raise HTTPException(status_code=err.response.status_code, detail="获取会话列表失败")


# --- Entrypoint ---

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Robot API service")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--chat-api-base-url", required=True)
    parser.add_argument("--resend-api-key", required=True,
                        help="Resend API key（必填）")
    parser.add_argument("--resend-from", required=True,
                        help="发件地址，例如 'Laborster <noreply@luotw.top>'")
    parser.add_argument("--admin-emails", required=True,
                        help="逗号分隔的管理员邮箱白名单（必填，至少一个）")
    parser.add_argument("--cookie-secure", required=True, choices=["true", "false"],
                        help="是否在 cookie 上设置 Secure（生产 HTTPS=true，本地 HTTP=false）")
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    args = parse_args()
    app.state.chat_api_base_url = args.chat_api_base_url.rstrip("/")
    app.state.resend_client = ResendClient(
        ResendConfig(api_key=args.resend_api_key, from_address=args.resend_from)
    )
    admin_emails: List[str] = [e.strip() for e in args.admin_emails.split(",") if e.strip()]
    if not admin_emails:
        raise SystemExit("--admin-emails 至少需要一个邮箱")
    app.state.admin_emails = admin_emails
    app.state.cookie_secure = (args.cookie_secure == "true")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
