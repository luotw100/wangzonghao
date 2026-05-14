"""bridge inbound sync redesign: msg_hash, sender_id, media_hashes

Revision ID: 002
Revises: 001
Create Date: 2026-05-14 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add msg_hash and sender_id to messages table.
    op.add_column("messages", sa.Column("msg_hash", sa.String(64), nullable=True))
    op.add_column("messages", sa.Column("sender_id", sa.String(256), nullable=True))

    # Partial unique index: only enforced when msg_hash IS NOT NULL.
    # Existing rows (msg_hash=NULL) are unaffected.
    op.create_index(
        "idx_message_msg_hash",
        "messages",
        ["contact_id", "msg_hash"],
        unique=True,
        postgresql_where=sa.text("msg_hash IS NOT NULL"),
    )

    # media_hashes: maps (account_id, content_hash) → storage_key.
    # Allows check-or-presign to skip S3 re-uploads for duplicate files.
    op.create_table(
        "media_hashes",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(48), nullable=False),
        sa.Column("content_hash", sa.String(71), nullable=False),
        sa.Column("storage_key", sa.String(256), nullable=False),
        sa.UniqueConstraint("account_id", "content_hash", name="uq_media_hash_account"),
    )
    op.create_index("idx_media_hash_account", "media_hashes", ["account_id"])


def downgrade() -> None:
    op.drop_index("idx_media_hash_account", table_name="media_hashes")
    op.drop_table("media_hashes")
    op.drop_index("idx_message_msg_hash", table_name="messages")
    op.drop_column("messages", "sender_id")
    op.drop_column("messages", "msg_hash")
