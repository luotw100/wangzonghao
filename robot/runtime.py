import asyncio
import json
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from robot.clients import ChatAPIClient, ProviderClient
from robot.db import SessionLocal, utc_now
from robot.models import Contact, DispatchJob, GenerationJob, InboundEvent, ProviderConfig, ReplyPlan, Robot, SessionRecord

logger = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT = 120.0
DEFAULT_POLL_INTERVAL = 2.0


@dataclass(frozen=True)
class RuntimeOptions:
    chat_api_base_url: str
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    poll_interval: float = DEFAULT_POLL_INTERVAL
    echo_mode: bool = False


OUTPUT_FORMAT_INSTRUCTION = """你必须只输出一个合法 JSON 对象，不要输出 Markdown、解释文字或额外前后缀。
JSON 顶层结构必须严格如下：
{"messages": [{"delay_seconds": 数字, "content": "微信回复文本"}]}
messages[*].content 只能包含最终要发送给用户的聊天文本。"""


def parse_llm_response(text: str) -> List[Dict[str, Any]]:
    data = json.loads(text.strip())
    messages = data.get("messages")
    if not isinstance(messages, list):
        raise ValueError("LLM response does not contain a messages list")

    parsed_messages: List[Dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("LLM response contains a non-object message item")
        if "content" not in message:
            raise ValueError("LLM response message is missing content")
        parsed_messages.append(
            {
                "delay_seconds": int(message.get("delay_seconds", 0)),
                "content": str(message["content"]),
            }
        )
    return parsed_messages


def get_generation_provider_config(db: Session, session_record: SessionRecord) -> Optional[ProviderConfig]:
    """Return the ProviderConfig for a session.

    Priority: session.provider_config_id → any single provider in the DB.
    Raises RuntimeError if multiple providers exist and the session has no explicit choice.
    """
    if session_record.provider_config_id:
        return db.query(ProviderConfig).filter(ProviderConfig.id == session_record.provider_config_id).first()

    # Fallback: pick the only provider, or raise if ambiguous
    provider_configs = db.query(ProviderConfig).order_by(ProviderConfig.created_at.asc(), ProviderConfig.id.asc()).all()
    if not provider_configs:
        return None
    if len(provider_configs) > 1:
        raise RuntimeError(
            f"Session {session_record.id} 没有指定 Provider Config，"
            "且数据库中存在多个 Provider Config，请在 Session 上明确选择一个"
        )
    return provider_configs[0]


def cancel_pending_reply_work(db: Session, session_id: str):
    now = utc_now()
    pending_reply_plans = db.query(ReplyPlan).filter(ReplyPlan.session_id == session_id, ReplyPlan.status == "pending").all()
    for reply_plan in pending_reply_plans:
        reply_plan.status = "canceled"
        reply_plan.canceled_at = now
        reply_plan.updated_at = now
        reply_plan.failure_reason = "Superseded by newer inbound events"

    pending_dispatch_jobs = db.query(DispatchJob).filter(DispatchJob.session_id == session_id, DispatchJob.status == "pending").all()
    for dispatch_job in pending_dispatch_jobs:
        dispatch_job.status = "canceled"
        dispatch_job.error = "Superseded by newer inbound events"
        dispatch_job.finished_at = now


def cancel_pending_generation_jobs(db: Session, session_id: str):
    now = utc_now()
    pending_jobs = db.query(GenerationJob).filter(GenerationJob.session_id == session_id, GenerationJob.status == "pending").all()
    for job in pending_jobs:
        job.status = "canceled"
        job.error = "Superseded by newer inbound events"
        job.finished_at = now


class RobotRuntime:
    def __init__(self, runtime_options: RuntimeOptions):
        self.runtime_options = runtime_options
        self.chat = ChatAPIClient(runtime_options.chat_api_base_url)
        self.provider = ProviderClient(runtime_options.request_timeout)
        self._tasks: List[asyncio.Task[Any]] = []

    async def start(self):
        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self.ingest_loop(), name="robot-inbound-ingest"),
            loop.create_task(self.orchestrator_loop(), name="robot-orchestrator"),
            loop.create_task(self.generation_loop(), name="robot-generation"),
            loop.create_task(self.dispatch_loop(), name="robot-dispatch"),
        ]

    async def stop(self):
        for task in self._tasks:
            task.cancel()

        for task in self._tasks:
            with suppress(asyncio.CancelledError):
                await task

        await self.chat.close()
        await self.provider.close()

    async def ingest_loop(self):
        logger.info("Inbound event ingestor started")
        while True:
            try:
                await self._ingest_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Inbound ingest error: %s", exc)
            await asyncio.sleep(self.runtime_options.poll_interval)

    async def _ingest_once(self):
        db = SessionLocal()
        try:
            sessions = (
                db.query(SessionRecord)
                .filter(SessionRecord.status == "active")
                .order_by(SessionRecord.created_at.asc())
                .all()
            )
            snapshots = [(session.id, session.adapter_thread_id, session.last_ingested_message_id) for session in sessions]
        finally:
            db.close()

        for session_id, adapter_thread_id, last_ingested_message_id in snapshots:
            try:
                payload = await self.chat.get_messages(adapter_thread_id, last_id=last_ingested_message_id, timeout=0)
            except httpx.HTTPStatusError as err:
                if err.response.status_code == 404:
                    self._mark_session_orphaned(session_id)
                    continue
                raise

            new_messages = payload.get("messages", [])
            if not new_messages:
                continue
            self._record_inbound_messages(session_id, new_messages)

    def _record_inbound_messages(self, session_id: str, messages: List[Dict[str, Any]]):
        db = SessionLocal()
        try:
            session_record = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
            if not session_record or session_record.status != "active":
                return

            max_message_id = session_record.last_ingested_message_id
            inserted_user_event = False
            now = utc_now()
            for message in messages:
                message_id = int(message["id"])
                max_message_id = max(max_message_id, message_id)
                if message.get("role") != "user":
                    continue

                existing_event = (
                    db.query(InboundEvent)
                    .filter(InboundEvent.session_id == session_id, InboundEvent.adapter_message_id == message_id)
                    .first()
                )
                if existing_event:
                    continue

                db.add(
                    InboundEvent(
                        session_id=session_id,
                        adapter_message_id=message_id,
                        role="user",
                        content=str(message.get("content", "")),
                        status="pending",
                        created_at=now,
                    )
                )
                inserted_user_event = True

            session_record.last_ingested_message_id = max_message_id
            session_record.updated_at = now

            if inserted_user_event:
                cancel_pending_generation_jobs(db, session_id)
                cancel_pending_reply_work(db, session_id)

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def orchestrator_loop(self):
        logger.info("Session orchestrator started")
        while True:
            try:
                self._orchestrate_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Orchestrator error: %s", exc)
            await asyncio.sleep(self.runtime_options.poll_interval)

    def _orchestrate_once(self):
        db = SessionLocal()
        try:
            pending_session_ids = [
                session_id
                for (session_id,) in db.query(InboundEvent.session_id)
                .filter(InboundEvent.status == "pending")
                .distinct()
                .all()
            ]

            for session_id in pending_session_ids:
                session_record = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
                if not session_record or session_record.status != "active":
                    continue

                active_job_exists = (
                    db.query(GenerationJob)
                    .filter(GenerationJob.session_id == session_id, GenerationJob.status.in_(["pending", "running"]))
                    .first()
                )
                if active_job_exists:
                    continue

                latest_event = (
                    db.query(InboundEvent)
                    .filter(InboundEvent.session_id == session_id, InboundEvent.status == "pending")
                    .order_by(InboundEvent.id.desc())
                    .first()
                )
                if not latest_event:
                    continue

                if not self.runtime_options.echo_mode:
                    try:
                        provider_config = get_generation_provider_config(db, session_record)
                    except RuntimeError as exc:
                        logger.error("Orchestrator: cannot resolve provider for session %s: %s", session_id, exc)
                        continue
                    if provider_config is None:
                        logger.warning("Orchestrator: no provider config available, skipping session %s", session_id)
                        continue
                else:
                    provider_config = None

                generation_job = GenerationJob(
                    session_id=session_id,
                    trigger_event_id=latest_event.id,
                    provider_config_id=provider_config.id if provider_config else None,
                    provider_name=provider_config.name if provider_config else None,
                    provider_base_url=provider_config.base_url if provider_config else None,
                    selected_model=provider_config.default_model if provider_config else None,
                    status="pending",
                )
                db.add(generation_job)
                session_record.updated_at = utc_now()

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def generation_loop(self):
        logger.info("Generation worker started")
        while True:
            job_snapshot = self._take_generation_job()
            if not job_snapshot:
                await asyncio.sleep(1)
                continue

            try:
                replies = await self._generate_replies(job_snapshot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._fail_generation_job(job_snapshot["job_id"], job_snapshot["trigger_event_id"], str(exc))
                continue

            self._persist_generation_result(job_snapshot, replies)

    def _take_generation_job(self) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            job = db.query(GenerationJob).filter(GenerationJob.status == "pending").order_by(GenerationJob.created_at.asc()).first()
            if not job:
                return None

            session_record = db.query(SessionRecord).filter(SessionRecord.id == job.session_id).first()
            robot = db.query(Robot).filter(Robot.id == session_record.robot_id).first() if session_record else None
            contact = db.query(Contact).filter(Contact.id == session_record.contact_id).first() if session_record else None
            provider_config = (
                db.query(ProviderConfig).filter(ProviderConfig.id == job.provider_config_id).first()
                if job.provider_config_id
                else None
            )

            if not session_record or session_record.status != "active":
                self._fail_generation_job(job.id, job.trigger_event_id, "Session is not active")
                return None
            if not robot or not contact:
                self._fail_generation_job(job.id, job.trigger_event_id, "Session references a missing robot or contact")
                return None
            if not self.runtime_options.echo_mode and not provider_config:
                self._fail_generation_job(job.id, job.trigger_event_id, "Provider Config is missing")
                return None

            job.status = "running"
            job.started_at = utc_now()
            db.commit()

            return {
                "job_id": job.id,
                "session_id": session_record.id,
                "adapter_thread_id": session_record.adapter_thread_id,
                "trigger_event_id": job.trigger_event_id,
                "profile": robot.profile,
                "contact_name": contact.name,
                "contact_profile": contact.profile,
                "provider_base_url": provider_config.base_url if provider_config else None,
                "provider_api_key": provider_config.api_key if provider_config else None,
                "selected_model": job.selected_model,
            }
        finally:
            db.close()

    async def _generate_replies(self, job_snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        history = await self.chat.get_history(job_snapshot["adapter_thread_id"])

        if self.runtime_options.echo_mode:
            user_messages = [message for message in history if message.get("role") == "user"]
            last_text = str(user_messages[-1].get("content", "")) if user_messages else ""
            return [{"delay_seconds": 1, "content": f"[复读] {last_text}"}]

        if not job_snapshot["provider_api_key"]:
            raise ValueError("Provider config is missing api_key")
        if not job_snapshot["selected_model"]:
            raise ValueError("Provider config is missing default_model")

        system_parts = [OUTPUT_FORMAT_INSTRUCTION]
        if job_snapshot["profile"]:
            system_parts.append(job_snapshot["profile"])
        if job_snapshot["contact_profile"]:
            system_parts.append(f"\n【当前联系人档案：{job_snapshot['contact_name']}】\n{job_snapshot['contact_profile']}")

        messages: List[Dict[str, str]] = [{"role": "system", "content": "\n\n".join(system_parts)}]
        for message in history:
            role = "assistant" if message.get("role") == "robot" else "user"
            content = str(message.get("content", ""))
            if content.startswith("data:"):
                content = "[附件已省略]"
            messages.append({"role": role, "content": content})

        response_text = await self.provider.complete_chat(
            job_snapshot["provider_base_url"],
            job_snapshot["provider_api_key"],
            job_snapshot["selected_model"],
            messages,
        )
        return parse_llm_response(response_text)

    def _persist_generation_result(self, job_snapshot: Dict[str, Any], replies: List[Dict[str, Any]]):
        db = SessionLocal()
        try:
            job = db.query(GenerationJob).filter(GenerationJob.id == job_snapshot["job_id"]).first()
            session_record = db.query(SessionRecord).filter(SessionRecord.id == job_snapshot["session_id"]).first()
            if not job or not session_record or job.status != "running":
                return

            newer_pending_events = (
                db.query(InboundEvent)
                .filter(
                    InboundEvent.session_id == job.session_id,
                    InboundEvent.status == "pending",
                    InboundEvent.id > job.trigger_event_id,
                )
                .first()
            )
            if newer_pending_events:
                job.status = "canceled"
                job.error = "Superseded by newer inbound events"
                job.finished_at = utc_now()
                db.commit()
                return

            newer_jobs = (
                db.query(GenerationJob)
                .filter(
                    GenerationJob.session_id == job.session_id,
                    GenerationJob.id > job.id,
                    GenerationJob.status.in_(["pending", "running"]),
                )
                .first()
            )
            if newer_jobs:
                job.status = "canceled"
                job.error = "Superseded by a newer generation job"
                job.finished_at = utc_now()
                db.commit()
                return

            now = utc_now()
            cumulative_delay = 0
            for reply in replies:
                cumulative_delay += max(int(reply.get("delay_seconds", 0)), 0)
                scheduled_for = now + timedelta(seconds=cumulative_delay)
                reply_plan = ReplyPlan(
                    session_id=job.session_id,
                    generation_job_id=job.id,
                    content=str(reply.get("content", "")),
                    scheduled_for=scheduled_for,
                    status="pending",
                    created_at=now,
                    updated_at=now,
                )
                db.add(reply_plan)
                db.flush()
                db.add(
                    DispatchJob(
                        session_id=job.session_id,
                        reply_plan_id=reply_plan.id,
                        scheduled_for=scheduled_for,
                        status="pending",
                        created_at=now,
                    )
                )

            pending_events = (
                db.query(InboundEvent)
                .filter(
                    InboundEvent.session_id == job.session_id,
                    InboundEvent.status == "pending",
                    InboundEvent.id <= job.trigger_event_id,
                )
                .all()
            )
            for event in pending_events:
                event.status = "processed"
                event.processed_at = now

            job.status = "completed"
            job.finished_at = now
            session_record.updated_at = now
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _fail_generation_job(self, job_id: int, trigger_event_id: int, error: str):
        db = SessionLocal()
        try:
            job = db.query(GenerationJob).filter(GenerationJob.id == job_id).first()
            if not job:
                return

            now = utc_now()
            pending_events = (
                db.query(InboundEvent)
                .filter(
                    InboundEvent.session_id == job.session_id,
                    InboundEvent.status == "pending",
                    InboundEvent.id <= trigger_event_id,
                )
                .all()
            )
            for event in pending_events:
                event.status = "failed"
                event.processed_at = now

            job.status = "failed"
            job.error = error
            job.finished_at = now
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def dispatch_loop(self):
        logger.info("Dispatch worker started")
        while True:
            job_snapshot = self._take_dispatch_job()
            if not job_snapshot:
                await asyncio.sleep(1)
                continue

            try:
                await self.chat.send_message(job_snapshot["adapter_thread_id"], job_snapshot["content"])
            except asyncio.CancelledError:
                raise
            except httpx.HTTPStatusError as err:
                if err.response.status_code == 404:
                    self._mark_session_orphaned(job_snapshot["session_id"])
                self._fail_dispatch_job(job_snapshot["job_id"], job_snapshot["reply_plan_id"], str(err))
                continue
            except Exception as exc:
                self._fail_dispatch_job(job_snapshot["job_id"], job_snapshot["reply_plan_id"], str(exc))
                continue

            self._complete_dispatch_job(job_snapshot["job_id"], job_snapshot["reply_plan_id"], job_snapshot["session_id"])

    def _take_dispatch_job(self) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            now = utc_now()
            dispatch_job = (
                db.query(DispatchJob)
                .filter(DispatchJob.status == "pending", DispatchJob.scheduled_for <= now)
                .order_by(DispatchJob.scheduled_for.asc(), DispatchJob.id.asc())
                .first()
            )
            if not dispatch_job:
                return None

            reply_plan = db.query(ReplyPlan).filter(ReplyPlan.id == dispatch_job.reply_plan_id).first()
            session_record = db.query(SessionRecord).filter(SessionRecord.id == dispatch_job.session_id).first()
            if not reply_plan or not session_record or session_record.status != "active":
                self._fail_dispatch_job(
                    dispatch_job.id,
                    dispatch_job.reply_plan_id,
                    "Dispatch job references a missing or inactive session/reply plan",
                )
                return None

            dispatch_job.status = "running"
            dispatch_job.started_at = now
            db.commit()

            return {
                "job_id": dispatch_job.id,
                "reply_plan_id": reply_plan.id,
                "session_id": session_record.id,
                "adapter_thread_id": session_record.adapter_thread_id,
                "content": reply_plan.content,
            }
        finally:
            db.close()

    def _complete_dispatch_job(self, job_id: int, reply_plan_id: int, session_id: str):
        db = SessionLocal()
        try:
            dispatch_job = db.query(DispatchJob).filter(DispatchJob.id == job_id).first()
            reply_plan = db.query(ReplyPlan).filter(ReplyPlan.id == reply_plan_id).first()
            session_record = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
            if not dispatch_job or not reply_plan:
                return

            now = utc_now()
            dispatch_job.status = "completed"
            dispatch_job.finished_at = now
            reply_plan.status = "sent"
            reply_plan.sent_at = now
            reply_plan.updated_at = now
            if session_record:
                session_record.updated_at = now
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _fail_dispatch_job(self, job_id: int, reply_plan_id: int, error: str):
        db = SessionLocal()
        try:
            dispatch_job = db.query(DispatchJob).filter(DispatchJob.id == job_id).first()
            reply_plan = db.query(ReplyPlan).filter(ReplyPlan.id == reply_plan_id).first()
            if not dispatch_job or not reply_plan:
                return

            now = utc_now()
            dispatch_job.status = "failed"
            dispatch_job.error = error
            dispatch_job.finished_at = now
            reply_plan.status = "failed"
            reply_plan.failure_reason = error
            reply_plan.updated_at = now
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _mark_session_orphaned(self, session_id: str):
        db = SessionLocal()
        try:
            session_record = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
            if not session_record:
                return

            session_record.status = "orphaned"
            session_record.updated_at = utc_now()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()