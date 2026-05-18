"""initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'user')", name="ck_account_role"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_account_status"),
    )
    op.create_index("ix_accounts_id", "accounts", ["id"])
    op.create_index("ix_accounts_username", "accounts", ["username"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(48), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_id", "auth_sessions", ["id"])
    op.create_index("ix_auth_sessions_account_id", "auth_sessions", ["account_id"])

    op.create_table(
        "provider_configs",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("owner_account_id", sa.String(48), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key", sa.Text, nullable=True),
        sa.Column("default_model", sa.String(128), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('global')", name="ck_provider_scope"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_provider_status"),
    )
    op.create_index("ix_provider_configs_id", "provider_configs", ["id"])
    op.create_index("ix_provider_configs_owner_account_id", "provider_configs", ["owner_account_id"])

    op.create_table(
        "personas",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("account_id", sa.String(48), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("persona_md", sa.Text, nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "name", name="uq_persona_account_name"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_persona_status"),
    )
    op.create_index("ix_personas_id", "personas", ["id"])
    op.create_index("ix_personas_account_id", "personas", ["account_id"])

    op.create_table(
        "bridges",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("account_id", sa.String(48), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("machine_id", sa.String(256), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "machine_id", name="uq_bridge_account_machine_id"),
        sa.CheckConstraint("status IN ('online', 'offline', 'revoked')", name="ck_bridge_status"),
    )
    op.create_index("ix_bridges_id", "bridges", ["id"])
    op.create_index("ix_bridges_account_id", "bridges", ["account_id"])

    op.create_table(
        "inboxes",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("account_id", sa.String(48), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("bridge_id", sa.String(48), sa.ForeignKey("bridges.id"), nullable=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("default_persona_id", sa.String(48), sa.ForeignKey("personas.id"), nullable=True),
        sa.Column("reply_provider_config_id", sa.String(48), sa.ForeignKey("provider_configs.id"), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("platform_self_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_inboxes_id", "inboxes", ["id"])
    op.create_index("ix_inboxes_account_id", "inboxes", ["account_id"])
    op.create_index("ix_inboxes_bridge_id", "inboxes", ["bridge_id"])

    op.create_table(
        "contacts",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("inbox_id", sa.String(48), sa.ForeignKey("inboxes.id"), nullable=False),
        sa.Column("peer_platform_id", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("card_md", sa.Text, nullable=True),
        sa.Column("persona_id", sa.String(48), sa.ForeignKey("personas.id"), nullable=True),
        sa.Column("reply_provider_config_id", sa.String(48), sa.ForeignKey("provider_configs.id"), nullable=True),
        sa.Column("takeover", sa.Boolean, nullable=False),
        sa.Column("reply_policy", sa.String(16), nullable=False),
        sa.Column("pending_reply", sa.Boolean, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_seen_platform_msg_id", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("inbox_id", "peer_platform_id", name="uq_contact_inbox_peer"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_contact_status"),
        sa.CheckConstraint("reply_policy IN ('disabled', 'autoreply')", name="ck_contact_reply_policy"),
    )
    op.create_index("ix_contacts_id", "contacts", ["id"])
    op.create_index("ix_contacts_inbox_id", "contacts", ["inbox_id"])

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("contact_id", sa.String(48), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("external_id", sa.String(256), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("authored_by", sa.String(16), nullable=False),
        sa.Column("msg_type", sa.String(16), nullable=False, server_default="text"),
        sa.Column("sender_name", sa.String(256), nullable=True),
        sa.Column("sender_id", sa.String(256), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("msg_hash", sa.String(64), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("contact_id", "external_id", name="uq_message_contact_external"),
        sa.CheckConstraint("role IN ('self', 'counterpart')", name="ck_message_role"),
        sa.CheckConstraint("authored_by IN ('unknown')", name="ck_message_authored_by"),
        sa.CheckConstraint("msg_type IN ('text', 'image', 'audio', 'video', 'file')", name="ck_message_msg_type"),
    )
    op.create_index("ix_messages_contact_id", "messages", ["contact_id"])
    op.create_index("ix_messages_timestamp", "messages", ["timestamp"])
    op.create_index("idx_msg_contact_ts", "messages", ["contact_id", "timestamp"])
    op.create_index(
        "idx_message_msg_hash",
        "messages",
        ["contact_id", "msg_hash"],
        unique=True,
        postgresql_where=sa.text("msg_hash IS NOT NULL"),
    )

    op.create_table(
        "media_hashes",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(48), nullable=False),
        sa.Column("content_hash", sa.String(71), nullable=False),
        sa.Column("storage_key", sa.String(256), nullable=False),
        sa.UniqueConstraint("account_id", "content_hash", name="uq_media_hash_account"),
    )
    op.create_index("idx_media_hash_account", "media_hashes", ["account_id"])

    op.create_table(
        "distill_jobs",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("account_id", sa.String(48), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("contact_ids", postgresql.JSONB, nullable=False),
        sa.Column("target_persona_id", sa.String(48), sa.ForeignKey("personas.id"), nullable=True),
        sa.Column("provider_config_id", sa.String(48), sa.ForeignKey("provider_configs.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", postgresql.JSONB, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'running', 'done', 'failed')", name="ck_distill_status"),
    )
    op.create_index("ix_distill_jobs_id", "distill_jobs", ["id"])
    op.create_index("ix_distill_jobs_account_id", "distill_jobs", ["account_id"])
    op.create_index("ix_distill_jobs_target_persona_id", "distill_jobs", ["target_persona_id"])
    op.create_index("ix_distill_jobs_provider_config_id", "distill_jobs", ["provider_config_id"])

    op.create_table(
        "outbound_messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("inbox_id", sa.String(48), sa.ForeignKey("inboxes.id"), nullable=False),
        sa.Column("contact_id", sa.String(48), sa.ForeignKey("contacts.id"), nullable=False),
        sa.Column("msg_type", sa.String(16), nullable=False, server_default="text"),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("send_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'delivered', 'failed', 'canceled')", name="ck_outbound_status"),
        sa.CheckConstraint("msg_type IN ('text', 'image', 'audio', 'video', 'file')", name="ck_outbound_msg_type"),
    )
    op.create_index("ix_outbound_messages_inbox_id", "outbound_messages", ["inbox_id"])
    op.create_index("ix_outbound_messages_contact_id", "outbound_messages", ["contact_id"])
    op.create_index("idx_outbound_inbox_id", "outbound_messages", ["inbox_id", "id"])
    op.create_index("idx_outbound_send_after", "outbound_messages", ["status", "send_after"])

    op.create_table(
        "llm_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("persona_id", sa.String(48), nullable=True),
        sa.Column("inbox_id", sa.String(48), nullable=True),
        sa.Column("request_messages", sa.Text, nullable=False),
        sa.Column("response_raw", sa.Text, nullable=False),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("purpose IN ('distill', 'reply')", name="ck_llm_log_purpose"),
    )
    op.create_index("ix_llm_logs_persona_id", "llm_logs", ["persona_id"])
    op.create_index("ix_llm_logs_inbox_id", "llm_logs", ["inbox_id"])


def downgrade() -> None:
    op.drop_table("llm_logs")
    op.drop_table("outbound_messages")
    op.drop_table("distill_jobs")
    op.drop_table("media_hashes")
    op.drop_table("messages")
    op.drop_table("contacts")
    op.drop_table("inboxes")
    op.drop_table("bridges")
    op.drop_table("personas")
    op.drop_table("provider_configs")
    op.drop_table("auth_sessions")
    op.drop_table("accounts")
