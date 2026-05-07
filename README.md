# Laborster

Laborster 是一个**通用拟人化私聊接管服务**：让 AI 替主播 / 销售 / 自由职业者，在长期私聊里自动回复，保温关系。

> 命名上保持中性（Persona / Inbox / Contact）以兼容未来扩展。详细产品定位与规则见 [AGENTS.md](./AGENTS.md)。

---

## 系统由三部分组成

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   A · 平台       │ ←→  │   B · Bridge     │ ←→  │   C · Robot      │
│  WeChat/Chat/...│     │  本地 daemon     │     │  云端，人设/卡片  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

| 角色 | 是什么 | 干什么 | 不干什么 |
| --- | --- | --- | --- |
| **A** | 真实聊天平台（微信、飞书、QQ，以及我们的 Chat sandbox） | 收发消息 | — |
| **B** | 跑在主播 PC 上的桥接 daemon | 接管一个平台号、收发消息、模拟打字、缓存离线 | 不调 LLM、不存人设、不蒸馏 |
| **C** | 云端服务（本仓库的 robot） | 人设 / 卡片管理、蒸馏、生成回复、把待发回复排进 outbound 队列 | 不直连任何平台 |

仓库结构里两个独立项目：

- [services/chat/](services/chat/) — Chat sandbox（充当 A 的可控版本，方便 dogfood 整条链路）
- [services/robot/](services/robot/) — Robot (C)。Bridge (B) 单独项目，等 chat 协议跑通后再加 [services/bridge/]

---

## C 的核心概念

| 概念 | 一句话 | 数量 |
| --- | --- | --- |
| **Account** | 登录 Robot 后台的账号（一个人 / 一个团队），CLI 创建 | 1 |
| **Persona** | 人设 — 纯内容资产（markdown），多个 Inbox 可共享同一个 | N / Account |
| **Inbox** | 接管号 — 一个平台号 = 一个 Bridge daemon | N / Account |
| **Contact** | 接管号下的某个对方（粉丝、客户），有自己的关系卡 | N / Inbox |
| **ProviderConfig** | LLM 后端配置池 | N / Account |
| **Archive** | 上传的 WeFlow JSON 历史聊天 | N / Account |
| **DistillJob** | 把一个 Inbox 的历史蒸出 persona + 每个 contact 的卡片 | N / Account |

**关键**：Persona 跟 Inbox **解耦**。一个运营管 5 个微信号 = 5 个 Inbox，可以全部用同一个 persona，也可以一号一人设。粒度：每个 Contact 还能 override 用别的人设；每个 Contact 还能单独开关 autoreply。

---

## 设计原则

**没有"幽灵默认值"。** DB 不存任何 column-level default；所有字段在创建时由调用方显式传入。前端要给"默认选项"，就拉全部可能的值，把视觉默认显式发出来——后端不替用户做选择。

**B 永远不做策略决定。** B 只做平台收发 + 物理拟人（打字延迟）。是否回复、用哪个人设、回什么内容，全部 C 决定。这样 B 多平台扩展时（chat → wechat → feishu）只是写新 adapter，C 不用动。

**C 不直连平台。** C 不再有 ChatAdapter / 各平台 SDK 之类。所有"跟平台说话"经过 B。这样 C 单元化、好部署、好测试。

**Inbox 1:1 Bridge daemon。** 每个接管号生成一个一次性 token，主播复制到本地 Bridge 启动命令里。token 永不过期，丢了或换机器就在后台 revoke + 重发。同一个 Inbox 同一时刻只允许一个 Bridge 在线。

---

## 典型场景

**单主播 alice：1 个人设、1～2 个平台**
- 1 个 Persona（自己）
- 2 个 Inbox（alice@chat、alice@wechat），各跑一个 B
- 后台一键开关 autoreply，按需调

**MCN 运营 op：管 5 个微信号、各自人设**
- 5 个 Persona（lily, emma, sophia, amy, zoe）
- 5 个 Inbox，各一台 PC（微信桌面端单设备登录约束）、各一个 B、各绑各的默认 persona
- 5 个号下的 contacts 互不干扰

**MCN 运营 op2：1 个号上跑多人设**
- 1 个 Inbox
- 多个 Persona
- 部分 contacts override 用别的人设

---

## 怎么跑起来

### Chat sandbox（独立项目）

```bash
cd services/chat
docker compose up -d --build
docker compose exec -T chat-api uv run python -m chat.cli create-account \
  --username demo --password demo123 --display-name 演示账号
```
打开 http://localhost:23456 用 demo / demo123 登录。

### Robot（独立项目）

```bash
cd services/robot
docker compose up -d --build
docker compose exec -T robot-api uv run python -m robot.cli create-account \
  --username alice --password Alice123 --display-name 主播小A
```
打开 http://localhost:23457 用 alice / Alice123 登录。

后台操作顺序（推荐）：
1. 「Provider」tab → 新建一个 LLM Provider
2. 「人设」tab → 新建至少一个人设
3. 「接管号」tab → 新建一个接管号 → **复制 token**（窗口关闭后无法再看到）
4. （未来）在自己 PC 上跑 Bridge daemon，把 token 喂进去
5. 「聊天档案」tab → 上传 WeFlow JSON（指明哪个 wxid 是"我" + 落地到哪个接管号）
6. 「蒸馏」tab → 选 接管号 + 目标人设 + Provider → 开蒸 → 后台会更新 persona 和每个 contact 的卡片

### 账号 CLI

```bash
# Robot 账号
cd services/robot
docker compose exec -T robot-api uv run python -m robot.cli list-accounts
docker compose exec -T robot-api uv run python -m robot.cli reset-password --username alice --password 新密码

# Chat 账号（语法完全同构）
cd services/chat
docker compose exec -T chat-api uv run python -m chat.cli list-accounts
```

⚠️ Docker 起的服务跟本地裸跑的服务是**两份独立的存储**（docker volume vs `services/*/storage/`）。账号互不可见，要在哪边管账号就用对应的命令。

### 本地裸跑（不开 docker）

```bash
# Robot API
cd services/robot/api
ROBOT_STORAGE_DIR=$PWD/../storage uv run uvicorn robot.main:app --host 0.0.0.0 --port 23457

# Robot Worker（蒸馏后台进程）
cd services/robot/api
ROBOT_STORAGE_DIR=$PWD/../storage uv run python -m robot.worker --request-timeout 120

# Robot 前端
cd services/robot/web && npm install && npm run dev

# Chat API / 前端类似
```

---

## 现状

- ✅ Chat sandbox 完整可用
- ✅ Robot 后端：账号 / Persona / Inbox / Contact / Archive / Distill 全部齐
- ✅ Robot 后端：Bridge 协议骨架（handshake / heartbeat / incoming / outbound long-poll / ack）
- ✅ Robot 前端：5 个 tab 的最小 CRUD UI
- ⏳ Bridge daemon (B) 本身：未开始（下一步）
- ⏳ Reply LLM brain（接 B 的 incoming → 写 outbound）：未开始
- ⏳ 真微信 adapter：等 chat sandbox 路径全部跑通之后再加

---

## 持久化

| 项目 | 存储 |
| --- | --- |
| Chat | docker volume `chat-storage`（chat.db + 附件） |
| Robot | bind-mount `services/robot/storage/`（robot.db + uploads/） |

---

## 设计备注

- **没有"角色"这一层概念**：早期把"人设"和"平台身份"塞在同一张表（character），导致 MCN 一上多号就崩。现在 Persona 和 Inbox 严格分开。
- **Robot 不再回看真平台**：早期 Robot 直接调 Chat 接口创建 user / bulk-import / poll，把 Chat 当成"微信模拟器"。这条路下线了，由未来的 Bridge 桥接。这也是"先做 Chat sandbox adapter"路径的合理性来源——Chat sandbox 重新变成**真实平台 A 的简化版**，Bridge 把它和真微信一视同仁。
- **不存默认值**：每条 INSERT 显式赋值。这样将来 schema 演化、字段重命名、字段语义变更，都能在 git diff 里看清——而不是依赖 sqlalchemy 的某行 `default=False` 在某次重启时悄悄改掉行为。
