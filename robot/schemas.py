from typing import Optional

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Auth ---

class RequestCodeIn(StrictModel):
    email: str


class VerifyCodeIn(StrictModel):
    email: str
    code: str


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
    provider_config_id: Optional[str] = None


class CharacterUpdate(StrictModel):
    name: Optional[str] = None
    persona_md: Optional[str] = None
    provider_config_id: Optional[str] = None
    status: Optional[str] = None


# --- Contacts ---

class ContactUpdate(StrictModel):
    display_name: Optional[str] = None
    card_md: Optional[str] = None
    status: Optional[str] = None
