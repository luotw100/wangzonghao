from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from robot.db import Base, utc_now


class Robot(Base):
    __tablename__ = "robots"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    profile = Column(Text, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    profile = Column(Text, nullable=True)
    is_deleted = Column(Boolean, nullable=False, default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    base_url = Column(String, nullable=False)
    api_key = Column(Text, nullable=True)
    default_model = Column(String, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class SessionRecord(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=True)
    robot_id = Column(String, index=True, nullable=False)
    contact_id = Column(String, index=True, nullable=False)
    provider_config_id = Column(String, index=True, nullable=True)
    adapter_type = Column(String, nullable=False, default="chat")
    adapter_thread_id = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class RobotMessage(Base):
    __tablename__ = "robot_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True, nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="sent")  # scheduled, sent, canceled
    scheduled_for = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class LlmLog(Base):
    __tablename__ = "llm_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True, nullable=False)
    request_messages = Column(Text, nullable=False)   # JSON: the messages array sent to LLM
    request_pending = Column(Text, nullable=True)      # JSON: pending contents sent to LLM (null if none)
    response_raw = Column(Text, nullable=False)        # raw LLM response text
    model = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)