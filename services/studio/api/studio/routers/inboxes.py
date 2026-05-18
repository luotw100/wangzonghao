"""Inbox endpoints (no manual creation — inboxes are auto-provisioned via bridge handshake)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from studio.db import get_db, utc_now
from studio.deps import (
    CurrentAccountDep,
    get_account_bridge,
    get_account_contact,
    get_account_inbox,
    get_account_persona,
    new_id,
)
from studio.enums import OutboundStatus
from studio.models import Contact, Inbox, OutboundMessage
from studio.schemas import InboxUpdate, OutboundCreate
from studio.serializers import s_contact, s_inbox, s_outbound

router = APIRouter()


@router.get("/api/inboxes")
def list_inboxes(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取当前账号的 Inbox 列表，按创建时间降序排列。

    Inbox 代表一个平台账号身份（如一个微信号），由 Bridge 握手时自动创建，不支持手动创建。
    """
    query = db.query(Inbox).filter(Inbox.account_id == account.id)
    items = query.order_by(Inbox.created_at.desc()).all()
    return [s_inbox(i) for i in items]


@router.get("/api/inboxes/{inbox_id}")
def get_inbox(inbox_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取单个 Inbox 详情。"""
    return s_inbox(get_account_inbox(db, account, inbox_id))


@router.put("/api/inboxes/{inbox_id}")
def update_inbox(inbox_id: str, payload: InboxUpdate, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """更新 Inbox 配置。只传需要修改的字段。

    - `clear_bridge=true`：解除与当前 Bridge 的绑定，Inbox 进入未绑定状态，不再收发消息。
    - `enabled=false`：关闭自动回复，消息仍正常存储但不触发 AI 回复。
    """
    inbox = get_account_inbox(db, account, inbox_id)
    fields = payload.model_fields_set
    if "display_name" in fields and payload.display_name is not None:
        inbox.display_name = payload.display_name
    if "default_persona_id" in fields and payload.default_persona_id is not None:
        get_account_persona(db, account, payload.default_persona_id)
        inbox.default_persona_id = payload.default_persona_id
    if "bridge_id" in fields and payload.bridge_id is not None:
        get_account_bridge(db, account, payload.bridge_id)
        inbox.bridge_id = payload.bridge_id
    if payload.clear_bridge:
        inbox.bridge_id = None
    if "enabled" in fields and payload.enabled is not None:
        inbox.enabled = payload.enabled
    inbox.updated_at = utc_now()
    db.commit(); db.refresh(inbox)
    return s_inbox(inbox)


@router.delete("/api/inboxes/{inbox_id}")
def delete_inbox(inbox_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """删除 Inbox。删除前会自动将该 Inbox 下所有待发消息（status=pending）标记为 canceled。"""
    inbox = get_account_inbox(db, account, inbox_id)
    db.query(OutboundMessage).filter(
        OutboundMessage.inbox_id == inbox.id, OutboundMessage.status == OutboundStatus.PENDING
    ).update({OutboundMessage.status: OutboundStatus.CANCELED}, synchronize_session=False)
    db.delete(inbox); db.commit()
    return {"status": "deleted", "id": inbox_id}


@router.get("/api/inboxes/{inbox_id}/contacts")
def list_inbox_contacts(inbox_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取指定 Inbox 下所有联系人，按最后更新时间降序排列。"""
    inbox = get_account_inbox(db, account, inbox_id)
    items = (
        db.query(Contact).filter(Contact.inbox_id == inbox.id)
        .order_by(Contact.updated_at.desc()).all()
    )
    return [s_contact(c) for c in items]


@router.post("/api/inboxes/{inbox_id}/outbound")
def seed_outbound(inbox_id: str, payload: OutboundCreate, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """手动向指定联系人发送一条消息（调试 / 预设回复用）。

    将消息写入 outbound 队列，Bridge 会在下次轮询时取走并实际发送到平台。
    contact_id 必须属于当前 Inbox，否则返回 400。
    """
    inbox = get_account_inbox(db, account, inbox_id)
    contact = get_account_contact(db, account, payload.contact_id)
    if contact.inbox_id != inbox.id:
        raise HTTPException(status_code=400, detail="Contact 不属于该 inbox")
    now_ts = utc_now()
    o = OutboundMessage(
        inbox_id=inbox.id, contact_id=contact.id,
        msg_type=payload.msg_type,
        content=payload.content,
        send_after=now_ts,
        status=OutboundStatus.PENDING, delivered_at=None, failed_reason=None, created_at=now_ts,
    )
    db.add(o); db.commit(); db.refresh(o)
    return s_outbound(o, peer_platform_id=contact.peer_platform_id)
