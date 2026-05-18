"""Bridge daemon ↔ Studio protocol endpoints."""

import hashlib
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
from studio.deps import BridgeDep, create_auth_session, new_id
from studio.enums import (
    AccountStatus,
    BridgeStatus,
    ContactStatus,
    MessageAuthoredBy,
    OutboundAckResult,
    OutboundStatus,
    PersonaStatus,
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
    Persona,
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
from studio.serializers import s_bridge_inbox_view

router = APIRouter()


@router.post("/api/bridge/handshake")
def bridge_handshake(payload: BridgeHandshake, db: Annotated[Session, Depends(get_db)]):
    """Login — password in, session token out. Nothing else.

    1. Verify Studio account credentials.
    2. Upsert Bridge by (account_id, machine_id). If no machine_id given
       (first launch), Studio generates one with id_new("m").
    3. Mint a fresh account session token (same table as the web console).
       The daemon sends X-Machine-Id on every subsequent /api/bridge/*
       call; the bridge identity is resolved from that, not the token.

    Channel registration is a separate token-authenticated call
    (POST /api/bridge/inboxes). The bridge persists the token and reuses
    it across restarts — the password is never stored and only re-entered
    when the token is revoked/expired, exactly like a browser session.
    """
    account = (
        db.query(Account).filter(Account.username == payload.username).first()
    )
    if not account or account.status != AccountStatus.ACTIVE or not verify_password(
        payload.password, account.password_hash
    ):
        raise HTTPException(status_code=401, detail="Studio 账号或密码错误")

    now = utc_now()
    if payload.machine_id:
        bridge = (
            db.query(Bridge)
            .filter(Bridge.account_id == account.id, Bridge.machine_id == payload.machine_id)
            .first()
        )
    else:
        bridge = None

    if bridge is None:
        machine_id = new_id("m")
        bridge = Bridge(
            id=new_id("br"),
            account_id=account.id,
            machine_id=machine_id,
            status=BridgeStatus.ONLINE,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(bridge)
        db.flush()
    else:
        machine_id = bridge.machine_id
        bridge.status = BridgeStatus.ONLINE
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

    Called by the daemon on every start and whenever the user adds or
    removes a channel. Upserts/binds an Inbox per (platform,
    platform_self_id), returns the authoritative inbox list + the
    outbound cursor (latest non-pending outbound id for served inboxes).
    """
    now = utc_now()
    default_persona = (
        db.query(Persona)
        .filter(Persona.account_id == bridge.account_id, Persona.status == PersonaStatus.ACTIVE)
        .order_by(Persona.created_at.asc())
        .first()
    )

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
        "inboxes": [s_bridge_inbox_view(i) for i in served],
        "cursor": cursor,
        "no_persona": not default_persona,
    }


@router.post("/api/bridge/heartbeat")
def bridge_heartbeat(db: Annotated[Session, Depends(get_db)], bridge: BridgeDep):
    """Bridge 心跳。每次调用刷新 last_seen_at，并将 status 置为 online（若此前因超时被标记为 offline）。
    返回当前 Bridge 服务的 Inbox 列表（含最新配置），Bridge 可借此感知 Inbox 绑定变化。
    """
    now = utc_now()
    bridge.last_seen_at = now
    if bridge.status != BridgeStatus.ONLINE:
        bridge.status = BridgeStatus.ONLINE
    db.commit()
    inboxes = db.query(Inbox).filter(Inbox.bridge_id == bridge.id).all()
    return {"inboxes": [s_bridge_inbox_view(i) for i in inboxes]}


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

    Studio 对每条消息执行以下处理：
    1. 校验 inbox_id 确实属于当前 Bridge，不属于则 rejected+1；
    2. 按 peer_platform_id 查找或自动创建 Contact（继承 Inbox 的默认人设和 Provider）；
    3. 双重去重：先按 msg_hash（SHA256 of contact_id+sender_id+sent_at+msg_type+content），
       再按 platform_msg_id（向后兼容旧数据）；重复则 deduped+1；
    4. 写入消息，role 由 sender_id 与 inbox.platform_self_id 比较决定（self / counterpart）；
    5. 若是媒体消息且附带 content_hash，写入 MediaHash 表（避免后续重复上传）；
    6. 若对方发来消息且 reply_policy=autoreply，将 contact.pending_reply 置为 true，触发 worker 生成回复。

    返回 accepted / deduped / rejected 计数。
    """
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
                takeover=False, reply_policy=ReplyPolicy.DISABLED, pending_reply=False,
                status=ContactStatus.ACTIVE, last_seen_platform_msg_id=None,
                created_at=now, updated_at=now,
            )
            db.add(contact)
            db.flush()

        # Compute msg_hash for primary dedup.
        sent_at_str = _canonical_sent_at(m.sent_at)
        content_for_hash = m.content_hash if (m.msg_type != "text" and m.content_hash) else m.content
        msg_hash = _compute_msg_hash(contact.id, m.sender_id, sent_at_str, m.msg_type, content_for_hash)

        # Primary dedup: msg_hash.
        existing = (
            db.query(Message.id)
            .filter(Message.contact_id == contact.id, Message.msg_hash == msg_hash)
            .first()
        )
        if existing:
            deduped += 1
            continue

        # Secondary dedup: external_id (backward compat for pre-migration rows with msg_hash=NULL).
        if m.platform_msg_id:
            external_id = f"live:{m.platform_msg_id}"
            existing_ext = (
                db.query(Message.id)
                .filter(Message.contact_id == contact.id, Message.external_id == external_id)
                .first()
            )
            if existing_ext:
                deduped += 1
                continue
        else:
            external_id = f"hash:{msg_hash}"

        # Compute role from sender_id vs inbox platform_self_id.
        role = "self" if m.sender_id == inbox.platform_self_id else "counterpart"

        ts = m.sent_at if m.sent_at.tzinfo else m.sent_at.replace(tzinfo=timezone.utc)
        db.add(Message(
            contact_id=contact.id,
            external_id=external_id,
            msg_hash=msg_hash,
            role=role,
            authored_by=MessageAuthoredBy.UNKNOWN,
            sender_id=m.sender_id,
            msg_type=m.msg_type,
            sender_name=None,
            content=m.content,
            timestamp=ts,
            created_at=now,
        ))

        # Record media hash mapping so check-or-presign can skip re-uploads.
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
                ))

        contact.last_seen_platform_msg_id = m.platform_msg_id
        contact.updated_at = now
        if role == "counterpart" and inbox.enabled and contact.reply_policy == ReplyPolicy.AUTOREPLY:
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
    """拉取待发消息（支持长轮询）。Bridge 用此接口驱动主动发送流程。

    - `cursor`：只返回 ID 严格大于此值且 status=pending、send_after<=now 的消息，每次最多 50 条。
      Bridge 应将最后一条消息的 id 作为新 cursor 供下次调用。
    - `timeout`：长轮询等待秒数（0~60）。无消息时服务端等待最多 timeout 秒，期间每 0.1~0.5s 查询一次；
      超时后返回空列表。传 0 则立即返回（短轮询）。
    - 返回的每条消息包含 peer_platform_id（用于定位平台侧发送目标）。
    - Bridge 取到消息后应尽快调用 POST /api/bridge/outbound/{id}/ack 回报发送结果。
    """
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
    """回报待发消息的发送结果。

    - result=sent：消息状态变为 delivered，记录 delivered_at；
    - result=failed：消息状态变为 failed，记录 failed_reason；
    - 若消息不在 pending 状态（已 delivered/failed/canceled），直接返回当前状态，不重复处理（幂等）。
    """
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


@router.post("/api/bridge/media/presign-upload")
def bridge_media_presign_upload(
    payload: BridgeMediaPresignRequest,
    bridge: BridgeDep,
):
    """申请媒体文件直传 Studio S3 的预签名 PUT URL。

    返回 storage_key 和 upload_url。Bridge 用 HTTP PUT 将文件二进制直接上传到 upload_url，
    上传成功后将 storage_key 作为消息的 content 通过 /api/bridge/incoming 上报。

    注意：若同一文件可能重复上传，应优先使用 POST /api/bridge/media/check-or-presign，
    避免相同内容被多次传输。
    """
    storage_key = f"media/{bridge.id}/{uuid.uuid4().hex}"
    upload_url = s3_presigned_put_url(storage_key, payload.mime_type)
    return {"storage_key": storage_key, "upload_url": upload_url}


@router.post("/api/bridge/media/check-or-presign")
def bridge_media_check_or_presign(
    payload: BridgeMediaCheckOrPresignRequest,
    db: Annotated[Session, Depends(get_db)],
    bridge: BridgeDep,
):
    """Check whether Studio already has a file with this content hash.

    Returns {"status": "exists", "storage_key": "..."} if the file is
    already in Studio S3 (skip upload). Returns {"status": "new",
    "storage_key": "...", "upload_url": "..."} otherwise; Bridge should
    PUT the file binary to upload_url before calling /incoming.
    """
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
    """Upsert contacts from the peer list the bridge discovered on the platform.

    Creates new contacts with takeover=False; updates display_name for existing ones.
    Does not touch takeover or reply_policy so user state is preserved.
    """
    inbox = (
        db.query(Inbox)
        .filter(Inbox.id == payload.inbox_id, Inbox.bridge_id == bridge.id)
        .first()
    )
    if not inbox:
        raise HTTPException(status_code=404, detail="Inbox 不存在")

    now = utc_now()
    upserted = 0
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
            db.add(Contact(
                id=new_id("ct"),
                inbox_id=inbox.id,
                peer_platform_id=peer.peer_platform_id,
                display_name=peer.display_name,
                card_md=None,
                persona_id=inbox.default_persona_id,
                reply_provider_config_id=inbox.reply_provider_config_id,
                takeover=False,
                reply_policy=ReplyPolicy.DISABLED,
                pending_reply=False,
                status=ContactStatus.ACTIVE,
                last_seen_platform_msg_id=None,
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
    """获取当前 Bridge 下所有已开启 AI 接管（takeover=true）且状态正常的联系人列表。

    Bridge 用此接口初始化本地的"接管名单"，决定哪些 peer 的消息要触发 AI 回复。
    返回格式：[{"inbox_id": "...", "peer_platform_id": "..."}]。
    """
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
    """获取 Bridge 上传的媒体文件（302 重定向到 S3 预签名 URL）。

    只允许访问属于当前 Bridge 的文件（storage key 必须以 `media/{bridge_id}/` 开头），否则返回 403。
    """
    if not storage_key.startswith(f"media/{bridge.id}/"):
        raise HTTPException(status_code=403, detail="无权访问该文件")
    url = s3_presigned_get_url(storage_key)
    return RedirectResponse(url=url)
