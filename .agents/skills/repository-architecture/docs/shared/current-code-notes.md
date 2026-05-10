# Current Code Notes / 当前代码注意点

本文只记录当前代码事实和仓库中已存在文件的状态，不记录规划。

## Studio Vite proxy

`services/studio/web/vite.config.ts` 当前把 `/api` proxy 到 `localhost:23457`。

## Bridge 默认 Studio URL

`services/bridge/bridge/main.py` 当前定义 `DEFAULT_STUDIO_URL = "https://studio.laborster.com"`。本地联调命令通过 `--studio-url` 覆盖。

## Model defaults

Chat sandbox 和 Studio models 当前都不使用 SQLAlchemy column defaults；insert 路径必须显式写入状态、时间戳和布尔值。

## Database

Studio 和 Chat 都使用 PostgreSQL，由 Alembic 管理 schema 迁移。启动时通过 `run_migrations()` 执行 `alembic upgrade head`。所有 DateTime 列存储为 `timestamptz`（时区感知 UTC）。所有自增主键使用 `BigInteger`。

## Migrations

`studio/migrate.py` 和 `chat/migrate.py` 封装 Alembic `upgrade head`。API 启动通过 FastAPI lifespan 调用；Worker 和 CLI 在各自入口调用。

## Account ID

Account id 由 `studio/deps.py` 中的 `new_id("acc")` 生成，格式为 `acc_{uuid8}`（UUID 随机 8 位）。

## API 模块结构

`studio/main.py` 当前是薄入口，仅 mount 各 router module。路由处理逻辑分布在 `studio/routers/` 目录下（auth, accounts, providers, personas, bridges, inboxes, contacts, archives, bridge_protocol）。序列化函数在 `studio/serializers.py`，认证依赖和 ownership helpers 在 `studio/deps.py`。

## Inbox 创建

Inbox 仅由 Bridge handshake 自动 upsert 创建，没有独立的创建 API。

## Bridge offline 状态

Studio 在 heartbeat 时更新 `Bridge.last_seen_at` 并保持 `status='online'`。Bridge offline 状态仅由手动 revoke 设置，没有自动 offline scanner。

## Bridge token

Bridge session token 只保存在 Bridge 内存中。Bridge 重启后重新 handshake；Studio 会清掉同一 Bridge 的旧 BridgeSession。

## Provider UI

Studio Provider 管理在 Settings 页面，仅 admin 可见。当前 UI 支持创建、启用/禁用和设为默认；普通 user 不展示 Provider 选择和 Provider 管理。

## Archive ingest

Archive ingest 当前只支持 1:1 聊天。`_identify_counterpart()` 在出现多个 counterpart 时抛错。

`studio/distill/ingest.py` 中 `_ensure_contact()` 当前创建 Contact 时显式设置 Persona、Provider、autoreply、pending、status 等字段；`reply_provider_config_id` 继承 Inbox 的 Provider override，允许为空。

Archive model 中的 `platform_self_id` 字段标识 Archive 对应的平台自身 ID（之前名为 `self_wxid`）。
