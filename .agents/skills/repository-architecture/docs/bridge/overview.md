# Bridge Desktop App / Bridge 桌面应用总览

## 当前形态

`desktop/` 是运行在主播/运营本机的 **Electron 桌面应用**。它内嵌一个 TypeScript daemon，持有平台登录态，并在 Chat adapter 和 Studio 之间桥接消息。对 text 消息，Bridge 是透明管道；媒体消息当前仅文本路径已实现，媒体 S3 搬运为 stub（chat sandbox 实践中只发 text）。

## 目录结构

```text
desktop/
  package.json
  electron-vite.config.ts
  electron-builder.yml
  tsconfig.json / tsconfig.node.json / tsconfig.web.json
  src/
    main/
      index.ts              # Electron 主进程：窗口、托盘、IPC handlers、daemon 生命周期
      state.ts              # Store（safeStorage 加密 token + chat 密码，不存 Studio 密码）
      daemon/
        types.ts            # 共享类型：DaemonState、LogLine、Channel 等
        studio-client.ts    # Studio /api/bridge/* 全部 HTTP 端点
        local-store.ts      # SQLite 去重表（better-sqlite3，WAL 模式）
        adapters/
          chat.ts           # Chat sandbox HTTP 轮询适配器
        runtime.ts          # BridgeRuntime：5 个并发循环
    preload/
      index.ts              # contextBridge：暴露给 renderer 的全部 IPC 接口
    renderer/
      index.html
      src/
        main.tsx            # React 入口
        App.tsx             # 2 屏（hasToken ? Channels : Login）
        index.css           # 与 Studio 同源的 @theme design token
        components/
          shared.tsx        # 共享 UI：StatusChip、Field、Btn…
        screens/
          Login.tsx         # 登录屏（Studio URL + 账号密码）
          Channels.tsx      # 唯一主页：channel 增删 + 状态 + 日志 + 登出
```

## 技术栈

- **Electron 33+**，`electron-vite` 构建，`electron-builder` 打包
- **主进程**（Node）：daemon 核心逻辑，HTTP 网络 IO，`better-sqlite3` 本地存储，`safeStorage` 凭据加密
- **Preload**：`contextBridge` 类型安全 IPC
- **Renderer**：React 19 + Tailwind v4，与 Studio 使用同一套 oklch design token，无第三方 UI 库

## IPC schema（preload 暴露给 renderer）

```typescript
window.bridge.bootstrap()        // { studioUrl, username, hasToken, channels, state }
window.bridge.login(opts)        // 用 Studio 账号密码 handshake，存 token，自动起 daemon
window.bridge.logout()           // 停 daemon，清除 token
window.bridge.getChannels()      // 已保存 channel 列表（无密码）
window.bridge.saveChannels(c)    // 保存 channel 并重启 daemon（重新注册）
window.bridge.stop()             // 停止 daemon
window.bridge.openStudio()       // shell.openExternal 打开 Studio URL
window.bridge.onState(cb)        // 订阅 DaemonState push（返回 unsubscribe）
window.bridge.onLog(cb)          // 订阅 LogLine push（返回 unsubscribe）
```

## 凭据管理

`Store`（`src/main/state.ts`）用 Electron `safeStorage`（OS keychain 加密）持久化 Studio session token 和 chat 平台密码。Studio 密码只在 `bridge:login` 调用期间于内存使用，绝不落盘；token 重启复用，仅 401 时回登录页重新输密码。

持久化文件位于 `app.getPath('userData')` 下：

- `bridge-state.json`：studioUrl、username、machineId、bridgeId、channels（chat baseUrl/username + safeStorage 加密密码）
- `bridge-token.enc`：safeStorage 加密的 Studio session token
- `data/messages.db`：SQLite 去重消息表

## 2 屏

```text
App 启动 → bridge.bootstrap()
  hasToken=false（首启 / 401）
    → Login（Studio URL + 账号密码 → bridge.login → 存 token）
  hasToken=true
    → Channels（唯一主页）
        - channel 增删（chat baseUrl/username/password）
        - 行内状态：daemon StatusChip、每 channel 在线/会话数、收发计数
        - daemon 日志 tail、打开 Studio↗、退出登录
        - 保存 → bridge.saveChannels → daemon 重启并重新注册
```

接管与回复策略不在 Bridge 配置，「打开 Studio↗」引导用户去 Studio 设置。

## 启动生命周期

```text
app.whenReady()
  → new Store() → createWindow() → registerIpc() → Tray()
  → hasToken && hasChannels → startDaemon()   # 复用持久化 token，无需密码
        ↓
BridgeRuntime.run({ onAuthError })            # 不接受密码
  → ChatAdapter.login() × N                   # 收集 selfId
  → StudioClient.registerInboxes(selfIds)     # token 鉴权注册 channel
  → 绑定 adapter ↔ inbox
  → startProducer() × N   # per-inbox 无限扫描循环
  → startConsumer()        # 1s 间隔推 Studio
  → startHeartbeat()       # 15s
  → startAnnounce()        # 60s
  → startActivePeers()     # 10s
  → startOutbound()        # long-poll 30s，收到 text 即发
```

`bridge:login` 成功后若已有 channel 立即 startDaemon；`bridge:save-channels` 会 stop 再 start 以重新注册。

## Bridge 当前不做的事

- 不调 LLM
- 不存 Persona / Contact Card
- 不判断 autoreply 是否开启
- 不选择 ProviderConfig
- 不实现媒体 S3 搬运（chat adapter 实践上只发 text）
- 不持久化 Studio 密码
