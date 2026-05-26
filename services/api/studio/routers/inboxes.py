"""Inbox endpoints (no manual creation — inboxes are auto-provisioned via bridge handshake)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from studio.db import get_db, utc_now
from studio.deps import (
    CurrentAccountDep,
    get_account_bridge,
    get_account_inbox,
)
from studio.enums import OutboundStatus
from studio.models import Inbox, OutboundMessage
from studio.schemas import InboxRead, InboxUpdate

router = APIRouter()


@router.get("/api/inboxes", response_model=list[InboxRead])
def list_inboxes(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取当前账号的 Inbox 列表，按创建时间降序排列。"""
    return (
        db.query(Inbox)
        .filter(Inbox.account_id == account.id)
        .order_by(Inbox.created_at.desc())
        .all()
    )


@router.get("/api/inboxes/{inbox_id}", response_model=InboxRead)
def get_inbox(inbox_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取单个 Inbox 详情。"""
    return get_account_inbox(db, account, inbox_id)


@router.patch("/api/inboxes/{inbox_id}", response_model=InboxRead)
def update_inbox(inbox_id: str, payload: InboxUpdate, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """更新 Inbox 配置。只传需要修改的字段；`bridge_id: null` 表示解除绑定。"""
    inbox = get_account_inbox(db, account, inbox_id)
    fields = payload.model_fields_set
    if "display_name" in fields and payload.display_name is not None:
        inbox.display_name = payload.display_name
    if "bridge_id" in fields:
        if payload.bridge_id is not None:
            get_account_bridge(db, account, payload.bridge_id)
        inbox.bridge_id = payload.bridge_id
    inbox.updated_at = utc_now()
    db.commit(); db.refresh(inbox)
    return inbox


@router.delete("/api/inboxes/{inbox_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inbox(inbox_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """删除 Inbox。删除前会自动将该 Inbox 下所有待发消息（status=pending）标记为 canceled。"""
    inbox = get_account_inbox(db, account, inbox_id)
    db.query(OutboundMessage).filter(
        OutboundMessage.inbox_id == inbox.id, OutboundMessage.status == OutboundStatus.PENDING
    ).update({OutboundMessage.status: OutboundStatus.CANCELED}, synchronize_session=False)
    db.delete(inbox); db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
