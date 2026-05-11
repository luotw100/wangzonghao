# Bridge Overview / Bridge 总览

## 当前角色

`services/bridge` 是运行在主播/运营本机的 daemon。它持有平台登录态，并在 Channel adapters 和 Studio 之间桥接消息。

Bridge 是无状态 daemon：不保存 DB、不保存长期 token；全部运行状态来自 CLI args、内存 token 和 adapter 内存状态。

## 目录结构

```text
services/bridge/
  compose.yaml
  Dockerfile
  pyproject.toml
  bridge/
    main.py
    runtime.py
    studio_client.py
    adapters/
      base.py
      chat.py
```

## 依赖

`pyproject.toml` 当前只有运行时依赖 `httpx`。其余使用 Python stdlib：`asyncio`、`logging`、`dataclasses` 等。

## CLI

`bridge/main.py` 当前参数：

- `--studio-username`：必填。
- `--studio-password`：必填。
- `--studio-url`：可选，默认 `https://studio.laborster.com`。
- `--hostname`：可选，默认 `socket.gethostname()`。
- `--chat-inbox`：可重复，格式 `base_url=...,username=...,password=...`。

一条 `--chat-inbox` 会变成 `InboxClaim(platform='chat', raw={...})`。

## 启动生命周期

```text
main()
  → parse args
  → 创建 InboxClaim list
  → 创建 StudioClient
  → 创建 BridgeRuntime
  → 注册 SIGINT/SIGTERM handler
  → await runtime.run()
```

`bridge.adapters.chat` 在 `main.py` 中以 side-effect import 方式加载；模块加载时调用 `register_adapter('chat', _build_chat_adapter)`。

## BridgeRuntime 当前职责

1. 每个 claim build 一个 adapter。
2. 登录每个 platform adapter。
3. 用 `(platform, platform_self_id)` 列表 handshake Studio。
4. 用 Studio 返回的 `inbox_id` 绑定本地 adapter。
5. 执行 initial catch-up。
6. 启动 heartbeat loop。
7. 启动 inbound batching pump。
8. 启动 outbound long-poll loop。
9. 平台发送和 ack。

## Bridge 当前不做的事

- 不调 LLM。
- 不存 Persona / Contact Card。
- 不判断 autoreply 是否应该开启。
- 不选择 ProviderConfig。
- 不持久化 Studio session token。
