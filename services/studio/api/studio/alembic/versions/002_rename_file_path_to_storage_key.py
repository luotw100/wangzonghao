"""rename archives.file_path to storage_key

Revision ID: 002
Revises: 001
Create Date: 2025-01-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("archives", "file_path", new_column_name="storage_key")


def downgrade() -> None:
    op.alter_column("archives", "storage_key", new_column_name="file_path")