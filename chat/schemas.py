from typing import Optional

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationCreate(StrictModel):
    title: Optional[str] = None


class ConversationUpdate(StrictModel):
    title: Optional[str] = None


class ConversationMessageCreate(StrictModel):
    role: str
    msg_type: str
    content: str
