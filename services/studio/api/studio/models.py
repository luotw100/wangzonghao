"""Studio data model.

Principles:
- No SQLAlchemy column-level defaults. Every INSERT must pass every field
  explicitly. The schema enforces NOT NULL; the application enforces values.
- Persona, Inbox, Bridge are independent entities. Persona is content
  (markdown). Inbox is a logical platform-side identity; Bridge is the
  daemon process that physically runs adapters. An Inbox is bound to one
  Bridge (Inbox.bridge_id) and a Bridge can serve N inboxes.
- ProviderConfigs are an account-level pool. Any operation calling an LLM
  must reference one explicitly.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)

from studio.db import Base


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class Account(Base):
    __tablename__ = "accounts"

    id            = Column(String, primary_key=True, index=True)
    username      = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    display_name  = Column(String, nullable=True)
    status        = Column(String, nullable=False)              # 'active' | 'disabled'
    created_at    = Column(DateTime, nullable=False)
    updated_at    = Column(DateTime, nullable=False)
    last_login_at = Column(DateTime, nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id           = Column(String, primary_key=True, index=True)  # token sha256
    account_id   = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    created_at   = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# LLM provider pool
# ---------------------------------------------------------------------------

class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id            = Column(String, primary_key=True, index=True)
    account_id    = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    name          = Column(String, nullable=False)
    base_url      = Column(String, nullable=False)
    api_key       = Column(Text, nullable=True)
    default_model = Column(String, nullable=False)
    created_at    = Column(DateTime, nullable=False)
    updated_at    = Column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------

class Persona(Base):
    __tablename__ = "personas"
    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_persona_account_name"),
    )

    id         = Column(String, primary_key=True, index=True)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    name       = Column(String, nullable=False)
    persona_md = Column(Text, nullable=True)
    status     = Column(String, nullable=False)              # 'active' | 'archived'
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# Bridge — a registered daemon (Cloudflare-tunnel style: one per PC,
# multiplexes N adapters / inboxes via a single connection).
# ---------------------------------------------------------------------------

class Bridge(Base):
    __tablename__ = "bridges"

    id              = Column(String, primary_key=True, index=True)
    account_id      = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    display_name    = Column(String, nullable=False)
    token_hash      = Column(String, nullable=False, unique=True, index=True)
    status          = Column(String, nullable=False)         # 'paired_pending' | 'online' | 'offline' | 'revoked'
    hostname        = Column(String, nullable=True)
    last_seen_at    = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, nullable=False)
    updated_at      = Column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# Inbox — a platform-side identity (one wxid / one chat user / one feishu
# open_id ...) logically independent of which Bridge happens to serve it.
# An inbox without a bridge_id is unbound: nothing can deliver from/to it.
# ---------------------------------------------------------------------------

class Inbox(Base):
    __tablename__ = "inboxes"

    id                       = Column(String, primary_key=True, index=True)
    account_id               = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    bridge_id                = Column(String, ForeignKey("bridges.id"), nullable=True, index=True)
    platform                 = Column(String, nullable=False)     # 'chat' | 'wechat' | ...
    display_name             = Column(String, nullable=False)
    default_persona_id       = Column(String, ForeignKey("personas.id"), nullable=True)
    reply_provider_config_id = Column(String, ForeignKey("provider_configs.id"), nullable=True)
    enabled                  = Column(Boolean, nullable=False)
    platform_self_id         = Column(String, nullable=True)        # Bridge reports per inbox on handshake
    created_at               = Column(DateTime, nullable=False)
    updated_at               = Column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# Contact, Archive, Message, DistillJob
# ---------------------------------------------------------------------------

class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("inbox_id", "peer_platform_id", name="uq_contact_inbox_peer"),
    )

    id                          = Column(String, primary_key=True, index=True)
    inbox_id                    = Column(String, ForeignKey("inboxes.id"), nullable=False, index=True)
    peer_platform_id            = Column(String, nullable=False)
    display_name                = Column(String, nullable=False)
    card_md                     = Column(Text, nullable=True)
    persona_id                  = Column(String, ForeignKey("personas.id"), nullable=True)
    autoreply_enabled           = Column(Boolean, nullable=False)
    pending_reply               = Column(Boolean, nullable=False)
    status                      = Column(String, nullable=False)    # 'active' | 'archived'
    last_seen_platform_msg_id   = Column(String, nullable=True)
    created_at                  = Column(DateTime, nullable=False)
    updated_at                  = Column(DateTime, nullable=False)


class Archive(Base):
    __tablename__ = "archives"
    __table_args__ = (
        UniqueConstraint("account_id", "file_hash", name="uq_archive_account_hash"),
    )

    id            = Column(String, primary_key=True, index=True)
    account_id    = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    inbox_id      = Column(String, ForeignKey("inboxes.id"), nullable=False, index=True)
    filename      = Column(String, nullable=False)
    file_path     = Column(String, nullable=False)
    file_hash     = Column(String, nullable=False, index=True)
    self_wxid     = Column(String, nullable=False)
    message_count = Column(Integer, nullable=False)
    contact_count = Column(Integer, nullable=False)
    uploaded_at   = Column(DateTime, nullable=False)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_msg_contact_ts", "contact_id", "timestamp"),
        UniqueConstraint("contact_id", "external_id", name="uq_message_contact_external"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    contact_id      = Column(String, ForeignKey("contacts.id"), nullable=False, index=True)
    archive_id      = Column(String, ForeignKey("archives.id"), nullable=True, index=True)
    external_id     = Column(String, nullable=False)
    source          = Column(String, nullable=False)             # 'archive' | 'live'
    role            = Column(String, nullable=False)             # 'self' | 'counterpart'
    sender_name     = Column(String, nullable=True)
    content         = Column(Text, nullable=False)
    timestamp       = Column(DateTime, nullable=False, index=True)
    archive_msg_idx = Column(Integer, nullable=True)
    created_at      = Column(DateTime, nullable=False)


class DistillJob(Base):
    __tablename__ = "distill_jobs"

    id                 = Column(String, primary_key=True, index=True)
    account_id         = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    source_inbox_id    = Column(String, ForeignKey("inboxes.id"), nullable=False, index=True)
    target_persona_id  = Column(String, ForeignKey("personas.id"), nullable=False, index=True)
    provider_config_id = Column(String, ForeignKey("provider_configs.id"), nullable=False, index=True)
    status             = Column(String, nullable=False)
    progress           = Column(JSON, nullable=False)
    error_message      = Column(Text, nullable=True)
    created_at         = Column(DateTime, nullable=False)
    started_at         = Column(DateTime, nullable=True)
    finished_at        = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# OutboundMessage — Studio→Bridge work queue.
# Cursor: auto-increment id (globally monotonic). Bridge filters server-side
# to its own inboxes and tracks the max id it has consumed.
# ---------------------------------------------------------------------------

class OutboundMessage(Base):
    __tablename__ = "outbound_messages"
    __table_args__ = (
        Index("idx_outbound_inbox_id", "inbox_id", "id"),
    )

    id            = Column(Integer, primary_key=True, autoincrement=True)
    inbox_id      = Column(String, ForeignKey("inboxes.id"), nullable=False, index=True)
    contact_id    = Column(String, ForeignKey("contacts.id"), nullable=False, index=True)
    chunks        = Column(JSON, nullable=False)
    status        = Column(String, nullable=False)             # 'pending'|'delivered'|'failed'|'canceled'
    delivered_at  = Column(DateTime, nullable=True)
    failed_reason = Column(Text, nullable=True)
    created_at    = Column(DateTime, nullable=False)


class LlmLog(Base):
    __tablename__ = "llm_logs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    purpose          = Column(String, nullable=False)            # 'distill' | 'reply'
    persona_id       = Column(String, nullable=True, index=True)
    inbox_id         = Column(String, nullable=True, index=True)
    request_messages = Column(Text, nullable=False)
    response_raw     = Column(Text, nullable=False)
    model            = Column(String, nullable=True)
    created_at       = Column(DateTime, nullable=False)
