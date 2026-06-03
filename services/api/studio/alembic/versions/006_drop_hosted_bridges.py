"""drop hosted_bridges — remove the cloud-hosted bridge supervisor

The ``bridge-host`` service and its admin-driven cloud bridges are gone;
bridges now run only on operator/desktop machines. Drop the table that
backed the admin panel's hosted-bridge view.

Revision ID: 006
Revises: 005
Create Date: 2026-06-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("hosted_bridges", schema="studio")


def downgrade() -> None:
    op.create_table(
        "hosted_bridges",
        sa.Column("account_id", sa.String(48),
                  sa.ForeignKey("auth.accounts.id"), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("machine_id", sa.String(256), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('stopped', 'starting', 'running', 'auth_error', 'crashed')",
            name="ck_hosted_bridge_status",
        ),
        schema="studio",
    )
