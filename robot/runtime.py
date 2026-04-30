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
from robot.models import LlmLog, ProviderConfig, RobotMessage, SessionRecord

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

{"messages": [{"delay_seconds": <数字>, "content": "<文本>"}]}

- messages 是你要发送的消息，按顺序排列
- delay_seconds 是距离上一条消息的间隔秒数，反映真实打字速度：短消息 2-5 秒，长消息 5-15 秒
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


def build_system_prompt(session_record: SessionRecord) -> str:
    parts: list[str] = [SYSTEM_INSTRUCTION]

    if session_record.profile:
        parts.append(session_record.profile)

    ctx_lines: list[str] = []
    if session_record.counterpart_profile:
        ctx_lines.append(f"---\n【当前联系人画像】\n{session_record.counterpart_profile}")
    ctx_lines.append(f"---\n【当前时间】{format_beijing_time()}")

    parts.append("\n".join(ctx_lines))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# LLM response parser
# ---------------------------------------------------------------------------

def parse_llm_response(text: str) -> List[Dict[str, Any]]:
    data = json.loads(text.strip())
    raw_messages = data.get("messages", [])
    if not isinstance(raw_messages, list):
        raise ValueError("LLM response 'messages' is not an array")
    messages: List[Dict[str, Any]] = []
    for msg in raw_messages:
        if not isinstance(msg, dict):
            raise ValueError("message item must be an object")
        if "content" not in msg:
            raise ValueError("message item missing 'content'")
        messages.append({
            "delay_seconds": int(msg.get("delay_seconds", 0)),
            "content": str(msg["content"]),
        })
    return messages


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
                role="counterpart",
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
                    role="robot",
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

    async def _think_and_send(self):
        while True:
            self._state = "thinking"
            self._interrupted = False

            messages = await self._call_llm()
            if messages is None:
                self._state = "idle"
                return

            if self._interrupted:
                continue

            self._write_scheduled_messages(messages)
            all_scheduled_ids = self._get_all_scheduled_ids()

            self._state = "sending"
            self._interrupted = False

            await self._send_messages(all_scheduled_ids)

            if self._interrupted:
                self._cancel_all_scheduled()
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
            takeover_user_id = session_record.takeover_user_id
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
                await self.runtime.adapter.send_message(adapter_thread_id, takeover_user_id, content)
            except Exception as exc:
                logger.error("Failed to send reply for session %s: %s", self.session_id, exc)

    async def _call_llm(self) -> Optional[List[Dict[str, Any]]]:
        db = SessionLocal()
        try:
            session_record = db.query(SessionRecord).filter(
                SessionRecord.id == self.session_id
            ).first()
            if not session_record or session_record.status != "active":
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

            system_prompt = build_system_prompt(session_record)

            llm_messages: List[Dict[str, str]] = [
                {"role": "system", "content": system_prompt}
            ]
            for msg in history:
                role = "assistant" if msg.role == "robot" else "user"
                content = msg.content
                if content.startswith("data:"):
                    content = "[附件已省略]"
                llm_messages.append({"role": role, "content": content})

            base_url = provider_config.base_url
            api_key = provider_config.api_key
            model = provider_config.default_model
        finally:
            db.close()

        try:
            response_text, _usage = await self.runtime.provider.complete_chat(
                base_url, api_key, model, llm_messages
            )
        except Exception as exc:
            logger.error("LLM call failed for session %s: %s", self.session_id, exc)
            self._log_llm_call(llm_messages, f"ERROR: {exc}", model)
            return None

        self._log_llm_call(llm_messages, response_text, model)

        try:
            return parse_llm_response(response_text)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.error("Failed to parse LLM response for session %s: %s", self.session_id, exc)
            return None

    def _log_llm_call(
        self,
        request_messages: List[Dict[str, str]],
        response_raw: str,
        model: Optional[str],
    ):
        db = SessionLocal()
        try:
            db.add(LlmLog(
                session_id=self.session_id,
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


# ---------------------------------------------------------------------------
# RobotRuntime — top-level orchestrator (long-polling based)
# ---------------------------------------------------------------------------

class RobotRuntime:
    def __init__(self, options: RuntimeOptions):
        self.options = options
        self.adapter = ChatAdapter(options.chat_api_base_url)
        self.provider = ProviderClient(options.request_timeout)
        self._task: Optional[asyncio.Task[Any]] = None
        self._controllers: Dict[str, SessionController] = {}
        self._poll_tasks: Dict[str, asyncio.Task[Any]] = {}

    async def start(self):
        await self._recover_unprocessed()
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._session_scan_loop(), name="session-scanner")

    async def stop(self):
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        for task in self._poll_tasks.values():
            task.cancel()
        for task in self._poll_tasks.values():
            with suppress(asyncio.CancelledError):
                await task
        for ctrl in self._controllers.values():
            await ctrl.stop()
        self._controllers.clear()
        self._poll_tasks.clear()
        await self.adapter.close()
        await self.provider.close()

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
                if last_msg and last_msg.role == "counterpart":
                    logger.info("Recovery: re-triggering session %s", sr.id)
                    ctrl = self._get_or_create_controller(sr.id)
                    await ctrl.inbox.put({"content": "", "recovery": True})
        finally:
            db.close()

    def _get_or_create_controller(self, session_id: str) -> SessionController:
        if session_id not in self._controllers:
            ctrl = SessionController(session_id, self)
            self._controllers[session_id] = ctrl
            asyncio.get_running_loop().create_task(ctrl.start())
        return self._controllers[session_id]

    async def _session_scan_loop(self):
        """Periodically scan for active sessions and start/stop poll tasks."""
        while True:
            try:
                db = SessionLocal()
                try:
                    active_sessions = db.query(SessionRecord).filter(
                        SessionRecord.status == "active"
                    ).all()
                    active_ids = {s.id for s in active_sessions}
                    session_map = {s.id: s for s in active_sessions}
                finally:
                    db.close()

                # Start poll tasks for new active sessions
                for sid in active_ids:
                    if sid not in self._poll_tasks or self._poll_tasks[sid].done():
                        sr = session_map[sid]
                        self._poll_tasks[sid] = asyncio.get_running_loop().create_task(
                            self._poll_session(sr.id, sr.adapter_thread_id, sr.takeover_user_id),
                            name=f"poll-{sid}",
                        )

                # Stop poll tasks for inactive sessions
                for sid in list(self._poll_tasks.keys()):
                    if sid not in active_ids:
                        self._poll_tasks[sid].cancel()
                        with suppress(asyncio.CancelledError):
                            await self._poll_tasks[sid]
                        del self._poll_tasks[sid]

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Session scan error: %s", exc)

            await asyncio.sleep(5)

    async def _poll_session(self, session_id: str, thread_id: str, takeover_user_id: str):
        """Long-poll a single session for new messages from the counterpart."""
        # Get the last known message id from robot_messages
        last_id = 0
        db = SessionLocal()
        try:
            # First, get current messages to establish baseline
            result = await self.adapter.get_messages(thread_id, last_id=0, timeout=0)
            messages = result.get("messages", [])
            if messages:
                last_id = messages[-1]["id"]
        except Exception as exc:
            logger.error("Failed to get initial messages for session %s: %s", session_id, exc)
        finally:
            db.close()

        while True:
            try:
                result = await self.adapter.get_messages(thread_id, last_id=last_id, timeout=30)
                messages = result.get("messages", [])
                for msg in messages:
                    last_id = msg["id"]
                    # Only process messages from the counterpart (not from takeover_user)
                    if msg.get("sender_id") != takeover_user_id:
                        ctrl = self._get_or_create_controller(session_id)
                        await ctrl.inbox.put({
                            "content": msg.get("content", ""),
                            "sender_id": msg.get("sender_id"),
                        })
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Poll error for session %s: %s", session_id, exc)
                await asyncio.sleep(2)
