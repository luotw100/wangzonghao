# Development Workflow / 开发与验证流程

## 仓库布局

```text
bridge/      # Bridge daemon（Python REPL + GUI，prompt_toolkit + stdlib）
services/
  api/       # FastAPI 包：studio + chat 子包 + admin app（同一镜像，三 entrypoint）
  user_web/  # 用户侧 React SPA（/studio + /chat 都是它的路由）
  admin_web/ # admin React 面板（CF Access 保护）
```

两个项目互相独立。`bridge/` 是 Python 包（依赖 prompt_toolkit，其余 stdlib），`services/` 是 Python/Docker 工作区，不要跨项目直接 import 源码。

## 启动整套云端

唯一的 `docker-compose.yaml` 在仓库根目录，由 `scripts/up-all.sh <config.json>` 拉起一个 instance（`db`、`minio`、`migrate`、`user-api`、`user-worker`、`admin-api`、`user-web`、`admin-web`、`cloudflared`）。`.env` 提供 db/MinIO 凭据与 bucket 名；`<config.json>` 提供 instance-specific 值（`COMPOSE_PROJECT_NAME`、`CF_TUNNEL_TOKEN`、`S3_PUBLIC_URL`）。

```bash
scripts/up-all.sh scripts/.env.debug.json   # 拉起一个 instance
scripts/down-all.sh scripts/.env.debug.json # 停（保留 volume；加 -v 删 volume）
```

启动后：

- user-web / user-api 在容器内 `23456`，对外通过 cloudflared 暴露。
- admin-web / admin-api 在容器内 `23457`，由 Cloudflare Access 在边缘鉴权。
- chat 子包路由挂在 `/api/chat/*`，与 studio 共享 user-api 进程。

## 创建账号 / Provider

没有任何服务端 CLI。账号和 Provider 都通过 admin-api 维护：

```bash
# 调 admin-api（CF Access 鉴权）创建账号
curl -X POST https://admin.<your-domain>/api/admin/accounts \
  -H 'content-type: application/json' \
  -d '{"username":"u1","password":"Pw123","display_name":"主播一"}'

# 创建 Provider（最早创建的作为默认）
curl -X POST https://admin.<your-domain>/api/admin/providers \
  -H 'content-type: application/json' \
  -d '{"name":"dev","base_url":"https://api.deepseek.com","api_key":"sk-xxx","model":"deepseek-v4-flash"}'
```

也可以走 admin_web UI（`/api/admin/accounts`、`/api/admin/providers`）。

## Dev seed

`scripts/seed_dev.py <config.json>` 一次性建一批账号 + Provider。`config.json` 的 `seed` 块定义 `studio_url`、`users[]`、`providers[]`（参考 `scripts/.env.example.json`）。账号 + provider 通过 admin-api 写入。重复执行幂等：账号存在会告警跳过；Provider 同名也会跳过。

```bash
scripts/up-all.sh scripts/.env.debug.json   # 起来
python3 scripts/seed_dev.py scripts/.env.debug.json
```

## 推荐配置顺序

1. `up-all.sh` 起服务，`seed_dev.py` 创建账号 + 默认 Provider。
2. 用该账号登录 user-web，创建至少一个 Persona。
3. 启动 Bridge（user-web 的"设备" tab 有「快速生成命令」面板可一键复制）。
4. Bridge handshake 自动创建 Bridge 行、`POST /api/bridge/inboxes` 注册 Inbox。
5. 在 Takeover tab 给 Conversation 配置 Persona、reply_policy、card_md；可创建 distill job 自动产出 Persona / Card_md。每个 Conversation 独立 `provider_id`，每个 Account 独立 `distill_provider_id`。

## 启动 Bridge（命令行 daemon）

```bash
cd bridge
uv run laborster-bridge --state /path/to/state
```

REPL 内：
1. `/login` → 输入 Studio 账号密码（换 account session token 落盘到 `<state>/<account_id>/state.db` 的 `kv` 表）
2. `/channel add` → 添加平台账号（chat channel 直接复用同一个 studio token，无需再次输入密码）
3. daemon 自动连接（无 `/start`）→ `/status` 看在线状态；下次带 `--state` 启动即自动续连

Studio 地址硬编码在 `laborster_bridge/config.py`（`STUDIO_BASE_URL = https://studio.laborster.com`），无环境变量、无 base-URL 输入；chat 沙箱同主机，路径加 `/api/chat` 前缀。状态目录无默认值，必须 `--state` 或 REPL `/state <path>` 指定。

## Storage 事实

基础设施（PostgreSQL + MinIO）由仓库根 `docker-compose.yaml` 统一管理。单 PG 实例（三 schema：`auth` / `studio` / `chat`）+ 单 MinIO bucket。所有 API 进程通过 compose 容器网络连接，host 端口仅由开发者自行暴露时使用。

必要环境变量（缺失时直接报错）：

| 进程 | env |
| --- | --- |
| user-api / user-worker / admin-api / migrate | `DATABASE_URL`、`S3_ENDPOINT`、`S3_PUBLIC_URL`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`、`UPLOAD_MAX_SIZE_MB` |
| Bridge | 无；地址硬编码在 `bridge/laborster_bridge/config.py` |

## 构建命令

- Bridge：无构建步骤；`cd bridge && python3 -m compileall -q laborster_bridge` 做语法自检，`uv run laborster-bridge` 运行。GUI 打包脚本在 `bridge/scripts/`。
- user_web / admin_web：各自目录下 `npm ci && npm run build`；需要 lint 时 `npm run lint`。
- API：Dockerfile 内用 `uv sync --frozen` 构建。

## 当前验证策略

后端 / schema / protocol 改动：

1. `scripts/up-all.sh <config.json>` 重建 stack（或 `docker compose build && docker compose up -d`）。
2. 通过 admin-api 创建或重置账号 / Provider（或跑 `seed_dev.py`）。
3. 启动 Bridge daemon。
4. 验证 Bridge handshake 创建 Bridge 行、`/api/bridge/inboxes` 注册 Inbox。
5. 在 chat 沙箱以 contact 视角发送消息。
6. 确认 user-api 收到 live message。
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
