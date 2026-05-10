"""Archive upload and distill job endpoints."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from studio.db import get_db
from studio.deps import CurrentAccountDep, get_account_inbox, get_account_persona, is_admin
from studio.distill.ingest import ingest_archive
from studio.enums import DistillJobStatus
from studio.models import DistillJob
from studio.provider_policy import resolve_provider_config
from studio.schemas import DistillJobCreate
from studio.serializers import s_archive, s_distill_job

router = APIRouter()


@router.get("/api/archives")
def list_archives(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    from studio.models import Archive
    query = db.query(Archive)
    if not is_admin(account):
        query = query.filter(Archive.account_id == account.id)
    items = query.order_by(Archive.uploaded_at.desc()).all()
    return [s_archive(a) for a in items]


@router.post("/api/archives")
async def upload_archive(
    db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep,
    inbox_id: str = Form(...), platform_self_id: str = Form(...), file: UploadFile = File(...),
):
    import tempfile
    inbox = get_account_inbox(db, account, inbox_id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
        contents = await file.read()
        tmp.write(contents)
        tmp_path = Path(tmp.name)
    try:
        archive = await ingest_archive(
            db=db, account_id=inbox.account_id, inbox=inbox,
            platform_self_id=platform_self_id, src_path=tmp_path,
            original_filename=file.filename or tmp_path.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)
    return s_archive(archive)


@router.get("/api/distill-jobs")
def list_distill_jobs(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    query = db.query(DistillJob)
    if not is_admin(account):
        query = query.filter(DistillJob.account_id == account.id)
    items = query.order_by(DistillJob.created_at.desc()).all()
    return [s_distill_job(j) for j in items]


@router.post("/api/distill-jobs")
def create_distill_job(payload: DistillJobCreate, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    from studio.deps import new_id
    from studio.db import utc_now
    inbox = get_account_inbox(db, account, payload.source_inbox_id)
    get_account_persona(db, account, payload.target_persona_id)
    if payload.provider_config_id is not None and not is_admin(account):
        raise HTTPException(status_code=403, detail="只有管理员可以指定 Provider")
    provider_config = resolve_provider_config(db, payload.provider_config_id)
    if not provider_config:
        raise HTTPException(status_code=409, detail="没有可用的全局默认 Provider")
    pending = (
        db.query(DistillJob).filter(
            DistillJob.account_id == inbox.account_id,
            DistillJob.target_persona_id == payload.target_persona_id,
            DistillJob.status.in_([DistillJobStatus.PENDING, DistillJobStatus.RUNNING]),
        ).first()
    )
    if pending:
        raise HTTPException(status_code=409, detail=f"该 persona 已有进行中的蒸馏任务 {pending.id}")
    j = DistillJob(
        id=new_id("dj"), account_id=inbox.account_id,
        source_inbox_id=payload.source_inbox_id,
        target_persona_id=payload.target_persona_id,
        provider_config_id=provider_config.id,
        status=DistillJobStatus.PENDING, progress={}, error_message=None,
        created_at=utc_now(), started_at=None, finished_at=None,
    )
    db.add(j); db.commit(); db.refresh(j)
    return s_distill_job(j)


@router.get("/api/distill-jobs/{job_id}")
def get_distill_job(job_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    query = db.query(DistillJob).filter(DistillJob.id == job_id)
    if not is_admin(account):
        query = query.filter(DistillJob.account_id == account.id)
    j = query.first()
    if not j:
        raise HTTPException(status_code=404, detail="Distill Job 不存在")
    return s_distill_job(j)
