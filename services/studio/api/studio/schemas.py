from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Auth ---

class LoginRequest(StrictModel):
    username: str
    password: str


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


class PersonaUpdate(StrictModel):
    name: Optional[str] = None
    persona_md: Optional[str] = None
    status: Optional[Literal["active", "archived"]] = None


# --- Bridges (Cloudflare-tunnel-style daemons) ---

class BridgeCreate(StrictModel):
    display_name: str


class BridgeUpdate(StrictModel):
    display_name: Optional[str] = None


# --- Inboxes ---

class InboxCreate(StrictModel):
    platform: str
    display_name: str
    default_persona_id: Optional[str]
    bridge_id: Optional[str]
    reply_provider_config_id: Optional[str]
    enabled: bool


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
    autoreply_enabled: Optional[bool] = None
    status: Optional[Literal["active", "archived"]] = None


# --- Distill Jobs ---

class DistillJobCreate(StrictModel):
    source_inbox_id: str
    target_persona_id: str
    provider_config_id: str


# --- Manual outbound seed (debug / pre-LLM-brain) ---

class OutboundChunk(StrictModel):
    content: str
    msg_type: Literal["text"]


class OutboundCreate(StrictModel):
    contact_id: str
    chunks: list[OutboundChunk]


# --- Bridge protocol (Bridge daemon ↔ Studio) ---

class BridgeHandshakeInbox(StrictModel):
    platform: str
    platform_self_id: str


class BridgeHandshake(StrictModel):
    hostname: str
    inboxes: list[BridgeHandshakeInbox]   # platform logins this bridge has authenticated; Studio resolves to its own inbox_id


class BridgeIncomingMessage(StrictModel):
    inbox_id: str
    peer_platform_id: str
    peer_display_name: str
    platform_msg_id: str
    role: Literal["self", "counterpart"]
    content: str
    sent_at: datetime


class BridgeIncomingBatch(StrictModel):
    messages: list[BridgeIncomingMessage]


class BridgeOutboundAck(StrictModel):
    result: Literal["sent", "failed"]
    platform_msg_id: Optional[str] = None
    reason: Optional[str] = None
