"""Conversation endpoints (web UI)."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from studio.db import get_db, utc_now
from studio.notify import outbound_channel
from studio.deps import (
    CurrentAccountDep,
    get_account_conversation,
    get_account_inbox,
    get_account_persona,
)
from studio.enums import OutboundStatus
from studio.models import (
    Conversation,
    ConversationMember,
    Inbox,
    Message,
    OutboundMessage,
)
from studio.schemas import (
    ConversationListItem,
    ConversationRead,
    ConversationUpdate,
    MessageRead,
    OutboundCreate,
    OutboundRead,
)

router = APIRouter()


@router.get("/api/conversations/{conversation_id}", response_model=ConversationRead)
def get_conversation(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    account: CurrentAccountDep,
):
    """获取单个会话详情（含 card_md 与 members）。"""
    return get_account_conversation(db, account, conversation_id)


@router.get("/api/conversations", response_model=list[ConversationListItem])
def list_conversations(
    db: Annotated[Session, Depends(get_db)],
    account: CurrentAccountDep,
    inbox_id: Optional[str] = Query(None, description="只返回指定 Inbox 下的会话"),
):
    """会话列表，按最新消息时间降序。"""
    latest_ts_subq = (
        db.query(
            Message.conversation_id.label("cid"),
            func.max(Message.timestamp).label("max_ts"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )
    count_subq = (
        db.query(
            Message.conversation_id.label("cid"),
            func.count(Message.id).label("cnt"),
        )
        .group_by(Message.conversation_id)
        .subquery()
    )
    member_count_subq = (
        db.query(
            ConversationMember.conversation_id.label("cid"),
            func.count(ConversationMember.peer_platform_id).label("mcnt"),
        )
        .group_by(ConversationMember.conversation_id)
        .subquery()
    )

    q = (
        db.query(
            Conversation,
            Inbox,
            func.coalesce(count_subq.c.cnt, 0).label("cnt"),
            latest_ts_subq.c.max_ts,
            func.coalesce(member_count_subq.c.mcnt, 0).label("mcnt"),
        )
        .join(Inbox, Inbox.id == Conversation.inbox_id)
        .outerjoin(count_subq, count_subq.c.cid == Conversation.id)
        .outerjoin(latest_ts_subq, latest_ts_subq.c.cid == Conversation.id)
        .outerjoin(member_count_subq, member_count_subq.c.cid == Conversation.id)
        .filter(Inbox.account_id == account.id)
    )
    if inbox_id is not None:
        get_account_inbox(db, account, inbox_id)
        q = q.filter(Conversation.inbox_id == inbox_id)

    rows = q.order_by(
        func.coalesce(latest_ts_subq.c.max_ts, Conversation.updated_at).desc(),
        Conversation.id.desc(),
    ).all()

    conv_ids = [c.id for c, _, _, _, _ in rows]
    latest_by_conv: dict[str, Message] = {}
    if conv_ids:
        latest_msgs = (
            db.query(Message)
            .distinct(Message.conversation_id)
            .filter(Message.conversation_id.in_(conv_ids))
            .order_by(
                Message.conversation_id,
                Message.timestamp.desc(),
                Message.id.desc(),
            )
            .all()
        )
        latest_by_conv = {m.conversation_id: m for m in latest_msgs}

    return [
        {
            "conversation": conv,
            "inbox": inbox,
            "latest_message": latest_by_conv.get(conv.id),
            "message_count": int(cnt),
            "member_count": int(mcnt),
        }
        for conv, inbox, cnt, _, mcnt in rows
    ]


@router.get(
    "/api/conversations/{conversation_id}/messages",
    response_model=list[MessageRead],
)
def list_conversation_messages(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    account: CurrentAccountDep,
    limit: int = Query(200, ge=1, le=500),
):
    """获取指定会话的历史消息，时间升序（最新的在最后）。"""
    conv = get_account_conversation(db, account, conversation_id)
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    return rows


@router.patch("/api/conversations/{conversation_id}", response_model=ConversationRead)
def update_conversation(
    conversation_id: str,
    payload: ConversationUpdate,
    db: Annotated[Session, Depends(get_db)],
    account: CurrentAccountDep,
):
    """更新会话配置。persona_id 显式传 null 即清空。"""
    c = get_account_conversation(db, account, conversation_id)
    fields = payload.model_fields_set
    if "display_name" in fields and payload.display_name is not None:
        c.display_name = payload.display_name
    if "card_md" in fields and payload.card_md is not None:
        c.card_md = payload.card_md
    if "persona_id" in fields:
        if payload.persona_id is not None:
            get_account_persona(db, account, payload.persona_id)
        c.persona_id = payload.persona_id
    if "takeover" in fields and payload.takeover is not None:
        c.takeover = payload.takeover
    if "reply_policy" in fields and payload.reply_policy is not None:
        c.reply_policy = payload.reply_policy
    if "status" in fields and payload.status is not None:
        c.status = payload.status
    c.updated_at = utc_now()
    db.commit()
    db.refresh(c)
    return c


@router.post(
    "/api/conversations/{conversation_id}/outbound",
    response_model=OutboundRead,
    status_code=201,
)
def seed_outbound(
    conversation_id: str,
    payload: OutboundCreate,
    db: Annotated[Session, Depends(get_db)],
    account: CurrentAccountDep,
):
    """手动向指定会话发送一条消息（调试 / 预设回复用）。"""
    conv = get_account_conversation(db, account, conversation_id)
    now_ts = utc_now()
    o = OutboundMessage(
        inbox_id=conv.inbox_id,
        conversation_id=conv.id,
        msg_type=payload.msg_type,
        content=payload.content,
        send_after=now_ts,
        status=OutboundStatus.PENDING,
        delivered_at=None,
        failed_reason="",
        created_at=now_ts,
    )
    db.add(o)
    db.execute(
        text("SELECT pg_notify(:ch, '')").bindparams(ch=outbound_channel(conv.inbox_id))
    )
    db.commit()
    db.refresh(o)
    return o
