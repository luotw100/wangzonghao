# Studio Data Model / Studio 数据模型

## 当前模型原则

`models.py` 文件头明确写了当前原则：Studio 不使用 SQLAlchemy column-level defaults。每次 INSERT 应由应用层显式传入字段值。

## 数据库

Studio 使用 PostgreSQL。Schema 由 Alembic 迁移管理。所有 DateTime 列使用 `timezone=True`（存储为 `timestamptz`）。所有自增主键使用 `BigInteger`。所有 String 列有明确长度限制，无长度限制的用 `Text`。枚举字段使用 `CheckConstraint` 约束合法值。JSON 列使用 PostgreSQL 原生 `JSONB`。

## Tables

### `accounts` — `Account`

字段：

- `id`：`String(32)`，格式 `acc_...`。
- `username`：`String(64)`，唯一。
- `password_hash`：`String(128)`。
- `display_name`：`String(128)`，nullable。
- `role`：`String(16)`，CHECK `admin | user`。
- `status`：`String(16)`，CHECK `active | disabled`。
- timestamps（`timestamptz`）和 `last_login_at`（nullable）。

### `auth_sessions` — `AuthSession`

Web 登录 session。

- `id`：`String(64)`，token sha256 主键。
- `account_id`：`String(32)`。
- `created_at`、`last_seen_at`（`timestamptz`）。

### `provider_configs` — `ProviderConfig`

OpenAI-compatible LLM Provider。

- `id`：`String(32)`，格式 `p_...`。
- `owner_account_id`：`String(32)`。
- `name`：`String(128)`。
- `base_url`：`String(512)`。
- `api_key`：`Text`，nullable。
- `default_model`：`String(128)`。
- `scope`：`String(16)`，CHECK `global`。
- `status`：`String(16)`，CHECK `active | disabled`。
- `is_default`：Boolean。
- timestamps（`timestamptz`）。

### `personas` — `Persona`

人设 markdown 资产。

- `id`：`String(32)`，格式 `ps_...`。
- `account_id`：`String(32)`。
- `name`：`String(128)`。
- `persona_md`：`Text`，nullable。
- `status`：`String(16)`，CHECK `active | archived`。
- unique `(account_id, name)`。

### `bridges` — `Bridge`

本地 daemon 注册行。

- `id`：`String(32)`，格式 `br_...`。
- `account_id`：`String(32)`。
- `hostname`：`String(256)`。
- `display_name`：`String(256)`。
- `status`：`String(16)`，CHECK `online | offline | revoked`。
- `last_seen_at`：nullable `timestamptz`。
- unique `(account_id, hostname)`。

### `bridge_sessions` — `BridgeSession`

Bridge 运行时 token。

- `id`：`String(64)`，token sha256 主键。
- `bridge_id`：`String(32)`。
- `created_at`、`last_seen_at`（`timestamptz`）。

### `inboxes` — `Inbox`

平台侧身份。

- `id`：`String(32)`，格式 `ib_...`。
- `account_id`：`String(32)`。
- `bridge_id`：`String(32)`，nullable。
- `platform`：`String(32)`。
- `display_name`：`String(256)`。
- `default_persona_id`：`String(32)`，nullable。
- `reply_provider_config_id`：`String(32)`，nullable。
- `enabled`：Boolean。
- `platform_self_id`：`String(128)`，nullable；Bridge handshake 上报。
- timestamps（`timestamptz`）。

### `contacts` — `Contact`

粉丝/对方接管单元。

- `id`：`String(32)`，格式 `ct_...`。
- `inbox_id`：`String(32)`。
- `peer_platform_id`：`String(256)`。
- `display_name`：`String(256)`。
- `card_md`：`Text`，nullable。
- `persona_id`：`String(32)`，nullable。
- `reply_provider_config_id`：`String(32)`，nullable override。
- `autoreply_enabled`：Boolean。
- `pending_reply`：Boolean。
- `status`：`String(16)`，CHECK `active | archived`。
- `last_seen_platform_msg_id`：`String(256)`，nullable。
- unique `(inbox_id, peer_platform_id)`。

### `archives` — `Archive`

上传的 WeFlow 源文件 metadata。

- `id`：`String(32)`，格式 `a_...`。
- `account_id`：`String(32)`。
- `inbox_id`：`String(32)`。
- `filename`：`String(256)`。
- `file_path`：`String(512)`。
- `file_hash`：`String(64)`，sha256 前 16 位。
- `platform_self_id`：`String(128)`。
- `message_count`：Integer。
- `contact_count`：Integer。
- `uploaded_at`（`timestamptz`）。
- unique `(account_id, file_hash)`。

### `messages` — `Message`

统一消息表，包含 archive 和 live。

- `id`：`BigInteger`，自增主键。
- `contact_id`：`String(32)`。
- `archive_id`：`String(32)`，nullable。
- `external_id`：`String(256)`。
- `source`：`String(16)`，CHECK `archive | live`。
- `role`：`String(16)`，CHECK `self | counterpart`。
- `sender_name`：`String(256)`，nullable。
- `content`：`Text`。
- `timestamp`：`timestamptz`。
- `archive_msg_idx`：Integer，nullable。
- `created_at`：`timestamptz`。
- unique `(contact_id, external_id)`。
- index `(contact_id, timestamp)`。

### `distill_jobs` — `DistillJob`

蒸馏 worker job。

- `id`：`String(32)`，格式 `dj_...`。
- `account_id`：`String(32)`。
- `source_inbox_id`：`String(32)`。
- `target_persona_id`：`String(32)`。
- `provider_config_id`：`String(32)`。
- `status`：`String(16)`，CHECK `pending | running | done | failed`。
- `progress`：`JSONB`。
- `error_message`：`Text`，nullable。
- timestamps（`timestamptz`）。

### `outbound_messages` — `OutboundMessage`

Studio → Bridge 队列。

- `id`：`BigInteger`，自增 cursor。
- `inbox_id`：`String(32)`。
- `contact_id`：`String(32)`。
- `content`：`Text`。
- `send_after`：`timestamptz`。
- `status`：`String(16)`，CHECK `pending | delivered | failed | canceled`。
- `delivered_at`：`timestamptz`，nullable。
- `failed_reason`：`Text`，nullable。
- `created_at`：`timestamptz`。
- index `(inbox_id, id)`。

### `llm_logs` — `LlmLog`

LLM 调用日志。

- `id`：`BigInteger`，自增。
- `purpose`：`String(16)`，CHECK `distill | reply`。
- `persona_id`：`String(32)`，nullable。
- `inbox_id`：`String(32)`，nullable。
- `request_messages`：`Text`。
- `response_raw`：`Text`。
- `model`：`String(128)`，nullable。
- `created_at`：`timestamptz`。

## 关系图

```text
Account
  may own ProviderConfig as admin creator
  owns Persona
  owns Bridge
  owns Inbox
  owns Archive
  owns DistillJob

Bridge
  owns BridgeSession
  serves Inbox via Inbox.bridge_id

Inbox
  owns Contact
  references default Persona
  optionally references ProviderConfig override

Contact
  owns Message
  owns OutboundMessage
  references Persona
  optionally references ProviderConfig override

Archive
  owns imported Message rows

DistillJob
  reads source Inbox messages
  writes target Persona and Contact cards
```

## 创建时继承规则

Bridge incoming 创建 Contact 时：

- `persona_id = inbox.default_persona_id`。
- `reply_provider_config_id = inbox.reply_provider_config_id`。
- `autoreply_enabled = False`。
- `pending_reply = False`。

Archive ingest 创建 Contact 时：

- `persona_id = inbox.default_persona_id`。
- `reply_provider_config_id = inbox.reply_provider_config_id`。
- `autoreply_enabled = False`。
- `pending_reply = False`。
- `status = active`。

Contact 创建后，Contact 设置与 Inbox 默认值相互独立。

## Provider 解析规则

当前 Studio Provider 由管理员维护。普通用户 UI 不展示 Provider。Reply 和 Distill 使用的 Provider 解析为：Contact override → Inbox override → 全局默认 Provider。