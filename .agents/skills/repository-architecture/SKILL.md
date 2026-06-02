---
name: repository-architecture
description: Laborster 仓库架构全景 Skill。用于理解当前代码、服务边界、数据模型、协议、前后端流程、基础设施和跨模块改动影响。
---

# Laborster 仓库架构

**写作规则：所有文档必须只描述当前状态，严禁包含迁移过程、变更历史、"不再"、"已移除"、"改为"、"之前是"等描述变更的措辞。** 如果某个功能不存在，直接描述当前是什么。

> ⚠ 子文档 (`docs/`) 比 SKILL.md 漂得快，可能有过时段落。SKILL.md 是当前事实最新的入口。改文档前比对代码。

## 什么时候使用

- 改动 `desktop/sidecar/laborster_bridge/` 或 `services/api/{studio,chat,admin}` 中任一模块。
- 理解 Studio API、worker、reply brain、distill pipeline、数据库 schema 或 Bridge protocol。
- 理解 Chat sandbox 联系人/会话/消息/导入/长轮询/connector。
- 理解 Bridge daemon 的 adapter 生命周期、inbound/outbound、heartbeat、REPL 命令。
- 排查 Chat → Bridge → Studio → LLM → Bridge → Chat 端到端链路。
- 改 Docker Compose、Nginx 或本地开发配置。

## 一句话总览

Laborster 是私聊接管系统：`Channel ↔ Bridge ↔ Studio`。仓库由 **两个独立项目**组成——`desktop/`（主播端 Electron 桌面应用 + Python sidecar daemon）和 `services/`（云端：API + worker + admin + web）。Chat sandbox 是 dogfood Channel，但**代码上**作为 `services/api/chat/` 的子包与 Studio 同进程跑，业务边界靠 schema 和 Python 包隔离维持，运行边界仍是 Bridge HTTP。

## 仓库布局

```
desktop/
├── sidecar/
│   ├── laborster_bridge/   # laborster_bridge Python 包（pip install -e 给 bridge-host 容器用；PyInstaller 打包进桌面应用 sidecar）
│   │   ├── __main__.py     # 入口：--headless → headless.run()，否则 repl.run()
│   │   ├── headless.py     # hosted-bridge 云端 subprocess 模式（bridge-host 专用）
│   │   ├── repl.py         # 交互式 CLI（prompt_toolkit，本地调试用）
│   │   ├── runtime.py      # 5 个 actor（Scheduler/Upload/Takeover/Outbound/Heartbeat）
│   │   ├── commands.py     # 命令 dispatch + daemon 管理
│   │   ├── store.py        # SQLite（kv/channels/local_messages/conv_cursors）
│   │   ├── studio_client.py
│   │   ├── config.py       # STUDIO_BASE_URL 启动时从 discovery 解析；headless 通过 --studio-url 覆盖
│   │   ├── adapters/chat.py
│   │   └── gui/bridge_api.py  # HTTP sidecar 的 API 层（被 server.py 调用）
│   ├── server.py           # Electron sidecar HTTP 服务（反代 Studio、媒体上传）
│   ├── pyproject.toml      # hatchling，wheel 只打 laborster_bridge 包
│   └── requirements.txt
├── electron/               # Electron 主进程 + sidecar 管理
└── src/                    # React 前端
services/
├── api/
│   ├── studio/    # Studio 控制台 (auth、人设、卡片、reply、distill、bridge protocol)
│   ├── chat/      # Chat sandbox 子包（路由挂在 /api/chat/*）
│   ├── admin/     # 独立 FastAPI app，Cloudflare Access 在边缘鉴权
│   ├── alembic.ini
│   └── pyproject.toml
├── portal/        # 公开站点：静态 index.html（介绍 + 登录下载）+ /.well-known/laborster-api.json discovery 锚点；Caddy file_server 直接 serve，无构建
├── admin_web/     # 独立 admin React 面板，CF Access 保护（含 nginx.conf）
└── bridge_host/   # bridge-host service：admin 手动起停的 chat-only Bridge subprocess supervisor
docker-compose.yaml  # 唯一的 compose，服务按 profiles 分层：storage / app / edge
.env.example         # 每 instance 复制为 .env.release / .env.debug（自包含，含 COMPOSE_PROJECT_NAME + COMPOSE_PROFILES）
scripts/
├── backup.sh
├── seed.py            # 宿主机一次性 seed：动态取 admin-api 容器 IP，纯 HTTP 建账号/Provider
└── seed.example.json  # 复制为 seed.<instance>.json（gitignored，含 API key）
```

## 数据库 schema 布局

单 PG 实例，三个 PostgreSQL schema：

| schema   | 表 | 谁写 |
| --- | --- | --- |
| `auth`   | `accounts`, `auth_sessions` | studio (登录 / session 管理)、chat（只读 FK 引用） |
| `studio` | `provider_configs`, `personas`, `bridges`, `inboxes`, `conversations`, `conversation_members`, `messages`, `distill_jobs`, `outbound_messages`, `llm_logs`, `hosted_bridges`, `releases`, `download_events` | studio + worker + admin |
| `chat`   | `contacts`, `conversations`, `messages` | chat 子包 |

`alembic_version` 表在 `studio` schema。`studio.migrate` 启动时跑 `ensure_schemas()` 然后 `alembic upgrade head`。SQLAlchemy 用两套独立的 `Base`（`studio.db.Base` 和 `chat.db.Base`），同名类 `Conversation` / `Message` 不冲突；两边共享一个 engine + 连接池。

## 核心不变量

1. **Studio 进程不直连 Channel。** Chat sandbox 也只能由 Bridge 的 `chat` adapter 通过 HTTP 走 `/api/chat/*` 进入。
2. **包边界：`services/api/chat/` 与 `services/api/studio/` 不得互相 import；不得跨 schema 查业务表。** 允许的共享层：`studio.db`（engine / Base / utc_now）、`studio.auth_utils`、`studio.deps`（auth deps）、`studio.models.Account`、`studio.notify`。这条边界是用 import 纪律和 schema 隔离一起守的，没有别的强制机制。
3. **Bridge 不做策略决策。** 只登录平台、收消息、推 Studio、拉 outbound、发送。媒体消息走 S3 搬运。
4. **Studio S3 是媒体唯一源。** 单 bucket（默认 `media`）；chat keys 以 `media/{account_id}/` 前缀；studio keys 各自约定。
5. **Studio DB 是 source of truth。** `studio.messages` 表保存全部接管聊天历史，每条消息有 `msg_type`。
6. **Conversation 是接管单元。** Studio 的 `conversations` 行持有 `kind`（dm/group/unknown）、`persona_id`、`provider_id`、`takeover`、`reply_policy`、`card_md`、`last_reply_round_at`；`conversation_members` 描述群/DM 成员。
7. **Inbox 是平台身份。** Bridge 握手时通过 `POST /api/bridge/inboxes` 自动注册，没有面向用户的创建 API。**Per-channel 互斥**：一个 `(account, platform, platform_self_id)` 同一时刻只能被一个**在线**（`last_seen_at` 在 `BRIDGE_OFFLINE_S=45s` 内）Bridge 持有；第二个在线 Bridge 来抢报 409（detail 带占用方 machine_id），离线/stale 的 owner 可被透明接管。Bridge 端把 409 映射成终态 `CONFLICT`（不重试）；headless 在所有 channel 都 CONFLICT 时以退出码 4 退出，让心跳停掉、admin 面板转 stale。
8. **Bridge 行 = `(account_id, machine_id)`。** `machine_id` 由 Studio 首次握手生成，Bridge 本地持久化，每次请求带 `X-Machine-Id` 头解析。
9. **Auth 是 account 粒度的单一 token。** 浏览器、Bridge 和 chat adapter 共用同一张 `auth.auth_sessions`。Bridge 启动时用账号密码握换 token，存入本地 SQLite `kv` 表；chat channel 的 credential 直接复用同一个 studio token。token 24h 滑动续期；401 才再输密码。改密码会清空该 account 的所有 session（web、Bridge、hosted bridge 一并下线）。Studio API 对外主机是 `https://api.laborster.com`；chat 沙箱同主机，访问路径加 `/api/chat` 前缀。HTTP 请求加自定义 `User-Agent`（Cloudflare 屏蔽默认 `Python-urllib`）。
    **API host 不硬编码（discovery）**——`desktop/sidecar/laborster_bridge/config.py` 只烤进一个 discovery 锚点 `https://laborster.com/.well-known/laborster-api.json` 和 seed 兜底 `DEFAULT_API_BASE=https://api.laborster.com`。GUI/REPL 启动时 `resolve_studio_base_url()` 拉 discovery（单次、3s、无重试），成功则覆盖 `STUDIO_BASE_URL` 并把 last-known-good 缓存到 `<state_root>/api-config.json`，失败回退缓存→seed。挂载点：`server.py:main()`（桌面）和 `__main__.py` 非 headless 分支（REPL）各调一次。这样换 API host 只改 discovery 那个静态 JSON，不必重发客户端。
    **特例：hosted bridge 路径**——admin-api 可以为某 Account 直接 `create_auth_session` 签 token 给 bridge-host 用，无需密码；hosted bridge 的 `STUDIO_BASE_URL` 由 `--studio-url` flag 注入（指向 docker 内网 `http://user-api:23456`），且 **headless 永不调用 discovery**；主播端 Electron/REPL 永远走 discovery 结果、不接受 flag。
10. **Outbound 队列是数据库表。** `studio.outbound_messages`，Bridge long-poll；`status=pending` 含 `send_after` 控制打字节奏。
11. **环境变量必须显式提供。** 缺 `DATABASE_URL`、`S3_ENDPOINT`、`S3_PUBLIC_URL`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`、`UPLOAD_MAX_SIZE_MB` 直接报错。
12. **Models 不用 SQLAlchemy column default。** 每次 INSERT 显式写所有字段。
13. **Per-Conversation / per-Account Provider。** `conversations.provider_id` 控 reply，`accounts.distill_provider_id` 控 distill。无系统级 fallback；admin 通过 admin-api 维护 ProviderConfig 池，最早创建那条作为 pick_first_provider 默认。每个 web 账号只看自己的数据。
14. **Admin 平面独立**：`services/api/admin/` + `admin_web/`，挂 `/api/admin/*`，**无 in-app auth**，靠 Cloudflare Access 在边缘鉴权；与用户面（api / portal）不混。
15. **没有网页版用户界面。** 用户侧界面全在桌面应用（`desktop/`）。`api.laborster.com` 是机器面（桌面 app + bridge），浏览器打开除 `/api/health` 外都要 bearer token，未知路径 404；OpenAPI docs（`/api/docs`）默认开，关掉手动改 `studio/main.py`。公开站点是 `services/portal/` 静态文件（`laborster.com`）。
16. **桌面应用分发是邀请制下载。** 账号只能 admin 开（无公开注册），所以「有账号」=「被邀请」。portal 用账号密码登录 `POST /api/auth/login` 拿 token，再 `GET /api/download/latest?platform=win|mac`（需鉴权，只维护 Win x64 + Mac arm64）换一条 S3 presigned 直链并记 `download_events`。`releases` 表是「已发布版本目录 + 当前指针」（`is_latest` 每平台至多一行，partial unique index），安装包字节在 S3 `releases/<version>/<filename>`。portal 跨域调 api，靠 `PORTAL_ORIGINS`（CORS）放行。发版用 `scripts/publish-release.sh <env-file> <publish|list|promote> [args]`（env-file-first 透传，形状同 test.sh/seed.py）。真正的 CLI 是 `studio.publish_release`（.py，跟镜像走）：`publish` 上传 S3 + 登记行 + `--latest` 翻指针、`promote` 回滚切指针、`list` 查看；`.sh` 只负责在 compose 网络里跑它并把 `--file` 挂进容器。改完 .py 要 `up --build` 才生效。
17. **Hosted bridge 仅做 chat adapter**。bridge-host 起的 subprocess 走 `__main__.py --headless`，只注册 chat channel，不接入任何真实平台。物理 Bridge（主播 PC）和 hosted Bridge 共用同一套 `studio.bridges` 行 + `(account_id, machine_id)` 标识；机器侧由 machine_id 互不干扰。Hosted bridge 生命周期完全由 admin 手动控制——bridge-host 不做 auto-restart，重启后 `studio.hosted_bridges.status=running` 的行变成"stale"，需要 admin 重新点 Restart。

## 部署形态

一份 `docker-compose.yaml`（项目根）起：

| 服务 | 说明 |
| --- | --- |
| `db`         | postgres:16-alpine，单 DB，启动后 `migrate` 跑 alembic 建 3 schema + 全部表 |
| `minio` + `minio-create-buckets` | 单 bucket `${S3_BUCKET}` |
| `migrate`    | 一次性，跑 `studio.migrate` |
| `user-api`   | uvicorn studio.main:app，挂全部路由（studio + /api/chat + /api/download）；对外 `api.laborster.com` |
| `user-worker`| `studio.worker` — DistillScanner + ReplyScanner |
| `admin-api`  | uvicorn admin.app:app（端口 23457）；通过 `BRIDGE_HOST_URL` 调 bridge-host 起停 subprocess |
| `bridge-host`| FastAPI supervisor（端口 23458，仅 docker 内网），收 admin-api 指令 spawn/kill `python -m laborster_bridge --headless` 子进程；卷 `bridge-host-data:/data` 存各账号 sqlite |
| `admin-web`  | nginx + admin_web，`/api` 反代到 admin-api |
| `caddy`（edge）| 终止 TLS，按 Host 路由：`laborster.com`→`/srv/portal`（挂 `./services/portal`，file_server）、`api.laborster.com`→user-api、`s3.laborster.com`→minio。无 user-web 中间层 |
| `frpc`（edge）| 把 caddy:443 经首尔 frp relay TCP 透传暴露（用户面） |
| `cloudflared`（edge） | tunnel，仅 admin 面（admin-web 走 CF Access） |

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

Admin → Studio（hosted bridge 控制）：

| 端点 | 干什么 |
| --- | --- |
| `GET  /api/admin/hosted-bridges` | 列出所有 account 的 hosted bridge 状态 |
| `POST /api/admin/hosted-bridges/{account_id}/start` | 创建/复用 Bridge 行 + 签 session → 调 bridge-host `/spawn` |
| `POST /api/admin/hosted-bridges/{account_id}/stop`  | 调 bridge-host `/stop` + 删除该 session |

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
2. 跨服务的改动：再扫 `docs/shared/architecture.md` 和 `docs/bridge/protocol.md`（可能落后，以代码为准）。
3. 改 Bridge daemon：直接读 `desktop/sidecar/laborster_bridge/`。
4. 改 API/schema：直接读 `services/api/studio/models.py` 和 `routers/`。
5. 改 chat：直接读 `services/api/chat/`。
6. 改用户 UI：读 `desktop/src/`（`StudioViews.tsx` / `ChatSandbox.tsx`）。公开站点改 `services/portal/index.html`。admin 面板改 `services/admin_web/src/`。
7. 动手前对照不变量。
