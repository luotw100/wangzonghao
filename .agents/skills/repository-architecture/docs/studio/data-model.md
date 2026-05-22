# Studio Data Model

## 当前模型原则

`models.py` 文件头明确写了当前原则：Studio 不使用 SQLAlchemy column-level defaults。每次 INSERT 应由应用层显式传入字段值。

## 数据库

PostgreSQL，schema 由 Alembic 管理。所有 DateTime 列 `timezone=True`（`timestamptz`）；所有 String 列有明确长度（无限制的用 `Text`）；枚举字段用 `CheckConstraint` 约束；JSON 列用 `JSONB`。非自增 ID 用 `new_id(prefix)`（128 bit UUID hex，列类型 `String(48)`）。

## Tables

### `accounts` — `Account`

- `id` `acc_{uuid_hex}`、`username` unique、`password_hash`、`display_name`、`status (active|disabled)`、`distill_provider_id` FK、timestamps。

### `auth_sessions` — `AuthSession`

Web 控制台与 Bridge daemon 共用。Bridge 身份不在 token 里——靠 `X-Machine-Id` 头在 Studio 解析。token 24h 滑动续期；改密码删除该 account 全部 session。

- `id` (token sha256, 64 hex)、`account_id` FK、`expires_at`、`created_at`。

### `provider_configs` — `ProviderConfig`

OpenAI-compatible LLM Provider。运维通过 `studio.cli` 维护。

- `id` `p_*`、`name` unique、`base_url`、`api_key` nullable、`model`、timestamps。
- `pick_first_provider(db)` 返回 created_at 最早的一条——新 Account / 新 Conversation 用作种子。

### `personas` — `Persona`

- `id` `ps_*`、`account_id` FK、`name`、`persona_md`、`timezone` (IANA)、timestamps。unique `(account_id, name)`。

### `bridges` — `Bridge`

本地 daemon 注册行。`machine_id` 由 Studio 在 handshake 签发（4 位短码，per-account 唯一），Bridge 持久化复用。

- `id` `br_*`、`account_id` FK、`machine_id`、`last_seen_at`、timestamps。unique `(account_id, machine_id)`。
- online/offline 由 `last_seen_at + 45s` 阈值派生，无缓存列。

### `inboxes` — `Inbox`

平台侧身份。

- `id` `ib_*`、`account_id` FK、`bridge_id` nullable FK、`platform (chat|wechat|feishu)`、`display_name`（Bridge 上报，不再 Studio 编 `f"{self_id}@{platform}"`）、`platform_self_id` nullable、timestamps。

### `conversations` — `Conversation`

**接管单元，单位是 conversation 不是 peer**。一个 DM 是 `kind="dm"` + 1 个 member 的 Conversation；一个群是 `kind="group"` + N 个 members。同一套 takeover / reply_policy / persona / provider 配置统一管理。

- `id` `cv_*`、`inbox_id` FK
- `platform_conversation_id` — 平台稳定 ID（DM 一般等于 peer id，群是群 id）
- `kind` CHECK `dm | group | unknown`（unknown 是 `/incoming` 创建的占位，等 `/conversations` 来补全）
- `display_name`、`card_md`、`persona_id` nullable FK、`provider_id` FK
- `takeover` Boolean、`reply_policy` (`disabled | autoreply`)、`status` (`active | archived`)
- `last_reply_round_at` nullable
- unique `(inbox_id, platform_conversation_id)`

### `conversation_members` — `ConversationMember`

会话成员。Bridge 通过 `POST /api/bridge/conversations` upsert；Studio 其它路径不动这表。

- 复合主键 `(conversation_id, peer_platform_id)`
- `display_name`、`updated_at`
- `ON DELETE CASCADE` 跟随 Conversation

### `messages` — `Message`

- `id` BigInt 自增、`conversation_id` FK
- `client_id` — Bridge 上报的稳定去重 id；adapter 决定形态（chat 用 platform `msg.id`）
- `sender_id` nullable — **NULL = 自己发**（效仿 chat 语义）。Pydantic `MessageRead.from_self` 是 computed property = `sender_id IS NULL`
- `msg_type` CHECK `text|image|audio|video|file`（当前只允许 text，其它给前向接口留口）
- `content`、`timestamp`、`created_at`
- unique `(conversation_id, client_id)`
- index `(conversation_id, timestamp)`

**砍掉的列**：`external_id` / `msg_hash` / `role` / `authored_by` / `sender_name`。`msg_hash` 由 `client_id` 取代；role 派生为 `from_self`；其余字段在 v2 协议下都不再需要。

### `outbound_messages` — `OutboundMessage`

Studio → Bridge 队列。**无 leased_at、无 ack endpoint**：PENDING → DELIVERED 通过 `/incoming` from_self 匹配 `(conversation_id, content)` 自动推进（见 protocol.md）。

- `id` BigInt 自增、`inbox_id` FK、`conversation_id` FK
- `msg_type`、`content`、`send_after`
- `status` CHECK `pending|delivered|failed|canceled`
- `delivered_at` nullable、`failed_reason`、`created_at`
- index `(inbox_id, id)`、`(status, send_after)`、`(conversation_id, created_at)`

### `distill_jobs` — `DistillJob`

蒸馏 worker job。

- `id` `dj_*`、`account_id` FK
- `conversation_ids` JSONB（要处理的 conversation id 列表，长度 1..N）
- `target_persona_id` nullable FK、`provider_config_id` FK
- `status` CHECK `pending|running|done|failed`、`progress` JSONB、`error_message`
- timestamps（`started_at` / `finished_at` nullable）

### `llm_logs` — `LlmLog`

LLM 调用日志。`persona_id` / `inbox_id` 是裸 string FK（无 ON DELETE 约束），删除 persona/inbox 仍保留历史。

- `id` BigInt 自增、`purpose` (`distill|reply`)、`persona_id` nullable、`inbox_id` nullable、`request_messages`、`response_raw`、`model` nullable、`created_at`。

## 关系图

```text
ProviderConfig
  全局配置，无 owner，CLI 维护

Account
  owns Persona / Bridge / Inbox / DistillJob / AuthSession

Bridge
  serves Inbox via Inbox.bridge_id

Inbox
  owns Conversation

Conversation
  owns ConversationMember (cascade delete)
  owns Message
  owns OutboundMessage
  references Persona, ProviderConfig
```

### Conversation 创建路径

**`POST /api/bridge/incoming`**（消息推送时按需创建占位）：
- 找不到 `(inbox_id, platform_conversation_id)` → 创建：`kind=unknown`、`display_name=platform_conversation_id`、members 空、provider=pick_first_provider、takeover=False、reply_policy=disabled、status=active。

**`POST /api/bridge/conversations`**（Bridge 启动 + diff 推送）：
- 找不到 → 同上初始字段，但 `kind` / `display_name` / members 用 payload 提供的值
- 找到 → 原地 UPDATE `kind` / `display_name` / members（**不**覆盖 takeover/reply_policy/persona/provider）
- payload 缺失的 conversation **留下不动**，不软删——平台分页/限流让一次拉取常常不完整

## 已删除的 v1 概念

- `Contact` 表（接管单元升到 Conversation）；`peer_platform_id` 列已下放到 `conversation_members`
- `media_hashes` 表（媒体管线整体下线）
- `Message.role` / `external_id` / `msg_hash` / `sender_name` / `authored_by`
