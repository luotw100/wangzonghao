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
      state.ts              # CredentialStore（safeStorage 加密 token，不持久化密码）
      daemon/
        types.ts            # 共享类型：DaemonState、LogLine、InboxClaim 等
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
        App.tsx             # 4 屏状态机（login→inbox→panel/settings）
        index.css           # 与 Studio 同源的 @theme design token
        components/
          shared.tsx        # 共享 UI：Rail、StatusChip、KPIStat、Btn、Toggle…
        screens/
          Login.tsx         # 首启/Re-auth 屏
          InboxConfig.tsx   # Inbox 列表配置屏
          Panel.tsx         # 主状态面板（KPI、inbox 列表、日志）
          Settings.tsx      # 通用/网络/账号设置
```

## 技术栈

- **Electron 33+**，`electron-vite` 构建，`electron-builder` 打包
- **主进程**（Node）：daemon 核心逻辑，HTTP 网络 IO，`better-sqlite3` 本地存储，`safeStorage` 凭据加密
- **Preload**：`contextBridge` 类型安全 IPC
- **Renderer**：React 19 + Tailwind v4，与 Studio 使用同一套 oklch design token，无第三方 UI 库

## IPC schema（preload 暴露给 renderer）

```typescript
window.bridge.getState()        // 获取当前 DaemonState 快照
window.bridge.getCreds()        // 获取凭据信息（无敏感字段）
window.bridge.handshake(opts)   // 登录并握手 Studio
window.bridge.logout()          // 清除 token，停止 daemon
window.bridge.getInboxes()      // 获取已保存 inbox 列表（无密码）
window.bridge.saveInboxes(claims)// 保存 inbox 配置
window.bridge.start()           // 启动 daemon
window.bridge.stop()            // 停止 daemon
window.bridge.openStudio()      // shell.openExternal 打开 Studio URL
window.bridge.onStateChange(cb) // 订阅 DaemonState push（返回 unsubscribe）
window.bridge.onLog(cb)         // 订阅 LogLine push（返回 unsubscribe）
```

## 凭据管理

`CredentialStore`（`src/main/state.ts`）使用 Electron 内置 `safeStorage`（OS keychain 加密）持久化 token。密码只在握手时在内存中使用，握手后丢弃。

持久化文件位于 `app.getPath('userData')` 下：

- `bridge-state.json`：studioUrl、username、machineId、bridgeId、inbox 列表（密码 safeStorage 加密）
- `bridge-token.enc`：safeStorage 加密的 session token
- `data/messages.db`：SQLite 去重消息表
- `data/media/`：媒体 binary 缓存

## 4 屏状态机

```text
首启 / 401
  → Login（输入 Studio URL + 账号密码 → handshake）
        ↓ 成功
  → InboxConfig（配置 chat inbox 列表，密码 safeStorage 加密存储）
        ↓ 保存并启动
  → Panel（主面板：KPI 网格 + inbox 状态 + 日志 tail + Studio 引导）
        ↓ 导航
  → Settings（通用 / 网络 / 账号）
```

Panel 有「打开 Studio ↗」按钮，引导用户前往 `studio.laborster.com` 配置接管策略——Bridge 本身不管策略，只做 IO。

## 启动生命周期

```text
app.whenReady()
  → CredentialStore.load()
  → createWindow()
  → registerIpc()
  → Tray()
  → hasToken && hasInboxes → startDaemon()
        ↓
BridgeRuntime.run()
  → ChatAdapter.login() × N
  → StudioClient.handshake()
  → startProducer() × N   # per-inbox 无限扫描循环
  → startConsumer()        # 1s 间隔推 Studio
  → startHeartbeat()       # 15s
  → startAnnounce()        # 60s
  → startActivePeers()     # 10s
  → startOutbound()        # long-poll 30s，收到 text 即发
```

## Bridge 当前不做的事

- 不调 LLM
- 不存 Persona / Contact Card
- 不判断 autoreply 是否开启
- 不选择 ProviderConfig
- 不实现媒体 S3 搬运（chat adapter 实践上只发 text）
- 不持久化密码
