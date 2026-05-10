"""Database migration helper."""

import os

from alembic import command
from alembic.config import Config


def run_migrations() -> None:
    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", "studio/alembic")
    alembic_cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(alembic_cfg, "head")