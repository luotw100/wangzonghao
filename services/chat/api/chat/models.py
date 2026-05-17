from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from chat.db import Base


class Account(Base):
    __tablename__ = "chat_accounts"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="ck_chat_account_status"),
    )

    id = Column(String(48), primary_key=True, index=True)
    username = Column(String(64), nullable=False, unique=True, index=True)
    password_hash = Column(String(128), nullable=False)
    nickname = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    contacts = relationship("Contact", back_populates="account")
    conversations = relationship("Conversation", back_populates="account")


class AuthSession(Base):
    __tablename__ = "chat_auth_sessions"

    id = Column(String(64), primary_key=True, index=True)
    account_id = Column(String(48), ForeignKey("chat_accounts.id"), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

    account = relationship("Account")


class Contact(Base):
    __tablename__ = "chat_contacts"
    __table_args__ = (
        UniqueConstraint("account_id", "username", name="uq_chat_contact_username"),
    )

    id = Column(String(48), primary_key=True, index=True)
    account_id = Column(String(48), ForeignKey("chat_accounts.id"), nullable=False, index=True)
    username = Column(String(256), nullable=False)
    nickname = Column(String(256), nullable=False)
    remark_name = Column(String(256), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    account = relationship("Account", back_populates="contacts")
    conversations = relationship("Conversation", back_populates="contact")


class Conversation(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (
        UniqueConstraint("account_id", "contact_id", name="uq_chat_direct_conversation"),
    )

    id = Column(String(48), primary_key=True, index=True)
    account_id = Column(String(48), ForeignKey("chat_accounts.id"), nullable=False, index=True)
    contact_id = Column(String(48), ForeignKey("chat_contacts.id"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)

    account = relationship("Account", back_populates="conversations")
    contact = relationship("Contact", back_populates="conversations")


class Message(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("msg_type IN ('text', 'image', 'audio', 'video', 'file')", name="ck_chat_msg_type"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id = Column(String(48), ForeignKey("chat_accounts.id"), nullable=False, index=True)
    conversation_id = Column(String(48), ForeignKey("chat_conversations.id"), index=True, nullable=False)
    sender_id = Column(String(48), ForeignKey("chat_contacts.id"), nullable=True)
    msg_type = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

    conversation = relationship("Conversation")
    sender = relationship("Contact")
