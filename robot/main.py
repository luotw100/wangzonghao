import argparse
import asyncio
import time
import uuid
from contextlib import suppress
from typing import Any, AsyncIterator, Dict, Optional

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy.orm import Session

from robot.clients import ChatAPIClient
from robot.db import SessionLocal, ensure_database, get_db, utc_now
from robot.models import Contact, ProviderConfig, Robot, RobotMessage, SessionRecord
from robot.schemas import (
    ContactCreate,
    ContactUpdate,
    ProviderConfigCreate,
    ProviderConfigUpdate,
    RobotCreate,
    RobotUpdate,
    SessionCreate,
    SessionUpdate,
)

ensure_database()

app = FastAPI(title="Laborster Robot API")
app.state.chat_api_base_url = None


def serialize_robot(robot: Robot) -> Dict[str, Any]:
    return {
        "id": robot.id,
        "name": robot.name,
        "profile": robot.profile,
        "is_deleted": robot.is_deleted,
        "deleted_at": robot.deleted_at,
        "created_at": robot.created_at,
        "updated_at": robot.updated_at,
    }


def serialize_contact(contact: Contact) -> Dict[str, Any]:
    return {
        "id": contact.id,
        "name": contact.name,
        "profile": contact.profile,
        "is_deleted": contact.is_deleted,
        "deleted_at": contact.deleted_at,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }


def mask_api_key(api_key: Optional[str]) -> Optional[str]:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def serialize_provider_config(provider_config: ProviderConfig) -> Dict[str, Any]:
    return {
        "id": provider_config.id,
        "name": provider_config.name,
        "base_url": provider_config.base_url,
        "default_model": provider_config.default_model,
        "has_api_key": bool(provider_config.api_key),
        "api_key_preview": mask_api_key(provider_config.api_key),
        "created_at": provider_config.created_at,
        "updated_at": provider_config.updated_at,
    }


def get_robot_or_404(db: Session, robot_id: str, include_deleted: bool = False) -> Robot:
    query = db.query(Robot).filter(Robot.id == robot_id)
    if not include_deleted:
        query = query.filter(Robot.is_deleted.is_(False))
    robot = query.first()
    if not robot:
        raise HTTPException(status_code=404, detail="Robot 不存在")
    return robot


def get_contact_or_404(db: Session, contact_id: str, include_deleted: bool = False) -> Contact:
    query = db.query(Contact).filter(Contact.id == contact_id)
    if not include_deleted:
        query = query.filter(Contact.is_deleted.is_(False))
    contact = query.first()
    if not contact:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return contact


def get_provider_config_or_404(db: Session, provider_config_id: str) -> ProviderConfig:
    provider_config = db.query(ProviderConfig).filter(ProviderConfig.id == provider_config_id).first()
    if not provider_config:
        raise HTTPException(status_code=404, detail="Provider Config 不存在")
    return provider_config


def get_session_or_404(db: Session, session_id: str) -> SessionRecord:
    session_record = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
    if not session_record:
        raise HTTPException(status_code=404, detail="Session 不存在")
    return session_record


def extract_response_detail(response: httpx.Response, fallback: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict) and payload.get("detail"):
        return str(payload["detail"])

    text = response.text.strip()
    return text or fallback


def to_http_exception(err: httpx.HTTPStatusError, fallback: str) -> HTTPException:
    return HTTPException(status_code=err.response.status_code, detail=extract_response_detail(err.response, fallback))


def get_chat_api_base_url(request: Request) -> str:
    base_url = getattr(request.app.state, "chat_api_base_url", None)
    if not base_url:
        raise HTTPException(status_code=500, detail="Robot API 未配置 Chat API Base URL")
    return str(base_url)


async def get_chat_client(request: Request) -> AsyncIterator[ChatAPIClient]:
    chat = ChatAPIClient(get_chat_api_base_url(request))
    try:
        yield chat
    finally:
        await chat.close()


def build_session_payload(
    db: Session,
    session_record: SessionRecord,
    robot: Robot,
    contact: Contact,
    conversation: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    effective_status = session_record.status
    if conversation is None and session_record.status != "orphaned":
        effective_status = "orphaned"

    provider_config = None
    if session_record.provider_config_id:
        provider_config = db.query(ProviderConfig).filter(ProviderConfig.id == session_record.provider_config_id).first()

    return {
        "id": session_record.id,
        "title": conversation.get("title") if conversation else session_record.title,
        "status": effective_status,
        "created_at": session_record.created_at,
        "updated_at": session_record.updated_at,
        "robot_id": session_record.robot_id,
        "contact_id": session_record.contact_id,
        "provider_config_id": session_record.provider_config_id,
        "robot": serialize_robot(robot),
        "contact": serialize_contact(contact),
        "provider_config": serialize_provider_config(provider_config) if provider_config else None,
        "adapter": {
            "type": session_record.adapter_type,
            "thread_id": session_record.adapter_thread_id,
            "missing": conversation is None,
            "thread": conversation,
        },
    }


async def fetch_conversation_or_none(chat: ChatAPIClient, adapter_thread_id: str) -> Optional[Dict[str, Any]]:
    try:
        return await chat.get_conversation(adapter_thread_id, include_deleted=True)
    except httpx.HTTPStatusError as err:
        if err.response.status_code == 404:
            return None
        raise


async def fetch_session_payload(
    db: Session,
    session_record: SessionRecord,
    chat: ChatAPIClient,
    *,
    include_deleted: bool = False,
) -> Dict[str, Any]:
    robot = get_robot_or_404(db, session_record.robot_id, include_deleted=True)
    contact = get_contact_or_404(db, session_record.contact_id, include_deleted=True)
    conversation = await fetch_conversation_or_none(chat, session_record.adapter_thread_id)

    if conversation is not None and conversation.get("is_deleted") and not include_deleted:
        raise HTTPException(status_code=404, detail="Session 不存在")

    return build_session_payload(db, session_record, robot, contact, conversation)


@app.post("/api/robots")
def create_robot(robot_in: RobotCreate, db: Session = Depends(get_db)):
    now = utc_now()
    robot = Robot(
        id=f"r_{uuid.uuid4().hex[:8]}",
        name=robot_in.name,
        profile=robot_in.profile,
        created_at=now,
        updated_at=now,
    )
    db.add(robot)
    db.commit()
    db.refresh(robot)
    return serialize_robot(robot)


@app.get("/api/robots")
def list_robots(
    include_deleted: bool = Query(False, description="是否返回已删除的 Robot"),
    db: Session = Depends(get_db),
):
    query = db.query(Robot)
    if not include_deleted:
        query = query.filter(Robot.is_deleted.is_(False))
    robots = query.order_by(Robot.created_at.desc()).all()
    return [serialize_robot(robot) for robot in robots]


@app.put("/api/robots/{robot_id}")
def update_robot(robot_id: str, robot_update: RobotUpdate, db: Session = Depends(get_db)):
    robot = get_robot_or_404(db, robot_id)
    if "name" in robot_update.model_fields_set and robot_update.name is not None:
        robot.name = robot_update.name
    if "profile" in robot_update.model_fields_set:
        robot.profile = robot_update.profile
    robot.updated_at = utc_now()
    db.commit()
    db.refresh(robot)
    return serialize_robot(robot)


@app.delete("/api/robots/{robot_id}")
def delete_robot(robot_id: str, db: Session = Depends(get_db)):
    robot = get_robot_or_404(db, robot_id)
    now = utc_now()
    robot.is_deleted = True
    robot.deleted_at = now
    robot.updated_at = now
    db.commit()
    db.refresh(robot)
    return serialize_robot(robot)


@app.post("/api/robots/{robot_id}/restore")
def restore_robot(robot_id: str, db: Session = Depends(get_db)):
    robot = get_robot_or_404(db, robot_id, include_deleted=True)
    if not robot.is_deleted:
        return serialize_robot(robot)
    robot.is_deleted = False
    robot.deleted_at = None
    robot.updated_at = utc_now()
    db.commit()
    db.refresh(robot)
    return serialize_robot(robot)


@app.post("/api/contacts")
def create_contact(contact_in: ContactCreate, db: Session = Depends(get_db)):
    now = utc_now()
    contact = Contact(
        id=f"ct_{uuid.uuid4().hex[:8]}",
        name=contact_in.name,
        profile=contact_in.profile,
        created_at=now,
        updated_at=now,
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return serialize_contact(contact)


@app.get("/api/contacts")
def list_contacts(
    include_deleted: bool = Query(False, description="是否返回已删除的联系人"),
    db: Session = Depends(get_db),
):
    query = db.query(Contact)
    if not include_deleted:
        query = query.filter(Contact.is_deleted.is_(False))
    contacts = query.order_by(Contact.created_at.desc()).all()
    return [serialize_contact(contact) for contact in contacts]


@app.put("/api/contacts/{contact_id}")
def update_contact(contact_id: str, contact_update: ContactUpdate, db: Session = Depends(get_db)):
    contact = get_contact_or_404(db, contact_id)
    if "name" in contact_update.model_fields_set and contact_update.name is not None:
        contact.name = contact_update.name
    if "profile" in contact_update.model_fields_set:
        contact.profile = contact_update.profile
    contact.updated_at = utc_now()
    db.commit()
    db.refresh(contact)
    return serialize_contact(contact)


@app.delete("/api/contacts/{contact_id}")
def delete_contact(contact_id: str, db: Session = Depends(get_db)):
    contact = get_contact_or_404(db, contact_id)
    now = utc_now()
    contact.is_deleted = True
    contact.deleted_at = now
    contact.updated_at = now
    db.commit()
    db.refresh(contact)
    return serialize_contact(contact)


@app.post("/api/contacts/{contact_id}/restore")
def restore_contact(contact_id: str, db: Session = Depends(get_db)):
    contact = get_contact_or_404(db, contact_id, include_deleted=True)
    if not contact.is_deleted:
        return serialize_contact(contact)
    contact.is_deleted = False
    contact.deleted_at = None
    contact.updated_at = utc_now()
    db.commit()
    db.refresh(contact)
    return serialize_contact(contact)


@app.post("/api/provider-configs")
def create_provider_config(provider_in: ProviderConfigCreate, db: Session = Depends(get_db)):
    now = utc_now()
    provider_config = ProviderConfig(
        id=f"p_{uuid.uuid4().hex[:8]}",
        name=provider_in.name,
        base_url=provider_in.base_url.rstrip("/"),
        api_key=provider_in.api_key,
        default_model=provider_in.default_model,
        created_at=now,
        updated_at=now,
    )
    db.add(provider_config)
    db.commit()
    db.refresh(provider_config)
    return serialize_provider_config(provider_config)


@app.get("/api/provider-configs")
def list_provider_configs(db: Session = Depends(get_db)):
    provider_configs = db.query(ProviderConfig).order_by(ProviderConfig.updated_at.desc()).all()
    return [serialize_provider_config(provider_config) for provider_config in provider_configs]


@app.put("/api/provider-configs/{provider_config_id}")
def update_provider_config(provider_config_id: str, provider_update: ProviderConfigUpdate, db: Session = Depends(get_db)):
    provider_config = get_provider_config_or_404(db, provider_config_id)
    if "name" in provider_update.model_fields_set and provider_update.name is not None:
        provider_config.name = provider_update.name
    if "base_url" in provider_update.model_fields_set and provider_update.base_url is not None:
        provider_config.base_url = provider_update.base_url.rstrip("/")
    if "api_key" in provider_update.model_fields_set:
        provider_config.api_key = provider_update.api_key
    if "default_model" in provider_update.model_fields_set and provider_update.default_model is not None:
        provider_config.default_model = provider_update.default_model
    provider_config.updated_at = utc_now()
    db.commit()
    db.refresh(provider_config)
    return serialize_provider_config(provider_config)


@app.delete("/api/provider-configs/{provider_config_id}")
def delete_provider_config(provider_config_id: str, db: Session = Depends(get_db)):
    provider_config = get_provider_config_or_404(db, provider_config_id)
    db.delete(provider_config)
    db.commit()
    return {"status": "deleted", "id": provider_config_id}


@app.post("/api/sessions")
async def create_session(
    session_in: SessionCreate,
    db: Session = Depends(get_db),
    chat: ChatAPIClient = Depends(get_chat_client),
):
    get_robot_or_404(db, session_in.robot_id)
    get_contact_or_404(db, session_in.contact_id)

    # Resolve provider_config_id: use the supplied one or default to the first available
    provider_config_id = session_in.provider_config_id
    if provider_config_id:
        get_provider_config_or_404(db, provider_config_id)
    else:
        first_provider = db.query(ProviderConfig).order_by(ProviderConfig.created_at.asc()).first()
        provider_config_id = first_provider.id if first_provider else None

    try:
        conversation = await chat.create_conversation(session_in.title)
    except httpx.HTTPStatusError as err:
        raise to_http_exception(err, "创建 Session 失败")

    now = utc_now()
    session_record = SessionRecord(
        id=f"s_{uuid.uuid4().hex[:8]}",
        title=conversation.get("title"),
        robot_id=session_in.robot_id,
        contact_id=session_in.contact_id,
        provider_config_id=provider_config_id,
        adapter_type="chat",
        adapter_thread_id=conversation["id"],
        status="active",
        created_at=now,
        updated_at=now,
    )

    try:
        db.add(session_record)
        db.commit()
        db.refresh(session_record)
    except Exception:
        db.rollback()
        with suppress(Exception):
            await chat.delete_conversation(conversation["id"])
        raise

    return await fetch_session_payload(db, session_record, chat, include_deleted=True)


@app.get("/api/sessions")
async def list_sessions(
    include_deleted: bool = Query(False, description="是否返回已删除的 Session"),
    db: Session = Depends(get_db),
    chat: ChatAPIClient = Depends(get_chat_client),
):
    sessions = db.query(SessionRecord).order_by(SessionRecord.created_at.desc()).all()
    robots = {robot.id: robot for robot in db.query(Robot).all()}
    contacts = {contact.id: contact for contact in db.query(Contact).all()}

    try:
        conversations = await chat.list_conversations(include_deleted=True)
    except httpx.HTTPStatusError as err:
        raise to_http_exception(err, "获取 adapter 线程列表失败")

    conversation_map = {conversation["id"]: conversation for conversation in conversations}
    items = []
    for session_record in sessions:
        robot = robots.get(session_record.robot_id)
        contact = contacts.get(session_record.contact_id)
        if not robot or not contact:
            continue

        conversation = conversation_map.get(session_record.adapter_thread_id)
        if conversation is not None and conversation.get("is_deleted") and not include_deleted:
            continue
        items.append(build_session_payload(db, session_record, robot, contact, conversation))
    return items


@app.get("/api/sessions/{session_id}")
async def get_session(
    session_id: str,
    include_deleted: bool = Query(False, description="是否允许返回已删除的 Session"),
    db: Session = Depends(get_db),
    chat: ChatAPIClient = Depends(get_chat_client),
):
    session_record = get_session_or_404(db, session_id)
    return await fetch_session_payload(db, session_record, chat, include_deleted=include_deleted)


@app.put("/api/sessions/{session_id}")
async def update_session(
    session_id: str,
    session_update: SessionUpdate,
    db: Session = Depends(get_db),
    chat: ChatAPIClient = Depends(get_chat_client),
):
    session_record = get_session_or_404(db, session_id)
    if "robot_id" in session_update.model_fields_set and session_update.robot_id is not None:
        get_robot_or_404(db, session_update.robot_id)
        session_record.robot_id = session_update.robot_id
    if "contact_id" in session_update.model_fields_set and session_update.contact_id is not None:
        get_contact_or_404(db, session_update.contact_id)
        session_record.contact_id = session_update.contact_id
    if "provider_config_id" in session_update.model_fields_set:
        if session_update.provider_config_id is not None:
            get_provider_config_or_404(db, session_update.provider_config_id)
        session_record.provider_config_id = session_update.provider_config_id
    if "title" in session_update.model_fields_set:
        try:
            conversation = await chat.update_conversation(session_record.adapter_thread_id, session_update.title)
            session_record.title = conversation.get("title")
        except httpx.HTTPStatusError as err:
            raise to_http_exception(err, "更新 Session 标题失败")
    session_record.updated_at = utc_now()
    db.commit()
    db.refresh(session_record)
    return await fetch_session_payload(db, session_record, chat, include_deleted=True)


@app.delete("/api/sessions/{session_id}")
async def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    chat: ChatAPIClient = Depends(get_chat_client),
):
    session_record = get_session_or_404(db, session_id)
    try:
        conversation = await chat.delete_conversation(session_record.adapter_thread_id)
    except httpx.HTTPStatusError as err:
        raise to_http_exception(err, "删除 Session 失败")

    now = utc_now()
    session_record.status = "deleted"
    session_record.updated_at = now
    db.commit()

    robot = get_robot_or_404(db, session_record.robot_id, include_deleted=True)
    contact = get_contact_or_404(db, session_record.contact_id, include_deleted=True)
    return build_session_payload(db, session_record, robot, contact, conversation)


@app.post("/api/sessions/{session_id}/restore")
async def restore_session(
    session_id: str,
    db: Session = Depends(get_db),
    chat: ChatAPIClient = Depends(get_chat_client),
):
    session_record = get_session_or_404(db, session_id)
    try:
        conversation = await chat.restore_conversation(session_record.adapter_thread_id)
    except httpx.HTTPStatusError as err:
        raise to_http_exception(err, "恢复 Session 失败")

    session_record.status = "active"
    session_record.updated_at = utc_now()
    db.commit()

    robot = get_robot_or_404(db, session_record.robot_id, include_deleted=True)
    contact = get_contact_or_404(db, session_record.contact_id, include_deleted=True)
    return build_session_payload(db, session_record, robot, contact, conversation)


@app.get("/api/sessions/{session_id}/planned-replies")
async def get_planned_replies(
    session_id: str,
    timeout: int = Query(0, ge=0, description="超时时间(秒),0 表示立即返回"),
    last_count: int = Query(-1, description="客户端已知的计划消息数量，-1 表示首次请求"),
):
    """获取 session 的计划消息，支持长轮询。

    当 last_count >= 0 时，只要当前数量与 last_count 不同就立即返回（检测增减变化）。
    """
    start_time = time.time()

    while True:
        db = SessionLocal()
        try:
            get_session_or_404(db, session_id)
            replies = (
                db.query(RobotMessage)
                .filter(
                    RobotMessage.session_id == session_id,
                    RobotMessage.status == "scheduled",
                )
                .order_by(RobotMessage.scheduled_for.asc())
                .all()
            )
            result = [
                {
                    "id": r.id,
                    "content": r.content,
                    "status": r.status,
                    "scheduled_for": r.scheduled_for.isoformat() if r.scheduled_for else None,
                }
                for r in replies
            ]
        finally:
            db.close()

        # 状态有变化就立即返回（数量增减都算）
        if last_count >= 0 and len(result) != last_count:
            return result
        # 首次请求且有结果，立即返回
        if last_count < 0 and result:
            return result

        elapsed = time.time() - start_time
        if elapsed >= timeout:
            return result

        sleep_time = min(0.2, timeout - elapsed)
        await asyncio.sleep(sleep_time)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Robot API service")
    parser.add_argument("--host", required=True, help="监听地址，例: 127.0.0.1")
    parser.add_argument("--port", type=int, required=True, help="监听端口，例: 23457")
    parser.add_argument("--chat-api-base-url", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    app.state.chat_api_base_url = args.chat_api_base_url.rstrip("/")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()