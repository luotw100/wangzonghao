# Bridge Runtime and Adapters / Bridge 运行时与适配器

## Adapter contract

`bridge/adapters/base.py` 定义当前平台抽象。

### `IncomingMessage`

字段：

- `peer_id`：平台侧对方 id。
- `peer_display_name`：对方展示名，用于 Studio Contact 创建/展示。
- `platform_msg_id`：平台消息 id，用于 Studio 去重。
- `role`：`self | counterpart`。
- `content`：文本内容。
- `sent_at`：naive UTC datetime。

### `Adapter`

必须实现的 async 方法：

- `login() -> str`：登录平台并返回 `platform_self_id`。
- `list_initial_messages(since_ms) -> list[IncomingMessage]`：启动时补抓消息。
- `stream_incoming() -> AsyncIterator[IncomingMessage]`：持续产生新消息。
- `send_text(peer_id, content) -> str`：发送一条文本，返回平台消息 id。
- `close()`：释放资源。

约定：

- Adapter 不知道 Studio `inbox_id`。
- Adapter 不实现 typing delay。
- Runtime 给 inbound 消息加 `inbox_id`。
- Studio 用 `external_id = live:{platform_msg_id}` 去重。

## Adapter registry

- `register_adapter(platform, factory)` 注册 factory。
- `build_adapter(platform, raw_config)` 找 factory；找不到则退出。
- `chat.py` import 时注册 `chat` adapter。

## ChatAdapter

`bridge/adapters/chat.py` 当前把 Chat sandbox 包装成 Channel adapter。

内部状态：

- `base`、`username`、`password`。
- `_http`：`httpx.AsyncClient`。
- `_token`：Chat auth token。
- `_self_account_id`：Chat 登录后返回的 account id。
- `_threads`：conversation id → `peer_id`、`peer_display_name`、`last_msg_id`。
- `_poll_sleep = 2.0`。

### `login()`

- POST `{base}/api/auth/login`。
- 保存返回 token。
- 保存 Chat account id。
- 返回 account id 作为 `platform_self_id`。

### `_refresh_threads()`

- GET `/api/conversations`。
- 对每个 conversation 记录 peer contact id 和 display name。
- 新 thread 的 `last_msg_id = 0`。

### `list_initial_messages()`

- refresh threads。
- 对每个 conversation 用 `last_id=0` 拉取全部 messages。
- 转成 `IncomingMessage`。
- 更新 thread 的 `last_msg_id`。

### `stream_incoming()`

- 无限循环。
- refresh threads。
- 拉取每个 conversation 中 `id > last_msg_id` 的 messages。
- yield 转换后的 IncomingMessage。
- 无消息时 sleep 2s。
- Chat 返回 401 时重新 login。

### `send_text()`

- 通过 peer id 找 conversation id；找不到时 refresh 一次。
- POST `/api/conversations/{conv_id}/messages`，body 使用 `sender_type='self'`。
- 返回 response 中的 `id` 作为 `platform_msg_id`。

## BridgeRuntime state

`runtime.py` 当前常量：

- heartbeat interval：15s。
- inbound batch linger：0.4s。
- inbound batch max：30。
- outbound long-poll timeout：30s。

关键字段：

- `_adapters: dict[inbox_id, _AdapterEntry]`。
- `_inbound_queue: Queue[(inbox_id, IncomingMessage)]`。
- `_cursor: int`：outbound cursor。
- `_stop: Event`。
- `_loop_tasks`：heartbeat / inbound / outbound loop tasks。

## Inbound pump

```text
adapter.stream_incoming()
  → _adapter_inbound_loop()
  → _inbound_queue
  → _inbound_pump_loop()
  → _push_batch()
  → StudioClient.push_incoming()
```

Batch 规则：

- 等第一条消息。
- 最多收集 0.4s 或 30 条。
- `_to_payload()` 转 Studio payload。
- POST `/api/bridge/incoming`。

## Heartbeat loop

每 15 秒：

1. POST `/api/bridge/heartbeat`。
2. 收到 Studio 当前认可的 Inbox 列表。
3. 停掉本地存在但不在列表中的 adapter。

这使得 Studio UI 中 revoke/unbind 后，Bridge 能停止对应 adapter。

## Outbound loop

```text
GET /api/bridge/outbound?cursor=current&timeout=30
  → 对每个 id > cursor 的 item：
       _dispatch_outbound(item)
       cursor = item.id
```

`_dispatch_outbound()` 当前行为：

- 用 `inbox_id` 找 adapter。
- 校验 `peer_platform_id`。
- 跳过空 content。
- 调 `adapter.send_text(peer_id, content)`。
- 成功时 ack `sent`，携带 platform message id。
- 异常时 ack `failed`，携带 reason。

Bridge 不实现任何 delay 或 pacing。打字节奏由 Studio 在创建 OutboundMessage 时通过 `send_after` 时间戳控制。
