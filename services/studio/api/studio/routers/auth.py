"""Health check and auth endpoints."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from studio.auth_utils import hash_password, verify_password
from studio.db import get_db, utc_now
from studio.deps import (
    AdminAccountDep,
    CurrentAccountDep,
    create_account_record,
    create_auth_session,
    extract_bearer,
    hash_token,
    revoke_account_sessions,
)
from studio.enums import AccountRole, AccountStatus
from studio.models import Account, AuthSession
from studio.schemas import LoginRequest, OwnPasswordChange
from studio.serializers import s_account

router = APIRouter()


@router.get("/api/health")
def health():
    """健康检查。返回 `{"status": "ok"}`，可用于负载均衡探活。"""
    return {"status": "ok"}


@router.post("/api/auth/login")
def login(login_in: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    """登录。

    验证用户名和密码，成功后创建 session 并返回 Bearer token 和账号信息。
    后续所有需要鉴权的接口在 Header 中携带 `Authorization: Bearer <token>`。
    账号被禁用（status=disabled）时即使密码正确也会拒绝。
    """
    a = db.query(Account).filter(Account.username == login_in.username).first()
    if not a or a.status != AccountStatus.ACTIVE or not verify_password(login_in.password, a.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_auth_session(db, a)
    db.commit()
    db.refresh(a)
    return {"token": token, "account": s_account(a)}


@router.post("/api/auth/logout")
def logout(account: CurrentAccountDep, db: Annotated[Session, Depends(get_db)], authorization: Annotated[Optional[str], Header()] = None):
    """退出登录。销毁当前 token 对应的 session，立即失效。其他设备的 session 不受影响。"""
    token = extract_bearer(authorization)
    db.query(AuthSession).filter(AuthSession.id == hash_token(token)).delete(synchronize_session=False)
    db.commit()
    return {"status": "ok"}


@router.get("/api/auth/me")
def me(account: CurrentAccountDep):
    """获取当前登录账号的信息。"""
    return s_account(account)


@router.put("/api/auth/password")
def change_own_password(payload: OwnPasswordChange, account: CurrentAccountDep, db: Annotated[Session, Depends(get_db)]):
    """修改自己的密码。需要验证当前密码。修改成功后，当前账号所有设备的 session 全部立即失效，需重新登录。"""
    if not verify_password(payload.current_password, account.password_hash):
        raise HTTPException(status_code=400, detail="当前密码错误")
    account.password_hash = hash_password(payload.new_password)
    account.updated_at = utc_now()
    revoke_account_sessions(db, account.id)
    db.commit()
    return {"status": "updated"}
