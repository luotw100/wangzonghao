"""Studio data model.

Principles:
- No SQLAlchemy column-level defaults. Every INSERT must pass every field
  explicitly. The schema enforces NOT NULL; the application enforces values.
- Persona, Inbox, Bridge are independent entities. Persona is content
  (markdown). Inbox is a logical platform-side identity; Bridge is the
  daemon process that physically runs adapters. An Inbox is bound to one
  Bridge (Inbox.bridge_id) and a Bridge can serve N inboxes.
- ProviderConfig is operator-maintained, managed via the server-side CLI.
  Routing is explicit: each Contact owns a provider_id (used by reply),
  each Account owns a distill_provider_id (used by distill). No system
  default / fallback. New contacts and new accounts are seeded with the
  earliest-created provider; if no provider exists, creation fails.
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
from sqlalchemy.orm import relationship

from studio.db import Base


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="ck_account_status"),
    )

    id                  = Column(String(48), primary_key=True, index=True)
    username            = Column(String(64), nullable=False, unique=True, index=True)
    password_hash       = Column(String(128), nullable=False)
    display_name        = Column(String(128), nullable=False)
    status              = Column(String(16), nullable=False)
    distill_provider_id = Column(String(48), ForeignKey("provider_configs.id"), nullable=False, index=True)
    created_at          = Column(DateTime(timezone=True), nullable=False)
    updated_at          = Column(DateTime(timezone=True), nullable=False)

    distill_provider    = relationship("ProviderConfig", foreign_keys=[distill_provider_id])


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id           = Column(String(64), primary_key=True, index=True)
    account_id   = Column(String(48), ForeignKey("accounts.id"), nullable=False, index=True)
    expires_at   = Column(DateTime(timezone=True), nullable=False)
    created_at   = Column(DateTime(timezone=True), nullable=False)

    account      = relationship("Account")


# ---------------------------------------------------------------------------
# LLM provider pool
# ---------------------------------------------------------------------------

class ProviderConfig(Base):
    __tablename__ = "provider_configs"
    __table_args__ = (
        UniqueConstraint("name", name="uq_provider_name"),
    )

    id         = Column(String(48), primary_key=True, index=True)
    name       = Column(String(128), nullable=False)
    base_url   = Column(String(512), nullable=False)
    api_key    = Column(Text, nullable=True)   # nullable: local providers (e.g. ollama) need no key
    model      = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------

class Persona(Base):
    __tablename__ = "personas"
    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_persona_account_name"),
    )

    id         = Column(String(48), primary_key=True, index=True)
    account_id = Column(String(48), ForeignKey("accounts.id"), nullable=False, index=True)
    name       = Column(String(128), nullable=False)
    persona_md = Column(Text, nullable=False)
    timezone   = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Bridge — a registered daemon. Auto-provisioned on first handshake, keyed by
# (account_id, machine_id). Studio generates a short machine_id on first
# launch and returns it to the bridge, which persists it locally so the
# same machine gets the same Bridge row across restarts.
#
# online/offline is derived from last_seen_at + heartbeat threshold; no
# cached status column.
# ---------------------------------------------------------------------------

class Bridge(Base):
    __tablename__ = "bridges"
    __table_args__ = (
        UniqueConstraint("account_id", "machine_id", name="uq_bridge_account_machine_id"),
    )

    id           = Column(String(48), primary_key=True, index=True)
    account_id   = Column(String(48), ForeignKey("accounts.id"), nullable=False, index=True)
    machine_id   = Column(String(256), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    created_at   = Column(DateTime(timezone=True), nullable=False)
    updated_at   = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Inbox — a platform-side identity (one wxid / one chat user / one feishu
# open_id ...) logically independent of which Bridge happens to serve it.
# An inbox without a bridge_id is unbound: nothing can deliver from/to it.
# ---------------------------------------------------------------------------

class Inbox(Base):
    __tablename__ = "inboxes"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('chat', 'wechat', 'feishu')", name="ck_inbox_platform"
        ),
    )

    id                = Column(String(48), primary_key=True, index=True)
    account_id        = Column(String(48), ForeignKey("accounts.id"), nullable=False, index=True)
    bridge_id         = Column(String(48), ForeignKey("bridges.id"), nullable=True, index=True)
    platform          = Column(String(32), nullable=False)
    display_name      = Column(String(256), nullable=False)
    platform_self_id  = Column(String(128), nullable=True)
    created_at        = Column(DateTime(timezone=True), nullable=False)
    updated_at        = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Contact, Message, DistillJob
# ---------------------------------------------------------------------------

class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("inbox_id", "peer_platform_id", name="uq_contact_inbox_peer"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_contact_status"),
        CheckConstraint("reply_policy IN ('disabled', 'autoreply')", name="ck_contact_reply_policy"),
    )

    id                    = Column(String(48), primary_key=True, index=True)
    inbox_id              = Column(String(48), ForeignKey("inboxes.id"), nullable=False, index=True)
    peer_platform_id      = Column(String(256), nullable=False)
    display_name          = Column(String(256), nullable=False)
    card_md               = Column(Text, nullable=False)
    persona_id            = Column(String(48), ForeignKey("personas.id"), nullable=True)
    provider_id           = Column(String(48), ForeignKey("provider_configs.id"), nullable=False)
    takeover              = Column(Boolean, nullable=False)
    reply_policy          = Column(String(16), nullable=False)
    status                = Column(String(16), nullable=False)
    # last_reply_round_at: timestamp of the most recent reply-pipeline round
    # (queued outbound, intentional silence, or hard skip). Used to derive
    # "needs reply": latest message is counterpart with timestamp > this.
    last_reply_round_at   = Column(DateTime(timezone=True), nullable=True)
    created_at            = Column(DateTime(timezone=True), nullable=False)
    updated_at            = Column(DateTime(timezone=True), nullable=False)

    provider              = relationship("ProviderConfig", foreign_keys=[provider_id])


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_msg_contact_ts", "contact_id", "timestamp"),
        UniqueConstraint("contact_id", "msg_hash", name="uq_message_contact_hash"),
        CheckConstraint("role IN ('self', 'counterpart')", name="ck_message_role"),
        CheckConstraint("msg_type IN ('text', 'image', 'audio', 'video', 'file')", name="ck_message_msg_type"),
        CheckConstraint("authored_by IN ('unknown')", name="ck_message_authored_by"),
    )

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    contact_id      = Column(String(48), ForeignKey("contacts.id"), nullable=False, index=True)
    # external_id: platform-side message id, debug only — no uniqueness, no
    # ordering guarantee. Dedup runs on msg_hash.
    external_id     = Column(String(256), nullable=True)
    msg_hash        = Column(String(64), nullable=False)   # SHA256 content hash for cross-device dedup
    role            = Column(String(16), nullable=False)
    authored_by     = Column(String(16), nullable=False)  # reserved provenance flag; only 'unknown' for now
    sender_id       = Column(String(256), nullable=True)  # platform id of sender (group chat)
    sender_name     = Column(String(256), nullable=True)  # display name of sender (group chat)
    msg_type        = Column(String(16), nullable=False)
    content         = Column(Text, nullable=False)
    timestamp       = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at      = Column(DateTime(timezone=True), nullable=False)


class MediaHash(Base):
    """Maps (account_id, content_hash) → Studio S3 storage_key.

    Populated when Bridge sends a new media message. Used by check-or-presign
    to avoid re-uploading identical files across Bridge instances or restarts.
    """
    __tablename__ = "media_hashes"
    __table_args__ = (
        UniqueConstraint("account_id", "content_hash", name="uq_media_hash_account"),
    )

    id           = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id   = Column(String(48), ForeignKey("accounts.id"), nullable=False, index=True)
    content_hash = Column(String(71), nullable=False)   # "sha256:{64hexchars}"
    storage_key  = Column(String(256), nullable=False)
    created_at   = Column(DateTime(timezone=True), nullable=False)


class DistillJob(Base):
    __tablename__ = "distill_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'running', 'done', 'failed')", name="ck_distill_status"),
    )

    id                 = Column(String(48), primary_key=True, index=True)
    account_id         = Column(String(48), ForeignKey("accounts.id"), nullable=False, index=True)
    # contact_ids: JSONB array of Contact.id strings to fold in this job.
    contact_ids        = Column(JSONB, nullable=False)
    target_persona_id  = Column(String(48), ForeignKey("personas.id"), nullable=True, index=True)
    provider_config_id = Column(String(48), ForeignKey("provider_configs.id"), nullable=False, index=True)
    status             = Column(String(16), nullable=False)
    # progress: JSONB scratchpad written by the pipeline; e.g.
    # {"contacts_total": N, "contacts_done": K, "windows_total": M, "windows_done": J}.
    progress           = Column(JSONB, nullable=False)
    error_message      = Column(Text, nullable=False)
    created_at         = Column(DateTime(timezone=True), nullable=False)
    started_at         = Column(DateTime(timezone=True), nullable=True)
    finished_at        = Column(DateTime(timezone=True), nullable=True)

    provider           = relationship("ProviderConfig", foreign_keys=[provider_config_id])


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
        Index("idx_outbound_contact_created", "contact_id", "created_at"),
        CheckConstraint("status IN ('pending', 'delivered', 'failed', 'canceled')", name="ck_outbound_status"),
        CheckConstraint("msg_type IN ('text', 'image', 'audio', 'video', 'file')", name="ck_outbound_msg_type"),
    )

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    inbox_id      = Column(String(48), ForeignKey("inboxes.id"), nullable=False, index=True)
    contact_id    = Column(String(48), ForeignKey("contacts.id"), nullable=False, index=True)
    msg_type      = Column(String(16), nullable=False)
    content       = Column(Text, nullable=False)
    send_after    = Column(DateTime(timezone=True), nullable=False)
    status        = Column(String(16), nullable=False)
    delivered_at  = Column(DateTime(timezone=True), nullable=True)
    failed_reason = Column(Text, nullable=False)
    created_at    = Column(DateTime(timezone=True), nullable=False)


class LlmLog(Base):
    """Audit log of LLM round-trips. Deliberately uses bare string FKs
    (no ON DELETE cascade) so personas/inboxes can be deleted while the
    historical audit trail is preserved.
    """

    __tablename__ = "llm_logs"
    __table_args__ = (
        CheckConstraint("purpose IN ('distill', 'reply')", name="ck_llm_log_purpose"),
    )

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    purpose          = Column(String(16), nullable=False)
    persona_id       = Column(String(48), nullable=True, index=True)
    inbox_id         = Column(String(48), nullable=True, index=True)
    request_messages = Column(Text, nullable=False)
    response_raw     = Column(Text, nullable=False)
    model            = Column(String(128), nullable=True)
    created_at       = Column(DateTime(timezone=True), nullable=False)
