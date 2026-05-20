"""Contact and conversation endpoints."""

from typing import Annotated, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from studio.db import get_db, utc_now
from studio.deps import CurrentAccountDep, get_account_contact, get_account_persona
from studio.models import Contact, Inbox, Message, ProviderConfig
from studio.schemas import ContactUpdate
from studio.serializers import s_contact, s_inbox, s_message

router = APIRouter()


@router.get("/api/contacts/{contact_id}")
def get_contact(contact_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取单个联系人详情。"""
    return s_contact(get_account_contact(db, account, contact_id))


@router.get("/api/conversations")
def list_conversations(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取所有对话列表，按最新消息时间降序排列（无消息的按联系人更新时间排）。

    每条记录包含：联系人信息、所属 Inbox 信息、最新一条消息、消息总数。
    只返回当前账号下 Inbox 的对话。
    """
    query = (
        db.query(Contact, Inbox)
        .join(Inbox, Inbox.id == Contact.inbox_id)
        .filter(Inbox.account_id == account.id)
    )
    rows = query.all()
    out: List[Dict] = []
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


@router.get("/api/contacts/{contact_id}/messages")
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
    return [s_message(m) for m in rows]


@router.put("/api/contacts/{contact_id}")
def update_contact(contact_id: str, payload: ContactUpdate, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """更新联系人配置。只传需要修改的字段。

    - `takeover=true`：启用 AI 接管，Bridge 会将该联系人加入 active-peers 列表，允许 AI 代发消息。
    - `reply_policy=autoreply`：收到对方消息后自动触发 AI 生成回复（前提是 Inbox.enabled=true 且联系人 status=active）。
    """
    c = get_account_contact(db, account, contact_id)
    fields = payload.model_fields_set
    if "display_name" in fields and payload.display_name is not None: c.display_name = payload.display_name
    if "card_md" in fields and payload.card_md is not None: c.card_md = payload.card_md
    if "persona_id" in fields and payload.persona_id is not None:
        get_account_persona(db, account, payload.persona_id)
        c.persona_id = payload.persona_id
    if "provider_id" in fields and payload.provider_id is not None:
        pc = db.query(ProviderConfig).filter(ProviderConfig.id == payload.provider_id).first()
        if not pc:
            raise HTTPException(status_code=404, detail="Provider 不存在")
        c.provider_id = payload.provider_id
    if "takeover" in fields and payload.takeover is not None:
        c.takeover = payload.takeover
    if "reply_policy" in fields and payload.reply_policy is not None:
        c.reply_policy = payload.reply_policy
    if "status" in fields and payload.status is not None: c.status = payload.status
    c.updated_at = utc_now()
    db.commit(); db.refresh(c)
    return s_contact(c)
