"""Bridge read and revoke endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from studio.db import get_db
from studio.deps import CurrentAccountDep, get_account_bridge
from studio.enums import OutboundStatus
from studio.models import Bridge, Inbox, OutboundMessage
from studio.schemas import BridgeRead

router = APIRouter()


@router.get("/api/bridges", response_model=list[BridgeRead])
def list_bridges(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取当前账号的 Bridge 列表，按创建时间降序排列。"""
    return (
        db.query(Bridge)
        .filter(Bridge.account_id == account.id)
        .order_by(Bridge.created_at.desc())
        .all()
    )


@router.delete("/api/bridges/{bridge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bridge(bridge_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """撤销 Bridge（即删除该记录）。

    1. 将该 Bridge 下所有 Inbox 的待发消息（status=pending）标记为 canceled；
    2. 解除所有 Inbox 与该 Bridge 的绑定（bridge_id 置为 null）；
    3. 删除 Bridge 行——下次握手会按 (account, machine_id) 找不到，
       自动重新签发一个新的 machine_id。
    """
    b = get_account_bridge(db, account, bridge_id)
    inbox_ids = [r[0] for r in db.query(Inbox.id).filter(Inbox.bridge_id == b.id).all()]
    if inbox_ids:
        db.query(OutboundMessage).filter(
            OutboundMessage.inbox_id.in_(inbox_ids),
            OutboundMessage.status == OutboundStatus.PENDING,
        ).update({OutboundMessage.status: OutboundStatus.CANCELED}, synchronize_session=False)
        db.query(Inbox).filter(Inbox.bridge_id == b.id).update(
            {Inbox.bridge_id: None}, synchronize_session=False
        )
    db.delete(b)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
