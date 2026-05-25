"""Chat sandbox 数据模型。

合并后 Chat 不再有自己的账号体系——账号统一从 ``auth.accounts`` 来（与 Studio 共用）。
Chat 自己的业务表（contacts / conversations / messages）落在 ``chat`` schema，
通过 FK 引用 ``auth.accounts.id`` 做数据隔离。

主键 ID 由应用层生成（带前缀的随机字符串），数据库不做自增。
每次 INSERT 均由应用层显式提供全部字段，不依赖列级 default。
数据按 account_id 完全隔离，任意跨账号查询均不会发生。
"""

from sqlalchemy import (
    BigInteger,
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


class Contact(Base):
    """联系人。属于某个账号的私有数据，不同账号之间完全隔离。

    username 是该联系人在 chat sandbox 内的唯一标识；若创建时不传，
    系统会自动生成一个随机 ID。remark_name 仅对本账号可见，不影响联系人自身的 nickname。
    同一账号下 (account_id, username) 有唯一约束。
    """

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("account_id", "username", name="uq_chat_contact_username"),
        {"schema": "chat"},
    )

    id          = Column(String(48),  primary_key=True, index=True)
    account_id  = Column(String(48),  ForeignKey("auth.accounts.id"), nullable=False, index=True)
    username    = Column(String(256), nullable=False)        # chat sandbox 内唯一标识
    nickname    = Column(String(256), nullable=False)        # 联系人显示名称
    remark_name = Column(String(256), nullable=True)         # 本账号私有备注
    created_at  = Column(DateTime(timezone=True), nullable=False)
    updated_at  = Column(DateTime(timezone=True), nullable=False)

    conversations = relationship("Conversation", back_populates="contact")


class Conversation(Base):
    """一对一会话。每个联系人对应恰好一个会话。

    title 默认等于联系人昵称，创建联系人时可自定义。
    updated_at 每次写入消息后刷新，会话列表按此字段降序排列。
    """

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("account_id", "contact_id", name="uq_chat_direct_conversation"),
        {"schema": "chat"},
    )

    id         = Column(String(48),  primary_key=True, index=True)
    account_id = Column(String(48),  ForeignKey("auth.accounts.id"),       nullable=False, index=True)
    contact_id = Column(String(48),  ForeignKey("chat.contacts.id"),       nullable=False, index=True)
    title      = Column(String(256), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    contact = relationship("Contact", back_populates="conversations")


class Message(Base):
    """消息。

    id 是全局自增大整型，可直接用作翻页游标（before_id / last_id）。
    sender_id 为 NULL 表示由账号本人发出；非 NULL 则为联系人 ID，表示对方发出
    （用于导入历史消息时区分方向）。
    非文本消息的 content 是上传到 S3 后的 storage key（格式 ``media/{account_id}/{uuid}``），
    需通过 GET /api/chat/media/{storage_key} 换取实际访问 URL。
    """

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "msg_type IN ('text', 'image', 'audio', 'video', 'file')",
            name="ck_chat_msg_type",
        ),
        Index("ix_chat_messages_conversation_id_id", "conversation_id", "id"),
        {"schema": "chat"},
    )

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id      = Column(String(48), ForeignKey("auth.accounts.id"),       nullable=False, index=True)
    conversation_id = Column(String(48), ForeignKey("chat.conversations.id"),  nullable=False)
    sender_id       = Column(String(48), ForeignKey("chat.contacts.id"),       nullable=True)   # NULL=本人发出
    msg_type        = Column(String(16), nullable=False)
    content         = Column(Text,       nullable=False)
    created_at      = Column(DateTime(timezone=True), nullable=False)

    conversation = relationship("Conversation")
    sender       = relationship("Contact")
