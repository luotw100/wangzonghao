"""Studio data model.

Principles:
- No SQLAlchemy column-level defaults. Every INSERT must pass every field
  explicitly. The schema enforces NOT NULL; the application enforces values.
- Persona, Inbox, Bridge are independent entities. Persona is content
  (markdown). Inbox is a logical platform-side identity; Bridge is the
  daemon process that physically runs adapters. An Inbox is bound to one
  Bridge (Inbox.bridge_id) and a Bridge can serve N inboxes.
- ProviderConfig is operator-maintained, managed via the server-side CLI.
  Routing is explicit: each Conversation owns a provider_id (used by
  reply), each Account owns a distill_provider_id (used by distill). No
  system default / fallback. New conversations and accounts are seeded
  with the earliest-created provider; if no provider exists, creation
  fails.
- The takeover unit is **Conversation**, not peer. A DM is a Conversation
  with kind="dm" and one ConversationMember; a group chat is a
  Conversation with kind="group" and N members. The same takeover /
  reply_policy / persona / provider settings apply uniformly.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from studio.db import Base


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class Account(Base):
    """Studio 用户账号。

    每个账号拥有自己的 Persona / Inbox / Bridge / DistillJob 等资源，彼此完全隔离。
    distill_provider_id 指向该账号所有蒸馏任务使用的 LLM Provider，
    由 CLI `create-account` 时绑定（取最新创建的 Provider），运营手动维护。
    """

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="ck_account_status"),
        {"schema": "auth"},
    )

    id                  = Column(String(48),  primary_key=True, index=True)
    username            = Column(String(64),  nullable=False, unique=True, index=True)
    password_hash       = Column(String(128), nullable=False)
    display_name        = Column(String(128), nullable=False)
    status              = Column(String(16),  nullable=False)   # active / disabled
    # 账号级蒸馏 LLM 路由；reply 使用 Conversation.provider_id，互不影响
    distill_provider_id = Column(String(48),  ForeignKey("studio.provider_configs.id"), nullable=False, index=True)
    created_at          = Column(DateTime(timezone=True), nullable=False)
    updated_at          = Column(DateTime(timezone=True), nullable=False)

    distill_provider    = relationship("ProviderConfig", foreign_keys=[distill_provider_id])


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = ({"schema": "auth"},)

    id           = Column(String(64), primary_key=True, index=True)
    account_id   = Column(String(48), ForeignKey("auth.accounts.id"), nullable=False, index=True)
    expires_at   = Column(DateTime(timezone=True), nullable=False)
    created_at   = Column(DateTime(timezone=True), nullable=False)

    account      = relationship("Account")


# ---------------------------------------------------------------------------
# LLM provider pool
# ---------------------------------------------------------------------------

class ProviderConfig(Base):
    """LLM Provider 配置。

    由运营通过 CLI `create-provider` 创建并维护，Web 端无增删 API。
    最新创建的那条作为新账号/新会话的默认 Provider（pick_first_provider 取 created_at 最早的）。
    base_url + model 决定具体调用哪个 API；api_key 为空时由运营在服务侧配置认证。
    """

    __tablename__ = "provider_configs"
    __table_args__ = (
        UniqueConstraint("name", name="uq_provider_name"),
        {"schema": "studio"},
    )

    id         = Column(String(48),  primary_key=True, index=True)
    name       = Column(String(128), nullable=False)
    base_url   = Column(String(512), nullable=False)   # OpenAI-compatible API 地址
    api_key    = Column(Text,        nullable=True)    # 可为空（服务端环境变量注入）
    model      = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Persona
# ---------------------------------------------------------------------------

class Persona(Base):
    """人设（AI 扮演的角色设定）。

    persona_md 是 Markdown 格式的人设正文，作为 LLM reply 的 system prompt 核心内容。
    timezone 用于在 reply prompt 中生成"当前时间"上下文，格式为 IANA 时区名（如 Asia/Shanghai）。
    蒸馏任务可以把从对话中提炼的人设写回到 target_persona_id 指向的 Persona。
    同一账号下 name 唯一。
    """

    __tablename__ = "personas"
    __table_args__ = (
        UniqueConstraint("account_id", "name", name="uq_persona_account_name"),
        {"schema": "studio"},
    )

    id         = Column(String(48),  primary_key=True, index=True)
    account_id = Column(String(48),  ForeignKey("auth.accounts.id"), nullable=False, index=True)
    name       = Column(String(128), nullable=False)
    persona_md = Column(Text,        nullable=False)   # 人设 Markdown，作为 LLM system prompt
    timezone   = Column(String(64),  nullable=False)   # IANA 时区，用于生成 reply 时间上下文
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Bridge — registered daemon, keyed by (account_id, machine_id). Studio
# generates the machine_id on first handshake; the bridge persists and sends
# it via X-Machine-Id thereafter.
# ---------------------------------------------------------------------------

class Bridge(Base):
    """Bridge 守护进程注册记录，按 (account_id, machine_id) 唯一标识。

    machine_id 由 Studio 在首次握手时生成（4 位随机字母数字），Bridge 本地持久化后
    每次请求通过 X-Machine-Id 头携带。last_seen_at 由心跳和消息上报刷新，
    Studio 用 last_seen_at 派生在线/离线状态（超过 45 秒视为离线）。
    删除 Bridge 行相当于撤销该守护进程；下次握手会重新签发 machine_id。
    """

    __tablename__ = "bridges"
    __table_args__ = (
        UniqueConstraint("account_id", "machine_id", name="uq_bridge_account_machine_id"),
        {"schema": "studio"},
    )

    id           = Column(String(48),  primary_key=True, index=True)
    account_id   = Column(String(48),  ForeignKey("auth.accounts.id"), nullable=False, index=True)
    machine_id   = Column(String(256), nullable=False)          # Studio 签发的 4 位短 ID
    last_seen_at = Column(DateTime(timezone=True), nullable=False)   # 心跳/上报时刷新，派生在线状态
    created_at   = Column(DateTime(timezone=True), nullable=False)
    updated_at   = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Inbox — a platform-side identity (one chat user / one wxid / one feishu
# open_id ...). An inbox without bridge_id is unbound.
# ---------------------------------------------------------------------------

class Inbox(Base):
    """平台账号身份（如一个 Chat 用户、一个微信号）。

    Inbox 由 Bridge 握手时通过 POST /api/bridge/inboxes 自动注册，无面向用户的创建 API。
    bridge_id 为 NULL 时表示未绑定守护进程（Inbox 存在但当前无法收发）。
    platform_self_id 是该账号在平台上的唯一 ID（用于区分消息是否为"自己发出"）。
    display_name 由 Bridge 从平台侧读取并在每次注册时刷新。
    """

    __tablename__ = "inboxes"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('chat', 'wechat', 'feishu')", name="ck_inbox_platform"
        ),
        {"schema": "studio"},
    )

    id               = Column(String(48),  primary_key=True, index=True)
    account_id       = Column(String(48),  ForeignKey("auth.accounts.id"),  nullable=False, index=True)
    bridge_id        = Column(String(48),  ForeignKey("studio.bridges.id"), nullable=True,  index=True)  # NULL=未绑定
    platform         = Column(String(32),  nullable=False)             # chat / wechat / feishu
    display_name     = Column(String(256), nullable=False)             # 平台侧真实昵称，Bridge 注册时写入
    platform_self_id = Column(String(128), nullable=True)              # 本账号在平台的唯一 ID
    created_at       = Column(DateTime(timezone=True), nullable=False)
    updated_at       = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Conversation + members. Identity is (inbox_id, platform_conversation_id);
# kind distinguishes DM vs group. ConversationMember rows describe who's in
# the conversation — for kind="dm" there's exactly one member (the peer);
# for kind="group" there's N. The placeholder kind="unknown" is allowed
# while waiting for /api/bridge/conversations to fill in the metadata.
# ---------------------------------------------------------------------------

class Conversation(Base):
    """接管单元——Studio 对一个平台会话的全部配置和状态。

    身份由 (inbox_id, platform_conversation_id) 唯一确定。Bridge 上报消息时
    若该行不存在，Studio 会先创建 kind='unknown' 的占位行，等 /conversations 推送后再补全。

    接管开关与自动回复：
      takeover=True  → Bridge 将该会话的消息上报给 Studio（接管开启）
      reply_policy=autoreply + persona_id 非空 → ReplyScanner 触发 LLM 自动回复

    LLM 路由：
      provider_id  → 该会话的 reply LLM Provider（Conversation 级别，可独立配置）
      persona_id   → 指定人设；NULL 时 ReplyScanner 跳过该会话
      card_md      → 对方的用户画像 Markdown，拼入 reply system prompt 以个性化回复
    """

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "inbox_id", "platform_conversation_id",
            name="uq_conversation_inbox_pcid",
        ),
        CheckConstraint("kind IN ('dm', 'group', 'unknown')", name="ck_conversation_kind"),
        CheckConstraint("status IN ('active', 'archived')", name="ck_conversation_status"),
        CheckConstraint(
            "reply_policy IN ('disabled', 'autoreply')",
            name="ck_conversation_reply_policy",
        ),
        {"schema": "studio"},
    )

    id                       = Column(String(48),  primary_key=True, index=True)
    inbox_id                 = Column(String(48),  ForeignKey("studio.inboxes.id"),          nullable=False, index=True)
    platform_conversation_id = Column(String(256), nullable=False)   # 平台侧原始会话 ID（DM=对方 ID，群=群 ID）
    kind                     = Column(String(16),  nullable=False)   # dm / group / unknown（占位时为 unknown）
    display_name             = Column(String(256), nullable=False)   # DM=对方昵称，群=群名
    card_md                  = Column(Text,        nullable=False)   # 对方用户画像 Markdown，拼入 reply system prompt
    persona_id               = Column(String(48),  ForeignKey("studio.personas.id"),         nullable=True)   # NULL=不自动回复
    provider_id              = Column(String(48),  ForeignKey("studio.provider_configs.id"), nullable=False)  # reply LLM 路由
    takeover                 = Column(Boolean,     nullable=False)   # True=Bridge 上报该会话消息到 Studio
    reply_policy             = Column(String(16),  nullable=False)   # disabled / autoreply
    status                   = Column(String(16),  nullable=False)   # active / archived
    last_reply_round_at      = Column(DateTime(timezone=True), nullable=True)   # 上次 LLM 回复时间，用于安静期检查
    created_at               = Column(DateTime(timezone=True), nullable=False)
    updated_at               = Column(DateTime(timezone=True), nullable=False)

    provider = relationship("ProviderConfig", foreign_keys=[provider_id])
    members  = relationship(
        "ConversationMember",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )


class ConversationMember(Base):
    """Member of a conversation on the platform side.

    For DMs there's exactly one row (the peer). For groups, N rows. The
    bridge upserts via POST /api/bridge/conversations; Studio never mutates
    this table from elsewhere.
    """
    __tablename__ = "conversation_members"
    __table_args__ = ({"schema": "studio"},)

    conversation_id  = Column(
        String(48),
        ForeignKey("studio.conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    peer_platform_id = Column(String(256), primary_key=True)
    display_name     = Column(String(256), nullable=False)
    updated_at       = Column(DateTime(timezone=True), nullable=False)


class Message(Base):
    """Studio 消息记录，是全部聊天历史的 source of truth。

    由 Bridge 通过 POST /api/bridge/incoming 批量写入，Studio 自身不直接写消息。
    client_id 是 Bridge 侧稳定唯一标识（各平台 adapter 自行决定格式），
    按 (conversation_id, client_id) 去重，保证同一条消息不重复入库。
    sender_id 为 NULL 表示 Inbox 自己发出（from_self）；非 NULL 为对方平台 ID。
    """

    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_msg_conversation_ts", "conversation_id", "timestamp"),
        UniqueConstraint(
            "conversation_id", "client_id", name="uq_message_conv_client",
        ),
        CheckConstraint(
            "msg_type IN ('text', 'image', 'audio', 'video', 'file')",
            name="ck_message_msg_type",
        ),
        {"schema": "studio"},
    )

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(String(48),  ForeignKey("studio.conversations.id"), nullable=False, index=True)
    # Bridge 侧稳定唯一 ID；chat adapter 用平台 msg.id，其他 adapter 用平台原生 msg_id
    client_id       = Column(String(256), nullable=False)
    # NULL = Inbox 自己发出（即主播从其他客户端发的消息被 Bridge 观察并上报）
    sender_id       = Column(String(256), nullable=True)
    msg_type        = Column(String(16),  nullable=False)   # text / image / audio / video / file
    content         = Column(Text,        nullable=False)   # 文本正文 或 Studio S3 storage key
    timestamp       = Column(DateTime(timezone=True), nullable=False, index=True)   # 平台侧原始发送时间
    created_at      = Column(DateTime(timezone=True), nullable=False)


class DistillJob(Base):
    """蒸馏任务（从对话历史中提炼人设）。

    由 POST /api/distill-jobs 创建，DistillScanner 异步执行。
    同一时刻同一会话或同一目标人设只能有一个进行中的任务（pending 或 running），
    创建时会检查冲突。
    target_persona_id=NULL 表示仅预览，不写回人设；非 NULL 则将蒸馏结果写入该 Persona。
    progress 是 JSONB，由 pipeline 分段回写，供前端轮询进度条用。
    """

    __tablename__ = "distill_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed')",
            name="ck_distill_status",
        ),
        {"schema": "studio"},
    )

    id                 = Column(String(48), primary_key=True, index=True)
    account_id         = Column(String(48), ForeignKey("auth.accounts.id"),          nullable=False, index=True)
    conversation_ids   = Column(JSONB,      nullable=False)              # JSONB 字符串数组，参与蒸馏的会话 ID
    target_persona_id  = Column(String(48), ForeignKey("studio.personas.id"),        nullable=True,  index=True)  # NULL=不写回
    provider_config_id = Column(String(48), ForeignKey("studio.provider_configs.id"),nullable=False, index=True)
    status             = Column(String(16), nullable=False)              # pending → running → done / failed
    progress           = Column(JSONB,      nullable=False)              # pipeline 进度快照，供前端轮询
    error_message      = Column(Text,       nullable=False)              # 失败原因，成功时为空字符串
    created_at         = Column(DateTime(timezone=True), nullable=False)
    started_at         = Column(DateTime(timezone=True), nullable=True)  # DistillScanner 开始执行时写入
    finished_at        = Column(DateTime(timezone=True), nullable=True)  # done 或 failed 时写入

    provider           = relationship("ProviderConfig", foreign_keys=[provider_config_id])


# ---------------------------------------------------------------------------
# OutboundMessage — Studio→Bridge work queue. No state on the bridge side:
# bridge long-polls for status=pending and dispatches; Studio flips status
# to delivered when an /incoming message from_self matches by (conversation,
# content). Permanent failure has no reverse channel in v2 — failed sends
# stay pending until admin cleanup.
# ---------------------------------------------------------------------------

class OutboundMessage(Base):
    """Studio → Bridge 发送队列，是 AI 回复消息的最终出口。

    由 ReplyBrain（自动回复）或 POST /api/conversations/{id}/outbound（手动）写入，
    Bridge 通过 GET /api/bridge/outbound 长轮询拉取。

    状态机：
      pending   → delivered  Bridge 发送后，inbound from_self 自动 ack（无显式 ack 接口）
      pending   → canceled   Inbox/Bridge 被删除时批量标记取消
      pending   → failed     （保留值，当前无自动置 failed 逻辑，永久失败留 pending 待运营清理）

    send_after 是打字节奏模拟时间：ReplyBrain 按字数计算延迟写入，Bridge 到时才拉取到该行。
    ⚠ id 是自增插入顺序，与 send_after / created_at 无强关联——多条回复消息的 id 顺序
    即为发送顺序，但 id 本身不代表任何时间语义。
    """

    __tablename__ = "outbound_messages"
    __table_args__ = (
        Index("idx_outbound_inbox_id", "inbox_id", "id"),
        Index("idx_outbound_send_after", "status", "send_after"),
        Index("idx_outbound_conv_created", "conversation_id", "created_at"),
        CheckConstraint(
            "status IN ('pending', 'delivered', 'failed', 'canceled')",
            name="ck_outbound_status",
        ),
        CheckConstraint(
            "msg_type IN ('text', 'image', 'audio', 'video', 'file')",
            name="ck_outbound_msg_type",
        ),
        {"schema": "studio"},
    )

    id              = Column(BigInteger, primary_key=True, autoincrement=True)  # 插入顺序，≠ 时间顺序
    inbox_id        = Column(String(48), ForeignKey("studio.inboxes.id"),        nullable=False, index=True)
    conversation_id = Column(String(48), ForeignKey("studio.conversations.id"),  nullable=False, index=True)
    msg_type        = Column(String(16), nullable=False)
    content         = Column(Text,       nullable=False)
    send_after      = Column(DateTime(timezone=True), nullable=False)   # 打字节奏：到此时刻才对 Bridge 可见
    status          = Column(String(16), nullable=False)                # pending / delivered / failed / canceled
    delivered_at    = Column(DateTime(timezone=True), nullable=True)    # inbound from_self ack 时写入
    failed_reason   = Column(Text,       nullable=False)                # 失败原因，成功或 pending 时为空字符串
    created_at      = Column(DateTime(timezone=True), nullable=False)


class HostedBridge(Base):
    """Cloud-hosted bridge: a chat-only bridge subprocess spawned by the
    operator (via admin panel) for dogfood. One row per account.

    Lifecycle is admin-driven; bridge-host service executes the actual
    subprocess. ``session_id`` is the hash of the AuthSession token
    admin-api minted for the spawned process so we can revoke exactly
    that session on stop without touching the user's web sessions.

    machine_id points at a ``studio.bridges.machine_id`` row scoped to
    the same account; soft reference (no FK) — deleting the Bridge row
    just means the next start will mint a fresh one.
    """

    __tablename__ = "hosted_bridges"
    __table_args__ = (
        CheckConstraint(
            "status IN ('stopped', 'starting', 'running', 'auth_error', 'crashed')",
            name="ck_hosted_bridge_status",
        ),
        {"schema": "studio"},
    )

    account_id      = Column(String(48), ForeignKey("auth.accounts.id"), primary_key=True)
    status          = Column(String(16), nullable=False)
    machine_id      = Column(String(256), nullable=True)
    session_id      = Column(String(64),  nullable=True)   # hash_token(token) — the row in auth.auth_sessions
    last_started_at = Column(DateTime(timezone=True), nullable=True)
    last_error      = Column(Text,        nullable=False)  # "" when none
    created_at      = Column(DateTime(timezone=True), nullable=False)
    updated_at      = Column(DateTime(timezone=True), nullable=False)


class LlmLog(Base):
    """Audit log of LLM round-trips. Bare string FKs (no cascade) preserve
    history even if personas/inboxes are deleted.
    """

    __tablename__ = "llm_logs"
    __table_args__ = (
        CheckConstraint("purpose IN ('distill', 'reply')", name="ck_llm_log_purpose"),
        {"schema": "studio"},
    )

    id                  = Column(BigInteger, primary_key=True, autoincrement=True)
    purpose             = Column(String(16), nullable=False)
    persona_id          = Column(String(48), nullable=True, index=True)
    inbox_id            = Column(String(48), nullable=True, index=True)
    conversation_id     = Column(String(48), nullable=True, index=True)
    distill_job_id      = Column(String(48), nullable=True, index=True)
    outbound_message_id = Column(BigInteger, nullable=True)
    window_index        = Column(Integer,    nullable=True)
    windows_total       = Column(Integer,    nullable=True)
    latency_ms          = Column(Integer,    nullable=True)
    prompt_tokens       = Column(Integer,    nullable=True)
    completion_tokens   = Column(Integer,    nullable=True)
    is_error            = Column(Boolean,    nullable=True)
    persona_md_snapshot = Column(Text,       nullable=True)
    card_md_snapshot    = Column(Text,       nullable=True)
    persona_md_after    = Column(Text,       nullable=True)
    card_md_after       = Column(Text,       nullable=True)
    request_messages    = Column(Text,       nullable=False)
    response_raw        = Column(Text,       nullable=False)
    model               = Column(String(128), nullable=True)
    created_at          = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Desktop app distribution
# ---------------------------------------------------------------------------

class Release(Base):
    """A published desktop-app installer, one row per (version, platform).

    Catalog + "what's current" pointer in one table: the download endpoint
    serves the single row with is_latest=True for the requested platform.
    A partial unique index (ix_releases_latest_per_platform) guarantees at
    most one latest per platform; publishing a new version flips the old
    row's is_latest off and the new one's on in a single transaction, which
    is also the rollback switch. Installer bytes live in S3 under
    releases/<version>/<filename>; this table never holds the binary.
    """

    __tablename__ = "releases"
    __table_args__ = (
        CheckConstraint("platform IN ('win', 'mac')", name="ck_release_platform"),
        UniqueConstraint("version", "platform", name="uq_release_version_platform"),
        Index(
            "ix_releases_latest_per_platform", "platform",
            unique=True, postgresql_where=Column("is_latest"),
        ),
        {"schema": "studio"},
    )

    id           = Column(String(48),  primary_key=True, index=True)
    version      = Column(String(32),  nullable=False)
    platform     = Column(String(16),  nullable=False)
    s3_key       = Column(String(512), nullable=False)
    filename     = Column(String(256), nullable=False)
    sha256       = Column(String(64),  nullable=False)
    size_bytes   = Column(BigInteger,  nullable=False)
    notes        = Column(Text,        nullable=True)
    is_latest    = Column(Boolean,     nullable=False)
    created_at   = Column(DateTime(timezone=True), nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False)


class DownloadEvent(Base):
    """Audit log: one row per successful presigned-download handout.

    Bare string account_id (no FK cascade) so the trail survives account
    deletion. ip / user_agent come from the edge-forwarded request headers.
    """

    __tablename__ = "download_events"
    __table_args__ = ({"schema": "studio"},)

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    account_id  = Column(String(48),  nullable=True, index=True)
    version     = Column(String(32),  nullable=False)
    platform    = Column(String(16),  nullable=False)
    ip          = Column(String(64),  nullable=True)
    user_agent  = Column(Text,        nullable=True)
    created_at  = Column(DateTime(timezone=True), nullable=False, index=True)
