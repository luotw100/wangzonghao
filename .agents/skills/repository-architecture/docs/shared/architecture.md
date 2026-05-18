# Shared Architecture / 跨服务架构

## 产品模型

Laborster 当前代码实现的是一个私聊接管系统。当前业务聚焦主播-粉丝私聊保温，但代码命名保持中性：`Account`、`Inbox`、`Contact`、`Persona`、`ProviderConfig`、`Bridge`。

系统目标不是通用问答，而是在私聊中保持拟人回复、关系延续和情绪价值。红线规则当前写在 `studio/reply.py` 的 `SYSTEM_INSTRUCTION` 中。

## 系统形态

```text
Channel / Chat platform
        ↕
Bridge daemon on operator PC
        ↕
Studio cloud control plane
```

- **Channel**：真实或模拟聊天平台。当前仓库中的实现是 `services/chat`。
- **Bridge**：本地 IO daemon，持有平台登录态，负责收发消息、搬运媒体二进制数据（平台 S3 ↔ Studio S3）。
- **Studio**：云端控制面，持有账号、人设、Provider、消息历史、关系卡、蒸馏任务、回复决策和 outbound 队列。Studio S3 是媒体文件的唯一源（source of truth）。

## 服务边界

### Chat sandbox

`services/chat` 是独立聊天应用，当前用于作为可控 Channel。它包含自己的账号、auth session、联系人、会话、消息（支持 text/image/audio/video/file 五种类型）、媒体上传下载（presigned URL 直连 S3）、导入、long polling 和前端 UI。

Studio 与 Chat 之间没有代码 import 和直接 API 调用；仅 Bridge 的 `ChatAdapter` 通过 HTTP 调用 Chat。

### Bridge CLI

`bridge/cli/` 是 Python 命令行 daemon（交互式 REPL，进程本身即 daemon；唯一三方依赖 prompt_toolkit 仅交互模式用，其余 stdlib）。用户在黑框框里用 slash 命令配置 Studio 账号和 chat channel 凭据，6 个后台循环线程在同进程运行，关掉进程即断线。

Bridge 当前负责：

- ChatAdapter 登录（HTTP POST `/api/auth/login`）；
- StudioClient handshake 用密码换 account session token（与 web 共用 `auth_sessions`）；token + `X-Machine-Id` 头鉴权 `POST /api/bridge/inboxes` 注册 channel 拿 Inbox 映射；
- live inbound 扫描（per-inbox async generator 轮询 chat API）；
- SQLite 本地去重（`local_messages` 表，`UNIQUE(inbox_id, local_hash)`）；
- consumer 按 activePeers 过滤后批量推 `/api/bridge/incoming`；
- heartbeat（15s）；
- announce peers（60s）；
- active-peers 拉取（10s）；
- outbound long-poll（30s）+ text 发送 + ack。

Bridge 当前不负责：

- LLM 调用；
- Persona / Card 读取或存储；
- autoreply gating；
- distill；
- 回复内容策略；
- 媒体 S3 搬运（outbound media 返回 failed，chat sandbox 实践上只发 text）。

### Studio

`services/studio` 是控制台和 AI brain。它提供 Web API 和 Bridge protocol API（含 media presign upload / download 端点），存储消息历史，执行 reply 和 distill，并写入 outbound queue。

Studio 当前负责：

- Account auth（仅登录 / 登出 / 改自己密码）；
- Persona CRUD；
- Bridge auto-registration 和 revoke；
- Inbox list/default settings；
- Contact takeover settings；
- distill job create / worker execution；
- reply scanning / LLM call；
- outbound queue 管理；
- Bridge media presign-upload 和 media serve 端点。

## 核心实体与归属

```text
Account
  ├─ AuthSession (web 与 Bridge 共用，account 粒度)
  ├─ Persona
  ├─ Bridge
  ├─ Inbox
  │    ├─ Contact
  │    │    ├─ Message
  │    │    └─ OutboundMessage
  │    └─ default Persona ref
  └─ DistillJob
       ├─ source Inbox
       ├─ target Persona
       └─ resolved ProviderConfig (恒为全局默认)

ProviderConfig
        单个全局配置，无 owner，由服务端 CLI 维护
```

### Account

Studio 登录账号，无角色概念（没有 admin）。账号只能用服务端 `studio.cli create-account` 开通；Web 端只有登录 / 登出 / 改自己密码。每个账号只能读写自己的数据。Web 与 Bridge 共用同一张 account 粒度 session 表。

### ProviderConfig

运维通过 `studio.cli create-provider` 维护的单个全局 LLM Provider 配置，包含 `base_url`、`api_key`、`default_model`、`scope`、`status`、`is_default`；最新创建者成为唯一默认。没有 per-Inbox / per-Contact override，reply/distill 恒用全局默认 Provider。

### Persona

可复用的人设 markdown。多个 Inbox/Contact 可以引用同一个 Persona。Distill pipeline 可以覆盖 `persona_md`。

### Bridge

本地 daemon 注册行，由 `(account_id, machine_id)` 唯一标识。`machine_id` 由 Studio 在首次握手时生成并返回，Bridge 持久化后跨重启复用，并在每个 `/api/bridge/*` 请求带 `X-Machine-Id` 头供服务端解析本行。Handshake upsert Bridge 并签发 account session token（与 web 共用，不再有独立 bridge session）。

### Inbox

一个平台身份，例如一个 Chat account。Handshake 按 `(account_id, platform, platform_self_id)` upsert Inbox。Inbox 可以绑定一个 Bridge，并保存默认 Persona。

### Contact

接管单元，属于一个 Inbox，对应平台里的一个 peer。Contact 保存 display name、关系卡、Persona 引用、`takeover`（Bridge 是否上报消息）、`reply_policy`（`disabled | autoreply`，Studio 是否自动回复）、`pending_reply` flag 和 status。

### Message

Studio `messages` 表保存全部消息历史，全部由 Bridge incoming 写入。按 `(contact_id, external_id)` 去重。`role` 是 `self | counterpart`，`msg_type` 是 `text | image | audio | video | file`。

### OutboundMessage

Studio → Bridge 的工作队列表。每条 OutboundMessage 是一条独立的待发送消息，包含 `msg_type`、`content`、`send_after`（打字节奏控制）、状态、投递/失败信息。Bridge 通过 cursor 消费并 ack。

## 媒体数据所有权

Studio S3 是媒体 binary 的唯一 source of truth。Inbound 时 Bridge 从平台 S3 下载 → 上传到 Studio S3 → 入站消息的 `content` 为 Studio storage key。Outbound 时 Studio 的 `content` 指向 Studio S3 storage key → Bridge 下载 → 上传到平台 S3 → 发送。

## 配置原则在当前代码中的体现

- Chat 需要 `DATABASE_URL`、`S3_ENDPOINT`、`S3_PUBLIC_URL`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`、`UPLOAD_MAX_SIZE_MB` 环境变量，缺失时报错。`S3_ENDPOINT` 是容器内地址，`S3_PUBLIC_URL` 是浏览器可达地址，两者不同因为 presigned URL 签名绑定 host。
- Studio 需要 `DATABASE_URL`、`S3_ENDPOINT`、`S3_PUBLIC_URL`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET` 环境变量，缺失时报错。`S3_PUBLIC_URL` 用于生成 Bridge 媒体端点的 presigned URL。
- Chat 和 Studio models 当前不使用 SQLAlchemy column default。
- Studio 和 Chat 使用 PostgreSQL，由 Alembic 管理 schema 迁移。
- Bridge CLI 的 Chat/Studio 地址在 `bridge/cli/laborster_bridge/config.py` 硬编码为 `https://chat.laborster.com` / `https://studio.laborster.com`，无 base-URL 输入、无环境变量、无默认覆盖。
