"""Ingest WeFlow JSON exports into robot.db + seed chat simulator.

Flow per archive:
    parse → identify self/counterpart wxids → upsert Contact (+ chat user)
    → upsert Session (+ chat conversation) → write Messages → bulk-import to chat
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy.orm import Session as ORMSession

from robot.clients import ChatAdapter
from robot.db import STORAGE_DIR
from robot.distill.converter import (
    build_name_map,
    clean_content,
    message_timestamp,
    should_keep,
)
from robot.models import (
    Character,
    ChatArchive,
    Contact,
    Message,
    SessionRecord,
)

UPLOADS_DIR = STORAGE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _persist_upload(character_id: str, archive_id: str, src_path: Path) -> Path:
    dest_dir = UPLOADS_DIR / character_id
    dest_dir.mkdir(exist_ok=True)
    dest_path = dest_dir / f"{archive_id}.json"
    shutil.copyfile(src_path, dest_path)
    return dest_path


def _identify_counterpart(name_map: Dict[str, str], self_wxid: str) -> str:
    if self_wxid not in name_map:
        raise ValueError(
            f"指定的主播 wxid '{self_wxid}' 不在聊天记录中。"
            f"可见 wxid: {sorted(name_map.keys())}"
        )
    counterparts = [w for w in name_map if w != self_wxid]
    if len(counterparts) != 1:
        raise ValueError(
            f"暂只支持 1 对 1 聊天，当前对方有 {len(counterparts)} 人: {counterparts}"
        )
    return counterparts[0]


async def _ensure_contact(
    db: ORMSession,
    character: Character,
    counterpart_wxid: str,
    counterpart_name: str,
    chat_adapter: ChatAdapter,
) -> Contact:
    contact = (
        db.query(Contact)
        .filter(
            Contact.character_id == character.id,
            Contact.wechat_wxid == counterpart_wxid,
        )
        .first()
    )
    if contact:
        return contact

    chat_user = await chat_adapter.create_user(counterpart_name)
    contact = Contact(
        id=f"ct_{uuid.uuid4().hex[:8]}",
        character_id=character.id,
        display_name=counterpart_name,
        wechat_wxid=counterpart_wxid,
        chat_user_id=chat_user["id"],
        status="active",
    )
    db.add(contact)
    db.flush()
    return contact


async def _ensure_session(
    db: ORMSession,
    character: Character,
    contact: Contact,
    chat_adapter: ChatAdapter,
) -> SessionRecord:
    session = (
        db.query(SessionRecord)
        .filter(
            SessionRecord.contact_id == contact.id,
            SessionRecord.adapter_type == "chat",
        )
        .first()
    )
    if session:
        return session

    character_chat_user_id = character.adapter_identities.get("chat")
    if not character_chat_user_id:
        raise ValueError(
            f"Character {character.id} 没有 chat user。"
            "Character 创建时应自动绑定 chat user，请检查初始化逻辑。"
        )

    conv = await chat_adapter.create_conversation(
        user_a_id=character_chat_user_id,
        user_b_id=contact.chat_user_id,
        title=f"{character.name} ↔ {contact.display_name}",
    )
    session = SessionRecord(
        id=f"s_{uuid.uuid4().hex[:8]}",
        contact_id=contact.id,
        adapter_type="chat",
        adapter_thread_id=conv["id"],
        status="active",
    )
    db.add(session)
    db.flush()
    return session


def _is_first_archive_for_contact(db: ORMSession, contact_id: str) -> bool:
    existing = (
        db.query(Message)
        .filter(Message.contact_id == contact_id, Message.source == "upload")
        .first()
    )
    return existing is None


async def ingest_archive(
    db: ORMSession,
    character: Character,
    self_wxid: str,
    src_path: Path,
    original_filename: str,
    chat_adapter: ChatAdapter,
) -> ChatArchive:
    """Ingest one WeFlow JSON file. Idempotent on file_hash; fails on duplicates."""
    # 1. Parse and validate
    with src_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    raw_messages: List[Dict[str, Any]] = data.get("messages") or []
    if not raw_messages:
        raise ValueError("聊天记录为空")

    name_map = build_name_map([raw_messages])
    counterpart_wxid = _identify_counterpart(name_map, self_wxid)
    counterpart_name = name_map[counterpart_wxid]

    # 2. Hash + dedup
    hash_hex = file_hash(src_path)
    duplicate = (
        db.query(ChatArchive)
        .filter(ChatArchive.character_id == character.id, ChatArchive.file_hash == hash_hex)
        .first()
    )
    if duplicate:
        raise ValueError(f"该文件已上传过 (archive {duplicate.id})")

    # 3. Persist file
    archive_id = f"a_{uuid.uuid4().hex[:8]}"
    dest_path = _persist_upload(character.id, archive_id, src_path)

    # 4. Upsert contact + session (creates chat user/conversation if needed)
    contact = await _ensure_contact(db, character, counterpart_wxid, counterpart_name, chat_adapter)
    session = await _ensure_session(db, character, contact, chat_adapter)

    seed_chat = _is_first_archive_for_contact(db, contact.id)
    character_chat_user_id = character.adapter_identities["chat"]

    # 5. Convert + insert messages, build chat bulk payload
    bulk_payload: List[Dict[str, Any]] = []
    msg_count = 0
    sorted_raw = sorted(raw_messages, key=lambda m: m.get("createTime") or 0)
    for idx, raw in enumerate(sorted_raw):
        if not should_keep(raw):
            continue
        wxid = raw.get("senderUsername", "")
        if not wxid or "@chatroom" in wxid:
            continue
        content = clean_content(raw.get("content") or "")
        if not content:
            continue
        try:
            ts = message_timestamp(raw)
        except ValueError:
            continue

        is_self = wxid == self_wxid
        sender_name = name_map.get(wxid, wxid)

        db.add(
            Message(
                contact_id=contact.id,
                archive_id=archive_id,
                source="upload",
                role="self" if is_self else "counterpart",
                sender_name=sender_name,
                content=content,
                timestamp=ts,
                status="sent",
                archive_msg_idx=idx,
            )
        )
        msg_count += 1

        if seed_chat:
            bulk_payload.append({
                "sender_id": character_chat_user_id if is_self else contact.chat_user_id,
                "msg_type": "text",
                "content": content,
                "created_at": ts.isoformat(),
            })

    archive = ChatArchive(
        id=archive_id,
        character_id=character.id,
        filename=original_filename,
        file_path=str(dest_path),
        file_hash=hash_hex,
        self_wxid=self_wxid,
        message_count=msg_count,
        contact_count=1,
    )
    db.add(archive)
    db.flush()

    # 6. Seed chat simulator (only for first archive of this contact)
    if seed_chat and bulk_payload:
        await chat_adapter.bulk_import_messages(session.adapter_thread_id, bulk_payload)

    db.commit()
    db.refresh(archive)
    return archive
