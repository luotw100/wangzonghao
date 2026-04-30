# Laborster 项目背景

## 产品定位

Laborster 的核心产品是 **Robot** —— 一个拟人自动化回复服务，帮助主播在微信里和粉丝保温。

**核心场景**：娱乐主播在直播或发抖音时，粉丝会线下加微信。但主播很忙，来不及及时回复，我们帮助主播和粉丝保温。系统把主播「蒸馏」——模拟主播的记忆、偏好、兴趣、经历，以及主播现实环境的情况（当地地标、交通、餐饮、文化等），以极高的拟人度在微信里和粉丝聊天。

**核心目标**：非常非常像真人。不冷场、不让粉丝的话落地上、培养亲密感。只提供情绪价值，不涉及金钱交易和线下约会。

用户在后台配置 Session（绑定人设 + 联系人画像 + LLM Provider），让 AI 基于这两个角色画像生成拟人化的回复。

## 当前阶段

- **Chat Service** 是一个**调试用的简易聊天平台（Adapter）**，不是最终产品。
- 未来 Robot 会接入微信、企微、飞书等多个消息平台，Chat 只是其中一个调试 Adapter。
- 除非 Chat 有重大设计失误，否则尽量不动它。

## 架构原则

- 简单可靠、耐操、易于理解、可扩展、性能好
- Robot Worker 通过长轮询 Chat API 获取新消息，不依赖消息队列
- Robot Service 拥有完整消息历史（source of truth），不依赖 Adapter 在线
- 延迟发送用 asyncio.sleep 实现，不需要额外表

## 编码偏好

- **禁止偷偷搞默认值**：所有配置（环境变量、CLI 参数、连接串）必须由外部显式指定，缺失时直接报错。不允许用 fallback 默认值静默连接到错误的服务。

## 问题处理原则

- **第一性原理**：遇到问题先从根本原因和架构层面思考，不要缝缝补补打补丁。如果设计本身有缺陷，就改设计，而不是在坏设计上叠 workaround。
- **完成后自验证**：改完代码后必须自己提交 git、启动 docker、针对性地做验证，确认改动生效且无副作用。不要改完就丢给用户。
- **做减法**：积极发现并提出可以删除、合并、简化的部分，保持系统纯净，拒绝臃肿。
- **不要自由发散**：除非特别简单的问题，否则对拿不准的细节、方案、改动范围**必须通过askQuestion反复和用户沟通确认**，直到用户同意方案后再动手。
- **大胆重构**：现在项目处在开发阶段，所以可以大刀阔斧的自由重构，不需要为了兼容而写任何代码，只需要在重构的时候告知用户即可。

## 技术栈

- 后端：Python 3.12+, FastAPI, SQLAlchemy, SQLite, httpx
- 前端：React + TypeScript + Tailwind CSS + Vite
- 部署：Docker Compose + Nginx 反向代理

---

## 技术架构详解

### 整体架构

系统共有四个运行单元，全部通过 Docker Compose 编排，由 Nginx 统一对外暴露 23456 端口：

| 容器 | 对外路径 | 内部端口 | 职责 |
| --- | --- | --- | --- |
| `nginx` | `:23456` | — | 静态资源 + 反向代理 |
| `chat` | `/api/*` | `:23456` | Chat Adapter 服务（FastAPI） |
| `robot-api` | `/api/robot/*` | `:23457` | Robot 管理 API（FastAPI） |
| `robot-worker` | — | — | 消息长轮询 + LLM 调用（asyncio） |

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
  - 管理 `User`（用户）、`Conversation`（聊天会话）和 `Message`（消息）的 CRUD
  - 用户和会话支持软删除（is_deleted / deleted_at）
  - 提供长轮询接口 `GET /api/conversations/{id}/messages?last_id=M&timeout=N`，前端和 Worker 通过此接口拉取新消息
  - 提供 `/storage` 静态文件服务（附件）
- **数据库**：`storage/chat.db`
- **外部依赖**：无

#### `robot/main.py` — Robot API

- **定位**：Robot 领域的管理 API，是前端操作 ProviderConfig / Session 的唯一入口。
- **核心职责**：
  - 管理 `ProviderConfig`（LLM 配置）的 CRUD，api_key 仅在内部使用，API 返回时脱敏
  - 管理 `Session`（会话）的生命周期：创建时绑定 adapter_thread_id 和 takeover_user_id
  - 代理 Chat API 的会话列表（`GET /api/conversations`），供前端创建 Session 时选择
  - 通过 `ChatAdapter`（HTTP）与 Chat 服务通信
  - 提供 `GET /api/sessions/{id}/planned-replies` 长轮询接口，供前端实时展示待发送消息
- **数据库**：`storage/robot.db`
- **外部依赖**：Chat API（HTTP）
- **启动参数**：`--host`、`--port`、`--chat-api-base-url`（必填）

#### `robot/worker.py` + `robot/runtime.py` — Robot Worker

- **定位**：独立运行的消息消费者进程，是 LLM 推理和回复发送的执行者。
- **核心架构**：
  - `RobotRuntime`：顶层编排器，负责启动时故障恢复、定期扫描 active Session、为每个 Session 启动长轮询任务
  - `SessionController`：每个 active Session 一个实例，状态机驱动：`idle → thinking → sending → (idle | thinking)`
- **核心职责**：
  - 启动时执行 **故障恢复**：扫描所有 active Session，若最后一条消息是 user 消息则重新触发处理
  - 为每个 active Session 长轮询 Chat API（`get_messages(timeout=30)`），检测到非 takeover_user 发的消息后推入 SessionController 的 inbox
  - 收到消息后：存入 `robot_messages`（role=user, status=sent）→ 启动 think+send 流程
  - 若同一 SessionController 有未完成的处理（thinking/sending 状态），标记 interrupted，旧 scheduled 消息变为 pending
  - 调用 LLM，解析 JSON 响应（含 `pending` 决策和 `messages` 新消息）
  - 将所有计划回复写入 `robot_messages`（status=scheduled）
  - 按 `scheduled_for` 时间依次 `asyncio.sleep` → 更新 status=sent → 调用 Chat API 发送消息
  - 所有 LLM 调用记录到 `llm_logs` 表
- **数据库**：`storage/robot.db`（同 Robot API 共享）
- **外部依赖**：Chat API（HTTP 长轮询 + 发送回复）、LLM Provider（HTTP）
- **启动参数**：`--chat-api-base-url`、`--request-timeout`（必填）

#### `robot/clients.py` — HTTP 客户端封装

- `BaseAdapter`（ABC）：消息平台适配器抽象基类，定义 `list_conversations`、`get_conversation`、`get_messages`、`send_message`、`close` 接口
- `ChatAdapter`：继承 `BaseAdapter`，封装对 Chat API 的所有 HTTP 调用
- `ProviderClient`：封装对 OpenAI-compatible LLM 的 `/chat/completions` 调用，超时由 `--request-timeout` 控制

#### `robot/distill/` — Distill CLI（蒸馏工具）

- **定位**：独立的命令行工具，从微信聊天记录导出文件中蒸馏出每个人的风格档案和记忆账本。
- **核心流程**：
  1. 加载 WeFlow JSON 聊天导出文件
  2. `converter.py`：构建 wxid→姓名映射，过滤消息类型，转为 `[timestamp] sender: content` 格式
  3. `packer.py`：按 30 分钟间隔切分 Session，按 40k token 限制打包为 Window
  4. `pipeline.py`：滚动蒸馏（rolling fold），每个 Window 调用 LLM 更新档案，输出每人 `style.md` + `memory.md`
- **外部依赖**：LLM Provider（HTTP，复用 `ProviderClient`）
- **启动参数**：`--input`、`--api-base`、`--api-key`、`--model`、`--output-dir`（必填），`--request-timeout`、`--max-windows`（可选）

#### `frontend/` — React 前端

- 通过 `/api/robot/*` 调用 Robot API 管理 ProviderConfig / Session
- 通过 `/api/conversations/{id}/messages` 直接与 Chat API 交互（发消息 + 长轮询拉取）
- 通过 `/api/robot/sessions/{id}/planned-replies` 长轮询展示 Worker 正在排队的待发消息
- 暗色赛博朋克风格 UI，cyan (#00e5ff) 为主色调

---

### 数据库设计

#### `storage/chat.db`

| 表 | 主键规则 | 说明 |
| --- | --- | --- |
| `users` | `u_{uuid8}` | 用户，支持软删除（is_deleted / deleted_at） |
| `conversations` | `c_{uuid12}` | 聊天会话，关联两个 User（user_a_id / user_b_id），支持软删除 |
| `messages` | 自增 Integer | 聊天消息，含 sender_id、msg_type（如 `text`）、content |

#### `storage/robot.db`

| 表 | 主键规则 | 说明 |
| --- | --- | --- |
| `provider_configs` | `p_{uuid8}` | LLM Provider 配置，`api_key` 仅在内部使用，API 返回时脱敏 |
| `sessions` | `s_{uuid8}` | 核心会话，关联 provider_config + adapter conversation |
| `robot_messages` | 自增 Integer | 完整消息历史（source of truth），含调度状态 |
| `llm_logs` | 自增 Integer | LLM 调用日志，记录请求/响应/模型 |

**`sessions` 关键字段：**
- `adapter_type`：当前固定为 `"chat"`，为未来接入微信/企微预留
- `adapter_thread_id`：对应 chat.db 中 `conversations.id`（唯一索引）
- `takeover_user_id`：机器人扮演的 User.id（在 Chat 中以此身份发送回复）
- `profile`：机器人人设文本（System Prompt 的核心部分）
- `counterpart_profile`：联系人画像文本
- `status`：`"active"` / `"deleted"`

**`robot_messages` 关键字段：**
- `role`：`"user"`（用户输入）或 `"assistant"`（机器人回复）
- `status`：`"scheduled"`（已计划待发）/ `"sent"`（已发送）/ `"canceled"`（被新消息打断取消）
- `scheduled_for`：计划发送时间，Worker 据此 sleep

**`llm_logs` 关键字段：**
- `request_messages`：发送给 LLM 的完整消息列表（JSON）
- `request_pending`：当前的 pending 消息内容（JSON，可为空）
- `response_raw`：LLM 原始响应文本
- `model`：使用的模型名称

---

### 数据处理流程

#### 创建 Session

```
用户 → POST /api/robot/sessions
Robot API → 检查 adapter_thread_id 唯一性
          → 解析 provider_config_id（未指定则取唯一的一个）
          → 创建 SessionRecord（robot.db）
          → 返回完整 session payload（含嵌入的 provider_config）
```

#### 用户发消息 → 机器人回复

```
1. 用户 → POST /api/conversations/{id}/messages (sender_id=对方, msg_type=text)
2. Chat → 存 Message（chat.db）→ 返回成功
3. Worker → 长轮询 GET /api/conversations/{id}/messages?last_id=M&timeout=30
4. Worker → 检测到 sender_id != takeover_user_id 的新消息
5. Worker → 推入 SessionController.inbox → 存 RobotMessage(role=user, status=sent)
6. Worker → 若 SessionController 正在 thinking/sending → 标记 interrupted
7. Worker → SessionController 状态机：
   a. idle → thinking：取消旧 scheduled 消息（如有），捕获为 pending → 构建 LLM messages → 调用 LLM
   b. thinking 被打断：保留 LLM 返回的 pending 中 action=send 的消息，与新 pending 合并，重新调 LLM
   c. thinking 完成 → 写入 scheduled 消息 → sending：逐条 asyncio.sleep → 更新 status=sent → POST Chat API 发送
   d. sending 被打断：取消剩余 scheduled 消息，捕获为 pending，回到 thinking
8. 前端 → GET /api/conversations/{id}/messages?last_id=M&timeout=30（长轮询）→ 收到新消息
```

#### 故障恢复（Worker 启动时）

```
Worker 启动 → 扫描所有 status=active Session
            → 若最后一条 RobotMessage.role == "user"
            → 推入 SessionController.inbox（recovery: true，不重复写 user 消息）
            → 正常走 think+send 流程
```

#### LLM Prompt 构建规则

- System prompt = `SYSTEM_INSTRUCTION`（硬编码微信拟人指令）+ session.profile + `【当前联系人画像】\n{counterpart_profile}` + `【当前时间】{北京时间}` + pending 消息（如有）
- 消息历史仅包含 `status=sent` 的消息（scheduled/canceled 的不进入上下文）
- `role=assistant` 的消息 → LLM messages 中 role=`"assistant"`；其余 → `"user"`
- 内容以 `data:` 开头（base64 附件）→ 替换为 `"[附件已省略]"`
- LLM 必须返回合法 JSON：
  ```json
  {
    "pending": [
      {"action": "send"},
      {"action": "send", "content": "修改后的文本"},
      {"action": "cancel"}
    ],
    "messages": [
      {"delay_seconds": 5, "content": "消息文本"}
    ]
  }
  ```
- `pending`：对待定消息的决策，与系统提供的待定消息列表一一对应
- `messages`：额外发送的新消息，delay_seconds 反映真实打字速度
