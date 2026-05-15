# Bridge ↔ Studio Protocol / Bridge 协议

所有 endpoint 都在 Studio 的 `/api/bridge/*` 下。

## 认证模型

Bridge 认证通过 handshake 动态获取 token，不需要预创建。认证流程是：

1. Bridge 启动时持有 Studio username/password 和可选的本地持久化 `machine_id`。
2. Bridge 调 handshake。
3. Studio 校验账号密码。
4. 如果请求带 `machine_id`，Studio 按 `(account_id, machine_id)` 查找已有 Bridge；如果没有（首次启动），Studio 生成 `machine_id` 并创建新 Bridge。
5. Studio 删除该 Bridge 的旧 BridgeSession。
6. Studio 创建并返回新 session token。
7. Bridge 后续请求带 `Authorization: Bearer {token}`。
8. token 保存到 `state.json`，重启时优先尝试复用（成功则跳过 handshake）。

撤销 Bridge 时，Studio 删除 BridgeSession 并把 Bridge 状态置为 `revoked`；Bridge 下次调用会收到 401。

## 消息类型

Bridge 协议支持多种消息类型。`msg_type` 字段值：`text | image | audio | video | file`。

- **text**：`content` 为纯文本。
- **image / audio / video / file**：`content` 为 Studio S3 的 storage key（格式 `media/{bridge_id}/{uuid}`），媒体二进制数据通过 Studio S3 流转。

媒体数据流向：Inbound 时 Bridge 从平台 S3 下载 → 上传到 Studio S3 → 用 Studio storage key 替换 content；Outbound 时 Bridge 从 Studio S3 下载 → 上传到平台 S3 → 发送。

## `POST /api/bridge/handshake`

### Request

```json
{
  "username": "demo",
  "password": "demo123",
  "machine_id": "m_xxxxxxxxxxxx",
  "inboxes": [
    { "platform": "chat", "platform_self_id": "acct_alice" }
  ]
}
```

### Studio 当前行为

1. 校验 Studio account username/password，且 account status 必须是 active。
2. 如果请求带了 `machine_id`，按 `(account_id, machine_id)` 查找已有 Bridge；如果没带（首次启动），生成新 `machine_id`（`m_` + uuid hex 前 12 字符）并创建新 Bridge。
3. 标记 Bridge online，更新 `last_seen_at`。
4. 删除这个 Bridge 的旧 `BridgeSession`。
5. 生成 token，插入新 `BridgeSession`。
6. 选择当前账号下第一个 active Persona 作为新 Inbox 默认 Persona。
7. 对每个上报的平台身份：
   - 按 `(account_id, platform, platform_self_id)` 查 Inbox；
   - 存在则绑定当前 `bridge_id`；
   - 不存在则创建 Inbox，display name 为 `{platform_self_id}@{platform}`，enabled=true，provider=null，default persona 为上一步选到的 Persona 或 null。
8. 对 served inboxes 计算 outbound cursor：取最新非 pending outbound id。
9. commit 并返回 token 和 served inboxes。

### Response

```json
{
  "token": "opaque-session-token",
  "bridge_id": "br_xxxxxxxx",
  "machine_id": "m_xxxxxxxxxxxx",
  "account_id": "acc_xxxxxxxx",
  "inboxes": [
    {
      "id": "ib_xxxxxxxx",
      "platform": "chat",
      "platform_self_id": "acct_alice",
      "display_name": "acct_alice@chat",
      "enabled": true,
      "default_persona_id": "ps_xxxxxxxx"
    }
  ],
  "cursor": 0,
  "no_persona": false
}
```

## `POST /api/bridge/heartbeat`

### Auth

Bearer Bridge session token。

### 当前行为

- 用 token hash 查 `BridgeSession`。
- session 不存在或 Bridge revoked 时拒绝。
- 更新 session `last_seen_at`。
- 如果 Bridge status 不是 online，则置为 online。
- 更新 Bridge `last_seen_at`。
- 返回当前 `Inbox.bridge_id == bridge.id` 的 Inbox 列表。

### Response

```json
{
  "inboxes": [
    {
      "id": "ib_xxxxxxxx",
      "platform": "chat",
      "platform_self_id": "acct_alice",
      "display_name": "acct_alice@chat",
      "enabled": true,
      "default_persona_id": "ps_xxxxxxxx"
    }
  ]
}
```

Bridge 会停止本地存在但不在 response 中的 adapter。

## `POST /api/bridge/incoming`

### Request

```json
{
  "messages": [
    {
      "inbox_id": "ib_xxxxxxxx",
      "peer_platform_id": "peer-id",
      "peer_display_name": "粉丝名",
      "platform_msg_id": "123",
      "role": "counterpart",
      "msg_type": "audio",
      "content": "media/br_xxx/abc123.mp3",
      "sent_at": "2026-05-09T12:00:00"
    }
  ]
}
```

### 当前行为

逐条处理：

1. 校验 Inbox 存在、属于 Bridge account、且绑定到当前 Bridge。
2. 不合法则 `rejected += 1`。
3. 按 `(inbox_id, peer_platform_id)` upsert Contact。
4. 新 Contact 字段：`persona_id = inbox.default_persona_id`；`reply_provider_config_id = inbox.reply_provider_config_id`；`takeover = False`；`reply_policy = disabled`；`pending_reply = False`；`status = active`。
5. 主去重：计算 `msg_hash = sha256(contact_id \x00 sender_id \x00 sent_at_canonical \x00 msg_type \x00 content_for_hash)`，`content_for_hash` 对媒体消息使用 `content_hash` 字段；已有相同 `msg_hash` 则 `deduped += 1`。
6. 次级去重（后向兼容）：若 `platform_msg_id` 存在，检查 `external_id = live:{platform_msg_id}` 是否已存在。
7. 计算 `role = 'self'`（sender_id == inbox.platform_self_id）或 `'counterpart'`。
8. 插入 `Message`（含 `msg_hash`、`msg_type`）。
9. 媒体消息写入 `MediaHash(account_id, content_hash, storage_key)`（已有则跳过）。
10. 更新 Contact last seen 和 updated_at。
11. 如果 role 是 counterpart 且 inbox enabled 且 contact `reply_policy == 'autoreply'`，则置 `pending_reply=True`。
12. `accepted += 1`。

### Response

```json
{ "accepted": 1, "deduped": 0, "rejected": 0 }
```

## `GET /api/bridge/outbound?cursor=N&timeout=T`

### Auth

Bearer Bridge session token。

### 当前行为

- 最多 long-poll `timeout` 秒，参数上限 60。
- 每轮重新打开 DB session。
- 计算当前 Bridge 绑定的 Inbox ids。
- 查询 `OutboundMessage`：
  - `inbox_id` 属于这些 Inbox；
  - `id > cursor`；
  - `status == pending`；
  - `send_after <= now`。
- 按 id 升序，limit 50。
- 从 Contact 附加 `peer_platform_id`。
- 有 payload 立即返回，否则 sleep 后重试。

### Response

```json
[
  {
    "id": 123,
    "inbox_id": "ib_xxxxxxxx",
    "contact_id": "ct_xxxxxxxx",
    "peer_platform_id": "peer-id",
    "msg_type": "audio",
    "content": "media/br_xxx/abc123.mp3",
    "status": "pending",
    "created_at": "...",
    "delivered_at": null,
    "failed_reason": null
  }
]
```

## `POST /api/bridge/outbound/{outbound_id}/ack`

### Request: sent

```json
{ "result": "sent", "platform_msg_id": "456" }
```

### Request: failed

```json
{ "result": "failed", "reason": "platform send error" }
```

### 当前行为

- 通过 OutboundMessage join Inbox，确认 outbound 属于当前 Bridge 绑定的 Inbox。
- 找不到时 404。
- 如果 status 已不是 pending，幂等返回当前 status。
- `sent`：status 置 `delivered`，写 `delivered_at`。
- `failed`：status 置 `failed`，写 `failed_reason`。

### Response

```json
{ "status": "delivered" }
```

## `POST /api/bridge/peers`

Bridge 上报登录 inbox 后发现的 peer 列表（会话目录），Studio 据此 upsert Contact 行，供前端展示全量会话列表而不依赖消息到达。

### Request

```json
{ "inbox_id": "ib_xxx", "peers": [{ "peer_platform_id": "peer-id", "display_name": "粉丝名" }] }
```

### 当前行为

- 校验 inbox 属于当前 Bridge。
- 对每个 peer：已有 Contact 时只更新 `display_name`；不存在时创建（`takeover=False`，`reply_policy=disabled`）。
- 不覆盖已有 Contact 的 `takeover`/`reply_policy`。

### Response

```json
{ "upserted": 2 }
```

## `GET /api/bridge/active-peers`

查询当前 Bridge 绑定 inbox 下所有 `takeover=True` 的 Contact，Bridge runtime 用此结果决定哪些 peer 的消息要上传到 Studio。

### Response

```json
{ "peers": [{ "inbox_id": "ib_xxx", "peer_platform_id": "peer-id" }] }
```

## `POST /api/bridge/media/check-or-presign`

Bridge 上传媒体前调用。按 `content_hash` 查 `MediaHash` 表，若已存在直接返回 storage key（skip upload），否则生成新 storage key 和 presigned PUT URL。

### Request

```json
{ "content_hash": "sha256:abcdef...", "filename": "voice.ogg", "mime_type": "audio/ogg" }
```

### Response（已存在）

```json
{ "status": "exists", "storage_key": "media/br_xxx/abc" }
```

### Response（新文件）

```json
{ "status": "new", "storage_key": "media/br_xxx/abc", "upload_url": "https://s3.../" }
```

## `POST /api/bridge/media/presign-upload`

### Auth

Bearer Bridge session token。

### Request

```json
{ "filename": "voice.mp3", "mime_type": "audio/mp3" }
```

### Response

```json
{ "storage_key": "media/br_xxx/abc123", "upload_url": "https://s3.../" }
```

Bridge 拿到 `upload_url` 后 PUT 二进制数据，然后用 `storage_key` 作为 incoming message 的 `content`。

## `GET /api/bridge/media/{storage_key}`

### Auth

Bearer Bridge session token。

### 当前行为

校验 `storage_key` 以 `media/{bridge.id}/` 开头（Bridge 只能访问自己上传的媒体），返回 302 重定向到 Studio S3 的 presigned GET URL。

Bridge 用此端点下载媒体二进制数据以发送 outbound media message。
