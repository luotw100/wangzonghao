from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from chat.auth_utils import hash_token
from chat.db import get_db, utc_now
from chat.enums import AccountStatus
from chat.models import Account, AuthSession, Contact, Conversation
from chat.scoping import scoped


DbDep = Annotated[Session, Depends(get_db)]


def _bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip()
    return None


def resolve_auth_session(db: Session, raw_token: str | None) -> AuthSession:
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少登录令牌"
        )
    auth_session = (
        db.query(AuthSession)
        .options(joinedload(AuthSession.account))
        .filter(AuthSession.id == hash_token(raw_token))
        .first()
    )
    if (
        not auth_session
        or not auth_session.account
        or auth_session.account.status != AccountStatus.ACTIVE
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效"
        )
    if auth_session.expires_at < utc_now():
        db.delete(auth_session)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已超时"
        )
    auth_session.expires_at = utc_now() + timedelta(hours=24)
    db.commit()
    return auth_session


def get_auth_session(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
) -> AuthSession:
    return resolve_auth_session(db, _bearer_token(authorization))


AuthSessionDep = Annotated[AuthSession, Depends(get_auth_session)]


def current_account(auth_session: AuthSessionDep) -> Account:
    return auth_session.account


CurrentAccountDep = Annotated[Account, Depends(current_account)]


def resolve_media_account(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
) -> Account:
    raw_token = _bearer_token(authorization) or token
    return resolve_auth_session(db, raw_token).account


MediaAccountDep = Annotated[Account, Depends(resolve_media_account)]


def get_contact_or_404(db: Session, account: Account, contact_id: str) -> Contact:
    contact = scoped(db, account, Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return contact


def get_conversation_or_404(
    db: Session, account: Account, conversation_id: str
) -> Conversation:
    conversation = (
        scoped(db, account, Conversation)
        .options(joinedload(Conversation.contact))
        .filter(Conversation.id == conversation_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation
