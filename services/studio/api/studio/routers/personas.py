"""Persona CRUD endpoints."""

from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from studio.db import get_db, utc_now
from studio.deps import CurrentAccountDep, get_account_persona, new_id
from studio.models import Contact, Persona
from studio.schemas import PersonaCreate, PersonaUpdate
from studio.serializers import s_persona

router = APIRouter()


def _validate_timezone(tz: str) -> str:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, KeyError):
        raise HTTPException(status_code=422, detail=f"无效的时区名称: {tz!r}")
    return tz


@router.get("/api/personas")
def list_personas(db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取当前账号的人设列表，按创建时间降序排列。"""
    query = db.query(Persona).filter(Persona.account_id == account.id)
    items = query.order_by(Persona.created_at.desc()).all()
    return [s_persona(p) for p in items]


@router.post("/api/personas")
def create_persona(payload: PersonaCreate, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """创建人设。同一账号下名称不可重复。"""
    tz = _validate_timezone(payload.timezone)
    now = utc_now()
    p = Persona(
        id=new_id("ps"), account_id=account.id,
        name=payload.name, persona_md=payload.persona_md or "",
        timezone=tz, created_at=now, updated_at=now,
    )
    db.add(p); db.commit(); db.refresh(p)
    return s_persona(p)


@router.get("/api/personas/{persona_id}")
def get_persona(persona_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """获取单个人设详情。"""
    return s_persona(get_account_persona(db, account, persona_id))


@router.put("/api/personas/{persona_id}")
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
    db.commit(); db.refresh(p)
    return s_persona(p)


@router.delete("/api/personas/{persona_id}")
def delete_persona(persona_id: str, db: Annotated[Session, Depends(get_db)], account: CurrentAccountDep):
    """删除人设。若该人设仍被某个 Contact 引用，返回 409。"""
    p = get_account_persona(db, account, persona_id)
    in_use_contact = db.query(Contact).filter(Contact.persona_id == p.id).first()
    if in_use_contact:
        raise HTTPException(status_code=409, detail=f"Persona 仍被 contact {in_use_contact.id} 引用")
    db.delete(p); db.commit()
    return {"status": "deleted", "id": persona_id}
