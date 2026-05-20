from __future__ import annotations

from sqlalchemy.orm import Session

from studio.models import ProviderConfig


def get_default_provider(db: Session) -> ProviderConfig | None:
    """Return the most recently updated provider as the system default.

    Future work: per-contact / per-distill provider routing via
    Contact.provider_id / DistillJob.provider_config_id (already wired).
    """
    return (
        db.query(ProviderConfig)
        .order_by(ProviderConfig.updated_at.desc())
        .first()
    )
