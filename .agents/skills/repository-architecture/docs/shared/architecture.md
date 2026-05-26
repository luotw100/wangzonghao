# Shared Architecture / 跨服务架构

## 产品模型

Laborster 当前代码实现的是一个私聊接管系统。当前业务聚焦主播-粉丝私聊保温，但代码命名保持中性：`Account`、`Inbox`、`Conversation`、`Persona`、`ProviderConfig`、`Bridge`。

系统目标不是通用问答，而是在私聊中保持拟人回复、关系延续和情绪价值。红线规则当前写在 `studio/reply.py` 的 `SYSTEM_INSTRUCTION` 中。

## 系统形态

```text
Channel / Chat platform
        ↕
Bridge daemon on operator PC
        ↕
Studio cloud control plane
```

- **Channel**：真实或模拟聊天平台。当前仓库中的实现是 `services/studio/api/chat/` 子包。
- **Bridge**：本地 IO daemon，持有平台登录态，负责收发消息。媒体消息走 S3 搬运（平台 S3 ↔ Studio S3）。
- **Studio**：云端控制面，持有账号、人设、Provider、消息历史、关系卡、蒸馏任务、回复决策和 outbound 队列。Studio S3 是媒体文件的唯一源。

## 服务边界

### Chat sandbox

`services/studio/api/chat/` 是 Studio 同进程的子包，当前用作可控 Channel（dogfood）。它包含自己的联系人、会话、消息（支持 text/image/audio/video/file 五种类型）、媒体上传下载（presigned URL 直连 S3）、long polling 和前端 UI。

Chat 与 Studio 之间没有代码 import（除共享 DB engine、auth deps 和 notify broker）；仅 Bridge 的 `ChatAdapter` 通过 HTTP 调用 `/api/chat/*`。

### Bridge CLI

`bridge/cli/` 是 Python 命令行 daemon（交互式 REPL + GUI 模式）。用户通过 `/login` 命令配置 Studio 账号密码，通过 `/channel add` 添加平台账号，state 持久化在本地 SQLite。后台 5 个循环线程在同进程运行，关掉进程即断线。

Bridge 当前负责：

- ChatAdapter 登录（复用 Studio session token 调用 Chat API）；
- StudioClient handshake 用密码换 account session token（与 web 共用 `auth_sessions`）；token + `X-Machine-Id` 头鉴权；
- live inbound 扫描（per-conversation 轮询 chat API）；
- SQLite 本地去重（`local_messages` 表，`UNIQUE(inbox_id, client_id)`）；
- upload pump 按 takeovers 集合过滤后批量推 `/api/bridge/incoming`；
- heartbeat（15s）；
- takeover watcher（10s）拉取需要接管的会话集合；
- outbound long-poll（30s）+ 发送；无 ack 端点，由 inbound from_self 自动标记 delivered。

Bridge 当前不负责：

- LLM 调用；
- Persona / Card 读取或存储；
- autoreply gating；
- distill；
- 回复内容策略。

### Studio

`services/studio` 是控制台和 AI brain。它提供 Web API（用户侧 + admin 侧）和 Bridge protocol API（8 个端点），存储消息历史，执行 reply 和 distill，并写入 outbound queue。

Studio 当前负责：

- Account auth（登录 / 登出 / 改自己密码）；
- Persona CRUD；
- Bridge 注册和撤销（DELETE `/api/bridges/{bridge_id}`）；
- Inbox 列表（Bridge 注册时 upsert）；
- Conversation 接管设置（takeover / reply_policy / persona_id / provider_id / card_md）；
- distill job create / worker execution；
- reply scanning / LLM call；
- outbound queue 管理。

## 核心实体与归属

```text
Account
  ├─ AuthSession (web 与 Bridge 共用，account 粒度)
  ├─ Persona
  ├─ Bridge
  ├─ Inbox
  │    ├─ Conversation (按 (inbox_id, platform_conversation_id) 唯一)
  │    │    ├─ ConversationMember(s)
  │    │    ├─ Message(s)
  │    │    └─ OutboundMessage(s)
  │    └─ persona_id / provider_id / card_md 在 Conversation 级别
  └─ DistillJob
       ├─ conversation_ids (JSONB)
       ├─ target Persona
       └─ resolved ProviderConfig (account.distill_provider_id)

ProviderConfig
        全局池，由 admin 通过 CLI 或 admin-api 维护；最早创建的为新 Conversation 默认
        Conversation.provider_id 控 reply LLM 路由
        Account.distill_provider_id 控 distill LLM 路由
```

### Account

Studio 登录账号，`status ∈ {active, disabled}`，无 role 列。账号只能用服务端 `studio.cli create-account`或 admin-api 开通；Web 端只有登录 / 登出 / 改自己密码。每个账号只能读写自己的数据。Web 与 Bridge 共用同一张 account 粒度 session 表。

### ProviderConfig

运维通过 admin-api 或 CLI 维护的 LLM Provider 配置，包含 `base_url`、`api_key`、`model`、`name`；最早创建的作为新 Conversation / 新 Account 的默认 Provider。`Conversation.provider_id` 控 reply LLM 路由，`Account.distill_provider_id` 控 distill LLM 路由。无系统级 fallback。

### Persona

可复用的人设 markdown。多个 Conversation 可以引用同一个 Persona。Distill pipeline 可以覆盖 `persona_md`。Persona 有 `timezone` 字段用于 reply prompt 时间上下文。

### Bridge

本地 daemon 注册行，由 `(account_id, machine_id)` 唯一标识。`machine_id` 由 Studio 在首次握手时生成（4 位随机 ID），Bridge 持久化到本地 SQLite `kv` 表后跨重启复用，并在每个 `/api/bridge/*` 请求带 `X-Machine-Id` 头供服务端解析本行。Handshake 按 `(account_id, machine_id)` upsert Bridge 行并签发 account session token（与 web 共用 `auth.auth_sessions`，不再有独立 bridge session 表）。

### Inbox

一个平台身份，例如一个 Chat account。Bridge 通过 `POST /api/bridge/inboxes` 注册，按 `(account_id, platform, platform_self_id)` 标识。Inbox 绑定一个 Bridge（`bridge_id` 可空）。

### Conversation

接管单元，属于一个 Inbox，对应平台里的一个会话（DM 或 Group）。Conversation 保存 `kind`（dm/group/unknown）、`display_name`、`card_md`（关系卡 Markdown）、`persona_id` 引用、`provider_id`（reply LLM 路由）、`takeover`（Bridge 是否上报消息）、`reply_policy`（`disabled | autoreply`）、`status`（`active | archived`）和 `last_reply_round_at`。`/api/bridge/incoming` 到达时若该 Conversation 行不存在则自动创建 kind='unknown' 的占位行，等 `/api/bridge/conversations` 推送元数据后补全。

### Message

Studio `messages` 表保存全部消息历史，全部由 Bridge incoming 写入。按 `(conversation_id, client_id)` 去重。`sender_id` 为 NULL 表示 Inbox 自己发出（from_self），非 NULL 为对方平台 ID。`msg_type` 是 `text | image | audio | video | file`。

### OutboundMessage

Studio → Bridge 的工作队列表。每条 OutboundMessage 是一条独立的待发送消息，包含 `msg_type`、`content`、`send_after`（打字节奏控制）、`status`（`pending | delivered | failed | canceled`）。Bridge long-poll 拉取 pending 行；发送后 Bridge 上报 from_self inbound，Studio 按 `(conversation_id, content)` 自动匹配并标记 delivered，无需 ack 端点。

## 媒体数据所有权

Studio S3 是媒体 binary 的唯一 source of truth。Inbound 时 Bridge 从平台 S3 下载 → 上传到 Studio S3 → 入站消息的 `content` 为 Studio storage key。Outbound 时 Studio 的 `content` 指向 Studio S3 storage key → Bridge 下载 → 上传到平台 S3 → 发送。

## 配置原则在当前代码中的体现

- Chat 需要 `DATABASE_URL`、`S3_ENDPOINT`、`S3_PUBLIC_URL`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`、`UPLOAD_MAX_SIZE_MB` 环境变量，缺失时报错。`S3_ENDPOINT` 是容器内地址，`S3_PUBLIC_URL` 是浏览器可达地址，两者不同因为 presigned URL 签名绑定 host。
- Studio 需要 `DATABASE_URL`、`S3_ENDPOINT`、`S3_PUBLIC_URL`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET` 环境变量，缺失时报错。
- Chat 和 Studio models 当前不使用 SQLAlchemy column default。
- Studio 和 Chat 使用 PostgreSQL，由 Alembic 管理 schema 迁移。
- Bridge CLI 的 Studio 地址在 `bridge/cli/laborster_bridge/config.py` 硬编码为 `https://studio.laborster.com`，Chat 沙箱同主机路径加 `/api/chat` 前缀，无环境变量、无默认覆盖。