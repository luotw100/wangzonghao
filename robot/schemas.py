from typing import Optional

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class SessionCreate(StrictModel):
    adapter_thread_id: str
    takeover_user_id: str
    profile: Optional[str] = None
    counterpart_profile: Optional[str] = None
    provider_config_id: Optional[str] = None


class SessionUpdate(StrictModel):
    profile: Optional[str] = None
    counterpart_profile: Optional[str] = None
    provider_config_id: Optional[str] = None
    status: Optional[str] = None