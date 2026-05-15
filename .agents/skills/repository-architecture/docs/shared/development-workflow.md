# Development Workflow / 开发与验证流程

## 仓库布局

```text
desktop/     # Bridge 桌面 app（Electron + TypeScript）
services/
  chat/      # Chat sandbox Channel
  studio/    # 控制台和 AI brain
```

三个项目互相独立。`desktop/` 是 npm 工作区，`services/` 是 Python/Docker 工作区，不要跨项目直接 import 源码。

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
8. 在 Takeover tab 中给 Contact 配置 Persona、autoreply 和 card，可创建 distill job 蒸馏 Persona 和 Card。

> 一键 dev seed：`python3 scripts/seed_dev.py`，全部配置走 `scripts/.env`（参考 `scripts/.env.example`，所有键必填、无代码默认值）。它创建一个 Studio admin、`CHAT_SEED_USERS` / `STUDIO_SEED_USERS` 两份独立清单里的用户（格式严格为 `username:password:display`，Studio role=user），以及一个共享 Provider。仅建账号 + provider，不播种 persona/contact/消息（清空 volume 后可重复执行，已存在的账号会告警跳过）。

## 启动 Bridge（桌面 app 开发模式）

```bash
cd desktop
npm install          # 首次：postinstall 自动运行 electron-rebuild
npm run dev          # electron-vite dev：renderer HMR + main 进程热重启
```

Dev 模式启动后显示 Login 屏：
1. Studio URL 填 `http://localhost:23457`，输入 Studio 账号密码点「握手并启动」
2. 进入 InboxConfig，填入 Chat sandbox 账号（Base URL: `http://localhost:23456`）
3. 点「保存并启动 daemon」进入 Panel

多个 Chat inbox 在 InboxConfig 屏点「+ 加 inbox」逐条添加。

## Storage 事实

基础设施（PostgreSQL + MinIO）由 `infra/compose.yaml` 统一管理，通过 host 端口暴露。Chat/Studio/Bridge 通过 `host.docker.internal` 连接。

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

Studio：CLI 是首个 admin 的唯一创建入口；登录页仅提供 username/password 登录。后续账号管理走 Web Settings——admin 可创建/list/停用启用账号、重置任意账号密码；普通 user 可修改自己的密码。CLI 同时保留作为运维/救援入口：

```bash
cd services/studio
docker compose exec -T studio-api uv run python -m studio.cli create-account \
  --username admin --password Admin123 --display-name 平台管理员 --role admin
docker compose exec -T studio-api uv run python -m studio.cli list-accounts
docker compose exec -T studio-api uv run python -m studio.cli reset-password --username demo --password NewPassword
```

## 构建命令

- Bridge desktop：在 `desktop/` 下执行 `npm run build`（tsc 类型检查 + electron-vite build）；`npm run dist:mac` / `npm run dist:win` 生成安装包。
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

1. 确保有活跃的 ProviderConfig。
2. 创建 DistillJob。
3. 查看 job progress 和最终 Persona/Card。
4. 需要排查 prompt/parse 时查看 `llm_logs`。

## 跨服务改动检查表

- 改 Bridge protocol：同步更新 Studio schema/endpoint、`desktop/src/main/daemon/studio-client.ts`、文档。
- 改 Contact 语义：检查 Studio data model、Takeover UI、reply gates、distill card。
- 增加平台适配：当前边界是在 `desktop/src/main/daemon/adapters/` 新增 adapter 并在 `runtime.ts` 中注册，Studio 不直连平台。
- 增加配置项（desktop）：在 `CredentialStore` 或 Settings 屏扩展，不引入 env var（桌面 app 无 env）。
- 改 outbound status：同步检查 Studio model、`runtime.ts` dispatchOutbound、frontend 展示和文档。
