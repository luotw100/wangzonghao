"""Persona CRUD endpoints."""

from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from studio.db import get_db, utc_now
from studio.deps import CurrentAccountDep, get_account_persona, new_id
from studio.models import Conversation, Persona
from studio.schemas import PersonaCreate, PersonaRead, PersonaSummary, PersonaUpdate

router = APIRouter()


def _validate_timezone(tz: str) -> str:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, KeyError):
        raise HTTPException(status_code=422, detail=f"无效的时区名称: {tz!r}")
    return tz


@router.get("/api/personas", response_model=list[PersonaSummary])
def list_personas(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取当前账号的人设列表（瘦版，不含 persona_md），按创建时间降序排列。

    需要 markdown 正文时调用 GET /api/personas/{id}。
    """
    return (
        db.query(Persona)
        .filter(Persona.account_id == account.id)
        .order_by(Persona.created_at.desc())
        .all()
    )


@router.post("/api/personas", response_model=PersonaRead, status_code=status.HTTP_201_CREATED)
def create_persona(payload: PersonaCreate, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """创建人设。同一账号下名称不可重复。"""
    tz = _validate_timezone(payload.timezone)
    now = utc_now()
    p = Persona(
        id=new_id("ps"), account_id=account.id,
        name=payload.name, persona_md=payload.persona_md or "",
        timezone=tz, created_at=now, updated_at=now,
    )
    db.add(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="同名人设已存在")
    db.refresh(p)
    return p


@router.get("/api/personas/{persona_id}", response_model=PersonaRead)
def get_persona(persona_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取单个人设详情（含 persona_md）。"""
    return get_account_persona(db, account, persona_id)


@router.patch("/api/personas/{persona_id}", response_model=PersonaRead)
def update_persona(persona_id: str, payload: PersonaUpdate, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """更新人设。只传需要修改的字段。"""
    p = get_account_persona(db, account, persona_id)
    fields = payload.model_fields_set
    if "name" in fields and payload.name is not None:
        p.name = payload.name
    if "persona_md" in fields and payload.persona_md is not None:
        p.persona_md = payload.persona_md
    if "timezone" in fields and payload.timezone is not None:
        p.timezone = _validate_timezone(payload.timezone)
    p.updated_at = utc_now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="同名人设已存在")
    db.refresh(p)
    return p


@router.delete("/api/personas/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_persona(persona_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """删除人设。若该人设仍被任一 Conversation 引用，返回 409。"""
    p = get_account_persona(db, account, persona_id)
    in_use_count = db.query(Conversation).filter(Conversation.persona_id == p.id).count()
    if in_use_count:
        raise HTTPException(status_code=409, detail=f"Persona 仍被 {in_use_count} 个会话引用")
    db.delete(p)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
