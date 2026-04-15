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
from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, create_engine, or_, and_
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

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
Base = declarative_base()

# --- 2. 数据库模型 (ORM) ---
class Robot(Base):
    __tablename__ = "robots"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    system_prompt = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String, primary_key=True, index=True)
    robot_id = Column(String, index=True)
    title = Column(String, nullable=False)
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

# 创建所有表
Base.metadata.create_all(bind=engine)

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

class ConversationUpdate(BaseModel):
    title: str

class MessageCreate(BaseModel):
    conversation_id: str
    role: str
    msg_type: str
    content: str

class TaskUpdate(BaseModel):
    status: str
    error_message: Optional[str] = None

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
def list_robots(db: Session = Depends(get_db)):
    return db.query(Robot).all()

@app.put("/api/robots/{robot_id}")
def update_robot(robot_id: str, robot_update: RobotUpdate, db: Session = Depends(get_db)):
    db_robot = db.query(Robot).filter(Robot.id == robot_id).first()
    if not db_robot:
        raise HTTPException(status_code=404, detail="Robot 不存在")

    if robot_update.name is not None:
        db_robot.name = robot_update.name
    if robot_update.system_prompt is not None:
        db_robot.system_prompt = robot_update.system_prompt
    db_robot.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(db_robot)
    return db_robot

# --- 会话 API ---
@app.post("/api/conversations")
def create_conversation(conv_in: ConversationCreate, db: Session = Depends(get_db)):
    robot = db.query(Robot).filter(Robot.id == conv_in.robot_id).first()
    if not robot:
        raise HTTPException(status_code=404, detail=f"Robot '{conv_in.robot_id}' 不存在")

    now_str = datetime.now(timezone.utc).strftime("%m%d_%H%M")
    final_title = conv_in.title if conv_in.title else f"{robot.name}_{now_str}"

    conv_id = f"c_{uuid.uuid4().hex[:12]}"
    db_conv = Conversation(id=conv_id, robot_id=conv_in.robot_id, title=final_title)
    db.add(db_conv)
    db.commit()
    db.refresh(db_conv)
    return db_conv

@app.get("/api/conversations")
def list_conversations(db: Session = Depends(get_db)):
    return db.query(Conversation).order_by(Conversation.updated_at.desc()).all()

@app.put("/api/conversations/{conv_id}")
def update_conversation_title(conv_id: str, conv_update: ConversationUpdate, db: Session = Depends(get_db)):
    db_conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not db_conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    db_conv.title = conv_update.title
    db.commit()
    db.refresh(db_conv)
    return db_conv

# --- 消息 API ---
@app.post("/api/messages")
def send_message(msg_in: MessageCreate, db: Session = Depends(get_db)):
    if msg_in.role not in ["user", "robot"]:
        raise HTTPException(status_code=400, detail="角色 role 只能是 'user' 或 'robot'")

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
        {"updated_at": datetime.now(timezone.utc)}
    )

    db.commit()
    db.refresh(db_msg)

    # 如果是用户消息，创建 Task
    if msg_in.role == "user":
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
    db: Session = Depends(get_db)
):
    start_time = time.time()

    while True:
        msgs = db.query(Message).filter(
            and_(
                Message.conversation_id == conversation_id,
                Message.id > last_id
            )
        ).order_by(Message.id.asc()).all()

        if msgs:
            return msgs

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
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    robot = db.query(Robot).filter(Robot.id == conv.robot_id).first()

    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.id.asc()).all()

    return {
        "conversation": conv,
        "robot": robot,
        "messages": messages
    }


# --- 6. 优雅托管前端页面 ---
FRONTEND_DIR = BASE_DIR / "frontend"

@app.get("/")
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend_static")