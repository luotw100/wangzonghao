"""蒸馏 Pipeline：逐会话滚动 fold，将对话历史提炼为 card_md / persona_md。

流程：
  run_distill(conversation_ids, target_persona_id, provider_config_id)
    └─ 对每个 conversation 调用 _fold_conversation()
         └─ 消息按 timestamp asc 排序（⚠ 不用 id，id 是插入顺序不代表时间）
         └─ 拆分为 session → 打包为 window（token 上限 40k）
         └─ 对每个 window 调用 LLM（fold prompt）→ 解析输出
         └─ 写回 Conversation.card_md（对方画像）
         └─ 若 target_persona_id 非空，同步写回 Persona.persona_md（人设）

一条代码路径，唯一条件分支是"是否指定了目标人设"。
每次 fold 后立即写回 DB，下一个 window 基于最新的 card_md / persona_md 继续。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session as ORMSession

from studio.clients import ProviderClient
from studio.db import SessionLocal, utc_now
from studio.distill.packer import (
    TextMessage,
    Window,
    pack_windows,
    split_sessions,
)
from studio.enums import LlmPurpose
from studio.models import (
    Conversation,
    Inbox,
    LlmLog,
    Message,
    Persona,
    ProviderConfig,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
FOLD_PROMPT = (PROMPTS_DIR / "fold.md").read_text(encoding="utf-8")

_PERSONA_RE = re.compile(
    r"={3,}\s*Character Persona\s*={3,}\s*(.*?)(?=\n={3,}\s*Contact Card\s*={3,})",
    re.DOTALL,
)
_CARD_RE = re.compile(
    r"={3,}\s*Contact Card\s*={3,}\s*(.*)",
    re.DOTALL,
)


ProgressCb = Callable[[Dict[str, int]], None]


@dataclass
class _DistillCtx:
    persona_id: Optional[str]
    persona_name: str
    base_url: str
    api_key: str
    model: str
    display_tz: str


def _load_ctx(
    db: ORMSession,
    *,
    target_persona_id: Optional[str],
    provider_config_id: str,
) -> _DistillCtx:
    persona_id: Optional[str] = None
    persona_name = ""
    display_tz = "UTC"
    if target_persona_id is not None:
        persona = db.query(Persona).filter(Persona.id == target_persona_id).first()
        if not persona:
            raise ValueError(f"Persona {target_persona_id} 不存在")
        persona_id = persona.id
        persona_name = persona.name
        display_tz = persona.timezone or "UTC"

    pc = db.query(ProviderConfig).filter(
        ProviderConfig.id == provider_config_id,
    ).first()
    if not pc:
        raise ValueError(f"Provider Config {provider_config_id} 不存在")
    if not pc.api_key:
        raise ValueError(f"Provider Config {pc.id} 缺少 api_key")

    return _DistillCtx(
        persona_id=persona_id,
        persona_name=persona_name,
        base_url=pc.base_url,
        api_key=pc.api_key,
        model=pc.model,
        display_tz=display_tz,
    )


def _load_conversation_messages(db: ORMSession, conversation_id: str) -> List[Message]:
    # 按真实发送时间升序排列（timestamp asc），id 仅作同 timestamp 时的稳定次序，
    # 不参与时间语义判断。
    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.timestamp.asc(), Message.id.asc())
        .all()
    )


def _messages_to_text_messages(msgs: List[Message], display_tz: str) -> List[TextMessage]:
    try:
        tz = ZoneInfo(display_tz)
    except (ZoneInfoNotFoundError, KeyError):
        tz = ZoneInfo("UTC")
    out: List[TextMessage] = []
    for m in msgs:
        sender = "我" if m.sender_id is None else "对方"
        ts_local = m.timestamp.astimezone(tz)
        line = f"[{ts_local.strftime('%Y-%m-%d %H:%M:%S')}] {sender}: {m.content}"
        out.append(
            TextMessage(
                timestamp=ts_local,
                sender=sender,
                content=m.content,
                raw_line=line,
            )
        )
    return out


def _build_user_message(
    *,
    ctx: _DistillCtx,
    conversation: Conversation,
    inbox_platform_self_id: Optional[str],
    window: Window,
    total_windows: int,
    sessions_so_far: int,
    persona_md: str,
    card_md: str,
) -> str:
    return (
        f"```yaml\n"
        f"character_name: {json.dumps(ctx.persona_name, ensure_ascii=False)}\n"
        f"character_wxid: {json.dumps(inbox_platform_self_id or '', ensure_ascii=False)}\n"
        f"contact_name: {json.dumps(conversation.display_name, ensure_ascii=False)}\n"
        f"contact_wxid: {json.dumps(conversation.platform_conversation_id or '', ensure_ascii=False)}\n"
        f"window: {window.window_id}/{total_windows}\n"
        f"time_range: \"{window.time_range}\"\n"
        f"sessions_in_window: {window.session_count}\n"
        f"total_sessions: {sessions_so_far}\n"
        f"```\n\n"
        f"===== Character Persona =====\n{persona_md or '空'}\n\n"
        f"===== Contact Card =====\n{card_md or '空'}\n\n"
        f"以下是聊天记录：\n\n{window.text}"
    )


def _parse_fold_output(text: str) -> Tuple[Optional[str], Optional[str]]:
    persona_match = _PERSONA_RE.search(text)
    card_match = _CARD_RE.search(text)
    persona = persona_match.group(1).strip() if persona_match else None
    card = card_match.group(1).strip() if card_match else None
    return persona, card


def _log_llm_call(
    db: ORMSession,
    *,
    persona_id: Optional[str],
    inbox_id: str,
    request_messages: List[Dict[str, str]],
    response_raw: str,
    model: str,
) -> None:
    db.add(
        LlmLog(
            purpose=LlmPurpose.DISTILL,
            persona_id=persona_id,
            inbox_id=inbox_id,
            request_messages=json.dumps(request_messages, ensure_ascii=False),
            response_raw=response_raw,
            model=model,
            created_at=utc_now(),
        )
    )
    db.commit()


async def _fold_conversation(
    *,
    client: ProviderClient,
    ctx: _DistillCtx,
    conversation_id: str,
    progress_state: Dict[str, int],
    progress_cb: Optional[ProgressCb],
) -> None:
    """对单个会话执行滚动 fold（多 window 串行处理）。

    吃：该会话的全部消息（按 timestamp asc）→ 拆 session → 打包成 windows
    吐（副作用）：
      - 每处理完一个 window，立即写回 Conversation.card_md
      - 若 ctx.persona_id 非空，同步更新 Persona.persona_md
      - 每个 window 写一条 LlmLog 审计记录
      - 调用 progress_cb 更新进度（供 DistillJob.progress 前端轮询）
    """
    db = SessionLocal()
    try:
        conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if not conv:
            return
        inbox = db.query(Inbox).filter(Inbox.id == conv.inbox_id).first()
        inbox_id = conv.inbox_id
        inbox_platform_self_id = inbox.platform_self_id if inbox else None
        messages = _load_conversation_messages(db, conversation_id)
    finally:
        db.close()

    if not messages:
        logger.info("Conversation %s 没有消息，跳过", conversation_id)
        return

    text_msgs = _messages_to_text_messages(messages, ctx.display_tz)
    sessions = split_sessions(text_msgs)
    windows = pack_windows(sessions)
    if not windows:
        return

    sessions_so_far = 0
    for window in windows:
        sessions_so_far += window.session_count

        db = SessionLocal()
        try:
            persona_md = ""
            if ctx.persona_id is not None:
                persona = db.query(Persona).filter(Persona.id == ctx.persona_id).first()
                persona_md = (persona.persona_md or "") if persona else ""
            conv_row = db.query(Conversation).filter(Conversation.id == conversation_id).first()
            card_md = conv_row.card_md or ""
        finally:
            db.close()

        user_msg = _build_user_message(
            ctx=ctx, conversation=conv_row,
            inbox_platform_self_id=inbox_platform_self_id,
            window=window, total_windows=len(windows),
            sessions_so_far=sessions_so_far,
            persona_md=persona_md, card_md=card_md,
        )
        request_messages = [
            {"role": "system", "content": FOLD_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        try:
            response_text, _usage = await client.complete_chat(
                ctx.base_url, ctx.api_key, ctx.model, request_messages
            )
        except Exception as exc:
            logger.error(
                "Fold LLM call failed for conversation %s window %d: %s",
                conversation_id, window.window_id, exc,
            )
            db = SessionLocal()
            try:
                _log_llm_call(
                    db, persona_id=ctx.persona_id, inbox_id=inbox_id,
                    request_messages=request_messages,
                    response_raw=f"ERROR: {exc}", model=ctx.model,
                )
            finally:
                db.close()
            raise

        db = SessionLocal()
        try:
            _log_llm_call(
                db, persona_id=ctx.persona_id, inbox_id=inbox_id,
                request_messages=request_messages,
                response_raw=response_text, model=ctx.model,
            )
        finally:
            db.close()

        new_persona, new_card = _parse_fold_output(response_text)
        if new_persona is None and new_card is None:
            logger.warning(
                "Fold output 无法解析，保留原状（conversation=%s window=%d）",
                conversation_id, window.window_id,
            )
        else:
            db = SessionLocal()
            try:
                conv_row = db.query(Conversation).filter(Conversation.id == conversation_id).first()
                if new_card is not None:
                    conv_row.card_md = new_card
                    conv_row.updated_at = utc_now()
                if ctx.persona_id is not None and new_persona is not None:
                    persona = db.query(Persona).filter(Persona.id == ctx.persona_id).first()
                    if persona:
                        persona.persona_md = new_persona
                        persona.updated_at = utc_now()
                db.commit()
            finally:
                db.close()

        progress_state["windows_done"] += 1
        if progress_cb:
            progress_cb(dict(progress_state))


async def run_distill(
    *,
    conversation_ids: List[str],
    target_persona_id: Optional[str],
    provider_config_id: str,
    request_timeout: float,
    progress_cb: Optional[ProgressCb] = None,
) -> None:
    """蒸馏任务入口，由 DistillScanner 的 asyncio Task 调用。

    吃：conversation_ids（去重后的列表）+ 可选 target_persona_id + provider_config_id
    吐（副作用）：
      - 对每个有消息的会话调用 _fold_conversation()
      - 最终写回各会话的 card_md，以及（若有目标人设）persona_md
      - 通过 progress_cb 回传 {conversations_total, conversations_done,
        windows_total, windows_done}，供 DistillJob.progress 前端轮询
    """
    db = SessionLocal()
    try:
        ctx = _load_ctx(
            db,
            target_persona_id=target_persona_id,
            provider_config_id=provider_config_id,
        )
    finally:
        db.close()

    total_windows = 0
    runnable_ids: List[str] = []
    for cid in conversation_ids:
        db = SessionLocal()
        try:
            cv = db.query(Conversation).filter(Conversation.id == cid).first()
            if not cv:
                continue
            msgs = _load_conversation_messages(db, cid)
        finally:
            db.close()
        if not msgs:
            continue
        text_msgs = _messages_to_text_messages(msgs, ctx.display_tz)
        sessions = split_sessions(text_msgs)
        windows = pack_windows(sessions)
        total_windows += len(windows)
        if windows:
            runnable_ids.append(cid)

    if total_windows == 0:
        logger.info("蒸馏任务没有可处理的聊天记录（conversations=%d）", len(conversation_ids))
        return

    progress_state = {
        "conversations_total": len(runnable_ids),
        "conversations_done": 0,
        "windows_total": total_windows,
        "windows_done": 0,
    }
    if progress_cb:
        progress_cb(dict(progress_state))

    client = ProviderClient(request_timeout=request_timeout)
    try:
        for cid in runnable_ids:
            await _fold_conversation(
                client=client, ctx=ctx, conversation_id=cid,
                progress_state=progress_state, progress_cb=progress_cb,
            )
            progress_state["conversations_done"] += 1
            if progress_cb:
                progress_cb(dict(progress_state))
    finally:
        await client.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="Distill 蒸馏（CLI / 调试用）")
    parser.add_argument("--conversation-ids", required=True, help="逗号分隔的 conversation id 列表")
    parser.add_argument("--target-persona-id", default=None)
    parser.add_argument("--provider-config-id", required=True)
    parser.add_argument("--request-timeout", type=float, required=True)
    args = parser.parse_args()

    def progress_cb(state: Dict[str, int]) -> None:
        print(f"  progress: {state}")

    asyncio.run(
        run_distill(
            conversation_ids=[c for c in args.conversation_ids.split(",") if c],
            target_persona_id=args.target_persona_id,
            provider_config_id=args.provider_config_id,
            request_timeout=args.request_timeout,
            progress_cb=progress_cb,
        )
    )


if __name__ == "__main__":
    main()
