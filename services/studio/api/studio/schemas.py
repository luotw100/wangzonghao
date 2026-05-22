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
    persona_md: Optional[str] = Field(default="", description="人设内容（Markdown 格式）")
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
    """账号信息（返回给客户端，不含密码）。"""
    id: str
    username: str
    display_name: Optional[str]
    status: AccountStatus
    created_at: datetime
    updated_at: datetime


class PersonaSummary(_ReadModel):
    """人设列表项（不含 persona_md 正文，减少传输量）。需要正文时调用 GET /api/personas/{id}。"""
    id: str
    account_id: str
    name: str
    timezone: str
    created_at: datetime
    updated_at: datetime


class PersonaRead(PersonaSummary):
    """人设详情（含 persona_md）。"""
    persona_md: str


class InboxRead(_ReadModel):
    """Inbox（平台账号身份）详情。bridge_id=null 表示当前未绑定守护进程。"""
    id: str
    account_id: str
    bridge_id: Optional[str]   # null=未绑定 Bridge，无法收发消息
    platform: str
    display_name: str
    platform_self_id: Optional[str]
    created_at: datetime
    updated_at: datetime


class ProviderBrief(_ReadModel):
    """Provider 的精简视图（仅 name），嵌入会话/蒸馏任务响应中，避免泄露 api_key。"""
    name: str


class ConversationMemberRead(_ReadModel):
    """会话成员（平台侧）。DM 只有一条（对方），群聊有 N 条。"""
    peer_platform_id: str   # 成员在平台的唯一 ID
    display_name: str
    updated_at: datetime


class ConversationSummary(_ReadModel):
    """会话列表项（不含 card_md 和 members，减少传输量）。"""
    id: str
    inbox_id: str
    platform_conversation_id: str
    kind: ConversationKind       # dm / group / unknown
    display_name: str
    persona_id: Optional[str]    # null=未绑定人设，ReplyScanner 会跳过
    provider: ProviderBrief
    takeover: bool               # True=Bridge 正在上报该会话消息
    reply_policy: ReplyPolicy    # disabled / autoreply
    status: ConversationStatus
    last_reply_round_at: Optional[datetime]   # 上次 LLM 回复时间
    created_at: datetime
    updated_at: datetime


class ConversationRead(ConversationSummary):
    """会话详情（含 card_md 和 members）。"""
    card_md: str                            # 对方用户画像 Markdown
    members: List[ConversationMemberRead]


class MessageRead(_ReadModel):
    """消息详情。

    ⚠ id 是数据库自增插入顺序，与消息的真实发送时间（timestamp）完全无关。
    同一会话中 id 较大的消息不一定比 id 较小的消息发送时间更晚（历史消息导入、
    平台延迟等场景下时间可能乱序）。展示时请以 timestamp 排序，
    翻页/去重等"是否已处理"逻辑才使用 id。

    from_self=True 表示该消息由 Inbox 自己发出（sender_id IS NULL）。
    """
    id: int               # 插入顺序，用作翻页游标；≠ 时间顺序
    conversation_id: str
    client_id: str        # Bridge 侧稳定 ID，(conversation_id, client_id) 全局唯一去重
    sender_id: Optional[str]   # null=Inbox 本人发出；非 null=对方平台 ID
    msg_type: str
    content: str
    timestamp: datetime   # 消息的真实平台发送时间（展示和排序应用此字段）
    created_at: datetime  # Studio 入库时间（仅审计用，不代表发送时间）

    @computed_field
    @property
    def from_self(self) -> bool:
        return self.sender_id is None


class DistillJobSummary(_ReadModel):
    """蒸馏任务列表项（不含 progress 和 error_message）。"""
    id: str
    account_id: str
    conversation_ids: List[str]
    target_persona_id: Optional[str]   # null=仅预览，不写回人设
    provider: ProviderBrief
    status: str                        # pending / running / done / failed
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class DistillJobRead(DistillJobSummary):
    """蒸馏任务详情（含 progress 进度快照和 error_message）。"""
    progress: dict        # pipeline 分段进度，由 DistillScanner 回写
    error_message: str    # 失败原因；done/pending/running 时为空字符串


class BridgeRead(_ReadModel):
    """Bridge 守护进程读取视图。status 字段由 last_seen_at 实时派生，不存库。"""
    id: str
    account_id: str
    machine_id: str
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def status(self) -> str:
        """online / offline，由 last_seen_at 实时派生（超过 45s 未心跳视为离线）。"""
        ts = self.last_seen_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_tz.utc)
        return "online" if (datetime.now(_tz.utc) - ts) <= _BRIDGE_OFFLINE_AFTER else "offline"


class BridgeInboxView(_ReadModel):
    """Bridge 协议侧的 Inbox 视图（不暴露 account_id / bridge_id）。

    仅供 Bridge daemon 使用；返回给 Bridge 的信息只包含它发送消息时需要的字段。
    """
    id: str
    platform: str
    platform_self_id: Optional[str]
    display_name: str


class OutboundForBridge(_ReadModel):
    """Bridge 拉取待发消息时的精简视图。

    Studio 内部状态字段（status / created_at / failed_reason）不下发给 Bridge，
    避免 Bridge 做不应由它做的状态决策。
    ⚠ id 是插入顺序，Studio 侧按 id asc 下发以保证先创建的先发，但 id 不代表时间语义。
    """
    id: int             # 插入顺序；Bridge 用此值在 _inflight 字典中去重，防止重发
    inbox_id: str
    platform_conversation_id: str
    msg_type: str
    content: str


class OutboundRead(_ReadModel):
    """待发消息的完整视图（供 Web UI / 调试使用）。"""
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
    """会话列表聚合项（Web UI 会话列表接口的返回格式）。

    包含会话本身、所属 Inbox、最新一条消息及统计数字，一次请求满足列表页的全部展示需求。
    """
    conversation: ConversationSummary
    inbox: InboxRead
    latest_message: Optional[MessageRead]   # 无消息时为 null
    message_count: int
    member_count: int
