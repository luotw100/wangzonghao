from datetime import datetime

from pydantic import BaseModel, ConfigDict

from chat.enums import AccountStatus, CommandStatus, MessageSource, MessageType, SenderType


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class AccountRead(StrictModel):
    id: str
    username: str
    nickname: str
    avatar_url: str | None
    status: AccountStatus
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


class AccountUpdate(StrictModel):
    nickname: str


class LoginRequest(StrictModel):
    username: str
    password: str


class LoginResponse(StrictModel):
    token: str
    account: AccountRead


class ContactCreate(StrictModel):
    nickname: str
    username: str | None = None
    remark_name: str | None = None
    avatar_url: str | None = None


class ContactUpdate(StrictModel):
    remark_name: str | None = None
    avatar_url: str | None = None


class ContactRead(StrictModel):
    id: str
    account_id: str
    username: str
    nickname: str
    remark_name: str | None
    avatar_url: str | None
    is_deleted: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


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
    msg_type: MessageType = MessageType.TEXT
    content: str
    created_at: datetime | None = None


class MessageRead(StrictModel):
    id: int
    account_id: str
    conversation_id: str
    sender_type: SenderType
    sender_contact_id: str | None
    msg_type: MessageType
    content: str
    source: MessageSource
    created_at: datetime


class ConversationMessages(StrictModel):
    conversation: ConversationRead
    messages: list[MessageRead]


class MessageBulkItem(StrictModel):
    sender_type: SenderType
    msg_type: MessageType = MessageType.TEXT
    content: str
    created_at: datetime

class MessageBulkCreate(StrictModel):
    messages: list[MessageBulkItem]

class StatusResponse(StrictModel):
    status: CommandStatus
    id: int | None = None
    count: int | None = None


class UploadPresignRequest(StrictModel):
    filename: str
    mime_type: str


class UploadPresignResponse(StrictModel):
    storage_key: str
    upload_url: str
