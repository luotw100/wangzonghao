# Studio Backend API / Studio 后端 API

## 入口文件

- FastAPI app：`studio/main.py`（薄入口，lifespan 中执行 `run_migrations()`，mount 各 router）。
- DB：`studio/db.py`。
- Models：`studio/models.py`。
- Schemas：`studio/schemas.py`。
- Auth utils：`studio/auth_utils.py`。
- LLM client：`studio/clients.py`。
- CLI：`studio/cli.py`。
- Serializers：`studio/serializers.py`。
- 依赖：`studio/deps.py`。
- Migration：`studio/migrate.py`（封装 Alembic `upgrade head`）。
- Routers：`studio/routers/`（auth, accounts, providers, personas, bridges, inboxes, contacts, distill, bridge_protocol）。

## DB 初始化

`db.py` 当前行为：

- 读取 `DATABASE_URL` 和 S3 环境变量（`S3_ENDPOINT`、`S3_PUBLIC_URL`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`），缺失时报错。`S3_PUBLIC_URL` 用于生成媒体上传/下载的 presigned URL。
- PostgreSQL 连接池：`pool_size=10, max_overflow=20`。
- 暴露 `Base`、`SessionLocal`、`get_db()`、`utc_now()`。
- `utc_now()` 返回时区感知的 UTC datetime。

`main.py` 通过 FastAPI lifespan 在 startup 时调用 `run_migrations()`（`studio/migrate.py`），执行 `alembic upgrade head`。Worker 和 CLI 在各自的入口也调用 `run_migrations()`。

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
- `s_contact()`
- `s_message()`：包含 `msg_type` 字段。
- `s_distill_job()`
- `s_outbound()`：包含 `msg_type` 字段，可附加 `peer_platform_id`。

## Ownership helpers

这些 helper 按 account 校验归属；每个账号只能读写自己的数据：

- `get_account_persona()`。
- `get_account_bridge()`。
- `get_account_inbox()`。
- `get_account_contact()`：Contact 通过 join Inbox 校验 account。

## Schemas

`schemas.py` 使用 `StrictModel(extra='forbid')`。

主要 request models：

- `LoginRequest`。
- `OwnPasswordChange`。
- `PersonaCreate`、`PersonaUpdate`。
- `InboxUpdate`——Inbox 仅由 bridge handshake 自动创建，没有独立创建 schema。
- `ContactUpdate`。
- `DistillJobCreate`。
- `OutboundCreate`：包含 `msg_type` 和 `content`。
- Bridge protocol：`BridgeHandshakeInbox`、`BridgeHandshake`、`BridgeIncomingMessage`（含 `msg_type`）、`BridgeIncomingBatch`、`BridgeOutboundAck`、`BridgeMediaPresignRequest`。

## Web API endpoints

### Health/Auth

- `GET /api/health`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `PUT /api/auth/password`

`PUT /api/auth/password` 要求当前密码和新密码，成功后会删除该账号所有 Web AuthSession（web 与所有 Bridge 一并下线）。

Studio 没有 admin 概念，没有任何账号管理 / Provider 管理的 Web API。账号开通和 Provider 维护只能用服务端 `studio.cli`（见 CLI 小节）。

### Persona

- `GET /api/personas`
- `POST /api/personas`
- `GET /api/personas/{persona_id}`
- `PUT /api/personas/{persona_id}`
- `DELETE /api/personas/{persona_id}`

Delete 当前在 Persona 被 Inbox default 或 Contact 引用时返回 409。

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
- `GET /api/inboxes/{inbox_id}/contacts`
- `POST /api/inboxes/{inbox_id}/outbound`

Inbox 仅由 Bridge handshake 自动 upsert 创建，没有 `POST /api/inboxes` 端点。UI 主要编辑默认值。

`POST /api/inboxes/{inbox_id}/outbound` 是手工 seed outbound 的 debug endpoint。

### Contacts / Conversations

- `GET /api/contacts/{contact_id}`
- `GET /api/conversations`
- `GET /api/contacts/{contact_id}/messages?limit=N`
- `PUT /api/contacts/{contact_id}`

`GET /api/conversations` 当前返回 Contact + Inbox + latest_message + message_count，并按 latest timestamp 或 contact updated_at 排序。

### Distill

- `GET /api/distill-jobs`
- `POST /api/distill-jobs`
- `GET /api/distill-jobs/{job_id}`

`DistillJobCreate`：`contact_ids: list[str]`（非空）、`target_persona_id: str | None`、`provider_config_id: str | None`。Create 逻辑：dedup `contact_ids` 并逐个 `get_account_contact` 校验归属；job `account_id` 取首个 contact 所属 Inbox 的 account；设置了 `target_persona_id` 才校验 Persona 归属；拒绝与已有 pending/running job 的 `contact_ids` 有交集，或（指定了 persona 时）该 persona 已有 in-flight job。`provider_config_id` 可空；为空时解析全局默认 Provider。普通 user 不能显式指定 Provider。

## Bridge API

Bridge protocol endpoints 见 `docs/bridge/protocol.md`。当前包含：

- `POST /api/bridge/handshake`
- `POST /api/bridge/heartbeat`
- `POST /api/bridge/incoming`
- `GET /api/bridge/outbound`
- `POST /api/bridge/outbound/{outbound_id}/ack`
- `POST /api/bridge/media/presign-upload` — Bridge 获取 Studio S3 上传 presigned URL
- `GET /api/bridge/media/{storage_key}` — Bridge 获取 Studio S3 下载 presigned URL（302 redirect）

## ProviderClient

`clients.py` 中 `ProviderClient` 当前行为：

- 持有 `httpx.AsyncClient`。
- POST `{base_url}/chat/completions`。
- body 包含 `model`、`messages`、`temperature=0.7`。
- 非 2xx 抛错。
- 返回 `(content, usage)`。

## Studio CLI

`python -m studio.cli` 当前命令：

- `create-account`（`--username --password --display-name`）
- `list-accounts`
- `reset-password`（`--username --password`）
- `create-provider`（`--name --base-url [--api-key] --default-model`）：校验 `base_url` 在 `ALLOWED_BASE_URLS` 白名单，清掉已有 default，新建者 `is_default=True`。
- `list-providers`
- `delete-provider`（`--id`）

account id 生成规则是 `acc_{完整 UUID hex}`（128 bit，无截断）。Create 显式设置 active status 和 timestamps。CLI 输出使用带颜色的表格。账号开通和 Provider 维护的唯一路径就是这个 CLI——没有任何 Web 入口。