"""Bridge daemon ↔ Studio protocol endpoints."""

import hashlib
import secrets
import uuid

import asyncio
import time
from datetime import timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from studio.auth_utils import verify_password
from studio.db import get_db, utc_now
from studio.deps import BridgeDep, create_auth_session, new_id, pick_first_provider
from studio.enums import (
    AccountStatus,
    ContactStatus,
    MessageAuthoredBy,
    OutboundAckResult,
    OutboundStatus,
    ReplyPolicy,
)
from studio.models import (
    Account,
    Bridge,
    Contact,
    Inbox,
    MediaHash,
    Message,
    OutboundMessage,
)
from studio.s3 import s3_presigned_get_url, s3_presigned_put_url
from studio.schemas import (
    BridgeHandshake,
    BridgeRegisterInboxes,
    BridgeIncomingBatch,
    BridgeMediaCheckOrPresignRequest,
    BridgeMediaPresignRequest,
    BridgeOutboundAck,
    BridgeReportPeers,
)
from studio.schemas import BridgeInboxView, OutboundRead

router = APIRouter()


_MACHINE_ID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _new_machine_id(db: Session, account_id: str) -> str:
    """Generate a fresh 4-char machine_id, unique per (account_id, machine_id).

    Search space: 62^4 ≈ 14.7M. Collisions per account are vanishingly
    rare; we still retry on the off-chance.
    """
    for _ in range(64):
        candidate = "".join(secrets.choice(_MACHINE_ID_ALPHABET) for _ in range(4))
        exists = (
            db.query(Bridge.id)
            .filter(Bridge.account_id == account_id, Bridge.machine_id == candidate)
            .first()
        )
        if not exists:
            return candidate
    raise HTTPException(status_code=500, detail="machine_id 生成失败")


@router.post("/api/bridge/handshake")
def bridge_handshake(payload: BridgeHandshake, db: Annotated[Session, Depends(get_db)]):
    """Login — password in, session token out. Nothing else.

    1. Verify Studio account credentials.
    2. Upsert Bridge by (account_id, machine_id). The client-supplied
       machine_id is only honored if it already matches an existing row
       for this account; otherwise Studio mints a fresh short id and the
       client must persist the returned value. This keeps machine_id
       provisioning server-controlled.
    3. Mint a fresh account session token (same table as the web console).
    """
    account = (
        db.query(Account).filter(Account.username == payload.username).first()
    )
    if not account or account.status != AccountStatus.ACTIVE or not verify_password(
        payload.password, account.password_hash
    ):
        raise HTTPException(status_code=401, detail="Studio 账号或密码错误")

    now = utc_now()
    bridge: Optional[Bridge] = None
    if payload.machine_id:
        bridge = (
            db.query(Bridge)
            .filter(Bridge.account_id == account.id, Bridge.machine_id == payload.machine_id)
            .first()
        )

    if bridge is None:
        machine_id = _new_machine_id(db, account.id)
        bridge = Bridge(
            id=new_id("br"),
            account_id=account.id,
            machine_id=machine_id,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(bridge)
        db.flush()
    else:
        machine_id = bridge.machine_id
        bridge.last_seen_at = now
        bridge.updated_at = now

    raw_token = create_auth_session(db, account)
    db.commit()

    return {
        "token": raw_token,
        "bridge_id": bridge.id,
        "machine_id": machine_id,
        "account_id": account.id,
    }


@router.post("/api/bridge/inboxes")
def bridge_register_inboxes(
    payload: BridgeRegisterInboxes,
    db: Annotated[Session, Depends(get_db)],
    bridge: BridgeDep,
):
    """Register/refresh the channel set this bridge serves. Token-authed.

    Upserts/binds an Inbox per (platform, platform_self_id), returns the
    authoritative inbox list + the outbound cursor (latest non-pending
    outbound id for served inboxes).
    """
    now = utc_now()

    served: List[Inbox] = []
    for claim in payload.inboxes:
        inbox = (
            db.query(Inbox)
            .filter(
                Inbox.account_id == bridge.account_id,
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
            account_id=bridge.account_id,
            bridge_id=bridge.id,
            platform=claim.platform,
            display_name=f"{claim.platform_self_id}@{claim.platform}",
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
        "inboxes": [BridgeInboxView.model_validate(i) for i in served],
        "cursor": cursor,
    }


@router.post("/api/bridge/heartbeat")
def bridge_heartbeat(db: Annotated[Session, Depends(get_db)], bridge: BridgeDep):
    """Bridge 心跳，刷新 last_seen_at。online/offline 由 last_seen_at + 阈值派生。"""
    bridge.last_seen_at = utc_now()
    db.commit()
    inboxes = db.query(Inbox).filter(Inbox.bridge_id == bridge.id).all()
    return {"inboxes": [BridgeInboxView.model_validate(i) for i in inboxes]}


def _canonical_sent_at(dt: Any) -> str:
    """Normalize datetime to UTC ISO8601 with microseconds — must match Bridge's canonical_sent_at."""
    from datetime import datetime as _dt
    if not isinstance(dt, _dt):
        raise ValueError(f"expected datetime, got {type(dt)}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def _compute_msg_hash(
    contact_id: str,
    sender_id: str,
    sent_at_canonical: str,
    msg_type: str,
    content_for_hash: str,
) -> str:
    """SHA256 of null-separated fields. Must match Bridge's compute_local_hash logic."""
    raw = "\x00".join([contact_id, sender_id, sent_at_canonical, msg_type, content_for_hash])
    return hashlib.sha256(raw.encode()).hexdigest()


@router.post("/api/bridge/incoming")
def bridge_incoming(
    payload: BridgeIncomingBatch,
    db: Annotated[Session, Depends(get_db)],
    bridge: BridgeDep,
):
    """批量上报入站消息（Bridge → Studio）。

    去重以 msg_hash 为唯一依据；platform_msg_id 不参与去重。
    """
    accepted = 0
    deduped = 0
    rejected = 0
    now = utc_now()
    inbox_cache: Dict[str, Inbox] = {}
    seed_provider = None   # lazy: only loaded the first time a new Contact is built

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
            if seed_provider is None:
                seed_provider = pick_first_provider(db)
                if not seed_provider:
                    raise HTTPException(status_code=409, detail="尚未配置任何 Provider，无法登记新联系人")
            contact = Contact(
                id=new_id("ct"), inbox_id=inbox.id,
                peer_platform_id=m.peer_platform_id,
                display_name=m.peer_display_name or m.peer_platform_id,
                card_md="", persona_id=None, provider_id=seed_provider.id,
                takeover=False, reply_policy=ReplyPolicy.DISABLED,
                status=ContactStatus.ACTIVE, last_reply_round_at=None,
                created_at=now, updated_at=now,
            )
            db.add(contact)
            db.flush()

        sent_at_str = _canonical_sent_at(m.sent_at)
        content_for_hash = m.content_hash if (m.msg_type != "text" and m.content_hash) else m.content
        msg_hash = _compute_msg_hash(contact.id, m.sender_id, sent_at_str, m.msg_type, content_for_hash)

        existing = (
            db.query(Message.id)
            .filter(Message.contact_id == contact.id, Message.msg_hash == msg_hash)
            .first()
        )
        if existing:
            deduped += 1
            continue

        external_id = m.platform_msg_id or None
        role = "self" if m.sender_id == inbox.platform_self_id else "counterpart"

        ts = m.sent_at if m.sent_at.tzinfo else m.sent_at.replace(tzinfo=timezone.utc)
        db.add(Message(
            contact_id=contact.id,
            external_id=external_id,
            msg_hash=msg_hash,
            role=role,
            authored_by=MessageAuthoredBy.UNKNOWN,
            sender_id=m.sender_id,
            sender_name=None,
            msg_type=m.msg_type,
            content=m.content,
            timestamp=ts,
            created_at=now,
        ))

        if m.msg_type != "text" and m.content_hash:
            existing_hash = (
                db.query(MediaHash)
                .filter(
                    MediaHash.account_id == bridge.account_id,
                    MediaHash.content_hash == m.content_hash,
                )
                .first()
            )
            if not existing_hash:
                db.add(MediaHash(
                    account_id=bridge.account_id,
                    content_hash=m.content_hash,
                    storage_key=m.content,
                    created_at=now,
                ))

        contact.updated_at = now
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
    """拉取待发消息（支持长轮询）。"""
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
                        OutboundMessage.send_after <= utc_now(),
                        OutboundMessage.content != "",
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
                payload = []
                for o in rows:
                    o.peer_platform_id = peer_map.get(o.contact_id)  # type: ignore[attr-defined]
                    payload.append(OutboundRead.model_validate(o).model_dump(mode="json"))
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
    """回报待发消息的发送结果。"""
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
        o.failed_reason = payload.reason or ""
    db.commit()
    return {"status": o.status}


@router.post("/api/bridge/media/presign-upload")
def bridge_media_presign_upload(
    payload: BridgeMediaPresignRequest,
    bridge: BridgeDep,
):
    """申请媒体文件直传 Studio S3 的预签名 PUT URL。"""
    storage_key = f"media/{bridge.id}/{uuid.uuid4().hex}"
    upload_url = s3_presigned_put_url(storage_key, payload.mime_type)
    return {"storage_key": storage_key, "upload_url": upload_url}


@router.post("/api/bridge/media/check-or-presign")
def bridge_media_check_or_presign(
    payload: BridgeMediaCheckOrPresignRequest,
    db: Annotated[Session, Depends(get_db)],
    bridge: BridgeDep,
):
    """Check whether Studio already has a file with this content hash."""
    existing = (
        db.query(MediaHash)
        .filter(
            MediaHash.account_id == bridge.account_id,
            MediaHash.content_hash == payload.content_hash,
        )
        .first()
    )
    if existing:
        return {"status": "exists", "storage_key": existing.storage_key}

    storage_key = f"media/{bridge.id}/{uuid.uuid4().hex}"
    upload_url = s3_presigned_put_url(storage_key, payload.mime_type)
    return {"status": "new", "storage_key": storage_key, "upload_url": upload_url}


@router.post("/api/bridge/peers")
def bridge_report_peers(
    payload: BridgeReportPeers,
    db: Annotated[Session, Depends(get_db)],
    bridge: BridgeDep,
):
    """Upsert contacts from the peer list the bridge discovered on the platform."""
    inbox = (
        db.query(Inbox)
        .filter(Inbox.id == payload.inbox_id, Inbox.bridge_id == bridge.id)
        .first()
    )
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox 不存在")

    now = utc_now()
    upserted = 0
    seed_provider = None
    for peer in payload.peers:
        contact = (
            db.query(Contact)
            .filter(
                Contact.inbox_id == inbox.id,
                Contact.peer_platform_id == peer.peer_platform_id,
            )
            .first()
        )
        if contact:
            contact.display_name = peer.display_name
            contact.updated_at = now
        else:
            if seed_provider is None:
                seed_provider = pick_first_provider(db)
                if not seed_provider:
                    raise HTTPException(status_code=409, detail="尚未配置任何 Provider，无法登记新联系人")
            db.add(Contact(
                id=new_id("ct"),
                inbox_id=inbox.id,
                peer_platform_id=peer.peer_platform_id,
                display_name=peer.display_name,
                card_md="",
                persona_id=None,
                provider_id=seed_provider.id,
                takeover=False,
                reply_policy=ReplyPolicy.DISABLED,
                status=ContactStatus.ACTIVE,
                last_reply_round_at=None,
                created_at=now,
                updated_at=now,
            ))
            upserted += 1

    db.commit()
    return {"upserted": upserted}


@router.get("/api/bridge/active-peers")
def bridge_active_peers(
    db: Annotated[Session, Depends(get_db)],
    bridge: BridgeDep,
):
    """获取当前 Bridge 下所有已开启 AI 接管（takeover=true）且状态正常的联系人列表。"""
    rows = (
        db.query(Contact.peer_platform_id, Inbox.id.label("inbox_id"))
        .join(Inbox, Inbox.id == Contact.inbox_id)
        .filter(
            Inbox.bridge_id == bridge.id,
            Contact.takeover.is_(True),
            Contact.status == ContactStatus.ACTIVE,
        )
        .all()
    )
    return {
        "peers": [
            {"inbox_id": r.inbox_id, "peer_platform_id": r.peer_platform_id}
            for r in rows
        ]
    }


@router.get("/api/bridge/media/{storage_key:path}")
def bridge_media_serve(
    storage_key: str,
    bridge: BridgeDep,
):
    """获取 Bridge 上传的媒体文件（302 重定向到 S3 预签名 URL）。"""
    if not storage_key.startswith(f"media/{bridge.id}/"):
        raise HTTPException(status_code=403, detail="无权访问该文件")
    url = s3_presigned_get_url(storage_key)
    return RedirectResponse(url=url)
