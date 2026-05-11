# Chat Infrastructure / Chat 基础设施

## Compose

`services/chat/compose.yaml` 当前定义两个 service，无 volume。

### `chat-web`

- build context：`./web`。
- dockerfile：`Dockerfile`。
- host port：`23456:23456`。
- mount `./nginx.conf:/etc/nginx/conf.d/default.conf:ro`。
- depends on `chat-api`。
- restart：`unless-stopped`。

### `chat-api`

- build context：`./api`。
- env：`DATABASE_URL`、`S3_ENDPOINT`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`。
- `extra_hosts: host.docker.internal:host-gateway`（连接 infra 的 PG 和 MinIO）。
- restart：`unless-stopped`。

## 外部依赖

Chat 不再管理自己的 PG 或 MinIO 容器。数据库和对象存储由 `infra/compose.yaml` 统一管理，通过 host 端口暴露：

- PostgreSQL：`host.docker.internal:5433`
- MinIO S3 API：`host.docker.internal:9000`
- MinIO Console：`host.docker.internal:9001`

生产环境替换为云服务时，只需修改 `.env` 中的 `DATABASE_URL` 和 `S3_ENDPOINT`。

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

`DATABASE_URL`、`S3_ENDPOINT`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET` 都必须存在。缺失时 `chat/db.py` 或 `chat/s3.py` 会直接抛错。

## Database

Chat 使用 PostgreSQL，由 Alembic 管理 schema 迁移。启动时通过 FastAPI lifespan 调用 `run_migrations()`（`chat/migrate.py`），自动执行 `alembic upgrade head`。CLI 在入口也调用 `run_migrations()`。

Schema 变更流程：修改 `models.py` → 生成新的 Alembic migration → `alembic upgrade head`。

## 运行注意点

- Chat 账号和 Studio 账号是两套 DB。
- Bridge 需要 Chat sandbox 账号密码。
- Docker 中的 Bridge 访问本机 Chat 时使用 `http://host.docker.internal:23456`。