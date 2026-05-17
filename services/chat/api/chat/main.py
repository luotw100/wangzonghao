import time
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from chat.auth_utils import hash_token, new_session_token, verify_password
from chat.db import SessionLocal, get_db, utc_now
from chat.enums import AccountStatus, CommandStatus, MessageType
from chat.ids import new_id
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
    s3_presigned_post,
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


# Browser-renderable active content uploaded to the media bucket and served
# back inline is a stored-XSS vector, so it is rejected at presign time.
DISALLOWED_UPLOAD_MIME_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    _get_upload_max_size()
    yield


app = FastAPI(
    title="Laborster Chat",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

DbDep = Annotated[Session, Depends(get_db)]


def normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def resolve_auth_session(db: Session, raw_token: str | None) -> AuthSession:
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少登录令牌"
        )
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


def _bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip()
    return None


def get_auth_session(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthSession:
    return resolve_auth_session(db, _bearer_token(authorization))


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



@app.get("/api/health")
def health() -> dict[str, str]:
    """健康检查。返回 `{"status": "ok"}`，可用于负载均衡探活。"""
    return {"status": "ok"}


@app.post("/api/auth/login", response_model=LoginResponse)
def login(login_in: LoginRequest, db: DbDep) -> LoginResponse:
    """登录。

    验证用户名和密码，成功后创建一个有效期 24 小时的 session，并返回 Bearer token。
    后续所有需要鉴权的接口都需要在请求头携带 `Authorization: Bearer <token>`。
    每次成功鉴权会自动将有效期续期 24 小时。
    账号被禁用（status=disabled）时即使密码正确也会拒绝登录。
    """
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
    """退出登录。

    删除当前请求所使用的 session token，使其立即失效。
    其他设备上的 session 不受影响。
    """
    db.delete(auth_session)
    db.commit()
    return StatusResponse(status=CommandStatus.SUCCESS)


@app.get("/api/auth/me", response_model=AccountRead)
def me(account: CurrentAccountDep) -> Account:
    """获取当前登录账号的详细信息。"""
    return account


@app.patch("/api/auth/me", response_model=AccountRead)
def update_me(update: AccountUpdate, account: CurrentAccountDep, db: DbDep) -> Account:
    """修改当前账号资料（目前仅支持改昵称）。"""
    account.nickname = update.nickname
    account.updated_at = utc_now()
    db.commit()
    db.refresh(account)
    return account


@app.get("/api/contacts", response_model=list[ContactRead])
def list_contacts(account: CurrentAccountDep, db: DbDep) -> list[Contact]:
    """获取当前账号的所有联系人，按最后更新时间降序排列。"""
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
    """创建联系人。

    创建成功后，系统会自动为该联系人创建一个一对一会话（同一账号下一个联系人只有一个会话）。
    同一账号下 username 不可重复，重复提交会返回 409。
    若不传 username，系统自动生成一个唯一 ID 作为其外部标识。
    """
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
    try:
        db.flush()
        get_or_create_direct_conversation(db, account.id, contact)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该联系人已存在")
    db.refresh(contact)
    return contact


@app.put("/api/contacts/{contact_id}", response_model=ContactRead)
def update_contact(
    contact_id: str,
    contact_update: ContactUpdate,
    account: CurrentAccountDep,
    db: DbDep,
) -> Contact:
    """更新联系人（目前仅支持修改备注名）。传 null 可清除备注。"""
    contact = get_contact_or_404(db, account.id, contact_id)
    if contact_update.remark_name is not None:
        contact.remark_name = contact_update.remark_name
    contact.updated_at = utc_now()
    db.commit()
    db.refresh(contact)
    return contact


@app.get("/api/conversations", response_model=list[ConversationRead])
def list_conversations(account: CurrentAccountDep, db: DbDep) -> list[Conversation]:
    """获取当前账号的所有一对一会话，按最后活跃时间降序排列（最新有消息的在前）。每条会话内嵌了联系人详情。"""
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
    """向指定会话批量写入消息。

    支持一次提交多条，按数组顺序依次写入，返回实际写入的条数（`count` 字段）。
    媒体消息（image/audio/video/file）的 content 必须是以 `media/{account_id}/` 开头的 storage key，
    需先通过 POST /api/uploads/presign 完成上传后再填入，否则会返回 400。
    可以通过 sender_id 指定发送方，null 表示本人发出，联系人 ID 表示对方发出，用于导入历史记录。
    """
    conversation = get_conversation_or_404(db, account.id, conversation_id)
    expected_prefix = f"media/{account.id}/"
    for msg in payload.messages:
        if msg.msg_type != MessageType.TEXT and not msg.content.startswith(expected_prefix):
            raise HTTPException(
                status_code=400,
                detail=f"媒体消息的 content 必须是以 {expected_prefix} 开头的 storage key",
            )

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
    "/api/conversations/{conversation_id}/messages/before",
    response_model=ConversationMessages,
)
def get_messages_before(
    conversation_id: str,
    account: CurrentAccountDep,
    db: DbDep,
    before_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, object]:
    """向前翻页获取历史消息。

    - `before_id`：只返回 ID 严格小于此值的消息，用于向上翻页加载更早的内容。不传则从最新一条开始。
    - `limit`：最多返回条数，默认 100，最大 500。
    - 返回结果按 ID 升序排列（时间从旧到新），方便直接渲染到聊天界面。
    """
    conversation = get_conversation_or_404(db, account.id, conversation_id)
    q = db.query(Message).filter(
        Message.account_id == account.id,
        Message.conversation_id == conversation_id,
    )
    if before_id is not None:
        q = q.filter(Message.id < before_id)
    rows = q.order_by(Message.id.desc()).limit(limit).all()
    return {"conversation": conversation, "messages": list(reversed(rows))}


@app.get(
    "/api/conversations/{conversation_id}/messages/after",
    response_model=ConversationMessages,
)
def get_messages_after(
    conversation_id: str,
    account: CurrentAccountDep,
    last_id: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=0, le=500)] = 0,
    timeout: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    """拉取新消息（支持长轮询）。

    - `last_id`：只返回 ID 严格大于此值的消息，客户端应把上次收到的最大消息 ID 传进来。首次拉取传 0。
    - `limit`：最多返回条数，0 表示不限制（返回全部）。
    - `timeout`：长轮询等待秒数。若当前无新消息，服务端会阻塞最多 timeout 秒后返回（期间每 200ms 轮询一次数据库）。
      传 0 则立即返回（短轮询）。注意：此接口在线程池中同步运行，不会阻塞事件循环，每次轮询间隔会释放数据库连接。
    - 返回结果按 ID 升序排列（时间从旧到新）。
    """
    # Sync endpoint: FastAPI runs it in the threadpool, so the blocking DB
    # query and sleep below never stall the event loop. Each iteration uses a
    # short-lived session so the pooled connection is released during sleep.
    start_time = time.time()
    db = SessionLocal()
    try:
        conversation = get_conversation_or_404(db, account.id, conversation_id)
    finally:
        db.close()
    while True:
        db = SessionLocal()
        try:
            q = db.query(Message).filter(
                Message.account_id == account.id,
                Message.conversation_id == conversation_id,
                Message.id > last_id,
            ).order_by(Message.id.asc())
            if limit > 0:
                q = q.limit(limit)
            messages = q.all()
        finally:
            db.close()
        if messages or (time.time() - start_time) >= timeout:
            return {"conversation": conversation, "messages": messages}
        time.sleep(max(0.0, min(0.2, timeout - (time.time() - start_time))))


@app.post("/api/uploads/presign", response_model=UploadPresignResponse)
def presign_upload(
    payload: UploadPresignRequest,
    account: CurrentAccountDep,
) -> UploadPresignResponse:
    """申请媒体文件上传的预签名信息。

    返回 `upload_url`（S3 地址）和 `fields`（签名表单字段）。
    客户端用 multipart/form-data 把 fields 里的所有键值对加上文件二进制（key='file'）一起 POST 到 upload_url，
    S3 返回 204 表示上传成功。
    上传完成后，将返回的 `storage_key` 填入消息的 content 字段发送即可。

    注意：text/html、application/xhtml+xml、image/svg+xml 等 MIME 类型会被拒绝（防止存储型 XSS）。
    """
    if payload.mime_type.split(";")[0].strip().lower() in DISALLOWED_UPLOAD_MIME_TYPES:
        raise HTTPException(status_code=400, detail="不支持的文件类型")
    storage_key = s3_generate_storage_key(account.id)
    post = s3_presigned_post(storage_key, payload.mime_type, _get_upload_max_size())
    return UploadPresignResponse(
        storage_key=storage_key,
        upload_url=post["url"],
        fields=post["fields"],
    )


def _resolve_media_account(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
) -> Account:
    raw_token = _bearer_token(authorization) or token
    return resolve_auth_session(db, raw_token).account


MediaAccountDep = Annotated[Account, Depends(_resolve_media_account)]


@app.get("/api/media/{storage_key:path}")
def serve_media(
    storage_key: str,
    account: MediaAccountDep,
    db: DbDep,
) -> RedirectResponse:
    """获取媒体文件访问链接（302 重定向到 S3 预签名 URL）。

    只允许访问属于当前账号的文件（storage key 必须以 `media/{account_id}/` 开头），否则返回 403。
    鉴权支持两种方式：Header `Authorization: Bearer <token>` 或 Query 参数 `?token=<token>`，
    后者方便在 `<img>`/`<video>` 等标签的 src 属性中直接使用。

    根据消息类型自动决定 Content-Disposition：
    - image/audio/video 类型设为 inline（浏览器直接预览）；
    - file 类型或尚未关联到任何消息的文件设为 attachment（强制下载）。
    """
    expected_prefix = f"media/{account.id}/"
    if not storage_key.startswith(expected_prefix):
        raise HTTPException(status_code=403, detail="无权访问该文件")

    msg_type = (
        db.query(Message.msg_type)
        .filter(Message.account_id == account.id, Message.content == storage_key)
        .limit(1)
        .scalar()
    )
    # Only image/audio/video are rendered inline; anything else (including a
    # blob not yet attached to a message) is served as an attachment.
    inline_types = {MessageType.IMAGE, MessageType.AUDIO, MessageType.VIDEO}
    force_attachment = msg_type not in inline_types
    url = s3_presigned_get_url(storage_key, force_attachment=force_attachment)
    return RedirectResponse(url=url)
