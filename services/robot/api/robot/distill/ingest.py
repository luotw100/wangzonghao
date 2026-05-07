"""Ingest WeFlow JSON exports into robot.db.

Flow per archive:
    parse → identify self/counterpart wxids → upsert Contact → write Messages
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy.orm import Session as ORMSession

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


def _ensure_contact(
    db: ORMSession,
    character: Character,
    counterpart_wxid: str,
    counterpart_name: str,
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

    contact = Contact(
        id=f"ct_{uuid.uuid4().hex[:8]}",
        character_id=character.id,
        display_name=counterpart_name,
        wechat_wxid=counterpart_wxid,
        status="active",
    )
    db.add(contact)
    db.flush()
    return contact


async def ingest_archive(
    db: ORMSession,
    character: Character,
    self_wxid: str,
    src_path: Path,
    original_filename: str,
) -> ChatArchive:
    """Ingest one WeFlow JSON file. Idempotent on file_hash; fails on duplicates."""
    with src_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    raw_messages: List[Dict[str, Any]] = data.get("messages") or []
    if not raw_messages:
        raise ValueError("聊天记录为空")

    name_map = build_name_map([raw_messages])
    counterpart_wxid = _identify_counterpart(name_map, self_wxid)
    counterpart_name = name_map[counterpart_wxid]

    hash_hex = file_hash(src_path)
    duplicate = (
        db.query(ChatArchive)
        .filter(ChatArchive.character_id == character.id, ChatArchive.file_hash == hash_hex)
        .first()
    )
    if duplicate:
        raise ValueError(f"该文件已上传过 (archive {duplicate.id})")

    archive_id = f"a_{uuid.uuid4().hex[:8]}"
    dest_path = _persist_upload(character.id, archive_id, src_path)

    contact = _ensure_contact(db, character, counterpart_wxid, counterpart_name)

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
                role="self" if is_self else "counterpart",
                sender_name=sender_name,
                content=content,
                timestamp=ts,
                archive_msg_idx=idx,
            )
        )
        msg_count += 1

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
    db.commit()
    db.refresh(archive)
    return archive
