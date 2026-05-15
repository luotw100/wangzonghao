# Bridge Runtime & Adapters / Bridge 运行时与适配器

## 类型系统（types.ts）

```typescript
type MsgType = 'text' | 'image' | 'audio' | 'video' | 'file'

interface IncomingMessage {
  peerId: string
  peerDisplayName: string
  platformMsgId: string | null
  senderId: string
  msgType: MsgType
  content: string
  sentAt: Date
}

type DaemonStatus = 'idle' | 'connecting' | 'online' | 'degraded' | 'offline' | 'error401'

interface DaemonState {
  status: DaemonStatus
  machineId?: string
  bridgeId?: string
  studioUrl: string
  username?: string
  inboxes: InboxStatus[]
  inCount5m: number
  outboundPending: number
}

interface LogLine {
  t: string        // HH:MM:SS
  src: string      // 'core' | 'adapter' | 'studio' | 'heart' | 'consumer' | 'outbound'
  level: 'info' | 'ok' | 'warn' | 'err'
  msg: string
}
```

## ChatAdapter（adapters/chat.ts）

Chat sandbox HTTP 轮询适配器。

**内部状态**：`token`、`selfId`（`account_id`）、`threads: Map<convId, {peerId, peerDisplayName}>`、`stopped: boolean`。

### login()

`POST {baseUrl}/api/auth/login` → 保存 token 和 account_id，返回 account_id 作为 `platformSelfId`。

### listPeers()

调 `_refreshThreads()` → GET `/api/conversations` → 返回 `[{peerPlatformId, displayName}]`。

### scan(cursors)

异步生成器，无限循环：`_refreshThreads()` → 对每个 thread 按 `since_id=cursors[peerId]` 拉消息 → yield `IncomingMessage` → 更新 cursors。无新消息时 sleep 2s。

### send(peerId, content)

`POST {baseUrl}/api/conversations/{peerId}/messages`，msg_type 固定 `text`，返回 platform msg id。

## LocalStore（local-store.ts）

`better-sqlite3` SQLite，WAL 模式，单例，同步 API。

### 表：local_messages

字段：`id`（autoincrement）、`inbox_id`、`peer_id`、`peer_display_name`、`platform_msg_id`（nullable）、`sender_id`、`sent_at`（UTC ISO8601）、`msg_type`、`content`、`mime_type`（nullable）、`local_hash`、`sent`（0/1）。

索引：`UNIQUE(inbox_id, local_hash)`（去重键）、`(sent, id)`（consumer 查询）、`(inbox_id, peer_id, id)`（cursor 推导）。

### 关键方法

- `static localHash(inboxId, peerId, senderId, sentAt, msgType, content) → sha256 hex`
- `getCursors(inboxId) → {peerId: lastPlatformMsgId | null}`：从已插入行推导各 peer 扫描位置
- `insertMessage(msg) → boolean`：`INSERT OR IGNORE`，返回是否实际插入
- `getUnsent(limit, activePeers: Set<"inboxId|peerId"> | null) → LocalMessage[]`：`activePeers` 为 null 时不过滤，为空 Set 时直接返回 `[]`
- `markSent(id)`
- `countUnsent() → number`
- `countRecentIncoming(sinceMs) → number`

## BridgeRuntime（runtime.ts）

### 常量

```typescript
HEARTBEAT_MS        = 15_000
ANNOUNCE_MS         = 60_000
ACTIVE_PEERS_MS     = 10_000
CONSUMER_MS         = 1_000
CONSUMER_BATCH      = 50
OUTBOUND_TIMEOUT_SECS = 30
```

### 关键字段

- `adapters: Map<inboxId, AdapterEntry>`：每个 inbox 一个 ChatAdapter + 其 cursors
- `activePeers: Set<"inboxId|peerId">`：`takeover=true` 的 peer 集合，由 `startActivePeers` 维护
- `outboundCursor: number`：Studio outbound 队列消费游标
- `stopped: boolean`
- `timers: ReturnType<typeof setInterval>[]`：所有定时器，stop 时全部清除
- `store: LocalStore`

### 启动序列（run()）

1. emit `connecting` 状态
2. 对每个 InboxClaim：创建 ChatAdapter → login() → 收集 selfId
3. StudioClient.handshake()，传入所有 `{platform: 'chat', platformSelfId}`
4. 按 selfId 匹配 Studio 返回的 Inbox，绑定 adapter
5. emit `online`
6. 并行启动所有循环

### Inbound 流程（producer-consumer）

```text
adapter.scan(cursors)                     # per-inbox async generator
  → _startProducer()                      # for await，每条消息：
      → LocalStore.localHash()
      → store.insertMessage()             # UNIQUE(inbox_id, local_hash) 去重

setInterval(1s)
  → _startConsumer()
      → store.getUnsent(50, activePeers)  # activePeers 过滤：未接管 peer 的消息留在本地
      → studio.pushIncoming()             # POST /api/bridge/incoming
      → store.markSent()
```

`activePeers` 为空时 consumer 不推任何消息。接管后 consumer 自动补发历史未推消息。

### Heartbeat loop（15s）

`POST /api/bridge/heartbeat` → 对比返回的 inbox 列表，停掉不在列表中的 adapter。收到 401 → clearToken + emit error401 + stop()。

### Announce loop（60s）

对每个 adapter 调 `listPeers()` → `POST /api/bridge/peers` 上报 peer 目录，供 Studio 前端展示全量会话列表。

### Active peers loop（10s）

`GET /api/bridge/active-peers` → 更新 `activePeers` Set。

### Outbound loop（long-poll）

```text
while (!stopped):
  GET /api/bridge/outbound?cursor=N&timeout=30
  → 对每个 item:
       text:  adapter.send(peerId, content) → ack sent
       media: ack failed（不支持，chat sandbox 实践上只发 text）
```

### stop()

清除所有 setInterval，对每个 adapter 调 `.stop()`（中断 scan），关闭 SQLite，emit log `core info "daemon stopped"`。

## 与 Electron 主进程的集成

`BridgeRuntime` 的 `emit` 回调连接到 `ipcMain`，通过 `win.webContents.send()` 将 DaemonState 和 LogLine 推送给 renderer。Renderer 通过 `window.bridge.onStateChange(cb)` 和 `window.bridge.onLog(cb)` 订阅（preload contextBridge 包装的 ipcRenderer.on）。
