"""Contact and conversation endpoints."""

from typing import Annotated, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from studio.db import get_db, utc_now
from studio.deps import CurrentAccountDep, get_account_contact, get_account_persona, get_provider_or_404, is_admin
from studio.models import Contact, Inbox, Message
from studio.schemas import ContactUpdate
from studio.serializers import s_contact, s_inbox, s_message

router = APIRouter()


@router.get("/api/contacts/{contact_id}")
def get_contact(contact_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    return s_contact(get_account_contact(db, account, contact_id))


@router.get("/api/conversations")
def list_conversations(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    query = db.query(Contact, Inbox).join(Inbox, Inbox.id == Contact.inbox_id)
    if not is_admin(account):
        query = query.filter(Inbox.account_id == account.id)
    rows = query.all()
    out: List[Dict] = []
    for contact, inbox in rows:
        latest = (
            db.query(Message)
            .filter(Message.contact_id == contact.id)
            .order_by(Message.timestamp.desc(), Message.id.desc())
            .first()
        )
        message_count = db.query(Message).filter(Message.contact_id == contact.id).count()
        out.append({
            "contact": s_contact(contact),
            "inbox": s_inbox(inbox),
            "latest_message": s_message(latest) if latest else None,
            "message_count": message_count,
        })
    out.sort(
        key=lambda item: (
            item["latest_message"]["timestamp"] if item["latest_message"] else item["contact"]["updated_at"],
            item["contact"]["id"],
        ),
        reverse=True,
    )
    return out


@router.get("/api/contacts/{contact_id}/messages")
def list_contact_messages(
    contact_id: str,
    db: Annotated[Session, Depends(get_db)],
    account: CurrentAccountDep,
    limit: int = Query(200, ge=1, le=500),
):
    contact = get_account_contact(db, account, contact_id)
    rows = (
        db.query(Message)
        .filter(Message.contact_id == contact.id)
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    return [s_message(m) for m in rows]


@router.put("/api/contacts/{contact_id}")
def update_contact(contact_id: str, payload: ContactUpdate, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    c = get_account_contact(db, account, contact_id)
    fields = payload.model_fields_set
    if "display_name" in fields and payload.display_name is not None: c.display_name = payload.display_name
    if "card_md" in fields: c.card_md = payload.card_md
    if "persona_id" in fields and payload.persona_id is not None:
        get_account_persona(db, account, payload.persona_id)
        c.persona_id = payload.persona_id
    if ("reply_provider_config_id" in fields or payload.clear_reply_provider) and not is_admin(account):
        raise HTTPException(status_code=403, detail="只有管理员可以修改 Provider")
    if "reply_provider_config_id" in fields and payload.reply_provider_config_id is not None:
        get_provider_or_404(db, payload.reply_provider_config_id)
        c.reply_provider_config_id = payload.reply_provider_config_id
    if payload.clear_reply_provider:
        c.reply_provider_config_id = None
    if "autoreply_enabled" in fields and payload.autoreply_enabled is not None:
        c.autoreply_enabled = payload.autoreply_enabled
    if "status" in fields and payload.status is not None: c.status = payload.status
    c.updated_at = utc_now()
    db.commit(); db.refresh(c)
    return s_contact(c)
