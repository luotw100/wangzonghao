"""LLM reply brain.

Triggered by the ReplyScanner in the worker: for each Contact with
pending_reply=True, builds prompt → calls LLM → writes outbound messages →
clears pending_reply.

Design:
- All gating is recomputed at reply time inside one DB session, so a stale
  pending_reply flag (e.g. left over after autoreply was disabled) is a no-op
  rather than a leak.
- A short quiet-period suppresses replies while the counterpart is still
  typing: if the latest counterpart message arrived less than QUIET_SECONDS
  ago, defer this round (the flag stays true; we'll be back).
- Each LLM response chunk becomes a separate OutboundMessage with a
  send_after timestamp. Studio controls pacing: Bridge simply forwards
  messages as soon as they become eligible.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session as ORMSession

from studio.clients import ProviderClient
from studio.db import SessionLocal, utc_now
from studio.enums import (
    ContactStatus,
    LlmPurpose,
    MessageRole,
    OutboundMessageType,
    OutboundStatus,
)
from studio.models import (
    Contact,
    Inbox,
    LlmLog,
    Message,
    OutboundMessage,
    Persona,
)
from studio.provider_policy import resolve_provider_config

logger = logging.getLogger(__name__)


# How long to wait after the latest counterpart message before replying.
# Lets the counterpart finish typing without firing N parallel LLM calls.
QUIET_SECONDS = 6
# How many recent messages to include in the prompt history dump.
HISTORY_TAIL = 60

# Pacing: Studio schedules each chunk's send_after so Bridge just forwards
# immediately when it becomes eligible. First chunk gets a "think" delay;
# subsequent chunks are spaced by simulated typing speed.
TYPING_CHARS_PER_SECOND = 6.0
TYPING_MIN_DELAY = 1.0
TYPING_MAX_DELAY = 12.0
THINK_DELAY = 1.5


SYSTEM_INSTRUCTION = """\
你是一个真实的人，正在私聊里和别人聊天。你不是 AI、不是助手、不是客服。你有自己的性格、情绪、生活。

## 绝对禁令
- 身份保密：绝对不能承认自己是 AI、机器人、程序。如被质疑，像真人一样反应——困惑、无语、生气都行，但不能承认。
- 金钱隔离：不引导转账、打赏、付费、借钱；不讨论具体金额；对方主动提起时自然转移话题。
- 线下隔离：不主动约线下见面；对方提议时自然推脱。
- 人设一致：始终在你的人设认知范围内说话。遇到不属于你知识范围的话题，按人设自然带过。
- 合规底线：不发露骨色情、暴力、违法内容。可以保持暧昧、调情，让对方有想象空间但不越界。

## 你在聊天里
- 打字有快有慢，不会瞬间回复大段文字。
- 把一句话拆几条发。
- 偶尔语气词、表情、省略号；标点随意。
- 你有情绪——会开心、无聊、不耐烦、犯困。
- 不给"完美回答"，真人聊天经常答非所问、跑题、忘事。

## 节奏
- 对方一次发一堆，你可以只接最感兴趣那一点。
- 真人会选择性忽略，不必每条都回。
- 可以反问、岔开、主动分享自己的事。
- 不要每轮都试图推进议程。

## 输出
你的回复必须是合法 JSON 对象，不要输出任何其他内容：

{"messages": ["第一条", "第二条"]}

- messages 是要发送的消息列表，按顺序排列。
- 每条是纯文本——就是聊天框里显示的内容。
- 条数自定，看你觉得自然。
- 如果当下不该回（比如对方最后一句你已经回过、或这段对话目前不需要你说话），返回 {"messages": []}。
"""


@dataclass(frozen=True)
class _ReplyCtx:
    contact_id: str
    contact_display_name: str
    persona_name: str
    persona_md: str
    card_md: str
    base_url: str
    api_key: str
    model: str
    inbox_id: str


@dataclass(frozen=True)
class _ReplyDecision:
    skip_reason: Optional[str]   # None => proceed
    ctx: Optional[_ReplyCtx]
    history: List[Message]


def _decide(db: ORMSession, contact_id: str) -> _ReplyDecision:
    """Re-validate every gate in one transaction; return a decision."""
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        return _ReplyDecision("contact 不存在", None, [])
    if contact.status != ContactStatus.ACTIVE:
        return _ReplyDecision("contact archived", None, [])
    if not contact.autoreply_enabled:
        return _ReplyDecision("autoreply disabled on contact", None, [])

    inbox = db.query(Inbox).filter(Inbox.id == contact.inbox_id).first()
    if not inbox or not inbox.enabled:
        return _ReplyDecision("inbox disabled", None, [])
    provider_id = contact.reply_provider_config_id or inbox.reply_provider_config_id
    pc = resolve_provider_config(db, provider_id)
    if not pc or not pc.api_key:
        return _ReplyDecision("provider 缺失或没 api_key（含全局默认 Provider）", None, [])

    persona = db.query(Persona).filter(Persona.id == contact.persona_id).first()
    if not persona:
        return _ReplyDecision("persona 不存在", None, [])

    history = (
        db.query(Message)
        .filter(Message.contact_id == contact.id)
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(HISTORY_TAIL)
        .all()
    )
    history.reverse()
    if not history:
        return _ReplyDecision("没有可用历史", None, [])

    latest = max(history, key=lambda m: m.timestamp)
    if latest.role != MessageRole.COUNTERPART:
        return _ReplyDecision("最近一条不是对方", None, history)

    seconds_since = (utc_now() - latest.timestamp).total_seconds()
    if seconds_since < QUIET_SECONDS:
        return _ReplyDecision(f"等静默期（{seconds_since:.0f}/{QUIET_SECONDS}s）", None, history)

    ctx = _ReplyCtx(
        contact_id=contact.id,
        contact_display_name=contact.display_name,
        persona_name=persona.name,
        persona_md=persona.persona_md or "",
        card_md=contact.card_md or "",
        base_url=pc.base_url,
        api_key=pc.api_key,
        model=pc.default_model,
        inbox_id=inbox.id,
    )
    return _ReplyDecision(None, ctx, history)


def _format_history_lines(history: List[Message]) -> str:
    _MEDIA_LABELS = {
        "image": "[图片]",
        "audio": "[音频]",
        "video": "[视频]",
        "file": "[文件]",
    }
    lines: List[str] = []
    for m in history:
        speaker = "我" if m.role == MessageRole.SELF else "对方"
        ts = m.timestamp.strftime("%m-%d %H:%M")
        msg_type = getattr(m, "msg_type", "text") or "text"
        if msg_type == "text":
            content = m.content.replace("\n", " ").strip()
        else:
            label = _MEDIA_LABELS.get(msg_type, f"[{msg_type}]")
            content = label
        lines.append(f"[{ts}] {speaker}: {content}")
    return "\n".join(lines)


def _build_user_message(ctx: _ReplyCtx, history: List[Message]) -> str:
    parts: List[str] = []
    if ctx.persona_md.strip():
        parts.append(f"## 你的人设\n{ctx.persona_md.strip()}")
    if ctx.card_md.strip():
        parts.append(f"## 关于对方（{ctx.contact_display_name}）\n{ctx.card_md.strip()}")
    parts.append(f"## 最近的对话\n{_format_history_lines(history)}")
    parts.append("现在轮到你回复了，按要求输出 JSON。")
    return "\n\n".join(parts)


def _parse_chunks(raw: str) -> List[str]:
    text = raw.strip()
    # Strip code fences like ```json ... ```
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[: -3]
    text = text.strip()
    data = json.loads(text)
    msgs = data.get("messages", [])
    if not isinstance(msgs, list):
        raise ValueError("messages 不是数组")
    out: List[str] = []
    for item in msgs:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if s:
            out.append(s)
    return out


async def maybe_reply(provider: ProviderClient, contact_id: str) -> str:
    """Run one reply attempt for one contact. Returns a short status string for logging."""
    # Phase 1: decide (read-only)
    db = SessionLocal()
    try:
        decision = _decide(db, contact_id)
    finally:
        db.close()

    if decision.skip_reason:
        if decision.skip_reason.startswith("等静默期"):
            return decision.skip_reason
        # Permanent skip — clear the flag so we stop polling forever
        db = SessionLocal()
        try:
            c = db.query(Contact).filter(Contact.id == contact_id).first()
            if c and c.pending_reply:
                c.pending_reply = False
                c.updated_at = utc_now()
                db.commit()
        finally:
            db.close()
        return f"skip: {decision.skip_reason}"

    ctx = decision.ctx
    assert ctx is not None
    request_messages = [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": _build_user_message(ctx, decision.history)},
    ]

    # Phase 2: LLM call (no db open while we wait)
    try:
        response_text, _usage = await provider.complete_chat(
            ctx.base_url, ctx.api_key, ctx.model, request_messages
        )
    except Exception as exc:
        logger.error("Reply LLM call failed for contact %s: %s", contact_id, exc)
        db = SessionLocal()
        try:
            db.add(LlmLog(
                purpose=LlmPurpose.REPLY, persona_id=None, inbox_id=ctx.inbox_id,
                request_messages=json.dumps(request_messages, ensure_ascii=False),
                response_raw=f"ERROR: {exc}", model=ctx.model, created_at=utc_now(),
            ))
            db.commit()
        finally:
            db.close()
        return f"llm_error: {exc}"

    # Phase 3: parse + commit
    db = SessionLocal()
    try:
        db.add(LlmLog(
            purpose=LlmPurpose.REPLY, persona_id=None, inbox_id=ctx.inbox_id,
            request_messages=json.dumps(request_messages, ensure_ascii=False),
            response_raw=response_text, model=ctx.model, created_at=utc_now(),
        ))
        try:
            chunks = _parse_chunks(response_text)
        except Exception as exc:
            logger.warning("Reply parse failed for contact %s: %s; raw=%s",
                           contact_id, exc, response_text[:300])
            c = db.query(Contact).filter(Contact.id == contact_id).first()
            if c:
                c.pending_reply = False
                c.updated_at = utc_now()
            db.commit()
            return f"parse_error: {exc}"

        c = db.query(Contact).filter(Contact.id == contact_id).first()
        if not c:
            db.commit()
            return "contact gone"

        if chunks:
            now_ts = utc_now()
            send_after = now_ts + timedelta(seconds=THINK_DELAY)
            for i, ch in enumerate(chunks):
                if i > 0:
                    prev_len = max(1, len(chunks[i - 1]))
                    delay = prev_len / TYPING_CHARS_PER_SECOND
                    delay = max(TYPING_MIN_DELAY, min(TYPING_MAX_DELAY, delay))
                    send_after = send_after + timedelta(seconds=delay)
                ob = OutboundMessage(
                    inbox_id=ctx.inbox_id,
                    contact_id=ctx.contact_id,
                    msg_type=OutboundMessageType.TEXT,
                    content=ch,
                    send_after=send_after,
                    status=OutboundStatus.PENDING,
                    delivered_at=None,
                    failed_reason=None,
                    created_at=now_ts,
                )
                db.add(ob)
            status = f"queued {len(chunks)} message(s)"
        else:
            status = "model returned empty (intentional silence)"

        c.pending_reply = False
        c.updated_at = utc_now()
        db.commit()
        return status
    finally:
        db.close()


def list_pending_contact_ids() -> List[str]:
    db = SessionLocal()
    try:
        rows = (
            db.query(Contact.id)
            .filter(Contact.pending_reply.is_(True), Contact.status == ContactStatus.ACTIVE)
            .all()
        )
        return [r[0] for r in rows]
    finally:
        db.close()
