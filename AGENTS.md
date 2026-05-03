# Laborster 项目背景

## 产品定位

Laborster 的核心产品是 **Robot** —— 一个通用的拟人自动化回复服务，帮助职业用户在私聊场景中长期保温关系。

**核心场景**：娱乐主播、销售、自由职业者等，会有大量长期联系人（粉丝、客户、客户）。本人忙不过来回复，我们用 AI 接管，以极高拟人度替他和联系人聊天。

**当前阶段聚焦**：先把「主播-粉丝」场景吃透，命名上保持中性以兼容未来场景。

**核心目标**：非常非常像真人。不冷场、不让对方的话落地上、培养亲密感。只提供情绪价值，不涉及金钱交易和线下约会（红线在 `runtime.py:SYSTEM_INSTRUCTION`，未来引入 Playbook 后可按场景定制）。

主播在后台配置自己（**Operator**），上传历史聊天记录蒸馏出 **Persona**（人设）+ 每个粉丝（**Contact**）的 **Card**（索引卡），让 AI 基于这些档案 + 对话历史生成拟人化回复。

## 当前阶段

- **Chat Service** 是一个**调试用的微信模拟器（Adapter）**。未来 Robot 会接入真实微信、企微等多个平台，Chat 只是其中一个调试 Adapter。
- 上传聊天记录会**双写**：一份进 robot.db 给蒸馏用，一份调 Chat API 把历史导入对应会话——这样在 Chat UI 里能看到完整聊天历史，开发者扮演粉丝继续聊就完成端到端调试，路径和真实微信完全同构。
- 除非 Chat 有重大设计失误，否则尽量不动它。

## 架构原则

- 简单可靠、耐操、易于理解、可扩展、性能好
- Robot Worker 每秒轮询 Chat API 获取新消息，不依赖消息队列
- Robot Service 拥有完整消息历史（source of truth），不依赖 Adapter 在线
- 延迟发送用 asyncio.sleep 实现，不需要额外表
- **核心数据三原语**：Operator（主播本人，1 个）+ Contact（粉丝，N 个）+ Conversation（每个粉丝一段对话，原始数据）。不要再回到把档案塞 Session 字段的模型。

## 编码偏好

- **禁止偷偷搞默认值**：所有配置（环境变量、CLI 参数、连接串）必须由外部显式指定，缺失时直接报错。不允许用 fallback 默认值静默连接到错误的服务。

## 问题处理原则

- **第一性原理**：遇到问题先从根本原因和架构层面思考，不要缝缝补补打补丁。如果设计本身有缺陷，就改设计，而不是在坏设计上叠 workaround。
- **完成后自验证**：改完代码后必须自己提交 git、启动 docker、针对性地做验证，确认改动生效且无副作用。不要改完就丢给用户。
- **做减法**：积极发现并提出可以删除、合并、简化的部分，保持系统纯净，拒绝臃肿。
- **不要自由发散**：除非特别简单的问题，否则对拿不准的细节、方案、改动范围**必须通过 askQuestion 反复和用户沟通确认**，直到用户同意方案后再动手。
- **大胆重构**：现在项目处在开发阶段，所以可以大刀阔斧的自由重构，不需要为了兼容而写任何代码，只需要在重构的时候告知用户即可。

## 技术栈

- 后端：Python 3.12+, FastAPI, SQLAlchemy, SQLite, httpx
- 前端：React + TypeScript + Tailwind CSS + Vite
- 部署：Docker Compose + Nginx 反向代理

---

## 技术架构详解

### 整体架构

系统四个运行单元，全部通过 Docker Compose 编排，由 Nginx 统一对外暴露 23456 端口：

| 容器 | 对外路径 | 内部端口 | 职责 |
| --- | --- | --- | --- |
| `nginx` | `:23456` | — | 静态资源 + 反向代理 |
| `chat` | `/api/*` | `:23456` | Chat Adapter 服务（FastAPI），充当微信模拟器 |
| `robot-api` | `/api/robot/*` | `:23457` | Robot 管理 API（FastAPI） |
| `robot-worker` | — | — | 1 个 Session Scanner + 1 个 Distill Scanner + N 个 Session Loop（asyncio） |

Nginx 路由（nginx.conf）：
- `/api/robot/` → `robot-api:23457/api/`（去掉 `/robot` 前缀）
- `/api/` → `chat:23456/api/`
- `/storage/` → 本地磁盘附件目录
- `/` → React 静态资源（SPA fallback）

---

### 模块职责

#### `chat/` — Chat Adapter（微信模拟器）

- **定位**：最简化的聊天 Adapter，不含任何角色/策略逻辑，仅存储原始消息。
- **核心职责**：
  - 管理 `User`（用户）、`Conversation`（聊天会话）和 `Message`（消息）的 CRUD
  - 提供长轮询接口 `GET /api/conversations/{id}/messages?last_id=M&timeout=N`
  - **`POST /api/conversations/{id}/messages/bulk`**：保留历史 timestamp 的 bulk import 接口，专给 Robot ingest 时把 WeFlow 历史聊天注入进来
  - 提供 `/storage` 静态文件服务（附件）
- **数据库**：`storage/chat.db`
- **外部依赖**：无

#### `robot/main.py` — Robot API

- **定位**：Robot 领域的管理 API，是前端操作所有 Robot 实体的唯一入口。
- **核心职责**：
  - `Operators` CRUD：创建 Operator 时**自动调 Chat API 创建一个 chat user**，绑到 `operator.adapter_identities.chat`
  - `Contacts` CRUD：列表 + 单条更新（display_name / card_md）。Contact 由 ingest 自动创建，不暴露 POST。
  - `ChatArchives` 上传 + 列表：`POST /api/operators/{id}/chat-archives`（multipart：`self_wxid` + `file`）触发 ingest（[robot/distill/ingest.py](robot/distill/ingest.py)）
  - `DistillJobs` 创建 + 查询：`POST /api/operators/{id}/distill-jobs` 写一行 pending 任务，worker 后台执行
  - `Sessions` 只读：由 ingest 自动管理，前端只查看
  - `ProviderConfigs` CRUD
  - `GET /api/sessions/{id}/planned-replies` 长轮询，供前端实时展示待发送消息
  - 透传 `GET /api/conversations` 给前端展示 chat 会话列表（debug 用）
- **数据库**：`storage/robot.db`
- **外部依赖**：Chat API（HTTP）
- **启动参数**：`--host`、`--port`、`--chat-api-base-url`（必填）

#### `robot/distill/` — 蒸馏管线

- **`converter.py`**：WeFlow JSON 工具：`build_name_map`（wxid→name）、`should_keep`（消息过滤）、`message_timestamp`、`clean_content`
- **`packer.py`**：`TextMessage` / `Window` 数据类，`split_sessions`（按 30 分钟间隔切 session）、`pack_windows`（按 40k token 限制打包）
- **`ingest.py`**：上传入口。校验 self_wxid → upsert Contact（含创建 chat user）→ upsert Session（含创建 chat conversation）→ 写 `messages` 表（source='upload'）→ bulk-import 到 chat 模拟器（仅首份 archive）
- **`pipeline.py`**：滚动 fold。`run_distill_for_operator(operator_id, request_timeout, progress_cb)` 遍历每个 Contact，window-by-window 调 LLM 更新 `operator.persona_md` + `contact.card_md`。也提供 CLI（`python -m robot.distill.pipeline --operator-id ... --request-timeout ...`）做调试。
- **`prompts/fold.md`**：fold prompt。**非对称**输出——一段 Operator Persona（主播本人）+ 一段 Contact Card（当前粉丝的固定字段索引卡）

#### `robot/worker.py` + `robot/runtime.py` — Robot Worker

- **定位**：独立运行的消息消费者 + 蒸馏执行者。
- **核心架构**：1 个 Session Scanner + 1 个 Distill Scanner + N 个 Session Loop
  - **Session Scanner**：每 5s 扫 `sessions` 表，为新 active Session 创建 Session Loop，为已 inactive Session 销毁 Session Loop
  - **Session Loop**：每 1s 轮询 Chat API（`get_messages`），新消息存入 `messages` 表（source='live'），最后一条 sent 是 counterpart 时调 LLM 生成 reply → 写入 scheduled 消息 → 按 `scheduled_for` 时间 asyncio.sleep → 状态置 sent → 调 Chat API 发送
  - **Distill Scanner**：每 5s 扫 `distill_jobs` 表，pending 任务起一个 task 跑 `run_distill_for_operator`，进度回写 `progress` 字段，结束置 `done`/`failed`
- **故障恢复**：自然实现——Worker 重启后扫描重建。Session Loop 启动时取当前最新 chat message id 作为 `last_id`，**自动跳过 backlog**（包括 ingest 时 bulk-import 的历史聊天），不会误回复历史消息
- **数据库**：`storage/robot.db`（同 Robot API 共享）
- **外部依赖**：Chat API（HTTP）、LLM Provider（HTTP）
- **启动参数**：`--chat-api-base-url`、`--request-timeout`（必填）

#### `robot/clients.py` — HTTP 客户端封装

- `BaseAdapter`（ABC）：消息平台适配器抽象基类
- `ChatAdapter`：包含完整的 chat API 调用：`list_conversations` / `get_conversation` / `get_messages` / `send_message` / **`create_user`** / **`create_conversation`** / **`bulk_import_messages`** / `close`
- `ProviderClient`：封装 OpenAI-compatible LLM 的 `/chat/completions` 调用

#### `frontend/` — React 前端

- **HomePage**：选 Chat / Robot 入口
- **ChatPage**：微信模拟器 UI，按 user 身份发消息，长轮询拉取
- **RobotPage**：Tabs 布局
  - 顶部：Operator 选择器 + 新建主播
  - **人设**：Persona markdown 编辑器
  - **联系人**：Contact 列表，点击展开编辑 Card
  - **聊天记录**：上传 WeFlow JSON + 历史 archive 列表
  - **蒸馏**：触发 distill job + 进度展示
  - **Provider**：ProviderConfig CRUD + 绑定到当前 Operator

---

### 数据库设计

#### `storage/chat.db`

| 表 | 主键规则 | 说明 |
| --- | --- | --- |
| `users` | `u_{uuid8}` | 用户，支持软删除 |
| `conversations` | `c_{uuid12}` | 聊天会话，关联两个 User |
| `messages` | 自增 Integer | 聊天消息，含 sender_id、msg_type、content、created_at |

#### `storage/robot.db`

| 表 | 主键规则 | 说明 |
| --- | --- | --- |
| `provider_configs` | `p_{uuid8}` | LLM Provider 配置 |
| `operators` | `op_{uuid8}` | 主播本人。`adapter_identities` 是 JSON，存 `{chat: u_xxx, wechat_wxid_self: ...}` |
| `contacts` | `ct_{uuid8}` | 粉丝。`(operator_id, wechat_wxid)` 唯一索引去重 |
| `sessions` | `s_{uuid8}` | Contact ↔ Adapter Thread 连接器（仅 contact_id, adapter_type, adapter_thread_id, status） |
| `chat_archives` | `a_{uuid8}` | 上传的 WeFlow JSON 文件清单。`(operator_id, file_hash)` 唯一去重 |
| `messages` | 自增 Integer | 统一消息表（upload 历史 + live 实时），`source` 区分。`(archive_id, archive_msg_idx)` 唯一防重复入库 |
| `distill_jobs` | `dj_{uuid8}` | 蒸馏任务。`status`: pending/running/done/failed；`progress`: JSON |
| `llm_logs` | 自增 Integer | LLM 调用日志。`purpose`: 'reply' / 'distill' |

**关键关系**：
```
Operator (1)
  ↓ owns
Contact (N)  ←  (operator_id, wxid) 唯一
  ↓ has
Session (1 per adapter)  →  adapter_thread_id  →  chat.conversations.id
Contact (1)
  ↓ holds
messages (N)  with source = upload | live
```

---

### 数据处理流程

#### 主播 Onboarding

```
1. 前端 → POST /api/robot/operators (name, provider_config_id)
2. Robot API → POST chat:/api/users (创建对应的 chat user) → 拿到 u_xxx
3. Robot API → 写 operators (adapter_identities.chat = u_xxx)
4. 前端 → POST /api/robot/operators/{id}/chat-archives (multipart: self_wxid + file)
5. Robot API → ingest_archive():
   - 校验 self_wxid 存在于 messages
   - upsert Contact (创建 chat user 给粉丝)
   - upsert Session (创建 chat conversation)
   - 写 messages (source=upload)
   - 调 chat /messages/bulk 把历史聊天注入模拟器（保留历史 timestamp）
6. 前端 → POST /api/robot/operators/{id}/distill-jobs
7. Worker Distill Scanner 拾取 → 跑 run_distill_for_operator()
   - 遍历每个 Contact
   - 每个 Contact 切 session/window，rolling fold 调 LLM 更新 persona_md + card_md
8. 前端 → 轮询 GET /api/robot/distill-jobs/{id} 看进度
9. 前端 → 在「人设 / 联系人」tab 校对自动生成的内容
```

#### 用户发消息 → 机器人回复

```
1. 调试者在 ChatPage → 切换为 Contact 身份 → POST /api/conversations/{id}/messages
2. Chat → 存 Message → 返回成功
3. Worker Session Loop 每秒 GET /api/conversations/{id}/messages?last_id=M&timeout=0
4. Worker → 检测到 sender_id != operator.adapter_identities.chat
5. Worker → 写 messages(source=live, role=counterpart, status=sent)
6. Worker → 检查 messages 最后一条 sent，role=counterpart → 触发 LLM
7. Worker → build_system_prompt(operator, contact) + build_chat_history(history)
   - history 包含 source=upload 和 source=live 的全部 sent 消息
8. Worker → 调 LLM → 解析 JSON → 写 messages(source=live, role=self, status=scheduled)
9. Worker → 按 scheduled_for asyncio.sleep → status=sent → POST chat/messages
10. 前端长轮询拉到新消息
```

#### 故障恢复

```
Worker 重启 → Session Scanner 扫 active sessions → 创建 Session Loop
            → Session Loop 取 chat 当前最大 msg.id 作为 last_id（跳过 backlog）
            → 检查 messages 最后一条 sent 是 counterpart？是 → 触发 LLM 回复
            → 无需额外恢复逻辑

Distill Scanner 同理：扫 pending 任务继续跑
```

#### Reply Prompt 构建规则

- System prompt = `SYSTEM_INSTRUCTION`（硬编码微信拟人指令）+ `operator.persona_md` + `contact.card_md` + `【当前时间】{北京时间}`
- 消息历史包含 source=upload + source=live 的全部 status=sent 消息，按 timestamp 排序
- `role=self` → LLM messages 中 role=`assistant`；其余 → `user`
- 内容以 `data:` 开头（base64 附件）→ 替换为 `[附件已省略]`
- LLM 必须返回合法 JSON：`{"messages": ["第一条", "第二条"]}`
- delay_seconds 由打字速度（6 字/秒，最少 2s）自动计算，不再由 LLM 指定

#### Distill Prompt 构建规则（fold.md）

- 输入：operator/contact 名字 + wxid + 当前 persona_md + 当前 card_md + 一段窗口聊天记录
- 输出非对称：一段 `===== Operator Persona =====` + 一段 `===== Contact Card =====`
- Persona 是主播自己的画像（风格 + 生活情境），覆盖式更新
- Card 是粉丝的索引卡（固定字段 + notes 兜底），覆盖式更新
- `shared_facts` 字段记录主播主动告诉过这个粉丝的事，避免穿帮
