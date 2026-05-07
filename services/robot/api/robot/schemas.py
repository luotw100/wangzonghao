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


# --- Inboxes ---

class InboxCreate(StrictModel):
    platform: str
    display_name: str
    default_persona_id: str
    enabled: bool


class InboxUpdate(StrictModel):
    display_name: Optional[str] = None
    default_persona_id: Optional[str] = None
    enabled: Optional[bool] = None


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


# --- Outbound (manual seed for testing; LLM brain not yet implemented) ---

class OutboundChunk(StrictModel):
    content: str
    msg_type: Literal["text"]


class OutboundCreate(StrictModel):
    contact_id: str
    chunks: list[OutboundChunk]


# --- Bridge protocol (B ↔ C) ---

class BridgeHandshake(StrictModel):
    hostname: str
    platform_self_id: str


class BridgeIncomingMessage(StrictModel):
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
