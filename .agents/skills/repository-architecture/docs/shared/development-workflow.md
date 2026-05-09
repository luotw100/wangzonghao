# Development Workflow / 开发与验证流程

## 仓库布局

```text
services/
  chat/      # Chat sandbox Channel
  bridge/    # 本地 daemon
  studio/    # 控制台和 AI brain
```

三个服务当前是独立项目。不要跨服务直接 import 源码。

## 启动 Chat sandbox

```bash
cd services/chat
docker compose up -d --build
docker compose exec -T chat-api uv run python -m chat.cli create-account \
  --username alice --password Alice123 --display-name 主播alice
```

Chat web/API 通过 Nginx 暴露在 `http://localhost:23456`。

## 启动 Studio

```bash
cd services/studio
docker compose up -d --build
docker compose exec -T studio-api uv run python -m studio.cli create-account \
  --username demo --password demo123 --display-name 演示
```

Studio web/API 通过 Nginx 暴露在 `http://localhost:23457`。

当前推荐顺序：

1. 创建 ProviderConfig。
2. 创建至少一个 Persona。
3. 启动 Bridge。
4. 等 Bridge handshake 自动创建 Bridge/Inbox。
5. 在 Takeover tab 中给 Contact 配置 Persona、Provider、autoreply 和 card。
6. 如需蒸馏，上传 archive 后创建 distill job。

## 启动 Bridge 连接本地 Chat 和 Studio

```bash
cd services/bridge
docker compose run --rm bridge \
  --studio-username=demo --studio-password=demo123 \
  --studio-url=http://host.docker.internal:23457 \
  --chat-inbox 'base_url=http://host.docker.internal:23456,username=alice,password=Alice123'
```

同一个 Bridge 要挂多个 Chat 账号时，重复传 `--chat-inbox`。

## Storage 事实

Docker 运行和本地裸跑是两套存储：

| Service | Docker storage | 本地 env |
| --- | --- | --- |
| Chat | volume `chat-storage` | `CHAT_STORAGE_DIR` |
| Studio | volume `studio-storage` | `STUDIO_STORAGE_DIR` |
| Bridge | 无持久存储 | CLI args |

在本地 DB 创建的账号不会出现在 Docker volume DB 中。

## Account CLI

Chat：

```bash
cd services/chat
docker compose exec -T chat-api uv run python -m chat.cli list-accounts
docker compose exec -T chat-api uv run python -m chat.cli reset-password --username alice --password NewPassword
```

Studio：

```bash
cd services/studio
docker compose exec -T studio-api uv run python -m studio.cli list-accounts
docker compose exec -T studio-api uv run python -m studio.cli reset-password --username demo --password NewPassword
```

## 构建命令

- Chat web：在 `services/chat/web` 下执行 `npm run build`。
- Studio web：在 `services/studio/web` 下执行 `npm run build`；需要 lint 时执行 `npm run lint`。
- Python 服务在 Dockerfile / Compose 中使用 `uv`。

## 当前验证策略

后端 / schema / protocol 改动：

1. 重建相关 Compose stack。
2. 在 Docker DB 中创建或重置账号。
3. 同时运行 Chat、Studio、Bridge。
4. 验证 Bridge handshake 创建 Bridge/Inbox。
5. 在 Chat 中以 contact 视角发送消息。
6. 确认 Studio 收到 live message。
7. 开启 autoreply，确认 worker 写入 outbound。
8. 确认 Bridge 发送并 ack outbound。

前端改动：

1. 在对应 web 项目下执行 `npm run build`。
2. Studio web 需要时执行 `npm run lint`。
3. 用浏览器验证对应 tab / flow。

distill 改动：

1. 上传一个小型已知 WeFlow JSON。
2. 创建可用 ProviderConfig。
3. 创建 DistillJob。
4. 查看 job progress 和最终 Persona/Card。
5. 需要排查 prompt/parse 时查看 `llm_logs`。

## 跨服务改动检查表

- 改 Bridge protocol：同步更新 Studio schema/endpoint、Bridge client/runtime、文档。
- 改 Contact 语义：检查 Studio data model、Takeover UI、reply gates、distill card。
- 增加平台适配：当前边界是在 Bridge 新增 adapter，Studio 不直连平台。
- 增加配置项：优先显式 env/CLI，缺失时报错。
- 改 outbound status：同步检查 Studio model、Bridge ack、前端展示和文档。
