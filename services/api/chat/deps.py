"""Chat sandbox dependencies.

Auth is delegated to studio's session machinery — there is no separate
chat login. ``CurrentAccountDep`` here re-exports the studio dep so chat
routers don't reach across packages by hand. Media downloads accept a
fallback ``?token=`` query so ``<img>`` / ``<video>`` tags can authenticate
without a header.
"""

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

# Shared auth + connection pool from studio. Auth lives in the "auth"
# schema and is the *only* studio dependency chat takes.
from studio.db import get_db
from studio.deps import CurrentAccountDep, resolve_account_from_token
from studio.models import Account

from chat.models import Contact, Conversation
from chat.scoping import scoped

DbDep = Annotated[Session, Depends(get_db)]

__all__ = [
    "DbDep",
    "CurrentAccountDep",
    "MediaAccountDep",
    "get_contact_or_404",
    "get_conversation_or_404",
]


def _bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ").strip()
    return None


def resolve_media_account(
    db: DbDep,
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
) -> Account:
    """Media auth: header or ``?token=`` query (for embed-able URLs)."""
    raw = _bearer_token(authorization) or token
    if not raw:
        raise HTTPException(status_code=401, detail="缺少登录令牌")
    return resolve_account_from_token(db, raw)


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
