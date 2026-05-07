from sqlalchemy import (
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

from robot.db import Base, utc_now


# ---------------------------------------------------------------------------
# Auth — Account / AuthSession
# ---------------------------------------------------------------------------

class Account(Base):
    """登录主体。username + password CLI 管理。"""
    __tablename__ = "accounts"

    id            = Column(String, primary_key=True, index=True)
    username      = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    display_name  = Column(String, nullable=True)
    status        = Column(String, nullable=False, default="active")  # active | disabled
    created_at    = Column(DateTime, default=utc_now, nullable=False)
    updated_at    = Column(DateTime, default=utc_now, nullable=False)
    last_login_at = Column(DateTime, nullable=True)


class AuthSession(Base):
    """登录后的会话；客户端 Bearer token，DB 只存其 hash。"""
    __tablename__ = "auth_sessions"

    id            = Column(String, primary_key=True, index=True)   # token sha256
    account_id    = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    created_at    = Column(DateTime, default=utc_now, nullable=False)
    last_seen_at  = Column(DateTime, default=utc_now, nullable=False)


# ---------------------------------------------------------------------------
# Domain — Provider / Character / Contact / Archive / Message / DistillJob / LlmLog
# ---------------------------------------------------------------------------

class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id            = Column(String, primary_key=True, index=True)
    name          = Column(String, nullable=False)
    base_url      = Column(String, nullable=False)
    api_key       = Column(Text, nullable=True)
    default_model = Column(String, nullable=False)
    created_at    = Column(DateTime, default=utc_now, nullable=False)
    updated_at    = Column(DateTime, default=utc_now, nullable=False)


class Character(Base):
    """主播管理的一个人设/角色。一个 account 可拥有 N 个 Character。"""
    __tablename__ = "characters"

    id                  = Column(String, primary_key=True, index=True)
    account_id          = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    name                = Column(String, nullable=False)
    persona_md          = Column(Text, nullable=True)
    wechat_wxid_self    = Column(String, nullable=True)
    provider_config_id  = Column(String, ForeignKey("provider_configs.id"), nullable=True, index=True)
    status              = Column(String, nullable=False, default="active")
    created_at          = Column(DateTime, default=utc_now, nullable=False)
    updated_at          = Column(DateTime, default=utc_now, nullable=False)


class Contact(Base):
    """粉丝/联系人。隶属于某个 Character。"""
    __tablename__ = "contacts"

    id              = Column(String, primary_key=True, index=True)
    character_id    = Column(String, ForeignKey("characters.id"), nullable=False, index=True)
    display_name    = Column(String, nullable=False)
    wechat_wxid     = Column(String, nullable=True)
    card_md         = Column(Text, nullable=True)
    status          = Column(String, nullable=False, default="active")
    created_at      = Column(DateTime, default=utc_now, nullable=False)
    updated_at      = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("character_id", "wechat_wxid", name="uq_contact_character_wxid"),
    )


class ChatArchive(Base):
    """上传的 WeFlow 聊天记录 artifact。"""
    __tablename__ = "chat_archives"

    id            = Column(String, primary_key=True, index=True)
    character_id  = Column(String, ForeignKey("characters.id"), nullable=False, index=True)
    filename      = Column(String, nullable=False)
    file_path     = Column(String, nullable=False)
    file_hash     = Column(String, nullable=False, index=True)
    self_wxid     = Column(String, nullable=False)
    message_count = Column(Integer, nullable=False, default=0)
    contact_count = Column(Integer, nullable=False, default=0)
    uploaded_at   = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("character_id", "file_hash", name="uq_archive_character_hash"),
    )


class Message(Base):
    """upload 历史消息表。蒸馏的输入。"""
    __tablename__ = "messages"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    contact_id      = Column(String, ForeignKey("contacts.id"), nullable=False, index=True)
    archive_id      = Column(String, ForeignKey("chat_archives.id"), nullable=True, index=True)
    role            = Column(String, nullable=False)               # 'self' | 'counterpart'
    sender_name     = Column(String, nullable=True)
    content         = Column(Text, nullable=False)
    timestamp       = Column(DateTime, nullable=False, index=True)
    archive_msg_idx = Column(Integer, nullable=True)
    created_at      = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        Index("idx_msg_contact_ts", "contact_id", "timestamp"),
        UniqueConstraint("archive_id", "archive_msg_idx", name="uq_msg_archive_idx"),
    )


class DistillJob(Base):
    """蒸馏任务，由 worker 消费执行。"""
    __tablename__ = "distill_jobs"

    id            = Column(String, primary_key=True, index=True)
    character_id  = Column(String, ForeignKey("characters.id"), nullable=False, index=True)
    status        = Column(String, nullable=False, default="pending")  # pending | running | done | failed
    progress      = Column(JSON, nullable=False, default=dict)
    error_message = Column(Text, nullable=True)
    created_at    = Column(DateTime, default=utc_now, nullable=False)
    started_at    = Column(DateTime, nullable=True)
    finished_at   = Column(DateTime, nullable=True)


class LlmLog(Base):
    """LLM 调用日志（蒸馏专用；reply 链路下线，等 B 出来后再加回）。"""
    __tablename__ = "llm_logs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    purpose          = Column(String, nullable=False)             # 'distill'
    character_id     = Column(String, nullable=True, index=True)
    request_messages = Column(Text, nullable=False)
    response_raw     = Column(Text, nullable=False)
    model            = Column(String, nullable=True)
    created_at       = Column(DateTime, default=utc_now, nullable=False)
