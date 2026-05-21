from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request

from chat.auth_utils import hash_password, hash_token, new_session_token, verify_password
from chat.db import utc_now
from chat.deps import AuthSessionDep, CurrentAccountDep, DbDep
from chat.enums import AccountStatus, CommandStatus
from chat.limiter import limiter
from chat.models import Account, AuthSession
from chat.schemas import (
    AccountRead,
    AccountUpdate,
    LoginRequest,
    LoginResponse,
    StatusResponse,
)


router = APIRouter(prefix="/api/auth", tags=["auth"])

# 让用户不存在的登录路径耗时与存在路径接近，避免用户名枚举。
_DUMMY_PASSWORD_HASH = hash_password("__dummy_for_timing__")


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login(request: Request, login_in: LoginRequest, db: DbDep) -> LoginResponse:
    """登录。

    验证用户名和密码，成功后创建一个有效期 24 小时的 session，并返回 Bearer token。
    后续所有需要鉴权的接口都需要在请求头携带 `Authorization: Bearer <token>`。
    每次成功鉴权会自动将有效期续期 24 小时。
    账号被禁用（status=disabled）时即使密码正确也会拒绝登录。
    单 IP 每分钟最多尝试 5 次。
    """
    account = db.query(Account).filter(Account.username == login_in.username).first()
    if not account or account.status != AccountStatus.ACTIVE:
        verify_password(login_in.password, _DUMMY_PASSWORD_HASH)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(login_in.password, account.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = new_session_token()
    now = utc_now()
    auth_session = AuthSession(
        id=hash_token(token),
        account_id=account.id,
        expires_at=now + timedelta(hours=24),
        created_at=now,
    )
    account.updated_at = now
    db.add(auth_session)
    db.commit()
    db.refresh(account)
    return LoginResponse(token=token, account=AccountRead.model_validate(account))


@router.post("/logout", response_model=StatusResponse)
def logout(auth_session: AuthSessionDep, db: DbDep) -> StatusResponse:
    """退出登录。

    删除当前请求所使用的 session token，使其立即失效。
    其他设备上的 session 不受影响。
    """
    db.delete(auth_session)
    db.commit()
    return StatusResponse(status=CommandStatus.SUCCESS)


@router.get("/me", response_model=AccountRead)
def me(account: CurrentAccountDep) -> Account:
    """获取当前登录账号的详细信息。"""
    return account


@router.patch("/me", response_model=AccountRead)
def update_me(update: AccountUpdate, account: CurrentAccountDep, db: DbDep) -> Account:
    """修改当前账号资料（目前仅支持改昵称）。"""
    account.nickname = update.nickname
    account.updated_at = utc_now()
    db.commit()
    db.refresh(account)
    return account
