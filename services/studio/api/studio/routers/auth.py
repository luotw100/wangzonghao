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
)
from studio.enums import AccountRole, AccountStatus
from studio.models import Account, AuthSession
from studio.schemas import LoginRequest, OwnPasswordChange
from studio.serializers import s_account

router = APIRouter()


@router.get("/api/health")
def health():
    return {"status": "ok"}


@router.post("/api/auth/login")
def login(login_in: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    a = db.query(Account).filter(Account.username == login_in.username).first()
    if not a or a.status != AccountStatus.ACTIVE or not verify_password(login_in.password, a.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_auth_session(db, a)
    db.commit()
    db.refresh(a)
    return {"token": token, "account": s_account(a)}


@router.post("/api/auth/logout")
def logout(account: CurrentAccountDep, db: Annotated[Session, Depends(get_db)], authorization: Annotated[Optional[str], Header()] = None):
    token = extract_bearer(authorization)
    db.query(AuthSession).filter(AuthSession.id == hash_token(token)).delete(synchronize_session=False)
    db.commit()
    return {"status": "ok"}


@router.get("/api/auth/me")
def me(account: CurrentAccountDep):
    return s_account(account)


@router.put("/api/auth/password")
def change_own_password(payload: OwnPasswordChange, account: CurrentAccountDep, db: Annotated[Session, Depends(get_db)]):
    if not verify_password(payload.current_password, account.password_hash):
        raise HTTPException(status_code=400, detail="当前密码错误")
    account.password_hash = hash_password(payload.new_password)
    account.updated_at = utc_now()
    db.query(AuthSession).filter(AuthSession.account_id == account.id).delete(synchronize_session=False)
    db.commit()
    return {"status": "updated"}
