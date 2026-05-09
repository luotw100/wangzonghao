# Studio Overview / Studio 总览

## 当前角色

`services/studio` 是当前仓库中的云端控制台和 AI brain。它存储 source-of-truth 消息历史，管理 Persona / ProviderConfig，接受 Bridge protocol，运行 reply 和 distill worker，并提供 Studio web console。

Studio 当前不直连 Chat 或其他平台。所有平台 IO 都通过 Bridge 进入/离开 Studio。

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
      clients.py
      cli.py
      db.py
      main.py
      models.py
      reply.py
      runtime.py
      schemas.py
      worker.py
      distill/
        converter.py
        ingest.py
        packer.py
        pipeline.py
        prompts/fold.md
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
- SQLite
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
- Archive upload。
- Distill job creation。
- Bridge handshake / heartbeat / incoming / outbound / ack。

### `studio-worker`

运行 `python -m studio.worker --request-timeout 120`。

当前职责：

- DistillScanner 扫 pending DistillJob。
- ReplyScanner 扫 `pending_reply=True` Contact。
- 通过 ProviderClient 执行 LLM 调用。

两个进程共享同一个 SQLite DB volume。

## Studio Web 当前 tabs

1. Takeover — Contact 级接管配置和消息预览。
2. Bridges — Bridge 状态和 revoke。
3. Personas — create/edit/delete Persona。
4. Providers — create/delete ProviderConfig。
5. Archives — 上传 WeFlow JSON 到目标 Inbox。
6. Distill — 创建和查看 distill jobs。

Bridge 和 Inbox 主要由 daemon handshake 自动创建；UI 当前不要求手动创建 Bridge。
