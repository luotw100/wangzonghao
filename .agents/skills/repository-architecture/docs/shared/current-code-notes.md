# Current Code Notes / 当前代码注意点

本文只记录当前代码事实和仓库中已存在文件的状态，不记录规划。

## Studio Vite proxy

`services/user_web/vite.config.ts` 当前把 `/api` proxy 到 `localhost:23456`。

## Bridge Studio URL

`bridge/laborster_bridge/config.py` 当前硬编码 `STUDIO_BASE_URL = "https://studio.laborster.com"`，无环境变量、无 CLI 覆盖。Chat 沙箱同主机，路径加 `/api/chat` 前缀。

## Model defaults

Models 不使用 SQLAlchemy column defaults；insert 路径必须显式写入状态、时间戳和布尔值。

## Database

单 PG 实例，三 schema（`auth` / `studio` / `chat`）。Alembic 管理迁移；启动时通过 `services/api/studio/migrate.py` 跑 `ensure_schemas()` + `alembic upgrade head`。`alembic_version` 表落在 `studio` schema。所有 DateTime 列存为 `timestamptz`（时区感知 UTC），自增主键 `BigInteger`。`studio.db.Base` 与 `chat.db.Base` 是两套独立 Base、共享 engine + 连接池。

## ID 生成

所有非自增主键使用 `new_id(prefix)`，格式 `{prefix}_{uuid4().hex}`（128 bit 熵，碰撞概率可忽略）。

- Studio 子包：`services/api/studio/deps.py:new_id`。
- Chat 子包：`services/api/chat/ids.py:new_id`。

Auth/AuthSession 的 ID 用 `hash_token(secrets.token_urlsafe(32))`（SHA-256，64 hex 字符）。

## API 模块结构

`services/api/studio/main.py` 是薄入口，挂 studio 路由（`studio/routers/`：auth、personas、bridges、inboxes、conversations、distill、bridge_protocol）+ chat 子包路由（`chat/routers/`，前缀 `/api/chat/*`）。admin 是独立 FastAPI app `services/api/admin/app.py`（CF Access 鉴权，无 in-app auth）。序列化在各自 `schemas.py`，鉴权 + ownership helpers 在 `studio/deps.py`。

## Inbox 创建

Inbox 由 Bridge 通过 `POST /api/bridge/inboxes` 注册（upsert），没有独立的创建 API。

## Bridge offline 状态

Studio worker 中 `BridgeOfflineScanner` 每 30s 扫描 `last_seen_at` 超过 45s 的 online Bridge，将其标为 offline。heartbeat 收到请求时会实时标回 online。offline 不影响已入队的 outbound 消息——它们会在 Bridge 恢复在线后被投递。

## Bridge token

Bridge 持有的是 account session token（与 web 控制台共用 Studio `auth_sessions`，不再有独立 bridge session 表），保存在状态目录下按账号隔离的 SQLite `state.db` 的 `kv` 表中（`studio_token` 键），`machine_id` 同存该表；各 Chat 账号 token 也存在 `kv` 表里。磁盘上不存任何密码。每个 `/api/bridge/*` 请求带 `Authorization: Bearer studio_token` + `X-Machine-Id: machine_id`，服务端按 `(account, machine_id)` 解析 Bridge 行。重启直接复用 token，无需密码、无需重新 handshake；channel 集合通过 `POST /api/bridge/inboxes` 注册。token 24h 滑动续期；只有 401 时才清 `studio_token` 并提示用密码重新 `/login`。改密码会按 account 删除全部 session（web 与所有 Bridge 一并下线）。

`on_auth_error` 带 token 身份保护：只在「当前磁盘 `studio_token` == 本 runtime 启动时的 token」才清除，且 runtime 已 `stop()` 后不触发。`LocalStore` 关闭后所有方法安全 no-op；未发消息留 unsent，下次重扫，Studio 按 `(conversation_id, client_id)` 去重。

## Provider 管理

Studio Provider 通过 admin-api 或 CLI 管理。最早创建的 ProviderConfig 作为新 Conversation / 新 Account 的默认 Provider（`pick_first_provider`）。`Conversation.provider_id` 控 reply LLM 路由，`Account.distill_provider_id` 控 distill LLM 路由。无系统级 fallback。
