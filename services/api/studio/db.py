import os
from datetime import datetime, timezone

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL is required")

# Connection budget — shared by every process that imports this engine
# (user-api ×4 uvicorn workers, admin-api ×1, user-worker ×1). Each process
# gets its own pool, so the fleet total must fit Postgres' max_connections=100:
#
#     (4 + 1 + 1) × (pool_size + max_overflow)  +  4 (asyncpg NOTIFY brokers, 1/user-api worker)
#       = 6 × 14 + 4 = 88  ≤  ~90  (100 − ~10 reserved for psql/migrate/superuser)
#
# To scale: raise max_connections AND pool_size/max_overflow together, keeping
# the fleet total under the new ceiling. Once a single Postgres can't grow
# max_connections further, front it with PgBouncer (transaction pooling) — the
# long-poll endpoint releases its connection between queries, so it pools well.
engine = create_engine(database_url, pool_size=6, max_overflow=8)
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
