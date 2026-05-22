"""LLM reply brain.

The ReplyScanner derives "needs reply" each tick by joining Conversation +
the latest Message: a conversation is pending iff its latest message is
from the counterpart (sender_id IS NOT NULL) and that message's timestamp
is newer than the conversation's last_reply_round_at. A reply round —
whether it queued outbound, emitted silence, errored, or was skipped by a
gate — always bumps last_reply_round_at so the loop terminates.

Per the v2 schema: "self vs counterpart" is derived from
``Message.sender_id IS NULL`` (NULL = self). There is no separate role
column anymore.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func
from sqlalchemy.orm import Session as ORMSession

from studio.clients import ProviderClient
from studio.db import SessionLocal, utc_now
from studio.enums import (
    ConversationStatus,
    LlmPurpose,
    OutboundMessageType,
    OutboundStatus,
    ReplyPolicy,
)
from studio.models import (
    Conversation,
    Inbox,
    LlmLog,
    Message,
    OutboundMessage,
    Persona,
    ProviderConfig,
)

logger = logging.getLogger(__name__)


QUIET_SECONDS = 6
HISTORY_TAIL = 60

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
    conversation_id: str
    conversation_display_name: str
    persona_name: str
    persona_md: str
    card_md: str
    base_url: str
    api_key: str
    model: str
    inbox_id: str
    display_tz: str


@dataclass(frozen=True)
class _ReplyDecision:
    skip_reason: Optional[str]
    ctx: Optional[_ReplyCtx]
    history: List[Message]


def _decide(db: ORMSession, conversation_id: str) -> _ReplyDecision:
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        return _ReplyDecision("conversation 不存在", None, [])
    if conv.status != ConversationStatus.ACTIVE:
        return _ReplyDecision("conversation archived", None, [])
    if conv.reply_policy != ReplyPolicy.AUTOREPLY:
        return _ReplyDecision("reply_policy is not autoreply", None, [])

    inbox = db.query(Inbox).filter(Inbox.id == conv.inbox_id).first()
    if not inbox:
        return _ReplyDecision("inbox 不存在", None, [])
    pc = db.query(ProviderConfig).filter(ProviderConfig.id == conv.provider_id).first()
    if not pc or not pc.api_key:
        return _ReplyDecision("provider 缺失或没 api_key", None, [])

    if not conv.persona_id:
        return _ReplyDecision("conversation 未配置 persona", None, [])
    persona = db.query(Persona).filter(Persona.id == conv.persona_id).first()
    if not persona:
        return _ReplyDecision("persona 不存在", None, [])

    history = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.timestamp.desc(), Message.id.desc())
        .limit(HISTORY_TAIL)
        .all()
    )
    history.reverse()
    if not history:
        return _ReplyDecision("没有可用历史", None, [])

    latest = max(history, key=lambda m: m.timestamp)
    if latest.sender_id is None:
        # NULL sender_id = self. We don't reply to ourselves.
        return _ReplyDecision("最近一条是自己发的", None, history)

    seconds_since = (utc_now() - latest.timestamp).total_seconds()
    if seconds_since < QUIET_SECONDS:
        return _ReplyDecision(
            f"等静默期（{seconds_since:.0f}/{QUIET_SECONDS}s）", None, history
        )

    ctx = _ReplyCtx(
        conversation_id=conv.id,
        conversation_display_name=conv.display_name,
        persona_name=persona.name,
        persona_md=persona.persona_md or "",
        card_md=conv.card_md or "",
        base_url=pc.base_url,
        api_key=pc.api_key,
        model=pc.model,
        inbox_id=inbox.id,
        display_tz=persona.timezone or "UTC",
    )
    return _ReplyDecision(None, ctx, history)


def _format_history_lines(history: List[Message], display_tz: str) -> str:
    try:
        tz = ZoneInfo(display_tz)
    except (ZoneInfoNotFoundError, KeyError):
        tz = ZoneInfo("UTC")
    _MEDIA_LABELS = {
        "image": "[图片]",
        "audio": "[音频]",
        "video": "[视频]",
        "file": "[文件]",
    }
    lines: List[str] = []
    for m in history:
        speaker = "我" if m.sender_id is None else "对方"
        ts = m.timestamp.astimezone(tz).strftime("%m-%d %H:%M")
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
        parts.append(f"## 关于对方（{ctx.conversation_display_name}）\n{ctx.card_md.strip()}")
    parts.append(f"## 最近的对话\n{_format_history_lines(history, ctx.display_tz)}")
    parts.append("现在轮到你回复了，按要求输出 JSON。")
    return "\n\n".join(parts)


def _parse_chunks(raw: str) -> List[str]:
    text = raw.strip()
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


def _mark_round_done(db: ORMSession, conversation_id: str) -> None:
    c = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if c:
        c.last_reply_round_at = utc_now()
        c.updated_at = c.last_reply_round_at


async def maybe_reply(provider: ProviderClient, conversation_id: str) -> str:
    """Run one reply attempt for one conversation."""
    db = SessionLocal()
    try:
        decision = _decide(db, conversation_id)
    finally:
        db.close()

    if decision.skip_reason:
        if decision.skip_reason.startswith("等静默期"):
            return decision.skip_reason
        db = SessionLocal()
        try:
            _mark_round_done(db, conversation_id)
            db.commit()
        finally:
            db.close()
        return f"skip: {decision.skip_reason}"

    ctx = decision.ctx
    assert ctx is not None

    if decision.history and decision.history[-1].msg_type != "text":
        # Media reply path removed in v2 — bridge can't dispatch media yet.
        db = SessionLocal()
        try:
            _mark_round_done(db, conversation_id)
            db.commit()
        finally:
            db.close()
        return "skip: latest message is not text (media unsupported)"

    request_messages = [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": _build_user_message(ctx, decision.history)},
    ]

    try:
        response_text, _usage = await provider.complete_chat(
            ctx.base_url, ctx.api_key, ctx.model, request_messages
        )
    except Exception as exc:
        logger.error("Reply LLM call failed for conversation %s: %s", conversation_id, exc)
        db = SessionLocal()
        try:
            db.add(
                LlmLog(
                    purpose=LlmPurpose.REPLY,
                    persona_id=None,
                    inbox_id=ctx.inbox_id,
                    request_messages=json.dumps(request_messages, ensure_ascii=False),
                    response_raw=f"ERROR: {exc}",
                    model=ctx.model,
                    created_at=utc_now(),
                )
            )
            _mark_round_done(db, conversation_id)
            db.commit()
        finally:
            db.close()
        return f"llm_error: {exc}"

    db = SessionLocal()
    try:
        db.add(
            LlmLog(
                purpose=LlmPurpose.REPLY,
                persona_id=None,
                inbox_id=ctx.inbox_id,
                request_messages=json.dumps(request_messages, ensure_ascii=False),
                response_raw=response_text,
                model=ctx.model,
                created_at=utc_now(),
            )
        )
        try:
            chunks = _parse_chunks(response_text)
        except Exception as exc:
            logger.warning(
                "Reply parse failed for conversation %s: %s; raw=%s",
                conversation_id, exc,
                response_text[:300].replace("\n", "\\n").replace("\r", "\\r"),
            )
            _mark_round_done(db, conversation_id)
            db.commit()
            return f"parse_error: {exc}"

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
                    conversation_id=ctx.conversation_id,
                    msg_type=OutboundMessageType.TEXT,
                    content=ch,
                    send_after=send_after,
                    status=OutboundStatus.PENDING,
                    delivered_at=None,
                    failed_reason="",
                    created_at=now_ts,
                )
                db.add(ob)
            status = f"queued {len(chunks)} message(s)"
        else:
            status = "model returned empty (intentional silence)"

        _mark_round_done(db, conversation_id)
        db.commit()
        return status
    finally:
        db.close()


def list_pending_conversation_ids() -> List[str]:
    """Conversations that need a reply: status=active, reply_policy=autoreply,
    persona configured, and latest message is from counterpart (sender_id IS
    NOT NULL) with timestamp > last_reply_round_at (or NULL).
    """
    db = SessionLocal()
    try:
        latest_ts = (
            db.query(
                Message.conversation_id.label("cid"),
                func.max(Message.timestamp).label("ts"),
            )
            .group_by(Message.conversation_id)
            .subquery()
        )
        rows = (
            db.query(Conversation.id, latest_ts.c.ts, Message.sender_id)
            .join(latest_ts, latest_ts.c.cid == Conversation.id)
            .join(
                Message,
                (Message.conversation_id == Conversation.id)
                & (Message.timestamp == latest_ts.c.ts),
            )
            .filter(
                Conversation.status == ConversationStatus.ACTIVE,
                Conversation.reply_policy == ReplyPolicy.AUTOREPLY,
                Conversation.persona_id.is_not(None),
            )
            .all()
        )
        out: List[str] = []
        seen: set[str] = set()
        for cid, ts, sender_id in rows:
            if cid in seen:
                continue
            seen.add(cid)
            if sender_id is None:
                # Latest is self — not waiting on us.
                continue
            c = (
                db.query(Conversation.last_reply_round_at)
                .filter(Conversation.id == cid)
                .first()
            )
            last = c[0] if c else None
            if last is None or last < ts:
                out.append(cid)
        return out
    finally:
        db.close()
