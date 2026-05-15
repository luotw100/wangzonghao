# Bridge Desktop Infrastructure / Bridge 桌面基础设施

## 构建工具链

| 工具 | 版本约束 | 职责 |
| --- | --- | --- |
| electron | ^33.0.0 | 宿主运行时 |
| electron-vite | ^2.3.0 | 开发服务器 + 三进程构建（main/preload/renderer） |
| electron-builder | ^25.0.0 | 跨平台打包：macOS .dmg、Windows NSIS .exe |
| electron-rebuild | ^3.2.9 | 为当前 Electron Node ABI 重编译原生模块 |
| better-sqlite3 | ^11.0.0 | 原生 SQLite 模块（postinstall 自动 rebuild） |
| React 19 + Tailwind v4 | — | renderer UI |

## 目录约定

```text
desktop/
  dist-electron/    # electron-vite 构建产物（git-ignored）
  dist-release/     # electron-builder 打包产物（git-ignored）
  resources/
    tray-icon.png   # 托盘图标（16×16 推荐 macOS template image）
```

## 本地开发

```bash
cd desktop
npm install            # postinstall 自动运行 electron-rebuild
npm run dev            # electron-vite dev：renderer HMR + main 进程自动重启
```

开发模式 renderer 加载 `http://localhost:5173`，main 进程直接读取 `src/main/` TS 源码（electron-vite 实时编译）。配置指向本地 Studio 只需在 Login 屏修改 Studio URL 为 `http://localhost:23457`，不需要任何环境变量。

## 打包

```bash
npm run build        # tsc 类型检查 + electron-vite build
npm run dist:mac     # electron-builder --mac → dist-release/*.dmg
npm run dist:win     # electron-builder --win → dist-release/*.exe（需 Windows 环境）
```

**macOS 无签名说明**：不签名 / 不公证时，Gatekeeper 会拒绝打开 DMG。内部分发绕过方式：

```bash
xattr -rd com.apple.quarantine /Applications/Laborster\ Bridge.app
```

**Windows 无签名说明**：SmartScreen 在首次运行时弹出警告，点「更多信息 → 仍要运行」可跳过。

## electron-builder 配置（electron-builder.yml 摘要）

```yaml
appId: com.laborster.bridge
asar: true
asarUnpack:
  - "**/*.node"         # better-sqlite3 原生模块必须解包，不能 asar 包内运行
mac:
  target: [dmg x64, dmg arm64]
win:
  target: [nsis x64]
```

## GitHub Actions 发布流程

`.github/workflows/desktop.yml`，手动触发（`workflow_dispatch`）：

1. macOS runner（`macos-14` arm64）和 Windows runner（`windows-latest`）并行构建
2. 各自 `npm ci` → `electron-rebuild` → `npm run build` → `electron-builder`
3. 产物上传为 GitHub Actions artifact（保留 14 天）
4. 手动触发：GitHub UI → Actions → Desktop Build → Run workflow

## 用户数据目录

运行时数据存储在 `app.getPath('userData')`，**升级和重装不会清除**：

| 平台 | 路径 |
| --- | --- |
| macOS | `~/Library/Application Support/Laborster Bridge/` |
| Windows | `%APPDATA%\Laborster Bridge\` |

目录内容：

```text
bridge-state.json   # Studio URL、username、machineId、bridgeId、inbox 列表
bridge-token.enc    # safeStorage 加密的 session token
data/
  messages.db       # SQLite 本地去重消息表（WAL 模式）
  media/            # 媒体 binary 缓存
```

## 原生模块注意点

`better-sqlite3` 是原生 `.node` 模块，必须为目标 Electron 的 Node ABI 单独编译。`postinstall` 脚本会自动执行 `electron-rebuild`。在 CI 中 `npm ci` 之后 `postinstall` 会再次触发，确保 GitHub runner 上的二进制与 Electron 版本匹配。`asar: true` + `asarUnpack: ["**/*.node"]` 确保原生模块在 asar 包外可被正常加载。
