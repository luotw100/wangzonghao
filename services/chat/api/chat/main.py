import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload

from chat.auth_utils import hash_token, new_session_token, verify_password
from chat.db import SessionLocal, get_db, utc_now
from chat.enums import AccountStatus, CommandStatus, MessageSource, MessageType, SenderType
from chat.migrate import run_migrations
from chat.models import (
    Account,
    AuthSession,
    Contact,
    Conversation,
    Message,
)
from chat.s3 import (
    s3_generate_storage_key,
    s3_presigned_get_url,
    s3_presigned_put_url,
)
from chat.schemas import (
    AccountRead,
    ContactCreate,
    ContactRead,
    ContactUpdate,
    ConversationMessages,
    ConversationRead,
    LoginRequest,
    LoginResponse,
    MessageCreate,
    StatusResponse,
    UploadPresignRequest,
    UploadPresignResponse,
)

from contextlib import asynccontextmanager

UPLOAD_MAX_SIZE_BYTES: int | None = None


def _init_upload_max_size() -> int:
    import os
    val = os.environ.get("UPLOAD_MAX_SIZE_MB")
    if not val:
        raise RuntimeError("UPLOAD_MAX_SIZE_MB environment variable is required")
    mb = int(val)
    if mb <= 0:
        raise RuntimeError("UPLOAD_MAX_SIZE_MB must be a positive integer")
    return mb * 1024 * 1024


def _get_upload_max_size() -> int:
    global UPLOAD_MAX_SIZE_BYTES
    if UPLOAD_MAX_SIZE_BYTES is None:
        UPLOAD_MAX_SIZE_BYTES = _init_upload_max_size()
    return UPLOAD_MAX_SIZE_BYTES


MIME_TYPE_MAP: dict[str, MessageType] = {
    "image/": MessageType.IMAGE,
    "audio/": MessageType.AUDIO,
    "video/": MessageType.VIDEO,
}


def _infer_msg_type(mime_type: str) -> MessageType:
    for prefix, mt in MIME_TYPE_MAP.items():
        if mime_type.startswith(prefix):
            return mt
    return MessageType.FILE


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    _get_upload_max_size()
    yield


app = FastAPI(title="Laborster Chat", lifespan=lifespan)

DbDep = Annotated[Session, Depends(get_db)]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def get_auth_session(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthSession:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少登录令牌"
        )
    token = authorization.removeprefix("Bearer ").strip()
    auth_session = (
        db.query(AuthSession)
        .options(joinedload(AuthSession.account))
        .filter(AuthSession.id == hash_token(token))
        .first()
    )
    if (
        not auth_session
        or not auth_session.account
        or auth_session.account.is_deleted
        or auth_session.account.status != AccountStatus.ACTIVE
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效"
        )
    if auth_session.expires_at is not None and auth_session.expires_at < utc_now():
        db.delete(auth_session)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已超时"
        )
    auth_session.last_seen_at = utc_now()
    auth_session.expires_at = utc_now() + timedelta(hours=24)
    db.commit()
    return auth_session


AuthSessionDep = Annotated[AuthSession, Depends(get_auth_session)]


def current_account(auth_session: AuthSessionDep) -> Account:
    return auth_session.account


CurrentAccountDep = Annotated[Account, Depends(current_account)]


def get_contact_or_404(
    db: Session, account_id: str, contact_id: str, include_deleted: bool = False
) -> Contact:
    query = db.query(Contact).filter(
        Contact.account_id == account_id, Contact.id == contact_id
    )
    if not include_deleted:
        query = query.filter(Contact.is_deleted.is_(False))
    contact = query.first()
    if not contact:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return contact


def get_conversation_or_404(
    db: Session,
    account_id: str,
    conversation_id: str,
    include_deleted: bool = False,
) -> Conversation:
    query = (
        db.query(Conversation)
        .options(joinedload(Conversation.contact))
        .filter(
            Conversation.account_id == account_id, Conversation.id == conversation_id
        )
    )
    if not include_deleted:
        query = query.filter(Conversation.is_deleted.is_(False))
    conversation = query.first()
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


def get_or_create_direct_conversation(
    db: Session, account_id: str, contact: Contact, title: str | None = None
) -> Conversation:
    conversation = (
        db.query(Conversation)
        .options(joinedload(Conversation.contact))
        .filter(
            Conversation.account_id == account_id, Conversation.contact_id == contact.id
        )
        .first()
    )
    if conversation:
        if conversation.is_deleted:
            conversation.is_deleted = False
            conversation.deleted_at = None
        if title:
            conversation.title = title
        conversation.updated_at = utc_now()
        return conversation

    now = utc_now()
    conversation = Conversation(
        id=new_id("c"),
        account_id=account_id,
        contact_id=contact.id,
        title=title or contact.display_name,
        is_deleted=False,
        deleted_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(conversation)
    return conversation


def add_message(
    db: Session,
    conversation: Conversation,
    sender_type: str,
    msg_type: str,
    content: str,
    source: MessageSource | None = None,
    created_at: datetime | None = None,
) -> Message:
    if sender_type not in {SenderType.SELF, SenderType.CONTACT}:
        raise HTTPException(
            status_code=400, detail="sender_type 必须是 self 或 contact"
        )

    if source is None:
        source = MessageSource.IMPORT if created_at else MessageSource.LIVE

    message = Message(
        account_id=conversation.account_id,
        conversation_id=conversation.id,
        sender_type=sender_type,
        sender_contact_id=conversation.contact_id if sender_type == SenderType.CONTACT else None,
        msg_type=msg_type,
        content=content,
        source=source,
        created_at=created_at or utc_now(),
    )
    db.add(message)
    conversation.updated_at = utc_now()
    return message


def get_messages_after_id(
    db: Session, account_id: str, conversation_id: str, last_id: int
) -> list[Message]:
    return (
        db.query(Message)
        .filter(
            Message.account_id == account_id,
            Message.conversation_id == conversation_id,
            Message.id > last_id,
        )
        .order_by(Message.id.asc())
        .all()
    )


def build_messages_payload(
    db: Session, account_id: str, conversation_id: str, last_id: int
) -> dict[str, object]:
    conversation = get_conversation_or_404(
        db, account_id, conversation_id, include_deleted=True
    )
    messages = get_messages_after_id(db, account_id, conversation_id, last_id)
    return {"conversation": conversation, "messages": messages}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(login_in: LoginRequest, db: DbDep) -> LoginResponse:
    account = db.query(Account).filter(Account.username == login_in.username).first()
    if not account or account.is_deleted or account.status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(login_in.password, account.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = new_session_token()
    now = utc_now()
    auth_session = AuthSession(
        id=hash_token(token),
        account_id=account.id,
        expires_at=now + timedelta(hours=24),
        created_at=now,
        last_seen_at=now,
    )
    account.last_login_at = now
    account.updated_at = now
    db.add(auth_session)
    db.commit()
    db.refresh(account)
    return LoginResponse(token=token, account=AccountRead.model_validate(account))


@app.post("/api/auth/logout", response_model=StatusResponse)
def logout(auth_session: AuthSessionDep, db: DbDep) -> StatusResponse:
    db.delete(auth_session)
    db.commit()
    return StatusResponse(status=CommandStatus.SUCCESS)


@app.get("/api/auth/me", response_model=AccountRead)
def me(account: CurrentAccountDep) -> Account:
    return account


@app.get("/api/contacts", response_model=list[ContactRead])
def list_contacts(
    account: CurrentAccountDep,
    db: DbDep,
    include_deleted: Annotated[bool, Query()] = False,
) -> list[Contact]:
    query = db.query(Contact).filter(Contact.account_id == account.id)
    if not include_deleted:
        query = query.filter(Contact.is_deleted.is_(False))
    return query.order_by(Contact.updated_at.desc()).all()


@app.post("/api/contacts", response_model=ContactRead)
def create_contact(
    contact_in: ContactCreate, account: CurrentAccountDep, db: DbDep
) -> Contact:
    now = utc_now()
    contact = Contact(
        id=new_id("ct"),
        account_id=account.id,
        platform_contact_id=contact_in.platform_contact_id or new_id("chatid"),
        display_name=contact_in.display_name,
        avatar_url=contact_in.avatar_url,
        note=contact_in.note,
        is_deleted=False,
        deleted_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(contact)
    db.flush()
    get_or_create_direct_conversation(db, account.id, contact)
    db.commit()
    db.refresh(contact)
    return contact


@app.put("/api/contacts/{contact_id}", response_model=ContactRead)
def update_contact(
    contact_id: str,
    contact_update: ContactUpdate,
    account: CurrentAccountDep,
    db: DbDep,
) -> Contact:
    contact = get_contact_or_404(db, account.id, contact_id)
    if contact_update.display_name is not None:
        contact.display_name = contact_update.display_name
    if contact_update.avatar_url is not None:
        contact.avatar_url = contact_update.avatar_url
    if contact_update.note is not None:
        contact.note = contact_update.note
    contact.updated_at = utc_now()
    db.commit()
    db.refresh(contact)
    return contact


@app.delete("/api/contacts/{contact_id}", response_model=ContactRead)
def delete_contact(contact_id: str, account: CurrentAccountDep, db: DbDep) -> Contact:
    contact = get_contact_or_404(db, account.id, contact_id)
    now = utc_now()
    contact.is_deleted = True
    contact.deleted_at = now
    contact.updated_at = now
    db.query(Conversation).filter(
        Conversation.account_id == account.id, Conversation.contact_id == contact.id
    ).update({"is_deleted": True, "deleted_at": now, "updated_at": now})
    db.commit()
    db.refresh(contact)
    return contact


@app.get("/api/conversations", response_model=list[ConversationRead])
def list_conversations(
    account: CurrentAccountDep,
    db: DbDep,
    include_deleted: Annotated[bool, Query()] = False,
) -> list[Conversation]:
    query = (
        db.query(Conversation)
        .options(joinedload(Conversation.contact))
        .filter(Conversation.account_id == account.id)
    )
    if not include_deleted:
        query = query.filter(Conversation.is_deleted.is_(False))
    return query.order_by(Conversation.updated_at.desc()).all()


@app.post(
    "/api/conversations/{conversation_id}/messages", response_model=StatusResponse
)
def send_debug_message(
    conversation_id: str,
    msg_in: MessageCreate,
    account: CurrentAccountDep,
    db: DbDep,
) -> StatusResponse:
    conversation = get_conversation_or_404(db, account.id, conversation_id)

    if msg_in.msg_type != MessageType.TEXT:
        expected_prefix = f"media/{account.id}/"
        if not msg_in.content.startswith(expected_prefix):
            raise HTTPException(
                status_code=400,
                detail=f"媒体消息的 content 必须是以 {expected_prefix} 开头的 storage key",
            )

    message = add_message(
        db,
        conversation,
        msg_in.sender_type,
        msg_in.msg_type,
        msg_in.content,
        created_at=normalize_timestamp(msg_in.created_at) if msg_in.created_at else None,
    )
    db.commit()
    db.refresh(message)
    return StatusResponse(status=CommandStatus.SUCCESS, id=message.id)


@app.post(
    "/api/connector/conversations/{conversation_id}/messages",
    response_model=StatusResponse,
)
def connector_send_message(
    conversation_id: str,
    msg_in: MessageCreate,
    account: CurrentAccountDep,
    db: DbDep,
) -> StatusResponse:
    if msg_in.sender_type != SenderType.SELF:
        raise HTTPException(
            status_code=400, detail="Connector 只能以当前登录账号发送消息"
        )
    conversation = get_conversation_or_404(db, account.id, conversation_id)

    if msg_in.msg_type != MessageType.TEXT:
        expected_prefix = f"media/{account.id}/"
        if not msg_in.content.startswith(expected_prefix):
            raise HTTPException(
                status_code=400,
                detail=f"媒体消息的 content 必须是以 {expected_prefix} 开头的 storage key",
            )

    message = add_message(
        db,
        conversation,
        SenderType.SELF,
        msg_in.msg_type,
        msg_in.content,
        created_at=normalize_timestamp(msg_in.created_at) if msg_in.created_at else None,
    )
    db.commit()
    db.refresh(message)
    return StatusResponse(status=CommandStatus.SUCCESS, id=message.id)


@app.get(
    "/api/conversations/{conversation_id}/messages", response_model=ConversationMessages
)
async def get_conversation_messages(
    conversation_id: str,
    account: CurrentAccountDep,
    last_id: Annotated[int, Query(ge=0)] = 0,
    timeout: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    start_time = time.time()

    while True:
        db = SessionLocal()
        try:
            payload = build_messages_payload(db, account.id, conversation_id, last_id)
        finally:
            db.close()

        if payload["messages"]:
            return payload

        elapsed = time.time() - start_time
        if elapsed >= timeout:
            return payload

        await asyncio.sleep(min(0.2, timeout - elapsed))


@app.post("/api/uploads/presign", response_model=UploadPresignResponse)
def presign_upload(
    payload: UploadPresignRequest,
    account: CurrentAccountDep,
) -> UploadPresignResponse:
    storage_key = s3_generate_storage_key(account.id)
    upload_url = s3_presigned_put_url(storage_key, payload.mime_type)
    return UploadPresignResponse(storage_key=storage_key, upload_url=upload_url)


def _resolve_media_account(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
) -> Account:
    raw_token: str | None = None
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.removeprefix("Bearer ").strip()
    elif token:
        raw_token = token
    if not raw_token:
        raise HTTPException(status_code=401, detail="缺少登录令牌")
    auth_session = (
        db.query(AuthSession)
        .options(joinedload(AuthSession.account))
        .filter(AuthSession.id == hash_token(raw_token))
        .first()
    )
    if (
        not auth_session
        or not auth_session.account
        or auth_session.account.is_deleted
        or auth_session.account.status != AccountStatus.ACTIVE
    ):
        raise HTTPException(status_code=401, detail="登录已失效")
    if auth_session.expires_at is not None and auth_session.expires_at < utc_now():
        db.delete(auth_session)
        db.commit()
        raise HTTPException(status_code=401, detail="登录已超时")
    now = utc_now()
    auth_session.last_seen_at = now
    auth_session.expires_at = now + timedelta(hours=24)
    db.commit()
    return auth_session.account


MediaAccountDep = Annotated[Account, Depends(_resolve_media_account)]


@app.get("/api/media/{storage_key:path}")
def serve_media(
    storage_key: str,
    account: MediaAccountDep,
) -> RedirectResponse:
    expected_prefix = f"media/{account.id}/"
    if not storage_key.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="无权访问该文件")

    url = s3_presigned_get_url(storage_key)
    return RedirectResponse(url=url)