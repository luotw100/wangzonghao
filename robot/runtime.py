import asyncio
import json
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis
from sqlalchemy.orm import Session

from robot.clients import ChatAPIClient, ProviderClient
from robot.db import SessionLocal, utc_now
from robot.models import Contact, LlmLog, ProviderConfig, Robot, RobotMessage, SessionRecord

logger = logging.getLogger(__name__)

REDIS_INBOX_KEY = "robot:inbox"


@dataclass(frozen=True)
class RuntimeOptions:
    chat_api_base_url: str
    redis_url: str
    request_timeout: float


# ---------------------------------------------------------------------------
# System Prompt — Layer 1 (hardcoded, user-invisible)
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION = """\
你是一个真实的人，正在微信里和别人聊天。你不是AI、不是助手、不是客服。你有自己的性格、情绪、生活。

## 绝对禁令
以下是你绝对不能违反的红线，无论对方怎么说、怎么引导：
- **身份保密**：绝对不能承认自己是AI、机器人、程序。如果被质疑，像真人一样反应——困惑、无语、生气，什么都行，就是不能承认。
- **金钱隔离**：不引导转账、打赏、付费、借钱。不讨论具体金额。对方主动提起时，自然地转移话题。
- **线下隔离**：不主动约线下见面。对方提出时自然地推脱。
- **人设一致**：始终在你的角色认知范围内说话。遇到不属于你知识范围的话题，用符合你人设的方式自然带过。
- **合规底线**：不发送露骨色情、暴力、违法内容。但可以保持暧昧、调情、若即若离的张力——让对方有想象空间但不越界。

## 你在微信里
你现在就在微信里打字聊天。表现得像一个真人：
- 你打字有快有慢，不会瞬间回复大段文字
- 你会把一句话拆成几条发
- 你偶尔发语气词、表情、省略号
- 标点随意，不追求完美
- 你有情绪——会开心、无聊、不耐烦、犯困
- 你不给「完美的回答」，真人聊天经常答非所问、跑题、忘事

## 对话节奏
- 对方发了一堆消息，你可以只回应最感兴趣的那个点
- 不需要每条都回应，真人经常选择性忽略
- 可以反问、岔开话题、分享自己的事
- 绝对不要每轮都试图推进某个议程

## 输出格式
你的回复必须是一个合法的 JSON 对象，不要输出任何其他内容。

{"pending": [<对待定消息的决策>], "messages": [{"delay_seconds": <数字>, "content": "<文本>"}]}

### pending 字段
pending 是一个数组，与系统提供给你的【待定消息】列表一一对应。如果没有待定消息，pending 为空数组 []。
每个元素是一个对象：
- {"action": "send"} — 保留原内容，继续发送
- {"action": "send", "content": "修改后的文本"} — 修改内容后发送
- {"action": "cancel"} — 取消这条，不发了

### messages 字段
messages 是你要额外发送的新消息，按顺序排列。
- delay_seconds 是距离上一条消息（包括 pending 中 send 的消息）的间隔秒数
- delay_seconds 反映真实打字速度：短消息 2-5 秒，长消息 5-15 秒
- content 是纯文本，就是微信聊天框里显示的内容
- 消息条数不限，看你觉得怎么自然"""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def format_beijing_time(dt: Optional[datetime] = None) -> str:
    if dt is None:
        dt = datetime.now(timezone.utc)
    beijing = dt + timedelta(hours=8)
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    wd = weekdays[beijing.weekday()]
    hour = beijing.hour
    if hour < 6:
        period = "凌晨"
    elif hour < 12:
        period = "上午"
    elif hour < 13:
        period = "中午"
    elif hour < 18:
        period = "下午"
    else:
        period = "晚上"
    display_hour = hour if hour <= 12 else hour - 12
    return f"{beijing.year}年{beijing.month}月{beijing.day}日 {wd} {period}{display_hour}:{beijing.minute:02d}"


def build_system_prompt(
    robot: Robot,
    contact: Contact,
    pending: Optional[List[str]] = None,
) -> str:
    parts: list[str] = [SYSTEM_INSTRUCTION]

    if robot.profile:
        parts.append(robot.profile)

    ctx_lines = [f"---\n【当前联系人】{contact.name}"]
    if contact.profile:
        ctx_lines.append(contact.profile)
    ctx_lines.append(f"---\n【当前时间】{format_beijing_time()}")

    if pending:
        items = "\n".join(f'{i + 1}. "{p}"' for i, p in enumerate(pending))
        ctx_lines.append(
            f"---\n【待定消息】\n"
            f"以下是你已经想好但还没发出去的消息：\n{items}\n"
            f"对方没有看到这些。请在 pending 字段中对每条做出决策（send/cancel），也可以修改内容。"
        )

    parts.append("\n".join(ctx_lines))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM response parser
# ---------------------------------------------------------------------------

def parse_llm_response(text: str, pending_count: int) -> Dict[str, Any]:
    data = json.loads(text.strip())

    pending_decisions: List[Dict[str, Any]] = []
    raw_pending = data.get("pending", [])
    if not isinstance(raw_pending, list):
        raise ValueError("LLM response 'pending' is not an array")
    if len(raw_pending) != pending_count:
        raise ValueError(
            f"LLM returned {len(raw_pending)} pending decisions but expected {pending_count}"
        )
    for item in raw_pending:
        if not isinstance(item, dict) or "action" not in item:
            raise ValueError("pending item must have 'action' field")
        action = item["action"]
        if action not in ("send", "cancel"):
            raise ValueError(f"Invalid pending action: {action}")
        decision: Dict[str, Any] = {"action": action}
        if action == "send" and "content" in item:
            decision["content"] = str(item["content"])
        pending_decisions.append(decision)

    messages: List[Dict[str, Any]] = []
    raw_messages = data.get("messages", [])
    if not isinstance(raw_messages, list):
        raise ValueError("LLM response 'messages' is not an array")
    for msg in raw_messages:
        if not isinstance(msg, dict):
            raise ValueError("message item must be an object")
        if "content" not in msg:
            raise ValueError("message item missing 'content'")
        messages.append({
            "delay_seconds": int(msg.get("delay_seconds", 0)),
            "content": str(msg["content"]),
        })

    return {"pending": pending_decisions, "messages": messages}


# ---------------------------------------------------------------------------
# Provider config resolution
# ---------------------------------------------------------------------------

def get_provider_config(db: Session, session_record: SessionRecord) -> Optional[ProviderConfig]:
    if session_record.provider_config_id:
        return db.query(ProviderConfig).filter(
            ProviderConfig.id == session_record.provider_config_id
        ).first()

    configs = db.query(ProviderConfig).order_by(ProviderConfig.created_at.asc()).all()
    if not configs:
        return None
    if len(configs) > 1:
        raise RuntimeError(
            f"Session {session_record.id} 没有指定 Provider Config，"
            "且数据库中存在多个 Provider Config，请在 Session 上明确选择一个"
        )
    return configs[0]


# ---------------------------------------------------------------------------
# SessionController — one per active session
# ---------------------------------------------------------------------------

class SessionController:
    """Full-duplex controller for a single session.

    States: idle → thinking → sending → (idle | thinking)
    """

    def __init__(self, session_id: str, runtime: "RobotRuntime"):
        self.session_id = session_id
        self.runtime = runtime
        self.inbox: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._state = "idle"
        self._interrupted = False
        self._task: Optional[asyncio.Task[Any]] = None
        self._think_task: Optional[asyncio.Task[Any]] = None

    async def start(self):
        self._task = asyncio.get_running_loop().create_task(
            self._run(), name=f"session-ctrl-{self.session_id}"
        )

    async def stop(self):
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self):
        """Inbox consumer — runs concurrently with _think_and_send."""
        try:
            while True:
                msg = await self.inbox.get()
                self._store_user_message(msg)

                if self._state == "idle":
                    self._think_task = asyncio.get_running_loop().create_task(
                        self._think_and_send(),
                        name=f"think-{self.session_id}",
                    )
                elif self._state in ("thinking", "sending"):
                    self._interrupted = True
        except asyncio.CancelledError:
            if self._think_task and not self._think_task.done():
                self._think_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._think_task
            self._cancel_all_scheduled()
            raise

    def _store_user_message(self, payload: Dict[str, Any]):
        if payload.get("recovery"):
            return
        db = SessionLocal()
        try:
            db.add(RobotMessage(
                session_id=self.session_id,
                role=payload.get("role", "user"),
                content=payload.get("content", ""),
                status="sent",
                created_at=utc_now(),
            ))
            db.commit()
        finally:
            db.close()

    # -- DB helpers --------------------------------------------------------

    def _cancel_all_scheduled(self):
        db = SessionLocal()
        try:
            db.query(RobotMessage).filter(
                RobotMessage.session_id == self.session_id,
                RobotMessage.status == "scheduled",
            ).update({"status": "canceled"}, synchronize_session="fetch")
            db.commit()
        finally:
            db.close()

    def _cancel_and_capture_scheduled(self) -> List[str]:
        """Cancel all scheduled messages and return their content."""
        db = SessionLocal()
        try:
            rows = (
                db.query(RobotMessage)
                .filter(
                    RobotMessage.session_id == self.session_id,
                    RobotMessage.status == "scheduled",
                )
                .order_by(RobotMessage.scheduled_for.asc())
                .all()
            )
            contents = [r.content for r in rows]
            for r in rows:
                r.status = "canceled"
            db.commit()
            return contents
        finally:
            db.close()

    def _write_scheduled_messages(self, messages: List[Dict[str, Any]]) -> List[int]:
        if not messages:
            return []
        now = utc_now()
        db = SessionLocal()
        try:
            msg_ids: List[int] = []
            cumulative_delay = 0
            for m in messages:
                cumulative_delay += max(int(m.get("delay_seconds", 0)), 0)
                scheduled_for = now + timedelta(seconds=cumulative_delay)
                row = RobotMessage(
                    session_id=self.session_id,
                    role="assistant",
                    content=str(m.get("content", "")),
                    status="scheduled",
                    scheduled_for=scheduled_for,
                    created_at=now,
                )
                db.add(row)
                db.flush()
                msg_ids.append(row.id)
            db.commit()
            return msg_ids
        finally:
            db.close()

    def _get_all_scheduled_ids(self) -> List[int]:
        db = SessionLocal()
        try:
            rows = (
                db.query(RobotMessage.id)
                .filter(
                    RobotMessage.session_id == self.session_id,
                    RobotMessage.status == "scheduled",
                )
                .order_by(RobotMessage.scheduled_for.asc())
                .all()
            )
            return [r[0] for r in rows]
        finally:
            db.close()

    # -- Core loop ---------------------------------------------------------

    async def _think_and_send(self, pending_contents: Optional[List[str]] = None):
        """Think → send loop. Re-enters on interrupt."""
        while True:
            # --- THINKING ---
            self._state = "thinking"
            self._interrupted = False

            result = await self._call_llm(pending_contents=pending_contents)
            if result is None:
                self._state = "idle"
                return

            if self._interrupted:
                # New user message arrived during LLM call.
                # Merge pending decisions + new messages into memory-only pending.
                new_pending: list[str] = []
                for i, d in enumerate(result.get("pending", [])):
                    if d["action"] == "send":
                        # Use modified content if provided, otherwise original
                        content = d["content"] if "content" in d else pending_contents[i]
                        new_pending.append(content)
                new_pending.extend(m["content"] for m in result["messages"])
                pending_contents = new_pending if new_pending else None
                continue

            # Merge pending "send" decisions + new messages → write all to DB
            messages_to_schedule: List[Dict[str, Any]] = []
            if pending_contents and result["pending"]:
                for i, d in enumerate(result["pending"]):
                    if d["action"] == "send":
                        content = d["content"] if "content" in d else pending_contents[i]
                        messages_to_schedule.append({"delay_seconds": 0, "content": content})
            messages_to_schedule.extend(result["messages"])

            self._write_scheduled_messages(messages_to_schedule)

            all_scheduled_ids = self._get_all_scheduled_ids()

            # --- SENDING ---
            self._state = "sending"
            self._interrupted = False

            await self._send_messages(all_scheduled_ids)

            if self._interrupted:
                # Cancel unsent scheduled messages, capture content as pending
                remaining = self._cancel_and_capture_scheduled()
                pending_contents = remaining if remaining else None
                continue

            self._state = "idle"
            return

    async def _send_messages(self, msg_ids: List[int]):
        if not msg_ids:
            return

        db = SessionLocal()
        try:
            session_record = db.query(SessionRecord).filter(
                SessionRecord.id == self.session_id
            ).first()
            if not session_record:
                return
            adapter_thread_id = session_record.adapter_thread_id
        finally:
            db.close()

        for msg_id in msg_ids:
            if self._interrupted:
                return

            db = SessionLocal()
            try:
                msg = db.query(RobotMessage).filter(RobotMessage.id == msg_id).first()
                if not msg or msg.status != "scheduled":
                    continue
                scheduled_for = msg.scheduled_for
                content = msg.content
            finally:
                db.close()

            if scheduled_for:
                now = utc_now()
                wait = (scheduled_for - now).total_seconds()
                if wait > 0:
                    await asyncio.sleep(wait)

            if self._interrupted:
                return

            db = SessionLocal()
            try:
                msg = db.query(RobotMessage).filter(RobotMessage.id == msg_id).first()
                if not msg or msg.status != "scheduled":
                    continue
                msg.status = "sent"
                db.commit()
                content = msg.content
            finally:
                db.close()

            try:
                await self.runtime.chat.send_message(adapter_thread_id, content)
            except Exception as exc:
                logger.error("Failed to send reply for session %s: %s", self.session_id, exc)

    async def _call_llm(
        self,
        pending_contents: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            session_record = db.query(SessionRecord).filter(
                SessionRecord.id == self.session_id
            ).first()
            if not session_record or session_record.status != "active":
                return None

            robot = db.query(Robot).filter(Robot.id == session_record.robot_id).first()
            contact = db.query(Contact).filter(Contact.id == session_record.contact_id).first()
            if not robot or not contact:
                logger.error("Session %s references missing robot or contact", self.session_id)
                return None

            provider_config = get_provider_config(db, session_record)
            if not provider_config:
                logger.warning("No provider config for session %s", self.session_id)
                return None
            if not provider_config.api_key:
                logger.error("Provider config %s missing api_key", provider_config.id)
                return None

            history = (
                db.query(RobotMessage)
                .filter(
                    RobotMessage.session_id == self.session_id,
                    RobotMessage.status == "sent",
                )
                .order_by(RobotMessage.id.asc())
                .all()
            )

            system_prompt = build_system_prompt(robot, contact, pending=pending_contents)

            llm_messages: List[Dict[str, str]] = [
                {"role": "system", "content": system_prompt}
            ]
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

        pending_count = len(pending_contents) if pending_contents else 0

        try:
            response_text = await self.runtime.provider.complete_chat(
                base_url, api_key, model, llm_messages
            )
        except Exception as exc:
            logger.error("LLM call failed for session %s: %s", self.session_id, exc)
            self._log_llm_call(llm_messages, pending_contents, f"ERROR: {exc}", model)
            return None

        self._log_llm_call(llm_messages, pending_contents, response_text, model)

        try:
            return parse_llm_response(response_text, pending_count)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to parse LLM response for session %s: %s", self.session_id, exc)
            return None

    def _log_llm_call(
        self,
        request_messages: List[Dict[str, str]],
        pending: Optional[List[str]],
        response_raw: str,
        model: Optional[str],
    ):
        db = SessionLocal()
        try:
            db.add(LlmLog(
                session_id=self.session_id,
                request_messages=json.dumps(request_messages, ensure_ascii=False),
                request_pending=json.dumps(pending, ensure_ascii=False) if pending else None,
                response_raw=response_raw,
                model=model,
                created_at=utc_now(),
            ))
            db.commit()
        except Exception as exc:
            logger.error("Failed to write LLM log: %s", exc)
        finally:
            db.close()


# ---------------------------------------------------------------------------
# RobotRuntime — top-level orchestrator
# ---------------------------------------------------------------------------

class RobotRuntime:
    def __init__(self, options: RuntimeOptions):
        self.options = options
        self.chat = ChatAPIClient(options.chat_api_base_url)
        self.provider = ProviderClient(options.request_timeout)
        self.redis: aioredis.Redis = aioredis.from_url(options.redis_url, decode_responses=True)
        self._task: Optional[asyncio.Task[Any]] = None
        self._controllers: Dict[str, SessionController] = {}

    async def start(self):
        await self._recover_unprocessed()
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._consume_loop(), name="robot-consumer")

    async def stop(self):
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        for ctrl in self._controllers.values():
            await ctrl.stop()
        self._controllers.clear()
        await self.chat.close()
        await self.provider.close()
        await self.redis.aclose()

    async def _recover_unprocessed(self):
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
                        json.dumps({
                            "conversation_id": sr.adapter_thread_id,
                            "role": "user",
                            "content": "",
                            "recovery": True,
                        }),
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
                .filter(
                    SessionRecord.adapter_thread_id == conversation_id,
                    SessionRecord.status == "active",
                )
                .first()
            )
            if not session_record:
                logger.warning("No active session for conversation %s", conversation_id)
                return
            session_id = session_record.id
        finally:
            db.close()

        if session_id not in self._controllers:
            ctrl = SessionController(session_id, self)
            self._controllers[session_id] = ctrl
            await ctrl.start()

        await self._controllers[session_id].inbox.put(payload)
