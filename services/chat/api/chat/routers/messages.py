import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from chat.config import LONG_POLL_INTERVAL_SECONDS
from chat.db import SessionLocal, utc_now
from chat.deps import CurrentAccountDep, DbDep, get_conversation_or_404
from chat.enums import CommandStatus, MessageType
from chat.models import Message
from chat.schemas import ConversationMessages, MessageSendRequest, StatusResponse
from chat.scoping import scoped


router = APIRouter(prefix="/api/conversations", tags=["messages"])


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@router.post("/{conversation_id}/messages", response_model=StatusResponse)
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
    `sender_id` 必须为 null（本人发出）或本会话对应的联系人 ID（对方发出），其他值会返回 400。
    """
    conversation = get_conversation_or_404(db, account, conversation_id)
    expected_prefix = f"media/{account.id}/"
    for msg in payload.messages:
        if msg.sender_id is not None and msg.sender_id != conversation.contact_id:
            raise HTTPException(
                status_code=400,
                detail="sender_id 必须为 null 或本会话对应的联系人 ID",
            )
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
            created_at=_normalize_timestamp(item.created_at) if item.created_at else utc_now(),
        )
        for item in payload.messages
    ]
    db.add_all(to_insert)
    conversation.updated_at = utc_now()
    db.commit()
    return StatusResponse(status=CommandStatus.SUCCESS, count=len(to_insert))


@router.get("/{conversation_id}/messages/before", response_model=ConversationMessages)
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
    conversation = get_conversation_or_404(db, account, conversation_id)
    q = scoped(db, account, Message).filter(Message.conversation_id == conversation_id)
    if before_id is not None:
        q = q.filter(Message.id < before_id)
    rows = q.order_by(Message.id.desc()).limit(limit).all()
    return {"conversation": conversation, "messages": list(reversed(rows))}


@router.get("/{conversation_id}/messages/after", response_model=ConversationMessages)
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
    - `timeout`：长轮询等待秒数。若当前无新消息，服务端会阻塞最多 timeout 秒后返回（期间每 0.5s 轮询一次数据库）。
      传 0 则立即返回（短轮询）。注意：此接口在线程池中同步运行，不会阻塞事件循环，每次轮询间隔会释放数据库连接。
    - 返回结果按 ID 升序排列（时间从旧到新）。
    """
    # Sync endpoint: FastAPI runs it in the threadpool, so the blocking DB
    # query and sleep below never stall the event loop. Each iteration uses a
    # short-lived session so the pooled connection is released during sleep.
    start_time = time.time()
    db = SessionLocal()
    try:
        conversation = get_conversation_or_404(db, account, conversation_id)
    finally:
        db.close()
    while True:
        db = SessionLocal()
        try:
            q = scoped(db, account, Message).filter(
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
        time.sleep(max(0.0, min(LONG_POLL_INTERVAL_SECONDS, timeout - (time.time() - start_time))))
