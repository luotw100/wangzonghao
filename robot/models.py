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
# Auth — Account / Identity / LoginCode / AuthSession
# ---------------------------------------------------------------------------

class Account(Base):
    """登录主体。所有业务表通过 account_id 引用此表，与登录方式解耦。"""
    __tablename__ = "accounts"

    id            = Column(String, primary_key=True, index=True)
    role          = Column(String, nullable=False)                 # 'admin' | 'operator_owner'
    status        = Column(String, nullable=False, default="pending")  # pending | active | disabled
    display_name  = Column(String, nullable=True)
    created_at    = Column(DateTime, default=utc_now, nullable=False)
    updated_at    = Column(DateTime, default=utc_now, nullable=False)
    last_login_at = Column(DateTime, nullable=True)


class AccountIdentity(Base):
    """登录方式（邮箱/手机/微信 ...）。一个 account 可挂多个 identity。"""
    __tablename__ = "account_identities"

    id          = Column(String, primary_key=True, index=True)
    account_id  = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    provider    = Column(String, nullable=False)              # 'email' | 'phone' | 'wechat'
    identifier  = Column(String, nullable=False)              # 邮箱/手机号/openid
    verified_at = Column(DateTime, nullable=True)
    created_at  = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "identifier", name="uq_identity_provider_identifier"),
    )


class LoginCode(Base):
    """一次性登录验证码。单次使用、过期即作废。"""
    __tablename__ = "login_codes"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    provider    = Column(String, nullable=False)              # 'email'
    identifier  = Column(String, nullable=False, index=True)  # 邮箱
    code_hash   = Column(String, nullable=False)              # 不存明文
    expires_at  = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    attempts    = Column(Integer, nullable=False, default=0)
    ip          = Column(String, nullable=True)
    created_at  = Column(DateTime, default=utc_now, nullable=False)


class AuthSession(Base):
    """登录后的会话（30 天有效），HttpOnly cookie 持有 token，DB 只存其 hash。"""
    __tablename__ = "auth_sessions"

    id            = Column(String, primary_key=True, index=True)   # token sha256
    account_id    = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    expires_at    = Column(DateTime, nullable=False)
    revoked_at    = Column(DateTime, nullable=True)
    last_seen_at  = Column(DateTime, default=utc_now, nullable=False)
    user_agent    = Column(String, nullable=True)
    ip            = Column(String, nullable=True)
    created_at    = Column(DateTime, default=utc_now, nullable=False)


# ---------------------------------------------------------------------------
# Domain — Provider / Character / Contact / Session / Archive / Message / Job
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
    persona_md          = Column(Text, nullable=True)                      # 蒸馏出来的人设
    adapter_identities  = Column(JSON, nullable=False, default=dict)       # {chat: u_xxx, wechat_wxid_self: wxid_xxx}
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
    wechat_wxid     = Column(String, nullable=True)               # WeFlow 导出的 wxid
    chat_user_id    = Column(String, nullable=True)               # chat 模拟器里的 user_id（自动创建）
    card_md         = Column(Text, nullable=True)                 # 蒸馏出来的卡片
    status          = Column(String, nullable=False, default="active")
    created_at      = Column(DateTime, default=utc_now, nullable=False)
    updated_at      = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("character_id", "wechat_wxid", name="uq_contact_character_wxid"),
    )


class SessionRecord(Base):
    """连接器：Contact ↔ Adapter Thread。"""
    __tablename__ = "sessions"

    id                = Column(String, primary_key=True, index=True)
    contact_id        = Column(String, ForeignKey("contacts.id"), nullable=False, index=True)
    adapter_type      = Column(String, nullable=False, default="chat")
    adapter_thread_id = Column(String, nullable=False, index=True)
    status            = Column(String, nullable=False, default="active")  # active | paused | deleted
    created_at        = Column(DateTime, default=utc_now, nullable=False)
    updated_at        = Column(DateTime, default=utc_now, nullable=False)


class ChatArchive(Base):
    """上传的 WeFlow 聊天记录 artifact。"""
    __tablename__ = "chat_archives"

    id            = Column(String, primary_key=True, index=True)
    character_id  = Column(String, ForeignKey("characters.id"), nullable=False, index=True)
    filename      = Column(String, nullable=False)
    file_path     = Column(String, nullable=False)
    file_hash     = Column(String, nullable=False, index=True)
    self_wxid     = Column(String, nullable=False)              # 上传时主播指明哪个 wxid 是自己
    message_count = Column(Integer, nullable=False, default=0)
    contact_count = Column(Integer, nullable=False, default=0)
    uploaded_at   = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("character_id", "file_hash", name="uq_archive_character_hash"),
    )


class Message(Base):
    """统一消息表：upload 历史 + live 实时。"""
    __tablename__ = "messages"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    contact_id      = Column(String, ForeignKey("contacts.id"), nullable=False, index=True)
    archive_id      = Column(String, ForeignKey("chat_archives.id"), nullable=True, index=True)
    source          = Column(String, nullable=False)               # 'upload' | 'live'
    role            = Column(String, nullable=False)               # 'self' | 'counterpart'
    sender_name     = Column(String, nullable=True)
    content         = Column(Text, nullable=False)
    timestamp       = Column(DateTime, nullable=False, index=True) # 真实消息时间（upload 用历史时间）
    status          = Column(String, nullable=False, default="sent")  # scheduled | sent | canceled
    scheduled_for   = Column(DateTime, nullable=True)
    archive_msg_idx = Column(Integer, nullable=True)               # 在 archive 内的原始位置，幂等去重用
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
    progress      = Column(JSON, nullable=False, default=dict)         # {windows_done, windows_total}
    error_message = Column(Text, nullable=True)
    created_at    = Column(DateTime, default=utc_now, nullable=False)
    started_at    = Column(DateTime, nullable=True)
    finished_at   = Column(DateTime, nullable=True)


class LlmLog(Base):
    """LLM 调用日志，覆盖 reply 和 distill 两类调用。"""
    __tablename__ = "llm_logs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    purpose          = Column(String, nullable=False)             # 'reply' | 'distill'
    session_id       = Column(String, nullable=True, index=True)  # reply 调用
    character_id     = Column(String, nullable=True, index=True)  # distill 调用
    request_messages = Column(Text, nullable=False)
    response_raw     = Column(Text, nullable=False)
    model            = Column(String, nullable=True)
    created_at       = Column(DateTime, default=utc_now, nullable=False)
