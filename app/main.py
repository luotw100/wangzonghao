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
    robot_id = Column(String, index=True) # 关联到 Robot
    title = Column(String, nullable=False) # 会话标题
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String, index=True)
    role = Column(String, nullable=False)     # 核心变更：只能是 'user' 或 'robot'
    msg_type = Column(String, nullable=False) # text, image, audio, video
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

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
    title: Optional[str] = None # 允许前端不传，后端自动生成

class ConversationUpdate(BaseModel):
    title: str

class MessageCreate(BaseModel):
    conversation_id: str
    role: str # 'user' 或 'robot'
    msg_type: str
    content: str

# --- 4. 工具函数：处理 Base64 落盘 ---
def save_base64_file(content: str, msg_type: str) -> str:
    # 检查是否是 Data URI 格式
    if not content.startswith("data:"):
        return content # 如果不是，说明可能是普通文本或已处理路径

    try:
        header, encoded = content.split(",", 1)
        # 提取后缀，例如从 "data:image/jpeg;base64" 中提取 "jpeg"
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

# 挂载静态文件目录，前端可以直接访问 /storage/xxx.jpg
app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")

# 获取 DB 会话
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Robot API (原 User API) ---
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
    # 1. 强校验：判断 Robot 是否存在
    robot = db.query(Robot).filter(Robot.id == conv_in.robot_id).first()
    if not robot:
        raise HTTPException(status_code=404, detail=f"Robot '{conv_in.robot_id}' 不存在")

    # 2. 生成默认 Title：Robot名字 + 当前日期时间 (例如: 物理老师_1024_1530)
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
    # 按照最后活跃时间降序排列，类似微信首页
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
    # 校验角色
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
    return {"status": "success", "id": db_msg.id}

@app.get("/api/messages")
def sync_messages(
    conversation_id: str,
    last_id: int = Query(0),
    db: Session = Depends(get_db)
):
    """
    短轮询：立即返回现有消息，不等待
    """
    return db.query(Message).filter(
        and_(
            Message.conversation_id == conversation_id,
            Message.id > last_id
        )
    ).order_by(Message.id.asc()).all()


@app.get("/api/messages/long-poll")
def long_poll_messages(
    conversation_id: str,
    last_id: int = Query(0),
    timeout: int = Query(30, description="超时时间（秒）"),
    db: Session = Depends(get_db)
):
    """
    长轮询接口：有新消息立即返回，超时则返回空列表
    """
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

        # 检查是否超时
        if time.time() - start_time >= timeout:
            return []

        # 休息一下再查，避免 CPU 空转
        time.sleep(0.5)


# --- 6. 优雅托管前端页面 ---
FRONTEND_DIR = BASE_DIR / "frontend"

# 优先拦截根目录 /，直接返回 index.html
@app.get("/")
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend_static")