from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from robot.db import Base, utc_now


class Robot(Base):
    __tablename__ = "robots"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    profile = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    profile = Column(Text, nullable=True)
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
    adapter_type = Column(String, nullable=False, default="chat")
    adapter_thread_id = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, nullable=False, default="active")
    last_ingested_message_id = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class InboundEvent(Base):
    __tablename__ = "inbound_events"
    __table_args__ = (UniqueConstraint("session_id", "adapter_message_id", name="uq_inbound_events_session_message"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True, nullable=False)
    adapter_message_id = Column(Integer, nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, default=utc_now, nullable=False)
    processed_at = Column(DateTime, nullable=True)


class GenerationJob(Base):
    __tablename__ = "generation_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True, nullable=False)
    trigger_event_id = Column(Integer, index=True, nullable=False)
    provider_config_id = Column(String, index=True, nullable=True)
    provider_name = Column(String, nullable=True)
    provider_base_url = Column(String, nullable=True)
    selected_model = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


class ReplyPlan(Base):
    __tablename__ = "reply_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True, nullable=False)
    generation_job_id = Column(Integer, index=True, nullable=True)
    content = Column(Text, nullable=False)
    scheduled_for = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    canceled_at = Column(DateTime, nullable=True)
    failure_reason = Column(Text, nullable=True)


class DispatchJob(Base):
    __tablename__ = "dispatch_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True, nullable=False)
    reply_plan_id = Column(Integer, index=True, unique=True, nullable=False)
    scheduled_for = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="pending")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)