# Laborster 项目背景

## 产品定位

Laborster 是一个**通用拟人自动化回复服务**，帮助职业用户在私聊场景中长期保温关系。

**核心场景**：娱乐主播、销售、自由职业者等，会有大量长期联系人（粉丝、客户）。本人忙不过来回复，我们用 AI 接管，以极高拟人度替他和联系人聊天。

**当前阶段聚焦**：先把「主播-粉丝」场景吃透，命名上保持中性以兼容未来场景。

**核心目标**：非常非常像真人。不冷场、不让对方的话落地上、培养亲密感。只提供情绪价值，不涉及金钱交易和线下约会（红线在 `studio/reply.py:SYSTEM_INSTRUCTION`，未来引入 Playbook 后可按场景定制）。

管理员在 Studio 后台维护账号和全局 **Provider**；主播 / 销售等普通用户配置自己 — 创建 **Persona**（人设）、上传历史聊天蒸馏出 Persona + 每个 **Contact**（粉丝）的 **Card**（关系卡）；主播 PC 上跑一个 **Bridge** daemon，把本机各种平台登录（chat / 未来微信 / 飞书...）桥到 Studio。Studio 拿 Persona + Card + 实时对话历史调 LLM 生成拟人化回复，每条回复 chunk 作为独立 OutboundMessage（带 `send_after` 时间戳控制打字节奏），经 Bridge 立即发出。

## 架构原则

- 简单可靠、耐操、易于理解、可扩展、性能好
- 三件套：**Channel（聊天平台）↔ Bridge（主播 PC daemon）↔ Studio（云端）**。Studio 不直连任何 Channel；Bridge 不调 LLM、不存人设。
- Bridge 用账号密码握手 + 长轮询，没有消息队列；Studio 用一张 `outbound_messages` 表当队列即可。
- 延迟发送（拟人打字速度）由 Studio worker 在创建 OutboundMessage 时通过 `send_after` 时间戳控制；Bridge 侧不做任何 delay，收到即发。
- Studio 拥有完整消息历史（source of truth），Bridge 离线不影响 Studio 决策。
- **核心数据原语**：Account（admin / user）+ Inbox（一个 Channel 上的身份，N 个）+ Contact（粉丝，N 个，挂在 Inbox 下）+ Persona（用户内容资产）+ Provider（管理员维护的全局 LLM 配置）。

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

### 三个独立项目

仓库下三个互不依赖的服务，各自一份 `pyproject.toml` / `uv.lock` / `Dockerfile` / `compose.yaml`：

- [services/chat/](services/chat/) — Chat sandbox（dogfood Channel）
- [services/studio/](services/studio/) — Studio（云端：人设 / 卡片 / 蒸馏 / 回复脑）
- [services/bridge/](services/bridge/) — Bridge daemon（跑在主播 PC 上）

### Studio 内部组成

| 容器 | 内部端口 | 职责 |
| --- | --- | --- |
| `studio-web` (nginx) | `:23457` | 静态资源 + `/api/` 反向代理到 studio-api |
| `studio-api` | `:23457` | FastAPI；账号与首次 admin 初始化 / Persona / Provider / Bridge 握手 / Inbox / Contact / Archive / Distill 全部 CRUD + Bridge 协议 |
| `studio-worker` | — | DistillScanner（扫 pending DistillJob 跑蒸馏）+ ReplyScanner（扫 `pending_reply=true` 的 Contact 调 LLM 写 outbound） |

Studio 不再有任何"直连 Channel"的代码，所有平台 IO 都经过 Bridge。

### Bridge 内部组成

Bridge 是单进程 daemon。一份 CLI 启动命令带：

- 一对 Studio 账号密码（同 web 登录），用来跟 Studio 握手；
- N 个 `--chat-inbox 'base_url=...,username=...,password=...'`，每个对应一个该机器要登的 chat 账号。

启动后内部跑：

- 每个 chat 登录一个 `ChatAdapter`，调用 chat sandbox API 完成 login → poll → send。
- 一个 inbound pump：把所有 adapter 的新消息批量推到 Studio `/api/bridge/incoming`。
- 一个 outbound long-poll：从 Studio `/api/bridge/outbound` 拉 pending 出件，立即调 `adapter.send_text` 发送，最后 ack。
- 一个 heartbeat：每 15s 一次 `/api/bridge/heartbeat`；返回当前 Studio 认可的 inbox 列表，Bridge 把 UI 那边删掉的 inbox 对应 adapter 关掉。

### Bridge ↔ Studio 协议

| 端点 | 谁调 | 干什么 |
| --- | --- | --- |
| `POST /api/bridge/handshake` | Bridge → Studio | 用 Studio 账号密码 + hostname + 已登入的 chat 身份列表换一个 session token；Studio upsert Bridge / Inbox 行，返回 token + 服务的 inbox 列表 + outbound 起始游标 |
| `POST /api/bridge/heartbeat` | Bridge → Studio | 续租 session、同步当前 inbox 列表 |
| `POST /api/bridge/incoming` | Bridge → Studio | 批量推 incoming 消息，按 `(contact_id, external_id)` 去重 |
| `GET /api/bridge/outbound?cursor=N&timeout=T` | Bridge → Studio | 长轮询 pending outbound |
| `POST /api/bridge/outbound/{id}/ack` | Bridge → Studio | 标记发送结果：sent / failed |

**Bridge auth 模型**：没有"先在 UI 创建 Bridge → 拷 token"。daemon 第一次握手时用账号密码登录，Studio 按 `(account_id, hostname)` upsert Bridge 行，wipe 旧 BridgeSession，发回新的 session token；token 只在内存里活，bridge 重启就再换一次。撤销靠 web 「Bridges」tab 的 revoke（删 BridgeSession + status='revoked'，daemon 下次调用 401）。

---

### 数据库设计

#### `services/studio` 内的 `studio.db`

| 表 | 主键规则 | 说明 |
| --- | --- | --- |
| `accounts` | `acc_{...}` | Studio 登录账号；`role ∈ {admin,user}`；首个 admin 可在 Web 首次初始化时创建，之后由 admin 在设置页管理 |
| `auth_sessions` | token sha256 | web 登录会话 |
| `bridge_sessions` | token sha256 | bridge daemon 会话；指向某个 Bridge |
| `provider_configs` | `p_{uuid8}` | 管理员维护的全局 LLM Provider 配置，带 owner / scope / status / is_default |
| `personas` | `ps_{uuid8}` | 人设；`(account_id, name)` 唯一 |
| `bridges` | `br_{uuid8}` | 主播 PC 上的 daemon；`(account_id, hostname)` 唯一 |
| `inboxes` | `ib_{uuid8}` | 一个 Channel 上的身份；`bridge_id` 指向当前承载的 Bridge（可空） |
| `contacts` | `ct_{uuid8}` | 粉丝；`(inbox_id, peer_platform_id)` 唯一。带 `persona_id`、`reply_provider_config_id`（可 override inbox 默认）、`autoreply_enabled`、`pending_reply` |
| `messages` | 自增 Integer | 历史 + live 一起，`source ∈ {archive, live}`；`(contact_id, external_id)` 唯一 |
| `archives` | `a_{uuid8}` | 上传的 WeFlow JSON；`(account_id, file_hash)` 唯一 |
| `distill_jobs` | `dj_{uuid8}` | 蒸馏任务（pending/running/done/failed） |
| `outbound_messages` | 自增 Integer | Studio→Bridge 出件队列 |
| `llm_logs` | 自增 Integer | LLM 调用记录（purpose='reply' / 'distill'） |

**关键关系：**

```
Account
  ↓ owns
Bridge  (auto-upsert by (account_id, hostname) on handshake)
  ↓ serves
Inbox   (auto-upsert by (account_id, platform, platform_self_id) on handshake)
  ↓ holds
Contact (auto-upsert by (inbox_id, peer_platform_id) on first inbound)
  ↓ has
messages (source=archive|live)
```

Persona 跨 Inbox / Contact 共享。ProviderConfig 由 admin 全局维护，Inbox / Contact 只保存可选 override；普通 user UI 不展示 Provider。

---

### 数据处理流程

#### Onboarding

```
1. web 首次初始化：没有账号时创建首个 admin；admin 在设置页创建普通 user + 全局默认 Provider
2. user 登录 → 建至少一个 Persona
3. 主播 PC: docker compose run --rm bridge \
     --studio-username=alice --studio-password=... \
     --chat-inbox 'base_url=...,username=alice_chat,password=...'
4. bridge daemon → handshake → Studio 自动建 Bridge 行 + Inbox 行（默认 persona = account 第一个 active persona）
5. web 「接管」tab：第一条消息进来后 Contact 自动出现；选人设 / 开 autoreply / 写关系卡；Provider 默认由 admin 全局配置，admin 可 override
6. （可选）「聊天档案」tab：上传 WeFlow JSON 落到目标接管号 → 「蒸馏」tab 跑 fold pipeline 自动产出 Persona + 各 Contact 的 Card
```

#### 用户发消息 → 机器人回复

```
1. counterpart 发消息到 chat sandbox
2. Bridge ChatAdapter poll 到，inbound pump 推到 Studio /api/bridge/incoming
3. studio-api 写 messages(source=live, role=counterpart)；如果 inbox.enabled && contact.autoreply_enabled，置 contact.pending_reply=true
4. studio-worker ReplyScanner 每 2s 扫 pending_reply=true 的 contact，gates 重新校验：
  - inbox.enabled / bridge 在线 / contact.persona_id / 解析 reply_provider = contact.reply_provider_config_id ?? inbox.reply_provider_config_id ?? global default provider
   - 距离 counterpart 最新消息 ≥ QUIET_SECONDS（避免对方还没打完就抢答）
 5. 通过 → 调 LLM → 解析 {"messages": [...]} → 每条 chunk 写一条独立 OutboundMessage(status=pending, send_after=计算打字节奏)
 6. Bridge outbound long-poll 拿到，立即调 adapter.send_text 发送
 7. Bridge ack；Studio 把 outbound 标 delivered
```

#### Reply Prompt 构建规则（studio/reply.py）

- system prompt = 硬编码 `SYSTEM_INSTRUCTION`（拟人 + 红线规则）。
- user message = persona.persona_md + contact.card_md + 最近 N 条历史（自然语言格式：`[mm-dd HH:MM] 我/对方: ...`）。
- 历史包含 source=archive + source=live 的全部消息，按 timestamp 升序；最后一条必须是 counterpart 才会触发回复。
- LLM 必须返回 `{"messages": ["第一条", "第二条"]}`；空数组表示"装作没看见"。
- 每条 LLM 回复 chunk 写一条独立 OutboundMessage，`send_after` 在 Studio 端按 `len(content) / 6 chars/sec` 计算打字节奏，最少 1s 最多 12s；首条多加 1.5s think delay。Bridge 收到即发，不做延迟。

#### Distill Pipeline（studio/distill/）

- 输入：一个 Inbox 下的全部历史消息（archive + live 都行，但通常是 archive）。
- 切 session（30 分钟间隔）→ 切 window（40k token 上限）→ 滚动 fold：每个 window 调一次 LLM，更新 target Persona 的 `persona_md` + 当前 Contact 的 `card_md`（覆盖式）。
- prompt 输出非对称：一段 `===== Operator Persona =====`（主播本人）+ 一段 `===== Contact Card =====`（当前粉丝）。
- 进度回写 `distill_jobs.progress` JSON，前端轮询。
