"""Chat sandbox 数据模型。

所有主键 ID 由应用层生成（带前缀的随机字符串），数据库不做自增。
每次 INSERT 均由应用层显式提供全部字段，不依赖列级 default。
数据按 account_id 完全隔离，任意跨账号查询均不会发生。
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from chat.db import Base


class Account(Base):
    """聊天沙箱账号。

    status: active（正常）/ disabled（已禁用，无法登录）。
    密码以 bcrypt 哈希存储，原文不持久化。
    """

    __tablename__ = "chat_accounts"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="ck_chat_account_status"),
    )

    id            = Column(String(48),  primary_key=True, index=True)
    username      = Column(String(64),  nullable=False, unique=True, index=True)  # 全局唯一，不可修改
    password_hash = Column(String(128), nullable=False)
    nickname      = Column(String(128), nullable=False)                           # 可改，仅展示用
    status        = Column(String(16),  nullable=False)                           # active / disabled
    created_at    = Column(DateTime(timezone=True), nullable=False)
    updated_at    = Column(DateTime(timezone=True), nullable=False)

    contacts      = relationship("Contact",      back_populates="account")
    conversations = relationship("Conversation", back_populates="account")


class AuthSession(Base):
    """登录 session。

    id 存的是 token 原文的 SHA-256 哈希，原始 token 只在登录响应中返回一次。
    每次鉴权成功后 expires_at 自动延后 24 小时（滑动有效期）。
    """

    __tablename__ = "chat_auth_sessions"

    id         = Column(String(64), primary_key=True, index=True)  # sha256(token)
    account_id = Column(String(48), ForeignKey("chat_accounts.id"), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)    # 24h 滑动有效期
    created_at = Column(DateTime(timezone=True), nullable=False)

    account    = relationship("Account")


class Contact(Base):
    """联系人。属于某个账号的私有数据，不同账号之间完全隔离。

    username 是该联系人在外部系统（如 chat sandbox）的唯一标识；
    若创建时不传，系统会自动生成一个随机 ID。
    remark_name 仅对本账号可见，不影响联系人自身的 nickname。
    同一账号下 (account_id, username) 有唯一约束。
    """

    __tablename__ = "chat_contacts"
    __table_args__ = (
        UniqueConstraint("account_id", "username", name="uq_chat_contact_username"),
    )

    id          = Column(String(48),  primary_key=True, index=True)
    account_id  = Column(String(48),  ForeignKey("chat_accounts.id"), nullable=False, index=True)
    username    = Column(String(256), nullable=False)        # 外部平台唯一标识，同账号下不重复
    nickname    = Column(String(256), nullable=False)        # 联系人显示名称
    remark_name = Column(String(256), nullable=True)         # 本账号私有备注，null 表示无备注
    created_at  = Column(DateTime(timezone=True), nullable=False)
    updated_at  = Column(DateTime(timezone=True), nullable=False)

    account       = relationship("Account",      back_populates="contacts")
    conversations = relationship("Conversation", back_populates="contact")


class Conversation(Base):
    """一对一会话。每个联系人对应恰好一个会话（数据库唯一约束保证）。

    title 默认等于联系人昵称，创建联系人时可自定义。
    updated_at 每次写入消息后刷新，会话列表按此字段降序排列。
    """

    __tablename__ = "chat_conversations"
    __table_args__ = (
        UniqueConstraint("account_id", "contact_id", name="uq_chat_direct_conversation"),
    )

    id         = Column(String(48),  primary_key=True, index=True)
    account_id = Column(String(48),  ForeignKey("chat_accounts.id"),      nullable=False, index=True)
    contact_id = Column(String(48),  ForeignKey("chat_contacts.id"),      nullable=False, index=True)
    title      = Column(String(256), nullable=False)   # 会话标题，默认取联系人昵称
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)  # 最后活跃时间，每发消息刷新

    account  = relationship("Account",  back_populates="conversations")
    contact  = relationship("Contact",  back_populates="conversations")


class Message(Base):
    """消息。

    id 是全局自增大整型，可直接用作翻页游标（before_id / last_id）。
    sender_id 为 NULL 表示由账号本人发出；非 NULL 则为联系人 ID，表示对方发出
    （用于导入历史消息时区分方向）。
    非文本消息的 content 是上传到 S3 后的 storage key（格式 media/{account_id}/{uuid}），
    需通过 GET /api/media/{storage_key} 换取实际访问 URL。
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(
            "msg_type IN ('text', 'image', 'audio', 'video', 'file')",
            name="ck_chat_msg_type",
        ),
        # 复合索引：会话内消息分页（conversation_id + id 升/降序翻页）
        Index("ix_chat_messages_conversation_id_id", "conversation_id", "id"),
    )

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id      = Column(String(48), ForeignKey("chat_accounts.id"),       nullable=False, index=True)
    conversation_id = Column(String(48), ForeignKey("chat_conversations.id"),  nullable=False)
    sender_id       = Column(String(48), ForeignKey("chat_contacts.id"),       nullable=True)   # NULL=本人发出
    msg_type        = Column(String(16), nullable=False)    # text / image / audio / video / file
    content         = Column(Text,       nullable=False)    # 文本正文 或 S3 storage key（媒体消息）
    created_at      = Column(DateTime(timezone=True), nullable=False)

    conversation = relationship("Conversation")
    sender       = relationship("Contact")
