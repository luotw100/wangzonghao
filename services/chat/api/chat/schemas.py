from datetime import datetime

from pydantic import BaseModel, ConfigDict

from chat.enums import AccountStatus, CommandStatus, MessageSource, MessageType, SenderType


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class AccountRead(StrictModel):
    id: str
    username: str
    display_name: str
    avatar_url: str | None
    status: AccountStatus
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


class LoginRequest(StrictModel):
    username: str
    password: str


class LoginResponse(StrictModel):
    token: str
    account: AccountRead


class ContactCreate(StrictModel):
    display_name: str
    platform_contact_id: str | None = None
    avatar_url: str | None = None
    note: str | None = None


class ContactUpdate(StrictModel):
    display_name: str | None = None
    avatar_url: str | None = None
    note: str | None = None


class ContactRead(StrictModel):
    id: str
    account_id: str
    platform_contact_id: str
    display_name: str
    avatar_url: str | None
    note: str | None
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationCreate(StrictModel):
    contact_id: str
    title: str | None = None


class ConversationUpdate(StrictModel):
    title: str | None = None


class ConversationRead(StrictModel):
    id: str
    account_id: str
    contact_id: str
    title: str
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    contact: ContactRead


class MessageCreate(StrictModel):
    sender_type: SenderType
    msg_type: MessageType
    content: str


class BulkMessageItem(StrictModel):
    sender_type: SenderType
    msg_type: MessageType
    content: str
    created_at: datetime


class BulkMessageImport(StrictModel):
    filename: str | None = None
    messages: list[BulkMessageItem]


class MessageRead(StrictModel):
    id: int
    account_id: str
    conversation_id: str
    sender_type: SenderType
    sender_contact_id: str | None
    msg_type: str
    content: str
    source: MessageSource
    created_at: datetime


class ConversationMessages(StrictModel):
    conversation: ConversationRead
    messages: list[MessageRead]


class StatusResponse(StrictModel):
    status: CommandStatus
    id: str | int | None = None
    imported: int | None = None
    ids: list[int] | None = None
