import asyncio
import json
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis
from sqlalchemy.orm import Session

from robot.clients import ChatAPIClient, ProviderClient
from robot.db import SessionLocal, utc_now
from robot.models import Contact, ProviderConfig, Robot, RobotMessage, SessionRecord

logger = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT = 120.0
REDIS_INBOX_KEY = "robot:inbox"


@dataclass(frozen=True)
class RuntimeOptions:
    chat_api_base_url: str
    redis_url: str
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
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

    parsed: List[Dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            raise ValueError("LLM response contains a non-object message item")
        if "content" not in msg:
            raise ValueError("LLM response message is missing content")
        parsed.append({
            "delay_seconds": int(msg.get("delay_seconds", 0)),
            "content": str(msg["content"]),
        })
    return parsed


def get_provider_config(db: Session, session_record: SessionRecord) -> Optional[ProviderConfig]:
    if session_record.provider_config_id:
        return db.query(ProviderConfig).filter(ProviderConfig.id == session_record.provider_config_id).first()

    configs = db.query(ProviderConfig).order_by(ProviderConfig.created_at.asc()).all()
    if not configs:
        return None
    if len(configs) > 1:
        raise RuntimeError(
            f"Session {session_record.id} 没有指定 Provider Config，"
            "且数据库中存在多个 Provider Config，请在 Session 上明确选择一个"
        )
    return configs[0]


class RobotRuntime:
    def __init__(self, options: RuntimeOptions):
        self.options = options
        self.chat = ChatAPIClient(options.chat_api_base_url)
        self.provider = ProviderClient(options.request_timeout)
        self.redis: aioredis.Redis = aioredis.from_url(options.redis_url, decode_responses=True)
        self._task: Optional[asyncio.Task[Any]] = None
        self._session_tasks: Dict[str, asyncio.Task[Any]] = {}

    async def start(self):
        await self._recover_unprocessed()
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._consume_loop(), name="robot-consumer")

    async def stop(self):
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        for task in self._session_tasks.values():
            task.cancel()
        for task in self._session_tasks.values():
            with suppress(asyncio.CancelledError):
                await task
        await self.chat.close()
        await self.provider.close()
        await self.redis.aclose()

    async def _recover_unprocessed(self):
        """On startup, find sessions whose last message is from 'user' and re-trigger processing."""
        db = SessionLocal()
        try:
            sessions = db.query(SessionRecord).filter(SessionRecord.status == "active").all()
            for sr in sessions:
                last_msg = (
                    db.query(RobotMessage)
                    .filter(RobotMessage.session_id == sr.id)
                    .order_by(RobotMessage.id.desc())
                    .first()
                )
                if last_msg and last_msg.role == "user":
                    logger.info("Recovery: re-triggering session %s", sr.id)
                    await self.redis.lpush(
                        REDIS_INBOX_KEY,
                        json.dumps({"conversation_id": sr.adapter_thread_id, "role": "user", "content": "", "recovery": True}),
                    )
        finally:
            db.close()

    async def _consume_loop(self):
        logger.info("Consumer loop started")
        while True:
            try:
                result = await self.redis.brpop(REDIS_INBOX_KEY, timeout=5)
                if result is None:
                    continue
                _, raw = result
                payload = json.loads(raw)
                await self._handle_inbox_message(payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Consumer loop error: %s", exc)
                await asyncio.sleep(1)

    async def _handle_inbox_message(self, payload: Dict[str, Any]):
        conversation_id = payload.get("conversation_id")
        if not conversation_id:
            logger.warning("Inbox message missing conversation_id: %s", payload)
            return

        db = SessionLocal()
        try:
            session_record = (
                db.query(SessionRecord)
                .filter(SessionRecord.adapter_thread_id == conversation_id, SessionRecord.status == "active")
                .first()
            )
            if not session_record:
                logger.warning("No active session for conversation %s", conversation_id)
                return

            session_id = session_record.id

            # Store the inbound message (skip for recovery triggers)
            is_recovery = payload.get("recovery", False)
            if not is_recovery:
                db.add(RobotMessage(
                    session_id=session_id,
                    role=payload.get("role", "user"),
                    content=payload.get("content", ""),
                    created_at=utc_now(),
                ))
                db.commit()
        finally:
            db.close()

        # Cancel any existing processing task for this session and start a new one
        old_task = self._session_tasks.pop(session_id, None)
        if old_task and not old_task.done():
            old_task.cancel()
            with suppress(asyncio.CancelledError):
                await old_task

        task = asyncio.create_task(self._process_session(session_id), name=f"process-{session_id}")
        self._session_tasks[session_id] = task

    async def _process_session(self, session_id: str):
        try:
            replies = await self._generate_replies(session_id)
            await self._send_replies(session_id, replies)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Processing session %s failed: %s", session_id, exc)
        finally:
            self._session_tasks.pop(session_id, None)

    async def _generate_replies(self, session_id: str) -> List[Dict[str, Any]]:
        db = SessionLocal()
        try:
            session_record = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
            if not session_record or session_record.status != "active":
                return []

            robot = db.query(Robot).filter(Robot.id == session_record.robot_id).first()
            contact = db.query(Contact).filter(Contact.id == session_record.contact_id).first()
            if not robot or not contact:
                logger.error("Session %s references missing robot or contact", session_id)
                return []

            if self.options.echo_mode:
                last_msg = (
                    db.query(RobotMessage)
                    .filter(RobotMessage.session_id == session_id, RobotMessage.role == "user")
                    .order_by(RobotMessage.id.desc())
                    .first()
                )
                return [{"delay_seconds": 1, "content": f"[复读] {last_msg.content if last_msg else ''}"}]

            provider_config = get_provider_config(db, session_record)
            if not provider_config:
                logger.warning("No provider config for session %s", session_id)
                return []
            if not provider_config.api_key:
                logger.error("Provider config %s missing api_key", provider_config.id)
                return []

            history = (
                db.query(RobotMessage)
                .filter(RobotMessage.session_id == session_id)
                .order_by(RobotMessage.id.asc())
                .all()
            )

            system_parts = [OUTPUT_FORMAT_INSTRUCTION]
            if robot.profile:
                system_parts.append(robot.profile)
            if contact.profile:
                system_parts.append(f"\n【当前联系人档案：{contact.name}】\n{contact.profile}")

            llm_messages: List[Dict[str, str]] = [{"role": "system", "content": "\n\n".join(system_parts)}]
            for msg in history:
                role = "assistant" if msg.role == "assistant" else "user"
                content = msg.content
                if content.startswith("data:"):
                    content = "[附件已省略]"
                llm_messages.append({"role": role, "content": content})

            base_url = provider_config.base_url
            api_key = provider_config.api_key
            model = provider_config.default_model
        finally:
            db.close()

        response_text = await self.provider.complete_chat(base_url, api_key, model, llm_messages)
        return parse_llm_response(response_text)

    async def _send_replies(self, session_id: str, replies: List[Dict[str, Any]]):
        if not replies:
            return

        db = SessionLocal()
        try:
            session_record = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
            if not session_record or session_record.status != "active":
                return
            adapter_thread_id = session_record.adapter_thread_id
        finally:
            db.close()

        for reply in replies:
            delay = max(int(reply.get("delay_seconds", 0)), 0)
            content = str(reply.get("content", ""))

            if delay > 0:
                await asyncio.sleep(delay)

            # Store reply in robot_messages
            db = SessionLocal()
            try:
                db.add(RobotMessage(
                    session_id=session_id,
                    role="assistant",
                    content=content,
                    created_at=utc_now(),
                ))
                db.commit()
            finally:
                db.close()

            # Forward reply to Chat adapter
            try:
                await self.chat.send_message(adapter_thread_id, content)
            except Exception as exc:
                logger.error("Failed to send reply to adapter for session %s: %s", session_id, exc)