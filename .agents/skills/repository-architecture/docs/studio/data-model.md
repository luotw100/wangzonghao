# Studio Data Model / Studio 数据模型

## 当前模型原则

`models.py` 文件头明确写了当前原则：Studio 不使用 SQLAlchemy column-level defaults。每次 INSERT 应由应用层显式传入字段值。

## Tables

### `accounts` — `Account`

字段：

- `id`：`acc_...`。
- `username`：唯一登录名。
- `password_hash`。
- `display_name`。
- `role`：`admin | user`。
- `status`：`active | disabled`。
- timestamps 和 `last_login_at`。

### `auth_sessions` — `AuthSession`

Web 登录 session。

- `id`：token sha256 主键。
- `account_id`。
- `created_at`、`last_seen_at`。

### `provider_configs` — `ProviderConfig`

OpenAI-compatible LLM Provider。

- `id`：`p_...`。
- `owner_account_id`：创建该 Provider 的管理员账号。
- `name`。
- `base_url`。
- `api_key` nullable。
- `default_model`。
- `scope`：当前为 `global`。
- `status`：`active | disabled`。
- `is_default`：当前全局默认 Provider 标记。
- timestamps。

### `personas` — `Persona`

人设 markdown 资产。

- `id`：`ps_...`。
- `account_id`。
- `name`。
- `persona_md` nullable。
- `status`：`active | archived`。
- unique `(account_id, name)`。

### `bridges` — `Bridge`

本地 daemon 注册行。

- `id`：`br_...`。
- `account_id`。
- `hostname`。
- `display_name`。
- `status`：`online | offline | revoked`。
- `last_seen_at`。
- unique `(account_id, hostname)`。

### `bridge_sessions` — `BridgeSession`

Bridge runtime token。

- `id`：token sha256 主键。
- `bridge_id`。
- `created_at`、`last_seen_at`。

### `inboxes` — `Inbox`

平台侧身份。

- `id`：`ib_...`。
- `account_id`。
- `bridge_id` nullable。
- `platform`：当前有 `chat`，字段语义允许其他字符串。
- `display_name`。
- `default_persona_id` nullable。
- `reply_provider_config_id` nullable。
- `enabled` boolean。
- `platform_self_id` nullable；Bridge handshake 上报。
- timestamps。

### `contacts` — `Contact`

粉丝/对方接管单元。

- `id`：`ct_...`。
- `inbox_id`。
- `peer_platform_id`。
- `display_name`。
- `card_md` nullable。
- `persona_id` nullable。
- `reply_provider_config_id` nullable override。
- `autoreply_enabled` boolean。
- `pending_reply` boolean。
- `status`：`active | archived`。
- `last_seen_platform_msg_id` nullable。
- unique `(inbox_id, peer_platform_id)`。

### `archives` — `Archive`

上传的 WeFlow 源文件 metadata。

- `id`：`a_...`。
- `account_id`。
- `inbox_id`。
- `filename`。
- `file_path`。
- `file_hash`：sha256 前 16 位。
- `self_wxid`。
- `message_count`、`contact_count`。
- `uploaded_at`。
- unique `(account_id, file_hash)`。

### `messages` — `Message`

统一消息表，包含 archive 和 live。

- `id`：自增 integer。
- `contact_id`。
- `archive_id` nullable。
- `external_id`。
- `source`：`archive | live`。
- `role`：`self | counterpart`。
- `sender_name` nullable。
- `content`。
- `timestamp`。
- `archive_msg_idx` nullable。
- `created_at`。
- unique `(contact_id, external_id)`。
- index `(contact_id, timestamp)`。

### `distill_jobs` — `DistillJob`

蒸馏 worker job。

- `id`：`dj_...`。
- `account_id`。
- `source_inbox_id`。
- `target_persona_id`。
- `provider_config_id`。
- `status`：`pending | running | done | failed`。
- `progress` JSON。
- `error_message` nullable。
- timestamps。

### `outbound_messages` — `OutboundMessage`

Studio → Bridge 队列。

- `id`：自增 cursor。
- `inbox_id`。
- `contact_id`。
- `chunks` JSON。
- `status`：`pending | delivered | failed | canceled`。
- `delivered_at` nullable。
- `failed_reason` nullable。
- `created_at`。
- index `(inbox_id, id)`。

### `llm_logs` — `LlmLog`

LLM 调用日志。

- `purpose`：`distill | reply`。
- `persona_id` nullable。
- `inbox_id` nullable。
- `request_messages`：text JSON。
- `response_raw`。
- `model` nullable。
- `created_at`。

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
