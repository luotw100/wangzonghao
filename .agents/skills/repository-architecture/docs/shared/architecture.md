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
- **Bridge**：本地 IO daemon，持有平台登录态，负责收发消息和 typing delay。
- **Studio**：云端控制面，持有账号、人设、Provider、消息历史、关系卡、蒸馏任务、回复决策和 outbound 队列。

## 服务边界

### Chat sandbox

`services/chat` 是独立聊天应用，当前用于作为可控 Channel。它包含自己的账号、auth session、联系人、会话、消息、导入、long polling 和前端 UI。

Studio 与 Chat 之间没有代码 import 和直接 API 调用；仅 Bridge 的 `ChatAdapter` 通过 HTTP 调用 Chat。

### Bridge daemon

`services/bridge` 是 Python asyncio daemon。它从 CLI 接收 Studio 登录信息和平台登录 claim，先登录平台拿到 `platform_self_id`，再向 Studio handshake 获取 Bridge session token 和 Inbox 映射。

Bridge 当前负责：

- adapter 登录；
- initial catch-up；
- live inbound streaming；
- 批量推送 `/api/bridge/incoming`；
- heartbeat；
- outbound long polling；
- chunk 级 typing delay；
- 平台发送和 ack。

Bridge 当前不负责：

- LLM 调用；
- Persona / Card 读取或存储；
- autoreply gating；
- distill；
- 回复内容策略。

### Studio

`services/studio` 是控制台和 AI brain。它提供 Web API 和 Bridge protocol API，存储 live/archive 消息，执行 reply 和 distill，并写入 outbound queue。

Studio 当前负责：

- Account auth；
- admin account management；
- admin-only ProviderConfig CRUD；
- Persona CRUD；
- Bridge auto-registration 和 revoke；
- Inbox list/default settings；
- Contact takeover settings；
- archive upload / ingest；
- distill job create / worker execution；
- reply scanning / LLM call；
- outbound queue 管理。

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
  ├─ Archive
  │    └─ Message
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

本地 daemon 注册行，由 `(account_id, hostname)` 唯一标识。Handshake 会 upsert Bridge，并清除该 Bridge 旧 session。

### Inbox

一个平台身份，例如一个 Chat account。Handshake 按 `(account_id, platform, platform_self_id)` upsert Inbox。Inbox 可以绑定一个 Bridge，并保存默认 Persona 和可选 Provider override。

### Contact

接管单元，属于一个 Inbox，对应平台里的一个 peer。Contact 保存 display name、关系卡、Persona 引用、可选 Provider override、autoreply 开关、pending reply flag 和 status。

### Message

Studio `messages` 表统一保存 archive 和 live 消息。按 `(contact_id, external_id)` 去重。`source` 是 `archive | live`，`role` 是 `self | counterpart`。

### OutboundMessage

Studio → Bridge 的工作队列表。包含 JSON `chunks`、状态、投递/失败信息。Bridge 通过 cursor 消费并 ack。

## 配置原则在当前代码中的体现

- Chat 需要 `DATABASE_URL` 和 S3 环境变量（`S3_ENDPOINT`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`），缺失时报错。
- Studio 需要 `DATABASE_URL` 和 S3 环境变量（`S3_ENDPOINT`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`），缺失时报错。
- Chat 和 Studio models 当前不使用 SQLAlchemy column default。
- Studio 和 Chat 使用 PostgreSQL，由 Alembic 管理 schema 迁移。
- Bridge 当前 CLI 有 `--studio-url` 默认值，这是当前代码事实；本地联调命令仍应显式传入。
