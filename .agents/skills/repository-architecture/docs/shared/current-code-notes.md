# Current Code Notes / 当前代码注意点

本文只记录当前代码事实和仓库中已存在文件的状态，不记录规划。

## Studio Vite proxy

`services/studio/web/vite.config.ts` 当前把 `/api` 和 `/storage` proxy 到 `localhost:23456`，而 Studio Compose 默认端口是 `23457`。这是当前文件内容，使用 Vite dev server 前需要核对。

## Bridge 默认 Studio URL

`services/bridge/bridge/main.py` 当前定义 `DEFAULT_STUDIO_URL = "https://studio.laborster.com"`。本地联调命令通过 `--studio-url` 覆盖。

## Chat model defaults

Chat sandbox models 当前使用 SQLAlchemy column defaults，例如 `status='active'` 和 timestamp defaults。Studio models 当前文件头明确要求不用 column-level defaults。

## Bridge offline 状态

Studio 当前会在 heartbeat 时更新 `Bridge.last_seen_at` 并保持 `status='online'`。当前代码没有自动把长时间无 heartbeat 的 Bridge 转成 `offline` 的 scanner。

## Bridge token

Bridge session token 只保存在 Bridge 内存中。Bridge 重启后重新 handshake；Studio 会清掉同一 Bridge 的旧 BridgeSession。

## Provider UI

Studio API 和前端 API client 当前都有 Provider update 能力；StudioPage 的 Providers tab 当前只暴露 create/delete，没有完整 edit UI。

## Archive ingest

Archive ingest 当前只支持 1:1 聊天。`_identify_counterpart()` 在出现多个 counterpart 时抛错。

`studio/distill/ingest.py` 中 `_ensure_contact()` 当前创建 Contact 时显式设置 Persona、autoreply、pending、status 等字段；`reply_provider_config_id` 字段在当前代码路径中没有显式传入，数据库列允许 NULL。
