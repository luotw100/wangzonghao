# Bridge Runtime & Adapters

## HTTP helper（http.py）

`request_json(method, url, *, token, body, timeout)` 基于 `urllib.request`。固定 `User-Agent: laborster-bridge/0.1`（Cloudflare 屏蔽默认 `Python-urllib`）。401 抛 `Unauthorized`，其余非 2xx 抛 `HttpError(status, body)`，网络错抛 `HttpError(0, reason)`。瞬时状态（0/502/503/504）内部退避重试。

## 本地存储（store.py）

单 SQLite 文件，per-account，在 `<state_root>/<account_id>/state.db`。开文件时上 POSIX `flock`，第二个进程开同一 account 直接报 `StoreLockError`。四张表：

### `kv`
`(key, value)` 启动必要的轻状态：`studio_token`、`machine_id`（Studio 签发）、`display_name`（账号选择器缓存）、`last_active_at`（open 与 close 各写一次）。**不存** `username/bridge_id/account_id`——派生事实。

### `channels`
`(id auto, platform, credential_json, inbox_id, created_at)`，UNIQUE inbox_id WHERE NOT NULL。PK 是本地 rowid。`inbox_id` 是 Studio 注册回写的 cache，每次 bootstrap 重写。`credential_json` 是 adapter 自定义不透明 blob。

### `local_messages`
`(id, inbox_id, conversation_id, client_id, sender_id NULLABLE, sent_at, msg_type, content, sent)`，UNIQUE `(inbox_id, client_id)`。
- `client_id` 由 **adapter 决定**（chat 用 platform `msg.id`；wechat 用官方 msg_id）；同一个值直接上 wire 当 Studio 的去重键
- `sender_id IS NULL` = 自己发的（效仿 chat 语义）
- 永不删除（用户取消托管后又重新托管要能复原）

### `conv_cursors`
`(inbox_id, conversation_id, cursor, updated_at)`，PK `(inbox_id, conversation_id)`。`cursor` 是 **adapter 自定义、Bridge 不解析的字符串**——`fetch_new` 返回的最后一条 `IncomingEvent.cursor` 原样写回。

### 关键方法
- `get_cursor(inbox_id, conversation_id) -> str | None`
- `ingest(inbox_id, conversation_id, events, new_cursor)`：**单事务** `INSERT OR IGNORE` 一批 events 进 `local_messages` 并 upsert `new_cursor`。崩溃即回滚，cursor 推进与消息落库原子绑定。
- `get_unsent(limit, active_takeovers)`：按 `(inbox_id, conversation_id) IN takeover_set` 过滤，空 set 直接 `[]`（接管是 consumer 唯一闸门）。key 形态 `"{inbox_id}|{conversation_id}"`。
- `mark_sent(ids)` / `count_unsent()` / `count_recent_incoming(since_iso)` / `close()`。
- `add_channel(platform, credential)` / `delete_channel(id)` / `set_channel_inbox(id, inbox_id)`。

`read_account_meta(db_file)` / `list_accounts(state_root)` 走只读 sqlite URI，不上 flock，用于启动时枚举 account。

## Adapter Protocol（adapters/__init__.py）

Bridge 只通过 Protocol 与平台交互；runtime/commands 永远 `adapters.get(platform)` 拿 factory，**从不 import 具体 adapter**。新平台 = 在 `adapters/` 加一个模块，模块底部调 `register(AdapterFactory(...))`。`adapters/__init__.py` 在模块底部 `from . import chat as _chat` 触发自注册。

### 三类异常

```text
Unauthorized      credential 死了，本 channel 重跑 LoginFlow；其它 channel 与 daemon 不受影响
TransientError    可退避重试
PermanentError    仅 send 抛——本条消息不可恢复
其它异常           bug，runtime 大声 log + 更长退避
```

`fetch_new` 必须 **全有或全无**。

### 数据形状

- `Credential = dict`，adapter 自定义、Bridge 当 JSON 不透明持久化。
- `Conversation { id, kind: "dm"|"group", display_name, peers: [{platform_id, display_name}] }`。
- `IncomingEvent { conversation_id, client_id, sender_id: str|None, sent_at, msg_type, content, cursor }`。`client_id` 由 adapter 拍板生成；`sender_id is None` 表示自己发。`cursor` 与 `client_id` 概念分离——`client_id` 是去重身份，`cursor` 是续传锚点（chat 两者数值相同纯属巧合）。
- `OutboundPayload { msg_type, content, media_ref? }`。
- `Step = PromptInput | WaitForExternal | Done | Failed`；`Field { name, label, secret?, placeholder? }`。

### `Adapter`（运行时 I/O，**全无状态**）

```text
adapter.platform_self_id: str                              # property，首次访问懒加载
adapter.platform_self_display_name: str                    # 同上，注册 inbox 时上报
adapter.list_conversations() -> list[Conversation]
adapter.fetch_new(conv_id, since: str | None) -> list[IncomingEvent]
adapter.send(conv_id, payload: OutboundPayload) -> None
```

**没有** `resolve_self()` / `list_peers()` / `scan()` / `stop()`。循环节奏、退避、监督全在 runtime 这层。

### `LoginFlow`（回合制状态机）

```text
flow.current() -> Step
flow.submit(answers: dict) -> Step
flow.poll() -> Step
flow.cancel() -> None
```

输入错误 → `PromptInput(error=...)`；终态 → `Failed(reason)`；网络挂 → 抛 `TransientError`。

## ChatAdapter（adapters/chat.py）

chat sandbox HTTP 轮询适配器，模块底部自注册 `register(AdapterFactory(platform="chat", ...))`。base = `config.CHAT_BASE_URL`。

- **`_ChatLoginFlow`**：单步 `PromptInput([username, password])` → `submit()` 调 `POST /api/auth/login`：成功 `Done(credential={"token": "..."})`；401 重发 `PromptInput(error=...)`；网络错 → `TransientError`。
- **`platform_self_id` / `platform_self_display_name`**：`_ensure_me()` 首次访问 `GET /api/auth/me`，把 `id` 和 `nickname / username` 缓存。
- **`list_conversations()`**：`GET /api/conversations` → 每条返回 DM 形态的 `Conversation`，peers 取 contact。
- **`fetch_new(conv_id, since)`**：`since` 当 last_id (int)，分页 `GET /messages/after?last_id=&limit=200`。每条 `client_id = str(msg.id)`、`cursor = str(msg.id)`、`sender_id = None if msg.sender_id is None else peer_id`。**全有或全无**。
- **`send(conv_id, payload)`**：非 text → 立即 `PermanentError`；text 则 `POST /messages`。
- 内部 `_req` 把 http.Unauthorized → adapter.Unauthorized，HttpError → TransientError。

## events.py

`Events`：`threading.Condition` 保护的日志环形缓冲（`deque(maxlen=1000)`）+ DaemonState 快照。`log()`/`set_state()` daemon 线程写；`snapshot()`/`tail(n)`/`follow(stop)` 主线程读。

## StudioClient（studio_client.py）

构造接受 `get_token` / `get_machine_id` callable。base = `config.STUDIO_BASE_URL`，每次请求带 `X-Machine-Id`。方法对应协议 v2 八个端点：`handshake / register_inboxes / get_inboxes / heartbeat / push_incoming / get_outbound / push_conversations / get_takeovers`。没有 `ack_outbound`、没有 `announce_peers`、没有 `media_*`。

## BridgeRuntime（runtime.py）

### 常量
```text
HEARTBEAT_S = 15   TAKEOVERS_S = 10   CONSUMER_S = 1
CONSUMER_BATCH = 50   OUTBOUND_TIMEOUT_S = 30   PRODUCER_INTERVAL_S = 2
```

### 关键字段
- `_adapters: {inbox_id: {adapter, inbox, conv_signature, conv_count}}`
  - `conv_signature`: 上一次 `list_conversations()` 的可哈希签名（id, kind, display, members 全集），用来 diff 决定是否调 `push_conversations`。
- `_active_takeovers: set["inboxId|platform_conversation_id"]`（`_loop_takeovers` 维护）
- `_inflight_outbound: set[int]`（进程内防同一 outbound id 在同一轮长轮询内被重复 dispatch；重启会丢，平台 dedup 兜底）
- `_last_error`、`_stop`、`_threads`、`_store: Store`

### bootstrap

`start()` 起 `bootstrap` 守护线程立即返回。bootstrap：

1. `_push_state("connecting")`
2. 对每个 `Channel`：`adapters.get(ch.platform).build(ch.credential)` → 读 `platform_self_id` + `platform_self_display_name`（同一次或两次 HTTP，cache）。失败按 Unauthorized/TransientError 分类，跳过。全失败 → `offline`。
3. `studio.register_inboxes([{platform, self_id, display_name}, ...])`；401 → auth_error + `error401`；其它异常 → `offline`。
4. 按 `(platform, self_id)` 匹配 Studio 返回的 inbox，回写 `store.set_channel_inbox(id, inbox_id)`，建 entry。
5. `_push_state("online")`，并行起 5 类循环线程。

### 循环

- **producer × N**（每 inbox 一线程，`PRODUCER_INTERVAL_S` 节奏）：
  1. `adapter.list_conversations()`
  2. 算签名 `_conv_signature(convs)`，跟 `entry["conv_signature"]` 比对——**diff** 才调 `studio.push_conversations(inbox_id, ...)`；成功后更新签名
  3. 对每个 conv（DM 和 group 同等对待）：`since = store.get_cursor(...)` → `adapter.fetch_new(conv_id, since)` → `store.ingest(inbox_id, conv_id, events, new_cursor)`
  - `Unauthorized` → 摘除本 inbox，`degraded`，本线程退出
  - `TransientError` → 3s 退避；其它异常 → 5s
- **consumer 1s**：`get_unsent(50, _active_takeovers)` → `studio.push_incoming([{inbox_id, platform_conversation_id, client_id, sender_id, msg_type, content, sent_at}, ...])` → `mark_sent`。adapter 已摘除的 inbox 行直接 `mark_sent`。401 静默 return。
- **heartbeat 15s**：`studio.heartbeat()`（body 空）；401 → auth_error + `error401` + `stop()`。
- **takeovers 10s**：`studio.get_takeovers()` → 重建 `_active_takeovers` set。
- **outbound long-poll**：`studio.get_outbound(30)` → 对每个 item：`id` 已在 `_inflight_outbound` 则跳；否则加入 set，调 `_dispatch_outbound(item)` → `adapter.send(item["platform_conversation_id"], payload)`。错误只 log，不上报（没有 ack/failed 端点）。401 → auth_error + stop。

### stop()
置 `_stop`，join 线程（2s 超时），清空 `_adapters`，`_push_state("idle")`。**不关 store**——store 生命周期归 `commands.Context`（一个 active account 一个 store）。

## REPL/GUI 集成

`commands.Context.store` 持当前 active store；运行时通过它读 channels、写 inbox_id。`_make_runtime` 把 `store.kv_get`/`set` 包成 base_info/get_token/get_machine_id 闭包传给 runtime/StudioClient——runtime 不直接持 sqlite 连接，只走 store 方法。
