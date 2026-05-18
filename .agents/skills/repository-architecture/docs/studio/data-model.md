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
- `status`：`String(16)`，CHECK `active | disabled`。
- timestamps（`timestamptz`，`created_at` / `updated_at`）。

### `auth_sessions` — `AuthSession`

Web 控制台与 Bridge daemon 共用的唯一 session 表，account 粒度，不含客户端判别字段。Bridge 身份不在 token 里——由认证出的 account + `X-Machine-Id` 头解析。

- `id`：`String(64)`，token sha256 主键。
- `account_id`：`String(48)`，FK，索引。
- `expires_at`：`timestamptz`，NOT NULL，24h 滑动续期。
- `created_at`：`timestamptz`。
- `account = relationship("Account")`。
- 撤销是 account 粒度的唯一安全控制（`revoke_account_sessions`）：改密码删除该 account 全部 session。

### `provider_configs` — `ProviderConfig`

OpenAI-compatible LLM Provider。

- `id`：`String(48)`，格式 `p_` + 完整 UUID hex。
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

### `inboxes` — `Inbox`

平台侧身份。

- `id`：`String(48)`，格式 `ib_` + 完整 UUID hex。
- `account_id`：`String(48)`。
- `bridge_id`：`String(48)`，nullable。
- `platform`：`String(32)`。
- `display_name`：`String(256)`。
- `default_persona_id`：`String(48)`，nullable。
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
- `authored_by`：`String(16)`，CHECK 仅 `unknown`，`server_default="unknown"`。预留的来源标识位；目前只有 `unknown` 一个取值，将来可能加 `ai` / `human`。Bridge incoming 写入时应用层显式传 `MessageAuthoredBy.UNKNOWN`，蒸馏目前不读这列。
- `msg_type`：`String(16)`，CHECK `text | image | audio | video | file`。
- `sender_name`：`String(256)`，nullable。
- `content`：`Text`。
- `timestamp`：`timestamptz`。
- `created_at`：`timestamptz`。
- unique `(contact_id, external_id)`。
- index `(contact_id, timestamp)`。

### `distill_jobs` — `DistillJob`

蒸馏 worker job。一个 job = 一组 contact + 可选 target persona（见 [worker-reply-distill](worker-reply-distill.md)）。

- `id`：`String(48)`，格式 `dj_` + 完整 UUID hex。
- `account_id`：`String(48)`。
- `contact_ids`：`JSONB`，要处理的 contact id 列表（长度 1..N）。长度 1 = 单粉丝关系卡刷新。
- `target_persona_id`：`String(48)`，**nullable**。设置时同时覆盖该 persona 的 `persona_md`；为 null 时只写 card、不动任何 persona。
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
ProviderConfig
  单个全局配置，无 owner，由服务端 CLI 维护

Account
  owns Persona
  owns Bridge
  owns Inbox
  owns DistillJob
  owns AuthSession (web 与 Bridge 共用)

Bridge
  serves Inbox via Inbox.bridge_id

Inbox
  owns Contact
  references default Persona

Contact
  owns Message
  owns OutboundMessage
  references Persona

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

Studio Provider 是单个全局配置，由运维通过 `studio.cli create-provider` 维护（最新创建者 `is_default=True`，旧的清除）。没有 per-Inbox / per-Contact override。Reply 和 Distill 恒用 `get_default_provider` 返回的全局默认 Provider；无可用默认 Provider 时 distill 创建返回 409、reply 跳过。
