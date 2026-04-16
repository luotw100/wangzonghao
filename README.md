# Laborster

Laborster 是一个面向私聊场景的 AI 角色调试工作台。

这条重构分支的核心目标是把系统拆成两个边界更清晰的后端：

- `chat` 只负责聊天事实本身：会话、消息、轮询
- `robot` 负责角色策略与编排：`profile`、联系人画像、Session、Reply Plan、Provider Config、任务流

当前前端还在适配新的后端边界，后端以 `chat` / `robot` 的拆分为准。

## 核心概念

| 概念 | 作用 |
| --- | --- |
| `Robot` | 机器人角色模板，主要字段是 `name` 和 `profile` |
| `Contact` | 独立联系人画像实体，主要字段是 `name` 和 `profile` |
| `Session` | `robot` 服务中的核心会话资源，关联 Robot、Contact 和 Adapter Thread |
| `ProviderConfig` | 内部 LLM Provider 配置资源，和 Robot 身份分离 |
| `Conversation` | `chat` 服务中的纯聊天会话，主要字段是 `title` |
| `Message` | 聊天消息，区分 `user` / `robot` |
| `InboundEvent` | 从 adapter 侧摄入的入站用户事件 |
| `GenerationJob` | 基于入站事件生成回复计划的任务 |
| `ReplyPlan` | `robot` 生成、等待发送的计划回复 |
| `DispatchJob` | 把 Reply Plan 发回 adapter 的发送任务 |

## 架构概览

### 运行结构

```text
Browser
  -> Nginx (:23456)
      -> /api/*        -> Chat (chat/main.py)
      -> /api/robot/*  -> Robot API (robot/main.py)
      -> /             -> frontend/

Chat
  -> SQLite(storage/chat.db)

Robot API
  -> calls Chat API for Session / adapter thread management

Robot Worker
  -> SQLite(storage/robot.db)
  -> 按 Session 轮询 Chat /api/conversations/{id}/messages
  -> 入站事件 -> 生成任务 -> 发送任务
  -> 调用 Provider Config 指向的 OpenAI-compatible LLM
  -> 把回复再发回 Chat /api/conversations/{id}/messages
```

### 组件职责

| 组件 | 路径 | 职责 |
| --- | --- | --- |
| Chat | `chat/main.py` | 会话 CRUD、消息写入与长轮询、聊天数据持久化 |
| Robot API | `robot/main.py` | Robot / Contact / Session / Provider Config API，以及 Session 对 adapter thread 的同步操作 |
| Robot Worker | `robot/worker.py` | 消费 `inbound_events` / `generation_jobs` / `dispatch_jobs`，执行编排、生成、发送 |
| Frontend | `frontend/` | 静态调试界面，由 Nginx 直接托管 |
| Storage | `storage/` | `chat.db`、`robot.db`、附件等运行时数据 |

## 当前消息流

1. 调用方通过 `POST /api/robot/sessions` 创建一个 Session。
2. `robot` 服务调用 `chat` 创建真实聊天会话，并把返回的 `conversation_id` 记为 Session 的 adapter thread reference。
3. 用户消息直接写入 `chat` 的 `POST /api/conversations/{id}/messages`。
4. `robot-worker` 按 Session 轮询 `chat` 的消息接口，把新的用户消息记录为 `inbound_events`。
5. 编排层把待处理入站事件变成 `generation_jobs`，显式记录本次运行选用的 Provider 和 Model。
6. 生成层读取 `Robot.profile` 与 `Contact.profile`，调用 LLM 生成 `reply_plans`。
7. 发送层把 `reply_plans` 转成 `dispatch_jobs`，到点后再发回 `chat`。
8. 调用方继续从 `chat` 读取真实消息，从 `robot-api` 读取 Session 状态、任务状态和 Reply Plan。

## API 边界

Nginx 对外暴露两个后端命名空间：

- `/api/*` -> `chat`
- `/api/robot/*` -> `robot`

当前建议：

- 原始聊天数据操作走 `chat`
- 任何跟角色、联系人画像、Session 编排、Provider 配置有关的操作走 `robot`

### Chat API

- `POST /api/conversations`
- `GET /api/conversations`
- `GET /api/conversations/{id}`
- `PUT /api/conversations/{id}`
- `DELETE /api/conversations/{id}`
- `POST /api/conversations/{id}/restore`
- `POST /api/conversations/{id}/messages`
- `GET /api/conversations/{id}/messages`

### Robot API

- `POST /api/robot/robots`
- `GET /api/robot/robots`
- `PUT /api/robot/robots/{id}`
- `POST /api/robot/contacts`
- `GET /api/robot/contacts`
- `PUT /api/robot/contacts/{id}`
- `POST /api/robot/provider-configs`
- `GET /api/robot/provider-configs`
- `PUT /api/robot/provider-configs/{id}`
- `POST /api/robot/sessions`
- `GET /api/robot/sessions`
- `GET /api/robot/sessions/{id}`
- `PUT /api/robot/sessions/{id}`
- `DELETE /api/robot/sessions/{id}`
- `POST /api/robot/sessions/{id}/restore`
- `GET /api/robot/sessions/{id}/reply-plans`

## 目录结构

```text
.
├── chat/                # 纯聊天后端
├── robot/               # 角色策略与编排后端
├── frontend/            # 静态前端资源
│   ├── css/
│   └── js/
├── storage/             # 运行期数据目录
├── docker-compose.yml
├── Dockerfile
├── nginx.conf
├── pyproject.toml
└── .github/
    └── copilot-instructions.md
```

## Docker Compose 启动

### 1. 启动

```bash
docker compose up --build
```

默认访问地址：

```text
http://localhost:23456
```

Compose 会启动四个服务：

- `nginx`：统一入口，托管前端并分发 API 请求
- `chat`：聊天后端
- `robot-api`：Robot 领域 API
- `robot-worker`：后台队列消费者

### 1.1 初始化 Provider Config

当前实现不再使用环境变量或 `.env` 来配置 Robot 进程。

同时，当前实现也不再使用 `is_default` 自动选 Provider，而是要求系统里只有一个 Provider Config。

如果一个都没有，Robot 不会创建生成任务。

如果有多个，Robot 会直接报错，而不是偷偷选一个。

示例：

```bash
curl -X POST http://localhost:23456/api/robot/provider-configs \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "deepseek",
    "base_url": "https://api.deepseek.com",
    "api_key": "YOUR_API_KEY",
    "default_model": "deepseek-chat"
  }'
```

这里的 `base_url` 语义是“`/chat/completions` 之前的前缀”。

例如：

- DeepSeek: `https://api.deepseek.com`
- OpenAI: `https://api.openai.com/v1`

### 3. 持久化数据

`docker compose` 会创建名为 `app-storage` 的 volume，用来保存：

- `storage/chat.db`
- `storage/robot.db`
- `storage/attachments/`

容器重建后，这些数据会继续保留。

## 本地直接运行

分别启动两个后端：

```bash
uv run uvicorn chat.main:app --host 0.0.0.0 --port 23456
uv run python -m robot.main --host 127.0.0.1 --port 23457 --chat-api-base-url http://127.0.0.1:23456/api
uv run python -m robot.worker --chat-api-base-url http://127.0.0.1:23456/api
```

如果要完整走前端入口，再额外启动 Nginx；否则也可以直接分别请求两个后端端口调试。

如果要用复读模式联调：

```bash
uv run python -m robot.worker --chat-api-base-url http://127.0.0.1:23456/api --echo-mode
```

## Robot API 启动参数

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--host` | Robot API 监听地址 | `127.0.0.1` |
| `--port` | Robot API 监听端口 | `23457` |
| `--chat-api-base-url` | Robot API 访问 Chat Adapter 的 API 地址 | 必填 |

## Robot Worker 启动参数

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `--chat-api-base-url` | Robot Worker 访问 Chat Adapter 的 API 地址 | 必填 |
| `--request-timeout` | LLM 请求超时（秒） | `120` |
| `--poll-interval` | Robot 轮询 Chat 的间隔（秒） | `2` |
| `--echo-mode` | 是否启用复读模式 | 关闭 |

## 当前约束

- `chat` 不负责 Robot / Contact / Session / Provider Config 的业务状态
- `robot-api` 只负责 Robot 领域 API，不消费后台任务
- `robot-worker` 通过 Chat API 感知新消息，不直接读写 `chat.db`
- `robot` 当前采用显式任务表：`inbound_events`、`generation_jobs`、`dispatch_jobs`
- `Provider Config` 目前是内部资源，当前实现要求库里只存在一个 Provider Config，或者显式开启 `--echo-mode`
- 前端尚未完成对 `contacts` / `sessions` / `provider-configs` 新接口的适配
- 前端仍在适配中，后端接口以这里的拆分设计为准