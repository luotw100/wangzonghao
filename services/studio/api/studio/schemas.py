from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from studio.enums import (
    AccountRole,
    AccountStatus,
    ContactStatus,
    OutboundAckResult,
    OutboundMessageType,
    PersonaStatus,
    ReplyPolicy,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Auth ---

class LoginRequest(StrictModel):
    """登录请求体。"""

    username: str = Field(description="用户名")
    password: str = Field(description="明文密码（传输层走 HTTPS 加密）")


class AccountCreate(StrictModel):
    """创建账号请求体（仅管理员可调用）。"""

    username: str = Field(description="登录用用户名，全局唯一")
    password: str = Field(description="初始密码")
    display_name: Optional[str] = Field(description="显示名称（可选）")
    role: AccountRole = Field(description="账号角色：admin（管理员，可管理所有账号和全局配置）/ user（普通用户，只能管理自己的数据）")


class AccountUpdate(StrictModel):
    """更新账号信息请求体（仅管理员可调用）。只传需要修改的字段。"""

    display_name: Optional[str] = Field(default=None, description="新显示名称，传 null 可清除")
    role: Optional[AccountRole] = Field(default=None, description="新角色")
    status: Optional[AccountStatus] = Field(
        default=None,
        description="新状态：active（正常）/ disabled（禁用）。设为非 active 时，该账号的所有 session 会被立即清除，强制下线。",
    )


class AccountPasswordReset(StrictModel):
    """管理员重置他人密码请求体。重置后该账号的所有 session 立即失效。"""

    password: str = Field(description="新密码（明文）")


class OwnPasswordChange(StrictModel):
    """修改自己密码的请求体。修改成功后当前账号的所有 session（含其他设备）立即失效，需重新登录。"""

    current_password: str = Field(description="当前密码（用于验证身份）")
    new_password: str = Field(description="新密码（明文）")


# --- Provider Configs ---

class ProviderConfigCreate(StrictModel):
    """创建 LLM Provider 配置请求体（仅管理员可调用）。

    Provider 是全局共享的 LLM 服务配置，蒸馏（Distill）和自动回复（Autoreply）都会用到。
    每次创建新 Provider 时，旧的 is_default 会被自动取消，新 Provider 成为默认。
    base_url 必须在白名单中，否则返回 400。
    """

    name: str = Field(description="配置名称，便于人工识别（如 'GPT-4o 正式环境'）")
    base_url: str = Field(description="LLM 服务的 OpenAI 兼容接口根地址，必须在系统白名单中")
    api_key: Optional[str] = Field(description="API Key（可选，部分私有部署的服务不需要）")
    default_model: str = Field(description="默认使用的模型 ID，如 gpt-4o、qwen-max 等")


class ProviderConfigUpdate(StrictModel):
    """更新 LLM Provider 配置请求体（仅管理员可调用）。只传需要修改的字段。"""

    name: Optional[str] = Field(default=None, description="新名称")
    base_url: Optional[str] = Field(default=None, description="新接口根地址，必须在系统白名单中")
    api_key: Optional[str] = Field(default=None, description="新 API Key，传 null 可清除")
    default_model: Optional[str] = Field(default=None, description="新默认模型 ID")


# --- Personas ---

class PersonaCreate(StrictModel):
    """创建人设请求体。

    人设是 AI 回复时的角色定义，以 Markdown 格式描述性格、背景、说话风格等。
    同一账号下名称不可重复。
    """

    name: str = Field(description="人设名称，同一账号下唯一")
    persona_md: Optional[str] = Field(
        description="人设内容（Markdown 格式），描述 AI 的性格、背景、说话风格等。不传则为空。"
    )
    timezone: str = Field(
        default="UTC",
        description="人设所在时区（IANA 格式，如 Asia/Shanghai、UTC），影响 AI 感知的当前时间。必须是合法的时区名称，否则返回 422。",
    )


class PersonaUpdate(StrictModel):
    """更新人设请求体。只传需要修改的字段。"""

    name: Optional[str] = Field(default=None, description="新名称")
    persona_md: Optional[str] = Field(default=None, description="新人设内容，传 null 可清除")
    timezone: Optional[str] = Field(default=None, description="新时区（IANA 格式），必须合法")
    status: Optional[PersonaStatus] = Field(
        default=None,
        description="新状态：active（启用）/ archived（归档）。归档后无法被新的 Inbox 或 Contact 引用，但已引用的不受影响。",
    )


# --- Bridges (auto-provisioned daemons; users only ever read/revoke them) ---


# --- Inboxes (creation via bridge handshake only; no manual POST) ---


class InboxUpdate(StrictModel):
    """更新 Inbox 配置请求体。只传需要修改的字段。

    Inbox 代表一个平台账号（如某个微信号、飞书账号），由 Bridge 守护进程握手时自动创建，不支持手动创建。
    `reply_provider_config_id` 和 `clear_reply_provider` 仅管理员可修改。
    """

    display_name: Optional[str] = Field(default=None, description="新显示名称")
    default_persona_id: Optional[str] = Field(
        default=None,
        description="新接受消息时默认使用的人设 ID。新 Contact 创建时会继承此设置。",
    )
    bridge_id: Optional[str] = Field(
        default=None,
        description="重新绑定到指定 Bridge。通常无需手动操作，Bridge 握手时会自动更新。",
    )
    reply_provider_config_id: Optional[str] = Field(
        default=None,
        description="（仅管理员）为此 Inbox 指定专属的 LLM Provider，优先级高于全局默认 Provider。",
    )
    enabled: Optional[bool] = Field(
        default=None,
        description="是否启用自动回复功能。关闭后此 Inbox 下的联系人不会触发 AI 回复，但消息仍会正常存储。",
    )
    clear_bridge: Optional[bool] = Field(
        default=None, description="传 true 可解除与当前 Bridge 的绑定，使 Inbox 进入未绑定状态。"
    )
    clear_reply_provider: Optional[bool] = Field(
        default=None,
        description="（仅管理员）传 true 可清除 Inbox 级别的 Provider 覆盖，回退到全局默认 Provider。",
    )


# --- Contacts ---

class ContactUpdate(StrictModel):
    """更新 Contact 配置请求体。只传需要修改的字段。

    Contact 是平台上的一个对话方（如一个微信好友），在 Bridge 收到消息时自动创建。
    `reply_provider_config_id` 和 `clear_reply_provider` 仅管理员可修改。
    """

    display_name: Optional[str] = Field(default=None, description="新显示名称")
    card_md: Optional[str] = Field(
        default=None,
        description="联系人名片（Markdown 格式），用于向 AI 描述这个人的背景信息，辅助生成更准确的回复。传 null 可清除。",
    )
    persona_id: Optional[str] = Field(
        default=None,
        description="为此联系人单独指定使用的人设 ID，优先级高于 Inbox 的 default_persona_id。",
    )
    reply_provider_config_id: Optional[str] = Field(
        default=None,
        description="（仅管理员）为此联系人指定专属的 LLM Provider，优先级最高，高于 Inbox 级别和全局默认。",
    )
    clear_reply_provider: Optional[bool] = Field(
        default=None,
        description="（仅管理员）传 true 可清除 Contact 级别的 Provider 覆盖。",
    )
    takeover: Optional[bool] = Field(
        default=None,
        description="是否启用 AI 接管（即 AI 可以代发消息）。为 true 时 Bridge 会将此联系人的 peer_platform_id 加入 active-peers 列表。",
    )
    reply_policy: Optional[ReplyPolicy] = Field(
        default=None,
        description="自动回复策略：disabled（关闭，不自动回复）/ autoreply（开启，收到对方消息后自动触发 AI 生成回复）。",
    )
    status: Optional[ContactStatus] = Field(
        default=None,
        description="联系人状态：active（正常）/ archived（归档）。归档后不再触发自动回复。",
    )


# --- Distill Jobs ---

class DistillJobCreate(StrictModel):
    """创建蒸馏任务请求体。

    蒸馏（Distill）是指让 AI 读取指定联系人的历史消息，从中学习对话风格、用词习惯、常见话题等，
    并将提炼结果写入目标人设的 persona_md。
    同一联系人不能同时参与多个进行中的蒸馏任务，否则返回 409。
    """

    contact_ids: List[str] = Field(
        description="参与蒸馏的联系人 ID 列表（去重后处理）。不能为空，否则返回 422。"
    )
    target_persona_id: Optional[str] = Field(
        default=None,
        description="蒸馏结果写入的目标人设 ID。不传则由系统选择默认人设。该人设不能已有进行中的蒸馏任务。",
    )
    provider_config_id: Optional[str] = Field(
        default=None,
        description="（仅管理员）指定执行蒸馏时使用的 LLM Provider。不传则使用全局默认 Provider，若无可用 Provider 则返回 409。",
    )


# --- Manual outbound seed (debug / pre-LLM-brain) ---

class OutboundCreate(StrictModel):
    """手动创建待发消息请求体（调试 / 预设回复用）。

    将一条消息写入 outbound 队列，Bridge 会在下次轮询时取走并发送。
    主要用于测试 Bridge 发送链路，或在 AI 回复功能上线前手动预填回复。
    """

    contact_id: str = Field(description="目标联系人 ID，必须属于当前 Inbox")
    msg_type: OutboundMessageType = Field(
        default=OutboundMessageType.TEXT,
        description="消息类型：text / image / audio / video / file",
    )
    content: str = Field(description="消息内容。媒体消息填 storage key。")


# --- Bridge protocol (Bridge daemon ↔ Studio) ---

class BridgeHandshakeInbox(StrictModel):
    """Bridge 握手时上报的单个平台账号身份。"""

    platform: str = Field(description="平台名称，如 wechat、feishu、chat")
    platform_self_id: str = Field(description="本账号在该平台上的唯一 ID（如微信 ID、飞书 open_id）")


class BridgeHandshake(StrictModel):
    """Bridge 首次启动或 token 失效后的登录请求（密码换 token）。

    Bridge 用 Studio 账号密码完成登录，Studio 按 (account_id, machine_id) 查找或创建 Bridge 记录，
    销毁旧 session 并签发新 token。
    若不传 machine_id（首次启动），Studio 自动生成并在响应中返回，Bridge 应持久化保存，
    后续重启时带上，这样每台机器始终对应同一条 Bridge 记录。
    """

    username: str = Field(description="Studio 账号用户名")
    password: str = Field(description="Studio 账号密码（明文）")
    machine_id: str | None = Field(
        default=None,
        description="Bridge 所在机器的唯一 ID。首次启动不传，Studio 会生成并返回；此后每次重启都应带上，以复用同一个 Bridge 记录。",
    )


class BridgeRegisterInboxes(StrictModel):
    """Bridge 启动或频道变化后，注册/刷新当前服务的平台账号列表（需 token 鉴权）。

    Bridge 每次启动后用此接口告知 Studio 自己当前登录了哪些平台账号。
    Studio 按 (account_id, platform, platform_self_id) upsert Inbox，并绑定到当前 Bridge。
    响应中包含权威的 inbox 列表和 outbound 游标（Bridge 从游标之后开始拉取待发消息）。
    """

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
        description="平台侧的消息 ID（可选，仅供去重用）。同一 contact 下相同 platform_msg_id 的消息会被跳过。",
    )
    sender_id: str = Field(
        description="发送方在平台上的唯一 ID。用于判断消息方向：等于 inbox.platform_self_id 时 role=self，否则 role=counterpart。"
    )
    msg_type: str = Field(default="text", description="消息类型：text / image / audio / video / file")
    content: str = Field(
        description="消息内容。文本消息为正文；媒体消息为 Studio S3 的 storage key（需先通过 check-or-presign 上传）。"
    )
    content_hash: Optional[str] = Field(
        default=None,
        description='媒体文件的内容哈希，格式为 "sha256:{64位十六进制}"。文本消息不传。用于跨设备/跨重启的媒体去重（check-or-presign 接口依赖此值）。',
    )
    sent_at: datetime = Field(description="消息在平台上的发送时间（UTC），用于去重哈希计算和消息时间戳")


class BridgeIncomingBatch(StrictModel):
    """Bridge 批量上报入站消息的请求体。支持一次提交多条，Studio 逐条处理去重后写入。"""

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
    """申请媒体文件上传预签名的请求体（Bridge 侧直接上传到 Studio S3）。"""

    filename: str = Field(description="文件名（含扩展名），仅用于构造 storage key")
    mime_type: str = Field(description="文件 MIME 类型，如 image/jpeg")


class BridgeMediaCheckOrPresignRequest(StrictModel):
    """检查媒体文件是否已存在，若不存在则申请上传预签名。

    Bridge 在上传媒体前应先调此接口，避免相同内容重复上传。
    若 Studio 已有相同 content_hash 的文件，直接返回已有 storage_key，跳过上传。
    """

    content_hash: str = Field(
        description='文件内容哈希，格式为 "sha256:{64位十六进制}"，Bridge 本地计算后传入'
    )
    filename: str = Field(description="文件名（含扩展名）")
    mime_type: str = Field(description="文件 MIME 类型")


class BridgePeer(StrictModel):
    """Bridge 上报的单个对话方信息。"""

    peer_platform_id: str = Field(description="对话方在平台上的唯一 ID")
    display_name: str = Field(description="对话方的平台显示名称")


class BridgeReportPeers(StrictModel):
    """Bridge 批量上报对话方列表请求体（用于同步通讯录）。

    新联系人以 takeover=False、reply_policy=disabled 创建；
    已有联系人只更新 display_name，其他字段（takeover、reply_policy 等）保持不变。
    """

    inbox_id: str = Field(description="对话方所属的 Inbox ID")
    peers: list[BridgePeer] = Field(description="对话方列表")
