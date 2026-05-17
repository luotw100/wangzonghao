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
from chat.enums import AccountStatus, CommandStatus, MessageType
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
    AccountUpdate,
    ContactCreate,
    ContactRead,
    ContactUpdate,
    ConversationMessages,
    ConversationRead,
    LoginRequest,
    LoginResponse,
    MessageSend,
    MessageSendRequest,
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
        or auth_session.account.status != AccountStatus.ACTIVE
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效"
        )
    if auth_session.expires_at < utc_now():
        db.delete(auth_session)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已超时"
        )
    auth_session.expires_at = utc_now() + timedelta(hours=24)
    db.commit()
    return auth_session


AuthSessionDep = Annotated[AuthSession, Depends(get_auth_session)]


def current_account(auth_session: AuthSessionDep) -> Account:
    return auth_session.account


CurrentAccountDep = Annotated[Account, Depends(current_account)]


def get_contact_or_404(db: Session, account_id: str, contact_id: str) -> Contact:
    contact = db.query(Contact).filter(
        Contact.account_id == account_id, Contact.id == contact_id
    ).first()
    if not contact:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return contact


def get_conversation_or_404(
    db: Session,
    account_id: str,
    conversation_id: str,
) -> Conversation:
    conversation = (
        db.query(Conversation)
        .options(joinedload(Conversation.contact))
        .filter(
            Conversation.account_id == account_id, Conversation.id == conversation_id
        )
        .first()
    )
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
        if title:
            conversation.title = title
        conversation.updated_at = utc_now()
        return conversation

    now = utc_now()
    conversation = Conversation(
        id=new_id("c"),
        account_id=account_id,
        contact_id=contact.id,
        title=title or contact.nickname,
        created_at=now,
        updated_at=now,
    )
    db.add(conversation)
    return conversation


def add_message(
    db: Session,
    conversation: Conversation,
    sender_id: str | None,
    msg_type: str,
    content: str,
    created_at: datetime | None = None,
) -> Message:
    message = Message(
        account_id=conversation.account_id,
        conversation_id=conversation.id,
        sender_id=sender_id,
        msg_type=msg_type,
        content=content,
        created_at=created_at or utc_now(),
    )
    db.add(message)
    conversation.updated_at = utc_now()
    return message


def get_messages_after_id(
    db: Session, account_id: str, conversation_id: str, last_id: int, limit: int = 0
) -> list[Message]:
    q = db.query(Message).filter(
        Message.account_id == account_id,
        Message.conversation_id == conversation_id,
        Message.id > last_id,
    )
    if limit > 0 and last_id == 0:
        rows = q.order_by(Message.id.desc()).limit(limit).all()
        return list(reversed(rows))
    return q.order_by(Message.id.asc()).all()


def get_messages_before_id(
    db: Session, account_id: str, conversation_id: str, before_id: int, limit: int
) -> list[Message]:
    rows = (
        db.query(Message)
        .filter(
            Message.account_id == account_id,
            Message.conversation_id == conversation_id,
            Message.id < before_id,
        )
        .order_by(Message.id.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


def build_messages_payload(
    db: Session, account_id: str, conversation_id: str, last_id: int, limit: int = 0
) -> dict[str, object]:
    conversation = get_conversation_or_404(db, account_id, conversation_id)
    messages = get_messages_after_id(db, account_id, conversation_id, last_id, limit)
    return {"conversation": conversation, "messages": messages}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(login_in: LoginRequest, db: DbDep) -> LoginResponse:
    account = db.query(Account).filter(Account.username == login_in.username).first()
    if not account or account.status != AccountStatus.ACTIVE:
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
    )
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


@app.patch("/api/auth/me", response_model=AccountRead)
def update_me(update: AccountUpdate, account: CurrentAccountDep, db: DbDep) -> Account:
    account.nickname = update.nickname
    account.updated_at = utc_now()
    db.commit()
    db.refresh(account)
    return account


@app.get("/api/contacts", response_model=list[ContactRead])
def list_contacts(account: CurrentAccountDep, db: DbDep) -> list[Contact]:
    return (
        db.query(Contact)
        .filter(Contact.account_id == account.id)
        .order_by(Contact.updated_at.desc())
        .all()
    )


@app.post("/api/contacts", response_model=ContactRead)
def create_contact(
    contact_in: ContactCreate, account: CurrentAccountDep, db: DbDep
) -> Contact:
    now = utc_now()
    contact = Contact(
        id=new_id("ct"),
        account_id=account.id,
        username=contact_in.username or new_id("chatid"),
        nickname=contact_in.nickname,
        remark_name=contact_in.remark_name,
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
    if contact_update.remark_name is not None:
        contact.remark_name = contact_update.remark_name
    contact.updated_at = utc_now()
    db.commit()
    db.refresh(contact)
    return contact


@app.get("/api/conversations", response_model=list[ConversationRead])
def list_conversations(account: CurrentAccountDep, db: DbDep) -> list[Conversation]:
    return (
        db.query(Conversation)
        .options(joinedload(Conversation.contact))
        .filter(Conversation.account_id == account.id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )


@app.post(
    "/api/conversations/{conversation_id}/messages", response_model=StatusResponse
)
def send_messages(
    conversation_id: str,
    payload: MessageSendRequest,
    account: CurrentAccountDep,
    db: DbDep,
) -> StatusResponse:
    conversation = get_conversation_or_404(db, account.id, conversation_id)
    expected_prefix = f"media/{account.id}/"
    for msg in payload.messages:
        if msg.msg_type != MessageType.TEXT and not msg.content.startswith(expected_prefix):
            raise HTTPException(
                status_code=400,
                detail=f"媒体消息的 content 必须是以 {expected_prefix} 开头的 storage key",
            )

    if len(payload.messages) == 1:
        msg = payload.messages[0]
        message = add_message(
            db,
            conversation,
            msg.sender_id,
            msg.msg_type,
            msg.content,
            created_at=normalize_timestamp(msg.created_at) if msg.created_at else None,
        )
        db.commit()
        db.refresh(message)
        return StatusResponse(status=CommandStatus.SUCCESS, id=message.id)

    to_insert = [
        Message(
            account_id=account.id,
            conversation_id=conversation.id,
            sender_id=item.sender_id,
            msg_type=item.msg_type,
            content=item.content,
            created_at=normalize_timestamp(item.created_at) if item.created_at else utc_now(),
        )
        for item in payload.messages
    ]
    db.add_all(to_insert)
    conversation.updated_at = utc_now()
    db.commit()
    return StatusResponse(status=CommandStatus.SUCCESS, count=len(to_insert))


@app.get(
    "/api/conversations/{conversation_id}/messages", response_model=ConversationMessages
)
async def get_conversation_messages(
    conversation_id: str,
    account: CurrentAccountDep,
    last_id: Annotated[int, Query(ge=0)] = 0,
    timeout: Annotated[int, Query(ge=0)] = 0,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=0, le=500)] = 0,
) -> dict[str, object]:
    # Paginated fetch (before_id) or initial bounded load: always immediate, no polling.
    if before_id is not None or (limit > 0 and last_id == 0 and timeout == 0):
        db = SessionLocal()
        try:
            conversation = get_conversation_or_404(db, account.id, conversation_id)
            if before_id is not None:
                messages = get_messages_before_id(
                    db, account.id, conversation_id, before_id, limit or 100
                )
            else:
                messages = get_messages_after_id(
                    db, account.id, conversation_id, 0, limit
                )
            return {"conversation": conversation, "messages": messages}
        finally:
            db.close()

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
        or auth_session.account.status != AccountStatus.ACTIVE
    ):
        raise HTTPException(status_code=401, detail="登录已失效")
    if auth_session.expires_at < utc_now():
        db.delete(auth_session)
        db.commit()
        raise HTTPException(status_code=401, detail="登录已超时")
    now = utc_now()
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
