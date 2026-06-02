"""releases + download_events

桌面应用分发：releases 是「已发布安装包目录 + 当前指针」（is_latest），
download_events 是「谁下了哪个版本」的审计 log。安装包字节在 S3
releases/<version>/<filename>，这两张表都不存二进制。

Revision ID: 004
Revises: 003
Create Date: 2026-06-02 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "releases",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("s3_key", sa.String(512), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_latest", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("platform IN ('win', 'mac', 'linux')", name="ck_release_platform"),
        sa.UniqueConstraint("version", "platform", name="uq_release_version_platform"),
        schema="studio",
    )
    op.create_index("ix_releases_id", "releases", ["id"], schema="studio")
    # At most one current release per platform.
    op.create_index(
        "ix_releases_latest_per_platform", "releases", ["platform"],
        unique=True, schema="studio", postgresql_where=sa.text("is_latest"),
    )

    op.create_table(
        "download_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(48), nullable=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="studio",
    )
    op.create_index(
        "ix_download_events_account_id", "download_events", ["account_id"], schema="studio"
    )
    op.create_index(
        "ix_download_events_created_at", "download_events", ["created_at"], schema="studio"
    )


def downgrade() -> None:
    op.drop_index("ix_download_events_created_at", table_name="download_events", schema="studio")
    op.drop_index("ix_download_events_account_id", table_name="download_events", schema="studio")
    op.drop_table("download_events", schema="studio")
    op.drop_index("ix_releases_latest_per_platform", table_name="releases", schema="studio")
    op.drop_index("ix_releases_id", table_name="releases", schema="studio")
    op.drop_table("releases", schema="studio")
