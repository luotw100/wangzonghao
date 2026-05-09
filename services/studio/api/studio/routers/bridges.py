"""Bridge read and revoke endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from studio.db import get_db, utc_now
from studio.deps import CurrentAccountDep, get_account_bridge, is_admin
from studio.enums import BridgeStatus, OutboundStatus
from studio.models import Bridge, BridgeSession, Inbox, OutboundMessage
from studio.serializers import s_bridge

router = APIRouter()


@router.get("/api/bridges")
def list_bridges(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    query = db.query(Bridge).filter(Bridge.status != BridgeStatus.REVOKED)
    if not is_admin(account):
        query = query.filter(Bridge.account_id == account.id)
    items = query.order_by(Bridge.created_at.desc()).all()
    return [s_bridge(b) for b in items]


@router.delete("/api/bridges/{bridge_id}")
def delete_bridge(bridge_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
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
    db.query(BridgeSession).filter(BridgeSession.bridge_id == b.id).delete(
        synchronize_session=False
    )
    b.status = BridgeStatus.REVOKED
    b.updated_at = utc_now()
    db.commit()
    return {"status": BridgeStatus.REVOKED, "id": bridge_id}
