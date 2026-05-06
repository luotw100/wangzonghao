from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from chat.db import Base, utc_now


class Account(Base):
    __tablename__ = "chat_accounts"

    id = Column(String, primary_key=True, index=True)
    username = Column(String, nullable=False, unique=True, index=True)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    avatar_url = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active")
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)

    contacts = relationship("Contact", back_populates="account")
    conversations = relationship("Conversation", back_populates="account")


class AuthSession(Base):
    __tablename__ = "chat_auth_sessions"

    id = Column(String, primary_key=True, index=True)
    account_id = Column(
        String, ForeignKey("chat_accounts.id"), nullable=False, index=True
    )
    token_hash = Column(String, nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    last_seen_at = Column(DateTime, default=utc_now, nullable=False)

    account = relationship("Account")


class Contact(Base):
    __tablename__ = "chat_contacts"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "platform_contact_id", name="uq_chat_contact_platform_id"
        ),
    )

    id = Column(String, primary_key=True, index=True)
    account_id = Column(
        String, ForeignKey("chat_accounts.id"), nullable=False, index=True
    )
    platform_contact_id = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    avatar_url = Column(String, nullable=True)
    note = Column(Text, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)

    account = relationship("Account", back_populates="contacts")
    conversations = relationship("Conversation", back_populates="contact")


class Conversation(Base):
    __tablename__ = "chat_conversations"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "contact_id", name="uq_chat_direct_conversation"
        ),
    )

    id = Column(String, primary_key=True, index=True)
    account_id = Column(
        String, ForeignKey("chat_accounts.id"), nullable=False, index=True
    )
    contact_id = Column(
        String, ForeignKey("chat_contacts.id"), nullable=False, index=True
    )
    title = Column(String, nullable=False)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)

    account = relationship("Account", back_populates="conversations")
    contact = relationship("Contact", back_populates="conversations")


class Message(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(
        String, ForeignKey("chat_accounts.id"), nullable=False, index=True
    )
    conversation_id = Column(
        String, ForeignKey("chat_conversations.id"), index=True, nullable=False
    )
    sender_type = Column(String, nullable=False)
    sender_contact_id = Column(
        String, ForeignKey("chat_contacts.id"), nullable=True, index=True
    )
    msg_type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String, nullable=False, default="live")
    created_at = Column(DateTime, default=utc_now, nullable=False)

    conversation = relationship("Conversation")
    sender_contact = relationship("Contact")


class ImportBatch(Base):
    __tablename__ = "chat_import_batches"

    id = Column(String, primary_key=True, index=True)
    account_id = Column(
        String, ForeignKey("chat_accounts.id"), nullable=False, index=True
    )
    conversation_id = Column(
        String, ForeignKey("chat_conversations.id"), nullable=False, index=True
    )
    filename = Column(String, nullable=True)
    message_count = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
