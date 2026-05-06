import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

storage_dir_value = os.environ.get("CHAT_STORAGE_DIR")
if not storage_dir_value:
    raise RuntimeError("CHAT_STORAGE_DIR is required")

STORAGE_DIR = Path(storage_dir_value).resolve()
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = STORAGE_DIR / "chat.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_database():
    from chat import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
