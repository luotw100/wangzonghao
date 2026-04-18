# Laborster 项目背景

## 产品定位

Laborster 的核心产品是 **Robot** —— 一个拟人自动化回复服务，帮助主播在微信里和粉丝保温。

**核心场景**：娱乐主播在直播或发抖音时，粉丝会线下加微信。但主播很忙，来不及及时回复，我们帮助主播和粉丝保温。系统把主播「蒸馏」——模拟主播的记忆、偏好、兴趣、经历，以及主播现实环境的情况（当地地标、交通、餐饮、文化等），以极高的拟人度在微信里和粉丝聊天。

**核心目标**：非常非常像真人。不冷场、不让粉丝的话落地上、培养亲密感。只提供情绪价值，不涉及金钱交易和线下约会。

用户在后台注册 Robot profile（主播人设），添加 Contact profile（粉丝档案），让 AI 基于这两个角色画像生成拟人化的回复。

## 当前阶段

- **Chat Service** 是一个**调试用的简易聊天平台（Adapter）**，不是最终产品。
- 未来 Robot 会接入微信、企微、飞书等多个消息平台，Chat 只是其中一个调试 Adapter。
- 除非 Chat 有重大设计失误，否则尽量不动它。

## 架构原则

- 简单可靠、耐操、易于理解、可扩展、性能好
- 消息队列 + 消费者模型（Redis 作为传输管道）
- Robot Service 拥有完整消息历史（source of truth），不依赖 Adapter 在线
- 流水表全砍，Worker 处理过程纯内存，可靠性靠 DB 兜底
- 延迟发送用 asyncio.sleep 实现，不需要额外表

## 编码偏好

- **禁止偷偷搞默认值**：所有配置（环境变量、CLI 参数、连接串）必须由外部显式指定，缺失时直接报错。不允许用 fallback 默认值静默连接到错误的服务。

## 问题处理原则

- **第一性原理**：遇到问题先从根本原因和架构层面思考，不要缝缝补补打补丁。如果设计本身有缺陷，就改设计，而不是在坏设计上叠 workaround。
- **完成后自验证**：改完代码后必须自己提交 git、启动 docker、针对性地做验证，确认改动生效且无副作用。不要改完就丢给用户。
- **做减法**：积极发现并提出可以删除、合并、简化的部分，保持系统纯净，拒绝臃肿。
- **不要自由发散**：除非特别简单的问题，否则对拿不准的细节、方案、改动范围必须先通过askQuestion和用户确认再动手。
- **大胆重构**：现在项目处在开发阶段，所以可以大刀阔斧的自由重构，不需要为了兼容而写任何代码，只需要在重构的时候告知用户即可。

## 技术栈

- 后端：Python 3.12+, FastAPI, SQLAlchemy, SQLite, Redis
- 前端：React + TypeScript + Tailwind CSS + Vite
- 部署：Docker Compose + Nginx 反向代理

---

## 技术架构详解

### 整体架构

系统共有五个运行单元，全部通过 Docker Compose 编排，由 Nginx 统一对外暴露 23456 端口：

| 容器 | 对外路径 | 内部端口 | 职责 |
| --- | --- | --- | --- |
| `nginx` | `:23456` | — | 静态资源 + 反向代理 |
| `chat` | `/api/*` | `:23456` | Chat Adapter 服务（FastAPI） |
| `robot-api` | `/api/robot/*` | `:23457` | Robot 管理 API（FastAPI） |
| `robot-worker` | — | — | 消息消费 + LLM 调用（asyncio） |
| `redis` | — | `:6379` | 消息管道（robot:inbox 队列） |

Nginx 路由规则（nginx.conf）：
- `/api/robot/` → `robot-api:23457/api/`（去掉 `/robot` 前缀）
- `/api/` → `chat:23456/api/`
- `/storage/` → 本地磁盘附件目录（直接 alias）
- `/` → React 静态资源（`try_files` SPA fallback）

---

### 模块职责

#### `chat/` — Chat Adapter（调试用聊天平台）

- **定位**：最简化的聊天 Adapter，不含任何角色/策略逻辑，仅存储原始消息。
- **核心职责**：
  - 管理 `Conversation`（聊天会话）和 `Message`（消息）的 CRUD
  - 用户发送消息时，把消息推入 Redis `robot:inbox` 队列（`LPUSH`）
  - 提供长轮询接口 `GET /api/conversations/{id}/messages?last_id=M&timeout=N`，前端通过此接口拉取新消息
  - 提供 `/storage` 静态文件服务（附件）
- **数据库**：`storage/chat.db`
- **外部依赖**：Redis（仅用于推送消息，失败不阻断消息存储）

#### `robot/main.py` — Robot API

- **定位**：Robot 领域的管理 API，是前端操作 Robot/Contact/Session 的唯一入口。
- **核心职责**：
  - 管理 `Robot`（机器人角色）、`Contact`（联系人）、`ProviderConfig`（LLM 配置）的 CRUD
  - 管理 `Session`（会话）的生命周期：创建时同步在 Chat 侧创建对应 `Conversation`，删除时同步删除
  - 通过 `ChatAPIClient`（HTTP）与 Chat 服务通信
  - 提供 `GET /api/sessions/{id}/planned-replies` 长轮询接口，供前端实时展示待发送消息
- **数据库**：`storage/robot.db`
- **外部依赖**：Chat API（HTTP）

#### `robot/worker.py` + `robot/runtime.py` — Robot Worker

- **定位**：独立运行的消息消费者进程，是 LLM 推理和回复发送的执行者。
- **核心职责**：
  - 启动时执行 **故障恢复**：扫描所有 active Session，若最后一条消息是 user 消息则重新触发处理
  - 持续 `BRPOP robot:inbox` 消费用户消息
  - 收到消息后：查找对应 Session → 存入 `robot_messages`（role=user）→ 启动 asyncio 处理 Task
  - 若同一 Session 有未完成的旧 Task，先 cancel 并将其 scheduled 消息标记为 canceled（防止过时回复发出）
  - 调用 LLM，解析 JSON 响应（`{"messages": [{"delay_seconds": N, "content": "..."}]}`）
  - 将所有计划回复写入 `robot_messages`（status=scheduled）
  - 按 `scheduled_for` 时间依次 `asyncio.sleep` → 更新 status=sent → 调用 Chat API 发送消息
- **数据库**：`storage/robot.db`（同 Robot API 共享）
- **外部依赖**：Redis（消费）、Chat API（HTTP 发送回复）、LLM Provider（HTTP）
- **启动参数**：`--chat-api-base-url`、`--redis-url`、`--request-timeout`（必填）

#### `robot/clients.py` — HTTP 客户端封装

- `ChatAPIClient`：封装对 Chat API 的所有 HTTP 调用（conversation CRUD + send_message）
- `ProviderClient`：封装对 OpenAI-compatible LLM 的 `/chat/completions` 调用，超时由 `--request-timeout` 控制

#### `frontend/` — React 前端

- 通过 `/api/robot/*` 调用 Robot API 管理 Robot / Contact / ProviderConfig / Session
- 通过 `/api/conversations/{id}/messages` 直接与 Chat API 交互（发消息 + 长轮询拉取）
- 通过 `/api/robot/sessions/{id}/planned-replies` 长轮询展示 Worker 正在排队的待发消息

---

### 数据库设计

#### `storage/chat.db`

| 表 | 主键规则 | 说明 |
| --- | --- | --- |
| `conversations` | `c_{uuid12}` | 聊天会话，支持软删除（is_deleted / deleted_at） |
| `messages` | 自增 Integer | 聊天消息，role 为 `user` 或 `robot` |

`messages` 包含 `msg_type` 字段（如 `text`），为未来富媒体消息预留。

#### `storage/robot.db`

| 表 | 主键规则 | 说明 |
| --- | --- | --- |
| `robots` | `r_{uuid8}` | 机器人角色，含 `name` + `profile`（System Prompt），支持软删除 |
| `contacts` | `ct_{uuid8}` | 联系人画像，含 `name` + `profile`，支持软删除 |
| `provider_configs` | `p_{uuid8}` | LLM Provider 配置，`api_key` 仅在内部使用，API 返回时脱敏 |
| `sessions` | `s_{uuid8}` | 核心会话，关联 robot + contact + provider_config + adapter conversation |
| `robot_messages` | 自增 Integer | 完整消息历史（source of truth），含调度状态 |

**`sessions` 关键字段：**
- `adapter_type`：当前固定为 `"chat"`，为未来接入微信/企微预留
- `adapter_thread_id`：对应 chat.db 中 `conversations.id`（唯一索引）
- `status`：DB 层存储 `"active"` / `"deleted"`；API 响应时若对应 Conversation 不存在则动态计算为 `"orphaned"`

**`robot_messages` 关键字段：**
- `role`：`"user"`（用户输入）或 `"assistant"`（机器人回复）
- `status`：`"scheduled"`（已计划待发）/ `"sent"`（已发送）/ `"canceled"`（被新消息打断取消）
- `scheduled_for`：计划发送时间，Worker 据此 sleep

---

### 数据处理流程

#### 创建 Session

```
用户 → POST /api/robot/sessions
Robot API → 验证 robot/contact/provider_config 存在
         → POST /api/conversations（Chat API）
         → 创建 SessionRecord（robot.db）
         → 返回完整 session payload（含 adapter.thread）
```

#### 用户发消息 → 机器人回复

```
1. 用户 → POST /api/conversations/{id}/messages (role=user)
2. Chat → 存 Message（chat.db）→ LPUSH robot:inbox {conversation_id, role, content}
3. Worker → BRPOP robot:inbox
4. Worker → 查找 Session（by adapter_thread_id）→ 存 RobotMessage(role=user, status=sent)
5. Worker → Cancel 旧 Task（若有）→ 将旧 scheduled 消息标记 canceled
6. Worker → 查询消息历史（status=sent）+ robot/contact profile → 构建 LLM messages
7. Worker → POST {llm_base_url}/chat/completions → 解析 JSON 响应
8. Worker → 批量写入 RobotMessage(role=assistant, status=scheduled, scheduled_for=...)
9. Worker → 逐条 asyncio.sleep → 更新 status=sent → POST /api/conversations/{id}/messages (role=robot)
10. 前端 → GET /api/conversations/{id}/messages?last_id=M&timeout=30（长轮询）→ 收到新消息
```

#### 故障恢复（Worker 启动时）

```
Worker 启动 → 扫描所有 status=active Session
            → 若最后一条 RobotMessage.role == "user"
            → LPUSH robot:inbox {conversation_id, recovery: true}
            → 正常走消费流程（不重复写 user 消息，直接生成回复）
```

#### LLM Prompt 构建规则

- System prompt = `OUTPUT_FORMAT_INSTRUCTION` + robot.profile + `【联系人档案：{name}】\n{contact.profile}`
- 消息历史仅包含 `status=sent` 的消息（scheduled/canceled 的不进入上下文）
- `role=assistant` 的消息 → LLM messages 中 role=`"assistant"`；其余 → `"user"`
- 内容以 `data:` 开头（base64 附件）→ 替换为 `"[附件已省略]"`
- LLM 必须返回合法 JSON：`{"messages": [{"delay_seconds": N, "content": "..."}]}`
