# Bridge Runtime & Adapters / Bridge 运行时与适配器

## HTTP helper（http.py）

`request_json(method, url, *, token, body, timeout)` 基于 `urllib.request`。固定加 `User-Agent: laborster-bridge/0.1`（Cloudflare 屏蔽默认 `Python-urllib`，返回 403 code 1010）。401 抛 `Unauthorized`，其余非 2xx 抛 `HttpError(status, body)`，网络错误抛 `HttpError(0, reason)`。

## 去重存储（store.py）

`LocalStore` 用 `sqlite3` 单连接（`check_same_thread=False`）+ `threading.Lock` 串行化，WAL 模式，等价于原同步单实例语义。

### 表：local_messages

字段：`id`(autoincrement)、`inbox_id`、`peer_id`、`peer_display_name`、`platform_msg_id`(nullable)、`sender_id`、`sent_at`、`msg_type`、`content`、`mime_type`(nullable)、`local_hash`、`sent`(0/1)。索引：`UNIQUE(inbox_id, local_hash)`、`(sent, id)`、`(inbox_id, peer_id, id)`。

### 关键方法

- `local_hash(inbox_id, peer_id, sender_id, sent_at, msg_type, content)` → `sha256` hex，字段以 `\x00` join。
- `get_cursors(inbox_id)` → `{peer_id: max(platform_msg_id) | None}`。
- `insert_message(dict)` → bool（`INSERT OR IGNORE`，返回是否实际插入）。
- `get_unsent(limit, active_peers)`：`active_peers` 为 None 不过滤；为空 set 返回 `[]`；否则按 `(inbox_id, peer_id) IN (...)` 过滤。
- `mark_sent(id)` / `count_unsent()` / `count_recent_incoming(since_iso)` / `close()`。

## StudioClient（studio_client.py）

构造接受 `get_token` callable（懒读 token，401 清除后无需重建）。base url = `config.STUDIO_BASE_URL`。方法与 `/api/bridge/*` 协议一一对应：`handshake`（唯一带密码，不带 token）、`register_inboxes`、`heartbeat`、`push_incoming`、`get_outbound`、`ack_outbound`、`announce_peers`、`get_active_peers`。请求/响应字段做 snake_case 映射。

## ChatAdapter（chat_adapter.py）

Chat sandbox HTTP 轮询适配器。base url = `config.CHAT_BASE_URL`。

- `obtain_token(username, password)`（staticmethod）→ `POST /api/auth/login`，返回 `(token, account.id)`。**仅 `/channel add` 调用一次**，密码用完即弃。
- `resolve_self()` → `GET /api/auth/me`，用持久化 token 恢复 `self_id`（`acct_…`）。daemon 启动时调用，无需密码。
- `_refresh_threads()` → `GET /api/conversations`，以 `contact.id` 为 peerId、`contact.nickname || username` 为 display name 建立 `peer_id → {conv_id, peer_id, display_name}`。
- `list_peers()` → 刷新后返回 `[{peer_platform_id, display_name}]`。
- `scan(cursors)` → 无限生成器：刷新 threads → 对每个 thread `GET /api/conversations/{conv}/messages?last_id=&limit=200` → 逐条 yield（`sender_id` = self 时 `platform_self_id` 否则 peerId；`sent_at` 经 `_iso_z` 规范化为毫秒 UTC `...Z`）→ 更新 cursors。无新消息 `sleep(2)`。
- `send(peer_id, content)` → 按 peer 查 conv → `POST /api/conversations/{conv}/messages`（`sender_type=self, msg_type=text`）→ 返回 `str(id)`。
- `stop()` → 置停止标志，中断 scan。

## events.py

`Events`：`threading.Condition` 保护的日志环形缓冲（`deque(maxlen=1000)`，每行带递增 `_seq`）+ 当前 DaemonState 快照。`log()`/`set_state()` 由 daemon 线程写；`snapshot()`/`tail(n)`/`follow(stop)` 由 REPL 主线程读。`follow` 阻塞 yield 新行直到 `stop` Event 置位（仅交互终端用）。

## BridgeRuntime（runtime.py）

### 常量

```text
HEARTBEAT_S = 15   ANNOUNCE_S = 60   ACTIVE_PEERS_S = 10
CONSUMER_S = 1     CONSUMER_BATCH = 50   OUTBOUND_TIMEOUT_S = 30
```

### 关键字段

- `_adapters: {inbox_id: {adapter, inbox, cursors, label}}`
- `_active_peers: set["inboxId|peerId"]`（takeover 集合，`_loop_active_peers` 维护）
- `_outbound_cursor: int`、`_last_error`、`_stop: threading.Event`、`_threads: list`
- `_store: LocalStore`

注：实例属性 `_active_peers`（set）与循环方法 `_loop_active_peers` 名字不可同名，否则 set 会遮蔽方法。

### start() / bootstrap

`start()` 起一个 `bootstrap` 守护线程后立即返回（不阻塞 REPL）。bootstrap：

1. `_push_state('connecting')`
2. 对每个 channel：`ChatAdapter(chat_token).resolve_self()` 收集 selfId（全失败 → `offline` 返回）
3. `studio.register_inboxes([('chat', selfId)…])`（token 鉴权）；401 → `on_auth_error` + `error401`
4. 按 selfId 匹配 inbox，绑定 adapter，`get_cursors` 初始化游标
5. `_push_state('online')`
6. 并行启动循环线程

### 循环（每个一个守护线程，用 `_stop.wait(timeout)` 可中断）

- **producer × N**：`for msg in adapter.scan(cursors)` → `local_hash` → `store.insert_message`（UNIQUE 去重）。
- **consumer 1s**：`get_unsent(50, active_peers or None)` → `studio.push_incoming` → `mark_sent`；adapter 不存在的行直接 `mark_sent`；401 直接 return（heartbeat 处理）。`active_peers` 为空时 consumer 不推任何消息。
- **heartbeat 15s**（先立即跑一次）：`studio.heartbeat`，停掉不在返回列表中的 adapter；401 → `on_auth_error` + `error401` + `stop()`。
- **announce 60s**：每 adapter `list_peers()` → `studio.announce_peers`，异常吞掉。
- **active-peers 10s**：`studio.get_active_peers` → 重建 `_active_peers` set。
- **outbound long-poll**：`while not stopped`：`studio.get_outbound(cursor, 30)` → 逐条推进 cursor 并 `_dispatch_outbound`：text → `adapter.send` + `ack sent`；非 text → `ack failed`。401 → `on_auth_error` + stop。

### stop()

置 `_stop`，停所有 adapter，join 线程（2s 超时，跳过当前线程），清空 `_adapters`，`_push_state('idle')`，关闭 store，日志 `core info "daemon stopped"`。

### 与 REPL 的集成

`emit` 不再是 IPC，而是写 `Events`。REPL 主线程通过 `events.snapshot()`（`/status`）和 `events.tail()` / `events.follow()`（`/log`）读取，线程安全。
