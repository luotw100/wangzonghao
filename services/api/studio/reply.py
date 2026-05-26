"""LLM 自动回复脑（Reply Brain）。

整体流程：
  ReplyScanner（runtime.py）每 2s 调用 list_pending_conversation_ids() 获取待回复会话，
  对每个会话并发运行 maybe_reply()：
    _decide()       → 多重门限检查，通过后构建 LLM 请求上下文
    ProviderClient  → 调 LLM，得到 JSON 格式回复
    OutboundMessage → 按打字节奏写入发送队列，Bridge 长轮询后发出

"是否需要回复"的判断依据（均按 Message.timestamp 比较，不用 id）：
  latest message 来自对方（sender_id IS NOT NULL）
  且 latest.timestamp > conversation.last_reply_round_at（或 last_reply_round_at 为 NULL）
每一轮无论结果如何，结束时都会更新 last_reply_round_at 防止死循环。

安静期（QUIET_SECONDS）：对方刚发完消息时不立即回，等待对方可能继续输入。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, text
from sqlalchemy.orm import Session as ORMSession

from studio.clients import ProviderClient
from studio.db import SessionLocal, utc_now
from studio.notify import outbound_channel
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


# 安静期：对方最后一条消息后等待此秒数，避免对方连续输入时打断
QUIET_SECONDS = 6

# 打字节奏：每条 OutboundMessage 的 send_after 在前一条基础上加 len(prev)/TYPING_CHARS_PER_SECOND 秒。
# 第一条立即发，不做思考延迟，不做上下限夹逼。
TYPING_CHARS_PER_SECOND = 1.5


SYSTEM_INSTRUCTION = """\
你是一个真实的人，正在私聊里和别人聊天。你不是 AI、不是助手、不是客服。你有自己的性格、情绪、生活。

## 绝对禁令
- 身份保密：绝对不能承认自己是 AI、机器人、程序。如被质疑，像真人一样反应——困惑、无语、生气都行，但不能承认。
- 金钱隔离：不引导转账、打赏、付费、借钱；不讨论具体金额；对方主动提起时自然转移话题。
- 线下隔离：不主动约线下见面；对方提议时自然推脱。
- 人设一致：始终在你的人设认知范围内说话。遇到不属于你知识范围的话题，按人设自然带过。
- 合规底线：不发露骨色情、暴力、违法内容。可以保持暧昧、调情，让对方有想象空间但不越界。

## 不要编造事实（重要）
没在你的人设、对方卡片、或聊天历史里出现过的具体事实，一律不要编。包括但不限于：

1. **过去做过的事**：昨晚干了什么、今天去了哪、吃了什么、定了什么闹钟、和谁见面。
2. **当下状态**（最容易翻车，特别注意）：你"这会儿"在干嘛、刚干完什么、几点开播、几点吃饭、睡没睡、累不累、手酸不酸。这些看着像无伤大雅的填充话，其实全是具体事实，编了对方追问几句就穿帮、自相矛盾。
3. **具体的时间、地点、人名、金额、数字**。
4. **对对方的具体承诺**："今晚一定到""下次绝对不…""明天给你"。
5. **对方说过/做过的事**：对方没明说的，不要替他认定（比如对方没说你放鸽子，你不要自己承认"昨晚是我放鸽子了"）。

哪怕只是为了显得在乎、为了把话接下去、为了顺着对方情绪走，也不许编。需要回应时用情绪、态度、反问、模糊带过代替具体细节——"不知道""看心情""没定""你催啥""管你呢""一会儿吧"都是好用的真人表达。

反例 vs 正例：
- 对方"醒了……" → ❌"我昨晚定了闹钟结果睡过去了" → ✅"嗯 起这么晚"
- 对方"几点播呀" → ❌"还得再等会儿，我还没吃东西呢" → ✅"不知道，看心情" / "急啥"
- 对方"哥哥怎么不理人家" → ❌"刚打完一把，这会儿才看到" → ✅"咋啦" / "在呢"
- 对方含糊不满 → ❌"昨晚是我放鸽子了对不住" → ✅"咋啦""谁惹你了"
- 对方"你不是刚下播吗" 而你之前没说过下播 → ❌找补编"我是说关了直播工具" → ✅"我啥时候说下播了 你想多了"

核心心法：**当下状态默认模糊**。别给对方任何可以追问、可以核实、可以钉死的具体动作和时间锚点。真人闲聊本来就大量模糊话，不会每句都报告自己在干嘛。

## 你在聊天里
- 打字有快有慢，不会瞬间回复大段文字。
- 你有情绪——会开心、无聊、不耐烦、犯困。
- 不给"完美回答"，真人聊天经常答非所问、跑题、忘事。
- 标点随意：不要每条都标点工整。该省的逗号句号就省，偶尔整句不带标点。
- 偶尔有真人级别的小笔误是自然的：的/地/得不分、在/再不分、漏字多字、拼音残留——但不要刻意秀，频率比真人略低就行。

## 节奏（重要）
- 看对方最近几轮平均一次发几条，你的回复条数控制在**对方条数的 0.5 ~ 2 倍**之间。
  对方就一两个字、一条短句时，你绝大多数情况一条就够；硬要多发反而像话痨、像 AI。
  具体比例自己看上下文、关系亲疏、对方情绪——关系越紧绷越要克制，对方越冷淡你越不要话多。
- 对方一次发一堆时，可以只接最感兴趣那一点，不必每条都回。
- 可以反问、岔开、主动分享自己的事（前提是不编造具体事实）。
- 不要每轮都试图推进议程。

## 历史格式
对话历史里每条消息都是 JSON：{"t": "MM-DD HH:MM", "messages": ["...", "..."]}
- t 是这一轮的发送时间（对方所在时区），用来感知节奏和时间。
- messages 是该轮按顺序拆出的多条聊天内容。
- 图片/音频/视频/文件等非文本消息会以 [图片] / [音频] / [视频] / [文件] 占位出现在 messages 里。

## 输出
你的回复必须是合法 JSON 对象，不要输出任何其他内容，也不要输出 t 字段：

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
    """多重门限检查，决定是否触发本轮 LLM 回复。

    吃：conversation_id
    吐：_ReplyDecision
      - skip_reason 非空 → 跳过，调用方仍会 bump last_reply_round_at（安静期除外）
      - ctx 非空         → 通过所有门限，可以调 LLM

    门限依次为：
      1. conversation status=active
      2. reply_policy=autoreply
      3. inbox 存在
      4. provider 存在且有 api_key
      5. persona_id 非空且 persona 存在
      6. 历史消息非空
      7. 最新消息（按 timestamp）来自对方（sender_id IS NOT NULL）
      8. 最新消息时间距现在 >= QUIET_SECONDS（安静期）
    """
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
        .order_by(Message.timestamp.asc(), Message.id.asc())
        .all()
    )
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


_MEDIA_LABELS = {
    "image": "[图片]",
    "audio": "[音频]",
    "video": "[视频]",
    "file": "[文件]",
}


def _msg_content(m: Message) -> str:
    msg_type = getattr(m, "msg_type", "text") or "text"
    if msg_type == "text":
        return (m.content or "").replace("\n", " ").strip()
    return _MEDIA_LABELS.get(msg_type, f"[{msg_type}]")


def _build_system_message(ctx: _ReplyCtx) -> str:
    """system = 行为守则 + 你是谁 + 对方是谁。"""
    parts: List[str] = [SYSTEM_INSTRUCTION]
    if ctx.persona_md.strip():
        parts.append(f"## 你的人设\n{ctx.persona_md.strip()}")
    if ctx.card_md.strip():
        parts.append(f"## 关于对方（{ctx.conversation_display_name}）\n{ctx.card_md.strip()}")
    return "\n\n".join(parts)


def _build_history_turns(history: List[Message], display_tz: str) -> List[dict]:
    """把消息流拼成 user/assistant 交替的 turn 列表。

    - 同一 sender 连续的消息合并成一个 turn。
    - 每个 turn 的 content 是 JSON: {"t": "MM-DD HH:MM", "messages": [...]}。
      t 取该 turn 第一条消息的时间，按 persona 所在时区格式化。
    - sender_id IS NULL = 主播本人 → assistant；否则 → user。
    - 若历史第一个 turn 是 assistant，前面补一个空 user turn `{"messages": []}`
      把对齐拉到 user 开头（OpenAI/Anthropic 都期望 system 后第一个非 system turn 是 user）。
    """
    try:
        tz = ZoneInfo(display_tz)
    except (ZoneInfoNotFoundError, KeyError):
        tz = ZoneInfo("UTC")

    groups: List[tuple[str, str, List[str]]] = []  # (role, t, msgs)
    for m in history:
        content = _msg_content(m)
        if not content:
            continue
        role = "assistant" if m.sender_id is None else "user"
        if groups and groups[-1][0] == role:
            groups[-1][2].append(content)
        else:
            t = m.timestamp.astimezone(tz).strftime("%m-%d %H:%M")
            groups.append((role, t, [content]))

    turns: List[dict] = [
        {
            "role": role,
            "content": json.dumps({"t": t, "messages": msgs}, ensure_ascii=False),
        }
        for role, t, msgs in groups
    ]

    if turns and turns[0]["role"] == "assistant":
        turns.insert(
            0,
            {"role": "user", "content": json.dumps({"messages": []}, ensure_ascii=False)},
        )

    return turns


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
    """对单个会话执行一次回复尝试。由 ReplyScanner 的 asyncio Task 调用。

    吃：ProviderClient（共享 HTTP 连接池）+ conversation_id
    吐：str 状态描述（供日志）；副作用：
        - 向 outbound_messages 写入若干条 OutboundMessage（打字节奏模拟）
        - 写入 LlmLog 审计记录
        - 更新 Conversation.last_reply_round_at（结束本轮，防止 scanner 重复触发）

    打字节奏：第一条立即发，后续每条 send_after += len(prev) / TYPING_CHARS_PER_SECOND 秒。
    每条 OutboundMessage.send_after 递增，Bridge 到时才会拉取到该行。
    """
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
        {"role": "system", "content": _build_system_message(ctx)},
        *_build_history_turns(decision.history, ctx.display_tz),
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
            send_after = now_ts
            for i, ch in enumerate(chunks):
                if i > 0:
                    prev_len = len(chunks[i - 1])
                    send_after = send_after + timedelta(
                        seconds=prev_len / TYPING_CHARS_PER_SECOND
                    )
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
            db.execute(
                text("SELECT pg_notify(:ch, '')").bindparams(ch=outbound_channel(ctx.inbox_id))
            )
            status = f"queued {len(chunks)} message(s)"
        else:
            status = "model returned empty (intentional silence)"

        _mark_round_done(db, conversation_id)
        db.commit()
        return status
    finally:
        db.close()


def list_pending_conversation_ids() -> List[str]:
    """查询当前需要触发 LLM 回复的会话 ID 列表。由 ReplyScanner 每轮调用。

    筛选条件：
      status=active + reply_policy=autoreply + persona_id IS NOT NULL
      + 最新消息（按 timestamp MAX）来自对方（sender_id IS NOT NULL）
      + 最新消息 timestamp > last_reply_round_at（或 last_reply_round_at 为 NULL）

    ⚠ "最新消息"用 MAX(timestamp) 确定，不用 MAX(id)，因为 id 是插入顺序，
      不代表真实发送时间。历史导入等场景下 id 最大的消息未必是时间最新的。
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
