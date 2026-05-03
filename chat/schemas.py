from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserCreate(StrictModel):
    name: str


class UserUpdate(StrictModel):
    name: Optional[str] = None


class ConversationCreate(StrictModel):
    title: Optional[str] = None
    user_a_id: str
    user_b_id: str


class ConversationUpdate(StrictModel):
    title: Optional[str] = None


class MessageCreate(StrictModel):
    sender_id: str
    msg_type: str
    content: str


class BulkMessageItem(StrictModel):
    sender_id: str
    msg_type: str
    content: str
    created_at: datetime  # 必填，用于保留历史时间戳；模拟器场景不可缺省


class BulkMessageImport(StrictModel):
    messages: List[BulkMessageItem]
