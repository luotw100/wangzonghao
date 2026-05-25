import os
from datetime import datetime, timezone

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is required")

engine = create_engine(database_url, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Shared across studio.Base and chat.Base so cross-schema FKs
# (chat.contacts.account_id → auth.accounts.id) resolve at flush time.
# Class-name registries stay per-Base, so chat.Conversation and
# studio.Conversation can co-exist.
metadata = MetaData()


class Base(DeclarativeBase):
    metadata = metadata


SCHEMAS = ("auth", "studio", "chat")


def ensure_schemas() -> None:
    """Create the three logical schemas if missing.

    Boundary rule: every table lives under exactly one of these.
    ``auth`` is the only shared layer (accounts, auth_sessions); ``studio``
    and ``chat`` business tables stay strictly within their package.
    """
    with engine.begin() as conn:
        for s in SCHEMAS:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{s}"'))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
