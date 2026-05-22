# Studio Overview / Studio 总览

## 当前角色

`services/studio` 是当前仓库中的云端控制台和 AI brain。它存储 source-of-truth 消息历史，管理 Persona / ProviderConfig，接受 Bridge protocol，运行 reply 和 distill worker，并提供 Studio web console。

Studio 所有平台 IO 都通过 Bridge 进入/离开，不直连 Chat 或其他平台。

## 目录结构

```text
services/studio/
  compose.yaml
  nginx.conf
  api/
    Dockerfile
    pyproject.toml
    studio/
      auth_utils.py
      cli.py
      cli_render.py
      clients.py
      db.py
      deps.py                 ← FastAPI 依赖、auth helpers、ownership checks、new_id()
      enums.py
      main.py                 ← 薄入口，仅 mount routers
      models.py
      provider_policy.py
      reply.py
      runtime.py
      schemas.py
      serializers.py           ← 响应序列化函数 s_account / s_persona / ...
      worker.py
      distill/
        packer.py
        pipeline.py
        prompts/fold.md
      routers/
        __init__.py
        auth.py               ← health + 登录/登出/me/改自己密码
        personas.py            ← Persona CRUD
        bridges.py             ← Bridge list + revoke
        inboxes.py             ← Inbox 操作（Inbox 创建仅通过 bridge handshake）
        conversations.py        ← Conversation endpoints
        distill.py             ← Distill job endpoints
        bridge_protocol.py     ← Bridge daemon ↔ Studio protocol
  web/
    Dockerfile
    package.json
    vite.config.ts
    src/
      App.tsx
      main.tsx
      index.css
      components/
      lib/
      pages/
```

## 技术栈

后端：

- Python 3.12+
- FastAPI
- SQLAlchemy
- PostgreSQL
- httpx
- python-multipart
- Uvicorn

前端：

- React 19
- TypeScript
- Vite
- React Router 7
- Tailwind CSS 4
- ESLint

基础设施：

- Docker Compose：`studio-web`、`studio-api`、`studio-worker`。
- Nginx serve SPA + reverse proxy。
- Docker volume `studio-storage`。

## 后端进程划分

### `studio-api`

运行 `studio.main:app`。

当前职责：

- Web auth。
- CRUD endpoints。
- Distill job creation。
- Bridge handshake / heartbeat / incoming / outbound / ack。

### `studio-worker`

运行 `python -m studio.worker --request-timeout 120`。

当前职责：

- DistillScanner 扫 pending DistillJob。
- ReplyScanner 扫 takeover=true 且最近消息为对方的 Conversation。
- 通过 ProviderClient 执行 LLM 调用。

两个进程共享同一个 PostgreSQL 数据库。

## Studio Web 当前 tabs

tab 导航：接管（默认） · 人设 · 设备

- **接管**：Conversation 级接管配置和消息预览。
- **人设**：create/edit/delete Persona。
- **设备**：Bridge 状态、快速启动命令和 revoke。
- 改自己密码走左下角头像菜单的弹窗，没有独立设置 tab，也没有任何账号 / Provider 管理界面。

Bridge 和 Inbox 主要由 daemon handshake 自动创建；UI 当前不要求手动创建 Bridge。
