# Chat Infrastructure / Chat 基础设施

## Compose

`services/chat/compose.yaml` 当前定义两个 service 和一个 volume。

### `chat-web`

- build context：`./web`。
- host port：`23456:23456`。
- mount `chat-storage:/app/storage:ro`。
- mount `./nginx.conf:/etc/nginx/conf.d/default.conf:ro`。
- depends on `chat-api`。
- restart：`unless-stopped`。

### `chat-api`

- build context：`./api`。
- env：`CHAT_STORAGE_DIR=/app/storage`。
- mount `chat-storage:/app/storage`。
- restart：`unless-stopped`。

### Volume

- `chat-storage` 保存 `chat.db` 和 storage assets。

## Nginx

`services/chat/nginx.conf` 当前行为：

- listen `23456`。
- 从 `/usr/share/nginx/html` serve SPA。
- `try_files $uri $uri/ /index.html`。
- `/storage/` alias 到 `/app/storage/`。
- `/api/` proxy 到 `http://chat-api:23456/api/`。
- 设置 `Host` 和 `X-Real-IP`。
- `client_max_body_size 50m`。

## API Dockerfile

`services/chat/api/Dockerfile` 当前行为：

- base image：`python:3.12-slim`。
- 安装 `uv`。
- copy `pyproject.toml` 和 `uv.lock`。
- 执行 `uv sync --frozen --no-dev --no-install-project`。
- copy `chat/` package。
- 创建 `/app/storage/attachments`。
- expose `23456`。
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

## 运行注意点

- Chat 账号和 Studio 账号是两套 DB。
- Bridge 需要 Chat sandbox 账号密码。
- Docker 中的 Bridge 访问本机 Chat 时使用 `http://host.docker.internal:23456`。
