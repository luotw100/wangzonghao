---
name: repository-architecture
description: Laborster 仓库架构全景 Skill。理解服务边界、数据模型、协议、端到端流程、基础设施，以及跨模块改动的影响面。
---

# Laborster 仓库架构

这是一张**指向代码的地图**，不是代码的镜像。框架、输入输出、思路写在这里；具体字段/端点/参数以代码为准，按下面的指针去读源文件。**只描述当前状态**——不写迁移过程、变更历史、"不再/已移除/曾经"之类措辞。改文档前先比对代码。

## 什么时候用

- 改 `desktop/sidecar/laborster_bridge/` 或 `services/api/{studio,chat,admin}` 任一模块。
- 想理解 Studio API / worker / reply / distill / schema / Bridge 协议 / Chat sandbox。
- 排查 Chat → Bridge → Studio → LLM → Bridge → Chat 端到端链路。
- 改 Docker Compose、edge（Caddy/frpc）或本地开发配置。

## 一句话总览

Laborster 是私聊接管系统：`Channel ↔ Bridge ↔ Studio`。仓库是**两个独立项目**——`desktop/`（主播端 Electron + Python sidecar daemon）和 `services/`（云端 API + worker + admin + portal）。Chat sandbox 是 dogfood Channel，代码上作为 `services/api/chat/` 子包与 Studio 同进程跑，业务边界靠 schema + Python 包隔离维持，运行边界仍是 Bridge HTTP。

## 仓库布局

```
desktop/
├── sidecar/laborster_bridge/   # Python 包，PyInstaller 冻结进桌面 sidecar
│   ├── __main__.py             # 入口：--headless → headless.run()，否则 repl.run()
│   ├── runtime.py              # 5 actor：Scheduler/Upload/Takeover/Outbound/Heartbeat
│   ├── store.py                # SQLite：kv/channels/local_messages/conv_cursors
│   ├── studio_client.py        # 对 Studio 的 HTTP 客户端
│   ├── config.py               # STUDIO_BASE_URL 硬编码（见不变量 §auth）
│   └── adapters/chat.py        # Channel adapter
├── sidecar/server.py           # Electron sidecar HTTP 服务（反代 Studio、媒体上传）
├── electron/                   # 主进程 + sidecar 管理
└── src/                        # React 前端（StudioViews.tsx / ChatSandbox.tsx）
services/
├── api/
│   ├── studio/                 # 控制台：auth、人设、卡片、reply、distill、bridge 协议、worker
│   ├── chat/                   # Chat sandbox 子包，路由挂 /api/chat/*
│   └── admin/                  # 独立 FastAPI app，Cloudflare Access 边缘鉴权
├── portal/index.html           # 公开站点静态页（Caddy file_server，无构建）
└── admin_web/                  # 独立 admin React 面板
edge/                           # 用户面 edge：caddy/（Dockerfile + Caddyfile）+ frpc.toml
docker-compose.yaml             # 唯一 compose，按 profiles 分层：storage / app / edge
.env.example                    # 复制为 .env.release / .env.debug（自包含）
scripts/                        # publish-release.sh / test.sh / seed.py / loadtest.py 等
```

## 数据模型框架

单 PG 实例，三个 schema，靠 schema + 包隔离维持业务边界：

| schema   | 谁写 | 内容 |
| --- | --- | --- |
| `auth`   | studio 写，chat 只读 FK | accounts、auth_sessions |
| `studio` | studio + worker + admin | provider/persona/bridge/inbox/conversation/message/distill/outbound/llm_log/release 等 |
| `chat`   | chat 子包 | contacts、conversations、messages |

`alembic_version` 在 `studio` schema；启动 `studio.migrate` 跑 `ensure_schemas()` + `alembic upgrade head`。两套独立 `Base`（`studio.db.Base` / `chat.db.Base`）共享一个 engine + 连接池，同名类不冲突。
**字段以代码为准**：`services/api/studio/models.py`、`services/api/chat/` 下的 models。

## 核心不变量

看单个文件推不出来的架构决策，动手前对照：

1. **Studio 不直连 Channel。** Chat sandbox 也只能由 Bridge 的 `chat` adapter 经 HTTP 走 `/api/chat/*` 进入。
2. **包边界：`chat/` 与 `studio/` 不互相 import、不跨 schema 查业务表。** 仅允许共享 `studio.db`、`studio.auth_utils`、`studio.deps`、`studio.models.Account`、`studio.notify`。靠 import 纪律 + schema 隔离守，无强制机制。
3. **Bridge 不做策略决策。** 只登录平台、收消息、推 Studio、拉 outbound、发送；媒体走 S3。
4. **Studio DB 是 source of truth。** `studio.messages` 存全部接管历史；conversation 是接管单元（持 takeover/reply_policy/persona/provider）。
5. **Inbox per-channel 互斥。** 一个 `(account, platform, platform_self_id)` 同时只能被一个**在线**（`last_seen_at` 在 `BRIDGE_OFFLINE_S` 内）Bridge 持有；第二个在线 Bridge 抢报 409，离线/stale owner 可被透明接管。Bridge 把 409 映射成终态 CONFLICT 不重试。
6. **Auth 是 account 粒度单 token。** 浏览器/Bridge/chat adapter 共用 `auth.auth_sessions`；24h 滑动续期，401 才重输密码；改密码清空该 account 全部 session。
7. **API host 硬编码。** `desktop/sidecar/laborster_bridge/config.py` 的 `STUDIO_BASE_URL = https://api.laborster.com`，GUI/REPL 永远走这个、不接受 flag、无 startup 网络探测（.well-known discovery 会卡 BRIDGE_READY 握手，故不用）。仅 headless 可用 `--studio-url` 覆盖。请求带自定义 User-Agent（CF 屏蔽 `Python-urllib`）。
8. **Provider 是 per-conversation / per-account。** `conversations.provider_id` 控 reply，`accounts.distill_provider_id` 控 distill；无系统级 fallback，admin 维护 Provider 池。每个账号只看自己的数据。
9. **Admin 平面独立。** `services/api/admin/` + `admin_web/`，挂 `/api/admin/*`，**无 in-app auth**，靠 Cloudflare Access 边缘鉴权，与用户面不混。
10. **没有网页版用户界面。** 用户侧全在桌面应用；`api.laborster.com` 是机器面，浏览器除 `/api/health` 外都要 bearer token。公开站点是 `services/portal/`。
11. **桌面分发是邀请制。** 无公开注册（账号 admin 开）；portal 登录后 `GET /api/download/latest` 换 S3 presigned 直链。发版用 `scripts/publish-release.sh`，真正 CLI 是 `studio.publish_release`（改 .py 要 `up --build`）。

约定细节（INSERT 显式写全字段、必需环境变量、S3 单 bucket 等）看对应代码，不在此枚举。

## Bridge ↔ Studio 协议

Bridge 是唯一进出口，全部 HTTP。**端点与字段以 `services/api/studio/routers/bridge_protocol.py` 为准**，下面只列输入输出意图：

| 端点 | 方向 | 干什么 |
| --- | --- | --- |
| `POST /api/bridge/handshake` | Bridge→Studio | 账号密码 + machine_id 换 token；machine_id 首次握手由 Studio 生成、Bridge 持久化，后续请求带 `X-Machine-Id` |
| `POST /api/bridge/heartbeat` | Bridge→Studio | 续租 session、更新 last_seen_at |
| `POST/GET /api/bridge/inboxes` | Bridge↔Studio | 注册/拉取认可的 inbox（平台身份；握手时自动注册，无用户创建 API） |
| `POST /api/bridge/conversations` | Bridge→Studio | 同步会话目录（kind/display_name/members） |
| `GET /api/bridge/takeovers` | Bridge→Studio | 拉需接管的 (inbox, conv) |
| `POST /api/bridge/incoming` | Bridge→Studio | 批量推消息，按 `(conversation_id, client_id)` 去重 |
| `GET /api/bridge/outbound` | Bridge→Studio | 长轮询 pending outbound（无 cursor/lease/ack） |

## Reply / Distill 思路

```text
Conversation.takeover ∧ reply_policy=autoreply ∧ persona_id≠NULL
  → ReplyScanner（worker，每 2s 扫）→ maybe_reply()
  → ProviderClient.complete_chat()（走 conversation.provider_id）
  → OutboundMessage(status=pending, send_after=打字节奏)
  → Bridge long-poll 拉取 → 发出 → inbound from_self 自动 ack
```

Distill 走 `accounts.distill_provider_id`，由 DistillScanner 异步执行，progress 是 JSONB 供前端轮询。实现看 `services/api/studio/worker.py`。

## 部署形态与网络结构

唯一 `docker-compose.yaml`，profiles 分层 storage/app/edge：

- **storage**：`db`（postgres:16）、`minio` + 建桶、`migrate`（一次性跑 `studio.migrate`）。
- **app**：`user-api`（uvicorn `studio.main:app`，挂 studio + /api/chat + /api/download，对外 `api.laborster.com`）、`user-worker`（`studio.worker`：DistillScanner + ReplyScanner）、`fake-llm`（压测假 LLM）、`admin-api`、`admin-web`。
- **edge**：`caddy`（终止 TLS，按 Host 路由 portal/api/s3）、`frpc`（把 caddy:443 经首尔 frp relay 透传，用户面）、`cloudflared`（仅 admin 面）。

网络拓扑（细节看 `docker-compose.yaml` + `edge/`）：

- **不发布任何宿主机端口**（compose 里无 `ports:`）。所有服务跑在默认 compose 网络上，外部只能从两个 edge 入口进：
  - **用户面**：公网 → 首尔 frp relay → `frpc` → `caddy:443`（在此终止 TLS）→ 按 Host 路由到 `/srv/portal`(静态) / `user-api` / `minio`。relay 只搬密文。
  - **admin 面**：公网 → Cloudflare tunnel(`cloudflared`) → `admin-web` → `admin-api`，鉴权由 CF Access 在边缘做。
- **卷全部 `external: true`**，名字 `${COMPOSE_PROJECT_NAME}_<vol>`（pgdata/minio-data/caddy-data/caddy-config）。所以每个实例靠 `COMPOSE_PROJECT_NAME` 隔离数据，且 `docker compose down -v` **删不掉**它们（external 卷不归 compose 管）。

## 开发与测试工作流

改完代码本地验证，**只动 debug 实例，严禁碰 release**——release 实例承载真实数据，`.env.release` 是生产配置。

- 起/重启 debug 栈（改代码后必须 `--build` 才会重打镜像）：
  ```
  docker compose --env-file .env.debug up --build -d
  ```
- 拆 debug 栈：
  ```
  docker compose --env-file .env.debug down
  ```
  `.env.debug` / `.env.release` 自包含（含 `COMPOSE_PROJECT_NAME` + `COMPOSE_PROFILES`），靠 `--env-file` 选实例，不要混用。

- 几个 compose 坑：
  - 改了 `studio.publish_release` 等随镜像走的 `.py`，必须 `up --build` 才生效。
  - 改 `edge/Caddyfile` 或 `edge/frpc.toml`（单文件 bind mount）→ 加 `--force-recreate`。
  - 删过某个 service → 加 `--remove-orphans`。
  - `down -v` 在本仓库**对数据安全**（卷是 external，删不掉）；但**throwaway 实验绝不复用真实的 `COMPOSE_PROJECT_NAME` / 卷名**——曾因复用真名把 release 的 pgdata 抹掉过。临时测试用随机 project+volume 名。

- 发版（**不在常规测试里做，需明确授权**）：`scripts/publish-release.sh <env-file> <publish|list|promote> [args]`，在 compose 网络里跑 `studio.publish_release`。
- 测试 / seed / 压测 wrapper：`scripts/{test.sh,seed.py,loadtest.py}`，同样 env-file-first。

## 版本号与发版

仓库只有**两个真相源版本号**，各对应一个独立发布单元，两者节奏/受众不同，**不强行对齐**：

| 单元 | 真相源 | tag | 受众 |
| --- | --- | --- | --- |
| 客户端（Electron + sidecar，打成一个安装包） | `desktop/package.json` | `v<x.y.z>` | 用户 |
| 服务端（api + admin_web + 迁移，一起部署） | `services/api/pyproject.toml` | `server-v<x.y.z>`（手动，将来用） | 运维 |

其余带版本字段的文件**都不是发布版本**，已在文件内注释冻结，勿当版本 bump：`desktop/sidecar/pyproject.toml`（sidecar 随客户端走）、`services/admin_web/package.json`（随服务端部署）。`package-lock.json` 的 version 是 npm 从 `package.json` 自动同步的镜像，**勿手改**。

桌面发版流程（tag 在 draft **转正**那一刻才真正写进 git，不是构建时）：

```
cd desktop && npm version patch --no-git-tag-version   # 改 package.json + package-lock，npm 默认会建 commit+git tag，故关掉让 action 独占 tag
git add desktop/package.json desktop/package-lock.json && git commit -m "chore(desktop): bump version to x.y.z" && git push
gh workflow run build-desktop.yml                      # 仅手动；读 package.json → 建 draft release（tag v<x.y.z>）+ 传安装包
# → 在 GitHub 把 draft 转正（此刻 git tag v<x.y.z> 落地）
# → scripts/publish-release.sh <env> publish --version x.y.z --platform <win|mac> --file <安装包> --latest   # 登记进 release DB，门户才认
```

tag 命名约束：客户端 tag 由 `electron-builder.yml`（github publisher）与 `build-desktop.yml` 共同决定，electron-builder 只支持 `vPrefixedTagName` 开关、**不支持自定义前缀**，故客户端固定 `v<x.y.z>`；服务端用 `server-v<x.y.z>` 建立命名空间避让，不冲突。

## 阅读顺序

1. 先读本 SKILL.md（地图 + 不变量）。
2. 改 Bridge daemon：`desktop/sidecar/laborster_bridge/`（runtime.py 起）。
3. 改 API/schema：`services/api/studio/models.py` + `routers/`。
4. 改 chat：`services/api/chat/`。
5. 改 worker/reply/distill：`services/api/studio/worker.py`。
6. 改用户 UI：`desktop/src/`（StudioViews.tsx / ChatSandbox.tsx）；公开站点 `services/portal/index.html`；admin 面板 `services/admin_web/src/`。
7. 改部署：`docker-compose.yaml` + `edge/`。
8. 动手前对照核心不变量。
