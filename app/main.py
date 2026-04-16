import asyncio
import base64
import uuid
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi.responses import FileResponse
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, String, Integer, DateTime, Text, create_engine, and_, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

# --- 1. 环境与路径配置 ---
BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
ATTACHMENTS_DIR = STORAGE_DIR / "attachments"

STORAGE_DIR.mkdir(exist_ok=True)
ATTACHMENTS_DIR.mkdir(exist_ok=True)

DB_PATH = STORAGE_DIR / "chat.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
class Base(DeclarativeBase):
    pass

# --- 2. 数据库模型 (ORM) ---
class Robot(Base):
    __tablename__ = "robots"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    system_prompt = Column(Text, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String, primary_key=True, index=True)
    robot_id = Column(String, index=True)
    title = Column(String, nullable=False)
    user_profile = Column(Text, nullable=True)
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

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, index=True)
    user_message_id = Column(Integer, nullable=False)
    status = Column(String, default="pending")  # pending / processing / done / failed
    retry_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class PlannedReply(Base):
    __tablename__ = "planned_replies"
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, index=True)
    content = Column(Text, nullable=False)
    send_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

# 创建所有表
Base.metadata.create_all(bind=engine)

# --- 数据库迁移：补充新增字段 ---
def _run_migrations():
    from sqlalchemy.exc import OperationalError
    migrations = [
        ("conversations", "user_profile", "TEXT"),
        ("robots", "is_deleted", "BOOLEAN NOT NULL DEFAULT 0"),
        ("robots", "deleted_at", "DATETIME"),
        ("conversations", "is_deleted", "BOOLEAN NOT NULL DEFAULT 0"),
        ("conversations", "deleted_at", "DATETIME"),
    ]

    with engine.connect() as conn:
        for table_name, column_name, definition in migrations:
            try:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
                conn.commit()
            except OperationalError:
                pass  # 列已存在，忽略

_run_migrations()

# --- 3. Pydantic 响应/请求模型 (Schemas) ---
class RobotCreate(BaseModel):
    name: str
    system_prompt: Optional[str] = None

class RobotUpdate(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None

class ConversationCreate(BaseModel):
    robot_id: str
    title: Optional[str] = None
    user_profile: Optional[str] = None

class ConversationUpdate(BaseModel):
    title: Optional[str] = None
    user_profile: Optional[str] = None

class MessageCreate(BaseModel):
    conversation_id: str
    role: str
    msg_type: str
    content: str

class TaskUpdate(BaseModel):
    status: str
    error_message: Optional[str] = None

class PlannedReplyCreate(BaseModel):
    conversation_id: str
    content: str
    send_at: datetime

class PlannedRepliesBatch(BaseModel):
    replies: List[PlannedReplyCreate]

# --- 4. 工具函数：处理 Base64 落盘 ---
def save_base64_file(content: str, msg_type: str) -> str:
    if not content.startswith("data:"):
        return content

    try:
        header, encoded = content.split(",", 1)
        match = re.search(r'/(.*?);', header)
        ext = match.group(1) if match else "bin"

        filename = f"file_{uuid.uuid4().hex}.{ext}"
        file_path = ATTACHMENTS_DIR / filename

        with open(file_path, "wb") as f:
            f.write(base64.b64decode(encoded))

        return f"/storage/attachments/{filename}"
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 data: {str(e)}")

# --- 5. FastAPI 实例与路由 ---
app = FastAPI(title="FakeWeChat API")

app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_robot_query(db: Session, include_deleted: bool = False):
    query = db.query(Robot)
    if not include_deleted:
        query = query.filter(Robot.is_deleted.is_(False))
    return query


def get_conversation_query(db: Session, include_deleted: bool = False):
    query = db.query(Conversation)
    if not include_deleted:
        query = query.filter(Conversation.is_deleted.is_(False))
    return query


def get_robot_or_404(db: Session, robot_id: str, include_deleted: bool = False) -> Robot:
    robot = get_robot_query(db, include_deleted=include_deleted).filter(Robot.id == robot_id).first()
    if not robot:
        raise HTTPException(status_code=404, detail="Robot 不存在")
    return robot


def get_conversation_or_404(db: Session, conv_id: str, include_deleted: bool = False) -> Conversation:
    conversation = get_conversation_query(db, include_deleted=include_deleted).filter(Conversation.id == conv_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation


def block_deleted_conversations(db: Session, conversation_ids: List[str]):
    if not conversation_ids:
        return

    now = utc_now()
    db.query(PlannedReply).filter(
        PlannedReply.conversation_id.in_(conversation_ids)
    ).delete(synchronize_session=False)
    db.query(Task).filter(
        Task.conversation_id.in_(conversation_ids),
        Task.status.in_(["pending", "processing"])
    ).update(
        {
            Task.status: "failed",
            Task.error_message: "Conversation deleted",
            Task.updated_at: now,
        },
        synchronize_session=False,
    )


def soft_delete_conversations(db: Session, conversations: List[Conversation]):
    active_conversations = [conv for conv in conversations if not conv.is_deleted]
    if not active_conversations:
        return

    now = utc_now()
    for conversation in active_conversations:
        conversation.is_deleted = True
        conversation.deleted_at = now
        conversation.updated_at = now

    block_deleted_conversations(db, [conversation.id for conversation in active_conversations])

# --- Robot API ---
@app.post("/api/robots")
def create_robot(robot_in: RobotCreate, db: Session = Depends(get_db)):
    robot_id = f"bot_{uuid.uuid4().hex[:8]}"
    db_robot = Robot(id=robot_id, name=robot_in.name, system_prompt=robot_in.system_prompt)
    db.add(db_robot)
    db.commit()
    db.refresh(db_robot)
    return db_robot

@app.get("/api/robots")
def list_robots(
    include_deleted: bool = Query(False, description="是否返回已删除的 Robot"),
    db: Session = Depends(get_db)
):
    return get_robot_query(db, include_deleted=include_deleted).all()

@app.put("/api/robots/{robot_id}")
def update_robot(robot_id: str, robot_update: RobotUpdate, db: Session = Depends(get_db)):
    db_robot = get_robot_or_404(db, robot_id)

    if robot_update.name is not None:
        db_robot.name = robot_update.name
    if "system_prompt" in robot_update.model_fields_set:
        db_robot.system_prompt = robot_update.system_prompt
    db_robot.updated_at = utc_now()

    db.commit()
    db.refresh(db_robot)
    return db_robot


@app.delete("/api/robots/{robot_id}")
def delete_robot(robot_id: str, db: Session = Depends(get_db)):
    db_robot = get_robot_or_404(db, robot_id)
    now = utc_now()

    db_robot.is_deleted = True
    db_robot.deleted_at = now
    db_robot.updated_at = now

    robot_conversations = db.query(Conversation).filter(Conversation.robot_id == robot_id).all()
    soft_delete_conversations(db, robot_conversations)

    db.commit()
    db.refresh(db_robot)
    return db_robot


@app.post("/api/robots/{robot_id}/restore")
def restore_robot(robot_id: str, db: Session = Depends(get_db)):
    db_robot = get_robot_or_404(db, robot_id, include_deleted=True)
    if not db_robot.is_deleted:
        return db_robot

    db_robot.is_deleted = False
    db_robot.deleted_at = None
    db_robot.updated_at = utc_now()

    db.commit()
    db.refresh(db_robot)
    return db_robot

# --- 会话 API ---
@app.post("/api/conversations")
def create_conversation(conv_in: ConversationCreate, db: Session = Depends(get_db)):
    robot = get_robot_query(db).filter(Robot.id == conv_in.robot_id).first()
    if not robot:
        raise HTTPException(status_code=404, detail=f"Robot '{conv_in.robot_id}' 不存在")

    now_str = utc_now().strftime("%m%d_%H%M")
    final_title = conv_in.title if conv_in.title else f"{robot.name}_{now_str}"

    conv_id = f"c_{uuid.uuid4().hex[:12]}"
    db_conv = Conversation(
        id=conv_id,
        robot_id=conv_in.robot_id,
        title=final_title,
        user_profile=conv_in.user_profile
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

@app.put("/api/conversations/{conv_id}")
def update_conversation_title(conv_id: str, conv_update: ConversationUpdate, db: Session = Depends(get_db)):
    db_conv = get_conversation_or_404(db, conv_id)

    if conv_update.title is not None:
        db_conv.title = conv_update.title
    if "user_profile" in conv_update.model_fields_set:
        db_conv.user_profile = conv_update.user_profile
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
    block_deleted_conversations(db, [db_conv.id])

    db.commit()
    db.refresh(db_conv)
    return db_conv


@app.post("/api/conversations/{conv_id}/restore")
def restore_conversation(conv_id: str, db: Session = Depends(get_db)):
    db_conv = get_conversation_or_404(db, conv_id, include_deleted=True)
    db_robot = get_robot_or_404(db, db_conv.robot_id, include_deleted=True)
    if db_robot.is_deleted:
        raise HTTPException(status_code=400, detail="所属 Robot 已删除，请先恢复 Robot")
    if not db_conv.is_deleted:
        return db_conv

    db_conv.is_deleted = False
    db_conv.deleted_at = None
    db_conv.updated_at = utc_now()

    db.commit()
    db.refresh(db_conv)
    return db_conv

# --- 消息 API ---
@app.post("/api/messages")
def send_message(msg_in: MessageCreate, db: Session = Depends(get_db)):
    if msg_in.role not in ["user", "robot"]:
        raise HTTPException(status_code=400, detail="角色 role 只能是 'user' 或 'robot'")

    get_conversation_or_404(db, msg_in.conversation_id)

    content = msg_in.content
    if msg_in.msg_type in ["image", "audio", "video"]:
        content = save_base64_file(msg_in.content, msg_in.msg_type)

    db_msg = Message(
        conversation_id=msg_in.conversation_id,
        role=msg_in.role,
        msg_type=msg_in.msg_type,
        content=content
    )
    db.add(db_msg)

    # 更新会话活跃时间
    db.query(Conversation).filter(Conversation.id == msg_in.conversation_id).update(
        {"updated_at": utc_now()}
    )

    db.commit()
    db.refresh(db_msg)

    # 如果是用户消息：取消该会话所有计划回复，并创建新 Task（全双工中断）
    if msg_in.role == "user":
        db.query(PlannedReply).filter(
            PlannedReply.conversation_id == msg_in.conversation_id
        ).delete(synchronize_session=False)
        db_task = Task(
            conversation_id=msg_in.conversation_id,
            user_message_id=db_msg.id,
            status="pending"
        )
        db.add(db_task)
        db.commit()

    return {"status": "success", "id": db_msg.id}

@app.get("/api/messages")
async def get_messages(
    conversation_id: str,
    last_id: int = Query(0),
    timeout: int = Query(30, description="超时时间（秒），0 表示立即返回"),
):
    db = SessionLocal()
    try:
        get_conversation_or_404(db, conversation_id, include_deleted=True)
    finally:
        db.close()

    start_time = time.time()

    while True:
        db = SessionLocal()
        try:
            msgs = db.query(Message).filter(
                and_(
                    Message.conversation_id == conversation_id,
                    Message.id > last_id
                )
            ).order_by(Message.id.asc()).all()

            if msgs:
                return msgs
        finally:
            db.close()

        elapsed = time.time() - start_time
        if elapsed >= timeout:
            return []

        sleep_time = min(0.5, timeout - elapsed)
        await asyncio.sleep(sleep_time)


# --- Task API (供 Worker 使用) ---
@app.get("/api/tasks")
def list_tasks(
    status: str = Query(None, description="过滤状态: pending/processing/done/failed"),
    limit: int = Query(10, description="返回数量限制"),
    db: Session = Depends(get_db)
):
    query = db.query(Task)
    if status:
        query = query.filter(Task.status == status)
    if status in [None, "pending", "processing"]:
        query = query.join(Conversation, Conversation.id == Task.conversation_id).filter(
            Conversation.is_deleted.is_(False)
        )
    return query.order_by(Task.created_at.asc()).limit(limit).all()

@app.put("/api/tasks/{task_id}")
def update_task(task_id: int, task_update: TaskUpdate, db: Session = Depends(get_db)):
    db_task = db.query(Task).filter(Task.id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Task 不存在")

    if task_update.status:
        db_task.status = task_update.status
    if task_update.error_message is not None:
        db_task.error_message = task_update.error_message

    if task_update.status == "processing":
        db_task.retry_count += 1

    db_task.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(db_task)
    return db_task

# --- 获取会话历史消息（供 Worker 使用） ---
@app.get("/api/conversations/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: str,
    db: Session = Depends(get_db)
):
    """获取会话的所有历史消息，按时间顺序返回"""
    conv = get_conversation_or_404(db, conversation_id)

    robot = get_robot_or_404(db, conv.robot_id)

    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.id.asc()).all()

    return {
        "conversation": conv,
        "robot": robot,
        "messages": messages
    }


# --- PlannedReply API ---
@app.post("/api/planned_replies")
def create_planned_replies(batch: PlannedRepliesBatch, db: Session = Depends(get_db)):
    """Worker 批量提交计划回复"""
    conversation_ids = {reply.conversation_id for reply in batch.replies}
    active_count = db.query(Conversation).filter(
        Conversation.id.in_(conversation_ids),
        Conversation.is_deleted.is_(False)
    ).count() if conversation_ids else 0
    if active_count != len(conversation_ids):
        raise HTTPException(status_code=404, detail="会话不存在")

    for r in batch.replies:
        # send_at 统一存储为 UTC naive datetime（SQLite 不支持带时区的列）
        if r.send_at.tzinfo is not None:
            send_at_utc = r.send_at.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            send_at_utc = r.send_at
        db_reply = PlannedReply(
            conversation_id=r.conversation_id,
            content=r.content,
            send_at=send_at_utc
        )
        db.add(db_reply)
    db.commit()
    return {"status": "ok", "count": len(batch.replies)}

@app.get("/api/planned_replies/due")
def get_due_planned_replies(db: Session = Depends(get_db)):
    """Worker 获取所有到期（send_at <= now）的计划回复"""
    now = datetime.utcnow()
    replies = db.query(PlannedReply).join(
        Conversation,
        Conversation.id == PlannedReply.conversation_id
    ).filter(
        PlannedReply.send_at <= now,
        Conversation.is_deleted.is_(False)
    ).order_by(PlannedReply.send_at.asc()).all()
    return replies

@app.get("/api/planned_replies")
def get_planned_replies(conversation_id: str = Query(...), db: Session = Depends(get_db)):
    """前端获取指定会话的所有计划回复（用于显示半透明气泡）"""
    get_conversation_or_404(db, conversation_id, include_deleted=True)
    replies = db.query(PlannedReply).filter(
        PlannedReply.conversation_id == conversation_id
    ).order_by(PlannedReply.send_at.asc()).all()
    return replies

@app.delete("/api/planned_replies/{reply_id}")
def delete_planned_reply(reply_id: int, db: Session = Depends(get_db)):
    """Worker 发送完毕后删除计划回复"""
    db.query(PlannedReply).filter(PlannedReply.id == reply_id).delete(synchronize_session=False)
    db.commit()
    return {"status": "ok"}


# --- 6. 托管前端页面 ---
FRONTEND_DIR = BASE_DIR / "frontend"

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend_static")

@app.get("/")
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")
