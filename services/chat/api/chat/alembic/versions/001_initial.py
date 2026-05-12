"""initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_accounts",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("avatar_url", sa.String(512), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_chat_account_status"),
    )
    op.create_index("ix_chat_accounts_id", "chat_accounts", ["id"])
    op.create_index("ix_chat_accounts_username", "chat_accounts", ["username"])

    op.create_table(
        "chat_auth_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(48), sa.ForeignKey("chat_accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_auth_sessions_id", "chat_auth_sessions", ["id"])
    op.create_index("ix_chat_auth_sessions_account_id", "chat_auth_sessions", ["account_id"])

    op.create_table(
        "chat_contacts",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("account_id", sa.String(48), sa.ForeignKey("chat_accounts.id"), nullable=False),
        sa.Column("platform_contact_id", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("avatar_url", sa.String(512), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "platform_contact_id", name="uq_chat_contact_platform_id"),
    )
    op.create_index("ix_chat_contacts_id", "chat_contacts", ["id"])
    op.create_index("ix_chat_contacts_account_id", "chat_contacts", ["account_id"])
    op.create_index("ix_chat_contacts_platform_contact_id", "chat_contacts", ["platform_contact_id"])

    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("account_id", sa.String(48), sa.ForeignKey("chat_accounts.id"), nullable=False),
        sa.Column("contact_id", sa.String(48), sa.ForeignKey("chat_contacts.id"), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("is_deleted", sa.Boolean, nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "contact_id", name="uq_chat_direct_conversation"),
    )
    op.create_index("ix_chat_conversations_id", "chat_conversations", ["id"])
    op.create_index("ix_chat_conversations_account_id", "chat_conversations", ["account_id"])
    op.create_index("ix_chat_conversations_contact_id", "chat_conversations", ["contact_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(48), sa.ForeignKey("chat_accounts.id"), nullable=False),
        sa.Column("conversation_id", sa.String(48), sa.ForeignKey("chat_conversations.id"), nullable=False),
        sa.Column("sender_type", sa.String(16), nullable=False),
        sa.Column("sender_contact_id", sa.String(48), sa.ForeignKey("chat_contacts.id"), nullable=True),
        sa.Column("msg_type", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sender_type IN ('self', 'contact')", name="ck_chat_msg_sender_type"),
        sa.CheckConstraint("msg_type IN ('text', 'image', 'audio', 'video', 'file')", name="ck_chat_msg_type"),
        sa.CheckConstraint("source IN ('live', 'import')", name="ck_chat_msg_source"),
    )
    op.create_index("ix_chat_messages_account_id", "chat_messages", ["account_id"])
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])
    op.create_index("ix_chat_messages_sender_contact_id", "chat_messages", ["sender_contact_id"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")
    op.drop_table("chat_contacts")
    op.drop_table("chat_auth_sessions")
    op.drop_table("chat_accounts")