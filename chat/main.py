import asyncio

import uuid
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Column, String, Integer, DateTime, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

# --- 1. 环境与路径配置 ---
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"

STORAGE_DIR.mkdir(exist_ok=True)

DB_PATH = STORAGE_DIR / "chat.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
class Base(DeclarativeBase):
    pass

# --- 2. 数据库模型 (ORM) ---
class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, index=True)
    role = Column(String, nullable=False)
    msg_type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

# 创建所有表
Base.metadata.create_all(bind=engine)

# --- 3. Pydantic 响应/请求模型 (Schemas) ---
class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None

class ConversationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None

class ConversationMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    msg_type: str
    content: str

# --- 5. FastAPI 实例与路由 ---
app = FastAPI(title="Laborster Chat")

app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

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

# --- 会话 API ---
@app.post("/api/conversations")
def create_conversation(conv_in: ConversationCreate, db: Session = Depends(get_db)):
    now_str = utc_now().strftime("%m%d_%H%M")
    final_title = conv_in.title if conv_in.title else f"Conv_{now_str}"

    conv_id = f"c_{uuid.uuid4().hex[:12]}"
    db_conv = Conversation(
        id=conv_id,
        title=final_title
    )
    db.add(db_conv)
    db.commit()
    db.refresh(db_conv)
    return db_conv

@app.get("/api/conversations")
def list_conversations(
    include_deleted: bool = Query(False, description="是否返回已删除的会话"),
    db: Session = Depends(get_db)
):
    return get_conversation_query(db, include_deleted=include_deleted).order_by(Conversation.updated_at.desc()).all()

@app.get("/api/conversations/{conv_id}")
def get_conversation(
    conv_id: str,
    db: Session = Depends(get_db)
):
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
    msg_in: ConversationMessageCreate,
    db: Session = Depends(get_db)
):
    if msg_in.role not in ["user", "robot"]:
        raise HTTPException(status_code=400, detail="角色 role 只能是 'user' 或 'robot'")

    get_conversation_or_404(db, conversation_id)

    db_msg = Message(
        conversation_id=conversation_id,
        role=msg_in.role,
        msg_type=msg_in.msg_type,
        content=msg_in.content
    )
    db.add(db_msg)

    # 更新会话活跃时间
    db.query(Conversation).filter(Conversation.id == conversation_id).update(
        {"updated_at": utc_now()}
    )

    db.commit()
    db.refresh(db_msg)
    return {"status": "success", "id": db_msg.id}

@app.get("/api/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    last_id: int = Query(0, ge=0),
    timeout: int = Query(0, ge=0, description="超时时间(秒),0 表示立即返回"),
):
    """按会话获取消息，支持全量快照、增量查询和长轮询。"""
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

        sleep_time = min(0.5, timeout - elapsed)
        await asyncio.sleep(sleep_time)
