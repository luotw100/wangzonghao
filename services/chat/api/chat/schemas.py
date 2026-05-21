from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from chat.enums import AccountStatus, CommandStatus, MessageType


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class AccountRead(StrictModel):
    """账号信息（返回给客户端，不含密码）。"""

    id: str = Field(description="账号唯一 ID，前缀 'acct'")
    username: str = Field(description="登录用用户名，全局唯一，不可修改")
    nickname: str = Field(description="显示昵称，可通过 PATCH /api/auth/me 修改")
    status: AccountStatus = Field(description="账号状态：active（正常可用）/ disabled（已禁用，无法登录）")
    created_at: datetime = Field(description="账号创建时间（UTC）")
    updated_at: datetime = Field(description="账号最后更新时间（UTC）")


class AccountUpdate(StrictModel):
    """修改当前账号资料（目前仅支持改昵称）。"""

    nickname: str = Field(min_length=1, max_length=128, description="新昵称")


class LoginRequest(StrictModel):
    """登录请求体。"""

    username: str = Field(min_length=1, max_length=64, description="用户名")
    password: str = Field(min_length=1, max_length=256, description="明文密码（传输层走 HTTPS 加密）")


class LoginResponse(StrictModel):
    """登录成功响应，返回 session token 和账号信息。"""

    token: str = Field(
        description=(
            "Bearer token。后续所有需要鉴权的请求均需在 Header 中携带：Authorization: Bearer <token>。"
            "有效期 24 小时，每次鉴权成功后自动续期。"
        )
    )
    account: AccountRead = Field(description="当前登录账号的完整信息")


class ContactCreate(StrictModel):
    """创建联系人请求体。创建成功后，系统会自动为该联系人创建一个一对一会话。"""

    nickname: str = Field(min_length=1, max_length=256, description="联系人显示名称")
    username: str | None = Field(
        default=None,
        max_length=256,
        description=(
            "联系人的外部标识（如 chat ID）。同一账号下不可重复。"
            "若不传，系统会自动生成一个唯一 ID。"
        ),
    )
    remark_name: str | None = Field(
        default=None,
        max_length=256,
        description="备注名（可选）。仅对本账号可见，不影响联系人本身的 nickname。",
    )


class ContactUpdate(StrictModel):
    """更新联系人请求体（目前仅支持修改备注名）。"""

    remark_name: str | None = Field(
        default=None,
        max_length=256,
        description="新备注名。传 null 则清除备注。",
    )


class ContactRead(StrictModel):
    """联系人详情。联系人是账号私有数据，不同账号之间完全隔离。"""

    id: str = Field(description="联系人唯一 ID，前缀 'ct'")
    account_id: str = Field(description="所属账号 ID")
    username: str = Field(description="联系人的外部标识（如 chat ID），同账号下唯一")
    nickname: str = Field(description="联系人显示名称")
    remark_name: str | None = Field(description="本账号对该联系人的私有备注名，无备注时为 null")
    created_at: datetime = Field(description="创建时间（UTC）")
    updated_at: datetime = Field(description="最后更新时间（UTC）")


class ConversationRead(StrictModel):
    """一对一会话信息。每个联系人对应恰好一个会话（数据库有唯一约束）。"""

    id: str = Field(description="会话唯一 ID，前缀 'c'")
    account_id: str = Field(description="所属账号 ID")
    contact_id: str = Field(description="关联联系人 ID")
    title: str = Field(description="会话标题，默认等于联系人昵称，创建联系人时可自定义")
    created_at: datetime = Field(description="会话创建时间（UTC）")
    updated_at: datetime = Field(
        description="最后活跃时间（UTC）。每次发送消息后刷新，会话列表按此字段降序排列。"
    )
    contact: ContactRead = Field(description="关联联系人的完整信息")


class MessageSend(StrictModel):
    """批量发消息时单条消息的格式。"""

    sender_id: str | None = Field(
        default=None,
        max_length=48,
        description=(
            "发送方 ID（可选）。"
            "传 null 表示由当前账号本人发出；"
            "传联系人 ID 则表示该条消息由对方发出，用于导入对方历史消息。"
        ),
    )
    msg_type: MessageType = Field(
        default=MessageType.TEXT,
        description=(
            "消息类型：text（文本）/ image（图片）/ audio（音频）/ video（视频）/ file（文件）。"
            "非文本类型的 content 必须是通过 POST /api/uploads/presign 上传完成后的 storage key。"
        ),
    )
    content: str = Field(
        min_length=1,
        max_length=100_000,
        description=(
            "消息正文。"
            "文本消息填文字内容；"
            "媒体消息填上传后得到的 storage key（格式：media/{account_id}/{uuid}）。"
        ),
    )
    created_at: datetime | None = Field(
        default=None,
        description=(
            "消息时间戳（UTC）。"
            "不传则以服务器接收时间为准；"
            "传入可用于导入历史消息并保留原始发送时间。"
        ),
    )


class MessageSendRequest(StrictModel):
    """批量发消息请求体，支持一次提交多条，按顺序写入。"""

    messages: list[MessageSend] = Field(
        description="消息列表，按数组顺序依次写入数据库，写入后 ID 单调递增"
    )


class MessageRead(StrictModel):
    """单条消息详情（读取时返回）。"""

    id: int = Field(description="消息自增 ID，全局单调递增，可用作翻页游标")
    account_id: str = Field(description="所属账号 ID")
    conversation_id: str = Field(description="所属会话 ID")
    sender_id: str | None = Field(
        description="发送方 ID。null 表示账号本人发出；非 null 则为联系人 ID，表示对方发出。"
    )
    msg_type: MessageType = Field(description="消息类型")
    content: str = Field(
        description=(
            "消息内容。"
            "文本消息为正文；"
            "媒体消息为 storage key，需通过 GET /api/media/{storage_key} 换取实际访问 URL。"
        )
    )
    created_at: datetime = Field(description="消息时间戳（UTC）")


class ConversationMessages(StrictModel):
    """会话 + 消息列表，分页和长轮询接口的统一返回格式。"""

    conversation: ConversationRead = Field(description="会话信息")
    messages: list[MessageRead] = Field(
        description="按消息 ID 升序排列的消息列表（时间从旧到新）"
    )


class StatusResponse(StrictModel):
    """通用操作结果响应。"""

    status: CommandStatus = Field(description="操作结果：success（成功）")
    count: int | None = Field(
        default=None,
        description="受影响的记录数（如本次批量写入的消息条数），部分接口不返回此字段",
    )


class UploadPresignRequest(StrictModel):
    """申请媒体文件上传预签名的请求体。

    上传流程：
    1. POST /api/uploads/presign 获取 storage_key、upload_url 和 fields；
    2. 以 multipart/form-data 格式直接 POST 到 upload_url，把 fields 里的所有键值对都带上，
       最后附上文件二进制（key 为 'file'）；S3 返回 204 表示上传成功；
    3. 将 storage_key 填入消息的 content 字段，调用发消息接口即可。
    """

    filename: str = Field(
        min_length=1,
        max_length=256,
        description="文件名（含扩展名），仅用于生成 storage key，不影响实际存储路径",
    )
    mime_type: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "文件 MIME 类型，例如 image/jpeg、audio/mp4。"
            "注意：text/html、application/xhtml+xml、image/svg+xml 等可被浏览器直接渲染为活动内容的类型会被拒绝（防止存储型 XSS）。"
        ),
    )


class UploadPresignResponse(StrictModel):
    """媒体文件上传预签名响应。"""

    storage_key: str = Field(
        description=(
            "文件在 S3 的唯一存储路径，格式为 media/{account_id}/{uuid}。"
            "上传完成后，将此值填入消息的 content 字段发送。"
        )
    )
    upload_url: str = Field(
        description="S3 预签名上传地址，直接以 multipart/form-data 格式 POST 到此 URL"
    )
    fields: dict[str, str] = Field(
        description=(
            "必须随 multipart 表单一起提交的签名字段（含 key、policy、signature 等）。"
            "顺序无要求，但不可省略任何一项，否则 S3 会拒绝上传。"
        )
    )
