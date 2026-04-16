# wangzonghao

## Docker Compose 启动

项目包含两个运行中的进程：

- `web`：FastAPI 服务，负责 API、SQLite 和静态前端页面
- `worker`：轮询任务并调用 LLM 生成回复

前端页面由 `web` 服务直接托管，不需要单独启动第三个前端容器。

### 1. 准备环境变量

```bash
cp .env.example .env
```

至少需要把 `.env` 里的 `LLM_API_KEY` 改成可用值；如果只想联调流程，也可以把 `ECHO_MODE=true` 打开，让 worker 进入复读模式。

### 2. 启动

```bash
docker compose up --build
```

默认访问地址：

```text
http://localhost:23456
```

如果想改宿主机端口，可以在 `.env` 里调整 `WEB_PORT`。

### 3. 持久化数据

`docker compose` 会创建名为 `app-storage` 的 volume，用来保存：

- `storage/chat.db`
- `storage/attachments/`

容器重建后，这些数据会继续保留。
