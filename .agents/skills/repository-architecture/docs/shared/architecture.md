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

### Bridge daemon

`services/bridge` 是 Python asyncio daemon。它从 CLI 接收 Studio 登录信息和平台登录 claim，先登录平台拿到 `platform_self_id`，再向 Studio handshake 获取 Bridge session token 和 Inbox 映射。

Bridge 当前负责：

- adapter 登录；
- initial catch-up；
- live inbound streaming（含 media 下载 + 上传到 Studio S3）；
- 批量推送 `/api/bridge/incoming`；
- heartbeat；
- outbound long polling（含 media 从 Studio S3 下载 + 推到平台）；
- 平台发送和 ack。

Bridge 当前不负责：

- LLM 调用；
- Persona / Card 读取或存储；
- autoreply gating；
- distill；
- 回复内容策略；
- media 缓存。

### Studio

`services/studio` 是控制台和 AI brain。它提供 Web API 和 Bridge protocol API（含 media presign upload / download 端点），存储消息历史，执行 reply 和 distill，并写入 outbound queue。

Studio 当前负责：

- Account auth；
- admin account management；
- admin-only ProviderConfig CRUD；
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
  ├─ Persona
  ├─ Bridge
  │    └─ BridgeSession
  ├─ Inbox
  │    ├─ Contact
  │    │    ├─ Message
  │    │    └─ OutboundMessage
  │    ├─ default Persona ref
  │    └─ optional ProviderConfig override ref
  └─ DistillJob
       ├─ source Inbox
       ├─ target Persona
       └─ ProviderConfig

ProviderConfig
        └─ owner Account ref
```

### Account

Studio 登录账号，带 `admin | user` role。数据库没有任何账号时，Web 登录页可创建首个 admin；之后账号创建、列表、停用/启用和重置密码的主路径是 Studio Web 设置页。Web auth session 和 Bridge session 是两套表。

### ProviderConfig

管理员维护的全局 LLM Provider 配置，包含 `base_url`、`api_key`、`default_model`、`scope`、`status`、`is_default`。Inbox 和 Contact 保留可选 Provider override；普通 user UI 不展示 Provider。

### Persona

可复用的人设 markdown。多个 Inbox/Contact 可以引用同一个 Persona。Distill pipeline 可以覆盖 `persona_md`。

### Bridge

本地 daemon 注册行，由 `(account_id, machine_id)` 唯一标识。`machine_id` 由 Studio 在首次握手时生成并返回，Bridge 持久化后跨重启复用。Handshake 会 upsert Bridge，并清除该 Bridge 旧 session。

### Inbox

一个平台身份，例如一个 Chat account。Handshake 按 `(account_id, platform, platform_self_id)` upsert Inbox。Inbox 可以绑定一个 Bridge，并保存默认 Persona 和可选 Provider override。

### Contact

接管单元，属于一个 Inbox，对应平台里的一个 peer。Contact 保存 display name、关系卡、Persona 引用、可选 Provider override、autoreply 开关、pending reply flag 和 status。

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
- Bridge 当前 CLI 有 `--studio-url` 默认值，这是当前代码事实；本地联调命令仍应显式传入。
