from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from studio.enums import (
    AccountRole,
    AccountStatus,
    ContactStatus,
    OutboundAckResult,
    OutboundMessageType,
    PersonaStatus,
    ReplyPolicy,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Auth ---

class LoginRequest(StrictModel):
    username: str
    password: str


class AccountCreate(StrictModel):
    username: str
    password: str
    display_name: Optional[str]
    role: AccountRole


class AccountUpdate(StrictModel):
    display_name: Optional[str] = None
    role: Optional[AccountRole] = None
    status: Optional[AccountStatus] = None


class AccountPasswordReset(StrictModel):
    password: str


class OwnPasswordChange(StrictModel):
    current_password: str
    new_password: str


# --- Provider Configs ---

class ProviderConfigCreate(StrictModel):
    name: str
    base_url: str
    api_key: Optional[str]
    default_model: str


class ProviderConfigUpdate(StrictModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: Optional[str] = None


# --- Personas ---

class PersonaCreate(StrictModel):
    name: str
    persona_md: Optional[str]
    timezone: str = "UTC"


class PersonaUpdate(StrictModel):
    name: Optional[str] = None
    persona_md: Optional[str] = None
    timezone: Optional[str] = None
    status: Optional[PersonaStatus] = None


# --- Bridges (auto-provisioned daemons; users only ever read/revoke them) ---


# --- Inboxes (creation via bridge handshake only; no manual POST) ---


class InboxUpdate(StrictModel):
    display_name: Optional[str] = None
    default_persona_id: Optional[str] = None
    bridge_id: Optional[str] = None
    reply_provider_config_id: Optional[str] = None
    enabled: Optional[bool] = None
    clear_bridge: Optional[bool] = None
    clear_reply_provider: Optional[bool] = None


# --- Contacts ---

class ContactUpdate(StrictModel):
    display_name: Optional[str] = None
    card_md: Optional[str] = None
    persona_id: Optional[str] = None
    reply_provider_config_id: Optional[str] = None
    clear_reply_provider: Optional[bool] = None
    takeover: Optional[bool] = None
    reply_policy: Optional[ReplyPolicy] = None
    status: Optional[ContactStatus] = None


# --- Distill Jobs ---

class DistillJobCreate(StrictModel):
    contact_ids: List[str]
    target_persona_id: Optional[str] = None
    provider_config_id: Optional[str] = None


# --- Manual outbound seed (debug / pre-LLM-brain) ---

class OutboundCreate(StrictModel):
    contact_id: str
    msg_type: OutboundMessageType = OutboundMessageType.TEXT
    content: str


# --- Bridge protocol (Bridge daemon ↔ Studio) ---

class BridgeHandshakeInbox(StrictModel):
    platform: str
    platform_self_id: str


class BridgeHandshake(StrictModel):
    """Login — password in, token out. Nothing else.

    The bridge presents Studio account credentials + optional machine_id;
    if machine_id is not provided (first launch), Studio generates one.
    Studio upserts a Bridge row keyed by (account, machine_id) and mints
    a fresh session token used for all subsequent token-authenticated
    /api/bridge/* calls (including inbox registration).
    """
    username: str
    password: str
    machine_id: str | None = None


class BridgeRegisterInboxes(StrictModel):
    """Token-authenticated channel registration.

    Reports the platform identities this bridge is logged into. Studio
    upserts/binds an Inbox per identity and returns the authoritative
    inbox list + outbound cursor. No password — the bridge session token
    proves the account, exactly like a browser session.
    """
    inboxes: list[BridgeHandshakeInbox]


class BridgeIncomingMessage(StrictModel):
    inbox_id: str
    peer_platform_id: str
    peer_display_name: str
    platform_msg_id: Optional[str] = None   # nullable; advisory only
    sender_id: str                           # platform id of the sender (replaces role)
    msg_type: str = "text"
    content: str
    content_hash: Optional[str] = None      # for media: "sha256:{hex}"; None for text
    sent_at: datetime


class BridgeIncomingBatch(StrictModel):
    messages: list[BridgeIncomingMessage]


class BridgeOutboundAck(StrictModel):
    result: OutboundAckResult
    platform_msg_id: Optional[str] = None
    reason: Optional[str] = None


class BridgeMediaPresignRequest(StrictModel):
    filename: str
    mime_type: str


class BridgeMediaCheckOrPresignRequest(StrictModel):
    content_hash: str   # "sha256:{hex}"
    filename: str
    mime_type: str


class BridgePeer(StrictModel):
    peer_platform_id: str
    display_name: str


class BridgeReportPeers(StrictModel):
    inbox_id: str
    peers: list[BridgePeer]
