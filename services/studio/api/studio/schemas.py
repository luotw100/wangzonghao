from datetime import datetime, timedelta, timezone as _tz
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

from studio.enums import (
    AccountStatus,
    ContactStatus,
    OutboundAckResult,
    OutboundMessageType,
    OutboundStatus,
    ReplyPolicy,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ReadModel(BaseModel):
    """ORM → JSON 投影基类。声明字段后 FastAPI 用 from_attributes 自动转换。"""
    model_config = ConfigDict(from_attributes=True)


# Bridge online/offline 派生阈值
_BRIDGE_OFFLINE_AFTER = timedelta(seconds=45)


# --- Auth ---

class LoginRequest(StrictModel):
    """登录请求体。"""

    username: str = Field(description="用户名")
    password: str = Field(description="明文密码（传输层走 HTTPS 加密）")


class LoginResponse(BaseModel):
    """登录响应：token + 账号信息。"""
    token: str
    account: "AccountRead"  # forward ref, defined below


class OwnPasswordChange(StrictModel):
    """修改自己密码的请求体。修改成功后当前账号的所有 session（含其他设备）立即失效，需重新登录。"""

    current_password: str = Field(description="当前密码（用于验证身份）")
    new_password: str = Field(description="新密码（明文）")


# --- Personas ---

class PersonaCreate(StrictModel):
    """创建人设请求体。同一账号下名称不可重复。"""

    name: str = Field(description="人设名称，同一账号下唯一")
    persona_md: str = Field(
        default="",
        description="人设内容（Markdown 格式）。",
    )
    timezone: str = Field(
        default="UTC",
        description="人设所在时区（IANA 格式，如 Asia/Shanghai、UTC）。",
    )


class PersonaUpdate(StrictModel):
    """更新人设请求体。只传需要修改的字段。"""

    name: Optional[str] = Field(default=None, description="新名称")
    persona_md: Optional[str] = Field(default=None, description="新人设内容")
    timezone: Optional[str] = Field(default=None, description="新时区（IANA 格式）")


# --- Inboxes ---

class InboxUpdate(StrictModel):
    """更新 Inbox 配置请求体。只传需要修改的字段。

    - `bridge_id`：传 string 重新绑定到指定 Bridge；传 null 解除绑定。
      字段缺省时保持当前值不变（语义靠 PATCH + model_fields_set 区分）。
    """

    display_name: Optional[str] = Field(default=None, description="新显示名称")
    bridge_id: Optional[str] = Field(
        default=None,
        description="重新绑定到指定 Bridge；传 null 解除绑定。缺省时保持原值。",
    )


# --- Contacts ---

class ContactUpdate(StrictModel):
    """更新 Contact 配置请求体（PATCH 语义）。只传需要修改的字段。

    对 `persona_id`：缺省 = 保持原值；显式传 null = 清空。Provider 不开放前端配置，由后台 CLI 维护。
    """

    display_name: Optional[str] = Field(default=None, description="新显示名称")
    card_md: Optional[str] = Field(
        default=None,
        description="联系人名片（Markdown 格式）。",
    )
    persona_id: Optional[str] = Field(
        default=None,
        description="为此联系人指定使用的人设 ID。",
    )
    takeover: Optional[bool] = Field(
        default=None,
        description="是否启用 AI 接管。",
    )
    reply_policy: Optional[ReplyPolicy] = Field(
        default=None,
        description="自动回复策略：disabled / autoreply。",
    )
    status: Optional[ContactStatus] = Field(
        default=None,
        description="联系人状态：active / archived。",
    )


# --- Distill Jobs ---

class DistillJobCreate(StrictModel):
    """创建蒸馏任务请求体。"""

    contact_ids: List[str] = Field(
        min_length=1,
        description="参与蒸馏的联系人 ID 列表（去重后处理）。至少 1 个。",
    )
    target_persona_id: Optional[str] = Field(
        default=None,
        description="蒸馏结果写入的目标人设 ID。",
    )


# --- Manual outbound seed (debug / pre-LLM-brain) ---

class OutboundCreate(StrictModel):
    """手动创建待发消息请求体（调试 / 预设回复用）。目标 contact 由路径决定。"""

    msg_type: OutboundMessageType = Field(
        default=OutboundMessageType.TEXT,
        description="消息类型：text / image / audio / video / file",
    )
    content: str = Field(description="消息内容。媒体消息填 storage key。")


# --- Bridge protocol (Bridge daemon ↔ Studio) ---

class BridgeHandshakeInbox(StrictModel):
    """Bridge 握手时上报的单个平台账号身份。"""

    platform: str = Field(description="平台名称，如 wechat、feishu、chat")
    platform_self_id: str = Field(description="本账号在该平台上的唯一 ID")


class BridgeHandshake(StrictModel):
    """Bridge 首次启动或 token 失效后的登录请求（密码换 token）。

    machine_id 完全由 Studio 签发：若客户端传入的 machine_id 未在数据库中
    匹配到本账号下的 Bridge 行，则忽略并重新生成一个 4 位短码返回。
    """

    username: str = Field(description="Studio 账号用户名")
    password: str = Field(description="Studio 账号密码（明文）")
    machine_id: str | None = Field(
        default=None,
        description="Bridge 所在机器的唯一 ID（4 位短码）。首次启动不传；之后每次重启都应带上。",
    )


class BridgeRegisterInboxes(StrictModel):
    """Bridge 启动或频道变化后，注册/刷新当前服务的平台账号列表（需 token 鉴权）。"""

    inboxes: list[BridgeHandshakeInbox] = Field(
        description="Bridge 当前服务的平台账号列表"
    )


class BridgeIncomingMessage(StrictModel):
    """Bridge 上报的单条入站消息。"""

    inbox_id: str = Field(description="消息所属的 Inbox ID（Bridge 服务的平台账号）")
    peer_platform_id: str = Field(description="对话方在平台上的唯一 ID，用于查找或创建 Contact")
    peer_display_name: str = Field(description="对话方的平台显示名称，Contact 不存在时用于初始化 display_name")
    platform_msg_id: Optional[str] = Field(
        default=None,
        description="平台侧的消息 ID（可选，仅用于调试/排查；不参与去重，去重靠 msg_hash）。",
    )
    sender_id: str = Field(
        description="发送方在平台上的唯一 ID。"
    )
    msg_type: str = Field(default="text", description="消息类型：text / image / audio / video / file")
    content: str = Field(
        description="消息内容。文本消息为正文；媒体消息为 Studio S3 的 storage key。"
    )
    content_hash: Optional[str] = Field(
        default=None,
        description='媒体文件的内容哈希，格式为 "sha256:{64位十六进制}"。文本消息不传。',
    )
    sent_at: datetime = Field(description="消息在平台上的发送时间（UTC）")


class BridgeIncomingBatch(StrictModel):
    """Bridge 批量上报入站消息的请求体。"""

    messages: list[BridgeIncomingMessage] = Field(description="入站消息列表")


class BridgeOutboundAck(StrictModel):
    """Bridge 回报待发消息执行结果的请求体。"""

    result: OutboundAckResult = Field(
        description="执行结果：sent（发送成功，消息状态变为 delivered）/ failed（发送失败，状态变为 failed）"
    )
    platform_msg_id: Optional[str] = Field(
        default=None, description="平台侧分配的消息 ID（发送成功时可选上报，目前仅记录）"
    )
    reason: Optional[str] = Field(
        default=None, description="失败原因（result=failed 时填写，记录到 failed_reason 字段）"
    )


class BridgeMediaPresignRequest(StrictModel):
    """申请媒体文件上传预签名的请求体。"""

    filename: str = Field(description="文件名（含扩展名）")
    mime_type: str = Field(description="文件 MIME 类型")


class BridgeMediaCheckOrPresignRequest(StrictModel):
    """检查媒体文件是否已存在，若不存在则申请上传预签名。"""

    content_hash: str = Field(
        description='文件内容哈希，格式为 "sha256:{64位十六进制}"'
    )
    filename: str = Field(description="文件名（含扩展名）")
    mime_type: str = Field(description="文件 MIME 类型")


class BridgePeer(StrictModel):
    """Bridge 上报的单个对话方信息。"""

    peer_platform_id: str = Field(description="对话方在平台上的唯一 ID")
    display_name: str = Field(description="对话方的平台显示名称")


class BridgeReportPeers(StrictModel):
    """Bridge 批量上报对话方列表请求体（用于同步通讯录）。"""

    inbox_id: str = Field(description="对话方所属的 Inbox ID")
    peers: list[BridgePeer] = Field(description="对话方列表")


# ===========================================================================
# Read schemas — ORM → JSON 投影
# 列表用 *Summary（瘦版，去掉大字段）；详情用完整版。
# 路由用 response_model=... 让 FastAPI 自动按 schema 投影。
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
    """对外展示当前在用的 Provider — 只有名字，不暴露 base_url / api_key / id。"""
    name: str


class ContactSummary(_ReadModel):
    id: str
    inbox_id: str
    peer_platform_id: str
    display_name: str
    persona_id: Optional[str]
    provider: ProviderBrief
    takeover: bool
    reply_policy: ReplyPolicy
    status: ContactStatus
    last_reply_round_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ContactRead(ContactSummary):
    card_md: str


class MessageRead(_ReadModel):
    id: int
    contact_id: str
    external_id: Optional[str]
    role: str
    msg_type: str
    sender_name: Optional[str]
    content: str
    timestamp: datetime
    created_at: datetime


class DistillJobSummary(_ReadModel):
    id: str
    account_id: str
    contact_ids: List[str]
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
    """握手/心跳给 Bridge 看到的 Inbox 视图（不含 account_id / bridge_id 等内部字段）。"""
    id: str
    platform: str
    platform_self_id: Optional[str]
    display_name: str


class OutboundRead(_ReadModel):
    """OutboundMessage 的对外投影。peer_platform_id 由路由层注入（不在表里）。"""
    id: int
    inbox_id: str
    contact_id: str
    peer_platform_id: Optional[str] = None
    msg_type: str
    content: str
    status: OutboundStatus
    created_at: datetime
    delivered_at: Optional[datetime]
    failed_reason: str


class ConversationItem(BaseModel):
    """list_conversations 的单条聚合结果。"""
    contact: ContactSummary
    inbox: InboxRead
    latest_message: Optional[MessageRead]
    message_count: int
