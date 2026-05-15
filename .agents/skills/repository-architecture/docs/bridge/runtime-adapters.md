# Bridge Runtime and Adapters / Bridge 运行时与适配器

## Adapter contract

`bridge/adapters/base.py` 定义当前平台抽象。

### `IncomingMessage`

字段：

- `peer_id`：平台侧对方 id。
- `peer_display_name`：对方展示名。
- `platform_msg_id`：平台消息 id（nullable），advisory，用于平台侧 cursor。
- `sender_id`：发送者平台 id（区分 self/counterpart 用 inbox.platform_self_id 比较）。
- `msg_type`：`text | image | audio | video | file`。text 时 content 为文本；media 时 content 为平台 S3 storage key。
- `content`：文本内容或平台 storage key。
- `sent_at`：UTC-aware datetime。

### `Adapter`

必须实现的 async 方法：

- `login() -> str`：登录平台，返回 `platform_self_id`。
- `list_peers() -> list[dict]`：返回 `[{"peer_platform_id": ..., "display_name": ...}]`，供 announce loop 上报 Studio；默认空列表，子类应覆盖。
- `scan(cursors: dict[str, str | None]) -> AsyncIterator[IncomingMessage]`：无限循环，持续 yield 历史和实时消息。`cursors` 是 `{peer_id: last_platform_msg_id}` 映射，adapter 读取并在 yield 后更新。
- `send(peer_id, msg_type, content) -> str`：发送消息，返回平台消息 id。
- `send_text(peer_id, content) -> str`：便捷方法，委托 `send()`。
- `download_media(storage_key) -> (bytes, mime_type)`：从平台 S3 下载媒体二进制。
- `upload_and_send_media(peer_id, msg_type, data, filename, mime_type) -> str`：上传二进制到平台 S3 后发送。
- `close()`：释放资源。

约定：

- Adapter 不知道 Studio `inbox_id`。
- Adapter 不实现 typing delay。
- Runtime 给 inbound 消息加 `inbox_id`。

## Adapter registry

- `register_adapter(platform, factory)` 注册 factory。
- `build_adapter(platform, raw_config)` 找 factory；找不到则退出。
- `chat.py` import 时注册 `chat` adapter。

## ChatAdapter

`bridge/adapters/chat.py` 把 Chat sandbox 包装成 Channel adapter。

内部状态：

- `base`、`username`、`password`。
- `_http`：`httpx.AsyncClient`。
- `_token`：Chat auth token。
- `_self_account_id`：Chat 登录后返回的 account id。
- `_threads`：`{conv_id: {peer_id, peer_display_name}}`。
- `_poll_sleep = 2.0`。

### `login()`

- POST `{base}/api/auth/login`，保存 token 和 account id，返回 account id 作为 `platform_self_id`。

### `_refresh_threads()`

- GET `/api/conversations`，更新 `self._threads`（新 thread 初始化，已有 thread 更新 display name）。

### `list_peers()`

- 调 `_refresh_threads()`，返回 `self._threads` 中所有 peer 的 `{peer_platform_id, display_name}` 列表。

### `scan(cursors)`

- 无限循环：`_refresh_threads()` → 对每个 thread 用 `since_id = cursors.get(peer_id) or 0` 拉取消息 → yield `IncomingMessage` → 更新 `cursors[peer_id]`。
- 无消息时 sleep 2s。
- 401 时重新 login；其它异常 log 后继续。

### `send()` / `upload_and_send_media()`

与 outbound dispatch 协作，流程见 Outbound loop 节。

## LocalStore

`bridge/local_store.py`，SQLite-backed 本地消息持久化。WAL 模式。

### 表：`local_messages`

字段：`id`（autoincrement）、`inbox_id`、`peer_id`、`peer_display_name`、`platform_msg_id`（nullable）、`sender_id`、`sent_at`（canonical UTC ISO8601）、`msg_type`、`content`（text: 明文；media: `sha256:{hex}`）、`mime_type`（media 时非 null）、`local_hash`（SHA256 去重键）、`sent`（0/1）。

索引：`UNIQUE(inbox_id, local_hash)`（本地去重）、`(sent, id)`（consumer 查询）、`(inbox_id, peer_id, id)`（cursor 查询）。

### 关键方法

- `migrate()`：建表，每次启动安全调用。
- `get_cursors(inbox_id) -> {peer_id: last_platform_msg_id}`：从已插入行推导各 peer 的扫描位置。
- `insert_message(msg) -> bool`：`INSERT OR IGNORE`，返回是否实际插入（local_hash 去重）。
- `get_unsent(limit, active_peers) -> list[LocalMessage]`：返回 `sent=0` 的行；`active_peers` 为 `frozenset[(inbox_id, peer_id)]`，非 None 时按 `(inbox_id, peer_id) IN (...)` 过滤，空 frozenset 直接返回 `[]`。
- `mark_sent(id)`：将行标记为已发送。

### local_hash 计算

`sha256("\x00".join([inbox_id, peer_id, sender_id, sent_at_canonical, msg_type, content]))`

content 是 *存储形式*：text 用明文，media 用 `sha256:{hex}`（文件内容 hash）。

## BridgeRuntime

`bridge/runtime.py`，当前采用 producer-consumer inbound 模型。

### 常量

- `HEARTBEAT_INTERVAL = 15.0`
- `OUTBOUND_LONG_POLL_TIMEOUT = 30`
- `CONSUMER_SLEEP = 1.0`
- `CONSUMER_BATCH = 50`
- `ANNOUNCE_INTERVAL = 60.0`
- `ACTIVE_PEERS_INTERVAL = 10.0`

### 关键字段

- `_adapters: dict[inbox_id, _AdapterEntry]`：每个 inbox 一个 adapter entry，含 `producer_task`。
- `_cursor: int`：outbound cursor（Studio→Bridge 队列游标）。
- `_active_peers: frozenset[(inbox_id, peer_id)]`：当前 `takeover=True` 的 peer 集合，由 `_active_peers_loop` 维护。
- `_stop: Event`。
- `_loop_tasks`：heartbeat / consumer / outbound / announce / active-peers loop tasks。
- `_media_sem`：限制并发媒体下载（最多 5）。

### 启动序列（`run()`）

1. 对每个 claim：build adapter → login → 收集 `(claim, adapter, self_id)`。
2. handshake 或 token 复用。
3. `store.migrate()`。
4. 对每个成功登录的 claim：绑定 inbox_id → 初始化 `cursors = store.get_cursors(inbox_id)` → 启动 `producer_task`。
5. 启动 heartbeat / consumer / outbound / announce / active-peers 五个 loop task。

## Inbound 流程（producer-consumer 模型）

```text
adapter.scan(cursors)
  → _producer_loop (per inbox)
      → _to_local_message()        # 文本直接用；媒体 download + sha256 + 落磁盘
      → store.insert_message()     # UNIQUE(inbox_id, local_hash) 本地去重

store.get_unsent(active_peers=self._active_peers)
  → _consumer_loop (global, 1s sleep)
      → _resolve_content()         # text 直接取；media check-or-presign → 必要时 PUT S3
      → studio.push_incoming()     # POST /api/bridge/incoming
      → store.mark_sent()
```

**媒体处理（producer）**：下载 → `sha256(data)` → 缓存到 `{media_cache_dir}/{sha256hex}` → content 存 `sha256:{hex}`；mime_type 同步记录。

**媒体处理（consumer）**：调 `check-or-presign`；status=exists 跳过上传；status=new 从 cache 读 bytes → PUT Studio S3 → 用 storage_key 作为 content 上传。

**active_peers 过滤**：consumer 只推送 `(inbox_id, peer_id)` 在 `_active_peers` 集合中的消息。不在集合的消息 `sent=0` 留在本地 store，待接管后由 consumer 自动补发历史。Producer 和 cursor 不受影响——无论是否接管，Bridge 本地全量采集。

## Peer 目录与接管同步

### `_announce_loop`（60s 周期）

对每个 adapter 调 `list_peers()` → 调 `POST /api/bridge/peers` 上报发现的 peer 列表，供 Studio 前端展示会话目录。启动后立即执行第一次。

### `_active_peers_loop`（10s 周期）

调 `GET /api/bridge/active-peers` 拉取 `takeover=True` 的 peer 集合 → 更新 `self._active_peers`。启动后立即执行第一次，确保 consumer 在首次 1s sleep 前即有正确的 active peers。

## Heartbeat loop

每 15 秒：POST `/api/bridge/heartbeat`，收到当前 Studio 认可的 inbox 列表，停掉不在列表中的 adapter。

## Outbound loop（含 media 下发）

```text
GET /api/bridge/outbound?cursor=current&timeout=30
  → 对每个 id > cursor 的 item：
       _dispatch_outbound(item)
       cursor = item.id
```

`_dispatch_outbound()` 当前行为：

- 用 `inbox_id` 找 adapter；找不到 ack failed。
- `msg_type == 'text'`：调 `adapter.send_text()`。
- `msg_type != 'text'`（media）：调 `studio.get_media_url(content)` → 下载二进制 → `adapter.upload_and_send_media()`。
- 成功 ack `sent`（携带 platform_msg_id），异常 ack `failed`（携带 reason）。

打字节奏由 Studio 在创建 OutboundMessage 时通过 `send_after` 时间戳控制；Bridge 直接按 `send_after <= now` 消费，不实现额外 delay。
