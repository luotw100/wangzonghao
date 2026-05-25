from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing both packages registers all tables on their respective Bases.
# We don't autogenerate migrations from this metadata — 001 is written by
# hand — but loading them keeps env.py honest if anyone runs `alembic
# revision --autogenerate` locally.
from studio.db import Base as StudioBase  # noqa: F401
from studio import models as _studio_models  # noqa: F401
from chat import models as _chat_models  # noqa: F401

config = context.config

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError("DATABASE_URL environment variable is required")
config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 001 is hand-written and creates tables across multiple schemas. We
# don't use autogenerate, so target_metadata is informational only.
target_metadata = StudioBase.metadata

VERSION_SCHEMA = "studio"


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=VERSION_SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=VERSION_SCHEMA,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
