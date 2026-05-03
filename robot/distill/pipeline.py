"""Distill pipeline: per-contact rolling fold.

Reads upload messages from robot.db, runs windows through the fold prompt,
writes Operator persona_md + Contact card_md back to DB.
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

from sqlalchemy.orm import Session as ORMSession

from robot.clients import ProviderClient
from robot.db import SessionLocal, ensure_database, utc_now
from robot.distill.packer import (
    TextMessage,
    Window,
    pack_windows,
    split_sessions,
)
from robot.models import (
    Contact,
    LlmLog,
    Message,
    Operator,
    ProviderConfig,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
FOLD_PROMPT = (PROMPTS_DIR / "fold.md").read_text(encoding="utf-8")

# Parser for the two-section fold output
_PERSONA_RE = re.compile(
    r"={3,}\s*Operator Persona\s*={3,}\s*(.*?)(?=\n={3,}\s*Contact Card\s*={3,})",
    re.DOTALL,
)
_CARD_RE = re.compile(
    r"={3,}\s*Contact Card\s*={3,}\s*(.*)",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ProgressCb = Callable[[Dict[str, int]], None]


@dataclass
class _OperatorCtx:
    operator_id: str
    operator_name: str
    operator_wxid: Optional[str]
    base_url: str
    api_key: str
    model: str


def _load_operator_ctx(db: ORMSession, operator_id: str) -> _OperatorCtx:
    op = db.query(Operator).filter(Operator.id == operator_id).first()
    if not op:
        raise ValueError(f"Operator {operator_id} 不存在")
    if not op.provider_config_id:
        raise ValueError(f"Operator {operator_id} 未配置 Provider Config")
    pc = db.query(ProviderConfig).filter(ProviderConfig.id == op.provider_config_id).first()
    if not pc:
        raise ValueError(f"Provider Config {op.provider_config_id} 不存在")
    if not pc.api_key:
        raise ValueError(f"Provider Config {pc.id} 缺少 api_key")
    return _OperatorCtx(
        operator_id=op.id,
        operator_name=op.name,
        operator_wxid=(op.adapter_identities or {}).get("wechat_wxid_self"),
        base_url=pc.base_url,
        api_key=pc.api_key,
        model=pc.default_model,
    )


def _load_contact_messages(db: ORMSession, contact_id: str) -> List[Message]:
    return (
        db.query(Message)
        .filter(Message.contact_id == contact_id, Message.source == "upload")
        .order_by(Message.timestamp.asc(), Message.id.asc())
        .all()
    )


def _messages_to_text_messages(msgs: List[Message]) -> List[TextMessage]:
    out: List[TextMessage] = []
    for m in msgs:
        sender = m.sender_name or ("我" if m.role == "self" else "对方")
        line = f"[{m.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {sender}: {m.content}"
        out.append(
            TextMessage(
                timestamp=m.timestamp,
                sender=sender,
                content=m.content,
                raw_line=line,
            )
        )
    return out


def _build_user_message(
    *,
    op_ctx: _OperatorCtx,
    contact: Contact,
    window: Window,
    total_windows: int,
    sessions_so_far: int,
    persona_md: str,
    card_md: str,
) -> str:
    return (
        f"```yaml\n"
        f"operator_name: {json.dumps(op_ctx.operator_name, ensure_ascii=False)}\n"
        f"operator_wxid: {json.dumps(op_ctx.operator_wxid or '', ensure_ascii=False)}\n"
        f"contact_name: {json.dumps(contact.display_name, ensure_ascii=False)}\n"
        f"contact_wxid: {json.dumps(contact.wechat_wxid or '', ensure_ascii=False)}\n"
        f"window: {window.window_id}/{total_windows}\n"
        f"time_range: \"{window.time_range}\"\n"
        f"sessions_in_window: {window.session_count}\n"
        f"total_sessions: {sessions_so_far}\n"
        f"```\n\n"
        f"===== Operator Persona =====\n{persona_md or '空'}\n\n"
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
    operator_id: str,
    request_messages: List[Dict[str, str]],
    response_raw: str,
    model: str,
) -> None:
    db.add(
        LlmLog(
            purpose="distill",
            session_id=None,
            operator_id=operator_id,
            request_messages=json.dumps(request_messages, ensure_ascii=False),
            response_raw=response_raw,
            model=model,
            created_at=utc_now(),
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# Per-contact fold
# ---------------------------------------------------------------------------

async def _fold_contact(
    *,
    client: ProviderClient,
    op_ctx: _OperatorCtx,
    contact_id: str,
    progress_state: Dict[str, int],
    progress_cb: Optional[ProgressCb],
) -> None:
    """Run rolling fold over one contact's history; updates Operator.persona_md + Contact.card_md."""
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            return
        messages = _load_contact_messages(db, contact_id)
    finally:
        db.close()

    if not messages:
        logger.info("Contact %s 没有 upload 消息，跳过", contact_id)
        return

    text_msgs = _messages_to_text_messages(messages)
    sessions = split_sessions(text_msgs)
    windows = pack_windows(sessions)
    if not windows:
        return

    sessions_so_far = 0
    for window in windows:
        sessions_so_far += window.session_count

        # Reload current state each iteration (job runner may concurrently update other operators)
        db = SessionLocal()
        try:
            op = db.query(Operator).filter(Operator.id == op_ctx.operator_id).first()
            ct = db.query(Contact).filter(Contact.id == contact_id).first()
            persona_md = op.persona_md or ""
            card_md = ct.card_md or ""
        finally:
            db.close()

        user_msg = _build_user_message(
            op_ctx=op_ctx,
            contact=ct,
            window=window,
            total_windows=len(windows),
            sessions_so_far=sessions_so_far,
            persona_md=persona_md,
            card_md=card_md,
        )
        request_messages = [
            {"role": "system", "content": FOLD_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        try:
            response_text, _usage = await client.complete_chat(
                op_ctx.base_url, op_ctx.api_key, op_ctx.model, request_messages
            )
        except Exception as exc:
            logger.error("Fold LLM call failed for contact %s window %d: %s",
                         contact_id, window.window_id, exc)
            db = SessionLocal()
            try:
                _log_llm_call(
                    db,
                    operator_id=op_ctx.operator_id,
                    request_messages=request_messages,
                    response_raw=f"ERROR: {exc}",
                    model=op_ctx.model,
                )
            finally:
                db.close()
            raise

        db = SessionLocal()
        try:
            _log_llm_call(
                db,
                operator_id=op_ctx.operator_id,
                request_messages=request_messages,
                response_raw=response_text,
                model=op_ctx.model,
            )
        finally:
            db.close()

        new_persona, new_card = _parse_fold_output(response_text)
        if new_persona is None and new_card is None:
            logger.warning(
                "Fold output 无法解析，保留原状（contact=%s window=%d）",
                contact_id, window.window_id,
            )
        else:
            db = SessionLocal()
            try:
                op = db.query(Operator).filter(Operator.id == op_ctx.operator_id).first()
                ct = db.query(Contact).filter(Contact.id == contact_id).first()
                if new_persona is not None:
                    op.persona_md = new_persona
                    op.updated_at = utc_now()
                if new_card is not None:
                    ct.card_md = new_card
                    ct.updated_at = utc_now()
                db.commit()
            finally:
                db.close()

        progress_state["windows_done"] += 1
        if progress_cb:
            progress_cb(dict(progress_state))


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def run_distill_for_operator(
    operator_id: str,
    request_timeout: float,
    progress_cb: Optional[ProgressCb] = None,
) -> None:
    """Run full distill for an operator across all its contacts."""
    db = SessionLocal()
    try:
        op_ctx = _load_operator_ctx(db, operator_id)
        contacts = (
            db.query(Contact)
            .filter(Contact.operator_id == operator_id, Contact.status == "active")
            .order_by(Contact.created_at.asc())
            .all()
        )
    finally:
        db.close()

    # Pre-compute total windows for progress
    total_windows = 0
    contact_ids: List[str] = []
    for ct in contacts:
        db = SessionLocal()
        try:
            msgs = _load_contact_messages(db, ct.id)
        finally:
            db.close()
        if not msgs:
            continue
        text_msgs = _messages_to_text_messages(msgs)
        sessions = split_sessions(text_msgs)
        windows = pack_windows(sessions)
        total_windows += len(windows)
        if windows:
            contact_ids.append(ct.id)

    if total_windows == 0:
        logger.info("Operator %s 没有可蒸馏的聊天记录", operator_id)
        return

    progress_state = {
        "contacts_total": len(contact_ids),
        "contacts_done": 0,
        "windows_total": total_windows,
        "windows_done": 0,
    }
    if progress_cb:
        progress_cb(dict(progress_state))

    client = ProviderClient(request_timeout=request_timeout)
    try:
        for cid in contact_ids:
            await _fold_contact(
                client=client,
                op_ctx=op_ctx,
                contact_id=cid,
                progress_state=progress_state,
                progress_cb=progress_cb,
            )
            progress_state["contacts_done"] += 1
            if progress_cb:
                progress_cb(dict(progress_state))
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# CLI (debug)
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="Distill 蒸馏（CLI / 调试用）")
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--request-timeout", type=float, default=120.0)
    args = parser.parse_args()

    ensure_database()

    def progress_cb(state: Dict[str, int]) -> None:
        print(f"  progress: {state}")

    asyncio.run(
        run_distill_for_operator(
            operator_id=args.operator_id,
            request_timeout=args.request_timeout,
            progress_cb=progress_cb,
        )
    )


if __name__ == "__main__":
    main()
