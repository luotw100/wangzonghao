---
name: repository-architecture
description: Laborster 仓库架构全景 Skill。用于理解当前代码、服务边界、数据模型、协议、前后端流程、基础设施和跨服务改动影响。
---

# Laborster 仓库架构

这是当前仓库的 1:1 架构说明入口。文档只描述当前代码中已经存在的设计材料。

**写作规则：所有文档必须只描述当前状态，严禁包含迁移过程、变更历史、"不再"、"已移除"、"改为"、"之前是"等描述变更的措辞。** 如果某个功能不存在，直接描述当前是什么，不要提及它曾经存在。例如：不要写"POST /api/inboxes 已移除"，而要写"Inbox 仅由 Bridge handshake 创建，没有独立的创建 API"。

## 什么时候使用

在处理以下任务前，先读这个 Skill：

- 需要改动 `services/chat`、`services/bridge`、`services/studio` 中任意两个以上服务。
- 需要理解 Studio API、worker、reply brain、distill pipeline、数据库 schema 或 Bridge protocol。
- 需要理解 Chat sandbox 的联系人、会话、消息、导入、long polling 或 connector 行为。
- 需要理解 Bridge daemon 的 CLI、adapter 生命周期、inbound/outbound、heartbeat 或 typing delay。
- 需要排查从 Chat → Bridge → Studio → LLM → Bridge → Chat 的端到端消息链路。
- 需要改 Docker Compose、Dockerfile、Nginx、本地开发或部署相关配置。

## 一句话总览

Laborster 是私聊接管系统。当前仓库由三个独立项目组成：`Channel ↔ Bridge ↔ Studio`。其中 Chat sandbox 是可控 Channel，Bridge 是本地 IO daemon，Studio 是云端控制台、消息源、LLM 回复脑和蒸馏脑。

## 三个独立项目

| 项目 | 路径 | 当前职责 | 边界规则 |
| --- | --- | --- | --- |
| Chat sandbox | `services/chat/` | dogfood Channel / 可控聊天平台 | 只模拟平台；Studio 不直接调用它。 |
| Bridge daemon | `services/bridge/` | 登录本地平台账号并桥接到 Studio | 不调 LLM、不存人设、不保存长期 token。 |
| Studio | `services/studio/` | 控制台、source of truth、reply/distill brain | 不直连任何 Channel，只接受 Bridge protocol。 |

每个项目都有独立的依赖、Dockerfile、Compose 配置和运行边界。不要把它们当成一个 Python/Node 单体项目处理。

## 当前核心不变量

1. **Studio 不直连 Channel。** 当前 Chat sandbox 也只能通过 Bridge 的 `chat` adapter 进入 Studio。
2. **Bridge 不做策略决策。** Bridge 只登录平台、收消息、推 Studio、拉 outbound、发送。对媒体消息，Bridge 是粗管道：平台 S3 ↔ Studio S3 搬运二进制数据。
3. **Studio S3 是媒体唯一源。** 所有媒体二进制最终存储在 Studio S3。Inbound 时 Bridge 下载平台媒体 → 上传 Studio S3 → 消息 content 为 Studio storage key。Outbound 时 content 指向 Studio S3 storage key → Bridge 下载 → 上传到平台 → 发送。
4. **Studio DB 是 source of truth。** Studio 的 `messages` 表统一保存 archive/live 历史，每条消息有 `msg_type` 字段（text | image | audio | video | file）。
5. **Contact 是接管单元。** Contact 持有 `persona_id`、可选 Provider override、`autoreply_enabled`、`card_md`、`pending_reply`。
6. **Inbox 是平台身份。** Inbox 表示一个平台账号/身份，并给新 Contact 提供默认 Persona 和可选 Provider override。
7. **Bridge 是本地 daemon 实例。** Bridge 行由 `(account_id, hostname)` 标识，可服务多个 Inbox。
8. **Outbound 队列是数据库表。** `outbound_messages` 是 Studio → Bridge 的工作队列，每条携带 `msg_type`；Bridge long-poll 并维护 cursor。
9. **Chat/Studio 数据库和 S3 环境变量必须显式提供。** 缺失 `DATABASE_URL`、`S3_ENDPOINT`、`S3_PUBLIC_URL`、`S3_ACCESS_KEY`、`S3_SECRET_KEY` 或 `S3_BUCKET` 会直接报错。
10. **Chat/Studio models 不用 SQLAlchemy column default。** 当前设计要求插入时显式写入字段值。迁移中使用 `server_default` 仅为兼容已有数据。
11. **Studio Provider 是管理员维护的全局配置。** 普通用户 UI 不展示 Provider；reply/distill 解析顺序是 Contact override → Inbox override → 全局默认 Provider。
12. **Studio 和 Chat 使用 PostgreSQL + Alembic 管理 schema。** 启动时自动执行 `run_migrations()`。

## 文档地图

### Shared / 跨服务

- `docs/shared/architecture.md` — 产品模型、服务边界、核心实体、归属关系。
- `docs/shared/end-to-end-flows.md` — 当前端到端流程：登录、incoming、自动回复、outbound、archive、distill。
- `docs/shared/development-workflow.md` — 当前运行、账号 CLI、存储、验证方法。
- `docs/shared/current-code-notes.md` — 当前代码事实与注意点，不包含规划。

### Chat sandbox

- `docs/chat/overview.md` — Chat 的角色、目录、技术栈、运行定位。
- `docs/chat/backend.md` — FastAPI 后端、DB models、schemas、auth、endpoints、long polling。
- `docs/chat/frontend.md` — React 状态、hooks、components、API client、导入 UI。
- `docs/chat/infra.md` — Compose、Nginx、Dockerfile、端口、storage、本地 dev。

### Bridge daemon

- `docs/bridge/overview.md` — daemon 目的、CLI、claims、启动生命周期。
- `docs/bridge/runtime-adapters.md` — adapter contract、Chat adapter、inbound pump、heartbeat、outbound dispatch。
- `docs/bridge/protocol.md` — 当前 Studio `/api/bridge/*` protocol。
- `docs/bridge/infra.md` — Compose、Dockerfile、配置面、运行行为。

### Studio

- `docs/studio/overview.md` — Studio 职责、进程划分、目录结构。
- `docs/studio/backend-api.md` — FastAPI 依赖、auth、serializers、ownership helpers、web endpoints。
- `docs/studio/data-model.md` — SQLAlchemy tables、constraints、relationships、状态值。
- `docs/studio/worker-reply-distill.md` — worker scanners、reply brain、LLM logs、distill ingest/packer/pipeline/fold prompt。
- `docs/studio/frontend.md` — React routes、auth context、API client、StudioPage tabs 和数据流。
- `docs/studio/infra.md` — Compose、Nginx、Dockerfile、worker 进程、storage。

## 当前实现和仓库设计文档的关系

当前代码中的 Studio reply runtime 是 scanner-based：

```text
Contact.pending_reply=True
  → StudioRuntime ReplyScanner every 2s
  → maybe_reply()
  → ProviderClient.complete_chat()
  → OutboundMessage(msg_type='text', status=pending, send_after=打字节奏)
  → Bridge long-poll + 即发 + ack
```

## AI / 开发者阅读顺序

1. 先读 `docs/shared/architecture.md`。
2. 再读目标服务的 `overview.md`。
3. 改 API/schema 时读对应 backend/data-model 文档。
4. 改消息链路时读 Bridge protocol、Studio worker/reply 文档和 end-to-end flows。
5. 改 UI 时读对应 frontend 文档和 API client 部分。
6. 动手前确认改动是否跨服务，是否违反上面的当前不变量。
