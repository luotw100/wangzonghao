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

Bridge 是无状态 daemon：无持久文件、无 volume、无 DB、无 token file。

## 本地网络

Bridge 容器访问本机 Compose 服务时当前命令使用：

- Studio：`http://host.docker.internal:23457`
- Chat：`http://host.docker.internal:23456`

## 当前失败行为

- 某个 adapter 登录失败：记录 error，关闭该 adapter，继续处理其他 claim。
- Studio handshake 失败：关闭已登录 adapters，runtime 返回。
- inbound push 失败：记录 error；失败消息不落盘到 offline queue。
- heartbeat 失败：记录 warning，下个 interval 重试。
- outbound long-poll 失败：记录 warning，sleep 2s。
- outbound 发送失败：ack outbound 为 failed。

## 当前运行限制

- Bridge 通过 `--state-dir` 目录下的 `state.json` 持久化 `machine_id` 和 session token。
- `machine_id` 由 Studio 生成，跨重启不变；token 重启时优先复用（成功则跳过 handshake）。
- heartbeat response 能停 adapter，但不能启动 CLI 中不存在的新 adapter。
