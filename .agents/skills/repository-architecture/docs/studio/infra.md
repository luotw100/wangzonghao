# Studio Infrastructure / Studio 基础设施

## Compose

`services/studio/compose.yaml` 当前定义四个 service 和两个 volume。

### `studio-web`

- build context：`./web`。
- host port：`23457:23457`。
- mount `./nginx.conf:/etc/nginx/conf.d/default.conf:ro`。
- depends on `studio-api`。
- restart：`unless-stopped`。

### `studio-api`

- build context：`./api`。
- env：`STUDIO_STORAGE_DIR=/app/storage`、`DATABASE_URL=postgresql://studio:studio@studio-db/studio`。
- mount `studio-storage:/app/storage`。
- depends on `studio-db`（condition: `service_healthy`）。
- restart：`unless-stopped`。

### `studio-worker`

- build context：`./api`。
- command：`uv run python -m studio.worker --request-timeout 120`。
- env：`STUDIO_STORAGE_DIR=/app/storage`、`DATABASE_URL=postgresql://studio:studio@studio-db/studio`。
- mount 同一个 `studio-storage`。
- depends on `studio-api`。
- restart：`unless-stopped`。

### `studio-db`

- image：`postgres:16-alpine`。
- env：`POSTGRES_USER=studio`、`POSTGRES_PASSWORD=studio`、`POSTGRES_DB=studio`。
- mount `studio-pgdata:/var/lib/postgresql/data`。
- healthcheck：`pg_isready -U studio`。
- restart：`unless-stopped`。

### Volumes

- `studio-storage`：保存 uploads 和共享 storage 文件。
- `studio-pgdata`：PostgreSQL 数据目录。

## Nginx

`services/studio/nginx.conf` 当前行为：

- listen `23457`。
- 从 `/usr/share/nginx/html` serve SPA。
- `try_files $uri $uri/ /index.html`。
- `/storage/` 显式返回 404。
- `/api/` proxy 到 `http://studio-api:23457/api/`。
- `proxy_read_timeout 120s`。
- `client_max_body_size 50m`。

## API Dockerfile

`services/studio/api/Dockerfile` 当前行为：

- base image：`python:3.12-slim`。
- 安装 `uv`。
- copy `pyproject.toml` 和 `uv.lock`。
- 执行 `uv sync --frozen --no-dev --no-install-project`。
- copy `alembic.ini`。
- copy `studio/` package。
- 创建 `/app/storage/uploads`。
- command：`uv run uvicorn studio.main:app --host 0.0.0.0 --port 23457`。

## Web Dockerfile

`services/studio/web/Dockerfile` 当前行为：

- build stage：`node:20-alpine`。
- 支持 npm registry mirror build arg。
- 执行 `npm ci` 和 `npm run build`。
- runtime stage：`nginx:alpine`。
- copy dist 到 `/usr/share/nginx/html`。

## Vite dev server 当前配置

`services/studio/web/vite.config.ts` 当前只把 `/api` proxy 到 `localhost:23457`；dev server 不暴露 `/storage`。

## 必要环境变量

`DATABASE_URL` 和 `STUDIO_STORAGE_DIR` 都必须存在。缺失时 `studio/db.py` 会直接抛错。

## Database

Studio 使用 PostgreSQL，由 Alembic 管理 schema 迁移。启动时通过 FastAPI lifespan 调用 `run_migrations()`（`studio/migrate.py`），自动执行 `alembic upgrade head`。Worker 和 CLI 同样在入口调用 `run_migrations()`。

Schema 变更流程：修改 `models.py` → 生成新的 Alembic migration → `alembic upgrade head`。

## Storage paths

- Uploaded archives：`${STUDIO_STORAGE_DIR}/uploads/{account_id}/{archive_id}.json`。

## 进程耦合

`studio-api` 和 `studio-worker` 共享 PostgreSQL 数据库，通过 `studio-db` 服务访问。