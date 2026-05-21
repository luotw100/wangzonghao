# Bridge Runtime & Adapters / Bridge 运行时与适配器

## HTTP helper（http.py）

`request_json(method, url, *, token, body, timeout)` 基于 `urllib.request`。固定加 `User-Agent: laborster-bridge/0.1`（Cloudflare 屏蔽默认 `Python-urllib`，返回 403 code 1010）。401 抛 `Unauthorized`，其余非 2xx 抛 `HttpError(status, body)`，网络错误抛 `HttpError(0, reason)`。瞬时状态（0/502/503/504）内部退避重试。

## 本地存储（store.py）

`LocalStore` 用 `sqlite3` 单连接（`check_same_thread=False`）+ `threading.Lock` 串行化，WAL 模式。两张表。

### 表：`local_messages`

字段：`id`(autoincrement)、`inbox_id`、`conversation_id`、`peer_id`、`peer_display_name`、`sender_id`、`sent_at`、`msg_type`、`content`、`local_hash`、`sent`(0/1)。索引：`UNIQUE(inbox_id, local_hash)`、`(sent, id)`、`(inbox_id, conversation_id, id)`。

`local_hash(inbox_id, conversation_id, sender_id, sent_at, msg_type, content)` = `sha256` hex（字段以 `\x00` join）。该 hash **仅 Bridge 本地用作 store 去重键**，不跨网，不参与协议；adapter 不向 Studio 暴露 `platform_msg_id`。

### 表：`conv_cursors`

字段：`inbox_id`、`conversation_id`、`cursor`、`updated_at`。主键 `(inbox_id, conversation_id)`。`cursor` 是 **adapter 自定义形态、Bridge 不解析的字符串**——adapter `fetch_new` 返回的最后一条 `IncomingEvent.cursor` 字段会原样写进这里，下次 `fetch_new` 原样读回。

### 关键方法

- `get_cursor(inbox_id, conversation_id) -> str | None`：读 conv 的续传锚点。
- `ingest(inbox_id, conversation_id, peer_id, peer_display_name, events, new_cursor)`：**单事务**把一批 events `INSERT OR IGNORE` 进 `local_messages` 并把 `new_cursor` upsert 进 `conv_cursors`。崩溃即回滚——cursor 推进与消息落库原子绑定。
- `get_unsent(limit, active_peers)`：按 `(inbox_id, peer_id) IN takeover_set` 过滤的未推送行；空 set 直接返回 `[]`（接管开关是 consumer 的唯一闸门）。
- `mark_sent(ids)` / `count_unsent()` / `count_recent_incoming(since_iso)` / `close()`。

## Adapter Protocol（adapters/__init__.py）

Bridge 只通过 Protocol 与平台交互；runtime/commands 永远 `adapters.get(platform)` 拿 factory，**从不 import 具体 adapter**。新平台 = 在 `adapters/` 加一个模块，模块底部调 `register(AdapterFactory(...))`。`adapters/__init__.py` 在模块底部 `from . import chat as _chat` 触发自注册。

### 三类异常（错误契约）

```text
Unauthorized      credential 死了，本 channel 需要重跑 LoginFlow，
                  不影响其它 channel 与 daemon
TransientError    可退避重试（网络抖动、5xx、超时）
PermanentError    仅 send 抛——本条消息不可恢复（被拉黑、内容被拒），
                  runtime 直接 ack failed
其它异常           bug，runtime 大声 log + 更长退避，绝不静默吞
```

`fetch_new` 必须 **全有或全无**：要么返回 list，要么抛；不可半截 yield 后再抛。

### 数据形状

- `Credential = dict`，adapter 自定义、Bridge 当 JSON 不透明持久化。
- `Conversation { id, kind: "dm"|"group", display_name, peers: [{platform_id, display_name}] }`。`peers` 对 DM 长度为 1，对 group 可为多元素或省略。
- `IncomingEvent { conversation_id, sender_id, sent_at, msg_type, content, cursor }`——没有 platform_msg_id。
- `OutboundPayload { msg_type, content, media_ref? }`。
- `Step = PromptInput | WaitForExternal | Done | Failed`；`Field { name, label, secret?, placeholder? }`。

### `AdapterFactory`

```text
factory.platform: str
factory.begin_login() -> LoginFlow   # 可抛 TransientError
factory.build(credential) -> Adapter  # 纯构造，不抛
```

### `LoginFlow`（回合制状态机）

GUI/CLI 都用同一份驱动逻辑，没有平台特化：

```text
flow.current() -> Step                # 纯读，可反复调
flow.submit(answers: dict) -> Step    # 当前是 PromptInput
flow.poll() -> Step                   # 当前是 WaitForExternal
flow.cancel() -> None
```

输入错误（密码错、OTP 错）**不抛异常**，由 `PromptInput(error=...)` 表达；超时、过期、用户拒绝 → `Failed(reason)` 终态；网络挂 → submit/poll 抛 `TransientError`。

### `Adapter`（运行时 I/O，**全无状态**）

```text
adapter.platform_self_id: str                              # property，首次访问懒加载并 cache
adapter.list_conversations() -> list[Conversation]
adapter.fetch_new(conv_id, since: str | None) -> list[IncomingEvent]
adapter.send(conv_id, payload: OutboundPayload) -> None
```

**没有** `resolve_self()` / `list_peers()` / `scan()` / `stop()`。循环节奏、退避、监督全在 runtime 这一层。

## ChatAdapter（adapters/chat.py）

chat sandbox HTTP 轮询适配器。模块底部 `register(AdapterFactory(platform="chat", begin_login=lambda: _ChatLoginFlow(), build=lambda c: ChatAdapter(c)))` 自注册。base url = `config.CHAT_BASE_URL`。

- **`_ChatLoginFlow`**：单步 `PromptInput([username, password])` → `submit()` 调 `POST /api/auth/login`：成功 `Done(credential={"token": "..."})`；401 重发 `PromptInput(error="账号或密码错误")`；网络错 → `TransientError`。`poll()` 在本 flow 无用；`cancel()` 置 `Failed("用户取消")`。
- **`ChatAdapter.__init__(credential)`**：取 `credential["token"]`。
- **`platform_self_id`**（property）：首次访问 `GET /api/auth/me`，结果存入 `_self_id` 后 cache。
- **`list_conversations()`**：`GET /api/conversations` → 每条返回 `Conversation(id=c.id, kind="dm", display_name=contact.nickname or username, peers=[{platform_id: contact.id, display_name}])`。chat 全部是 DM。
- **`fetch_new(conv_id, since)`**：把 `since` 解为 int last_id（None=0），分页 `GET /messages/after?last_id=&limit=200`，gather 所有行后返回；每条 `IncomingEvent.cursor = str(msg.id)`，`sender_id = self_id if msg.sender_id is None else peer_id`。短页表示拉完。**全有或全无**：中途异常会丢弃已 gather 的部分再抛。
- **`send(conv_id, payload)`**：`payload.msg_type != "text"` → 立即抛 `PermanentError`；text 则 `POST /messages` 由服务端记为 self-sent。
- 内部 `_req` 把 http.Unauthorized → adapter.Unauthorized，HttpError → TransientError。

## events.py

`Events`：`threading.Condition` 保护的日志环形缓冲（`deque(maxlen=1000)`，每行带递增 `_seq`）+ 当前 DaemonState 快照。`log()`/`set_state()` 由 daemon 线程写；`snapshot()`/`tail(n)`/`follow(stop)` 由 REPL 主线程读。`follow` 阻塞 yield 新行直到 `stop` Event 置位（仅交互终端用）。

## StudioClient（studio_client.py）

构造接受 `get_token`、`get_machine_id` callable（懒读，401 清除后无需重建）。base = `config.STUDIO_BASE_URL`，每次请求带 `X-Machine-Id` 头（无值则不带）。方法：`handshake`（唯一带密码）、`register_inboxes`、`heartbeat`、`push_incoming`、`get_outbound`、`ack_outbound`、`announce_peers`、`get_active_peers`、`media_check_or_presign_upload`。`_inbox(i)` 仅取 Studio `BridgeInboxView` 暴露的字段 `{id, platform, platform_self_id, display_name}`。

## BridgeRuntime（runtime.py）

### 常量

```text
HEARTBEAT_S = 15   ANNOUNCE_S = 60   ACTIVE_PEERS_S = 10
CONSUMER_S = 1     CONSUMER_BATCH = 50   OUTBOUND_TIMEOUT_S = 30
PRODUCER_INTERVAL_S = 2
```

### 关键字段

- `_adapters: {inbox_id: {adapter, inbox, conv_map, peer_names, conv_count}}`
  - `conv_map: {peer_platform_id → conversation_id}`——由 producer 每拍刷新；outbound 派发用。
  - `peer_names: {conversation_id → (peer_id, display_name)}`——producer 维护，供 ingest 写 store 用。
- `_active_peers: set["inboxId|peerId"]`（takeover 集合，`_loop_active_peers` 维护）
- `_outbound_cursor: int`、`_last_error`、`_stop: threading.Event`、`_threads: list`
- `_store: LocalStore`

### start() / bootstrap

`start()` 起一个 `bootstrap` 守护线程后立即返回（不阻塞 REPL）。bootstrap：

1. `_push_state("connecting")`
2. 对每个 channel：`adapters.get(ch["platform"]).build(ch["credential"])` → 读 `adapter.platform_self_id`（一次 HTTP）。`adapters.Unauthorized` → 记 error 跳过；`TransientError` → 警告跳过；未知 platform → 跳过；全失败 → `offline` 返回。
3. `studio.register_inboxes([(platform, self_id)…])`（token + X-Machine-Id 鉴权）；401 → `on_auth_error` + `error401`。
4. 按 `(platform, self_id)` 匹配 Studio 返回的 inbox，初始化 entry。
5. `_push_state("online")`。
6. 并行起 6 类循环线程。

### 循环

- **producer × N**（每 inbox 一个，`PRODUCER_INTERVAL_S` 节奏）：`_poll_inbox` = `adapter.list_conversations()` 刷新 `conv_map/peer_names/conv_count` → 对每个 DM conv `since=store.get_cursor(...)` → `adapter.fetch_new(conv_id, since)` → `store.ingest(...)` 原子写入消息 + 推进 cursor。group conv 跳过。
  - `Unauthorized` → 日志 + 摘除本 inbox + `degraded`，本线程退出（其它 channel 不受影响）。
  - `TransientError` → 3s 退避后继续。
  - 其它异常 → 5s 退避（按 bug 处理，大声 log）。
- **consumer 1s**：`get_unsent(50, active_peers)` → `studio.push_incoming`（payload `platform_msg_id=None`，Studio 用 msg_hash 兜底）→ `mark_sent`；adapter 已摘除的 inbox 行直接 `mark_sent`。401 静默 return（heartbeat 处理）。
- **heartbeat 15s**（先立即跑一次）：`studio.heartbeat`，摘除不在返回列表的 adapter；401 → `on_auth_error` + `error401` + `stop()`。
- **announce 60s**：每 adapter `list_conversations()` → 抽 DM peers → `studio.announce_peers`；`Unauthorized` 跳过，其它异常仅 warn。
- **active-peers 10s**：`studio.get_active_peers` → 重建 `_active_peers` set。
- **outbound long-poll**：`studio.get_outbound(cursor, 30)` → `_dispatch_outbound(item)`：从 `entry["conv_map"]` 找 `conv_id`，cache miss 则刷一次 `list_conversations` 再查；找到则 `adapter.send(conv_id, OutboundPayload(...))` → `ack sent`；`PermanentError`/未知 conv → `ack failed`；`Unauthorized` → `ack failed` 标注 credential 失效。401（Studio 侧）→ `on_auth_error` + stop。

### stop()

置 `_stop`，join 线程（2s 超时，跳过当前线程），清空 `_adapters`，`_push_state("idle")`，关闭 store，日志 `core info "daemon stopped"`。adapter 无 `stop()` 方法——无状态、无长生命周期资源、无循环需信号。

### 与 REPL/GUI 的集成

写入 `Events`；REPL 主线程通过 `events.snapshot()`（`/status`）和 `events.tail()` / `events.follow()`（`/log`）读取，线程安全。GUI 同理：`bridge_api.Api` 把 `Events` 暴露成 `status()` / `logs()` / pump 推送到 `window.pushLog(...)`。
