# Chat Sandbox Overview / Chat 总览

## 当前角色

`services/chat` 是仓库内当前可运行的 dogfood Channel。它模拟一个聊天平台，用来测试 Bridge ↔ Studio 链路。

它不是 Studio，也不承担 AI 决策。它只管理 sandbox 账号、联系人、会话、消息和导入 UI。

## 目录结构

```text
services/chat/
  compose.yaml
  nginx.conf
  api/
    Dockerfile
    pyproject.toml
    chat/
      auth_utils.py
      cli.py
      db.py
      main.py
      models.py
      schemas.py
  web/
    Dockerfile
    package.json
    vite.config.ts
    src/
      api.ts
      App.tsx
      hooks/
      components/
      utils/
```

## 技术栈

后端：

- Python 3.12+
- FastAPI
- SQLAlchemy
- PostgreSQL（Alembic 管理 schema 迁移）
- Uvicorn

前端：

- React 19
- TypeScript
- Vite
- CSS

基础设施：

- Docker Compose
- Nginx serve SPA + reverse proxy `/api/`
- Docker volume `chat-storage`

## 在整体链路中的位置

```text
Chat web/API
  ↕ HTTP
Bridge ChatAdapter
  ↕ Studio Bridge protocol
Studio API/worker
```

Bridge 使用 Chat API 登录、拉取 conversations/messages、发送 messages。Studio 不直接调用 Chat。

## 存储和配置

`CHAT_STORAGE_DIR` 必须存在。Chat 使用 PostgreSQL 数据库，通过 `DATABASE_URL` 环境变量配置连接。Schema 由 Alembic 管理，启动时自动执行迁移。

## 账号管理

当前账号由 CLI 创建：

```bash
python -m chat.cli create-account --username alice --password Alice123 --display-name 主播alice
```

当前 CLI 的账号 id 生成规则是 `acct_{username}`。
