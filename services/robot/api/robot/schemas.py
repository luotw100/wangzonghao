from typing import Optional

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
    api_key: Optional[str] = None
    default_model: str


class ProviderConfigUpdate(StrictModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: Optional[str] = None


# --- Characters ---

class CharacterCreate(StrictModel):
    name: str
    wechat_wxid_self: Optional[str] = None
    provider_config_id: Optional[str] = None


class CharacterUpdate(StrictModel):
    name: Optional[str] = None
    persona_md: Optional[str] = None
    wechat_wxid_self: Optional[str] = None
    provider_config_id: Optional[str] = None
    status: Optional[str] = None


# --- Contacts ---

class ContactUpdate(StrictModel):
    display_name: Optional[str] = None
    card_md: Optional[str] = None
    status: Optional[str] = None
