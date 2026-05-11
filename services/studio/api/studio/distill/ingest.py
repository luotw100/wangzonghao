"""Ingest WeFlow JSON exports into studio.db.

Archive is account-level content. At ingest time the caller specifies which
inbox the archive belongs to and which wxid in the archive is "self". Contacts
and messages are written under that inbox.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List

from sqlalchemy.orm import Session as ORMSession

from studio.db import utc_now
from studio.distill.converter import (
    build_name_map,
    clean_content,
    message_timestamp,
    should_keep,
)
from studio.enums import ContactStatus, MessageRole, MessageSource
from studio.models import (
    Archive,
    Contact,
    Inbox,
)
from studio.s3 import s3_put


def _data_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def _persist_upload(account_id: str, archive_id: str, data: bytes) -> str:
    key = f"uploads/{account_id}/{archive_id}.json"
    s3_put(key, data, content_type="application/json")
    return key


def _identify_counterpart(name_map: Dict[str, str], platform_self_id: str) -> str:
    if platform_self_id not in name_map:
        raise ValueError(
            f"指定的 platform_self_id '{platform_self_id}' 不在聊天记录中。"
            f"可见 wxid: {sorted(name_map.keys())}"
        )
    counterparts = [w for w in name_map if w != platform_self_id]
    if len(counterparts) != 1:
        raise ValueError(
            f"暂只支持 1 对 1 聊天，当前对方有 {len(counterparts)} 人: {counterparts}"
        )
    return counterparts[0]


def _ensure_contact(
    db: ORMSession,
    inbox: Inbox,
    counterpart_wxid: str,
    counterpart_name: str,
) -> Contact:
    contact = (
        db.query(Contact)
        .filter(Contact.inbox_id == inbox.id, Contact.peer_platform_id == counterpart_wxid)
        .first()
    )
    if contact:
        return contact
    now = utc_now()
    contact = Contact(
        id=f"ct_{uuid.uuid4().hex[:8]}",
        inbox_id=inbox.id,
        peer_platform_id=counterpart_wxid,
        display_name=counterpart_name,
        card_md=None,
        persona_id=inbox.default_persona_id,
        reply_provider_config_id=inbox.reply_provider_config_id,
        autoreply_enabled=False,
        pending_reply=False,
        status=ContactStatus.ACTIVE,
        last_seen_platform_msg_id=None,
        created_at=now, updated_at=now,
    )
    db.add(contact)
    db.flush()
    return contact


async def ingest_archive(
    db: ORMSession,
    account_id: str,
    inbox: Inbox,
    platform_self_id: str,
    raw_data: bytes,
    original_filename: str,
) -> Archive:
    """Ingest one WeFlow JSON file. Idempotent on file_hash; fails on duplicates."""
    data = json.loads(raw_data)
    raw_messages: List[Dict[str, Any]] = data.get("messages") or []
    if not raw_messages:
        raise ValueError("聊天记录为空")

    name_map = build_name_map([raw_messages])
    counterpart_wxid = _identify_counterpart(name_map, platform_self_id)
    counterpart_name = name_map[counterpart_wxid]

    hash_hex = _data_hash(raw_data)
    duplicate = (
        db.query(Archive)
        .filter(Archive.account_id == account_id, Archive.file_hash == hash_hex)
        .first()
    )
    if duplicate:
        raise ValueError(f"该文件已上传过 (archive {duplicate.id})")

    archive_id = f"a_{uuid.uuid4().hex[:8]}"
    s3_key = _persist_upload(account_id, archive_id, raw_data)

    contact = _ensure_contact(db, inbox, counterpart_wxid, counterpart_name)

    msg_count = 0
    sorted_raw = sorted(raw_messages, key=lambda m: m.get("createTime") or 0)
    now = utc_now()
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

        is_self = wxid == platform_self_id
        sender_name = name_map.get(wxid, wxid)
        external_id = f"archive:{archive_id}:{idx}"
        db.add(Message(
            contact_id=contact.id,
            archive_id=archive_id,
            external_id=external_id,
            source=MessageSource.ARCHIVE,
            role=MessageRole.SELF if is_self else MessageRole.COUNTERPART,
            sender_name=sender_name,
            content=content,
            timestamp=ts,
            archive_msg_idx=idx,
            created_at=now,
        ))
        msg_count += 1

    archive = Archive(
        id=archive_id, account_id=account_id, inbox_id=inbox.id,
        filename=original_filename, storage_key=s3_key, file_hash=hash_hex,
        platform_self_id=platform_self_id, message_count=msg_count, contact_count=1,
        uploaded_at=now,
    )
    db.add(archive)
    db.commit()
    db.refresh(archive)
    return archive
