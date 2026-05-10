"""Studio data model.

Principles:
- No SQLAlchemy column-level defaults. Every INSERT must pass every field
  explicitly. The schema enforces NOT NULL; the application enforces values.
- Persona, Inbox, Bridge are independent entities. Persona is content
  (markdown). Inbox is a logical platform-side identity; Bridge is the
  daemon process that physically runs adapters. An Inbox is bound to one
  Bridge (Inbox.bridge_id) and a Bridge can serve N inboxes.
- ProviderConfigs are admin-maintained global configs. Inbox and Contact may
    hold optional overrides; runtime falls back to the global default Provider.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from studio.db import Base


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user')", name="ck_account_role"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_account_status"),
    )

    id            = Column(String(32), primary_key=True, index=True)
    username      = Column(String(64), nullable=False, unique=True, index=True)
    password_hash = Column(String(128), nullable=False)
    display_name  = Column(String(128), nullable=True)
    role          = Column(String(16), nullable=False)
    status        = Column(String(16), nullable=False)
    created_at    = Column(DateTime(timezone=True), nullable=False)
    updated_at    = Column(DateTime(timezone=True), nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id           = Column(String(64), primary_key=True, index=True)
    account_id   = Column(String(32), ForeignKey("accounts.id"), nullable=False, index=True)
    created_at   = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# LLM provider pool
# ---------------------------------------------------------------------------

class ProviderConfig(Base):
    __tablename__ = "provider_configs"
    __table_args__ = (
        CheckConstraint("scope IN ('global')", name="ck_provider_scope"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_provider_status"),
    )

    id               = Column(String(32), primary_key=True, index=True)
    owner_account_id = Column(String(32), ForeignKey("accounts.id"), nullable=False, index=True)
    name             = Column(String(128), nullable=False)
    base_url         = Column(String(512), nullable=False)
    api_key          = Column(Text, nullable=True)
    default_model    = Column(String(128), nullable=False)
    scope            = Column(String(16), nullable=False)
    status           = Column(String(16), nullable=False)
    is_default       = Column(Boolean, nullable=False)
    created_at       = Column(DateTime(timezone=True), nullable=False)
    updated_at       = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------

class Persona(Base):
    __tablename__ = "personas"
    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_persona_account_name"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_persona_status"),
    )

    id         = Column(String(32), primary_key=True, index=True)
    account_id = Column(String(32), ForeignKey("accounts.id"), nullable=False, index=True)
    name       = Column(String(128), nullable=False)
    persona_md = Column(Text, nullable=True)
    status     = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Bridge — a registered daemon. Auto-provisioned on first handshake, keyed by
# (account_id, hostname). The bridge identifies itself by sending its Studio
# account credentials on handshake; Studio mints a session token that the
# bridge uses for subsequent /api/bridge/* calls.
# ---------------------------------------------------------------------------

class Bridge(Base):
    __tablename__ = "bridges"
    __table_args__ = (
        UniqueConstraint("account_id", "hostname", name="uq_bridge_account_hostname"),
        CheckConstraint("status IN ('online', 'offline', 'revoked')", name="ck_bridge_status"),
    )

    id           = Column(String(32), primary_key=True, index=True)
    account_id   = Column(String(32), ForeignKey("accounts.id"), nullable=False, index=True)
    hostname     = Column(String(256), nullable=False)
    display_name = Column(String(256), nullable=False)
    status       = Column(String(16), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at   = Column(DateTime(timezone=True), nullable=False)
    updated_at   = Column(DateTime(timezone=True), nullable=False)


class BridgeSession(Base):
    __tablename__ = "bridge_sessions"

    id           = Column(String(64), primary_key=True, index=True)
    bridge_id    = Column(String(32), ForeignKey("bridges.id"), nullable=False, index=True)
    created_at   = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Inbox — a platform-side identity (one wxid / one chat user / one feishu
# open_id ...) logically independent of which Bridge happens to serve it.
# An inbox without a bridge_id is unbound: nothing can deliver from/to it.
# ---------------------------------------------------------------------------

class Inbox(Base):
    __tablename__ = "inboxes"

    id                       = Column(String(32), primary_key=True, index=True)
    account_id               = Column(String(32), ForeignKey("accounts.id"), nullable=False, index=True)
    bridge_id                = Column(String(32), ForeignKey("bridges.id"), nullable=True, index=True)
    platform                 = Column(String(32), nullable=False)
    display_name             = Column(String(256), nullable=False)
    default_persona_id       = Column(String(32), ForeignKey("personas.id"), nullable=True)
    reply_provider_config_id = Column(String(32), ForeignKey("provider_configs.id"), nullable=True)
    enabled                  = Column(Boolean, nullable=False)
    platform_self_id         = Column(String(128), nullable=True)
    created_at               = Column(DateTime(timezone=True), nullable=False)
    updated_at               = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Contact, Archive, Message, DistillJob
# ---------------------------------------------------------------------------

class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("inbox_id", "peer_platform_id", name="uq_contact_inbox_peer"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_contact_status"),
    )

    id                          = Column(String(32), primary_key=True, index=True)
    inbox_id                    = Column(String(32), ForeignKey("inboxes.id"), nullable=False, index=True)
    peer_platform_id            = Column(String(256), nullable=False)
    display_name                = Column(String(256), nullable=False)
    card_md                     = Column(Text, nullable=True)
    persona_id                  = Column(String(32), ForeignKey("personas.id"), nullable=True)
    reply_provider_config_id    = Column(String(32), ForeignKey("provider_configs.id"), nullable=True)
    autoreply_enabled           = Column(Boolean, nullable=False)
    pending_reply               = Column(Boolean, nullable=False)
    status                      = Column(String(16), nullable=False)
    last_seen_platform_msg_id   = Column(String(256), nullable=True)
    created_at                  = Column(DateTime(timezone=True), nullable=False)
    updated_at                  = Column(DateTime(timezone=True), nullable=False)


class Archive(Base):
    __tablename__ = "archives"
    __table_args__ = (
        UniqueConstraint("account_id", "file_hash", name="uq_archive_account_hash"),
    )

    id             = Column(String(32), primary_key=True, index=True)
    account_id     = Column(String(32), ForeignKey("accounts.id"), nullable=False, index=True)
    inbox_id       = Column(String(32), ForeignKey("inboxes.id"), nullable=False, index=True)
    filename       = Column(String(256), nullable=False)
    file_path      = Column(String(512), nullable=False)
    file_hash      = Column(String(64), nullable=False, index=True)
    platform_self_id = Column(String(128), nullable=False)
    message_count  = Column(Integer, nullable=False)
    contact_count  = Column(Integer, nullable=False)
    uploaded_at    = Column(DateTime(timezone=True), nullable=False)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_msg_contact_ts", "contact_id", "timestamp"),
        UniqueConstraint("contact_id", "external_id", name="uq_message_contact_external"),
        CheckConstraint("source IN ('archive', 'live')", name="ck_message_source"),
        CheckConstraint("role IN ('self', 'counterpart')", name="ck_message_role"),
    )

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    contact_id      = Column(String(32), ForeignKey("contacts.id"), nullable=False, index=True)
    archive_id      = Column(String(32), ForeignKey("archives.id"), nullable=True, index=True)
    external_id     = Column(String(256), nullable=False)
    source          = Column(String(16), nullable=False)
    role            = Column(String(16), nullable=False)
    sender_name     = Column(String(256), nullable=True)
    content         = Column(Text, nullable=False)
    timestamp       = Column(DateTime(timezone=True), nullable=False, index=True)
    archive_msg_idx = Column(Integer, nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False)


class DistillJob(Base):
    __tablename__ = "distill_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'running', 'done', 'failed')", name="ck_distill_status"),
    )

    id                 = Column(String(32), primary_key=True, index=True)
    account_id         = Column(String(32), ForeignKey("accounts.id"), nullable=False, index=True)
    source_inbox_id    = Column(String(32), ForeignKey("inboxes.id"), nullable=False, index=True)
    target_persona_id  = Column(String(32), ForeignKey("personas.id"), nullable=False, index=True)
    provider_config_id = Column(String(32), ForeignKey("provider_configs.id"), nullable=False, index=True)
    status             = Column(String(16), nullable=False)
    progress           = Column(JSONB, nullable=False)
    error_message      = Column(Text, nullable=True)
    created_at         = Column(DateTime(timezone=True), nullable=False)
    started_at         = Column(DateTime(timezone=True), nullable=True)
    finished_at        = Column(DateTime(timezone=True), nullable=True)


# ---------------------------------------------------------------------------
# OutboundMessage — Studio→Bridge work queue.
# Cursor: auto-increment id (globally monotonic). Bridge filters server-side
# to its own inboxes and tracks the max id it has consumed.
# ---------------------------------------------------------------------------

class OutboundMessage(Base):
    __tablename__ = "outbound_messages"
    __table_args__ = (
        Index("idx_outbound_inbox_id", "inbox_id", "id"),
        Index("idx_outbound_send_after", "status", "send_after"),
        CheckConstraint("status IN ('pending', 'delivered', 'failed', 'canceled')", name="ck_outbound_status"),
    )

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    inbox_id      = Column(String(32), ForeignKey("inboxes.id"), nullable=False, index=True)
    contact_id    = Column(String(32), ForeignKey("contacts.id"), nullable=False, index=True)
    content       = Column(Text, nullable=False)
    send_after    = Column(DateTime(timezone=True), nullable=False)
    status        = Column(String(16), nullable=False)
    delivered_at  = Column(DateTime(timezone=True), nullable=True)
    failed_reason = Column(Text, nullable=True)
    created_at    = Column(DateTime(timezone=True), nullable=False)


class LlmLog(Base):
    __tablename__ = "llm_logs"
    __table_args__ = (
        CheckConstraint("purpose IN ('distill', 'reply')", name="ck_llm_log_purpose"),
    )

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    purpose          = Column(String(16), nullable=False)
    persona_id       = Column(String(32), nullable=True, index=True)
    inbox_id         = Column(String(32), nullable=True, index=True)
    request_messages = Column(Text, nullable=False)
    response_raw     = Column(Text, nullable=False)
    model            = Column(String(128), nullable=True)
    created_at       = Column(DateTime(timezone=True), nullable=False)