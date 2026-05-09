from __future__ import annotations

from sqlalchemy.orm import Session

from studio.enums import ProviderScope, ProviderStatus
from studio.models import ProviderConfig


def get_default_provider(db: Session) -> ProviderConfig | None:
    return (
        db.query(ProviderConfig)
        .filter(
            ProviderConfig.scope == ProviderScope.GLOBAL,
            ProviderConfig.status == ProviderStatus.ACTIVE,
            ProviderConfig.is_default.is_(True),
        )
        .order_by(ProviderConfig.updated_at.desc())
        .first()
    )


def resolve_provider_config(db: Session, provider_id: str | None = None) -> ProviderConfig | None:
    if provider_id:
        return (
            db.query(ProviderConfig)
            .filter(ProviderConfig.id == provider_id, ProviderConfig.status == ProviderStatus.ACTIVE)
            .first()
        )
    return get_default_provider(db)
