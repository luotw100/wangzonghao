import argparse
import asyncio
import time
import uuid
from typing import Any, AsyncIterator, Dict, Optional

import httpx
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy.orm import Session

from robot.clients import ChatAdapter
from robot.db import SessionLocal, ensure_database, get_db, utc_now
from robot.models import ProviderConfig, RobotMessage, SessionRecord
from robot.schemas import (
    ProviderConfigCreate,
    ProviderConfigUpdate,
    SessionCreate,
    SessionUpdate,
)

ensure_database()

app = FastAPI(title="Laborster Robot API")
app.state.chat_api_base_url = None


# --- Helpers ---

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


def serialize_session(session_record: SessionRecord, provider_config: Optional[ProviderConfig] = None) -> Dict[str, Any]:
    return {
        "id": session_record.id,
        "adapter_type": session_record.adapter_type,
        "adapter_thread_id": session_record.adapter_thread_id,
        "takeover_user_id": session_record.takeover_user_id,
        "profile": session_record.profile,
        "counterpart_profile": session_record.counterpart_profile,
        "provider_config_id": session_record.provider_config_id,
        "provider_config": serialize_provider_config(provider_config) if provider_config else None,
        "status": session_record.status,
        "created_at": session_record.created_at,
        "updated_at": session_record.updated_at,
    }


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


def get_chat_api_base_url(request: Request) -> str:
    base_url = getattr(request.app.state, "chat_api_base_url", None)
    if not base_url:
        raise HTTPException(status_code=500, detail="Robot API 未配置 Chat API Base URL")
    return str(base_url)


async def get_adapter(request: Request) -> AsyncIterator[ChatAdapter]:
    adapter = ChatAdapter(get_chat_api_base_url(request))
    try:
        yield adapter
    finally:
        await adapter.close()


def build_session_payload(db: Session, session_record: SessionRecord) -> Dict[str, Any]:
    provider_config = None
    if session_record.provider_config_id:
        provider_config = db.query(ProviderConfig).filter(ProviderConfig.id == session_record.provider_config_id).first()
    return serialize_session(session_record, provider_config)


# --- Provider Configs ---

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
    return [serialize_provider_config(pc) for pc in provider_configs]


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


# --- Sessions ---

@app.get("/api/conversations")
async def list_conversations(adapter: ChatAdapter = Depends(get_adapter)):
    """Proxy: list Chat conversations for the frontend to pick from when creating a session."""
    try:
        return await adapter.list_conversations()
    except httpx.HTTPStatusError as err:
        raise HTTPException(status_code=err.response.status_code, detail="获取会话列表失败")


@app.post("/api/sessions")
def create_session(session_in: SessionCreate, db: Session = Depends(get_db)):
    # Check adapter_thread_id not already taken
    existing = db.query(SessionRecord).filter(
        SessionRecord.adapter_thread_id == session_in.adapter_thread_id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="该会话已被接管")

    provider_config_id = session_in.provider_config_id
    if provider_config_id:
        get_provider_config_or_404(db, provider_config_id)
    else:
        first_provider = db.query(ProviderConfig).order_by(ProviderConfig.created_at.asc()).first()
        provider_config_id = first_provider.id if first_provider else None

    now = utc_now()
    session_record = SessionRecord(
        id=f"s_{uuid.uuid4().hex[:8]}",
        adapter_type="chat",
        adapter_thread_id=session_in.adapter_thread_id,
        takeover_user_id=session_in.takeover_user_id,
        profile=session_in.profile,
        counterpart_profile=session_in.counterpart_profile,
        provider_config_id=provider_config_id,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(session_record)
    db.commit()
    db.refresh(session_record)
    return build_session_payload(db, session_record)


@app.get("/api/sessions")
def list_sessions(db: Session = Depends(get_db)):
    sessions = db.query(SessionRecord).order_by(SessionRecord.created_at.desc()).all()
    return [build_session_payload(db, s) for s in sessions]


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    session_record = get_session_or_404(db, session_id)
    return build_session_payload(db, session_record)


@app.put("/api/sessions/{session_id}")
def update_session(session_id: str, session_update: SessionUpdate, db: Session = Depends(get_db)):
    session_record = get_session_or_404(db, session_id)
    if "profile" in session_update.model_fields_set:
        session_record.profile = session_update.profile
    if "counterpart_profile" in session_update.model_fields_set:
        session_record.counterpart_profile = session_update.counterpart_profile
    if "provider_config_id" in session_update.model_fields_set:
        if session_update.provider_config_id is not None:
            get_provider_config_or_404(db, session_update.provider_config_id)
        session_record.provider_config_id = session_update.provider_config_id
    session_record.updated_at = utc_now()
    db.commit()
    db.refresh(session_record)
    return build_session_payload(db, session_record)


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    session_record = get_session_or_404(db, session_id)
    session_record.status = "deleted"
    session_record.updated_at = utc_now()
    db.commit()
    db.refresh(session_record)
    return build_session_payload(db, session_record)


# --- Planned Replies ---

@app.get("/api/sessions/{session_id}/planned-replies")
async def get_planned_replies(
    session_id: str,
    timeout: int = Query(0, ge=0),
    last_count: int = Query(-1),
):
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

        if last_count >= 0 and len(result) != last_count:
            return result
        if last_count < 0 and result:
            return result

        elapsed = time.time() - start_time
        if elapsed >= timeout:
            return result

        sleep_time = min(0.2, timeout - elapsed)
        await asyncio.sleep(sleep_time)


# --- Entrypoint ---

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Robot API service")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--chat-api-base-url", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    app.state.chat_api_base_url = args.chat_api_base_url.rstrip("/")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()