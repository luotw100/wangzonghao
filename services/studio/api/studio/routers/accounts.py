"""Account management and admin overview endpoints."""

from typing import Annotated, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from studio.auth_utils import hash_password
from studio.db import get_db, utc_now
from studio.deps import AdminAccountDep, create_account_record, is_admin, revoke_account_sessions
from studio.enums import AccountRole, AccountStatus, BridgeStatus, OutboundStatus
from studio.models import (
    Account,
    Bridge,
    Contact,
    Inbox,
    Message,
    OutboundMessage,
    Persona,
    ProviderConfig,
)
from studio.schemas import AccountCreate, AccountPasswordReset, AccountUpdate
from studio.serializers import s_account

router = APIRouter()


@router.get("/api/accounts")
def list_accounts(db: Annotated[Session, Depends(get_db)], account: AdminAccountDep):
    """获取所有账号列表（仅管理员可调用），按创建时间升序排列。"""
    items = db.query(Account).order_by(Account.created_at.asc()).all()
    return [s_account(item) for item in items]


@router.post("/api/accounts")
def create_account(payload: AccountCreate, db: Annotated[Session, Depends(get_db)], account: AdminAccountDep):
    """创建新账号（仅管理员可调用）。用户名全局唯一，重复时返回 409。"""
    created = create_account_record(
        db,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        role=payload.role,
    )
    db.commit()
    db.refresh(created)
    return s_account(created)


@router.put("/api/accounts/{account_id}")
def update_account(account_id: str, payload: AccountUpdate, db: Annotated[Session, Depends(get_db)], account: AdminAccountDep):
    """更新账号信息（仅管理员可调用）。只传需要修改的字段。若将 status 设为非 active，该账号所有 session 立即失效。"""
    target = db.query(Account).filter(Account.id == account_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    fields = payload.model_fields_set
    if "display_name" in fields:
        target.display_name = payload.display_name
    if "role" in fields and payload.role is not None:
        target.role = payload.role
    if "status" in fields and payload.status is not None:
        target.status = payload.status
        if payload.status != AccountStatus.ACTIVE:
            revoke_account_sessions(db, target.id)
    target.updated_at = utc_now()
    db.commit()
    db.refresh(target)
    return s_account(target)


@router.put("/api/accounts/{account_id}/password")
def reset_account_password(
    account_id: str, payload: AccountPasswordReset, db: Annotated[Session, Depends(get_db)], account: AdminAccountDep
):
    """重置他人密码（仅管理员可调用）。不需要验证旧密码。重置后该账号所有 session 立即失效，需重新登录。"""
    target = db.query(Account).filter(Account.id == account_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="账号不存在")
    target.password_hash = hash_password(payload.password)
    target.updated_at = utc_now()
    revoke_account_sessions(db, target.id)
    db.commit()
    return {"status": "updated", "id": target.id}


@router.get("/api/admin/overview")
def admin_overview(db: Annotated[Session, Depends(get_db)], account: AdminAccountDep):
    """全局运营概览（仅管理员可调用）。

    返回两个部分：
    - `totals`：全局汇总数据，包括账号数、在线/离线 Bridge 数、Inbox 数、Persona 数、联系人数、
      开启 AI 接管的联系人数、消息总数、全局 Provider 数、待发 outbound 消息数。
    - `accounts`：每个账号的详细统计，包含账号信息及其下各类资源的计数。
    """
    accounts = db.query(Account).order_by(Account.created_at.asc()).all()

    bridge_counts: Dict[str, Dict[str, int]] = {}
    for account_id, status_value, count in (
        db.query(Bridge.account_id, Bridge.status, func.count(Bridge.id))
        .group_by(Bridge.account_id, Bridge.status)
        .all()
    ):
        bridge_counts.setdefault(account_id, {})[status_value] = count

    inbox_counts: Dict[str, int] = dict(
        db.query(Inbox.account_id, func.count(Inbox.id))
        .group_by(Inbox.account_id).all()
    )
    persona_counts: Dict[str, int] = dict(
        db.query(Persona.account_id, func.count(Persona.id))
        .group_by(Persona.account_id).all()
    )

    contact_rows = (
        db.query(Inbox.account_id, func.count(Contact.id))
        .join(Contact, Contact.inbox_id == Inbox.id)
        .group_by(Inbox.account_id).all()
    )
    contact_counts: Dict[str, int] = dict(contact_rows)

    autoreply_rows = (
        db.query(Inbox.account_id, func.count(Contact.id))
        .join(Contact, Contact.inbox_id == Inbox.id)
        .filter(Contact.takeover.is_(True))
        .group_by(Inbox.account_id).all()
    )
    autoreply_counts: Dict[str, int] = dict(autoreply_rows)

    message_rows = (
        db.query(Inbox.account_id, func.count(Message.id))
        .join(Contact, Contact.inbox_id == Inbox.id)
        .join(Message, Message.contact_id == Contact.id)
        .group_by(Inbox.account_id).all()
    )
    message_counts: Dict[str, int] = dict(message_rows)

    items: List[Dict] = []
    for a in accounts:
        bridges_for_account = bridge_counts.get(a.id, {})
        items.append({
            "account": s_account(a),
            "bridges_online": bridges_for_account.get(BridgeStatus.ONLINE, 0),
            "bridges_offline": bridges_for_account.get(BridgeStatus.OFFLINE, 0),
            "bridges_revoked": bridges_for_account.get(BridgeStatus.REVOKED, 0),
            "inboxes": inbox_counts.get(a.id, 0),
            "personas": persona_counts.get(a.id, 0),
            "contacts": contact_counts.get(a.id, 0),
            "contacts_autoreply": autoreply_counts.get(a.id, 0),
            "messages": message_counts.get(a.id, 0),
        })

    totals = {
        "accounts": len(accounts),
        "admins": sum(1 for a in accounts if a.role == AccountRole.ADMIN),
        "users": sum(1 for a in accounts if a.role == AccountRole.USER),
        "bridges_online": sum(b.get(BridgeStatus.ONLINE, 0) for b in bridge_counts.values()),
        "bridges_offline": sum(b.get(BridgeStatus.OFFLINE, 0) for b in bridge_counts.values()),
        "inboxes": sum(inbox_counts.values()),
        "personas": sum(persona_counts.values()),
        "contacts": sum(contact_counts.values()),
        "contacts_autoreply": sum(autoreply_counts.values()),
        "messages": sum(message_counts.values()),
        "providers": db.query(func.count(ProviderConfig.id)).scalar() or 0,
        "outbound_pending": db.query(func.count(OutboundMessage.id))
            .filter(OutboundMessage.status == OutboundStatus.PENDING)
            .scalar() or 0,
    }

    return {"totals": totals, "accounts": items}
