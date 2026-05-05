"""Auth primitives: code generation, hashing, session token, FastAPI dependencies."""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import timedelta
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from robot.db import get_db, utc_now
from robot.models import Account, AuthSession, LoginCode

logger = logging.getLogger(__name__)


# --- Constants ---

CODE_LENGTH = 6
CODE_TTL = timedelta(minutes=5)
CODE_MAX_ATTEMPTS = 5
RESEND_INTERVAL = timedelta(seconds=60)
DAILY_REQUEST_LIMIT_PER_EMAIL = 10

SESSION_COOKIE_NAME = "robot_session"
SESSION_TTL = timedelta(days=30)


# --- Hashing ---

def hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_code() -> str:
    """Cryptographically random 6-digit string."""
    return f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"


def generate_session_token() -> str:
    """48 random bytes, urlsafe-encoded — used as the cookie value."""
    return secrets.token_urlsafe(48)


# --- Rate-limit helpers (called from endpoints, not dependencies) ---

class RateLimitError(Exception):
    pass


def check_request_code_rate_limits(db: Session, identifier: str) -> None:
    """Raise RateLimitError if too many recent codes for this identifier."""
    now = utc_now()
    last = (
        db.query(LoginCode)
        .filter(LoginCode.identifier == identifier)
        .order_by(LoginCode.id.desc())
        .first()
    )
    if last and (now - last.created_at) < RESEND_INTERVAL:
        wait = int(RESEND_INTERVAL.total_seconds() - (now - last.created_at).total_seconds())
        raise RateLimitError(f"请求过于频繁，请 {wait} 秒后再试")

    one_day_ago = now - timedelta(days=1)
    count_today = (
        db.query(LoginCode)
        .filter(LoginCode.identifier == identifier, LoginCode.created_at >= one_day_ago)
        .count()
    )
    if count_today >= DAILY_REQUEST_LIMIT_PER_EMAIL:
        raise RateLimitError("今日验证码请求次数过多，请明天再试")


# --- Session lifecycle ---

def issue_session(
    db: Session,
    *,
    account_id: str,
    user_agent: Optional[str],
    ip: Optional[str],
) -> tuple[str, AuthSession]:
    """Create a new auth session and return (raw token, db row). Cookie should hold the raw token."""
    token = generate_session_token()
    now = utc_now()
    auth_session = AuthSession(
        id=hash_token(token),
        account_id=account_id,
        expires_at=now + SESSION_TTL,
        last_seen_at=now,
        user_agent=user_agent[:255] if user_agent else None,
        ip=ip,
        created_at=now,
    )
    db.add(auth_session)
    db.flush()
    return token, auth_session


def revoke_session_by_token(db: Session, token: str) -> None:
    h = hash_token(token)
    s = db.query(AuthSession).filter(AuthSession.id == h).first()
    if s and s.revoked_at is None:
        s.revoked_at = utc_now()
        db.commit()


def set_session_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
    )


# --- FastAPI dependencies ---

def get_current_account(
    request: Request,
    robot_session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> Account:
    """Resolve the current account from the session cookie, or 401."""
    if not robot_session:
        raise HTTPException(status_code=401, detail="未登录")
    s = (
        db.query(AuthSession)
        .filter(AuthSession.id == hash_token(robot_session))
        .first()
    )
    now = utc_now()
    if not s or s.revoked_at is not None or s.expires_at < now:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    account = db.query(Account).filter(Account.id == s.account_id).first()
    if not account:
        raise HTTPException(status_code=401, detail="账号不存在")
    if account.status == "disabled":
        raise HTTPException(status_code=403, detail="账号已被停用")
    if account.status == "pending":
        raise HTTPException(status_code=403, detail="账号待审批，请等待管理员通过")
    s.last_seen_at = now
    db.commit()
    request.state.current_account = account
    return account


def require_admin(account: Account = Depends(get_current_account)) -> Account:
    if account.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问")
    return account


# --- Allowed email lookup ---

def is_admin_email(email: str, admin_emails: list[str]) -> bool:
    e = email.strip().lower()
    return e in {x.strip().lower() for x in admin_emails if x.strip()}


def revoke_all_sessions_for_account(db: Session, account_id: str) -> None:
    now = utc_now()
    db.query(AuthSession).filter(
        AuthSession.account_id == account_id,
        AuthSession.revoked_at.is_(None),
    ).update({"revoked_at": now}, synchronize_session=False)
    db.commit()


def new_account_id() -> str:
    return f"acc_{uuid.uuid4().hex[:8]}"


def new_identity_id() -> str:
    return f"ai_{uuid.uuid4().hex[:8]}"
