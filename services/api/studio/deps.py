"""FastAPI 依赖注入、鉴权辅助、资源归属校验、ID 生成。

核心依赖：
  CurrentAccountDep — 从 Authorization: Bearer <token> 解析当前 Web 用户，滑动续期 24h
  BridgeDep         — 从 Authorization + X-Machine-Id 解析当前 Bridge daemon，同一 session 表

所有 get_account_* 辅助函数在校验 account_id 归属的同时做 404 处理，
路由层直接调用，不需要额外的权限检查。
"""

from datetime import timedelta
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from studio.auth_utils import hash_password, hash_token, new_session_token, verify_password
from studio.db import get_db, utc_now
from studio.enums import AccountStatus
from studio.models import Account, AuthSession, Bridge, Inbox, Persona, ProviderConfig


# A bridge is "online" if its last_seen_at was refreshed within this many
# seconds. Heartbeat cadence is 15s, so 45s = 3 missed beats. Used by the
# inbox-ownership mutex (bridge_protocol).
BRIDGE_OFFLINE_S = 45


# Web session lifetime, refreshed on use (sliding expiry). To avoid a DB
# write + commit on every authenticated request — which serialized all read
# traffic on the session row — the expiry is advanced only when it would move
# forward by at least SESSION_RENEW_INTERVAL, i.e. at most one write per minute
# per session. Expiry stays accurate to within that interval, so an idle user
# is logged out at most ~1 min early.
SESSION_TTL = timedelta(hours=24)
SESSION_RENEW_INTERVAL = timedelta(minutes=1)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def pick_first_provider(db: Session) -> Optional[ProviderConfig]:
    """The seed provider used when a new account / contact needs a provider id.

    Returns the earliest-created ProviderConfig, or None if the pool is empty.
    Callers decide how to surface "no provider configured" (CLI: SystemExit,
    HTTP routers: HTTPException, bridge auto-create: 409).
    """
    return db.query(ProviderConfig).order_by(ProviderConfig.created_at.asc()).first()


def extract_bearer(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少令牌"
        )
    return authorization.removeprefix("Bearer ").strip()


def create_account_record(
    db: Session,
    *,
    username: str,
    password: str,
    display_name: Optional[str],
) -> Account:
    username = username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if not password:
        raise HTTPException(status_code=400, detail="密码不能为空")
    existing = db.query(Account).filter(Account.username == username).first()
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")
    provider = pick_first_provider(db)
    if not provider:
        raise HTTPException(status_code=409, detail="尚未配置任何 Provider，无法创建账号")
    now = utc_now()
    created = Account(
        id=new_id("acc"),
        username=username,
        password_hash=hash_password(password),
        display_name=display_name or username,
        status=AccountStatus.ACTIVE,
        distill_provider_id=provider.id,
        created_at=now,
        updated_at=now,
    )
    db.add(created)
    return created


def create_auth_session(db: Session, account: Account) -> str:
    token = new_session_token()
    now = utc_now()
    db.add(AuthSession(
        id=hash_token(token), account_id=account.id,
        expires_at=now + SESSION_TTL, created_at=now,
    ))
    return token


def revoke_account_sessions(db: Session, account_id: str) -> None:
    """Kill every session for an account — web and bridge alike.

    The single security control under sliding expiry. Called on password
    change.
    """
    db.query(AuthSession).filter(
        AuthSession.account_id == account_id
    ).delete(synchronize_session=False)


# ---------------------------------------------------------------------------
# FastAPI dependency: authenticated web user
# ---------------------------------------------------------------------------

def resolve_account_from_token(db: Session, raw_token: str) -> Account:
    """Look up the account for a bearer token and slide its 24h TTL on use.

    The renewal write is throttled to at most once per SESSION_RENEW_INTERVAL
    per session (see the constant) so the common case is a pure read.

    Used by both the standard ``get_account`` FastAPI dep and by chat's
    media route, which accepts a fallback ``?token=`` query parameter.
    """
    # joinedload pulls the Account in the same round-trip; without it, reading
    # s.account below fires a second lazy SELECT on every authenticated request.
    s = (
        db.query(AuthSession)
        .options(joinedload(AuthSession.account))
        .filter(AuthSession.id == hash_token(raw_token))
        .first()
    )
    if not s:
        raise HTTPException(status_code=401, detail="登录已失效")
    now = utc_now()
    if s.expires_at < now:
        db.query(AuthSession).filter(AuthSession.id == s.id).delete()
        db.commit()
        raise HTTPException(status_code=401, detail="登录已超时")
    account = s.account
    if not account or account.status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="登录已失效")
    # new_expires - expires_at == now - last_renewal (expiry == last_renewal +
    # TTL), so this writes only when the session was last renewed >= 1 min ago.
    new_expires = now + SESSION_TTL
    if new_expires - s.expires_at >= SESSION_RENEW_INTERVAL:
        s.expires_at = new_expires
        db.commit()
    return account


def get_account(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> Account:
    return resolve_account_from_token(db, extract_bearer(authorization))


CurrentAccountDep = Annotated[Account, Depends(get_account)]


# ---------------------------------------------------------------------------
# FastAPI dependency: authenticated bridge daemon
# ---------------------------------------------------------------------------

def authenticate_bridge(
    db: Session,
    authorization: Optional[str],
    x_machine_id: Optional[str],
) -> Bridge:
    """Resolve + auth a bridge daemon on a caller-supplied session.

    Split out of ``get_authed_bridge`` so long-poll endpoints can run it on a
    short-lived session that is released *before* the idle wait — otherwise the
    ``get_db`` dependency pins one pool connection for the whole 30s poll, and
    concurrent online bridges hit the PG connection ceiling. See [studio.db].
    """
    token = extract_bearer(authorization)
    # joinedload pulls the Account in the same round-trip; without it, reading
    # s.account below fires a second lazy SELECT on every bridge request (same
    # fix as resolve_account_from_token).
    s = (
        db.query(AuthSession)
        .options(joinedload(AuthSession.account))
        .filter(AuthSession.id == hash_token(token))
        .first()
    )
    if not s:
        raise HTTPException(status_code=401, detail="登录已失效")
    now = utc_now()
    if s.expires_at < now:
        db.query(AuthSession).filter(AuthSession.id == s.id).delete()
        db.commit()
        raise HTTPException(status_code=401, detail="登录已超时")
    account = s.account
    if not account or account.status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="登录已失效")
    if not x_machine_id:
        raise HTTPException(status_code=401, detail="缺少 machine 标识")
    bridge = (
        db.query(Bridge)
        .filter(Bridge.account_id == account.id, Bridge.machine_id == x_machine_id)
        .first()
    )
    if not bridge:
        raise HTTPException(status_code=401, detail="bridge 已被撤销")
    # Throttle the sliding-renewal write the same way the web path does (see
    # resolve_account_from_token): the bridge daemon hits heartbeat/takeovers/
    # outbound at a fixed cadence, so an unconditional commit here made every
    # one of those a WAL fsync. Advance expiry only when it would move forward
    # by >= SESSION_RENEW_INTERVAL, turning the common case into a pure read.
    new_expires = now + SESSION_TTL
    if new_expires - s.expires_at >= SESSION_RENEW_INTERVAL:
        s.expires_at = new_expires
        db.commit()
    return bridge


def get_authed_bridge(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
    x_machine_id: Annotated[Optional[str], Header()] = None,
) -> Bridge:
    """FastAPI dependency for non-long-poll /api/bridge/* calls (request-scoped
    session). Long-poll endpoints call ``authenticate_bridge`` directly on a
    short-lived session instead — see that function's docstring."""
    return authenticate_bridge(db, authorization, x_machine_id)


BridgeDep = Annotated[Bridge, Depends(get_authed_bridge)]


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------

DbDep = Annotated[Session, Depends(get_db)]


def get_account_persona(db: Session, account: Account, persona_id: str) -> Persona:
    query = db.query(Persona).filter(
        Persona.id == persona_id, Persona.account_id == account.id
    )
    p = query.first()
    if not p:
        raise HTTPException(status_code=404, detail="Persona 不存在")
    return p


def get_account_bridge(db: Session, account: Account, bridge_id: str) -> Bridge:
    query = db.query(Bridge).filter(
        Bridge.id == bridge_id, Bridge.account_id == account.id
    )
    b = query.first()
    if not b:
        raise HTTPException(status_code=404, detail="Bridge 不存在")
    return b


def get_account_inbox(db: Session, account: Account, inbox_id: str) -> Inbox:
    query = db.query(Inbox).filter(
        Inbox.id == inbox_id, Inbox.account_id == account.id
    )
    i = query.first()
    if not i:
        raise HTTPException(status_code=404, detail="Inbox 不存在")
    return i


def get_account_conversation(db: Session, account: Account, conversation_id: str):
    from studio.models import Conversation
    query = db.query(Conversation).join(Inbox, Inbox.id == Conversation.inbox_id).filter(
        Conversation.id == conversation_id, Inbox.account_id == account.id
    )
    c = query.first()
    if not c:
        raise HTTPException(status_code=404, detail="Conversation 不存在")
    return c
