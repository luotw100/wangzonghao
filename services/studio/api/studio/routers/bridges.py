"""Bridge read and revoke endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from studio.db import get_db, utc_now
from studio.deps import CurrentAccountDep, get_account_bridge
from studio.enums import BridgeStatus, OutboundStatus
from studio.models import Bridge, Inbox, OutboundMessage
from studio.serializers import s_bridge

router = APIRouter()


@router.get("/api/bridges")
def list_bridges(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取当前账号的 Bridge 列表（已撤销的除外），按创建时间降序排列。

    Bridge 代表一个运行中的守护进程实例，由 Bridge 守护程序首次握手时自动创建，用户无法手动创建。
    """
    query = db.query(Bridge).filter(
        Bridge.status != BridgeStatus.REVOKED,
        Bridge.account_id == account.id,
    )
    items = query.order_by(Bridge.created_at.desc()).all()
    return [s_bridge(b) for b in items]


@router.delete("/api/bridges/{bridge_id}")
def delete_bridge(bridge_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """撤销 Bridge（即踢下线）。

    执行以下操作：
    1. 将该 Bridge 下所有 Inbox 的待发消息（status=pending）标记为 canceled；
    2. 解除所有 Inbox 与该 Bridge 的绑定（bridge_id 置为 null）；
    3. 将 Bridge 状态设为 revoked——鉴权按 (account, machine_id) 解析到该
       Bridge 行后会因 status=revoked 直接拒绝，即使守护进程还在运行，下次
       心跳或拉取消息时会收到 401。账号的 web/其他机器 session 不受影响。
    被撤销的 Bridge 守护进程若要重新接入，需重新执行握手流程。
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
    b.status = BridgeStatus.REVOKED
    b.updated_at = utc_now()
    db.commit()
    return {"status": BridgeStatus.REVOKED, "id": bridge_id}
