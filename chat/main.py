import asyncio
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from chat.db import STORAGE_DIR, SessionLocal, ensure_database, get_db, utc_now
from chat.models import Conversation, Message, User
from chat.schemas import (
    BulkMessageImport,
    ConversationCreate,
    ConversationUpdate,
    MessageCreate,
    UserCreate,
    UserUpdate,
)

ensure_database()

# --- FastAPI 实例与路由 ---
app = FastAPI(title="Laborster Chat")

app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")


# --- User helpers ---

def get_user_or_404(db: Session, user_id: str, include_deleted: bool = False) -> User:
    query = db.query(User).filter(User.id == user_id)
    if not include_deleted:
        query = query.filter(User.is_deleted.is_(False))
    user = query.first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


# --- Conversation helpers ---

def get_conversation_query(db: Session, include_deleted: bool = False):
    query = db.query(Conversation)
    if not include_deleted:
        query = query.filter(Conversation.is_deleted.is_(False))
    return query


def get_conversation_or_404(db: Session, conv_id: str, include_deleted: bool = False) -> Conversation:
    conversation = get_conversation_query(db, include_deleted=include_deleted).filter(Conversation.id == conv_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


def get_messages_after_id(db: Session, conversation_id: str, last_id: int):
    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id, Message.id > last_id)
        .order_by(Message.id.asc())
        .all()
    )


def build_conversation_messages_payload(db: Session, conversation_id: str, last_id: int):
    conversation = get_conversation_or_404(db, conversation_id, include_deleted=True)
    messages = get_messages_after_id(db, conversation_id, last_id)
    return {
        "conversation": conversation,
        "messages": messages,
    }


# --- User API ---

@app.post("/api/users")
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    now = utc_now()
    user = User(
        id=f"u_{uuid.uuid4().hex[:8]}",
        name=user_in.name,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/api/users")
def list_users(
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    if not include_deleted:
        query = query.filter(User.is_deleted.is_(False))
    return query.order_by(User.created_at.desc()).all()


@app.get("/api/users/{user_id}")
def get_user(user_id: str, db: Session = Depends(get_db)):
    return get_user_or_404(db, user_id, include_deleted=True)


@app.put("/api/users/{user_id}")
def update_user(user_id: str, user_update: UserUpdate, db: Session = Depends(get_db)):
    user = get_user_or_404(db, user_id)
    if user_update.name is not None:
        user.name = user_update.name
    user.updated_at = utc_now()
    db.commit()
    db.refresh(user)
    return user


@app.delete("/api/users/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db)):
    user = get_user_or_404(db, user_id)
    now = utc_now()
    user.is_deleted = True
    user.deleted_at = now
    user.updated_at = now
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/users/{user_id}/restore")
def restore_user(user_id: str, db: Session = Depends(get_db)):
    user = get_user_or_404(db, user_id, include_deleted=True)
    if not user.is_deleted:
        return user
    user.is_deleted = False
    user.deleted_at = None
    user.updated_at = utc_now()
    db.commit()
    db.refresh(user)
    return user


# --- 会话 API ---

@app.post("/api/conversations")
def create_conversation(conv_in: ConversationCreate, db: Session = Depends(get_db)):
    # Validate both users exist
    get_user_or_404(db, conv_in.user_a_id)
    get_user_or_404(db, conv_in.user_b_id)

    if conv_in.user_a_id == conv_in.user_b_id:
        raise HTTPException(status_code=400, detail="两个参与者不能是同一个用户")

    now = utc_now()
    now_str = now.strftime("%m%d_%H%M")
    final_title = conv_in.title if conv_in.title else f"Conv_{now_str}"

    conv_id = f"c_{uuid.uuid4().hex[:12]}"
    db_conv = Conversation(
        id=conv_id,
        title=final_title,
        user_a_id=conv_in.user_a_id,
        user_b_id=conv_in.user_b_id,
        created_at=now,
        updated_at=now,
    )
    db.add(db_conv)
    db.commit()
    db.refresh(db_conv)
    return db_conv


@app.get("/api/conversations")
def list_conversations(
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
):
    return get_conversation_query(db, include_deleted=include_deleted).order_by(Conversation.updated_at.desc()).all()


@app.get("/api/conversations/{conv_id}")
def get_conversation(conv_id: str, db: Session = Depends(get_db)):
    return get_conversation_or_404(db, conv_id, include_deleted=True)


@app.put("/api/conversations/{conv_id}")
def update_conversation(conv_id: str, conv_update: ConversationUpdate, db: Session = Depends(get_db)):
    db_conv = get_conversation_or_404(db, conv_id)
    if conv_update.title is not None:
        db_conv.title = conv_update.title
    db_conv.updated_at = utc_now()
    db.commit()
    db.refresh(db_conv)
    return db_conv


@app.delete("/api/conversations/{conv_id}")
def delete_conversation(conv_id: str, db: Session = Depends(get_db)):
    db_conv = get_conversation_or_404(db, conv_id)
    now = utc_now()
    db_conv.is_deleted = True
    db_conv.deleted_at = now
    db_conv.updated_at = now
    db.commit()
    db.refresh(db_conv)
    return db_conv


@app.post("/api/conversations/{conv_id}/restore")
def restore_conversation(conv_id: str, db: Session = Depends(get_db)):
    db_conv = get_conversation_or_404(db, conv_id, include_deleted=True)
    if not db_conv.is_deleted:
        return db_conv
    db_conv.is_deleted = False
    db_conv.deleted_at = None
    db_conv.updated_at = utc_now()
    db.commit()
    db.refresh(db_conv)
    return db_conv


# --- 消息 API ---

@app.post("/api/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: str,
    msg_in: MessageCreate,
    db: Session = Depends(get_db),
):
    conv = get_conversation_or_404(db, conversation_id)

    # Validate sender is a participant
    if msg_in.sender_id not in (conv.user_a_id, conv.user_b_id):
        raise HTTPException(status_code=400, detail="发送者不是该会话的参与者")

    db_msg = Message(
        conversation_id=conversation_id,
        sender_id=msg_in.sender_id,
        msg_type=msg_in.msg_type,
        content=msg_in.content,
    )
    db.add(db_msg)

    db.query(Conversation).filter(Conversation.id == conversation_id).update(
        {"updated_at": utc_now()}
    )

    db.commit()
    db.refresh(db_msg)
    return {"status": "success", "id": db_msg.id}


@app.post("/api/conversations/{conversation_id}/messages/bulk")
def bulk_import_messages(
    conversation_id: str,
    bulk_in: BulkMessageImport,
    db: Session = Depends(get_db),
):
    """Bulk-import historical messages preserving timestamps. Used by Robot to seed simulator."""
    conv = get_conversation_or_404(db, conversation_id)
    participants = {conv.user_a_id, conv.user_b_id}

    if not bulk_in.messages:
        return {"status": "success", "imported": 0}

    inserted_ids = []
    for item in bulk_in.messages:
        if item.sender_id not in participants:
            raise HTTPException(
                status_code=400,
                detail=f"发送者 {item.sender_id} 不是该会话的参与者",
            )
        ts = item.created_at.replace(tzinfo=None) if item.created_at.tzinfo else item.created_at
        db_msg = Message(
            conversation_id=conversation_id,
            sender_id=item.sender_id,
            msg_type=item.msg_type,
            content=item.content,
            created_at=ts,
        )
        db.add(db_msg)
        db.flush()
        inserted_ids.append(db_msg.id)

    db.query(Conversation).filter(Conversation.id == conversation_id).update(
        {"updated_at": utc_now()}
    )
    db.commit()
    return {"status": "success", "imported": len(inserted_ids), "ids": inserted_ids}


@app.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    last_id: int = Query(0, ge=0),
    timeout: int = Query(0, ge=0),
):
    start_time = time.time()

    while True:
        db = SessionLocal()
        try:
            payload = build_conversation_messages_payload(db, conversation_id, last_id)
        finally:
            db.close()

        if payload["messages"]:
            return payload

        elapsed = time.time() - start_time
        if elapsed >= timeout:
            return payload

        sleep_time = min(0.2, timeout - elapsed)
        await asyncio.sleep(sleep_time)
