"""Response serializer functions — pure data extraction, no business logic."""

from typing import Any, Dict, Optional

from studio.models import (
    Account,
    Archive,
    Bridge,
    Contact,
    DistillJob,
    Inbox,
    Message,
    OutboundMessage,
    Persona,
    ProviderConfig,
)


def mask_api_key(api_key: Optional[str]) -> Optional[str]:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def s_account(a: Account) -> Dict[str, Any]:
    return {
        "id": a.id, "username": a.username, "display_name": a.display_name,
        "role": a.role, "status": a.status,
        "created_at": a.created_at, "last_login_at": a.last_login_at,
    }


def s_provider(p: ProviderConfig) -> Dict[str, Any]:
    return {
        "id": p.id, "owner_account_id": p.owner_account_id,
        "name": p.name, "base_url": p.base_url,
        "default_model": p.default_model,
        "scope": p.scope, "status": p.status, "is_default": p.is_default,
        "has_api_key": bool(p.api_key), "api_key_preview": mask_api_key(p.api_key),
        "created_at": p.created_at, "updated_at": p.updated_at,
    }


def s_persona(p: Persona) -> Dict[str, Any]:
    return {
        "id": p.id, "account_id": p.account_id, "name": p.name,
        "persona_md": p.persona_md, "status": p.status,
        "created_at": p.created_at, "updated_at": p.updated_at,
    }


def s_bridge(b: Bridge) -> Dict[str, Any]:
    return {
        "id": b.id, "account_id": b.account_id, "display_name": b.display_name,
        "hostname": b.hostname, "status": b.status, "last_seen_at": b.last_seen_at,
        "created_at": b.created_at, "updated_at": b.updated_at,
    }


def s_inbox(i: Inbox) -> Dict[str, Any]:
    return {
        "id": i.id, "account_id": i.account_id, "bridge_id": i.bridge_id,
        "platform": i.platform, "display_name": i.display_name,
        "default_persona_id": i.default_persona_id,
        "reply_provider_config_id": i.reply_provider_config_id,
        "enabled": i.enabled, "platform_self_id": i.platform_self_id,
        "created_at": i.created_at, "updated_at": i.updated_at,
    }


def s_contact(c: Contact) -> Dict[str, Any]:
    return {
        "id": c.id, "inbox_id": c.inbox_id, "peer_platform_id": c.peer_platform_id,
        "display_name": c.display_name, "card_md": c.card_md,
        "persona_id": c.persona_id,
        "reply_provider_config_id": c.reply_provider_config_id,
        "autoreply_enabled": c.autoreply_enabled,
        "pending_reply": c.pending_reply,
        "status": c.status, "last_seen_platform_msg_id": c.last_seen_platform_msg_id,
        "created_at": c.created_at, "updated_at": c.updated_at,
    }


def s_message(m: Message) -> Dict[str, Any]:
    return {
        "id": m.id, "contact_id": m.contact_id, "archive_id": m.archive_id,
        "external_id": m.external_id, "source": m.source, "role": m.role,
        "sender_name": m.sender_name, "content": m.content,
        "timestamp": m.timestamp, "created_at": m.created_at,
    }


def s_archive(a: Archive) -> Dict[str, Any]:
    return {
        "id": a.id, "account_id": a.account_id, "inbox_id": a.inbox_id,
        "filename": a.filename, "self_wxid": a.self_wxid,
        "message_count": a.message_count, "contact_count": a.contact_count,
        "uploaded_at": a.uploaded_at,
    }


def s_distill_job(j: DistillJob) -> Dict[str, Any]:
    return {
        "id": j.id, "account_id": j.account_id,
        "source_inbox_id": j.source_inbox_id, "target_persona_id": j.target_persona_id,
        "provider_config_id": j.provider_config_id, "status": j.status,
        "progress": j.progress, "error_message": j.error_message,
        "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at,
    }


def s_outbound(o: OutboundMessage, *, peer_platform_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": o.id, "inbox_id": o.inbox_id, "contact_id": o.contact_id,
        "peer_platform_id": peer_platform_id,
        "chunks": o.chunks, "status": o.status, "created_at": o.created_at,
        "delivered_at": o.delivered_at, "failed_reason": o.failed_reason,
    }


def s_bridge_inbox_view(i: Inbox) -> Dict[str, Any]:
    return {
        "id": i.id,
        "platform": i.platform,
        "platform_self_id": i.platform_self_id,
        "display_name": i.display_name,
        "enabled": i.enabled,
        "default_persona_id": i.default_persona_id,
    }
