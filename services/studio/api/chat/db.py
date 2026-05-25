"""Chat sandbox shares the studio engine + connection pool, but holds its
own SQLAlchemy Base/registry so that ``Conversation`` / ``Message`` class
names don't collide with studio's models. Both Bases register tables on
their respective ``MetaData``; alembic combines them at migration time.
"""

from sqlalchemy.orm import DeclarativeBase

# Re-export the shared infrastructure so chat code reads the same engine
# and pool without re-creating either. This is the *only* cross-package
# dependency chat takes on studio: schema-creation, connection pool,
# session factory and utc_now. Auth tables live in the shared "auth"
# schema; everything else respects the chat/studio split.
from studio.db import SessionLocal, engine, get_db, utc_now  # noqa: F401


class Base(DeclarativeBase):
    """Chat-only declarative base. Distinct from studio's ``Base`` so
    string-based ``relationship("Conversation")`` resolves within chat's
    registry instead of colliding with studio's identically-named class.
    """
