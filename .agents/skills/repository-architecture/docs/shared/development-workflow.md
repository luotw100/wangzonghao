# Development Workflow / 开发与验证流程

## 仓库布局

```text
bridge/      # Bridge 命令行 daemon（Python REPL + GUI，prompt_toolkit + stdlib）
services/
  chat/      # Chat sandbox Channel
  studio/    # 控制台和 AI brain
```

三个项目互相独立。`bridge/` 是 Python 包（依赖 prompt_toolkit，其余 stdlib），`services/` 是 Python/Docker 工作区，不要跨项目直接 import 源码。

## 启动 Chat sandbox

```bash
cd infra && docker compose up -d    # 先启动基础设施
cd services/chat
docker compose up -d --build
docker compose exec -T chat-api uv run python -m chat.cli create-account \
  --username alice --password Alice123 --display-name 主播alice
```

Chat web/API 通过 Nginx 暴露在 `http://localhost:23456`。

## 启动 Studio

```bash
cd infra && docker compose up -d    # 先启动基础设施
cd services
docker compose up -d --build
```

Studio web/API 通过 Nginx 暴露在 `http://localhost:23457`。

Studio 登录页只做登录；账号和 Provider 都用服务端 CLI 创建：

```bash
docker compose exec -T studio-api uv run python -m studio.cli create-account \
  --username u1 --password Pw123 --display-name 主播一
docker compose exec -T studio-api uv run python -m studio.cli create-provider \
  --name dev --base-url https://api.deepseek.com --api-key sk-xxx --default-model deepseek-v4-flash
```

当前推荐顺序：

1. 用上面 CLI 创建账号和全局默认 Provider。
2. 用该账号登录 Studio，创建至少一个 Persona。
3. 启动 Bridge（在 Studio 的 设备 tab 顶部有「快速生成命令」面板可一键复制）。
4. 等 Bridge handshake 创建 Bridge、`POST /api/bridge/inboxes` 注册 Inbox。
5. 在 Takeover tab 中给 Conversation 配置 Persona、autoreply 和 card_md，可创建 distill job 蒸馏 Persona 和 Card_md。Conv 每个 Conversation 有独立的 provider_id，Account 有 distill_provider_id。

> 一键 dev seed：`python3 scripts/seed_dev.py`，全部配置走 `scripts/.env`（参考 `scripts/.env.example`，所有键必填、无代码默认值）。它创建 `CHAT_SEED_USERS` / `STUDIO_SEED_USERS` 两份独立清单里的用户（格式严格为 `username:password:display`），并经 `studio.cli create-provider` 创建一个全局 Provider。仅建账号 + provider，不播种 persona/contact/消息（清空 volume 后可重复执行；账号已存在会告警跳过，未清空 volume 重跑会多建一行 Provider，最新者为默认）。

## 启动 Bridge（命令行 daemon）

```bash
cd bridge
uv run laborster-bridge --state /path/to/state
```

REPL 内：
1. `/login` → 输入 Studio 账号密码（换 token 落盘）
2. `/channel add` → 输入 Chat sandbox 账号密码（换 chat token 落盘）
3. daemon 自动连接（无 `/start`）→ `/status` 看在线状态；下次带 `--state` 启动即自动续连

Chat/Studio 地址硬编码在 `config.py`（`chat.laborster.com` / `studio.laborster.com`），无 base-URL 输入；状态目录无默认值，必须 `--state` 或 REPL `/state <path>` 指定。多个 Chat channel 重复 `/channel add` 即可。

## Storage 事实

基础设施（PostgreSQL + MinIO）由项目根 `docker-compose.yaml` 统一管理，通过 host 端口暴露。Studio 通过容器网络连接。

| Service | 连接方式 |
| --- | --- |
| Chat PG | `host.docker.internal:5433` |
| Studio PG | `host.docker.internal:5432` |
| MinIO S3 | `host.docker.internal:9000` |

环境变量：

| Service | 必要 env |
| --- | --- |
| Chat | `DATABASE_URL`、`S3_ENDPOINT`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET` |
| Studio | `DATABASE_URL`、`S3_ENDPOINT`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET` |
| Bridge | 无持久存储（CLI args） |

文件存储使用 S3 兼容对象存储（开发环境用 MinIO），每个服务通过 `S3_BUCKET` 区分命名空间。生产环境替换为云服务时只需修改 `.env` 中的 `DATABASE_URL` 和 `S3_ENDPOINT`。

## Account management

Chat：

```bash
cd services/chat
docker compose exec -T chat-api uv run python -m chat.cli list-accounts
docker compose exec -T chat-api uv run python -m chat.cli reset-password --username alice --password NewPassword
```

Studio：账号开通和 Provider 维护只有 CLI 一条路径，没有任何 Web 管理入口；登录页仅提供 username/password 登录，Web 端只能改自己的密码。

```bash
cd services
docker compose exec -T studio-api uv run python -m studio.cli create-account \
  --username u1 --password Pw123 --display-name 主播一
docker compose exec -T studio-api uv run python -m studio.cli list-accounts
docker compose exec -T studio-api uv run python -m studio.cli reset-password --username u1 --password NewPassword
docker compose exec -T studio-api uv run python -m studio.cli create-provider \
  --name dev --base-url https://api.deepseek.com --api-key sk-xxx --default-model deepseek-v4-flash
docker compose exec -T studio-api uv run python -m studio.cli list-providers
```

## 构建命令

- Bridge CLI：无构建步骤；`cd bridge && python3 -m compileall -q laborster_bridge` 做语法自检，`uv run laborster-bridge` 运行（uv 解析 prompt_toolkit）。单文件可执行打包属发布层。
- Chat web：在 `services/chat/web` 下执行 `npm run build`。
- Studio web：在 `services/user_web` 下执行 `npm run build`；需要 lint 时执行 `npm run lint`。
- Python 服务在 Dockerfile / Compose 中使用 `uv`。

## 当前验证策略

后端 / schema / protocol 改动：

1. 重建相关 Compose stack。
2. 在 Docker DB 中创建或重置账号（Studio 优先通过 Web Settings，Chat 用 CLI）。
3. 同时运行 Chat、Studio、Bridge。
4. 验证 Bridge handshake 创建 Bridge、`/api/bridge/inboxes` 注册 Inbox。
5. 在 Chat 中以 contact 视角发送消息。
6. 确认 Studio 收到 live message。
7. 开启 autoreply，确认 worker 写入 outbound。
8. 确认 Bridge 发送 outbound，Bridge 上报 from_self inbound 后 Studio 自动标记 delivered。

前端改动：

1. 在对应 web 项目下执行 `npm run build`。
2. Studio web 需要时执行 `npm run lint`。
3. 用浏览器验证对应 tab / flow。

distill 改动：

1. 确保有活跃的 ProviderConfig。
2. 创建 DistillJob。
3. 查看 job progress 和最终 Persona/Card。
4. 需要排查 prompt/parse 时查看 `llm_logs`。

## 跨服务改动检查表

- 改 Bridge protocol：同步更新 Studio schema/endpoint、`bridge/laborster_bridge/studio_client.py`、文档。
- 改 Conversation 语义：检查 Studio data model、Takeover UI、reply gates、distill card_md。
- 增加平台适配：当前边界是在 `bridge/laborster_bridge/` 新增 adapter 模块并在 `runtime.py` 中接入，Studio 不直连平台。
- 增加配置项（Bridge）：扩展本地 SQLite kv 表字段或 slash 命令，不引入 env var、不加默认状态目录。
- 改 outbound status：同步检查 Studio model、`runtime.py` `_dispatch_outbound`、frontend 展示和文档。
