"""Run alembic upgrade head against the unified DB.

Schemas (auth / studio / chat) are created first because alembic's
own ``alembic_version`` table needs the ``studio`` schema to exist
before the first migration registers itself there.
"""

import os

from alembic import command
from alembic.config import Config

from studio.db import ensure_schemas


def run_migrations() -> None:
    ensure_schemas()
    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", "studio/alembic")
    alembic_cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(alembic_cfg, "head")


if __name__ == "__main__":
    run_migrations()
