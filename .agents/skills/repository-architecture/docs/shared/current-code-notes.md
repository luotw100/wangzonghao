# Current Code Notes / 当前代码注意点

本文只记录当前代码事实和仓库中已存在文件的状态，不记录规划。

## Studio Vite proxy

`services/studio/web/vite.config.ts` 当前把 `/api` proxy 到 `localhost:23457`。

## Bridge 默认 Studio URL

`services/bridge/bridge/main.py` 当前定义 `DEFAULT_STUDIO_URL = "https://studio.laborster.com"`。本地联调命令通过 `--studio-url` 覆盖。

## Model defaults

Chat sandbox 和 Studio models 当前都不使用 SQLAlchemy column defaults；insert 路径必须显式写入状态、时间戳和布尔值。

## Bridge offline 状态

Studio 当前会在 heartbeat 时更新 `Bridge.last_seen_at` 并保持 `status='online'`。当前代码没有自动把长时间无 heartbeat 的 Bridge 转成 `offline` 的 scanner。

## Bridge token

Bridge session token 只保存在 Bridge 内存中。Bridge 重启后重新 handshake；Studio 会清掉同一 Bridge 的旧 BridgeSession。

## Provider UI

Studio Provider 管理在 Settings 页面，仅 admin 可见。当前 UI 支持创建、启用/禁用和设为默认；普通 user 不展示 Provider 选择和 Provider 管理。

## Archive ingest

Archive ingest 当前只支持 1:1 聊天。`_identify_counterpart()` 在出现多个 counterpart 时抛错。

`studio/distill/ingest.py` 中 `_ensure_contact()` 当前创建 Contact 时显式设置 Persona、Provider、autoreply、pending、status 等字段；`reply_provider_config_id` 继承 Inbox 的 Provider override，允许为空。
