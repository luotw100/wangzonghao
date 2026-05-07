"""Robot data model.

Principles:
- No SQLAlchemy column-level defaults. Every INSERT must pass every field
  explicitly. The schema enforces NOT NULL; the application enforces values.
- Persona and Inbox are independent: Persona is content (markdown), Inbox is
  a platform login (1:1 with a Bridge daemon). One account can have many of
  each. A Contact (per-inbox) explicitly chooses which Persona to use.
- ProviderConfigs are a flat account-level pool. Any operation that calls an
  LLM (currently distill) must pass a provider_config_id explicitly.
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

from robot.db import Base


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
# LLM provider pool — account-level resource, used explicitly per call
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
# Persona — pure content asset (人设)
# ---------------------------------------------------------------------------

class Persona(Base):
    __tablename__ = "personas"
    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_persona_account_name"),
    )

    id         = Column(String, primary_key=True, index=True)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    name       = Column(String, nullable=False)
    persona_md = Column(Text, nullable=True)                  # may be empty before distill
    status     = Column(String, nullable=False)               # 'active' | 'archived'
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# Inbox — a single platform login (接管号)
#   1 Inbox <-> 1 Bridge daemon (bound by b_token)
#   1 Inbox -> N Contacts
# ---------------------------------------------------------------------------

class Inbox(Base):
    __tablename__ = "inboxes"

    id                       = Column(String, primary_key=True, index=True)
    account_id               = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    platform                 = Column(String, nullable=False)       # 'chat' | 'wechat' | ...
    display_name             = Column(String, nullable=False)
    default_persona_id       = Column(String, ForeignKey("personas.id"), nullable=False)
    reply_provider_config_id = Column(String, ForeignKey("provider_configs.id"), nullable=True)
    enabled                  = Column(Boolean, nullable=False)      # master switch
    platform_self_id         = Column(String, nullable=True)        # B reports on handshake
    hostname                 = Column(String, nullable=True)        # B reports on handshake
    b_token_hash             = Column(String, nullable=False, unique=True, index=True)
    b_status                 = Column(String, nullable=False)       # 'paired_pending'|'online'|'offline'|'revoked'
    last_seen_at             = Column(DateTime, nullable=True)
    created_at               = Column(DateTime, nullable=False)
    updated_at               = Column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# Contact — peer in a 1:1 conversation, scoped to one Inbox
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
    persona_id                  = Column(String, ForeignKey("personas.id"), nullable=False)
    autoreply_enabled           = Column(Boolean, nullable=False)
    pending_reply               = Column(Boolean, nullable=False)   # set true when new counterpart msg lands; ReplyScanner clears
    status                      = Column(String, nullable=False)   # 'active' | 'archived'
    last_seen_platform_msg_id   = Column(String, nullable=True)
    created_at                  = Column(DateTime, nullable=False)
    updated_at                  = Column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# Archives — uploaded WeFlow JSON, account-level content asset
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Messages — historical (from archive) + live (from bridge)
# ---------------------------------------------------------------------------

class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_msg_contact_ts", "contact_id", "timestamp"),
        UniqueConstraint("contact_id", "external_id", name="uq_message_contact_external"),
    )

    id              = Column(Integer, primary_key=True, autoincrement=True)
    contact_id      = Column(String, ForeignKey("contacts.id"), nullable=False, index=True)
    archive_id      = Column(String, ForeignKey("archives.id"), nullable=True, index=True)
    external_id     = Column(String, nullable=False)             # 'archive:<id>:<idx>' | 'live:<platform_msg_id>'
    source          = Column(String, nullable=False)             # 'archive' | 'live'
    role            = Column(String, nullable=False)             # 'self' | 'counterpart'
    sender_name     = Column(String, nullable=True)
    content         = Column(Text, nullable=False)
    timestamp       = Column(DateTime, nullable=False, index=True)
    archive_msg_idx = Column(Integer, nullable=True)
    created_at      = Column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# DistillJob — account-level training task; explicit source/target/provider
# ---------------------------------------------------------------------------

class DistillJob(Base):
    __tablename__ = "distill_jobs"

    id                   = Column(String, primary_key=True, index=True)
    account_id           = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    source_inbox_id      = Column(String, ForeignKey("inboxes.id"), nullable=False, index=True)
    target_persona_id    = Column(String, ForeignKey("personas.id"), nullable=False, index=True)
    provider_config_id   = Column(String, ForeignKey("provider_configs.id"), nullable=False, index=True)
    status               = Column(String, nullable=False)            # 'pending'|'running'|'done'|'failed'
    progress             = Column(JSON, nullable=False)               # {} when pending
    error_message        = Column(Text, nullable=True)
    created_at           = Column(DateTime, nullable=False)
    started_at           = Column(DateTime, nullable=True)
    finished_at          = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# OutboundMessage — bridge work queue (C → B)
# ---------------------------------------------------------------------------

class OutboundMessage(Base):
    __tablename__ = "outbound_messages"
    __table_args__ = (
        Index("idx_outbound_inbox_seq", "inbox_id", "seq"),
    )

    id            = Column(String, primary_key=True, index=True)
    seq           = Column(Integer, nullable=False)               # per-inbox monotonically increasing
    inbox_id      = Column(String, ForeignKey("inboxes.id"), nullable=False, index=True)
    contact_id    = Column(String, ForeignKey("contacts.id"), nullable=False, index=True)
    chunks        = Column(JSON, nullable=False)                  # [{content, msg_type}, ...]
    status        = Column(String, nullable=False)                # 'pending'|'delivered'|'failed'|'canceled'
    delivered_at  = Column(DateTime, nullable=True)
    failed_reason = Column(Text, nullable=True)
    created_at    = Column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# LlmLog — distill provenance (live reply not yet implemented)
# ---------------------------------------------------------------------------

class LlmLog(Base):
    __tablename__ = "llm_logs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    purpose          = Column(String, nullable=False)              # 'distill'
    persona_id       = Column(String, nullable=True, index=True)
    inbox_id         = Column(String, nullable=True, index=True)
    request_messages = Column(Text, nullable=False)
    response_raw     = Column(Text, nullable=False)
    model            = Column(String, nullable=True)
    created_at       = Column(DateTime, nullable=False)
