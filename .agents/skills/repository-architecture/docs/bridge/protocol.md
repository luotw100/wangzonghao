# Bridge ↔ Studio Protocol / Bridge 协议

所有 endpoint 都在 Studio 的 `/api/bridge/*` 下。

## 认证模型

Bridge 认证通过 handshake 动态获取 token，不需要预创建。认证流程是：

1. Bridge 启动时持有 Studio username/password 和 hostname。
2. Bridge 调 handshake。
3. Studio 校验账号密码。
4. Studio 按 `(account_id, hostname)` upsert Bridge。
5. Studio 删除该 Bridge 的旧 BridgeSession。
6. Studio 创建并返回新 session token。
7. Bridge 后续请求带 `Authorization: Bearer {token}`。
8. token 只在 Bridge 内存中保存。

撤销 Bridge 时，Studio 删除 BridgeSession 并把 Bridge 状态置为 `revoked`；Bridge 下次调用会收到 401。

## `POST /api/bridge/handshake`

### Request

```json
{
  "username": "demo",
  "password": "demo123",
  "hostname": "pc-hostname",
  "inboxes": [
    { "platform": "chat", "platform_self_id": "acct_alice" }
  ]
}
```

### Studio 当前行为

1. 校验 Studio account username/password，且 account status 必须是 active。
2. 按 `(account_id, hostname)` upsert `Bridge`。
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
      "content": "hello",
      "sent_at": "2026-05-09T12:00:00"
    }
  ]
}
```

当前 Bridge 协议的 incoming/outbound 消息仅传输纯文本（`content` 为字符串），不包含 `msg_type` 或 `media` 字段。

### 当前行为

逐条处理：

1. 校验 Inbox 存在、属于 Bridge account、且绑定到当前 Bridge。
2. 不合法则 `rejected += 1`。
3. 按 `(inbox_id, peer_platform_id)` upsert Contact。
4. 新 Contact 字段：
   - `persona_id = inbox.default_persona_id`；
   - `reply_provider_config_id = inbox.reply_provider_config_id`；
   - `autoreply_enabled = False`；
   - `pending_reply = False`；
   - `status = active`。
5. 构造 `external_id = live:{platform_msg_id}`。
6. 如果 `(contact_id, external_id)` 已存在，`deduped += 1`。
7. 插入 `Message(source='live')`。
8. 更新 Contact last seen 和 updated_at。
9. 如果 role 是 counterpart 且 inbox enabled 且 contact autoreply enabled，则置 `pending_reply=True`。
10. `accepted += 1`。

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
  - `status == pending`。
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
    "chunks": [
      { "content": "第一条", "msg_type": "text" }
    ],
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
