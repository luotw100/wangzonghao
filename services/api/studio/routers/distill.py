"""Distill job endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from studio.db import get_db, utc_now
from studio.deps import (
    CurrentAccountDep,
    get_account_conversation,
    get_account_persona,
    new_id,
)
from studio.enums import DistillJobStatus
from studio.models import DistillJob, Inbox
from studio.schemas import DistillJobCreate, DistillJobRead, DistillJobSummary

router = APIRouter()


@router.get("/api/distill-jobs", response_model=list[DistillJobSummary])
def list_distill_jobs(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取当前账号的蒸馏任务列表（瘦版），按创建时间降序排列。"""
    return (
        db.query(DistillJob)
        .filter(DistillJob.account_id == account.id)
        .order_by(DistillJob.created_at.desc())
        .all()
    )


@router.post("/api/distill-jobs", response_model=DistillJobRead, status_code=201)
def create_distill_job(
    payload: DistillJobCreate,
    db: Annotated[Session, Depends(get_db)],
    account: CurrentAccountDep,
):
    """创建蒸馏任务（异步）。"""
    conversation_ids = list(dict.fromkeys(payload.conversation_ids))
    conversations = [get_account_conversation(db, account, cid) for cid in conversation_ids]
    first_inbox = db.query(Inbox).filter(Inbox.id == conversations[0].inbox_id).first()
    account_id = first_inbox.account_id

    if payload.target_persona_id is not None:
        get_account_persona(db, account, payload.target_persona_id)

    in_flight = (
        db.query(DistillJob)
        .filter(
            DistillJob.account_id == account_id,
            DistillJob.status.in_(
                [DistillJobStatus.PENDING, DistillJobStatus.RUNNING]
            ),
        )
        .all()
    )
    requested = set(conversation_ids)
    for ex in in_flight:
        if requested.intersection(ex.conversation_ids or []):
            raise HTTPException(
                status_code=409,
                detail=f"选中的会话已有进行中的蒸馏任务 {ex.id}",
            )
        if payload.target_persona_id and ex.target_persona_id == payload.target_persona_id:
            raise HTTPException(
                status_code=409,
                detail=f"该人设已有进行中的蒸馏任务 {ex.id}",
            )

    j = DistillJob(
        id=new_id("dj"),
        account_id=account_id,
        conversation_ids=conversation_ids,
        target_persona_id=payload.target_persona_id,
        provider_config_id=account.distill_provider_id,
        status=DistillJobStatus.PENDING,
        progress={},
        error_message="",
        created_at=utc_now(),
        started_at=None,
        finished_at=None,
    )
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


@router.get("/api/distill-jobs/{job_id}", response_model=DistillJobRead)
def get_distill_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
    account: CurrentAccountDep,
):
    j = (
        db.query(DistillJob)
        .filter(DistillJob.id == job_id, DistillJob.account_id == account.id)
        .first()
    )
    if not j:
        raise HTTPException(status_code=404, detail="Distill Job 不存在")
    return j
