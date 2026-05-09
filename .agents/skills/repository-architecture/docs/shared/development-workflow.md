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
```

Studio web/API 通过 Nginx 暴露在 `http://localhost:23457`。

Studio 登录页只做登录；首个 admin 必须用 CLI 创建：

```bash
docker compose exec -T studio-api uv run python -m studio.cli create-account \
  --username admin --password Admin123 --display-name 平台管理员 --role admin
```

当前推荐顺序：

1. 用上面 CLI 创建首个 admin。
2. 用 admin 登录 Studio。Admin 默认进入 **总览** tab（系统级仪表盘：账号/设备/接管号/消息汇总）。
3. 在 Settings 中创建普通用户账号和全局默认 ProviderConfig（普通用户看不到 Provider tab）。
4. 用对应普通用户登录后创建至少一个 Persona。
5. 启动 Bridge（在 Studio 的 设备 tab 顶部有「快速生成命令」面板可一键复制）。
6. 等 Bridge handshake 自动创建 Bridge/Inbox。
7. 在 Takeover tab 中给 Contact 配置 Persona、autoreply 和 card；Provider override 只对 admin 可见，普通用户使用全局默认 Provider。
8. 如需蒸馏，上传 archive 后创建 distill job。

> 一键 dev seed：仓库根的 `scripts/seed-dev.sh` 会自动创建 chat 用户、Studio admin + 普通用户、provider、persona，并在 Chat 里灌几条样例消息（清空 volume 后可重复执行）。

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

## Account management

Chat：

```bash
cd services/chat
docker compose exec -T chat-api uv run python -m chat.cli list-accounts
docker compose exec -T chat-api uv run python -m chat.cli reset-password --username alice --password NewPassword
```

Studio：CLI 是首个 admin 的唯一创建入口；登录页不再有 first-run bootstrap。后续账号管理走 Web Settings——admin 可创建/list/停用启用账号、重置任意账号密码；普通 user 可修改自己的密码。CLI 同时保留作为运维/救援入口：

```bash
cd services/studio
docker compose exec -T studio-api uv run python -m studio.cli create-account \
  --username admin --password Admin123 --display-name 平台管理员 --role admin
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
2. 在 Docker DB 中创建或重置账号（Studio 优先通过 Web Settings，Chat 用 CLI）。
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
