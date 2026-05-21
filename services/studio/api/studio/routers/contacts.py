"""Contact and conversation endpoints."""

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from studio.db import get_db, utc_now
from studio.deps import (
    CurrentAccountDep,
    get_account_contact,
    get_account_inbox,
    get_account_persona,
)
from studio.enums import OutboundStatus
from studio.models import Contact, Inbox, Message, OutboundMessage
from studio.schemas import (
    ContactRead,
    ContactUpdate,
    ConversationItem,
    MessageRead,
    OutboundCreate,
    OutboundRead,
)

router = APIRouter()


@router.get("/api/contacts/{contact_id}", response_model=ContactRead)
def get_contact(contact_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取单个联系人详情（含 card_md）。"""
    return get_account_contact(db, account, contact_id)


@router.get("/api/conversations", response_model=list[ConversationItem])
def list_conversations(
    db: Annotated[Session, Depends(get_db)],
    account: CurrentAccountDep,
    inbox_id: Optional[str] = Query(None, description="只返回指定 Inbox 下的对话"),
):
    """获取对话列表（瘦版 contact，无 card_md），按最新消息时间降序。"""
    latest_ts_subq = (
        db.query(
            Message.contact_id.label("cid"),
            func.max(Message.timestamp).label("max_ts"),
        )
        .group_by(Message.contact_id)
        .subquery()
    )
    count_subq = (
        db.query(
            Message.contact_id.label("cid"),
            func.count(Message.id).label("cnt"),
        )
        .group_by(Message.contact_id)
        .subquery()
    )

    q = (
        db.query(
            Contact,
            Inbox,
            func.coalesce(count_subq.c.cnt, 0).label("cnt"),
            latest_ts_subq.c.max_ts,
        )
        .join(Inbox, Inbox.id == Contact.inbox_id)
        .outerjoin(count_subq, count_subq.c.cid == Contact.id)
        .outerjoin(latest_ts_subq, latest_ts_subq.c.cid == Contact.id)
        .filter(Inbox.account_id == account.id)
    )
    if inbox_id is not None:
        get_account_inbox(db, account, inbox_id)  # 404 if not owned
        q = q.filter(Contact.inbox_id == inbox_id)

    rows = q.order_by(
        func.coalesce(latest_ts_subq.c.max_ts, Contact.updated_at).desc(),
        Contact.id.desc(),
    ).all()

    contact_ids = [c.id for c, _, _, _ in rows]
    latest_by_contact: dict[str, Message] = {}
    if contact_ids:
        latest_msgs = (
            db.query(Message)
            .distinct(Message.contact_id)
            .filter(Message.contact_id.in_(contact_ids))
            .order_by(
                Message.contact_id,
                Message.timestamp.desc(),
                Message.id.desc(),
            )
            .all()
        )
        latest_by_contact = {m.contact_id: m for m in latest_msgs}

    return [
        {
            "contact": contact,
            "inbox": inbox,
            "latest_message": latest_by_contact.get(contact.id),
            "message_count": int(cnt),
        }
        for contact, inbox, cnt, _ in rows
    ]


@router.get("/api/contacts/{contact_id}/messages", response_model=list[MessageRead])
def list_contact_messages(
    contact_id: str,
    db: Annotated[Session, Depends(get_db)],
    account: CurrentAccountDep,
    limit: int = Query(200, ge=1, le=500),
):
    """获取指定联系人的历史消息，按时间升序返回（最新的在最后）。

    - `limit`：最多返回条数，默认 200，最大 500。
    - 当前为简单截取最近 N 条，无游标分页；如需加载更早的消息，请联系开发增加游标支持。
    """
    contact = get_account_contact(db, account, contact_id)
    rows = (
        db.query(Message)
        .filter(Message.contact_id == contact.id)
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    return rows


@router.patch("/api/contacts/{contact_id}", response_model=ContactRead)
def update_contact(contact_id: str, payload: ContactUpdate, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """更新联系人配置。只传需要修改的字段；persona_id 显式传 null 即清空。Provider 由后台 CLI 维护。"""
    c = get_account_contact(db, account, contact_id)
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
    db.commit(); db.refresh(c)
    return c


@router.post("/api/contacts/{contact_id}/outbound", response_model=OutboundRead, status_code=201)
def seed_outbound(
    contact_id: str,
    payload: OutboundCreate,
    db: Annotated[Session, Depends(get_db)],
    account: CurrentAccountDep,
):
    """手动向指定联系人发送一条消息（调试 / 预设回复用）。inbox 由 contact 推导。"""
    contact = get_account_contact(db, account, contact_id)
    now_ts = utc_now()
    o = OutboundMessage(
        inbox_id=contact.inbox_id, contact_id=contact.id,
        msg_type=payload.msg_type,
        content=payload.content,
        send_after=now_ts,
        status=OutboundStatus.PENDING,
        delivered_at=None, failed_reason="", created_at=now_ts,
    )
    db.add(o); db.commit(); db.refresh(o)
    # peer_platform_id 不在 OutboundMessage 表里，路由层注入
    o.peer_platform_id = contact.peer_platform_id  # type: ignore[attr-defined]
    return o
