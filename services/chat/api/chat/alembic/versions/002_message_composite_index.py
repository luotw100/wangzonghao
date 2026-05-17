"""composite index on chat_messages (conversation_id, id)

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
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.create_index(
        "ix_chat_messages_conversation_id_id",
        "chat_messages",
        ["conversation_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_conversation_id_id", table_name="chat_messages")
    op.create_index(
        "ix_chat_messages_conversation_id",
        "chat_messages",
        ["conversation_id"],
    )
