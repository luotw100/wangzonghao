---
name: repository-architecture
description: Laborster 仓库架构全景 Skill。用于理解当前代码、服务边界、数据模型、协议、前后端流程、基础设施和跨模块改动影响。
---

# Laborster 仓库架构

**写作规则：所有文档必须只描述当前状态，严禁包含迁移过程、变更历史、"不再"、"已移除"、"改为"、"之前是"等描述变更的措辞。** 如果某个功能不存在，直接描述当前是什么。

> ⚠ 子文档 (`docs/`) 比 SKILL.md 漂得快，可能有过时段落。SKILL.md 是当前事实最新的入口。改文档前比对代码。

## 什么时候使用

- 改动 `bridge/` 或 `services/api/{studio,chat,admin}` 中任一模块。
- 理解 Studio API、worker、reply brain、distill pipeline、数据库 schema 或 Bridge protocol。
- 理解 Chat sandbox 联系人/会话/消息/导入/长轮询/connector。
- 理解 Bridge daemon 的 adapter 生命周期、inbound/outbound、heartbeat、REPL 命令。
- 排查 Chat → Bridge → Studio → LLM → Bridge → Chat 端到端链路。
- 改 Docker Compose、Nginx 或本地开发配置。

## 一句话总览

Laborster 是私聊接管系统：`Channel ↔ Bridge ↔ Studio`。仓库由 **两个独立项目**组成——`bridge/`（主播 PC 上的 Python REPL daemon）和 `services/`（云端：API + worker + admin + web）。Chat sandbox 是 dogfood Channel，但**代码上**作为 `services/api/chat/` 的子包与 Studio 同进程跑，业务边界靠 schema 和 Python 包隔离维持，运行边界仍是 Bridge HTTP。

## 仓库布局

```
services/
├── api/
│   ├── studio/    # Studio 控制台 (auth、人设、卡片、reply、distill、bridge protocol)
│   ├── chat/      # Chat sandbox 子包（路由挂在 /api/chat/*）
│   ├── admin/     # 独立 FastAPI app，Cloudflare Access 在边缘鉴权
│   ├── alembic.ini
│   └── pyproject.toml
├── user_web/      # 单个 React SPA：/studio + /chat 都是它的路由（含 nginx.conf）
└── admin_web/     # 独立 admin React 面板，CF Access 保护（含 nginx.conf）
bridge/        # laborster_bridge Python 包
docker-compose.yaml  # 唯一的 compose：minio + db + migrate + user-api + user-worker + admin-api + user-web + admin-web + cloudflared
.env.example
scripts/
├── up-all.sh / down-all.sh / backup.sh
└── seed_dev.py
```

## 数据库 schema 布局

单 PG 实例，三个 PostgreSQL schema：

| schema   | 表 | 谁写 |
| --- | --- | --- |
| `auth`   | `accounts`, `auth_sessions` | studio (登录 / session 管理)、chat（只读 FK 引用） |
| `studio` | `provider_configs`, `personas`, `bridges`, `inboxes`, `conversations`, `conversation_members`, `messages`, `distill_jobs`, `outbound_messages`, `llm_logs` | studio + worker + admin |
| `chat`   | `contacts`, `conversations`, `messages` | chat 子包 |

`alembic_version` 表在 `studio` schema。`studio.migrate` 启动时跑 `ensure_schemas()` 然后 `alembic upgrade head`。SQLAlchemy 用两套独立的 `Base`（`studio.db.Base` 和 `chat.db.Base`），同名类 `Conversation` / `Message` 不冲突；两边共享一个 engine + 连接池。

## 核心不变量

1. **Studio 进程不直连 Channel。** Chat sandbox 也只能由 Bridge 的 `chat` adapter 通过 HTTP 走 `/api/chat/*` 进入。
2. **包边界：`services/api/chat/` 与 `services/api/studio/` 不得互相 import；不得跨 schema 查业务表。** 允许的共享层：`studio.db`（engine / Base / utc_now）、`studio.auth_utils`、`studio.deps`（auth deps）、`studio.models.Account`、`studio.notify`。这条边界是用 import 纪律和 schema 隔离一起守的，没有别的强制机制。
3. **Bridge 不做策略决策。** 只登录平台、收消息、推 Studio、拉 outbound、发送。媒体消息走 S3 搬运。
4. **Studio S3 是媒体唯一源。** 单 bucket（默认 `media`）；chat keys 以 `media/{account_id}/` 前缀；studio keys 各自约定。
5. **Studio DB 是 source of truth。** `studio.messages` 表保存全部接管聊天历史，每条消息有 `msg_type`。
6. **Conversation 是接管单元。** Studio 的 `conversations` 行持有 `kind`（dm/group/unknown）、`persona_id`、`provider_id`、`takeover`、`reply_policy`、`card_md`、`last_reply_round_at`；`conversation_members` 描述群/DM 成员。
7. **Inbox 是平台身份。** Bridge 握手时通过 `POST /api/bridge/inboxes` 自动注册，没有面向用户的创建 API。
8. **Bridge 行 = `(account_id, machine_id)`。** `machine_id` 由 Studio 首次握手生成，Bridge 本地持久化，每次请求带 `X-Machine-Id` 头解析。
9. **Auth 是 account 粒度的单一 token。** 浏览器、Bridge 和 chat adapter 共用同一张 `auth.auth_sessions`。Bridge 启动时用账号密码握换 token，存入本地 SQLite `kv` 表；chat channel 的 credential 直接复用同一个 studio token。token 24h 滑动续期；401 才再输密码。改密码会清空该 account 的所有 session（web 和 Bridge 一并下线）。`bridge/laborster_bridge/config.py` 硬编码 `STUDIO_BASE_URL=https://studio.laborster.com`；chat 沙箱同主机，访问路径加 `/api/chat` 前缀。HTTP 请求加自定义 `User-Agent`（Cloudflare 屏蔽默认 `Python-urllib`）。
10. **Outbound 队列是数据库表。** `studio.outbound_messages`，Bridge long-poll；`status=pending` 含 `send_after` 控制打字节奏。
11. **环境变量必须显式提供。** 缺 `DATABASE_URL`、`S3_ENDPOINT`、`S3_PUBLIC_URL`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`、`UPLOAD_MAX_SIZE_MB` 直接报错。
12. **Models 不用 SQLAlchemy column default。** 每次 INSERT 显式写所有字段。
13. **Per-Conversation / per-Account Provider。** `conversations.provider_id` 控 reply，`accounts.distill_provider_id` 控 distill。无系统级 fallback；admin 通过 admin-api 维护 ProviderConfig 池，最早创建那条作为 pick_first_provider 默认。每个 web 账号只看自己的数据。
14. **Admin 平面独立**：`services/api/admin/` + `admin_web/`，挂 `/api/admin/*`，**无 in-app auth**，靠 Cloudflare Access 在边缘鉴权；与 user_web 不混。

## 部署形态

一份 `docker-compose.yaml`（项目根）起：

| 服务 | 说明 |
| --- | --- |
| `db`         | postgres:16-alpine，单 DB，启动后 `migrate` 跑 alembic 建 3 schema + 全部表 |
| `minio` + `minio-create-buckets` | 单 bucket `${S3_BUCKET}` |
| `migrate`    | 一次性，跑 `studio.migrate` |
| `user-api`   | uvicorn studio.main:app，挂全部路由（studio + /api/chat） |
| `user-worker`| `studio.worker` — DistillScanner + ReplyScanner |
| `admin-api`  | uvicorn admin.app:app（端口 23457） |
| `user-web`   | nginx + user_web 构建产物，`/api` 反代到 user-api，其余 SPA fallback |
| `admin-web`  | nginx + admin_web，`/api` 反代到 admin-api |
| `cloudflared` | tunnel，对外暴露 |

## Bridge ↔ Studio 协议

| 端点 | 谁调 | 干什么 |
| --- | --- | --- |
| `POST /api/bridge/handshake` | Bridge → Studio | 账号密码 + machine_id → token + account_id + username + machine_id |
| `POST /api/bridge/heartbeat` | Bridge → Studio | 续租 session、更新 last_seen_at |
| `POST /api/bridge/inboxes`   | Bridge → Studio | 注册当前 daemon 持有的 inbox 集合 |
| `GET  /api/bridge/inboxes`   | Bridge → Studio | 拉服务认可的 inbox 列表 |
| `POST /api/bridge/conversations` | Bridge → Studio | 同步会话目录（kind / display_name / members） |
| `GET  /api/bridge/takeovers` | Bridge → Studio | 拉取需要接管的 (inbox, conv) 集合 |
| `POST /api/bridge/incoming`  | Bridge → Studio | 批量推消息，按 `(conversation_id, client_id)` 去重 |
| `GET  /api/bridge/outbound`  | Bridge → Studio | 长轮询 pending outbound（无 cursor、无 lease、无 ack）|

## Reply / Distill 运行时

```text
Conversation.takeover=True ∧ reply_policy=autoreply ∧ persona_id≠NULL
  → ReplyScanner（worker，每 2s 扫一次）
  → maybe_reply()
  → ProviderClient.complete_chat()  （走 Conversation.provider_id）
  → OutboundMessage(msg_type='text', status=pending, send_after=打字节奏)
  → Bridge long-poll 拉取 → 立即发出 → inbound from_self 自动 ack
```

DistillJob 路径走 `accounts.distill_provider_id`，由 DistillScanner 异步执行；progress 是 JSONB，前端轮询展示。

## 文档地图

> 以下子文档可能落后于代码事实，先以本 SKILL.md 为准，再读子文档补细节。

- `docs/shared/architecture.md` / `end-to-end-flows.md` / `development-workflow.md` / `current-code-notes.md`
- `docs/bridge/overview.md` / `runtime-adapters.md` / `protocol.md` / `infra.md`
- `docs/studio/overview.md` / `backend-api.md` / `data-model.md` / `worker-reply-distill.md` / `frontend.md` / `infra.md`

## AI / 开发者阅读顺序

1. 先读本 SKILL.md（事实最新）。
2. 跨服务的改动：再扫 `docs/shared/architecture.md` 和 `docs/bridge/protocol.md`。
3. 改 API/schema：直接读 `services/api/studio/models.py` 和 `routers/`。
4. 改 chat：直接读 `services/api/chat/`。
5. 改 UI：读 `services/user_web/src/`（chat 部分在 `chat/` 子目录）。
6. 动手前对照不变量。
