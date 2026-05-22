# Bridge ↔ Studio Protocol

所有 endpoint 都在 Studio 的 `/api/bridge/*` 下。**协议 v2，共 8 个端点。**

## 认证模型

handshake 用 Studio 账号密码换 account session token，与浏览器登录共用同一张 `auth_sessions` 表。Bridge 身份由 token 解出的 account + 请求头 `X-Machine-Id` 在 Studio 端解析出 Bridge 行（`(account_id, machine_id)` 唯一）。

token 24h 滑动续期；改密码删除该 account 的所有 session（web + 所有 Bridge）。

**machine_id 严格协议**：
- 客户端首次启动不带 → Studio 生成 4 位短码并返回（`secrets.choice` 在 a-zA-Z0-9 范围抽，per-account 唯一）
- 客户端带值且匹配现有 `(account, machine_id)` → 复用
- 客户端带值但不识别 → **400 `machine_id_invalid`**，不再静默换发。Bridge 收到 400 应清本地 state.db 重试。

## 端点全集

| # | Method | Path | 鉴权 |
|---|---|---|---|
| 1 | POST | `/api/bridge/handshake` | 账密 |
| 2 | POST | `/api/bridge/inboxes` | Bearer + Machine-Id |
| 3 | GET  | `/api/bridge/inboxes` | Bearer + Machine-Id |
| 4 | POST | `/api/bridge/heartbeat` | Bearer + Machine-Id |
| 5 | POST | `/api/bridge/incoming` | Bearer + Machine-Id |
| 6 | GET  | `/api/bridge/outbound` | Bearer + Machine-Id |
| 7 | POST | `/api/bridge/conversations` | Bearer + Machine-Id |
| 8 | GET  | `/api/bridge/takeovers` | Bearer + Machine-Id |

---

## 1. `POST /api/bridge/handshake`

密码换 token。不注册任何 inbox。

```json
// in
{ "username": "linxiaoman", "password": "...", "machine_id": "RU9d" }
// out
{ "token": "...", "account_id": "acc_...", "username": "linxiaoman", "machine_id": "RU9d" }
```

- `machine_id` 可空（首次启动）。Studio 生成新值。
- `machine_id` 不空但不识别 → `400 {"detail": "machine_id_invalid"}`。
- 响应**不含 `bridge_id`**——客户端不需要这字段，去掉以避免内部 id 渗透。
- 账密错 → 401。

## 2. `POST /api/bridge/inboxes` — 注册当前 channel 集合

```json
// in
{
  "inboxes": [
    { "platform": "chat", "platform_self_id": "acct_xxx", "display_name": "林小漫" }
  ]
}
// out
{
  "inboxes": [
    { "id": "ib_...", "platform": "chat", "platform_self_id": "acct_xxx", "display_name": "林小漫" }
  ]
}
```

按 `(account_id, platform, platform_self_id)` upsert Inbox；存在则绑当前 `bridge_id` 并刷新 `display_name`。**`display_name` 由 Bridge 上报**（chat 上即用户昵称），Studio 不再编 `f"{self_id}@{platform}"`。

响应无 `cursor`——outbound 模型已无游标。

## 3. `GET /api/bridge/inboxes` — 查当前 channel 集合

```json
// out
{ "inboxes": [ /* 同 #2 响应中的 InboxView */ ] }
```

Bridge 想在不重新 register 的情况下检测 Studio 侧变化（如管理员手动解绑 inbox），就调这个。

## 4. `POST /api/bridge/heartbeat` — 纯心跳

```json
// in
{}
// out
{}
```

只更新 `bridge.last_seen_at`。所有派生信息（inbox 列表等）请走专用端点。

## 5. `POST /api/bridge/incoming`

```json
// in
{
  "messages": [
    {
      "inbox_id": "ib_...",
      "platform_conversation_id": "c_xxx",
      "client_id": "12345",
      "sender_id": null,
      "msg_type": "text",
      "content": "你好",
      "sent_at": "2026-05-22T05:50:00.000Z"
    }
  ]
}
// out
{ "accepted": 1, "deduped": 0, "rejected": 0 }
```

**关键设计**：
- 仅引用 `(inbox_id, platform_conversation_id)`，**不携带 conversation 元信息**（kind、display_name、members 都归 #7 管）。
- 找不到 Conversation 行 → Studio 当场创建**占位行**：`kind="unknown"`、`display_name=platform_conversation_id`、members 空、provider=种子。占位行被 #7 来时**原地更新**——消息从一开始就锚定在正确的 row，从不"挪窝"。
- 去重键 `(conversation_id, client_id)`，UNIQUE 索引。client_id 由 adapter 决定形态：chat 用 platform `msg.id`；wechat 用官方 msg_id；fallback 让 adapter 自己 hash。Bridge 本地 `local_messages.client_id` 与 wire 同事实，不再各算各的 hash。
- `sender_id IS NULL` 时 Studio 尝试匹配 `(conversation_id, content)` 的某条 PENDING outbound → 自动 `DELIVERED + delivered_at=now`。这是 outbound 状态推进的唯一通道（替代 ack endpoint）。

`rejected`：找不到 inbox（inbox_id 不属于本 bridge）。

## 6. `GET /api/bridge/outbound?timeout=T`

```json
// out
[
  {
    "id": 7,
    "inbox_id": "ib_...",
    "platform_conversation_id": "c_xxx",
    "msg_type": "text",
    "content": "AI 回复"
  }
]
```

长轮询。过滤：`inbox.bridge_id == self AND status=PENDING AND send_after <= now`，最多 50 条。超时返回 `[]`。

**无 cursor，无 lease，无 ack**。
- 每次拉全集（PENDING）→ Bridge 进程内维护 in-flight set 防同一轮重发。
- 重启会重发；平台 dedup 兜底（不依赖 lease）。
- 永久失败没有专用 endpoint；Studio 等 from_self 入站消息匹配掉就标 DELIVERED，匹配不上就一直 PENDING 直到操作员手动清理。

OutboundForBridge 字段刻意精简——Studio 内部状态（`status`/`created_at`/`delivered_at`/`failed_reason`）不外泄给 Bridge。

## 7. `POST /api/bridge/conversations` — conversation 元信息唯一源

```json
// in
{
  "inbox_id": "ib_...",
  "conversations": [
    {
      "platform_conversation_id": "c_xxx",
      "kind": "dm",
      "display_name": "苏糖",
      "members": [
        { "peer_platform_id": "ct_zzz", "display_name": "苏糖" }
      ]
    }
  ]
}
// out
{ "upserted": 1 }
```

Bridge 启动时调一次，之后**diff 触发**——`list_conversations()` 跟上次缓存的签名比对，有变化才调。**纯 upsert，不删**：payload 缺失的 conversation 留下不动（平台分页/限流可能让一次拉取不完整）。

ConversationMember 集是**全量覆盖**该 conversation 的成员（payload 里没出现的 member 被删）。

**与 #5 的边界**：
- `/incoming` 只能创建占位行；占位 kind=`unknown`、members 空
- `/conversations` 是 kind/display_name/members 的唯一可信源
- 顺序无关：协议层接受任意顺序；Bridge 实现层"先 #7 再 #5"减小 placeholder 窗口

## 8. `GET /api/bridge/takeovers`

```json
// out
{
  "takeovers": [
    { "inbox_id": "ib_...", "platform_conversation_id": "c_xxx" }
  ]
}
```

返回 `bridge.id == self AND conv.takeover == true AND conv.status == active` 的所有 `(inbox_id, platform_conversation_id)`。**单位是 conversation 不是 peer**——DM 和群无差别。

Bridge 用这个来过滤 `_consumer`：只把这些 conversation 的入站消息往 Studio 推（其它对话即使 Bridge 看到了也不送）。

---

## 砍掉的 v1 端点

- `POST /api/bridge/outbound/{id}/ack` — 不再需要，靠 #5 from_self 自动 DELIVERED
- `POST /api/bridge/peers` — 合并进 #7 `/conversations`
- `GET /api/bridge/active-peers` — 改名 #8 `/takeovers`（且单位升到 conversation）
- `POST /api/bridge/media/presign-upload`
- `POST /api/bridge/media/check-or-presign`
- `GET /api/bridge/media/{key}` — 不属于 bridge daemon 协议

媒体管线整体下线：当前 Bridge `send` 对非 text 抛 `PermanentError`，wire `msg_type` 字段保留但只允许 `text`，给未来留口。
