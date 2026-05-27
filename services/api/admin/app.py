"""Laborster Admin API.

No auth middleware here — auth is delegated to Cloudflare Access, which
verifies the user's identity at the edge before traffic reaches this service.
"""
import json
import os
import urllib.error
import urllib.request
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from studio.auth_utils import hash_password, hash_token
from studio.clients import ALLOWED_BASE_URLS
from studio.db import get_db, utc_now
from studio.deps import create_auth_session, new_id, pick_first_provider
from studio.enums import AccountStatus, HostedBridgeStatus
from studio.models import (
    Account,
    AuthSession,
    Bridge,
    Conversation,
    ConversationMember,
    DistillJob,
    HostedBridge,
    Inbox,
    LlmLog,
    Message,
    Persona,
    ProviderConfig,
)
from sqlalchemy import text as sql_text
from studio.routers.bridge_protocol import ensure_bridge_row

BRIDGE_HOST_URL = os.environ.get("BRIDGE_HOST_URL", "http://bridge-host:23458")
BRIDGE_HOST_STUDIO_URL = os.environ.get("BRIDGE_HOST_STUDIO_URL", "http://user-api:23456")

app = FastAPI(
    title="Laborster Admin API",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

DbDep = Annotated[Session, Depends(get_db)]


def _mask(key: str | None) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class AccountOut(BaseModel):
    id: str
    username: str
    display_name: str
    status: str
    distill_provider_id: str
    distill_provider_name: str
    created_at: str
    updated_at: str


class CreateAccountIn(BaseModel):
    username: str
    password: str
    display_name: str


class ResetPasswordIn(BaseModel):
    password: str


class SetDistillProviderIn(BaseModel):
    provider_id: str


@app.get("/api/admin/accounts", response_model=list[AccountOut])
def list_accounts(db: DbDep):
    rows = (
        db.query(Account, ProviderConfig.name)
        .join(ProviderConfig, ProviderConfig.id == Account.distill_provider_id)
        .order_by(Account.created_at.asc())
        .all()
    )
    return [
        AccountOut(
            id=a.id,
            username=a.username,
            display_name=a.display_name,
            status=a.status,
            distill_provider_id=a.distill_provider_id,
            distill_provider_name=pname,
            created_at=a.created_at.isoformat(),
            updated_at=a.updated_at.isoformat(),
        )
        for a, pname in rows
    ]


@app.post("/api/admin/accounts", response_model=AccountOut, status_code=201)
def create_account(body: CreateAccountIn, db: DbDep):
    if db.query(Account).filter(Account.username == body.username).first():
        raise HTTPException(409, "用户名已存在")
    provider = pick_first_provider(db)
    if not provider:
        raise HTTPException(409, "尚未配置任何 Provider，请先创建 Provider")
    now = utc_now()
    account = Account(
        id=new_id("acc"),
        username=body.username,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        status=AccountStatus.ACTIVE,
        distill_provider_id=provider.id,
        created_at=now,
        updated_at=now,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return AccountOut(
        id=account.id,
        username=account.username,
        display_name=account.display_name,
        status=account.status,
        distill_provider_id=account.distill_provider_id,
        distill_provider_name=provider.name,
        created_at=account.created_at.isoformat(),
        updated_at=account.updated_at.isoformat(),
    )


@app.post("/api/admin/accounts/{account_id}/reset-password", status_code=204)
def reset_password(account_id: str, body: ResetPasswordIn, db: DbDep):
    a = db.query(Account).filter(Account.id == account_id).first()
    if not a:
        raise HTTPException(404, "账号不存在")
    a.password_hash = hash_password(body.password)
    a.updated_at = utc_now()
    db.commit()


@app.patch("/api/admin/accounts/{account_id}/distill-provider", status_code=204)
def set_distill_provider(account_id: str, body: SetDistillProviderIn, db: DbDep):
    a = db.query(Account).filter(Account.id == account_id).first()
    if not a:
        raise HTTPException(404, "账号不存在")
    p = db.query(ProviderConfig).filter(ProviderConfig.id == body.provider_id).first()
    if not p:
        raise HTTPException(404, "Provider 不存在")
    a.distill_provider_id = p.id
    a.updated_at = utc_now()
    db.commit()


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class ProviderOut(BaseModel):
    id: str
    name: str
    base_url: str
    model: str
    api_key_masked: str
    created_at: str
    updated_at: str


class CreateProviderIn(BaseModel):
    name: str
    base_url: str
    api_key: str | None = None
    model: str


class UpdateProviderIn(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


def _validate_base_url(url: str) -> str:
    normalized = url.rstrip("/")
    if normalized not in ALLOWED_BASE_URLS:
        raise HTTPException(400, f"base_url 不在白名单: {url!r}")
    return normalized


def _provider_out(p: ProviderConfig) -> ProviderOut:
    return ProviderOut(
        id=p.id,
        name=p.name,
        base_url=p.base_url,
        model=p.model,
        api_key_masked=_mask(p.api_key),
        created_at=p.created_at.isoformat(),
        updated_at=p.updated_at.isoformat(),
    )


@app.get("/api/admin/providers", response_model=list[ProviderOut])
def list_providers(db: DbDep):
    return [_provider_out(p) for p in db.query(ProviderConfig).order_by(ProviderConfig.created_at.asc()).all()]


@app.get("/api/admin/allowed-base-urls", response_model=list[str])
def allowed_base_urls():
    return sorted(ALLOWED_BASE_URLS)


@app.post("/api/admin/providers", response_model=ProviderOut, status_code=201)
def create_provider(body: CreateProviderIn, db: DbDep):
    if db.query(ProviderConfig).filter(ProviderConfig.name == body.name).first():
        raise HTTPException(409, "Provider 名称已存在")
    base_url = _validate_base_url(body.base_url)
    now = utc_now()
    p = ProviderConfig(
        id=new_id("p"),
        name=body.name,
        base_url=base_url,
        api_key=body.api_key,
        model=body.model,
        created_at=now,
        updated_at=now,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _provider_out(p)


@app.patch("/api/admin/providers/{provider_id}", response_model=ProviderOut)
def update_provider(provider_id: str, body: UpdateProviderIn, db: DbDep):
    p = db.query(ProviderConfig).filter(ProviderConfig.id == provider_id).first()
    if not p:
        raise HTTPException(404, "Provider 不存在")
    if body.name is not None:
        clash = db.query(ProviderConfig).filter(
            ProviderConfig.name == body.name, ProviderConfig.id != p.id
        ).first()
        if clash:
            raise HTTPException(409, "Provider 名称已被占用")
        p.name = body.name
    if body.base_url is not None:
        p.base_url = _validate_base_url(body.base_url)
    if body.api_key is not None:
        p.api_key = body.api_key
    if body.model is not None:
        p.model = body.model
    p.updated_at = utc_now()
    db.commit()
    db.refresh(p)
    return _provider_out(p)


@app.delete("/api/admin/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: str, db: DbDep):
    p = db.query(ProviderConfig).filter(ProviderConfig.id == provider_id).first()
    if not p:
        raise HTTPException(404, "Provider 不存在")
    conv_refs = db.query(Conversation).filter(Conversation.provider_id == p.id).count()
    acct_refs = db.query(Account).filter(Account.distill_provider_id == p.id).count()
    if conv_refs or acct_refs:
        raise HTTPException(
            409,
            f"Provider 被 {conv_refs} 个 Conversation 和 {acct_refs} 个 Account 引用，请先重新分配",
        )
    db.delete(p)
    db.commit()


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

class ConversationOut(BaseModel):
    id: str
    account_username: str
    inbox_platform: str
    inbox_display_name: str
    kind: str
    display_name: str
    persona_name: str | None
    provider_id: str
    provider_name: str
    reply_policy: str
    takeover: bool
    status: str
    created_at: str


class SetConversationProviderIn(BaseModel):
    provider_id: str


@app.get("/api/admin/conversations", response_model=list[ConversationOut])
def list_conversations(db: DbDep, account: str | None = Query(default=None)):
    q = (
        db.query(
            Conversation,
            Account.username,
            Inbox.platform,
            Inbox.display_name,
            Persona.name,
            ProviderConfig.name,
        )
        .join(Inbox, Inbox.id == Conversation.inbox_id)
        .join(Account, Account.id == Inbox.account_id)
        .join(ProviderConfig, ProviderConfig.id == Conversation.provider_id)
        .outerjoin(Persona, Persona.id == Conversation.persona_id)
    )
    if account:
        a = db.query(Account).filter(Account.username == account).first()
        if not a:
            raise HTTPException(404, f"账号不存在: {account}")
        q = q.filter(Inbox.account_id == a.id)
    q = q.order_by(Account.username.asc(), Inbox.display_name.asc(), Conversation.created_at.asc())
    return [
        ConversationOut(
            id=c.id,
            account_username=uname,
            inbox_platform=platform,
            inbox_display_name=iname,
            kind=c.kind,
            display_name=c.display_name,
            persona_name=pname,
            provider_id=c.provider_id,
            provider_name=prvname,
            reply_policy=c.reply_policy,
            takeover=c.takeover,
            status=c.status,
            created_at=c.created_at.isoformat(),
        )
        for c, uname, platform, iname, pname, prvname in q.all()
    ]


@app.patch("/api/admin/conversations/{conv_id}/provider", status_code=204)
def set_conversation_provider(conv_id: str, body: SetConversationProviderIn, db: DbDep):
    c = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not c:
        raise HTTPException(404, "Conversation 不存在")
    p = db.query(ProviderConfig).filter(ProviderConfig.id == body.provider_id).first()
    if not p:
        raise HTTPException(404, "Provider 不存在")
    c.provider_id = p.id
    c.updated_at = utc_now()
    db.commit()


# ---------------------------------------------------------------------------
# Hosted bridges (dogfood chat-only)
# ---------------------------------------------------------------------------

class HostedBridgeOut(BaseModel):
    account_id: str
    username: str
    display_name: str
    status: str
    machine_id: str | None
    last_started_at: str | None
    last_error: str


def _bridge_host_call(method: str, path: str, body: dict | None = None) -> dict:
    """Talk to the in-cluster bridge-host service. Raises 502 on failure."""
    url = f"{BRIDGE_HOST_URL.rstrip('/')}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise HTTPException(502, f"bridge-host {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise HTTPException(502, f"bridge-host 不可达: {exc.reason}")


# Heartbeat is every 15s; Studio considers a bridge offline at >45s. Same
# threshold here so the admin panel matches "Studio thinks this bridge is
# alive". Pure read-side derivation — DB row remains the operator's last
# *intent*; only the displayed `status` is overwritten when reality
# disagrees, so a Restart click still makes sense.
_HOSTED_STALE_S = 45


def _hosted_out(
    account: Account,
    row: HostedBridge | None,
    bridge_seen_at,
    now,
) -> HostedBridgeOut:
    if row is None:
        return HostedBridgeOut(
            account_id=account.id,
            username=account.username,
            display_name=account.display_name,
            status=HostedBridgeStatus.STOPPED,
            machine_id=None,
            last_started_at=None,
            last_error="",
        )
    display_status = row.status
    last_error = row.last_error
    if display_status in (HostedBridgeStatus.RUNNING, HostedBridgeStatus.STARTING):
        stale = (
            bridge_seen_at is None
            or (now - bridge_seen_at).total_seconds() > _HOSTED_STALE_S
        )
        if stale:
            display_status = HostedBridgeStatus.CRASHED
            if not last_error:
                last_error = "心跳超时（>45s 未收到 heartbeat）"
    return HostedBridgeOut(
        account_id=account.id,
        username=account.username,
        display_name=account.display_name,
        status=display_status,
        machine_id=row.machine_id,
        last_started_at=row.last_started_at.isoformat() if row.last_started_at else None,
        last_error=last_error,
    )


@app.get("/api/admin/hosted-bridges", response_model=list[HostedBridgeOut])
def list_hosted_bridges(db: DbDep):
    accounts = db.query(Account).order_by(Account.created_at.asc()).all()
    rows = {r.account_id: r for r in db.query(HostedBridge).all()}
    # Pull last_seen_at for every (account_id, machine_id) pair we care
    # about in a single query — Bridge is keyed by both, so a stale
    # machine_id from a prior incarnation can't accidentally satisfy us.
    keys = {(r.account_id, r.machine_id) for r in rows.values() if r.machine_id}
    seen: dict[tuple[str, str], object] = {}
    if keys:
        for b in db.query(Bridge.account_id, Bridge.machine_id, Bridge.last_seen_at).all():
            if (b.account_id, b.machine_id) in keys:
                seen[(b.account_id, b.machine_id)] = b.last_seen_at
    now = utc_now()
    out: list[HostedBridgeOut] = []
    for a in accounts:
        row = rows.get(a.id)
        seen_at = seen.get((a.id, row.machine_id)) if row and row.machine_id else None
        out.append(_hosted_out(a, row, seen_at, now))
    return out


def _get_or_create_hosted_row(db: Session, account_id: str) -> HostedBridge:
    row = db.query(HostedBridge).filter(HostedBridge.account_id == account_id).first()
    if row is not None:
        return row
    now = utc_now()
    row = HostedBridge(
        account_id=account_id,
        status=HostedBridgeStatus.STOPPED,
        machine_id=None,
        session_id=None,
        last_started_at=None,
        last_error="",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row


def _revoke_hosted_session(db: Session, row: HostedBridge) -> None:
    """Delete just the hosted bridge's AuthSession — leaves any web /
    physical bridge sessions for the same account untouched.
    """
    if not row.session_id:
        return
    db.query(AuthSession).filter(AuthSession.id == row.session_id).delete(
        synchronize_session=False
    )
    row.session_id = None


@app.post("/api/admin/hosted-bridges/{account_id}/start", response_model=HostedBridgeOut)
def start_hosted_bridge(account_id: str, db: DbDep):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(404, "账号不存在")
    if account.status != AccountStatus.ACTIVE:
        raise HTTPException(409, "账号已禁用")

    row = _get_or_create_hosted_row(db, account.id)
    # Drop any previous session this hosted bridge held — we're about to
    # mint a fresh one. (Don't touch the user's other sessions.)
    _revoke_hosted_session(db, row)

    bridge = ensure_bridge_row(db, account.id, row.machine_id)
    token = create_auth_session(db, account)

    now = utc_now()
    row.status = HostedBridgeStatus.STARTING
    row.machine_id = bridge.machine_id
    row.session_id = hash_token(token)
    row.last_started_at = now
    row.last_error = ""
    row.updated_at = now
    db.commit()

    try:
        # Pre-flight: kill any subprocess bridge-host might still be
        # tracking for this account so /spawn never hits a 409. Makes
        # Start idempotent (effectively Restart when a stale process is
        # still alive). bridge-host /stop is a no-op when nothing is
        # tracked.
        _bridge_host_call("POST", "/stop", {"account_id": account.id})
        _bridge_host_call("POST", "/spawn", {
            "account_id": account.id,
            "token": token,
            "machine_id": bridge.machine_id,
            "studio_url": BRIDGE_HOST_STUDIO_URL,
            "display_name": account.display_name,
        })
    except HTTPException as exc:
        # bridge-host rejected spawn — roll status back, drop session.
        row = db.query(HostedBridge).filter(HostedBridge.account_id == account.id).first()
        if row:
            _revoke_hosted_session(db, row)
            row.status = HostedBridgeStatus.CRASHED
            row.last_error = str(exc.detail)[:500]
            row.updated_at = utc_now()
            db.commit()
        raise

    row = db.query(HostedBridge).filter(HostedBridge.account_id == account.id).first()
    row.status = HostedBridgeStatus.RUNNING
    row.updated_at = utc_now()
    db.commit()
    db.refresh(row)
    return _row_to_out(db, account, row)


@app.post("/api/admin/hosted-bridges/{account_id}/stop", response_model=HostedBridgeOut)
def stop_hosted_bridge(account_id: str, db: DbDep):
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(404, "账号不存在")
    row = db.query(HostedBridge).filter(HostedBridge.account_id == account.id).first()
    if row is None:
        return _hosted_out(account, None, None, utc_now())

    # Best-effort: tell bridge-host to terminate the subprocess. Even if
    # bridge-host is down or doesn't know the account, we still revoke
    # the session and mark stopped so admin isn't stuck.
    try:
        _bridge_host_call("POST", "/stop", {"account_id": account.id})
    except HTTPException as exc:
        row.last_error = f"stop warning: {exc.detail}"[:500]

    _revoke_hosted_session(db, row)
    row.status = HostedBridgeStatus.STOPPED
    row.updated_at = utc_now()
    db.commit()
    db.refresh(row)
    return _row_to_out(db, account, row)


def _row_to_out(db: Session, account: Account, row: HostedBridge) -> HostedBridgeOut:
    """Single-row variant for start/stop responses: look up the live
    Bridge.last_seen_at on the fly so the returned status reflects
    current heartbeat health, same as the list endpoint.
    """
    seen_at = None
    if row.machine_id:
        b = (
            db.query(Bridge.last_seen_at)
            .filter(Bridge.account_id == account.id, Bridge.machine_id == row.machine_id)
            .first()
        )
        if b:
            seen_at = b[0]
    return _hosted_out(account, row, seen_at, utc_now())


# ---------------------------------------------------------------------------
# Audit: chat messages + LLM trace
#
# 这一块是给运营查"bot 为什么这样"用的。所有展示字段都给人话（昵称+备注），
# UUID 仅作 id 字段保留，前端跳转/锚定用。
# ---------------------------------------------------------------------------


def _resolve_chat_peer_names(
    db: Session, conversation_rows: list[Conversation]
) -> dict[str, dict[str, str | None]]:
    """For studio conversations whose inbox is 'chat' platform, look up the
    chat sandbox contact nickname + remark by joining chat.conversations →
    chat.contacts on studio.conversations.platform_conversation_id =
    chat.conversations.id.

    Returns {studio_conv_id: {"nickname": str, "remark": str | None}}.
    Conversations not on the chat platform are absent.
    """
    if not conversation_rows:
        return {}
    chat_ids: list[tuple[str, str]] = []  # (studio_conv_id, chat_conv_id)
    inbox_ids = {c.inbox_id for c in conversation_rows}
    platforms = {
        i.id: i.platform
        for i in db.query(Inbox).filter(Inbox.id.in_(inbox_ids)).all()
    }
    for c in conversation_rows:
        if platforms.get(c.inbox_id) == "chat":
            chat_ids.append((c.id, c.platform_conversation_id))
    if not chat_ids:
        return {}
    chat_conv_ids = [cid for _, cid in chat_ids]
    rows = db.execute(
        sql_text(
            "SELECT cv.id AS cv_id, ct.nickname, ct.remark_name "
            "FROM chat.conversations cv "
            "JOIN chat.contacts ct ON ct.id = cv.contact_id "
            "WHERE cv.id = ANY(:ids)"
        ),
        {"ids": chat_conv_ids},
    ).all()
    by_chat = {r.cv_id: (r.nickname, r.remark_name) for r in rows}
    out: dict[str, dict[str, str | None]] = {}
    for studio_id, chat_id in chat_ids:
        pair = by_chat.get(chat_id)
        if not pair:
            continue
        nickname, remark = pair
        out[studio_id] = {"nickname": nickname, "remark": remark}
    return out


def _peer_display(conv: Conversation, chat_peer: dict[str, str | None] | None) -> str:
    """Friendly DM peer label: '昵称 (备注)' for chat sandbox if remark set,
    otherwise the studio-side display_name (which is the platform-side nick)."""
    if chat_peer:
        nickname = chat_peer.get("nickname") or conv.display_name
        remark = chat_peer.get("remark")
        if remark and remark != nickname:
            return f"{nickname}（{remark}）"
        return nickname
    return conv.display_name


# ----- /api/admin/chats -----

class ChatConversationOut(BaseModel):
    id: str
    account_id: str
    account_username: str
    inbox_id: str
    inbox_display_name: str
    inbox_platform: str
    kind: str
    peer_display: str
    persona_id: str | None
    persona_name: str | None
    takeover: bool
    reply_policy: str
    updated_at: str


@app.get("/api/admin/chats", response_model=list[ChatConversationOut])
def list_chats(db: DbDep, account_id: str | None = Query(default=None)):
    q = (
        db.query(Conversation, Account, Inbox, Persona)
        .join(Inbox, Inbox.id == Conversation.inbox_id)
        .join(Account, Account.id == Inbox.account_id)
        .outerjoin(Persona, Persona.id == Conversation.persona_id)
    )
    if account_id:
        q = q.filter(Account.id == account_id)
    q = q.order_by(Account.username.asc(), Inbox.display_name.asc(), Conversation.updated_at.desc())
    rows = q.all()
    convs = [c for c, _, _, _ in rows]
    chat_peers = _resolve_chat_peer_names(db, convs)
    return [
        ChatConversationOut(
            id=c.id,
            account_id=a.id,
            account_username=a.username,
            inbox_id=i.id,
            inbox_display_name=i.display_name,
            inbox_platform=i.platform,
            kind=c.kind,
            peer_display=_peer_display(c, chat_peers.get(c.id)),
            persona_id=p.id if p else None,
            persona_name=p.name if p else None,
            takeover=c.takeover,
            reply_policy=c.reply_policy,
            updated_at=c.updated_at.isoformat(),
        )
        for c, a, i, p in rows
    ]


class ChatMessageOut(BaseModel):
    id: int
    ts: str
    direction: str            # 'self' | 'peer'
    sender_display: str
    msg_type: str
    content: str              # text payload or storage key
    llm_log_id: int | None    # only present for self messages produced by reply LLM


@app.get("/api/admin/chats/{conversation_id}/messages", response_model=list[ChatMessageOut])
def list_chat_messages(
    conversation_id: str,
    db: DbDep,
    limit: int = Query(default=200, ge=1, le=1000),
    before_id: int | None = Query(default=None),
):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(404, "Conversation 不存在")
    inbox = db.query(Inbox).filter(Inbox.id == conv.inbox_id).first()
    chat_peers = _resolve_chat_peer_names(db, [conv])
    peer_label = _peer_display(conv, chat_peers.get(conv.id))
    self_label = inbox.display_name if inbox else "(self)"

    # Group members for group chats — only needed if kind=group
    members = {}
    if conv.kind == "group":
        for m in db.query(ConversationMember).filter(
            ConversationMember.conversation_id == conv.id
        ).all():
            members[m.peer_platform_id] = m.display_name

    q = db.query(Message).filter(Message.conversation_id == conv.id)
    if before_id is not None:
        q = q.filter(Message.id < before_id)
    # Fetch newest first then reverse — gives a stable "latest N" window with cursor paging.
    rows = (
        q.order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()

    # Build sender display for each row
    def _sender(m: Message) -> str:
        if m.sender_id is None:
            return self_label
        if conv.kind == "group":
            return members.get(m.sender_id, m.sender_id)
        return peer_label

    # Link self messages → their LlmLog (via outbound_message_id ↔ outbound rows
    # that originated from that conversation). We resolve by joining LlmLog where
    # conversation_id matches and ordering by created_at ASC; then walk forward
    # mapping the next assistant message to the next reply log.
    # Simpler approach: directly join via outbound_message_id → OutboundMessage.
    # OutboundMessage no longer in scope here (we show studio.messages which are
    # *delivered* and from_self via bridge inbound, not outbound). So instead we
    # correlate by (conversation_id, sender_id IS NULL) + nearest LlmLog
    # created_at <= message.timestamp + small window. Cheaper & "good enough"
    # for admin audit:
    self_msgs = [m for m in rows if m.sender_id is None]
    log_links: dict[int, int] = {}
    if self_msgs:
        log_rows = (
            db.query(LlmLog.id, LlmLog.created_at)
            .filter(
                LlmLog.purpose == "reply",
                LlmLog.conversation_id == conv.id,
                LlmLog.is_error.is_(False),
            )
            .order_by(LlmLog.created_at.asc())
            .all()
        )
        # Greedy nearest-forward match: for each self msg in ts order, pick the
        # latest log whose created_at <= msg.timestamp + 90s (covers typing delay).
        from datetime import timedelta as _td
        log_iter = list(log_rows)
        i = 0
        for m in sorted(self_msgs, key=lambda x: x.timestamp):
            while i + 1 < len(log_iter) and log_iter[i + 1][1] <= m.timestamp + _td(seconds=90):
                i += 1
            if i < len(log_iter):
                log_id, log_ts = log_iter[i]
                if log_ts <= m.timestamp + _td(seconds=90) and log_ts >= m.timestamp - _td(minutes=5):
                    log_links[m.id] = log_id

    return [
        ChatMessageOut(
            id=m.id,
            ts=m.timestamp.isoformat(),
            direction="self" if m.sender_id is None else "peer",
            sender_display=_sender(m),
            msg_type=m.msg_type,
            content=m.content,
            llm_log_id=log_links.get(m.id),
        )
        for m in rows
    ]


# ----- /api/admin/llm-logs -----

class LlmLogSummary(BaseModel):
    id: int
    purpose: str
    created_at: str
    model: str | None
    latency_ms: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    is_error: bool | None
    account_username: str | None
    inbox_display_name: str | None
    persona_name: str | None
    conversation_peer_display: str | None
    conversation_id: str | None
    distill_job_id: str | None
    window_index: int | None
    windows_total: int | None


def _summary_enrich(
    db: Session, logs: list[LlmLog]
) -> dict[int, dict]:
    """Resolve human-readable names for a batch of LlmLog rows."""
    conv_ids = {l.conversation_id for l in logs if l.conversation_id}
    persona_ids = {l.persona_id for l in logs if l.persona_id}
    inbox_ids = {l.inbox_id for l in logs if l.inbox_id}

    convs = {c.id: c for c in db.query(Conversation).filter(Conversation.id.in_(conv_ids)).all()} if conv_ids else {}
    chat_peers = _resolve_chat_peer_names(db, list(convs.values()))
    personas = {p.id: p for p in db.query(Persona).filter(Persona.id.in_(persona_ids)).all()} if persona_ids else {}
    inboxes = {i.id: i for i in db.query(Inbox).filter(Inbox.id.in_(inbox_ids)).all()} if inbox_ids else {}
    account_ids = {i.account_id for i in inboxes.values()}
    accounts = {a.id: a for a in db.query(Account).filter(Account.id.in_(account_ids)).all()} if account_ids else {}

    out: dict[int, dict] = {}
    for l in logs:
        inbox = inboxes.get(l.inbox_id) if l.inbox_id else None
        conv = convs.get(l.conversation_id) if l.conversation_id else None
        persona = personas.get(l.persona_id) if l.persona_id else None
        out[l.id] = {
            "account_username": (
                accounts[inbox.account_id].username if inbox and inbox.account_id in accounts else None
            ),
            "inbox_display_name": inbox.display_name if inbox else None,
            "persona_name": persona.name if persona else None,
            "conversation_peer_display": _peer_display(conv, chat_peers.get(conv.id)) if conv else None,
        }
    return out


@app.get("/api/admin/llm-logs", response_model=list[LlmLogSummary])
def list_llm_logs(
    db: DbDep,
    account_id: str | None = Query(default=None),
    persona_id: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
    distill_job_id: str | None = Query(default=None),
    purpose: str | None = Query(default=None),
    is_error: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    before_id: int | None = Query(default=None),
):
    q = db.query(LlmLog)
    if account_id:
        # account → inbox_ids → filter
        ibs = [i.id for i in db.query(Inbox.id).filter(Inbox.account_id == account_id).all()]
        if not ibs:
            return []
        q = q.filter(LlmLog.inbox_id.in_(ibs))
    if persona_id:
        q = q.filter(LlmLog.persona_id == persona_id)
    if conversation_id:
        q = q.filter(LlmLog.conversation_id == conversation_id)
    if distill_job_id:
        q = q.filter(LlmLog.distill_job_id == distill_job_id)
    if purpose:
        q = q.filter(LlmLog.purpose == purpose)
    if is_error is not None:
        q = q.filter(LlmLog.is_error.is_(is_error))
    if before_id is not None:
        q = q.filter(LlmLog.id < before_id)
    rows = q.order_by(LlmLog.id.desc()).limit(limit).all()
    enrich = _summary_enrich(db, rows)
    return [
        LlmLogSummary(
            id=l.id,
            purpose=l.purpose,
            created_at=l.created_at.isoformat(),
            model=l.model,
            latency_ms=l.latency_ms,
            prompt_tokens=l.prompt_tokens,
            completion_tokens=l.completion_tokens,
            is_error=l.is_error,
            account_username=enrich[l.id]["account_username"],
            inbox_display_name=enrich[l.id]["inbox_display_name"],
            persona_name=enrich[l.id]["persona_name"],
            conversation_peer_display=enrich[l.id]["conversation_peer_display"],
            conversation_id=l.conversation_id,
            distill_job_id=l.distill_job_id,
            window_index=l.window_index,
            windows_total=l.windows_total,
        )
        for l in rows
    ]


class LlmLogDetail(LlmLogSummary):
    request_messages: list[dict]
    response_raw: str
    persona_md_snapshot: str | None
    card_md_snapshot: str | None
    persona_md_after: str | None
    card_md_after: str | None
    outbound_message_id: int | None


@app.get("/api/admin/llm-logs/{log_id}", response_model=LlmLogDetail)
def get_llm_log(log_id: int, db: DbDep):
    l = db.query(LlmLog).filter(LlmLog.id == log_id).first()
    if not l:
        raise HTTPException(404, "LlmLog 不存在")
    enrich = _summary_enrich(db, [l])[l.id]
    try:
        req = json.loads(l.request_messages)
    except Exception:
        req = [{"role": "raw", "content": l.request_messages}]
    return LlmLogDetail(
        id=l.id,
        purpose=l.purpose,
        created_at=l.created_at.isoformat(),
        model=l.model,
        latency_ms=l.latency_ms,
        prompt_tokens=l.prompt_tokens,
        completion_tokens=l.completion_tokens,
        is_error=l.is_error,
        account_username=enrich["account_username"],
        inbox_display_name=enrich["inbox_display_name"],
        persona_name=enrich["persona_name"],
        conversation_peer_display=enrich["conversation_peer_display"],
        conversation_id=l.conversation_id,
        distill_job_id=l.distill_job_id,
        window_index=l.window_index,
        windows_total=l.windows_total,
        request_messages=req,
        response_raw=l.response_raw,
        persona_md_snapshot=l.persona_md_snapshot,
        card_md_snapshot=l.card_md_snapshot,
        persona_md_after=l.persona_md_after,
        card_md_after=l.card_md_after,
        outbound_message_id=l.outbound_message_id,
    )


# ----- /api/admin/distill-jobs -----

class DistillJobSummary(BaseModel):
    id: str
    account_id: str
    account_username: str
    persona_id: str | None
    persona_name: str | None
    provider_name: str
    status: str
    conversation_count: int
    progress: dict
    error_message: str
    created_at: str


@app.get("/api/admin/distill-jobs", response_model=list[DistillJobSummary])
def list_distill_jobs(db: DbDep, account_id: str | None = Query(default=None), limit: int = Query(default=50, ge=1, le=200)):
    q = (
        db.query(DistillJob, Account, ProviderConfig, Persona)
        .join(Account, Account.id == DistillJob.account_id)
        .join(ProviderConfig, ProviderConfig.id == DistillJob.provider_config_id)
        .outerjoin(Persona, Persona.id == DistillJob.target_persona_id)
    )
    if account_id:
        q = q.filter(DistillJob.account_id == account_id)
    rows = q.order_by(DistillJob.created_at.desc()).limit(limit).all()
    return [
        DistillJobSummary(
            id=j.id,
            account_id=a.id,
            account_username=a.username,
            persona_id=p.id if p else None,
            persona_name=p.name if p else None,
            provider_name=pc.name,
            status=j.status,
            conversation_count=len(j.conversation_ids or []),
            progress=j.progress or {},
            error_message=j.error_message,
            created_at=j.created_at.isoformat(),
        )
        for j, a, pc, p in rows
    ]


class DistillFoldRow(BaseModel):
    log_id: int
    conversation_id: str
    conversation_peer_display: str
    window_index: int | None
    windows_total: int | None
    latency_ms: int | None
    is_error: bool | None
    persona_changed: bool
    card_changed: bool
    created_at: str


class DistillJobDetail(DistillJobSummary):
    folds: list[DistillFoldRow]


@app.get("/api/admin/distill-jobs/{job_id}", response_model=DistillJobDetail)
def get_distill_job(job_id: str, db: DbDep):
    row = (
        db.query(DistillJob, Account, ProviderConfig, Persona)
        .join(Account, Account.id == DistillJob.account_id)
        .join(ProviderConfig, ProviderConfig.id == DistillJob.provider_config_id)
        .outerjoin(Persona, Persona.id == DistillJob.target_persona_id)
        .filter(DistillJob.id == job_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "DistillJob 不存在")
    j, a, pc, p = row

    logs = (
        db.query(LlmLog)
        .filter(LlmLog.distill_job_id == j.id)
        .order_by(LlmLog.conversation_id.asc(), LlmLog.window_index.asc(), LlmLog.id.asc())
        .all()
    )
    conv_ids = {l.conversation_id for l in logs if l.conversation_id}
    convs = {c.id: c for c in db.query(Conversation).filter(Conversation.id.in_(conv_ids)).all()} if conv_ids else {}
    chat_peers = _resolve_chat_peer_names(db, list(convs.values()))

    folds = [
        DistillFoldRow(
            log_id=l.id,
            conversation_id=l.conversation_id or "",
            conversation_peer_display=(
                _peer_display(convs[l.conversation_id], chat_peers.get(l.conversation_id))
                if l.conversation_id and l.conversation_id in convs else "(已删除会话)"
            ),
            window_index=l.window_index,
            windows_total=l.windows_total,
            latency_ms=l.latency_ms,
            is_error=l.is_error,
            persona_changed=l.persona_md_after is not None
                and (l.persona_md_after or "") != (l.persona_md_snapshot or ""),
            card_changed=l.card_md_after is not None
                and (l.card_md_after or "") != (l.card_md_snapshot or ""),
            created_at=l.created_at.isoformat(),
        )
        for l in logs
    ]
    return DistillJobDetail(
        id=j.id,
        account_id=a.id,
        account_username=a.username,
        persona_id=p.id if p else None,
        persona_name=p.name if p else None,
        provider_name=pc.name,
        status=j.status,
        conversation_count=len(j.conversation_ids or []),
        progress=j.progress or {},
        error_message=j.error_message,
        created_at=j.created_at.isoformat(),
        folds=folds,
    )


# ----- /api/admin/personas/{id}/timeline -----

class PersonaTimelineEntry(BaseModel):
    log_id: int
    distill_job_id: str | None
    conversation_id: str | None
    conversation_peer_display: str | None
    window_index: int | None
    windows_total: int | None
    persona_md_before: str | None
    persona_md_after: str | None
    created_at: str


@app.get("/api/admin/personas", response_model=list[dict])
def list_personas(db: DbDep):
    """Flat list of personas with account label, for the timeline picker."""
    rows = (
        db.query(Persona, Account)
        .join(Account, Account.id == Persona.account_id)
        .order_by(Account.username.asc(), Persona.name.asc())
        .all()
    )
    return [
        {
            "id": p.id,
            "name": p.name,
            "account_id": a.id,
            "account_username": a.username,
        }
        for p, a in rows
    ]


@app.get("/api/admin/personas/{persona_id}/timeline", response_model=list[PersonaTimelineEntry])
def persona_timeline(persona_id: str, db: DbDep, limit: int = Query(default=200, ge=1, le=1000)):
    persona = db.query(Persona).filter(Persona.id == persona_id).first()
    if not persona:
        raise HTTPException(404, "Persona 不存在")
    logs = (
        db.query(LlmLog)
        .filter(
            LlmLog.purpose == "distill",
            LlmLog.persona_id == persona_id,
            LlmLog.persona_md_after.is_not(None),
        )
        .order_by(LlmLog.created_at.desc())
        .limit(limit)
        .all()
    )
    conv_ids = {l.conversation_id for l in logs if l.conversation_id}
    convs = {c.id: c for c in db.query(Conversation).filter(Conversation.id.in_(conv_ids)).all()} if conv_ids else {}
    chat_peers = _resolve_chat_peer_names(db, list(convs.values()))
    return [
        PersonaTimelineEntry(
            log_id=l.id,
            distill_job_id=l.distill_job_id,
            conversation_id=l.conversation_id,
            conversation_peer_display=(
                _peer_display(convs[l.conversation_id], chat_peers.get(l.conversation_id))
                if l.conversation_id and l.conversation_id in convs else None
            ),
            window_index=l.window_index,
            windows_total=l.windows_total,
            persona_md_before=l.persona_md_snapshot,
            persona_md_after=l.persona_md_after,
            created_at=l.created_at.isoformat(),
        )
        for l in logs
    ]
