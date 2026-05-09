"""Distill pipeline: per-contact rolling fold.

Reads messages of one source Inbox from studio.db, runs windows through the
fold prompt, writes target Persona persona_md + Contact card_md back to DB.
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

from studio.clients import ProviderClient
from studio.db import SessionLocal, ensure_database, utc_now
from studio.distill.packer import (
    TextMessage,
    Window,
    pack_windows,
    split_sessions,
)
from studio.enums import ContactStatus, LlmPurpose, MessageRole, ProviderStatus
from studio.models import (
    Contact,
    Inbox,
    LlmLog,
    Message,
    Persona,
    ProviderConfig,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
FOLD_PROMPT = (PROMPTS_DIR / "fold.md").read_text(encoding="utf-8")

# Parser for the two-section fold output (existing prompt still uses "Character Persona" header)
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
    persona_id: str
    persona_name: str
    inbox_id: str
    inbox_self_wxid: Optional[str]
    base_url: str
    api_key: str
    model: str


def _load_ctx(
    db: ORMSession,
    *,
    source_inbox_id: str,
    target_persona_id: str,
    provider_config_id: str,
) -> _DistillCtx:
    inbox = db.query(Inbox).filter(Inbox.id == source_inbox_id).first()
    if not inbox:
        raise ValueError(f"Inbox {source_inbox_id} 不存在")
    persona = db.query(Persona).filter(Persona.id == target_persona_id).first()
    if not persona:
        raise ValueError(f"Persona {target_persona_id} 不存在")
    pc = db.query(ProviderConfig).filter(
        ProviderConfig.id == provider_config_id,
        ProviderConfig.status == ProviderStatus.ACTIVE,
    ).first()
    if not pc:
        raise ValueError(f"Provider Config {provider_config_id} 不存在")
    if not pc.api_key:
        raise ValueError(f"Provider Config {pc.id} 缺少 api_key")
    return _DistillCtx(
        persona_id=persona.id,
        persona_name=persona.name,
        inbox_id=inbox.id,
        inbox_self_wxid=inbox.platform_self_id,
        base_url=pc.base_url,
        api_key=pc.api_key,
        model=pc.default_model,
    )


def _load_contact_messages(db: ORMSession, contact_id: str) -> List[Message]:
    return (
        db.query(Message)
        .filter(Message.contact_id == contact_id)
        .order_by(Message.timestamp.asc(), Message.id.asc())
        .all()
    )


def _messages_to_text_messages(msgs: List[Message]) -> List[TextMessage]:
    out: List[TextMessage] = []
    for m in msgs:
        sender = m.sender_name or ("我" if m.role == MessageRole.SELF else "对方")
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
    ctx: _DistillCtx,
    contact: Contact,
    window: Window,
    total_windows: int,
    sessions_so_far: int,
    persona_md: str,
    card_md: str,
) -> str:
    return (
        f"```yaml\n"
        f"character_name: {json.dumps(ctx.persona_name, ensure_ascii=False)}\n"
        f"character_wxid: {json.dumps(ctx.inbox_self_wxid or '', ensure_ascii=False)}\n"
        f"contact_name: {json.dumps(contact.display_name, ensure_ascii=False)}\n"
        f"contact_wxid: {json.dumps(contact.peer_platform_id or '', ensure_ascii=False)}\n"
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
    persona_id: str,
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


async def _fold_contact(
    *,
    client: ProviderClient,
    ctx: _DistillCtx,
    contact_id: str,
    progress_state: Dict[str, int],
    progress_cb: Optional[ProgressCb],
) -> None:
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            return
        messages = _load_contact_messages(db, contact_id)
    finally:
        db.close()

    if not messages:
        logger.info("Contact %s 没有消息，跳过", contact_id)
        return

    text_msgs = _messages_to_text_messages(messages)
    sessions = split_sessions(text_msgs)
    windows = pack_windows(sessions)
    if not windows:
        return

    sessions_so_far = 0
    for window in windows:
        sessions_so_far += window.session_count

        db = SessionLocal()
        try:
            persona = db.query(Persona).filter(Persona.id == ctx.persona_id).first()
            ct = db.query(Contact).filter(Contact.id == contact_id).first()
            persona_md = persona.persona_md or ""
            card_md = ct.card_md or ""
        finally:
            db.close()

        user_msg = _build_user_message(
            ctx=ctx, contact=ct, window=window,
            total_windows=len(windows), sessions_so_far=sessions_so_far,
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
            logger.error("Fold LLM call failed for contact %s window %d: %s",
                         contact_id, window.window_id, exc)
            db = SessionLocal()
            try:
                _log_llm_call(
                    db, persona_id=ctx.persona_id, inbox_id=ctx.inbox_id,
                    request_messages=request_messages,
                    response_raw=f"ERROR: {exc}", model=ctx.model,
                )
            finally:
                db.close()
            raise

        db = SessionLocal()
        try:
            _log_llm_call(
                db, persona_id=ctx.persona_id, inbox_id=ctx.inbox_id,
                request_messages=request_messages,
                response_raw=response_text, model=ctx.model,
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
                persona = db.query(Persona).filter(Persona.id == ctx.persona_id).first()
                ct = db.query(Contact).filter(Contact.id == contact_id).first()
                if new_persona is not None:
                    persona.persona_md = new_persona
                    persona.updated_at = utc_now()
                if new_card is not None:
                    ct.card_md = new_card
                    ct.updated_at = utc_now()
                db.commit()
            finally:
                db.close()

        progress_state["windows_done"] += 1
        if progress_cb:
            progress_cb(dict(progress_state))


async def run_distill(
    *,
    source_inbox_id: str,
    target_persona_id: str,
    provider_config_id: str,
    request_timeout: float,
    progress_cb: Optional[ProgressCb] = None,
) -> None:
    """Run distill across all contacts of one inbox; updates target persona + each contact card."""
    db = SessionLocal()
    try:
        ctx = _load_ctx(
            db,
            source_inbox_id=source_inbox_id,
            target_persona_id=target_persona_id,
            provider_config_id=provider_config_id,
        )
        contacts = (
            db.query(Contact)
            .filter(Contact.inbox_id == source_inbox_id, Contact.status == ContactStatus.ACTIVE)
            .order_by(Contact.created_at.asc())
            .all()
        )
    finally:
        db.close()

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
        logger.info("Inbox %s 没有可蒸馏的聊天记录", source_inbox_id)
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
                client=client, ctx=ctx, contact_id=cid,
                progress_state=progress_state, progress_cb=progress_cb,
            )
            progress_state["contacts_done"] += 1
            if progress_cb:
                progress_cb(dict(progress_state))
    finally:
        await client.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="Distill 蒸馏（CLI / 调试用）")
    parser.add_argument("--source-inbox-id", required=True)
    parser.add_argument("--target-persona-id", required=True)
    parser.add_argument("--provider-config-id", required=True)
    parser.add_argument("--request-timeout", type=float, required=True)
    args = parser.parse_args()

    ensure_database()

    def progress_cb(state: Dict[str, int]) -> None:
        print(f"  progress: {state}")

    asyncio.run(
        run_distill(
            source_inbox_id=args.source_inbox_id,
            target_persona_id=args.target_persona_id,
            provider_config_id=args.provider_config_id,
            request_timeout=args.request_timeout,
            progress_cb=progress_cb,
        )
    )


if __name__ == "__main__":
    main()
