"""Distill job endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from studio.db import get_db
from studio.deps import CurrentAccountDep, get_account_contact, get_account_persona, new_id
from studio.db import utc_now
from studio.enums import DistillJobStatus
from studio.models import DistillJob, Inbox
from studio.provider_policy import get_default_provider
from studio.schemas import DistillJobCreate
from studio.serializers import s_distill_job

router = APIRouter()


@router.get("/api/distill-jobs")
def list_distill_jobs(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取当前账号的蒸馏任务列表，按创建时间降序排列。"""
    query = db.query(DistillJob).filter(DistillJob.account_id == account.id)
    items = query.order_by(DistillJob.created_at.desc()).all()
    return [s_distill_job(j) for j in items]


@router.post("/api/distill-jobs")
def create_distill_job(payload: DistillJobCreate, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """创建蒸馏任务（异步执行）。

    任务创建后状态为 pending，由后台 worker 异步处理，状态流转：pending → running → done / failed。
    可通过 GET /api/distill-jobs/{job_id} 轮询进度。

    冲突检测（返回 409 的情况）：
    - 选中的某个联系人已在另一个 pending/running 任务中；
    - 指定的目标人设已在另一个 pending/running 任务中；
    - 没有可用的全局默认 Provider（未配置任何 Provider 时）。
    """
    if not payload.contact_ids:
        raise HTTPException(status_code=422, detail="contact_ids 不能为空")
    contact_ids = list(dict.fromkeys(payload.contact_ids))  # dedup, keep order
    contacts = [get_account_contact(db, account, cid) for cid in contact_ids]
    first_inbox = db.query(Inbox).filter(Inbox.id == contacts[0].inbox_id).first()
    account_id = first_inbox.account_id

    if payload.target_persona_id is not None:
        get_account_persona(db, account, payload.target_persona_id)
    provider_config = get_default_provider(db)
    if not provider_config:
        raise HTTPException(status_code=409, detail="没有可用的全局默认 Provider")

    in_flight = (
        db.query(DistillJob).filter(
            DistillJob.account_id == account_id,
            DistillJob.status.in_([DistillJobStatus.PENDING, DistillJobStatus.RUNNING]),
        ).all()
    )
    requested = set(contact_ids)
    for ex in in_flight:
        if requested.intersection(ex.contact_ids or []):
            raise HTTPException(status_code=409, detail=f"选中的联系人已有进行中的蒸馏任务 {ex.id}")
        if payload.target_persona_id and ex.target_persona_id == payload.target_persona_id:
            raise HTTPException(status_code=409, detail=f"该人设已有进行中的蒸馏任务 {ex.id}")

    j = DistillJob(
        id=new_id("dj"), account_id=account_id,
        contact_ids=contact_ids,
        target_persona_id=payload.target_persona_id,
        provider_config_id=provider_config.id,
        status=DistillJobStatus.PENDING, progress={}, error_message="",
        created_at=utc_now(), started_at=None, finished_at=None,
    )
    db.add(j); db.commit(); db.refresh(j)
    return s_distill_job(j)


@router.get("/api/distill-jobs/{job_id}")
def get_distill_job(job_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取单个蒸馏任务的详情和当前进度。"""
    query = db.query(DistillJob).filter(
        DistillJob.id == job_id, DistillJob.account_id == account.id
    )
    j = query.first()
    if not j:
        raise HTTPException(status_code=404, detail="Distill Job 不存在")
    return s_distill_job(j)
