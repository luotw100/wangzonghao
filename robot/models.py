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


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id            = Column(String, primary_key=True, index=True)
    name          = Column(String, nullable=False)
    base_url      = Column(String, nullable=False)
    api_key       = Column(Text, nullable=True)
    default_model = Column(String, nullable=False)
    created_at    = Column(DateTime, default=utc_now, nullable=False)
    updated_at    = Column(DateTime, default=utc_now, nullable=False)


class Operator(Base):
    """主播本人。一个真实运营者一个 Operator。"""
    __tablename__ = "operators"

    id                  = Column(String, primary_key=True, index=True)
    name                = Column(String, nullable=False)
    persona_md          = Column(Text, nullable=True)                      # 蒸馏出来的人设
    adapter_identities  = Column(JSON, nullable=False, default=dict)       # {chat: u_xxx, wechat_wxid_self: wxid_xxx}
    provider_config_id  = Column(String, ForeignKey("provider_configs.id"), nullable=True, index=True)
    status              = Column(String, nullable=False, default="active")
    created_at          = Column(DateTime, default=utc_now, nullable=False)
    updated_at          = Column(DateTime, default=utc_now, nullable=False)


class Contact(Base):
    """粉丝/联系人。隶属于某个 Operator。"""
    __tablename__ = "contacts"

    id              = Column(String, primary_key=True, index=True)
    operator_id     = Column(String, ForeignKey("operators.id"), nullable=False, index=True)
    display_name    = Column(String, nullable=False)
    wechat_wxid     = Column(String, nullable=True)               # WeFlow 导出的 wxid
    chat_user_id    = Column(String, nullable=True)               # chat 模拟器里的 user_id（自动创建）
    card_md         = Column(Text, nullable=True)                 # 蒸馏出来的卡片
    status          = Column(String, nullable=False, default="active")
    created_at      = Column(DateTime, default=utc_now, nullable=False)
    updated_at      = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("operator_id", "wechat_wxid", name="uq_contact_operator_wxid"),
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
    operator_id   = Column(String, ForeignKey("operators.id"), nullable=False, index=True)
    filename      = Column(String, nullable=False)
    file_path     = Column(String, nullable=False)
    file_hash     = Column(String, nullable=False, index=True)
    self_wxid     = Column(String, nullable=False)              # 上传时主播指明哪个 wxid 是自己
    message_count = Column(Integer, nullable=False, default=0)
    contact_count = Column(Integer, nullable=False, default=0)
    uploaded_at   = Column(DateTime, default=utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("operator_id", "file_hash", name="uq_archive_operator_hash"),
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
    operator_id   = Column(String, ForeignKey("operators.id"), nullable=False, index=True)
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
    operator_id      = Column(String, nullable=True, index=True)  # distill 调用
    request_messages = Column(Text, nullable=False)
    response_raw     = Column(Text, nullable=False)
    model            = Column(String, nullable=True)
    created_at       = Column(DateTime, default=utc_now, nullable=False)
