from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from chat.db import utc_now
from chat.deps import CurrentAccountDep, DbDep, get_contact_or_404
from chat.ids import new_id
from chat.models import Account, Contact, Conversation
from chat.schemas import ContactCreate, ContactRead, ContactUpdate
from chat.scoping import scoped


router = APIRouter(prefix="/api/contacts", tags=["contacts"])


def _get_or_create_direct_conversation(
    db: Session, account: Account, contact: Contact, title: str | None = None
) -> Conversation:
    conversation = (
        scoped(db, account, Conversation)
        .options(joinedload(Conversation.contact))
        .filter(Conversation.contact_id == contact.id)
        .first()
    )
    if conversation:
        if title:
            conversation.title = title
        conversation.updated_at = utc_now()
        return conversation

    now = utc_now()
    conversation = Conversation(
        id=new_id("c"),
        account_id=account.id,
        contact_id=contact.id,
        title=title or contact.nickname,
        created_at=now,
        updated_at=now,
    )
    db.add(conversation)
    return conversation


@router.get("", response_model=list[ContactRead])
def list_contacts(account: CurrentAccountDep, db: DbDep) -> list[Contact]:
    """获取当前账号的所有联系人，按最后更新时间降序排列。"""
    return scoped(db, account, Contact).order_by(Contact.updated_at.desc()).all()


@router.post("", response_model=ContactRead)
def create_contact(
    contact_in: ContactCreate, account: CurrentAccountDep, db: DbDep
) -> Contact:
    """创建联系人。

    创建成功后，系统会自动为该联系人创建一个一对一会话（同一账号下一个联系人只有一个会话）。
    同一账号下 username 不可重复，重复提交会返回 409。
    若不传 username，系统自动生成一个唯一 ID 作为其外部标识。
    """
    now = utc_now()
    contact = Contact(
        id=new_id("ct"),
        account_id=account.id,
        username=contact_in.username or new_id("chatid"),
        nickname=contact_in.nickname,
        remark_name=contact_in.remark_name,
        created_at=now,
        updated_at=now,
    )
    db.add(contact)
    try:
        db.flush()
        _get_or_create_direct_conversation(db, account, contact)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该联系人已存在")
    db.refresh(contact)
    return contact


@router.put("/{contact_id}", response_model=ContactRead)
def update_contact(
    contact_id: str,
    contact_update: ContactUpdate,
    account: CurrentAccountDep,
    db: DbDep,
) -> Contact:
    """更新联系人（目前仅支持修改备注名）。传 null 可清除备注。"""
    contact = get_contact_or_404(db, account, contact_id)
    if contact_update.remark_name is not None:
        contact.remark_name = contact_update.remark_name
    contact.updated_at = utc_now()
    db.commit()
    db.refresh(contact)
    return contact
