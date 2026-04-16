# Laborster

Laborster 是一个面向私聊场景的 **AI 角色调试工作台**。它把 Robot 人设、粉丝画像、异步任务、计划回复和真实消息发送串在一起，方便你在一个最小可运行系统里反复调试 prompt 与回复节奏。

## 项目背景

这个项目不是一个通用聊天应用，而是一个专门用于测试 **“人设 prompt + 用户画像 + 延迟回复 + Worker 编排”** 的小型全栈工作台。

核心调试目标包括：

- 不同 `system_prompt` 是否能稳定塑造角色
- 不同 `user_profile` 是否会影响回复风格
- LLM 返回的多条延迟消息是否会被正确排程和发送
- 用户新消息是否会中断未发送的 planned replies
- Worker 的轮询、重试和回写链路是否正常

## 核心概念

| 概念 | 作用 |
| --- | --- |
| `Robot` | 角色模板，核心字段是 `name` 和 `system_prompt` |
| `Conversation` | 某个具体聊天对象的上下文，核心字段是 `title` 和 `user_profile` |
| `Message` | 实际聊天消息，区分 `user` / `robot` |
| `Task` | 用户消息触发的异步处理任务 |
| `PlannedReply` | Worker 生成、等待未来发送的计划消息 |

## 架构概览

### 运行结构

```text
Browser
  -> FastAPI Web(app/main.py)
      -> SQLite(storage/chat.db)
      -> Static Frontend(frontend/)
      -> Attachments(storage/attachments/)
  -> Worker(worker/main.py)
      -> 调用 Web /api 接口
      -> 调用 OpenAI-compatible LLM
```

### 组件职责

| 组件 | 路径 | 职责 |
| --- | --- | --- |
| Web | `app/main.py` | FastAPI API、SQLAlchemy 模型、静态前端托管 |
| Frontend | `frontend/` | Vue 3 + Tailwind CDN 的静态调试界面 |
| Worker | `worker/main.py` | 轮询任务、拼接上下文、调用 LLM、写入/发送 planned replies |
| Storage | `storage/` | SQLite 数据库、附件持久化 |

### 消息处理流程

1. 前端调用 `POST /api/messages` 发送用户消息
2. 后端落库消息，并取消该会话未发送的 planned replies
3. 后端创建一条 `Task`
4. Worker 轮询待处理任务
5. Worker 拉取会话历史、Robot prompt、Conversation user profile
6. Worker 调用 OpenAI-compatible LLM
7. LLM 返回 JSON 后生成若干 `PlannedReply`
8. Worker 到点把 planned replies 转成真实 robot 消息
9. 前端通过轮询看到计划回复与正式消息

## 当前技术选型

- **Backend**: FastAPI + SQLAlchemy
- **Frontend**: Vue 3 global build + Tailwind CDN + 原生 JS
- **Database**: SQLite
- **Worker**: Python 异步轮询进程
- **Deployment**: Docker Compose

## 目录结构

```text
.
├── app/                 # FastAPI 服务、ORM、API 路由
├── frontend/            # 静态前端资源
│   ├── css/
│   └── js/
├── worker/              # 异步 worker 与配置
├── storage/             # SQLite 与附件目录（运行时数据）
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── .github/
    └── copilot-instructions.md
```

## Docker Compose 启动

项目包含两个运行中的进程：

- `web`：FastAPI 服务，负责 API、SQLite 和静态前端页面
- `worker`：轮询任务并调用 LLM 生成回复

前端页面由 `web` 服务直接托管，不需要单独启动第三个前端容器。

### 1. 准备环境变量

```bash
cp .env.example .env
```

至少需要把 `.env` 里的 `LLM_API_KEY` 改成可用值；如果只想联调流程，也可以把 `ECHO_MODE=true` 打开，让 worker 进入复读模式。

### 2. 启动

```bash
docker compose up --build
```

默认访问地址：

```text
http://localhost:23456
```

如果想改宿主机端口，可以在 `.env` 里调整 `WEB_PORT`。

### 3. 持久化数据

`docker compose` 会创建名为 `app-storage` 的 volume，用来保存：

- `storage/chat.db`
- `storage/attachments/`

容器重建后，这些数据会继续保留。

## 本地直接运行

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 23456
uv run python worker/main.py
```

## 常用环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `WEB_PORT` | Web 暴露到宿主机的端口 | `23456` |
| `LLM_BASE_URL` | OpenAI-compatible 接口地址 | `https://api.deepseek.com` |
| `LLM_API_KEY` | LLM API Key | 空 |
| `LLM_MODEL` | 模型名 | `deepseek-chat` |
| `REQUEST_TIMEOUT` | LLM 请求超时（秒） | `120` |
| `POLL_INTERVAL` | Worker 轮询间隔（秒） | `2` |
| `MAX_RETRIES` | 任务最大重试次数 | `3` |
| `ECHO_MODE` | 是否启用复读模式 | `false` |

## 开发约束

- 前端不是独立 Node 工程，**不要默认引入构建链**
- `app/main.py` 同时承担 API、模型和静态页面托管
- `worker/` 必须通过 `/api` 与 web 通信
- 变更持久化字段时，要同步考虑：
  - ORM 模型
  - Pydantic schema
  - API handler
  - 前端读写逻辑
  - Worker 上下文拼接
- `planned_replies.send_at` 当前以 **UTC naive datetime** 存储，避免随意改时区策略
