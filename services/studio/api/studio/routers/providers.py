"""ProviderConfig CRUD endpoints (admin-only)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from studio.clients import ALLOWED_BASE_URLS
from studio.db import get_db, utc_now
from studio.deps import AdminAccountDep, get_provider_or_404, new_id
from studio.enums import ProviderScope, ProviderStatus
from studio.models import ProviderConfig
from studio.schemas import ProviderConfigCreate, ProviderConfigUpdate
from studio.serializers import s_provider

router = APIRouter()


def _validate_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized not in ALLOWED_BASE_URLS:
        raise HTTPException(
            status_code=400,
            detail=f"base_url {base_url!r} 不在白名单中",
        )
    return normalized


@router.get("/api/provider-configs")
def list_providers(db: Annotated[Session, Depends(get_db)], account: AdminAccountDep):
    """获取所有 LLM Provider 配置（仅管理员可调用），按最后更新时间降序排列。"""
    items = (
        db.query(ProviderConfig)
        .order_by(ProviderConfig.updated_at.desc())
        .all()
    )
    return [s_provider(p) for p in items]


@router.post("/api/provider-configs")
def create_provider(payload: ProviderConfigCreate, db: Annotated[Session, Depends(get_db)], account: AdminAccountDep):
    """创建 LLM Provider 配置（仅管理员可调用）。

    每次创建都会成为新的默认 Provider（旧的 is_default 被清除）。
    base_url 必须在系统白名单中，否则返回 400。
    """
    now = utc_now()
    db.query(ProviderConfig).filter(ProviderConfig.is_default.is_(True)).update(
        {ProviderConfig.is_default: False, ProviderConfig.updated_at: now},
        synchronize_session=False,
    )
    p = ProviderConfig(
        id=new_id("p"), owner_account_id=account.id,
        name=payload.name, base_url=_validate_base_url(payload.base_url),
        api_key=payload.api_key, default_model=payload.default_model,
        scope=ProviderScope.GLOBAL,
        status=ProviderStatus.ACTIVE,
        is_default=True,
        created_at=now, updated_at=now,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return s_provider(p)


@router.put("/api/provider-configs/{provider_id}")
def update_provider(
    provider_id: str, payload: ProviderConfigUpdate, db: Annotated[Session, Depends(get_db)], account: AdminAccountDep
):
    """更新 LLM Provider 配置（仅管理员可调用）。只传需要修改的字段。"""
    p = get_provider_or_404(db, provider_id)
    fields = payload.model_fields_set
    if "name" in fields and payload.name is not None:
        p.name = payload.name
    if "base_url" in fields and payload.base_url is not None:
        p.base_url = _validate_base_url(payload.base_url)
    if "api_key" in fields:
        p.api_key = payload.api_key
    if "default_model" in fields and payload.default_model is not None:
        p.default_model = payload.default_model
    p.updated_at = utc_now()
    db.commit()
    db.refresh(p)
    return s_provider(p)


@router.delete("/api/provider-configs/{provider_id}")
def delete_provider(provider_id: str, db: Annotated[Session, Depends(get_db)], account: AdminAccountDep):
    """删除 LLM Provider 配置（仅管理员可调用）。"""
    p = get_provider_or_404(db, provider_id)
    db.delete(p)
    db.commit()
    return {"status": "deleted", "id": provider_id}
