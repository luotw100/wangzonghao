from datetime import datetime, timedelta, timezone as _tz
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

from studio.enums import (
    AccountStatus,
    ConversationKind,
    ConversationStatus,
    OutboundMessageType,
    OutboundStatus,
    ReplyPolicy,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ReadModel(BaseModel):
    """ORM → JSON projection base."""
    model_config = ConfigDict(from_attributes=True)


# Bridge online/offline derivation threshold
_BRIDGE_OFFLINE_AFTER = timedelta(seconds=45)


# --- Auth ---

class LoginRequest(StrictModel):
    username: str = Field(description="用户名")
    password: str = Field(description="明文密码（传输层走 HTTPS 加密）")


class LoginResponse(BaseModel):
    token: str
    account: "AccountRead"


class OwnPasswordChange(StrictModel):
    current_password: str = Field(description="当前密码（用于验证身份）")
    new_password: str = Field(description="新密码（明文）")


# --- Personas ---

class PersonaCreate(StrictModel):
    name: str = Field(description="人设名称，同一账号下唯一")
    persona_md: str = Field(default="", description="人设内容（Markdown 格式）")
    timezone: str = Field(default="UTC", description="人设所在时区（IANA 格式）")


class PersonaUpdate(StrictModel):
    name: Optional[str] = Field(default=None)
    persona_md: Optional[str] = Field(default=None)
    timezone: Optional[str] = Field(default=None)


# --- Inboxes ---

class InboxUpdate(StrictModel):
    display_name: Optional[str] = Field(default=None)
    bridge_id: Optional[str] = Field(
        default=None,
        description="重新绑定到指定 Bridge；传 null 解除绑定。缺省时保持原值。",
    )


# --- Conversations ---

class ConversationUpdate(StrictModel):
    """Conversation PATCH body. Defaults preserve the existing value;
    persona_id explicitly set to null clears it. Provider routing is
    server-managed via CLI.
    """

    display_name: Optional[str] = Field(default=None)
    card_md: Optional[str] = Field(default=None)
    persona_id: Optional[str] = Field(default=None)
    takeover: Optional[bool] = Field(default=None)
    reply_policy: Optional[ReplyPolicy] = Field(default=None)
    status: Optional[ConversationStatus] = Field(default=None)


# --- Distill jobs ---

class DistillJobCreate(StrictModel):
    conversation_ids: List[str] = Field(
        min_length=1, description="参与蒸馏的会话 ID 列表（去重后处理）。至少 1 个。",
    )
    target_persona_id: Optional[str] = Field(default=None)


# --- Manual outbound seed (debug) ---

class OutboundCreate(StrictModel):
    msg_type: OutboundMessageType = Field(
        default=OutboundMessageType.TEXT,
        description="消息类型：text / image / audio / video / file",
    )
    content: str = Field(description="消息内容。媒体消息填 storage key。")


# ===========================================================================
# Bridge protocol v2 (Bridge daemon ↔ Studio)
# ===========================================================================

class BridgeInboxClaim(StrictModel):
    """One inbox claim during register-inboxes."""
    platform: str = Field(description="平台名，如 chat / wechat / feishu")
    platform_self_id: str = Field(description="本账号在该平台上的唯一 ID")
    display_name: str = Field(description="Bridge 拿到的真实平台展示名")


class BridgeHandshake(StrictModel):
    """Password-for-token. machine_id is server-issued; client either omits
    it (first launch) or echoes the value Studio handed back earlier. An
    unrecognised machine_id is rejected with 400, not silently rotated.
    """
    username: str = Field(description="Studio 账号用户名")
    password: str = Field(description="Studio 账号密码（明文）")
    machine_id: Optional[str] = Field(
        default=None,
        description="Bridge 所在机器的 ID。首次启动不传；之后每次都应带 Studio 上次返回的值。",
    )


class BridgeRegisterInboxes(StrictModel):
    inboxes: List[BridgeInboxClaim] = Field(
        description="Bridge 当前服务的平台账号列表（含真实 display_name）",
    )


class BridgeIncomingMessage(StrictModel):
    """One inbound message reported by the bridge.

    The conversation is referenced by (inbox_id, platform_conversation_id)
    only — element metadata (kind / display_name / members) is owned by
    POST /api/bridge/conversations. If Studio doesn't find a row, it
    creates a placeholder (kind="unknown") so the message can land; the
    placeholder is updated in-place when /conversations comes through.
    """
    inbox_id: str = Field(description="消息所属的 Inbox ID")
    platform_conversation_id: str = Field(
        description="平台侧会话 ID（DM 一般等于 peer id，群是群 id）",
    )
    client_id: str = Field(
        description="Bridge 侧稳定唯一 ID（adapter 决定形态）。Studio 按 (conversation_id, client_id) 去重。",
    )
    sender_id: Optional[str] = Field(
        default=None,
        description="发送方平台 ID。NULL 表示是自己（inbox 的 platform_self_id）发出的。",
    )
    msg_type: str = Field(default="text", description="text only for now; image/audio/video/file 留作前向接口")
    content: str = Field(description="消息正文")
    sent_at: datetime = Field(description="消息在平台上的发送时间（UTC）")


class BridgeIncomingBatch(StrictModel):
    messages: List[BridgeIncomingMessage] = Field(description="入站消息列表")


class BridgeConversationMember(StrictModel):
    peer_platform_id: str = Field(description="成员在平台上的唯一 ID")
    display_name: str = Field(description="成员在该会话中的显示名")


class BridgeConversationItem(StrictModel):
    """One conversation in the upsert payload."""
    platform_conversation_id: str = Field(description="平台侧会话 ID")
    kind: ConversationKind = Field(description="dm / group / unknown")
    display_name: str = Field(description="会话展示名（DM=对方昵称，群=群名）")
    members: List[BridgeConversationMember] = Field(
        description="成员列表（DM 一条，群 N 条）",
    )


class BridgeConversationsUpsert(StrictModel):
    """Bulk conversation directory update (启动 + diff 时调)."""
    inbox_id: str = Field(description="Conversation 所属的 Inbox ID")
    conversations: List[BridgeConversationItem] = Field(
        description="完整或增量的 conversation 集合（漏报的留存，不删）",
    )


# ===========================================================================
# Read schemas (ORM → JSON projection)
# ===========================================================================

class AccountRead(_ReadModel):
    id: str
    username: str
    display_name: Optional[str]
    status: AccountStatus
    created_at: datetime
    updated_at: datetime


class PersonaSummary(_ReadModel):
    id: str
    account_id: str
    name: str
    timezone: str
    created_at: datetime
    updated_at: datetime


class PersonaRead(PersonaSummary):
    persona_md: str


class InboxRead(_ReadModel):
    id: str
    account_id: str
    bridge_id: Optional[str]
    platform: str
    display_name: str
    platform_self_id: Optional[str]
    created_at: datetime
    updated_at: datetime


class ProviderBrief(_ReadModel):
    name: str


class ConversationMemberRead(_ReadModel):
    peer_platform_id: str
    display_name: str
    updated_at: datetime


class ConversationSummary(_ReadModel):
    id: str
    inbox_id: str
    platform_conversation_id: str
    kind: ConversationKind
    display_name: str
    persona_id: Optional[str]
    provider: ProviderBrief
    takeover: bool
    reply_policy: ReplyPolicy
    status: ConversationStatus
    last_reply_round_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ConversationRead(ConversationSummary):
    card_md: str
    members: List[ConversationMemberRead]


class MessageRead(_ReadModel):
    id: int
    conversation_id: str
    client_id: str
    sender_id: Optional[str]
    msg_type: str
    content: str
    timestamp: datetime
    created_at: datetime

    @computed_field
    @property
    def from_self(self) -> bool:
        return self.sender_id is None


class DistillJobSummary(_ReadModel):
    id: str
    account_id: str
    conversation_ids: List[str]
    target_persona_id: Optional[str]
    provider: ProviderBrief
    status: str
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class DistillJobRead(DistillJobSummary):
    progress: dict
    error_message: str


class BridgeRead(_ReadModel):
    id: str
    account_id: str
    machine_id: str
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def status(self) -> str:
        ts = self.last_seen_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_tz.utc)
        return "online" if (datetime.now(_tz.utc) - ts) <= _BRIDGE_OFFLINE_AFTER else "offline"


class BridgeInboxView(_ReadModel):
    """View returned by /api/bridge/inboxes (no account_id/bridge_id leak)."""
    id: str
    platform: str
    platform_self_id: Optional[str]
    display_name: str


class OutboundForBridge(_ReadModel):
    """Slim outbound projection — what the bridge needs to dispatch.
    Studio-only state (status / created_at / failed_reason) stays internal.
    """
    id: int
    inbox_id: str
    platform_conversation_id: str
    msg_type: str
    content: str


class OutboundRead(_ReadModel):
    """Full outbound projection — for the web UI / debugging."""
    id: int
    inbox_id: str
    conversation_id: str
    msg_type: str
    content: str
    status: OutboundStatus
    created_at: datetime
    delivered_at: Optional[datetime]
    failed_reason: str


class ConversationListItem(BaseModel):
    """list-conversations aggregate item for the web UI."""
    conversation: ConversationSummary
    inbox: InboxRead
    latest_message: Optional[MessageRead]
    message_count: int
    member_count: int
