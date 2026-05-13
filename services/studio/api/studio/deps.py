"""FastAPI dependencies, auth helpers, ownership checks, and ID generation."""

from datetime import timedelta
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from studio.auth_utils import hash_password, hash_token, new_session_token, verify_password
from studio.db import get_db, utc_now
from studio.enums import AccountRole, AccountStatus, BridgeStatus
from studio.models import Account, AuthSession, Bridge, BridgeSession, Inbox, Persona, ProviderConfig


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


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
    role: AccountRole,
) -> Account:
    username = username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if not password:
        raise HTTPException(status_code=400, detail="密码不能为空")
    existing = db.query(Account).filter(Account.username == username).first()
    if existing:
        raise HTTPException(status_code=409, detail="用户名已存在")
    now = utc_now()
    created = Account(
        id=new_id("acc"),
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
        status=AccountStatus.ACTIVE,
        created_at=now,
        updated_at=now,
        last_login_at=None,
    )
    db.add(created)
    return created


def create_auth_session(db: Session, account: Account) -> str:
    token = new_session_token()
    now = utc_now()
    expires_at = now + timedelta(hours=24)
    db.add(AuthSession(
        id=hash_token(token), account_id=account.id,
        expires_at=expires_at, created_at=now, last_seen_at=now,
    ))
    account.last_login_at = now
    account.updated_at = now
    return token


# ---------------------------------------------------------------------------
# FastAPI dependency: authenticated web user
# ---------------------------------------------------------------------------

def get_account(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> Account:
    token = extract_bearer(authorization)
    s = db.query(AuthSession).filter(AuthSession.id == hash_token(token)).first()
    if not s:
        raise HTTPException(status_code=401, detail="登录已失效")
    if s.expires_at is not None and s.expires_at < utc_now():
        db.query(AuthSession).filter(AuthSession.id == s.id).delete()
        db.commit()
        raise HTTPException(status_code=401, detail="登录已超时")
    account = db.query(Account).filter(Account.id == s.account_id).first()
    if not account or account.status != AccountStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="登录已失效")
    now = utc_now()
    s.last_seen_at = now
    s.expires_at = now + timedelta(hours=24)
    db.commit()
    return account


def is_admin(account: Account) -> bool:
    return account.role == AccountRole.ADMIN


def require_admin(account: Account) -> Account:
    if not is_admin(account):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return account


CurrentAccountDep = Annotated[Account, Depends(get_account)]


def _admin_dep(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> Account:
    account = get_account(db, authorization)
    return require_admin(account)


AdminAccountDep = Annotated[Account, Depends(_admin_dep)]


# ---------------------------------------------------------------------------
# FastAPI dependency: authenticated bridge daemon
# ---------------------------------------------------------------------------

def get_authed_bridge(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> Bridge:
    token = extract_bearer(authorization)
    session = db.query(BridgeSession).filter(BridgeSession.id == hash_token(token)).first()
    if not session:
        raise HTTPException(status_code=401, detail="无效的 bridge 令牌")
    bridge = db.query(Bridge).filter(Bridge.id == session.bridge_id).first()
    if not bridge or bridge.status == BridgeStatus.REVOKED:
        raise HTTPException(status_code=401, detail="bridge 已被撤销")
    session.last_seen_at = utc_now()
    db.commit()
    return bridge


BridgeDep = Annotated[Bridge, Depends(get_authed_bridge)]


# ---------------------------------------------------------------------------
# Ownership helpers
# ---------------------------------------------------------------------------

DbDep = Annotated[Session, Depends(get_db)]


def get_provider_or_404(db: Session, provider_id: str) -> ProviderConfig:
    p = db.query(ProviderConfig).filter(ProviderConfig.id == provider_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Provider Config 不存在")
    return p


def get_account_persona(db: Session, account: Account, persona_id: str) -> Persona:
    query = db.query(Persona).filter(Persona.id == persona_id)
    if not is_admin(account):
        query = query.filter(Persona.account_id == account.id)
    p = query.first()
    if not p:
        raise HTTPException(status_code=404, detail="Persona 不存在")
    return p


def get_account_bridge(db: Session, account: Account, bridge_id: str) -> Bridge:
    query = db.query(Bridge).filter(Bridge.id == bridge_id)
    if not is_admin(account):
        query = query.filter(Bridge.account_id == account.id)
    b = query.first()
    if not b:
        raise HTTPException(status_code=404, detail="Bridge 不存在")
    return b


def get_account_inbox(db: Session, account: Account, inbox_id: str) -> Inbox:
    query = db.query(Inbox).filter(Inbox.id == inbox_id)
    if not is_admin(account):
        query = query.filter(Inbox.account_id == account.id)
    i = query.first()
    if not i:
        raise HTTPException(status_code=404, detail="Inbox 不存在")
    return i


def get_account_contact(db: Session, account: Account, contact_id: str):
    from studio.models import Contact
    query = db.query(Contact).join(Inbox, Inbox.id == Contact.inbox_id).filter(Contact.id == contact_id)
    if not is_admin(account):
        query = query.filter(Inbox.account_id == account.id)
    c = query.first()
    if not c:
        raise HTTPException(status_code=404, detail="Contact 不存在")
    return c
