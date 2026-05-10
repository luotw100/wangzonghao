# Chat Infrastructure / Chat 基础设施

## Compose

`services/chat/compose.yaml` 当前定义三个 service 和两个 volume。

### `chat-web`

- build context：`./web`。
- dockerfile：`Dockerfile`。
- host port：`23456:23456`。
- mount `./nginx.conf:/etc/nginx/conf.d/default.conf:ro`。
- depends on `chat-api`。
- restart：`unless-stopped`。

### `chat-api`

- build context：`./api`。
- env：`CHAT_STORAGE_DIR=/app/storage`、`DATABASE_URL=postgresql://chat:chat@chat-db/chat`。
- mount `chat-storage:/app/storage`。
- depends on `chat-db`（condition: `service_healthy`）。
- restart：`unless-stopped`。

### `chat-db`

- image：`postgres:16-alpine`。
- env：`POSTGRES_USER=chat`、`POSTGRES_PASSWORD=chat`、`POSTGRES_DB=chat`。
- mount `chat-pgdata:/var/lib/postgresql/data`。
- healthcheck：`pg_isready -U chat`。
- restart：`unless-stopped`。

### Volumes

- `chat-storage`：保存 storage assets。
- `chat-pgdata`：PostgreSQL 数据目录。

## Nginx

`services/chat/nginx.conf` 当前行为：

- listen `23456`。
- 从 `/usr/share/nginx/html` serve SPA。
- `try_files $uri $uri/ /index.html`。
- `/storage/` 显式返回 404。
- `/api/` proxy 到 `http://chat-api:23456/api/`。
- 设置 `Host` 和 `X-Real-IP`。
- `client_max_body_size 50m`。

## API Dockerfile

`services/chat/api/Dockerfile` 当前行为：

- base image：`python:3.12-slim`。
- 安装 `uv`。
- copy `pyproject.toml` 和 `uv.lock`。
- 执行 `uv sync --frozen --no-dev --no-install-project`。
- copy `alembic.ini`。
- copy `chat/` package。
- 创建 `/app/storage/attachments`。
- command：`uv run uvicorn chat.main:app --host 0.0.0.0 --port 23456`。

## Web Dockerfile

`services/chat/web/Dockerfile` 当前行为：

- build stage：`node:20-alpine`。
- 执行 `npm ci` 和 `npm run build`。
- runtime stage：`nginx:alpine`。
- copy dist 到 `/usr/share/nginx/html`。

## Vite dev server

`services/chat/web/vite.config.ts` 当前行为：

- 使用 React plugin。
- dev server host `0.0.0.0`，port `5173`。
- `/api` proxy 到 `http://localhost:23456`。

## 必要环境变量

`DATABASE_URL` 和 `CHAT_STORAGE_DIR` 都必须存在。缺失时 `chat/db.py` 会直接抛错。

## Database

Chat 使用 PostgreSQL，由 Alembic 管理 schema 迁移。启动时通过 FastAPI lifespan 调用 `run_migrations()`（`chat/migrate.py`），自动执行 `alembic upgrade head`。CLI 在入口也调用 `run_migrations()`。

Schema 变更流程：修改 `models.py` → 生成新的 Alembic migration → `alembic upgrade head`。

## 运行注意点

- Chat 账号和 Studio 账号是两套 DB。
- Bridge 需要 Chat sandbox 账号密码。
- Docker 中的 Bridge 访问本机 Chat 时使用 `http://host.docker.internal:23456`。