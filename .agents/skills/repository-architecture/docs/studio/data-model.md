# Studio Data Model / Studio 数据模型

## 当前模型原则

`models.py` 文件头明确写了当前原则：Studio 不使用 SQLAlchemy column-level defaults。每次 INSERT 应由应用层显式传入字段值。迁移中使用 `server_default` 仅为兼容已有数据。

## 数据库

Studio 使用 PostgreSQL。Schema 由 Alembic 迁移管理。所有 DateTime 列使用 `timezone=True`（存储为 `timestamptz`）。所有自增主键使用 `BigInteger`。所有 String 列有明确长度限制，无长度限制的用 `Text`。枚举字段使用 `CheckConstraint` 约束合法值。JSON 列使用 PostgreSQL 原生 `JSONB`。所有非自增 ID 使用 `new_id(prefix)` 生成（128 bit 完整 UUID hex），列类型为 `String(48)`。Session ID 使用 `hash_token(token)`（SHA-256，64 hex 字符），列类型为 `String(64)`。

## Tables

### `accounts` — `Account`

字段：

- `id`：`String(48)`，格式 `acc_` + 完整 UUID hex。
- `username`：`String(64)`，唯一。
- `password_hash`：`String(128)`。
- `display_name`：`String(128)`，nullable。
- `role`：`String(16)`，CHECK `admin | user`。
- `status`：`String(16)`，CHECK `active | disabled`。
- timestamps（`timestamptz`）和 `last_login_at`（nullable）。

### `auth_sessions` — `AuthSession`

Web 登录 session。

- `id`：`String(64)`，token sha256 主键。
- `account_id`：`String(48)`。
- `created_at`、`last_seen_at`（`timestamptz`）。

### `provider_configs` — `ProviderConfig`

OpenAI-compatible LLM Provider。

- `id`：`String(48)`，格式 `p_` + 完整 UUID hex。
- `owner_account_id`：`String(48)`。
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

- `id`：`String(48)`，格式 `ps_` + 完整 UUID hex。
- `account_id`：`String(48)`。
- `name`：`String(128)`。
- `persona_md`：`Text`，nullable。
- `timezone`：`String(64)`，IANA 时区（如 `"Asia/Shanghai"`），`server_default="UTC"`，应用层默认 `"UTC"`。
- `status`：`String(16)`，CHECK `active | archived`。
- unique `(account_id, name)`。

### `bridges` — `Bridge`

本地 daemon 注册行。

- `id`：`String(48)`，格式 `br_` + 完整 UUID hex。
- `account_id`：`String(48)`。
- `machine_id`：`String(256)`，Studio 在首次握手时生成（`m_` + uuid hex），Bridge 本地持久化后跨重启复用。
- `status`：`String(16)`，CHECK `online | offline | revoked`。
- `last_seen_at`：nullable `timestamptz`。
- unique `(account_id, machine_id)`。

### `bridge_sessions` — `BridgeSession`

Bridge 运行时 token。

- `id`：`String(64)`，token sha256 主键。
- `bridge_id`：`String(48)`。
- `created_at`、`last_seen_at`（`timestamptz`）。

### `inboxes` — `Inbox`

平台侧身份。

- `id`：`String(48)`，格式 `ib_` + 完整 UUID hex。
- `account_id`：`String(48)`。
- `bridge_id`：`String(48)`，nullable。
- `platform`：`String(32)`。
- `display_name`：`String(256)`。
- `default_persona_id`：`String(48)`，nullable。
- `reply_provider_config_id`：`String(48)`，nullable。
- `enabled`：Boolean。
- `platform_self_id`：`String(128)`，nullable；Bridge handshake 上报。
- timestamps（`timestamptz`）。

### `contacts` — `Contact`

粉丝/对方接管单元。

- `id`：`String(48)`，格式 `ct_` + 完整 UUID hex。
- `inbox_id`：`String(48)`。
- `peer_platform_id`：`String(256)`，平台侧稳定 ID，是 Contact 的索引键。
- `display_name`：`String(256)`，展示名（mutable）。
- `card_md`：`Text`，nullable。
- `persona_id`：`String(48)`，nullable。
- `reply_provider_config_id`：`String(48)`，nullable override。
- `takeover`：Boolean。Bridge 是否上报该会话消息。`True` → Bridge 将此 peer 的本地消息上传到 Studio；`False` → Bridge 本地采集但不推送。
- `reply_policy`：`String(16)`，CHECK `disabled | autoreply`。Studio reply brain 是否自动回复。默认 `disabled`；设为 `autoreply` 后对方发消息会触发 LLM 回复。
- `pending_reply`：Boolean。
- `status`：`String(16)`，CHECK `active | archived`。
- `last_seen_platform_msg_id`：`String(256)`，nullable。
- unique `(inbox_id, peer_platform_id)`。

### `messages` — `Message`

统一消息表，全部由 Bridge incoming 写入。

- `id`：`BigInteger`，自增主键。
- `contact_id`：`String(48)`。
- `external_id`：`String(256)`。
- `role`：`String(16)`，CHECK `self | counterpart`。
- `msg_type`：`String(16)`，CHECK `text | image | audio | video | file`。
- `sender_name`：`String(256)`，nullable。
- `content`：`Text`。
- `timestamp`：`timestamptz`。
- `created_at`：`timestamptz`。
- unique `(contact_id, external_id)`。
- index `(contact_id, timestamp)`。

### `distill_jobs` — `DistillJob`

蒸馏 worker job。

- `id`：`String(48)`，格式 `dj_` + 完整 UUID hex。
- `account_id`：`String(48)`。
- `source_inbox_id`：`String(48)`。
- `target_persona_id`：`String(48)`。
- `provider_config_id`：`String(48)`。
- `status`：`String(16)`，CHECK `pending | running | done | failed`。
- `progress`：`JSONB`。
- `error_message`：`Text`，nullable。
- timestamps（`timestamptz`）。

### `outbound_messages` — `OutboundMessage`

Studio → Bridge 队列。

- `id`：`BigInteger`，自增 cursor。
- `inbox_id`：`String(48)`。
- `contact_id`：`String(48)`。
- `msg_type`：`String(16)`，CHECK `text | image | audio | video | file`。
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
- `persona_id`：`String(48)`，nullable。
- `inbox_id`：`String(48)`，nullable。
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

Contact 有两个创建入口：

**`POST /api/bridge/peers`**（Bridge 上报发现的 peer 列表）：
- `takeover = False`；`reply_policy = disabled`；`pending_reply = False`；`status = active`。
- 已有 Contact 时只更新 `display_name`，不覆盖 `takeover`/`reply_policy`。

**`POST /api/bridge/incoming`**（Bridge 推送消息时按需创建）：
- 字段初始值同上。

Contact 创建后，Contact 设置与 Inbox 默认值相互独立。

### `media_hashes` — `MediaHash`

内容哈希 → Studio S3 storage key 映射表，用于跨 Bridge 实例/重启的媒体去重。

- `id`：`BigInteger`，自增。
- `account_id`：`String(48)`。
- `content_hash`：`String(71)`，格式 `sha256:{64hexchars}`。
- `storage_key`：`String(256)`，Studio S3 key。
- unique `(account_id, content_hash)`。

Bridge 上传新媒体时写入；`POST /api/bridge/media/check-or-presign` 查询此表决定是否跳过重复上传。

## Provider 解析规则

当前 Studio Provider 由管理员维护。普通用户 UI 不展示 Provider。Reply 和 Distill 使用的 Provider 解析为：Contact override → Inbox override → 全局默认 Provider。
