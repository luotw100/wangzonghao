# Studio Backend API / Studio 后端 API

## 入口文件

- FastAPI app：`studio/main.py`（薄入口，lifespan 中执行 `run_migrations()`，mount 各 router）。
- DB：`studio/db.py`。
- Models：`studio/models.py`。
- Schemas：`studio/schemas.py`。
- Auth utils：`studio/auth_utils.py`。
- LLM client：`studio/clients.py`。
- 依赖：`studio/deps.py`。
- Migration：`studio/migrate.py`（`ensure_schemas()` + `alembic upgrade head`）。
- Routers：`studio/routers/`（auth, personas, bridges, inboxes, conversations, distill, bridge_protocol）。Chat 子包路由在 `services/api/chat/routers/`，由 `studio/main.py` 一并挂在 `/api/chat/*`。Admin 是独立 FastAPI app（`services/api/admin/app.py`），单独进程，CF Access 鉴权。

## DB 初始化

`db.py` 当前行为：

- 读取 `DATABASE_URL` 和 S3 环境变量（`S3_ENDPOINT`、`S3_PUBLIC_URL`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`），缺失时报错。`S3_PUBLIC_URL` 用于生成媒体上传/下载的 presigned URL。
- PostgreSQL 连接池：`pool_size=10, max_overflow=20`。
- 暴露 `Base`、`SessionLocal`、`get_db()`、`utc_now()`。
- `utc_now()` 返回时区感知的 UTC datetime。

`migrate` compose service（`uv run python -m studio.migrate`）一次性跑 `ensure_schemas()` + `alembic upgrade head`，user-api / user-worker / admin-api 都依赖它 `service_completed_successfully`。

## Auth

### Web auth

`get_account()` 当前流程：

1. 解析 Bearer token。
2. hash token 后查询 `AuthSession`；不存在拒绝。
3. `expires_at` 已过期则删除该 session 并拒绝。
4. 经 `AuthSession.account` 加载 Account；拒绝缺失或非 active account。
5. 续期 `AuthSession.expires_at`（now + 24h）。

### Bridge auth

`get_authed_bridge()` 当前流程（与 web auth 共用 `auth_sessions`，account 粒度）：

1. 解析 Bearer token。
2. hash token 后查询 `AuthSession`；不存在拒绝；`expires_at` 过期则删除并拒绝。
3. 经 `AuthSession.account` 加载 Account；拒绝缺失或非 active account。
4. 无 `X-Machine-Id` 头拒绝；按 `(account_id, X-Machine-Id)` 查 Bridge。
5. Bridge 不存在或 status 是 revoked 时拒绝。
6. 续期 `AuthSession.expires_at`（now + 24h）。

## Serializers

`main.py` 当前使用手写 serializer（非 Pydantic response model）：

- `s_account()`
- `s_persona()`
- `s_bridge()`
- `s_inbox()`
- `s_conversation()`
- `s_message()`：包含 `msg_type` 字段。
- `s_distill_job()`
- `s_outbound()`：包含 `msg_type` 字段，可附加 `peer_platform_id`。

## Ownership helpers

这些 helper 按 account 校验归属；每个账号只能读写自己的数据：

- `get_account_persona()`。
- `get_account_bridge()`。
- `get_account_inbox()`。
- `get_account_conversation()`：Conversation 通过 join Inbox 校验 account。

## Schemas

`schemas.py` 使用 `StrictModel(extra='forbid')`。

主要 request models：

- `LoginRequest`。
- `OwnPasswordChange`。
- `PersonaCreate`、`PersonaUpdate`。
- `InboxUpdate`——Inbox 仅由 bridge handshake 自动创建，没有独立创建 schema。
- `ConversationUpdate`。
- `DistillJobCreate`。
- `OutboundCreate`：包含 `msg_type` 和 `content`。
- Bridge protocol v2：`BridgeHandshake`、`BridgeInboxClaim`、`BridgeRegisterInboxes`、`BridgeIncomingMessage`、`BridgeIncomingBatch`、`BridgeConversationItem`、`BridgeConversationsUpsert`。无 ack / 媒体 schema。

## Web API endpoints

### Health/Auth

- `GET /api/health`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `PUT /api/auth/password`

`PUT /api/auth/password` 要求当前密码和新密码，成功后会删除该账号所有 Web AuthSession（web 与所有 Bridge 一并下线）。

user-api 上没有账号管理或 Provider 管理端点。这些都在独立的 admin-api 进程上，挂 `/api/admin/*`（CF Access 鉴权）：`POST /api/admin/accounts`、`POST /api/admin/accounts/{id}/reset-password`、`PATCH /api/admin/accounts/{id}/distill-provider`、`POST /api/admin/providers`、`PATCH /api/admin/providers/{id}`、`DELETE /api/admin/providers/{id}` 等。详见 `services/api/admin/app.py`。

### Persona

- `GET /api/personas`
- `POST /api/personas`
- `GET /api/personas/{persona_id}`
- `PUT /api/personas/{persona_id}`
- `DELETE /api/personas/{persona_id}`

Delete 当前在 Persona 被任一 Conversation 引用时返回 409。

### Bridges

- `GET /api/bridges`
- `DELETE /api/bridges/{bridge_id}`

删除 Bridge 的当前语义是 revoke：

1. 找到当前 Bridge 绑定的 Inbox ids。
2. 把这些 Inbox 下 pending outbound 标成 canceled。
3. 解绑 Inboxes。
4. Bridge status 置 `revoked`（不动 session；鉴权按 `(account, machine_id)` 解析到该行后因 revoked 拒绝）。

### Inboxes

- `GET /api/inboxes`
- `GET /api/inboxes/{inbox_id}`
- `PUT /api/inboxes/{inbox_id}`
- `DELETE /api/inboxes/{inbox_id}`
Inbox 仅由 Bridge handshake 自动 upsert 创建，没有 `POST /api/inboxes` 端点。UI 主要编辑默认值。

### Conversations

- `GET /api/conversations[?inbox_id=...]` — 列表（带 latest_message、message_count、member_count）
- `GET /api/conversations/{conversation_id}` — 详情（含 card_md + members）
- `GET /api/conversations/{conversation_id}/messages?limit=N`
- `PATCH /api/conversations/{conversation_id}` — 编辑 takeover/reply_policy/persona/display_name/card_md/status
- `POST /api/conversations/{conversation_id}/outbound` — 手工 seed outbound (debug)

`MessageRead` 含 computed `from_self = (sender_id IS NULL)`。

### Distill

- `GET /api/distill-jobs`
- `POST /api/distill-jobs`
- `GET /api/distill-jobs/{job_id}`

`DistillJobCreate`：`conversation_ids: list[str]`（非空）、`target_persona_id: str | None`。Create 逻辑：dedup `conversation_ids` 并逐个 `get_account_conversation` 校验归属；job `account_id` 取首个 conversation 所属 Inbox 的 account；设置了 `target_persona_id` 才校验 Persona 归属；拒绝与已有 pending/running job 的 `conversation_ids` 有交集，或（指定了 persona 时）该 persona 已有 in-flight job。Provider 取 `account.distill_provider_id`，无法在创建时指定。

## Bridge API

详见 `docs/bridge/protocol.md`。v2 共 8 个端点：

- `POST /api/bridge/handshake`
- `POST/GET /api/bridge/inboxes`
- `POST /api/bridge/heartbeat`
- `POST /api/bridge/incoming`
- `GET /api/bridge/outbound`
- `POST /api/bridge/conversations`
- `GET /api/bridge/takeovers`

砍掉：`/peers`、`/active-peers`、`/outbound/{id}/ack`、`/media/*`。

## ProviderClient

`clients.py` 中 `ProviderClient` 当前行为：

- 持有 `httpx.AsyncClient`。
- POST `{base_url}/chat/completions`。
- body 包含 `model`、`messages`、`temperature=0.7`。
- 非 2xx 抛错。
- 返回 `(content, usage)`。

## Admin API

`services/api/admin/app.py` 是独立 FastAPI app（compose service `admin-api`，端口 23457，CF Access 在边缘鉴权，进程内无 auth middleware）。

当前端点：

- `GET/POST /api/admin/accounts`
- `POST /api/admin/accounts/{id}/reset-password`
- `PATCH /api/admin/accounts/{id}/distill-provider`
- `GET /api/admin/providers`
- `GET /api/admin/allowed-base-urls`
- `POST /api/admin/providers`
- `PATCH /api/admin/providers/{id}`
- `DELETE /api/admin/providers/{id}`
- `GET /api/admin/conversations`
- `PATCH /api/admin/conversations/{id}/provider`

`POST /api/admin/providers` 校验 `base_url` 在 `ALLOWED_BASE_URLS` 白名单。最早创建的 ProviderConfig 作为新 Conversation / 新 Account 的默认 Provider（`studio.deps.pick_first_provider`）。account id 生成规则是 `acc_{完整 UUID hex}`，Create 显式设置 active status 和 timestamps。