# Laborster 项目背景

## 产品定位

Laborster 是一个**通用拟人自动化回复服务**，帮助职业用户在私聊场景中长期保温关系。

**核心场景**：娱乐主播、销售、自由职业者等，会有大量长期联系人（粉丝、客户）。本人忙不过来回复，我们用 AI 接管，以极高拟人度替他和联系人聊天。

**当前阶段聚焦**：先把「主播-粉丝」场景吃透，命名上保持中性以兼容未来场景。

**核心目标**：非常非常像真人。不冷场、不让对方的话落地上、培养亲密感。只提供情绪价值，不涉及金钱交易和线下约会（红线在 `studio/reply.py:SYSTEM_INSTRUCTION`，未来引入 Playbook 后可按场景定制）。

管理员在 Studio 后台维护账号和全局 **Provider**；主播 / 销售等普通用户配置自己 — 创建 **Persona**（人设）、上传历史聊天蒸馏出 Persona + 每个 **Conversation**（会话）的 **Card_md**（关系卡 Markdown）；主播 PC 上跑一个 **Bridge** daemon，把本机各种平台登录（chat / 未来微信 / 飞书...）桥到 Studio。Studio 拿 Persona + Card_md + 实时对话历史调 LLM 生成拟人化回复，每条回复 chunk 作为独立 OutboundMessage（带 `send_after` 时间戳控制打字节奏），经 Bridge 立即发出。

## 架构原则

- 简单可靠、耐操、易于理解、可扩展、性能好
- 三件套：**Channel（聊天平台）↔ Bridge（主播 PC daemon）↔ Studio（云端）**。Studio 不直连任何 Channel；Bridge 不调 LLM、不存人设。仓库代码层面合并成**两个项目**——`services/`（云端：Studio + Chat sandbox + admin 同进程，schema 隔离）和 `bridge/`（主播本机 daemon），但运行时 Bridge → Chat 仍走 HTTP，Channel 边界不破。
- Bridge 用账号密码握手 + 长轮询，没有消息队列；Studio 用一张 `outbound_messages` 表当队列即可。
- 延迟发送（拟人打字速度）由 Studio worker 在创建 OutboundMessage 时通过 `send_after` 时间戳控制；Bridge 侧不做任何 delay，收到即发。
- Studio 拥有完整消息历史（source of truth），Bridge 离线不影响 Studio 决策。
- **核心数据原语**：Account（admin / user）+ Inbox（一个 Channel 上的身份，N 个）+ Conversation（接管单元，N 个，挂在 Inbox 下）+ Persona（用户内容资产）+ Provider（管理员维护的全局 LLM 配置）。

## 编码偏好

- **禁止偷偷搞默认值**：所有配置（环境变量、CLI 参数、连接串）必须由外部显式指定，缺失时直接报错。不允许用 fallback 默认值静默连接到错误的服务。

## 问题处理原则

- **第一性原理**：遇到问题先从根本原因和架构层面思考，不要缝缝补补打补丁。如果设计本身有缺陷，就改设计，而不是在坏设计上叠 workaround。
- **完成后自验证**：改完代码后必须自己提交 git、启动 docker、针对性地做验证，确认改动生效且无副作用。不要改完就丢给用户。
- **做减法**：积极发现并提出可以删除、合并、简化的部分，保持系统纯净，拒绝臃肿。
- **不要自由发散**：除非特别简单的问题，否则对拿不准的细节、方案、改动范围**必须通过 askQuestion 反复和用户沟通确认**，直到用户同意方案后再动手。
- **大胆重构**：现在项目处在开发阶段，所以可以大刀阔斧的自由重构，不需要为了兼容而写任何代码，只需要在重构的时候告知用户即可。

## 技术栈

- 后端：Python 3.12+, FastAPI, SQLAlchemy, PostgreSQL, httpx
- 前端：React + TypeScript + Vite
- 部署：Docker Compose + Nginx 反向代理

---

## 技术架构详解

### 仓库结构（两项目）

| 项目 | 路径 | 跑在哪 |
| --- | --- | --- |
| Server  | [services/](services/) | 云端 compose；同一 FastAPI 进程里挂 studio + chat 子包，另起 admin-api、worker、user_web、admin_web、cloudflared |
| Bridge  | [bridge/](bridge/) | 主播本机的 Python daemon |

详细架构、不变量、schema 布局、Bridge 协议见 `.agents/skills/repository-architecture/SKILL.md`，那是最新事实。

### Server 进程组成（docker-compose.yaml）

| 服务 | 内部端口 | 职责 |
| --- | --- | --- |
| `db` | 5432 | 单 PostgreSQL，三 schema（auth / studio / chat） |
| `minio` + `minio-create-buckets` | 9000 | 单 bucket `${S3_BUCKET}` |
| `migrate` | — | 一次性，`studio.migrate` 建 schema + alembic upgrade |
| `user-api` | 23456 | FastAPI `studio.main:app`：挂 studio 路由 + `/api/chat/*` + bridge protocol |
| `user-worker` | — | DistillScanner + ReplyScanner |
| `admin-api` | 23457 | FastAPI `admin.app:app`；Cloudflare Access 在边缘鉴权 |
| `user-web` | 23456 | nginx + user_web 构建产物；`/studio` 和 `/chat` 都是它的 SPA 路由 |
| `admin-web` | 23457 | nginx + admin_web |
| `cloudflared` | — | tunnel |

Server 进程不直连 Channel：所有平台 IO 都经过 Bridge HTTP。

### Bridge 内部组成

Bridge 是单进程 daemon。通过 REPL `/login` 命令完成 Studio 账号密码握手，再通过 `/channel add` 添加平台账号。

启动后内部跑：

- 每个 channel 登录一个 `Adapter`（目前仅 ChatAdapter），调用平台 API 完成 login → poll → send。
- 一个 inbound pump：只转发 Studio 标记为 takeover 的会话的新消息，批量推到 Studio `/api/bridge/incoming`。
- 一个 outbound long-poll：从 Studio `/api/bridge/outbound` 拉 pending 出件，立即调 `adapter.send()` 发送。
- 一个 heartbeat：每 15s 一次 `/api/bridge/heartbeat`；刷新 last_seen_at。
- 一个 takeover watcher：每 10s 从 `/api/bridge/takeovers` 拉取需要接管的会话集合，供 inbound pump 过滤。

### Bridge ↔ Studio 协议

| 端点 | 谁调 | 干什么 |
| --- | --- | --- |
| `POST /api/bridge/handshake` | Bridge → Studio | 账号密码 + machine_id → token + account_id + username + machine_id |
| `POST /api/bridge/heartbeat` | Bridge → Studio | 续租 session、更新 last_seen_at |
| `POST /api/bridge/inboxes`   | Bridge → Studio | 注册当前 daemon 持有的 inbox 集合（platform + platform_self_id + display_name） |
| `GET  /api/bridge/inboxes`   | Bridge → Studio | 拉服务认可的 inbox 列表 |
| `POST /api/bridge/conversations` | Bridge → Studio | 同步会话目录（kind / display_name / members） |
| `GET  /api/bridge/takeovers` | Bridge → Studio | 拉取需要接管的 (inbox_id, platform_conversation_id) 集合 |
| `POST /api/bridge/incoming`  | Bridge → Studio | 批量推消息，按 `(conversation_id, client_id)` 去重 |
| `GET  /api/bridge/outbound`  | Bridge → Studio | 长轮询 pending outbound（无 cursor、无 lease、无 ack）|

**Bridge auth 模型**：Bridge 通过 `/login` 命令用账号密码握手，Studio 按 `(account_id, machine_id)` upsert Bridge 行（machine_id 由 Studio 首次握手时生成 4 位随机 ID，Bridge 持久化到本地 SQLite），创建 `auth.auth_sessions` 行发回 token。撤销靠 DELETE `/api/bridges/{bridge_id}`（取消 pending outbound、解绑 inbox、删 Bridge 行；下次握手重新签发 machine_id）。

---

### 数据库设计

#### `services` 内的 `studio.db`

| 表 | 主键 | 说明 |
| --- | --- | --- |
| `accounts` | String(48) | Studio 登录账号；`status ∈ {active, disabled}` |
| `auth_sessions` | String(64) | web + bridge 共用登录会话 |
| `provider_configs` | String(48) | LLM Provider 配置（base_url + model + api_key）；最早创建那条作为默认 |
| `personas` | String(48) | 人设；`(account_id, name)` 唯一 |
| `bridges` | String(48) | Bridge daemon 注册记录；`(account_id, machine_id)` 唯一 |
| `inboxes` | String(48) | 平台身份；`bridge_id` 指向当前承载的 Bridge（可空） |
| `conversations` | String(48) | 接管单元；`(inbox_id, platform_conversation_id)` 唯一。持有 `kind`、`persona_id`、`provider_id`、`takeover`、`reply_policy`、`card_md`、`last_reply_round_at` |
| `conversation_members` | 复合 `(conversation_id, peer_platform_id)` | 会话成员（DM 1 条，群 N 条） |
| `messages` | 自增 BigInteger | 全部消息历史；`(conversation_id, client_id)` 唯一。`sender_id IS NULL` 表示自己发出 |
| `distill_jobs` | String(48) | 蒸馏任务（pending/running/done/failed） |
| `outbound_messages` | 自增 BigInteger | Studio→Bridge 发送队列；`status ∈ {pending, delivered, failed, canceled}`。`send_after` 控制打字节奏 |
| `llm_logs` | 自增 BigInteger | LLM 调用记录；`purpose ∈ {reply, distill}` |

`auth` schema 含 `accounts` + `auth_sessions`；`chat` schema 含 `contacts` + `conversations` + `messages`（chat sandbox 自用）。

**关键关系：**

```
Account
  ↓ owns
Bridge  (按 (account_id, machine_id) upsert，machine_id 由 Studio 首次握手生成)
  ↓ serves
Inbox   (通过 POST /api/bridge/inboxes 注册)
  ↓ holds
Conversation (按 (inbox_id, platform_conversation_id) 唯一，/incoming 时自动建占位行)
  ↓ has
  messages + conversation_members
```

Persona 跨 Inbox / Conversation 共享。ProviderConfig 由 admin 全局维护，Conversation 持有 `provider_id` 控 reply LLM 路由，Account 持有 `distill_provider_id` 控 distill LLM 路由。

---

### 数据处理流程

#### Onboarding

```
1. web 首次初始化：没有账号时创建首个 admin；admin 在设置页创建普通 user + 全局默认 Provider
2. user 登录 → 建至少一个 Persona
3. 主播 PC: 启动 Bridge daemon → /login 握手获取 token 和 machine_id → /channel add 添加平台账号
4. bridge daemon → handshake → Studio 自动建 Bridge 行；/api/bridge/inboxes 注册 Inbox 行
5. web 「接管」tab：第一条消息进来后 Conversation 占位行自动创建；选人设 / 开 autoreply / 写关系卡；Provider 默认取最早创建的 ProviderConfig
6. 在「接管」tab 配置 Conversation 的人设和 autoreply；Bridge 积累一定消息后可在「蒸馏」tab 创建 distill job 自动产出 Persona + 各 Conversation 的 Card_md
```

#### 用户发消息 → 机器人回复

```
1. counterpart 发消息到 chat sandbox
2. Bridge ChatAdapter poll 到，inbound pump 推到 Studio /api/bridge/incoming
3. studio-api 写 messages（sender_id = 对方平台 ID）；如果 conversation.takeover && conversation.reply_policy=autoreply，后续由 ReplyScanner 处理
4. studio-worker ReplyScanner 每 2s 扫描满足条件的 conversation，_decide() 8-gate 校验：
  - conversation.status=active / reply_policy=autoreply / persona_id 非空 / provider 有 api_key
  - 最新消息来自对方（sender_id IS NOT NULL）
  - 距离对方最新消息 ≥ QUIET_SECONDS（避免对方还没打完就抢答）
 5. 通过 → 调 LLM → 解析 {"messages": [...]} → 每条 chunk 写一条独立 OutboundMessage(status=pending, send_after=计算打字节奏)
 6. Bridge outbound long-poll 拿到，立即调 adapter.send() 发送
 7. Bridge 上报 from_self inbound；Studio 按 (conversation_id, content) 匹配 PENDING outbound 自动标 delivered
```

#### Reply Prompt 构建规则（studio/reply.py）

- system prompt = 硬编码 `SYSTEM_INSTRUCTION`（拟人 + 红线规则）。
- user message = persona.persona_md + conversation.card_md + 最近 N 条历史（自然语言格式：`[mm-dd HH:MM] 我/对方: ...`）。
- 历史包含全部消息，按 timestamp 升序；最后一条必须是 counterpart 才会触发回复。
- LLM 必须返回 `{"messages": ["第一条", "第二条"]}`；空数组表示"装作没看见"。
- 每条 LLM 回复 chunk 写一条独立 OutboundMessage，`send_after` 在 Studio 端按 `len(content) / 6 chars/sec` 计算打字节奏，最少 1s 最多 12s；首条多加 1.5s think delay。Bridge 收到即发，不做延迟。

#### Distill Pipeline（studio/distill/）

- 输入：一个 Inbox 下的全部历史消息（由 Bridge incoming 积累）。
- 切 session（30 分钟间隔）→ 切 window（40k token 上限）→ 滚动 fold：每个 window 调一次 LLM，更新 target Persona 的 `persona_md` + 当前 Conversation 的 `card_md`（覆盖式）。
- prompt 输出非对称：一段 `===== Character Persona =====`（主播本人）+ 一段 `===== Contact Card =====`（当前粉丝）。
- 进度回写 `distill_jobs.progress` JSON，前端轮询。
