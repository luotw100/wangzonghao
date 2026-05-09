# Bridge Infrastructure / Bridge 基础设施

## Compose

`services/bridge/compose.yaml` 当前只有一个 service：

```text
bridge
  build: .
  environment:
    LOG_LEVEL: ${LOG_LEVEL:-INFO}
  restart: "no"
```

当前使用方式是 `docker compose run --rm bridge ...args`，凭据通过 CLI 传入。

## Dockerfile

`services/bridge/Dockerfile` 当前行为：

- base image：`python:3.12-slim`。
- 安装 `uv`。
- copy `pyproject.toml` 和 `uv.lock`。
- 执行 `uv sync --frozen --no-dev --no-install-project`。
- copy `bridge/` package。
- entrypoint：`uv run python -m bridge.main`。

## 配置面

CLI args：

- Studio username/password。
- Studio URL。
- Hostname override。
- 一个或多个 Chat inbox specs。

Environment：

- `LOG_LEVEL`，Compose 默认 `INFO`。

当前没有持久文件、volume、DB 或 token file。

## 本地网络

Bridge 容器访问本机 Compose 服务时当前命令使用：

- Studio：`http://host.docker.internal:23457`
- Chat：`http://host.docker.internal:23456`

## 当前失败行为

- 某个 adapter 登录失败：记录 error，关闭该 adapter，继续处理其他 claim。
- Studio handshake 失败：关闭已登录 adapters，runtime 返回。
- inbound push 失败：记录 error；当前没有落盘 offline queue。
- heartbeat 失败：记录 warning，下个 interval 重试。
- outbound long-poll 失败：记录 warning，sleep 2s。
- outbound 发送失败：ack outbound 为 failed。

## 当前运行限制

- 没有本地离线缓存。
- heartbeat response 能停 adapter，但不能启动 CLI 中不存在的新 adapter。
- Bridge token 只在内存中；重启后重新 handshake。
