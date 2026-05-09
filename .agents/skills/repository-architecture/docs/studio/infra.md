# Studio Infrastructure / Studio 基础设施

## Compose

`services/studio/compose.yaml` 当前定义三个 service 和一个 volume。

### `studio-web`

- build context：`./web`。
- host port：`23457:23457`。
- mount `studio-storage:/app/storage:ro`。
- mount `./nginx.conf:/etc/nginx/conf.d/default.conf:ro`。
- depends on `studio-api`。
- restart：`unless-stopped`。

### `studio-api`

- build context：`./api`。
- env：`STUDIO_STORAGE_DIR=/app/storage`。
- mount `studio-storage:/app/storage`。
- restart：`unless-stopped`。

### `studio-worker`

- build context：`./api`。
- command：`uv run python -m studio.worker --request-timeout 120`。
- env：`STUDIO_STORAGE_DIR=/app/storage`。
- mount 同一个 `studio-storage`。
- depends on `studio-api`。
- restart：`unless-stopped`。

### Volume

- `studio-storage` 保存 `studio.db`、uploads 和共享 storage 文件。

## Nginx

`services/studio/nginx.conf` 当前行为：

- listen `23457`。
- 从 `/usr/share/nginx/html` serve SPA。
- `try_files $uri $uri/ /index.html`。
- `/storage/` alias 到 `/app/storage/`。
- `/api/` proxy 到 `http://studio-api:23457/api/`。
- `proxy_read_timeout 120s`。
- `client_max_body_size 50m`。

## API Dockerfile

`services/studio/api/Dockerfile` 当前行为：

- base image：`python:3.12-slim`。
- 安装 `uv`。
- copy `pyproject.toml` 和 `uv.lock`。
- 执行 `uv sync --frozen --no-dev --no-install-project`。
- copy `studio/` package。
- 创建 `/app/storage/uploads`。
- expose `23457`。
- command：`uv run uvicorn studio.main:app --host 0.0.0.0 --port 23457`。

## Web Dockerfile

`services/studio/web/Dockerfile` 当前行为：

- build stage：`node:20-alpine`。
- 支持 npm registry mirror build arg。
- 执行 `npm ci` 和 `npm run build`。
- runtime stage：`nginx:alpine`。
- copy dist 到 `/usr/share/nginx/html`。

## Vite dev server 当前配置

`services/studio/web/vite.config.ts` 当前把 `/api` 和 `/storage` proxy 到 `localhost:23456`，而 Studio Compose 默认端口是 `23457`。这是当前文件事实。

## 必要环境变量

`STUDIO_STORAGE_DIR` 必须存在。缺失时 `studio/db.py` 会直接抛错。

## Storage paths

- SQLite DB：`${STUDIO_STORAGE_DIR}/studio.db`。
- Uploaded archives：`${STUDIO_STORAGE_DIR}/uploads/{account_id}/{archive_id}.json`。

## 进程耦合

`studio-api` 和 `studio-worker` 当前共享一个 SQLite DB volume。
