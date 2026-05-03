import asyncio
import json
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from robot.clients import ChatAdapter, ProviderClient
from robot.db import SessionLocal, utc_now
from robot.distill.pipeline import run_distill_for_operator
from robot.models import (
    Contact,
    DistillJob,
    LlmLog,
    Message,
    Operator,
    ProviderConfig,
    SessionRecord,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeOptions:
    chat_api_base_url: str
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

{"messages": ["第一条消息", "第二条消息"]}

- messages 是你要发送的消息字符串列表，按顺序排列
- 每条消息是纯文本，就是微信聊天框里显示的内容
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


def build_system_prompt(operator: Operator, contact: Contact) -> str:
    parts: list[str] = [SYSTEM_INSTRUCTION]

    ctx_lines: list[str] = []
    if operator.persona_md:
        ctx_lines.append(f"---\n【你的角色画像】\n{operator.persona_md}")
    if contact.card_md:
        ctx_lines.append(f"---\n【当前联系人画像】\n{contact.card_md}")
    ctx_lines.append(f"---\n【当前时间】{format_beijing_time()}")

    parts.append("\n".join(ctx_lines))
    return "\n\n".join(parts)


def build_chat_history(history: list[Message]) -> str:
    if not history:
        return "（暂无聊天记录，这是第一次对话）"
    lines: list[str] = []
    for msg in history:
        label = "我" if msg.role == "self" else "对方"
        content = msg.content
        if content.startswith("data:"):
            content = "[附件已省略]"
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM response parser
# ---------------------------------------------------------------------------

TYPING_CHARS_PER_SECOND = 6  # simulated typing speed for delay calculation


def parse_llm_response(text: str) -> List[str]:
    data = json.loads(text.strip())
    raw_messages = data.get("messages", [])
    if not isinstance(raw_messages, list):
        raise ValueError("LLM response 'messages' is not an array")
    messages: List[str] = []
    for msg in raw_messages:
        if not isinstance(msg, str):
            raise ValueError("message item must be a string")
        if msg.strip():
            messages.append(msg)
    return messages


# ---------------------------------------------------------------------------
# RobotRuntime — 1 scanner + N session loops
# ---------------------------------------------------------------------------

class RobotRuntime:
    def __init__(self, options: RuntimeOptions):
        self.options = options
        self.adapter = ChatAdapter(options.chat_api_base_url)
        self.provider = ProviderClient(options.request_timeout)
        self._scanner_task: Optional[asyncio.Task[Any]] = None
        self._session_tasks: Dict[str, asyncio.Task[Any]] = {}
        self._distill_scanner_task: Optional[asyncio.Task[Any]] = None
        self._distill_tasks: Dict[str, asyncio.Task[Any]] = {}

    async def start(self):
        loop = asyncio.get_running_loop()
        self._scanner_task = loop.create_task(self._scanner_loop(), name="session-scanner")
        self._distill_scanner_task = loop.create_task(
            self._distill_scanner_loop(), name="distill-scanner"
        )

    async def stop(self):
        if self._scanner_task:
            self._scanner_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._scanner_task
        if self._distill_scanner_task:
            self._distill_scanner_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._distill_scanner_task
        for task in list(self._session_tasks.values()) + list(self._distill_tasks.values()):
            task.cancel()
        for task in list(self._session_tasks.values()) + list(self._distill_tasks.values()):
            with suppress(asyncio.CancelledError):
                await task
        self._session_tasks.clear()
        self._distill_tasks.clear()
        await self.adapter.close()
        await self.provider.close()

    # -- Scanner -----------------------------------------------------------

    async def _scanner_loop(self):
        while True:
            try:
                db = SessionLocal()
                try:
                    active_ids = {
                        s.id for s in db.query(SessionRecord).filter(
                            SessionRecord.status == "active"
                        ).all()
                    }
                finally:
                    db.close()

                for sid in active_ids:
                    if sid not in self._session_tasks or self._session_tasks[sid].done():
                        self._session_tasks[sid] = asyncio.get_running_loop().create_task(
                            self._session_loop(sid), name=f"session-{sid}"
                        )

                for sid in list(self._session_tasks.keys()):
                    if sid not in active_ids:
                        self._session_tasks[sid].cancel()
                        with suppress(asyncio.CancelledError):
                            await self._session_tasks[sid]
                        del self._session_tasks[sid]

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Scanner error: %s", exc)

            await asyncio.sleep(5)

    # -- Distill scanner ---------------------------------------------------

    async def _distill_scanner_loop(self):
        while True:
            try:
                db = SessionLocal()
                try:
                    pending = (
                        db.query(DistillJob)
                        .filter(DistillJob.status == "pending")
                        .order_by(DistillJob.created_at.asc())
                        .all()
                    )
                    pending_ids = [(j.id, j.operator_id) for j in pending]
                finally:
                    db.close()

                # Cleanup finished tasks
                for jid in list(self._distill_tasks.keys()):
                    if self._distill_tasks[jid].done():
                        del self._distill_tasks[jid]

                for job_id, operator_id in pending_ids:
                    if job_id in self._distill_tasks:
                        continue
                    self._distill_tasks[job_id] = asyncio.get_running_loop().create_task(
                        self._run_distill_job(job_id, operator_id),
                        name=f"distill-{job_id}",
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Distill scanner error: %s", exc)

            await asyncio.sleep(5)

    async def _run_distill_job(self, job_id: str, operator_id: str):
        # Mark running
        db = SessionLocal()
        try:
            job = db.query(DistillJob).filter(DistillJob.id == job_id).first()
            if not job or job.status != "pending":
                return
            job.status = "running"
            job.started_at = utc_now()
            db.commit()
        finally:
            db.close()

        def progress_cb(state: Dict[str, int]):
            d = SessionLocal()
            try:
                j = d.query(DistillJob).filter(DistillJob.id == job_id).first()
                if j:
                    j.progress = state
                    d.commit()
            finally:
                d.close()

        try:
            await run_distill_for_operator(
                operator_id=operator_id,
                request_timeout=self.options.request_timeout,
                progress_cb=progress_cb,
            )
        except Exception as exc:
            logger.error("Distill job %s failed: %s", job_id, exc)
            db = SessionLocal()
            try:
                j = db.query(DistillJob).filter(DistillJob.id == job_id).first()
                if j:
                    j.status = "failed"
                    j.error_message = str(exc)
                    j.finished_at = utc_now()
                    db.commit()
            finally:
                db.close()
            return

        db = SessionLocal()
        try:
            j = db.query(DistillJob).filter(DistillJob.id == job_id).first()
            if j:
                j.status = "done"
                j.finished_at = utc_now()
                db.commit()
        finally:
            db.close()

    # -- Session loop ------------------------------------------------------

    async def _session_loop(self, session_id: str):
        ctx = self._load_session_ctx(session_id)
        if not ctx:
            return
        thread_id, contact_id, operator_chat_user_id = ctx

        last_id = 0
        try:
            result = await self.adapter.get_messages(thread_id, last_id=0, timeout=0)
            msgs = result.get("messages", [])
            if msgs:
                last_id = msgs[-1]["id"]
        except Exception as exc:
            logger.error("Failed to get initial messages for session %s: %s", session_id, exc)

        try:
            while True:
                try:
                    result = await self.adapter.get_messages(thread_id, last_id=last_id, timeout=0)
                    for msg in result.get("messages", []):
                        last_id = msg["id"]
                        if msg.get("sender_id") != operator_chat_user_id:
                            self._store_counterpart_message(contact_id, msg.get("content", ""))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("Poll error for session %s: %s", session_id, exc)

                if self._needs_reply(contact_id):
                    messages = await self._call_llm(session_id)
                    if messages:
                        msg_ids = self._write_scheduled_messages(contact_id, messages)
                        await self._send_scheduled(
                            session_id, thread_id, operator_chat_user_id, msg_ids
                        )

                await asyncio.sleep(1)
        finally:
            self._cancel_scheduled(contact_id)

    # -- Helpers -----------------------------------------------------------

    def _load_session_ctx(self, session_id: str):
        """Return (thread_id, contact_id, operator_chat_user_id) for the session."""
        db = SessionLocal()
        try:
            s = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
            if not s:
                return None
            contact = db.query(Contact).filter(Contact.id == s.contact_id).first()
            if not contact:
                logger.error("Session %s has missing contact %s", session_id, s.contact_id)
                return None
            operator = db.query(Operator).filter(Operator.id == contact.operator_id).first()
            if not operator:
                logger.error("Contact %s has missing operator %s", contact.id, contact.operator_id)
                return None
            chat_user_id = (operator.adapter_identities or {}).get("chat")
            if not chat_user_id:
                logger.error("Operator %s missing chat adapter identity", operator.id)
                return None
            return s.adapter_thread_id, contact.id, chat_user_id
        finally:
            db.close()

    def _store_counterpart_message(self, contact_id: str, content: str):
        now = utc_now()
        db = SessionLocal()
        try:
            db.add(Message(
                contact_id=contact_id,
                source="live",
                role="counterpart",
                content=content,
                timestamp=now,
                status="sent",
                created_at=now,
            ))
            db.commit()
        finally:
            db.close()

    def _needs_reply(self, contact_id: str) -> bool:
        db = SessionLocal()
        try:
            last_msg = (
                db.query(Message)
                .filter(
                    Message.contact_id == contact_id,
                    Message.status == "sent",
                )
                .order_by(Message.id.desc())
                .first()
            )
            return last_msg is not None and last_msg.role == "counterpart"
        finally:
            db.close()

    def _cancel_scheduled(self, contact_id: str):
        db = SessionLocal()
        try:
            db.query(Message).filter(
                Message.contact_id == contact_id,
                Message.status == "scheduled",
            ).update({"status": "canceled"}, synchronize_session="fetch")
            db.commit()
        finally:
            db.close()

    def _write_scheduled_messages(self, contact_id: str, messages: List[str]) -> List[int]:
        if not messages:
            return []
        now = utc_now()
        db = SessionLocal()
        try:
            msg_ids: List[int] = []
            cumulative_delay = 0.0
            for content in messages:
                delay = max(2.0, len(content) / TYPING_CHARS_PER_SECOND)
                cumulative_delay += delay
                scheduled_for = now + timedelta(seconds=cumulative_delay)
                row = Message(
                    contact_id=contact_id,
                    source="live",
                    role="self",
                    content=content,
                    timestamp=scheduled_for,
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

    async def _send_scheduled(
        self,
        session_id: str,
        thread_id: str,
        operator_chat_user_id: str,
        msg_ids: List[int],
    ):
        for msg_id in msg_ids:
            db = SessionLocal()
            try:
                msg = db.query(Message).filter(Message.id == msg_id).first()
                if not msg or msg.status != "scheduled":
                    continue
                scheduled_for = msg.scheduled_for
            finally:
                db.close()

            if scheduled_for:
                now = utc_now()
                wait = (scheduled_for - now).total_seconds()
                if wait > 0:
                    await asyncio.sleep(wait)

            db = SessionLocal()
            try:
                msg = db.query(Message).filter(Message.id == msg_id).first()
                if not msg or msg.status != "scheduled":
                    continue
                msg.status = "sent"
                msg.timestamp = utc_now()
                db.commit()
                content = msg.content
            finally:
                db.close()

            try:
                await self.adapter.send_message(thread_id, operator_chat_user_id, content)
            except Exception as exc:
                logger.error("Failed to send reply for session %s: %s", session_id, exc)

    # -- LLM ---------------------------------------------------------------

    async def _call_llm(self, session_id: str) -> Optional[List[str]]:
        db = SessionLocal()
        try:
            s = db.query(SessionRecord).filter(SessionRecord.id == session_id).first()
            if not s or s.status != "active":
                return None
            contact = db.query(Contact).filter(Contact.id == s.contact_id).first()
            if not contact:
                return None
            operator = db.query(Operator).filter(Operator.id == contact.operator_id).first()
            if not operator:
                return None

            provider_config = self._resolve_provider_config(db, operator)
            if not provider_config:
                logger.warning("No provider config for operator %s", operator.id)
                return None
            if not provider_config.api_key:
                logger.error("Provider config %s missing api_key", provider_config.id)
                return None

            history = (
                db.query(Message)
                .filter(
                    Message.contact_id == contact.id,
                    Message.status == "sent",
                )
                .order_by(Message.timestamp.asc(), Message.id.asc())
                .all()
            )

            system_prompt = build_system_prompt(operator, contact)
            chat_history = build_chat_history(history)

            llm_messages: List[Dict[str, str]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": chat_history},
            ]

            base_url = provider_config.base_url
            api_key = provider_config.api_key
            model = provider_config.default_model
        finally:
            db.close()

        max_retries = 5
        for attempt in range(max_retries):
            try:
                response_text, _usage = await self.provider.complete_chat(
                    base_url, api_key, model, llm_messages
                )
            except Exception as exc:
                logger.error("LLM call failed for session %s: %s", session_id, exc)
                self._log_llm_call(
                    purpose="reply",
                    session_id=session_id,
                    operator_id=None,
                    request_messages=llm_messages,
                    response_raw=f"ERROR: {exc}",
                    model=model,
                )
                return None

            self._log_llm_call(
                purpose="reply",
                session_id=session_id,
                operator_id=None,
                request_messages=llm_messages,
                response_raw=response_text,
                model=model,
            )

            if not response_text or not response_text.strip():
                logger.warning(
                    "Empty response for session %s (attempt %d/%d), retrying...",
                    session_id, attempt + 1, max_retries,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(3 * (attempt + 1))
                continue

            try:
                return parse_llm_response(response_text)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "Failed to parse LLM response for session %s (attempt %d/%d): %s",
                    session_id, attempt + 1, max_retries, exc,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)

        return None

    def _resolve_provider_config(self, db: Session, operator: Operator) -> Optional[ProviderConfig]:
        if operator.provider_config_id:
            return db.query(ProviderConfig).filter(
                ProviderConfig.id == operator.provider_config_id
            ).first()
        configs = db.query(ProviderConfig).order_by(ProviderConfig.created_at.asc()).all()
        if not configs:
            return None
        if len(configs) > 1:
            raise RuntimeError(
                f"Operator {operator.id} 没有指定 Provider Config，"
                "且数据库中存在多个 Provider Config，请在 Operator 上明确选择一个"
            )
        return configs[0]

    def _log_llm_call(
        self,
        *,
        purpose: str,
        session_id: Optional[str],
        operator_id: Optional[str],
        request_messages: List[Dict[str, str]],
        response_raw: str,
        model: Optional[str],
    ):
        db = SessionLocal()
        try:
            db.add(LlmLog(
                purpose=purpose,
                session_id=session_id,
                operator_id=operator_id,
                request_messages=json.dumps(request_messages, ensure_ascii=False),
                response_raw=response_raw,
                model=model,
                created_at=utc_now(),
            ))
            db.commit()
        except Exception as exc:
            logger.error("Failed to write LLM log: %s", exc)
        finally:
            db.close()
