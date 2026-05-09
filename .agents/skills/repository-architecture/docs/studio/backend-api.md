# Studio Backend API / Studio 后端 API

## 入口文件

- FastAPI app：`studio/main.py`（薄入口，仅 mount 各 router）。
- DB：`studio/db.py`。
- Models：`studio/models.py`。
- Schemas：`studio/schemas.py`。
- Auth utils：`studio/auth_utils.py`。
- LLM client：`studio/clients.py`。
- CLI：`studio/cli.py`。
- Serializers：`studio/serializers.py`。
- 依赖：`studio/deps.py`。
- Routers：`studio/routers/`（auth, accounts, providers, personas, bridges, inboxes, contacts, archives, bridge_protocol）。

## DB 初始化

`db.py` 当前行为：

- 读取 `STUDIO_STORAGE_DIR`，缺失时报错。
- SQLite 文件是 `${STUDIO_STORAGE_DIR}/studio.db`。
- 暴露 `Base`、`SessionLocal`、`get_db()`、`ensure_database()`、`utc_now()`。

`main.py` import 时调用 `ensure_database()`。

## Auth

### Web auth

`get_account()` 当前流程：

1. 解析 Bearer token。
2. hash token 后查询 `AuthSession`。
3. 加载 Account。
4. 拒绝缺失或非 active account。
5. 更新 `AuthSession.last_seen_at`。

### Bridge auth

`get_authed_bridge()` 当前流程：

1. 解析 Bearer token。
2. hash token 后查询 `BridgeSession`。
3. 加载 Bridge。
4. Bridge 不存在或 status 是 revoked 时拒绝。
5. 更新 `BridgeSession.last_seen_at`。

## Serializers

`main.py` 当前使用手写 serializer（非 Pydantic response model）：

- `s_account()`
- `s_provider()`：mask API key。
- `s_persona()`
- `s_bridge()`
- `s_inbox()`
- `s_contact()`
- `s_message()`
- `s_archive()`
- `s_distill_job()`
- `s_outbound()`：可附加 `peer_platform_id`。

## Ownership helpers

这些 helper 当前用于按 account 校验归属；admin 账号可跨 account 读取，普通 user 只读自己的数据：

- `get_provider_or_404()`。
- `get_account_persona()`。
- `get_account_bridge()`。
- `get_account_inbox()`。
- `get_account_contact()`：Contact 通过 join Inbox 校验 account。

## Schemas

`schemas.py` 使用 `StrictModel(extra='forbid')`。

主要 request models：

- `LoginRequest`。
- `AccountCreate`、`AccountUpdate`、`AccountPasswordReset`、`OwnPasswordChange`。
- `ProviderConfigCreate`、`ProviderConfigUpdate`。
- `PersonaCreate`、`PersonaUpdate`。
- `InboxUpdate`——Inbox 仅由 bridge handshake 自动创建，没有独立创建 schema。
- `ContactUpdate`。
- `DistillJobCreate`。
- `OutboundChunk`、`OutboundCreate`。
- Bridge protocol：`BridgeHandshakeInbox`、`BridgeHandshake`、`BridgeIncomingMessage`、`BridgeIncomingBatch`、`BridgeOutboundAck`。

## Web API endpoints

### Health/Auth

- `GET /api/health`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `PUT /api/auth/password`

`PUT /api/auth/password` 要求当前密码和新密码，成功后会删除该账号所有 Web AuthSession。

首个 admin 没有 Web 入口——必须用 `python -m studio.cli create-account --role admin` 创建。

### Account admin

- `GET /api/accounts`
- `POST /api/accounts`
- `PUT /api/accounts/{account_id}`
- `PUT /api/accounts/{account_id}/password`
- `GET /api/admin/overview`

这些 endpoint 需要 admin role。Admin 可在 Web 设置页创建账号、列出账号、停用/启用账号和重置任意账号密码。`GET /api/admin/overview` 返回系统总览：账号列表（带每个账号的 bridges/inboxes/personas/contacts/messages 计数）和全局合计，给 Studio 前端的 admin 总览 tab 用。

### ProviderConfig

- `GET /api/provider-configs`
- `POST /api/provider-configs`
- `PUT /api/provider-configs/{provider_id}`
- `DELETE /api/provider-configs/{provider_id}`

Create 时对 `base_url` 做 `rstrip('/')`。Delete 不校验引用完整性（如 Provider 是否被 Inbox/Contact 引用）。

ProviderConfig endpoints 当前需要 admin role。创建 ProviderConfig 时会把已有 default 清掉，并把新 ProviderConfig 设为全局默认。

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
4. 删除 BridgeSession。
5. Bridge status 置 `revoked`。

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

### Archives

- `GET /api/archives`
- `POST /api/archives`

Upload 当前接收 multipart fields：

- `inbox_id`
- `self_wxid`
- `file`

处理流程：写临时文件 → 调 `ingest_archive()` → ValueError 转 400 → 删除临时文件。

### Distill

- `GET /api/distill-jobs`
- `POST /api/distill-jobs`
- `GET /api/distill-jobs/{job_id}`

Create 当前校验 source Inbox、target Persona，并拒绝同一 target Persona 已有 pending/running job。`provider_config_id` 可空；为空时解析全局默认 Provider。普通 user 不能显式指定 Provider。

## Bridge API

Bridge endpoints 见 `docs/bridge/protocol.md`。

## ProviderClient

`clients.py` 中 `ProviderClient` 当前行为：

- 持有 `httpx.AsyncClient`。
- POST `{base_url}/chat/completions`。
- body 包含 `model`、`messages`、`temperature=0.7`。
- 非 2xx 抛错。
- 返回 `(content, usage)`。

## Studio CLI

`python -m studio.cli` 当前命令：

- `create-account`
- `list-accounts`
- `reset-password`
- `set-role`

当前 account id 生成规则是 `acc_{uuid8}`（UUID 随机 8 位）。Create 显式设置 role、active status 和 timestamps。CLI 输出使用带颜色的表格；账号管理的主路径是 Studio Web 设置页。
