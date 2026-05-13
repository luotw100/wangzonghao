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

## ID 生成

所有非自增主键使用 `new_id(prefix)` 生成，格式为 `{prefix}_{uuid4().hex}`（完整 128 bit UUID hex，32 字符随机部分）。128 bit 熵下碰撞概率可忽略，不需要重试逻辑。

- Studio: `studio/deps.py` 中的 `new_id(prefix)` 函数。
- Chat: `chat/main.py` 中的 `new_id(prefix)` 函数。
- 辅助模块中的 ID 生成（`studio/cli.py`）也使用 `new_id()`，不内联 `uuid4().hex`。

Auth/AuthSession 的 ID 使用 `hash_token(secrets.token_urlsafe(32))`（SHA-256，64 hex 字符），不会碰撞。

## API 模块结构

`studio/main.py` 当前是薄入口，仅 mount 各 router module。路由处理逻辑分布在 `studio/routers/` 目录下（auth, accounts, providers, personas, bridges, inboxes, contacts, distill, bridge_protocol）。序列化函数在 `studio/serializers.py`，认证依赖和 ownership helpers 在 `studio/deps.py`。

## Inbox 创建

Inbox 仅由 Bridge handshake 自动 upsert 创建，没有独立的创建 API。

## Bridge offline 状态

Studio worker 中 `BridgeOfflineScanner` 每 30s 扫描 `last_seen_at` 超过 45s 的 online Bridge，将其标为 offline。heartbeat 收到请求时会实时标回 online。offline 不影响已入队的 outbound 消息——它们会在 Bridge 恢复在线后被投递。

## Bridge token

Bridge session token 保存在本地 `state.json`（`--state-dir` 目录）中。Bridge 重启时优先尝试复用已保存的 token 调用 heartbeat；成功则跳过 handshake。如果 token 过期（401）或有新的 `--chat-inbox` 声明，则走完整 handshake。旧 BridgeSession 在 handshake 时被清除。

## Provider UI

Studio Provider 管理在 Settings 页面，仅 admin 可见。当前 UI 支持创建、启用/禁用和设为默认；普通 user 不展示 Provider 选择和 Provider 管理。
