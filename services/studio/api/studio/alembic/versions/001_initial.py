"""initial schema (auth / studio / chat)

Single fresh migration for the merged service:
  * ``auth``   — shared identity (accounts, auth_sessions)
  * ``studio`` — control plane (personas, inboxes, bridges, conversations, ...)
  * ``chat``   — sandbox channel (contacts, conversations, messages)

Revision ID: 001
Revises:
Create Date: 2026-05-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Schemas. Idempotent so ensure_schemas() before alembic and this
    # migration are both safe to run on a clean DB.
    op.execute('CREATE SCHEMA IF NOT EXISTS "auth"')
    op.execute('CREATE SCHEMA IF NOT EXISTS "studio"')
    op.execute('CREATE SCHEMA IF NOT EXISTS "chat"')

    # ---------------- studio.provider_configs ----------------
    op.create_table(
        "provider_configs",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("api_key", sa.Text, nullable=True),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_provider_name"),
        schema="studio",
    )
    op.create_index("ix_provider_configs_id", "provider_configs", ["id"], schema="studio")

    # ---------------- auth.accounts ----------------
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("distill_provider_id", sa.String(48),
                  sa.ForeignKey("studio.provider_configs.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_account_status"),
        schema="auth",
    )
    op.create_index("ix_accounts_id", "accounts", ["id"], schema="auth")
    op.create_index("ix_accounts_username", "accounts", ["username"], schema="auth")
    op.create_index("ix_accounts_distill_provider_id", "accounts", ["distill_provider_id"], schema="auth")

    # ---------------- auth.auth_sessions ----------------
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(48),
                  sa.ForeignKey("auth.accounts.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="auth",
    )
    op.create_index("ix_auth_sessions_id", "auth_sessions", ["id"], schema="auth")
    op.create_index("ix_auth_sessions_account_id", "auth_sessions", ["account_id"], schema="auth")

    # ---------------- studio.personas ----------------
    op.create_table(
        "personas",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("account_id", sa.String(48),
                  sa.ForeignKey("auth.accounts.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("persona_md", sa.Text, nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "name", name="uq_persona_account_name"),
        schema="studio",
    )
    op.create_index("ix_personas_id", "personas", ["id"], schema="studio")
    op.create_index("ix_personas_account_id", "personas", ["account_id"], schema="studio")

    # ---------------- studio.bridges ----------------
    op.create_table(
        "bridges",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("account_id", sa.String(48),
                  sa.ForeignKey("auth.accounts.id"), nullable=False),
        sa.Column("machine_id", sa.String(256), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "machine_id", name="uq_bridge_account_machine_id"),
        schema="studio",
    )
    op.create_index("ix_bridges_id", "bridges", ["id"], schema="studio")
    op.create_index("ix_bridges_account_id", "bridges", ["account_id"], schema="studio")

    # ---------------- studio.inboxes ----------------
    op.create_table(
        "inboxes",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("account_id", sa.String(48),
                  sa.ForeignKey("auth.accounts.id"), nullable=False),
        sa.Column("bridge_id", sa.String(48),
                  sa.ForeignKey("studio.bridges.id"), nullable=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("platform_self_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "platform IN ('chat', 'wechat', 'feishu')", name="ck_inbox_platform"
        ),
        schema="studio",
    )
    op.create_index("ix_inboxes_id", "inboxes", ["id"], schema="studio")
    op.create_index("ix_inboxes_account_id", "inboxes", ["account_id"], schema="studio")
    op.create_index("ix_inboxes_bridge_id", "inboxes", ["bridge_id"], schema="studio")

    # ---------------- studio.conversations ----------------
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("inbox_id", sa.String(48),
                  sa.ForeignKey("studio.inboxes.id"), nullable=False),
        sa.Column("platform_conversation_id", sa.String(256), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("card_md", sa.Text, nullable=False),
        sa.Column("persona_id", sa.String(48),
                  sa.ForeignKey("studio.personas.id"), nullable=True),
        sa.Column("provider_id", sa.String(48),
                  sa.ForeignKey("studio.provider_configs.id"), nullable=False),
        sa.Column("takeover", sa.Boolean, nullable=False),
        sa.Column("reply_policy", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_reply_round_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("inbox_id", "platform_conversation_id", name="uq_conversation_inbox_pcid"),
        sa.CheckConstraint("kind IN ('dm', 'group', 'unknown')", name="ck_conversation_kind"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_conversation_status"),
        sa.CheckConstraint("reply_policy IN ('disabled', 'autoreply')", name="ck_conversation_reply_policy"),
        schema="studio",
    )
    op.create_index("ix_conversations_id", "conversations", ["id"], schema="studio")
    op.create_index("ix_conversations_inbox_id", "conversations", ["inbox_id"], schema="studio")

    op.create_table(
        "conversation_members",
        sa.Column("conversation_id", sa.String(48),
                  sa.ForeignKey("studio.conversations.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("peer_platform_id", sa.String(256), primary_key=True),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="studio",
    )

    # ---------------- studio.messages ----------------
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(48),
                  sa.ForeignKey("studio.conversations.id"), nullable=False),
        sa.Column("client_id", sa.String(256), nullable=False),
        sa.Column("sender_id", sa.String(256), nullable=True),
        sa.Column("msg_type", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "client_id", name="uq_message_conv_client"),
        sa.CheckConstraint("msg_type IN ('text', 'image', 'audio', 'video', 'file')", name="ck_message_msg_type"),
        schema="studio",
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"], schema="studio")
    op.create_index("ix_messages_timestamp", "messages", ["timestamp"], schema="studio")
    op.create_index("idx_msg_conversation_ts", "messages", ["conversation_id", "timestamp"], schema="studio")

    # ---------------- studio.distill_jobs ----------------
    op.create_table(
        "distill_jobs",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("account_id", sa.String(48),
                  sa.ForeignKey("auth.accounts.id"), nullable=False),
        sa.Column("conversation_ids", postgresql.JSONB, nullable=False),
        sa.Column("target_persona_id", sa.String(48),
                  sa.ForeignKey("studio.personas.id"), nullable=True),
        sa.Column("provider_config_id", sa.String(48),
                  sa.ForeignKey("studio.provider_configs.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", postgresql.JSONB, nullable=False),
        sa.Column("error_message", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'running', 'done', 'failed')", name="ck_distill_status"),
        schema="studio",
    )
    op.create_index("ix_distill_jobs_id", "distill_jobs", ["id"], schema="studio")
    op.create_index("ix_distill_jobs_account_id", "distill_jobs", ["account_id"], schema="studio")
    op.create_index("ix_distill_jobs_target_persona_id", "distill_jobs", ["target_persona_id"], schema="studio")
    op.create_index("ix_distill_jobs_provider_config_id", "distill_jobs", ["provider_config_id"], schema="studio")

    # ---------------- studio.outbound_messages ----------------
    op.create_table(
        "outbound_messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("inbox_id", sa.String(48),
                  sa.ForeignKey("studio.inboxes.id"), nullable=False),
        sa.Column("conversation_id", sa.String(48),
                  sa.ForeignKey("studio.conversations.id"), nullable=False),
        sa.Column("msg_type", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("send_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_reason", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'delivered', 'failed', 'canceled')", name="ck_outbound_status"),
        sa.CheckConstraint("msg_type IN ('text', 'image', 'audio', 'video', 'file')", name="ck_outbound_msg_type"),
        schema="studio",
    )
    op.create_index("ix_outbound_messages_inbox_id", "outbound_messages", ["inbox_id"], schema="studio")
    op.create_index("ix_outbound_messages_conversation_id", "outbound_messages", ["conversation_id"], schema="studio")
    op.create_index("idx_outbound_inbox_id", "outbound_messages", ["inbox_id", "id"], schema="studio")
    op.create_index("idx_outbound_send_after", "outbound_messages", ["status", "send_after"], schema="studio")
    op.create_index("idx_outbound_conv_created", "outbound_messages", ["conversation_id", "created_at"], schema="studio")

    # ---------------- studio.llm_logs ----------------
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
        schema="studio",
    )
    op.create_index("ix_llm_logs_persona_id", "llm_logs", ["persona_id"], schema="studio")
    op.create_index("ix_llm_logs_inbox_id", "llm_logs", ["inbox_id"], schema="studio")

    # ---------------- chat.contacts ----------------
    op.create_table(
        "contacts",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("account_id", sa.String(48),
                  sa.ForeignKey("auth.accounts.id"), nullable=False),
        sa.Column("username", sa.String(256), nullable=False),
        sa.Column("nickname", sa.String(256), nullable=False),
        sa.Column("remark_name", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "username", name="uq_chat_contact_username"),
        schema="chat",
    )
    op.create_index("ix_chat_contacts_id", "contacts", ["id"], schema="chat")
    op.create_index("ix_chat_contacts_account_id", "contacts", ["account_id"], schema="chat")

    # ---------------- chat.conversations ----------------
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("account_id", sa.String(48),
                  sa.ForeignKey("auth.accounts.id"), nullable=False),
        sa.Column("contact_id", sa.String(48),
                  sa.ForeignKey("chat.contacts.id"), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "contact_id", name="uq_chat_direct_conversation"),
        schema="chat",
    )
    op.create_index("ix_chat_conversations_id", "conversations", ["id"], schema="chat")
    op.create_index("ix_chat_conversations_account_id", "conversations", ["account_id"], schema="chat")
    op.create_index("ix_chat_conversations_contact_id", "conversations", ["contact_id"], schema="chat")

    # ---------------- chat.messages ----------------
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.String(48),
                  sa.ForeignKey("auth.accounts.id"), nullable=False),
        sa.Column("conversation_id", sa.String(48),
                  sa.ForeignKey("chat.conversations.id"), nullable=False),
        sa.Column("sender_id", sa.String(48),
                  sa.ForeignKey("chat.contacts.id"), nullable=True),
        sa.Column("msg_type", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("msg_type IN ('text', 'image', 'audio', 'video', 'file')", name="ck_chat_msg_type"),
        schema="chat",
    )
    op.create_index("ix_chat_messages_account_id", "messages", ["account_id"], schema="chat")
    op.create_index("ix_chat_messages_conversation_id_id", "messages", ["conversation_id", "id"], schema="chat")


def downgrade() -> None:
    op.drop_table("messages", schema="chat")
    op.drop_table("conversations", schema="chat")
    op.drop_table("contacts", schema="chat")
    op.drop_table("llm_logs", schema="studio")
    op.drop_table("outbound_messages", schema="studio")
    op.drop_table("distill_jobs", schema="studio")
    op.drop_table("messages", schema="studio")
    op.drop_table("conversation_members", schema="studio")
    op.drop_table("conversations", schema="studio")
    op.drop_table("inboxes", schema="studio")
    op.drop_table("bridges", schema="studio")
    op.drop_table("personas", schema="studio")
    op.drop_table("auth_sessions", schema="auth")
    op.drop_table("accounts", schema="auth")
    op.drop_table("provider_configs", schema="studio")
    op.execute('DROP SCHEMA IF EXISTS "chat" CASCADE')
    op.execute('DROP SCHEMA IF EXISTS "studio" CASCADE')
    op.execute('DROP SCHEMA IF EXISTS "auth" CASCADE')
