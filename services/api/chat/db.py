"""Chat sandbox shares the studio engine + connection pool, but holds its
own SQLAlchemy Base/registry so that ``Conversation`` / ``Message`` class
names don't collide with studio's models. Both Bases register tables on
their respective ``MetaData``; alembic combines them at migration time.
"""

from sqlalchemy.orm import DeclarativeBase

# Re-export the shared infrastructure so chat code reads the same engine,
# pool and MetaData without re-creating any. Chat keeps its own
# DeclarativeBase subclass so string-based ``relationship("Conversation")``
# resolves within chat's class registry instead of colliding with studio's
# identically-named class; both bases share ``metadata`` so cross-schema
# FKs (chat.contacts.account_id → auth.accounts.id) resolve at flush time.
from studio.db import SessionLocal, engine, get_db, metadata, utc_now  # noqa: F401


class Base(DeclarativeBase):
    metadata = metadata
