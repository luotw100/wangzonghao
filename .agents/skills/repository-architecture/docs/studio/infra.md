# Studio Infrastructure / Studio 基础设施

## Compose

`services/studio/compose.yaml` 当前定义三个 service，无 volume。

### `studio-web`

- build context：`./web`。
- host port：`23457:23457`。
- mount `./nginx.conf:/etc/nginx/conf.d/default.conf:ro`。
- depends on `studio-api`。
- restart：`unless-stopped`。

### `studio-api`

- build context：`./api`。
- env：`DATABASE_URL`、`S3_ENDPOINT`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`。
- `extra_hosts: host.docker.internal:host-gateway`（连接 infra 的 PG 和 MinIO）。
- restart：`unless-stopped`。

### `studio-worker`

- build context：`./api`。
- command：`uv run python -m studio.worker --request-timeout 120`。
- env：同 `studio-api`。
- `extra_hosts: host.docker.internal:host-gateway`。
- restart：`unless-stopped`。

## 外部依赖

Studio 的数据库和对象存储由 `infra/compose.yaml` 统一管理，通过 host 端口暴露：

- PostgreSQL：`host.docker.internal:5432`
- MinIO S3 API：`host.docker.internal:9000`
- MinIO Console：`host.docker.internal:9001`

生产环境替换为云服务时，只需修改 `.env` 中的 `DATABASE_URL` 和 `S3_ENDPOINT`。

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
- command：`uv run uvicorn studio.main:app --host 0.0.0.0 --port 23457`。

## Web Dockerfile

`services/studio/web/Dockerfile` 当前行为：

- build stage：`node:20-alpine`。
- 支持 npm registry mirror build arg。
- 执行 `npm ci` 和 `npm run build`。
- runtime stage：`nginx:alpine`。
- copy dist 到 `/usr/share/nginx/html`。

## Vite dev server 当前配置

`services/studio/web/vite.config.ts` 当前只把 `/api` proxy 到 `localhost:23457`。

## 必要环境变量

`DATABASE_URL`、`S3_ENDPOINT`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET` 都必须存在。缺失时 `studio/db.py` 或 `studio/s3.py` 会直接抛错。

## Database

Studio 使用 PostgreSQL，由 Alembic 管理 schema 迁移。启动时通过 FastAPI lifespan 调用 `run_migrations()`（`studio/migrate.py`），自动执行 `alembic upgrade head`。Worker 和 CLI 同样在入口调用 `run_migrations()`。

Schema 变更流程：修改 `models.py` → 生成新的 Alembic migration → `alembic upgrade head`。

## Object Storage (S3)

Studio 使用 S3 兼容对象存储（开发环境用 `infra/` 中的 MinIO）保存媒体文件。

- `studio/s3.py` 提供 `s3_put`、`s3_get`、`s3_presigned_put_url`、`s3_presigned_get_url`。
- 媒体文件存储 key：`media/{bridge_id}/{uuid}.ext`。

## 进程耦合

`studio-api` 和 `studio-worker` 共享 PostgreSQL 数据库和 S3 对象存储，均通过 `host.docker.internal` 访问 `infra/` 中的服务。