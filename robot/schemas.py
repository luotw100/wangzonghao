from typing import Optional

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RobotCreate(StrictModel):
    name: str
    profile: Optional[str] = None


class RobotUpdate(StrictModel):
    name: Optional[str] = None
    profile: Optional[str] = None


class ContactCreate(StrictModel):
    name: str
    profile: Optional[str] = None


class ContactUpdate(StrictModel):
    name: Optional[str] = None
    profile: Optional[str] = None


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
    robot_id: str
    contact_id: str
    title: Optional[str] = None
    provider_config_id: Optional[str] = None


class SessionUpdate(StrictModel):
    title: Optional[str] = None
    robot_id: Optional[str] = None
    contact_id: Optional[str] = None
    provider_config_id: Optional[str] = None