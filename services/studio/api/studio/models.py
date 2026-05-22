"""Studio data model.

Principles:
- No SQLAlchemy column-level defaults. Every INSERT must pass every field
  explicitly. The schema enforces NOT NULL; the application enforces values.
- Persona, Inbox, Bridge are independent entities. Persona is content
  (markdown). Inbox is a logical platform-side identity; Bridge is the
  daemon process that physically runs adapters. An Inbox is bound to one
  Bridge (Inbox.bridge_id) and a Bridge can serve N inboxes.
- ProviderConfig is operator-maintained, managed via the server-side CLI.
  Routing is explicit: each Conversation owns a provider_id (used by
  reply), each Account owns a distill_provider_id (used by distill). No
  system default / fallback. New conversations and accounts are seeded
  with the earliest-created provider; if no provider exists, creation
  fails.
- The takeover unit is **Conversation**, not peer. A DM is a Conversation
  with kind="dm" and one ConversationMember; a group chat is a
  Conversation with kind="group" and N members. The same takeover /
  reply_policy / persona / provider settings apply uniformly.
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
    api_key    = Column(Text, nullable=True)
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
# Bridge — registered daemon, keyed by (account_id, machine_id). Studio
# generates the machine_id on first handshake; the bridge persists and sends
# it via X-Machine-Id thereafter.
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
# Inbox — a platform-side identity (one chat user / one wxid / one feishu
# open_id ...). An inbox without bridge_id is unbound.
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
# Conversation + members. Identity is (inbox_id, platform_conversation_id);
# kind distinguishes DM vs group. ConversationMember rows describe who's in
# the conversation — for kind="dm" there's exactly one member (the peer);
# for kind="group" there's N. The placeholder kind="unknown" is allowed
# while waiting for /api/bridge/conversations to fill in the metadata.
# ---------------------------------------------------------------------------

class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "inbox_id", "platform_conversation_id",
            name="uq_conversation_inbox_pcid",
        ),
        CheckConstraint("kind IN ('dm', 'group', 'unknown')", name="ck_conversation_kind"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_conversation_status"),
        CheckConstraint(
            "reply_policy IN ('disabled', 'autoreply')",
            name="ck_conversation_reply_policy",
        ),
    )

    id                       = Column(String(48), primary_key=True, index=True)
    inbox_id                 = Column(String(48), ForeignKey("inboxes.id"), nullable=False, index=True)
    platform_conversation_id = Column(String(256), nullable=False)
    kind                     = Column(String(16), nullable=False)
    display_name             = Column(String(256), nullable=False)
    card_md                  = Column(Text, nullable=False)
    persona_id               = Column(String(48), ForeignKey("personas.id"), nullable=True)
    provider_id              = Column(String(48), ForeignKey("provider_configs.id"), nullable=False)
    takeover                 = Column(Boolean, nullable=False)
    reply_policy             = Column(String(16), nullable=False)
    status                   = Column(String(16), nullable=False)
    last_reply_round_at      = Column(DateTime(timezone=True), nullable=True)
    created_at               = Column(DateTime(timezone=True), nullable=False)
    updated_at               = Column(DateTime(timezone=True), nullable=False)

    provider                 = relationship("ProviderConfig", foreign_keys=[provider_id])
    members                  = relationship(
        "ConversationMember",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class ConversationMember(Base):
    """Member of a conversation on the platform side.

    For DMs there's exactly one row (the peer). For groups, N rows. The
    bridge upserts via POST /api/bridge/conversations; Studio never mutates
    this table from elsewhere.
    """
    __tablename__ = "conversation_members"

    conversation_id  = Column(
        String(48),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    peer_platform_id = Column(String(256), primary_key=True)
    display_name     = Column(String(256), nullable=False)
    updated_at       = Column(DateTime(timezone=True), nullable=False)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_msg_conversation_ts", "conversation_id", "timestamp"),
        UniqueConstraint(
            "conversation_id", "client_id", name="uq_message_conv_client",
        ),
        CheckConstraint(
            "msg_type IN ('text', 'image', 'audio', 'video', 'file')",
            name="ck_message_msg_type",
        ),
    )

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(String(48), ForeignKey("conversations.id"), nullable=False, index=True)
    # client_id: bridge-side stable identifier for this message. Adapter
    # picks the form (chat: platform msg.id; wechat: official msg_id; ...).
    # Same value used by the bridge's local store as its dedup key.
    client_id       = Column(String(256), nullable=False)
    # sender_id: platform id of the actual sender. NULL means "self"
    # (the inbox's own self_id sent it — i.e. a message the user sent
    # from another client that the bridge observed and reported back).
    sender_id       = Column(String(256), nullable=True)
    msg_type        = Column(String(16), nullable=False)
    content         = Column(Text, nullable=False)
    timestamp       = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at      = Column(DateTime(timezone=True), nullable=False)


class DistillJob(Base):
    __tablename__ = "distill_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed')",
            name="ck_distill_status",
        ),
    )

    id                  = Column(String(48), primary_key=True, index=True)
    account_id          = Column(String(48), ForeignKey("accounts.id"), nullable=False, index=True)
    # JSONB array of Conversation.id strings.
    conversation_ids    = Column(JSONB, nullable=False)
    target_persona_id   = Column(String(48), ForeignKey("personas.id"), nullable=True, index=True)
    provider_config_id  = Column(String(48), ForeignKey("provider_configs.id"), nullable=False, index=True)
    status              = Column(String(16), nullable=False)
    progress            = Column(JSONB, nullable=False)
    error_message       = Column(Text, nullable=False)
    created_at          = Column(DateTime(timezone=True), nullable=False)
    started_at          = Column(DateTime(timezone=True), nullable=True)
    finished_at         = Column(DateTime(timezone=True), nullable=True)

    provider            = relationship("ProviderConfig", foreign_keys=[provider_config_id])


# ---------------------------------------------------------------------------
# OutboundMessage — Studio→Bridge work queue. No state on the bridge side:
# bridge long-polls for status=pending and dispatches; Studio flips status
# to delivered when an /incoming message from_self matches by (conversation,
# content). Permanent failure has no reverse channel in v2 — failed sends
# stay pending until admin cleanup.
# ---------------------------------------------------------------------------

class OutboundMessage(Base):
    __tablename__ = "outbound_messages"
    __table_args__ = (
        Index("idx_outbound_inbox_id", "inbox_id", "id"),
        Index("idx_outbound_send_after", "status", "send_after"),
        Index("idx_outbound_conv_created", "conversation_id", "created_at"),
        CheckConstraint(
            "status IN ('pending', 'delivered', 'failed', 'canceled')",
            name="ck_outbound_status",
        ),
        CheckConstraint(
            "msg_type IN ('text', 'image', 'audio', 'video', 'file')",
            name="ck_outbound_msg_type",
        ),
    )

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    inbox_id        = Column(String(48), ForeignKey("inboxes.id"), nullable=False, index=True)
    conversation_id = Column(String(48), ForeignKey("conversations.id"), nullable=False, index=True)
    msg_type        = Column(String(16), nullable=False)
    content         = Column(Text, nullable=False)
    send_after      = Column(DateTime(timezone=True), nullable=False)
    status          = Column(String(16), nullable=False)
    delivered_at    = Column(DateTime(timezone=True), nullable=True)
    failed_reason   = Column(Text, nullable=False)
    created_at      = Column(DateTime(timezone=True), nullable=False)


class LlmLog(Base):
    """Audit log of LLM round-trips. Bare string FKs (no cascade) preserve
    history even if personas/inboxes are deleted.
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
