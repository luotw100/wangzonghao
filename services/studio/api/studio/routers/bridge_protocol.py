"""Bridge daemon ↔ Studio protocol (v2 — 8 endpoints).

  POST /api/bridge/handshake               username+password → token (+ machine_id)
  POST /api/bridge/inboxes                 register channels (with display_name)
  GET  /api/bridge/inboxes                 read current channel set
  POST /api/bridge/heartbeat               empty in / empty out
  POST /api/bridge/incoming                push messages (client_id dedup, conversation ref only)
  GET  /api/bridge/outbound                long-poll pending outbound (no cursor, no lease)
  POST /api/bridge/conversations           upsert conversation metadata (kind, display, members)
  GET  /api/bridge/takeovers               pull takeover (active) conversation set

Design highlights vs v1:
  - machine_id mismatch returns 400, not silent rotation.
  - Conversation identity is (inbox_id, platform_conversation_id), with
    kind dm/group. Studio creates a placeholder when /incoming arrives
    before /conversations; /conversations updates in-place.
  - Dedup uses bridge-supplied client_id (per-(conversation, client_id)).
  - No outbound cursor, no ack endpoint. PENDING → DELIVERED is auto-
    closed when an /incoming from_self (sender_id IS NULL) matches by
    (conversation_id, content).
  - /peers, /active-peers, /media/* all removed.
"""

import asyncio
import secrets
import time
from datetime import timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from studio.auth_utils import verify_password
from studio.db import get_db, utc_now
from studio.deps import BridgeDep, create_auth_session, new_id, pick_first_provider
from studio.enums import (
    AccountStatus,
    ConversationKind,
    ConversationStatus,
    OutboundStatus,
    ReplyPolicy,
)
from studio.models import (
    Account,
    Bridge,
    Conversation,
    ConversationMember,
    Inbox,
    Message,
    OutboundMessage,
)
from studio.schemas import (
    BridgeConversationsUpsert,
    BridgeHandshake,
    BridgeIncomingBatch,
    BridgeInboxView,
    BridgeRegisterInboxes,
    OutboundForBridge,
)

router = APIRouter()


_MACHINE_ID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _new_machine_id(db: Session, account_id: str) -> str:
    """Generate a 4-char machine_id unique within an account."""
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


# ===========================================================================
# 1. handshake — password → token
# ===========================================================================

@router.post("/api/bridge/handshake")
def bridge_handshake(payload: BridgeHandshake, db: Annotated[Session, Depends(get_db)]):
    """Password-for-token. machine_id mismatch is 400, not silent rotation.

    - Empty machine_id ⇒ Studio mints a new short id, creates Bridge row.
    - Non-empty machine_id ⇒ must match an existing (account, machine_id);
      otherwise 400 (the client should drop its local state and retry
      without machine_id).
    - Always returns ``account_id`` + ``username``; never returns
      ``bridge_id`` (the client doesn't need it).
    """
    account = (
        db.query(Account).filter(Account.username == payload.username).first()
    )
    if (
        not account
        or account.status != AccountStatus.ACTIVE
        or not verify_password(payload.password, account.password_hash)
    ):
        raise HTTPException(status_code=401, detail="Studio 账号或密码错误")

    now = utc_now()
    bridge: Optional[Bridge] = None
    if payload.machine_id:
        bridge = (
            db.query(Bridge)
            .filter(
                Bridge.account_id == account.id,
                Bridge.machine_id == payload.machine_id,
            )
            .first()
        )
        if bridge is None:
            raise HTTPException(
                status_code=400,
                detail="machine_id_invalid",
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
        "account_id": account.id,
        "username": account.username,
        "machine_id": machine_id,
    }


# ===========================================================================
# 2. inboxes (POST register / GET read)
# ===========================================================================

@router.post("/api/bridge/inboxes")
def bridge_register_inboxes(
    payload: BridgeRegisterInboxes,
    db: Annotated[Session, Depends(get_db)],
    bridge: BridgeDep,
):
    """Upsert the channel set this bridge serves; display_name comes from
    Bridge (it knows the platform-side nickname).
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
            inbox.display_name = claim.display_name
            inbox.updated_at = now
            served.append(inbox)
            continue

        inbox = Inbox(
            id=new_id("ib"),
            account_id=bridge.account_id,
            bridge_id=bridge.id,
            platform=claim.platform,
            display_name=claim.display_name,
            platform_self_id=claim.platform_self_id,
            created_at=now,
            updated_at=now,
        )
        db.add(inbox)
        db.flush()
        served.append(inbox)

    db.commit()
    return {"inboxes": [BridgeInboxView.model_validate(i) for i in served]}


@router.get("/api/bridge/inboxes")
def bridge_get_inboxes(
    db: Annotated[Session, Depends(get_db)],
    bridge: BridgeDep,
):
    """Returns the set of inboxes Studio currently considers this bridge to
    serve. Bridge calls this when it wants to detect external changes
    (e.g. operator unbound an inbox) without re-registering.
    """
    inboxes = db.query(Inbox).filter(Inbox.bridge_id == bridge.id).all()
    return {"inboxes": [BridgeInboxView.model_validate(i) for i in inboxes]}


# ===========================================================================
# 3. heartbeat
# ===========================================================================

@router.post("/api/bridge/heartbeat")
def bridge_heartbeat(db: Annotated[Session, Depends(get_db)], bridge: BridgeDep):
    """Pure heartbeat — refresh last_seen_at, return empty body."""
    bridge.last_seen_at = utc_now()
    db.commit()
    return {}


# ===========================================================================
# 4. incoming
# ===========================================================================

def _get_or_create_placeholder_conversation(
    db: Session,
    *,
    inbox: Inbox,
    platform_conversation_id: str,
    seed_provider_id_supplier,
    now,
) -> Conversation:
    """Find conversation by (inbox, platform_conversation_id); create a
    placeholder (kind=unknown) if absent so a message can land before its
    metadata arrives via /conversations.
    """
    conv = (
        db.query(Conversation)
        .filter(
            Conversation.inbox_id == inbox.id,
            Conversation.platform_conversation_id == platform_conversation_id,
        )
        .first()
    )
    if conv is not None:
        return conv
    provider_id = seed_provider_id_supplier()
    conv = Conversation(
        id=new_id("cv"),
        inbox_id=inbox.id,
        platform_conversation_id=platform_conversation_id,
        kind=ConversationKind.UNKNOWN,
        display_name=platform_conversation_id,
        card_md="",
        persona_id=None,
        provider_id=provider_id,
        takeover=False,
        reply_policy=ReplyPolicy.DISABLED,
        status=ConversationStatus.ACTIVE,
        last_reply_round_at=None,
        created_at=now,
        updated_at=now,
    )
    db.add(conv)
    db.flush()
    return conv


@router.post("/api/bridge/incoming")
def bridge_incoming(
    payload: BridgeIncomingBatch,
    db: Annotated[Session, Depends(get_db)],
    bridge: BridgeDep,
):
    """Bulk push inbound messages. Dedup by (conversation_id, client_id).

    Side-effect: when an inbound has sender_id IS NULL (i.e. "from self"),
    Studio tries to settle a matching PENDING outbound — by
    (conversation_id, content) — to status=DELIVERED. That replaces the
    outbound ack endpoint.
    """
    accepted = 0
    deduped = 0
    rejected = 0
    now = utc_now()
    inbox_cache: Dict[str, Inbox] = {}

    _seed_provider_cached = {"value": None}

    def get_seed_provider_id() -> str:
        if _seed_provider_cached["value"] is None:
            sp = pick_first_provider(db)
            if not sp:
                raise HTTPException(
                    status_code=409,
                    detail="尚未配置任何 Provider，无法登记新会话",
                )
            _seed_provider_cached["value"] = sp.id
        return _seed_provider_cached["value"]

    for m in payload.messages:
        inbox = inbox_cache.get(m.inbox_id)
        if inbox is None:
            inbox = (
                db.query(Inbox)
                .filter(
                    Inbox.id == m.inbox_id,
                    Inbox.bridge_id == bridge.id,
                    Inbox.account_id == bridge.account_id,
                )
                .first()
            )
            if not inbox:
                rejected += 1
                continue
            inbox_cache[m.inbox_id] = inbox

        conv = _get_or_create_placeholder_conversation(
            db,
            inbox=inbox,
            platform_conversation_id=m.platform_conversation_id,
            seed_provider_id_supplier=get_seed_provider_id,
            now=now,
        )

        existing = (
            db.query(Message.id)
            .filter(
                Message.conversation_id == conv.id,
                Message.client_id == m.client_id,
            )
            .first()
        )
        if existing:
            deduped += 1
            continue

        ts = m.sent_at if m.sent_at.tzinfo else m.sent_at.replace(tzinfo=timezone.utc)
        db.add(
            Message(
                conversation_id=conv.id,
                client_id=m.client_id,
                sender_id=m.sender_id,
                msg_type=m.msg_type,
                content=m.content,
                timestamp=ts,
                created_at=now,
            )
        )

        # Settle a matching PENDING outbound (auto-ack via inbound from_self).
        if m.sender_id is None:
            ob = (
                db.query(OutboundMessage)
                .filter(
                    OutboundMessage.conversation_id == conv.id,
                    OutboundMessage.status == OutboundStatus.PENDING,
                    OutboundMessage.content == m.content,
                )
                .order_by(OutboundMessage.id.asc())
                .first()
            )
            if ob is not None:
                ob.status = OutboundStatus.DELIVERED
                ob.delivered_at = now

        conv.updated_at = now
        accepted += 1

    bridge.last_seen_at = now
    db.commit()
    return {"accepted": accepted, "deduped": deduped, "rejected": rejected}


# ===========================================================================
# 5. outbound (long-poll, no cursor, no lease, no ack)
# ===========================================================================

@router.get("/api/bridge/outbound")
async def bridge_outbound(
    bridge: BridgeDep,
    timeout: int = Query(0, ge=0, le=60),
):
    """长轮询待发消息队列，每次最多返回 50 条 OutboundForBridge。

    设计要点：
    - 无游标：Bridge 每次拉取的都是当前全量 PENDING 集合（id asc），
      重启或重连后直接继续处理，不需要维护本地 offset。
    - 无租约：Bridge 用内存 _inflight 字典（INFLIGHT_TTL_S 窗口）做本地去重，
      防止同一条消息在同一次 long-poll 内重复发送。
    - id 是插入顺序，按 id asc 返回保证先创建的先发，但 id 不代表时间语义。
    - 状态回写：PENDING → DELIVERED 由 /incoming 的 from_self 消息自动 ack，
      无显式 ack 接口。永久发送失败的行保留 PENDING 状态，由运营手动清理。
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
                    db.query(OutboundMessage, Conversation.platform_conversation_id)
                    .join(Conversation, Conversation.id == OutboundMessage.conversation_id)
                    .filter(
                        OutboundMessage.inbox_id.in_(inbox_ids),
                        OutboundMessage.status == OutboundStatus.PENDING,
                        OutboundMessage.send_after <= utc_now(),
                    )
                    .order_by(OutboundMessage.id.asc())
                    .limit(50)
                    .all()
                )
                payload = [
                    {
                        "id": ob.id,
                        "inbox_id": ob.inbox_id,
                        "platform_conversation_id": pcid,
                        "msg_type": ob.msg_type,
                        "content": ob.content,
                    }
                    for ob, pcid in rows
                ]
        finally:
            db.close()
        if payload:
            return payload
        if time.time() >= deadline:
            return payload
        await asyncio.sleep(min(0.5, max(0.1, deadline - time.time())))


# ===========================================================================
# 6. conversations (upsert metadata)
# ===========================================================================

@router.post("/api/bridge/conversations")
def bridge_upsert_conversations(
    payload: BridgeConversationsUpsert,
    db: Annotated[Session, Depends(get_db)],
    bridge: BridgeDep,
):
    """Upsert per-conversation metadata (kind, display_name, members).

    Bridge calls this on startup and when its local diff detects any
    conversation change. Pure upsert — conversations missing from the
    payload stay (we don't soft-delete; bridges paginate and partial
    snapshots are the norm).
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
    seed_provider = None

    for item in payload.conversations:
        conv = (
            db.query(Conversation)
            .filter(
                Conversation.inbox_id == inbox.id,
                Conversation.platform_conversation_id == item.platform_conversation_id,
            )
            .first()
        )
        if conv is None:
            if seed_provider is None:
                seed_provider = pick_first_provider(db)
                if not seed_provider:
                    raise HTTPException(
                        status_code=409,
                        detail="尚未配置任何 Provider，无法登记新会话",
                    )
            conv = Conversation(
                id=new_id("cv"),
                inbox_id=inbox.id,
                platform_conversation_id=item.platform_conversation_id,
                kind=item.kind,
                display_name=item.display_name,
                card_md="",
                persona_id=None,
                provider_id=seed_provider.id,
                takeover=False,
                reply_policy=ReplyPolicy.DISABLED,
                status=ConversationStatus.ACTIVE,
                last_reply_round_at=None,
                created_at=now,
                updated_at=now,
            )
            db.add(conv)
            db.flush()
        else:
            # Update metadata in-place. Don't touch takeover/persona/etc.
            conv.kind = item.kind
            conv.display_name = item.display_name
            conv.updated_at = now

        # Member upsert: replace the member set for this conversation.
        existing_members = {
            m.peer_platform_id: m
            for m in db.query(ConversationMember)
            .filter(ConversationMember.conversation_id == conv.id)
            .all()
        }
        incoming_ids = set()
        for mem in item.members:
            incoming_ids.add(mem.peer_platform_id)
            row = existing_members.get(mem.peer_platform_id)
            if row is None:
                db.add(
                    ConversationMember(
                        conversation_id=conv.id,
                        peer_platform_id=mem.peer_platform_id,
                        display_name=mem.display_name,
                        updated_at=now,
                    )
                )
            else:
                row.display_name = mem.display_name
                row.updated_at = now
        for pid, row in existing_members.items():
            if pid not in incoming_ids:
                db.delete(row)

        upserted += 1

    db.commit()
    return {"upserted": upserted}


# ===========================================================================
# 7. takeovers
# ===========================================================================

@router.get("/api/bridge/takeovers")
def bridge_takeovers(
    db: Annotated[Session, Depends(get_db)],
    bridge: BridgeDep,
):
    """Return conversations currently flipped to takeover=true for this
    bridge. Bridge uses this to decide which messages to forward to Studio
    for AI reply pipeline.
    """
    rows = (
        db.query(
            Conversation.inbox_id,
            Conversation.platform_conversation_id,
        )
        .join(Inbox, Inbox.id == Conversation.inbox_id)
        .filter(
            Inbox.bridge_id == bridge.id,
            Conversation.takeover.is_(True),
            Conversation.status == ConversationStatus.ACTIVE,
        )
        .all()
    )
    return {
        "takeovers": [
            {
                "inbox_id": inbox_id,
                "platform_conversation_id": pcid,
            }
            for inbox_id, pcid in rows
        ]
    }
