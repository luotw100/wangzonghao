from typing import Optional

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


# --- Operators ---

class OperatorCreate(StrictModel):
    name: str
    provider_config_id: Optional[str] = None


class OperatorUpdate(StrictModel):
    name: Optional[str] = None
    persona_md: Optional[str] = None
    provider_config_id: Optional[str] = None
    status: Optional[str] = None


# --- Contacts ---

class ContactUpdate(StrictModel):
    display_name: Optional[str] = None
    card_md: Optional[str] = None
    status: Optional[str] = None


# --- Archives / Ingest ---

class ArchiveIngestRequest(StrictModel):
    """主播上传 WeFlow JSON 时的元数据。文件本体走 multipart/form-data。"""
    self_wxid: str  # 主播指明本份聊天记录里哪个 wxid 是自己


# --- Distill Jobs ---

class DistillJobCreate(StrictModel):
    pass  # operator_id from URL; no body needed


# --- Sessions ---
# Sessions 在新模型下完全由 ingest 内部管理，不暴露 create/update API。
# 仅提供查看接口。
