"""Bridge daemon ↔ Studio protocol endpoints."""

import asyncio
import time
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from studio.auth_utils import hash_password, verify_password, new_session_token, hash_token
from studio.db import get_db, utc_now
from studio.deps import BridgeDep, new_id
from studio.enums import (
    AccountStatus,
    BridgeStatus,
    ContactStatus,
    DistillJobStatus,
    MessageRole,
    MessageSource,
    OutboundAckResult,
    OutboundStatus,
    PersonaStatus,
)
from studio.models import (
    Account,
    Bridge,
    BridgeSession,
    Contact,
    Inbox,
    Message,
    OutboundMessage,
    Persona,
)
from studio.schemas import BridgeHandshake, BridgeIncomingBatch, BridgeOutboundAck
from studio.serializers import s_bridge_inbox_view

router = APIRouter()


@router.post("/api/bridge/handshake")
def bridge_handshake(payload: BridgeHandshake, db: Annotated[Session, Depends(get_db)]):
    """Login + register + report served inboxes, in one call.

    1. Verify Studio account credentials.
    2. Upsert Bridge by (account_id, hostname).
    3. Wipe prior BridgeSession rows for this bridge; mint a fresh token.
    4. Upsert an Inbox per (platform, platform_self_id) the bridge logged into.
    5. Return the token + authoritative inbox list + outbound cursor.
    """
    account = (
        db.query(Account).filter(Account.username == payload.username).first()
    )
    if not account or account.status != AccountStatus.ACTIVE or not verify_password(
        payload.password, account.password_hash
    ):
        raise HTTPException(status_code=401, detail="Studio 账号或密码错误")

    now = utc_now()
    bridge = (
        db.query(Bridge)
        .filter(Bridge.account_id == account.id, Bridge.hostname == payload.hostname)
        .first()
    )
    if bridge is None:
        bridge = Bridge(
            id=new_id("br"),
            account_id=account.id,
            hostname=payload.hostname,
            display_name=payload.hostname,
            status=BridgeStatus.ONLINE,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(bridge)
        db.flush()
    else:
        bridge.status = BridgeStatus.ONLINE
        bridge.last_seen_at = now
        bridge.updated_at = now

    db.query(BridgeSession).filter(BridgeSession.bridge_id == bridge.id).delete(
        synchronize_session=False
    )
    raw_token = new_session_token()
    db.add(BridgeSession(
        id=hash_token(raw_token),
        bridge_id=bridge.id,
        created_at=now,
        last_seen_at=now,
    ))

    default_persona = (
        db.query(Persona)
        .filter(Persona.account_id == account.id, Persona.status == PersonaStatus.ACTIVE)
        .order_by(Persona.created_at.asc())
        .first()
    )

    served: List[Inbox] = []
    for claim in payload.inboxes:
        inbox = (
            db.query(Inbox)
            .filter(
                Inbox.account_id == account.id,
                Inbox.platform == claim.platform,
                Inbox.platform_self_id == claim.platform_self_id,
            )
            .first()
        )
        if inbox:
            inbox.bridge_id = bridge.id
            inbox.updated_at = now
            served.append(inbox)
            continue

        inbox = Inbox(
            id=new_id("ib"),
            account_id=account.id,
            bridge_id=bridge.id,
            platform=claim.platform,
            display_name=f"{claim.platform_self_id}@{claim.platform}",
            default_persona_id=default_persona.id if default_persona else None,
            reply_provider_config_id=None,
            enabled=True,
            platform_self_id=claim.platform_self_id,
            created_at=now,
            updated_at=now,
        )
        db.add(inbox)
        db.flush()
        served.append(inbox)

    if served:
        last_outbound_id = (
            db.query(OutboundMessage.id)
            .filter(
                OutboundMessage.inbox_id.in_([i.id for i in served]),
                OutboundMessage.status != OutboundStatus.PENDING,
            )
            .order_by(OutboundMessage.id.desc())
            .first()
        )
        cursor = last_outbound_id[0] if last_outbound_id else 0
    else:
        cursor = 0
    db.commit()

    return {
        "token": raw_token,
        "bridge_id": bridge.id,
        "account_id": account.id,
        "inboxes": [s_bridge_inbox_view(i) for i in served],
        "cursor": cursor,
        "no_persona": not default_persona,
    }


@router.post("/api/bridge/heartbeat")
def bridge_heartbeat(db: Annotated[Session, Depends(get_db)], bridge: BridgeDep):
    now = utc_now()
    bridge.last_seen_at = now
    if bridge.status != BridgeStatus.ONLINE:
        bridge.status = BridgeStatus.ONLINE
    db.commit()
    inboxes = db.query(Inbox).filter(Inbox.bridge_id == bridge.id).all()
    return {"inboxes": [s_bridge_inbox_view(i) for i in inboxes]}


@router.post("/api/bridge/incoming")
def bridge_incoming(payload: BridgeIncomingBatch, db: Annotated[Session, Depends(get_db)], bridge: BridgeDep):
    accepted = 0
    deduped = 0
    rejected = 0
    now = utc_now()
    inbox_cache: Dict[str, Inbox] = {}
    for m in payload.messages:
        inbox = inbox_cache.get(m.inbox_id)
        if inbox is None:
            inbox = (
                db.query(Inbox).filter(
                    Inbox.id == m.inbox_id,
                    Inbox.bridge_id == bridge.id,
                    Inbox.account_id == bridge.account_id,
                ).first()
            )
            if not inbox:
                rejected += 1
                continue
            inbox_cache[m.inbox_id] = inbox

        contact = (
            db.query(Contact)
            .filter(Contact.inbox_id == inbox.id, Contact.peer_platform_id == m.peer_platform_id)
            .first()
        )
        if not contact:
            contact = Contact(
                id=new_id("ct"), inbox_id=inbox.id,
                peer_platform_id=m.peer_platform_id,
                display_name=m.peer_display_name or m.peer_platform_id,
                card_md=None, persona_id=inbox.default_persona_id,
                reply_provider_config_id=inbox.reply_provider_config_id,
                autoreply_enabled=False, pending_reply=False,
                status=ContactStatus.ACTIVE, last_seen_platform_msg_id=None,
                created_at=now, updated_at=now,
            )
            db.add(contact); db.flush()

        external_id = f"live:{m.platform_msg_id}"
        existing = (
            db.query(Message)
            .filter(Message.contact_id == contact.id, Message.external_id == external_id)
            .first()
        )
        if existing:
            deduped += 1
            continue

        ts = m.sent_at.replace(tzinfo=None) if m.sent_at.tzinfo else m.sent_at
        db.add(Message(
            contact_id=contact.id, archive_id=None,
            external_id=external_id, source=MessageSource.LIVE,
            role=m.role, sender_name=None, content=m.content,
            timestamp=ts, archive_msg_idx=None, created_at=now,
        ))
        contact.last_seen_platform_msg_id = m.platform_msg_id
        contact.updated_at = now
        if m.role == MessageRole.COUNTERPART and inbox.enabled and contact.autoreply_enabled:
            contact.pending_reply = True
        accepted += 1

    bridge.last_seen_at = now
    db.commit()
    return {"accepted": accepted, "deduped": deduped, "rejected": rejected}


@router.get("/api/bridge/outbound")
async def bridge_outbound(
    bridge: BridgeDep,
    cursor: int = Query(0, ge=0),
    timeout: int = Query(0, ge=0, le=60),
):
    deadline = time.time() + timeout
    while True:
        from studio.db import SessionLocal
        db = SessionLocal()
        try:
            inbox_ids = [
                r[0] for r in db.query(Inbox.id).filter(Inbox.bridge_id == bridge.id).all()
            ]
            if not inbox_ids:
                payload: List[Dict[str, Any]] = []
            else:
                rows = (
                    db.query(OutboundMessage)
                    .filter(
                        OutboundMessage.inbox_id.in_(inbox_ids),
                        OutboundMessage.id > cursor,
                        OutboundMessage.status == OutboundStatus.PENDING,
                    )
                    .order_by(OutboundMessage.id.asc())
                    .limit(50)
                    .all()
                )
                contact_ids = list({o.contact_id for o in rows})
                peer_map: Dict[str, str] = {}
                if contact_ids:
                    peers = db.query(Contact.id, Contact.peer_platform_id).filter(
                        Contact.id.in_(contact_ids)
                    ).all()
                    peer_map = {cid: peer for cid, peer in peers}
                from studio.serializers import s_outbound
                payload = [s_outbound(o, peer_platform_id=peer_map.get(o.contact_id)) for o in rows]
        finally:
            db.close()
        if payload:
            return payload
        if time.time() >= deadline:
            return payload
        await asyncio.sleep(min(0.5, max(0.1, deadline - time.time())))


@router.post("/api/bridge/outbound/{outbound_id}/ack")
def bridge_outbound_ack(
    outbound_id: int, payload: BridgeOutboundAck, db: Annotated[Session, Depends(get_db)], bridge: BridgeDep
):
    from studio.serializers import s_outbound
    o = (
        db.query(OutboundMessage)
        .join(Inbox, Inbox.id == OutboundMessage.inbox_id)
        .filter(OutboundMessage.id == outbound_id, Inbox.bridge_id == bridge.id)
        .first()
    )
    if not o:
        raise HTTPException(status_code=404, detail="Outbound 不存在")
    if o.status != OutboundStatus.PENDING:
        return {"status": o.status}
    now = utc_now()
    if payload.result == OutboundAckResult.SENT:
        o.status = OutboundStatus.DELIVERED
        o.delivered_at = now
    else:
        o.status = OutboundStatus.FAILED
        o.failed_reason = payload.reason
    db.commit()
    return {"status": o.status}
