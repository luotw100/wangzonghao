import argparse
import asyncio
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

import httpx
import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session

from robot.clients import ChatAdapter
from robot.db import SessionLocal, ensure_database, get_db, utc_now
from robot.distill.ingest import ingest_archive
from robot.models import (
    ChatArchive,
    Contact,
    DistillJob,
    Message,
    Operator,
    ProviderConfig,
    SessionRecord,
)
from robot.schemas import (
    ContactUpdate,
    OperatorCreate,
    OperatorUpdate,
    ProviderConfigCreate,
    ProviderConfigUpdate,
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


def serialize_operator(op: Operator, db: Session) -> Dict[str, Any]:
    pc = None
    if op.provider_config_id:
        pc = db.query(ProviderConfig).filter(ProviderConfig.id == op.provider_config_id).first()
    return {
        "id": op.id,
        "name": op.name,
        "persona_md": op.persona_md,
        "adapter_identities": op.adapter_identities or {},
        "provider_config_id": op.provider_config_id,
        "provider_config": serialize_provider_config(pc) if pc else None,
        "status": op.status,
        "created_at": op.created_at,
        "updated_at": op.updated_at,
    }


def serialize_contact(contact: Contact) -> Dict[str, Any]:
    return {
        "id": contact.id,
        "operator_id": contact.operator_id,
        "display_name": contact.display_name,
        "wechat_wxid": contact.wechat_wxid,
        "chat_user_id": contact.chat_user_id,
        "card_md": contact.card_md,
        "status": contact.status,
        "created_at": contact.created_at,
        "updated_at": contact.updated_at,
    }


def serialize_session(session_record: SessionRecord) -> Dict[str, Any]:
    return {
        "id": session_record.id,
        "contact_id": session_record.contact_id,
        "adapter_type": session_record.adapter_type,
        "adapter_thread_id": session_record.adapter_thread_id,
        "status": session_record.status,
        "created_at": session_record.created_at,
        "updated_at": session_record.updated_at,
    }


def serialize_archive(archive: ChatArchive) -> Dict[str, Any]:
    return {
        "id": archive.id,
        "operator_id": archive.operator_id,
        "filename": archive.filename,
        "self_wxid": archive.self_wxid,
        "message_count": archive.message_count,
        "contact_count": archive.contact_count,
        "uploaded_at": archive.uploaded_at,
    }


def serialize_distill_job(job: DistillJob) -> Dict[str, Any]:
    return {
        "id": job.id,
        "operator_id": job.operator_id,
        "status": job.status,
        "progress": job.progress or {},
        "error_message": job.error_message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def get_provider_config_or_404(db: Session, provider_config_id: str) -> ProviderConfig:
    pc = db.query(ProviderConfig).filter(ProviderConfig.id == provider_config_id).first()
    if not pc:
        raise HTTPException(status_code=404, detail="Provider Config 不存在")
    return pc


def get_operator_or_404(db: Session, operator_id: str) -> Operator:
    op = db.query(Operator).filter(Operator.id == operator_id).first()
    if not op:
        raise HTTPException(status_code=404, detail="Operator 不存在")
    return op


def get_contact_or_404(db: Session, contact_id: str) -> Contact:
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact 不存在")
    return contact


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


# --- Provider Configs ---

@app.post("/api/provider-configs")
def create_provider_config(provider_in: ProviderConfigCreate, db: Session = Depends(get_db)):
    now = utc_now()
    pc = ProviderConfig(
        id=f"p_{uuid.uuid4().hex[:8]}",
        name=provider_in.name,
        base_url=provider_in.base_url.rstrip("/"),
        api_key=provider_in.api_key,
        default_model=provider_in.default_model,
        created_at=now,
        updated_at=now,
    )
    db.add(pc)
    db.commit()
    db.refresh(pc)
    return serialize_provider_config(pc)


@app.get("/api/provider-configs")
def list_provider_configs(db: Session = Depends(get_db)):
    items = db.query(ProviderConfig).order_by(ProviderConfig.updated_at.desc()).all()
    return [serialize_provider_config(p) for p in items]


@app.put("/api/provider-configs/{provider_config_id}")
def update_provider_config(
    provider_config_id: str,
    provider_update: ProviderConfigUpdate,
    db: Session = Depends(get_db),
):
    pc = get_provider_config_or_404(db, provider_config_id)
    fields = provider_update.model_fields_set
    if "name" in fields and provider_update.name is not None:
        pc.name = provider_update.name
    if "base_url" in fields and provider_update.base_url is not None:
        pc.base_url = provider_update.base_url.rstrip("/")
    if "api_key" in fields:
        pc.api_key = provider_update.api_key
    if "default_model" in fields and provider_update.default_model is not None:
        pc.default_model = provider_update.default_model
    pc.updated_at = utc_now()
    db.commit()
    db.refresh(pc)
    return serialize_provider_config(pc)


@app.delete("/api/provider-configs/{provider_config_id}")
def delete_provider_config(provider_config_id: str, db: Session = Depends(get_db)):
    pc = get_provider_config_or_404(db, provider_config_id)
    db.delete(pc)
    db.commit()
    return {"status": "deleted", "id": provider_config_id}


# --- Operators ---

@app.post("/api/operators")
async def create_operator(
    operator_in: OperatorCreate,
    db: Session = Depends(get_db),
    adapter: ChatAdapter = Depends(get_adapter),
):
    if operator_in.provider_config_id:
        get_provider_config_or_404(db, operator_in.provider_config_id)

    chat_user = await adapter.create_user(operator_in.name)
    now = utc_now()
    op = Operator(
        id=f"op_{uuid.uuid4().hex[:8]}",
        name=operator_in.name,
        adapter_identities={"chat": chat_user["id"]},
        provider_config_id=operator_in.provider_config_id,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return serialize_operator(op, db)


@app.get("/api/operators")
def list_operators(db: Session = Depends(get_db)):
    ops = db.query(Operator).order_by(Operator.created_at.desc()).all()
    return [serialize_operator(o, db) for o in ops]


@app.get("/api/operators/{operator_id}")
def get_operator(operator_id: str, db: Session = Depends(get_db)):
    op = get_operator_or_404(db, operator_id)
    return serialize_operator(op, db)


@app.put("/api/operators/{operator_id}")
def update_operator(operator_id: str, op_update: OperatorUpdate, db: Session = Depends(get_db)):
    op = get_operator_or_404(db, operator_id)
    fields = op_update.model_fields_set
    if "name" in fields and op_update.name is not None:
        op.name = op_update.name
    if "persona_md" in fields:
        op.persona_md = op_update.persona_md
    if "provider_config_id" in fields:
        if op_update.provider_config_id is not None:
            get_provider_config_or_404(db, op_update.provider_config_id)
        op.provider_config_id = op_update.provider_config_id
    if "status" in fields and op_update.status is not None:
        op.status = op_update.status
    op.updated_at = utc_now()
    db.commit()
    db.refresh(op)
    return serialize_operator(op, db)


@app.delete("/api/operators/{operator_id}")
def delete_operator(operator_id: str, db: Session = Depends(get_db)):
    op = get_operator_or_404(db, operator_id)
    op.status = "deleted"
    op.updated_at = utc_now()
    db.commit()
    return {"status": "deleted", "id": operator_id}


# --- Contacts ---

@app.get("/api/operators/{operator_id}/contacts")
def list_contacts(operator_id: str, db: Session = Depends(get_db)):
    get_operator_or_404(db, operator_id)
    items = (
        db.query(Contact)
        .filter(Contact.operator_id == operator_id)
        .order_by(Contact.created_at.desc())
        .all()
    )
    return [serialize_contact(c) for c in items]


@app.get("/api/contacts/{contact_id}")
def get_contact(contact_id: str, db: Session = Depends(get_db)):
    return serialize_contact(get_contact_or_404(db, contact_id))


@app.put("/api/contacts/{contact_id}")
def update_contact(contact_id: str, contact_update: ContactUpdate, db: Session = Depends(get_db)):
    contact = get_contact_or_404(db, contact_id)
    fields = contact_update.model_fields_set
    if "display_name" in fields and contact_update.display_name is not None:
        contact.display_name = contact_update.display_name
    if "card_md" in fields:
        contact.card_md = contact_update.card_md
    if "status" in fields and contact_update.status is not None:
        contact.status = contact_update.status
    contact.updated_at = utc_now()
    db.commit()
    db.refresh(contact)
    return serialize_contact(contact)


# --- Chat Archives ---

@app.post("/api/operators/{operator_id}/chat-archives")
async def upload_chat_archive(
    operator_id: str,
    self_wxid: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    adapter: ChatAdapter = Depends(get_adapter),
):
    op = get_operator_or_404(db, operator_id)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    try:
        archive = await ingest_archive(
            db=db,
            operator=op,
            self_wxid=self_wxid,
            src_path=tmp_path,
            original_filename=file.filename or tmp_path.name,
            chat_adapter=adapter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)

    return serialize_archive(archive)


@app.get("/api/operators/{operator_id}/chat-archives")
def list_archives(operator_id: str, db: Session = Depends(get_db)):
    get_operator_or_404(db, operator_id)
    items = (
        db.query(ChatArchive)
        .filter(ChatArchive.operator_id == operator_id)
        .order_by(ChatArchive.uploaded_at.desc())
        .all()
    )
    return [serialize_archive(a) for a in items]


# --- Distill Jobs ---

@app.post("/api/operators/{operator_id}/distill-jobs")
def create_distill_job(operator_id: str, db: Session = Depends(get_db)):
    op = get_operator_or_404(db, operator_id)
    if not op.provider_config_id:
        raise HTTPException(status_code=400, detail="Operator 未配置 Provider Config，无法蒸馏")
    pending = (
        db.query(DistillJob)
        .filter(
            DistillJob.operator_id == operator_id,
            DistillJob.status.in_(["pending", "running"]),
        )
        .first()
    )
    if pending:
        raise HTTPException(status_code=409, detail=f"已有进行中的蒸馏任务 {pending.id}")
    job = DistillJob(
        id=f"dj_{uuid.uuid4().hex[:8]}",
        operator_id=operator_id,
        status="pending",
        progress={},
        created_at=utc_now(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return serialize_distill_job(job)


@app.get("/api/operators/{operator_id}/distill-jobs")
def list_distill_jobs(operator_id: str, db: Session = Depends(get_db)):
    get_operator_or_404(db, operator_id)
    jobs = (
        db.query(DistillJob)
        .filter(DistillJob.operator_id == operator_id)
        .order_by(DistillJob.created_at.desc())
        .all()
    )
    return [serialize_distill_job(j) for j in jobs]


@app.get("/api/distill-jobs/{job_id}")
def get_distill_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(DistillJob).filter(DistillJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Distill Job 不存在")
    return serialize_distill_job(job)


# --- Sessions (read-only; created internally by ingest) ---

@app.get("/api/operators/{operator_id}/sessions")
def list_sessions(operator_id: str, db: Session = Depends(get_db)):
    get_operator_or_404(db, operator_id)
    sessions = (
        db.query(SessionRecord)
        .join(Contact, Contact.id == SessionRecord.contact_id)
        .filter(Contact.operator_id == operator_id)
        .order_by(SessionRecord.created_at.desc())
        .all()
    )
    return [serialize_session(s) for s in sessions]


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    s = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session 不存在")
    return serialize_session(s)


# --- Planned Replies (long-poll) ---

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
            s = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
            if not s:
                raise HTTPException(status_code=404, detail="Session 不存在")
            replies = (
                db.query(Message)
                .filter(
                    Message.contact_id == s.contact_id,
                    Message.source == "live",
                    Message.role == "self",
                    Message.status == "scheduled",
                )
                .order_by(Message.scheduled_for.asc())
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


# --- Chat Conversations passthrough (for debug UI to pick threads) ---

@app.get("/api/conversations")
async def list_chat_conversations(adapter: ChatAdapter = Depends(get_adapter)):
    try:
        return await adapter.list_conversations()
    except httpx.HTTPStatusError as err:
        raise HTTPException(status_code=err.response.status_code, detail="获取会话列表失败")


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
