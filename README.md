# Laborster

Laborster 是一个**通用拟人化私聊接管服务**：让 AI 替主播 / 销售 / 自由职业者，在长期私聊里自动回复，保温关系。

> 详细产品定位与规则见 [AGENTS.md](./AGENTS.md)。

---

## 系统由三部分组成

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Channel        │ ←→  │   Bridge         │ ←→  │   Studio         │
│  WeChat/Chat/... │     │  本地 daemon     │     │  云端，人设 / 卡片 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

| 角色 | 是什么 | 干什么 | 不干什么 |
| --- | --- | --- | --- |
| **Channel** | 真实聊天平台（微信、飞书、QQ、我们的 Chat sandbox） | 收发消息 | — |
| **Bridge** | 跑在主播 PC 上的 daemon | 接管这台机器上的所有平台登录、收发消息、模拟打字、缓存离线 | 不调 LLM、不存人设、不蒸馏 |
| **Studio** | 云端服务（本仓库） | 人设 / 卡片管理、蒸馏、生成回复、把待发回复排进 outbound 队列 | 不直连任何 Channel |

仓库结构里**三个独立项目**：

- [services/chat/](services/chat/) — Chat sandbox，作为 dogfood 用的可控 Channel
- [services/studio/](services/studio/) — Studio
- [services/bridge/](services/bridge/) — Bridge daemon

---

## Studio 的核心概念

UI 上你只直接接触 **接管 / 人设 / 设备 / 设置** 这几个区域。Inbox 和 Bridge 仍然存在于 DB / 协议里，但都是 daemon 第一次握手时自动出现，不需要在 UI 上手工建。Provider 由管理员在设置页统一维护，普通用户无感。

| 概念 | 一句话 | 数量 |
| --- | --- | --- |
| **Account** | Studio 后台登录账号，分 admin / user；首个 admin 可在 Web 首次初始化时创建 | N |
| **Persona** | 人设 — 纯内容资产（markdown），多个 Contact / Inbox 可共享 | N / Account |
| **ProviderConfig** | 管理员维护的全局 LLM 后端配置池 | N / Studio |
| **DistillJob** | 把一个接管号的历史蒸出 Persona + 各 Contact 卡片 | N / Account |
| **Inbox**（自动） | 一个 Channel 上的身份（一个 wxid / chat user）；bridge 登入时自动出现 | N / Account |
| **Bridge**（自动） | 主播 PC 上的 daemon；按 (account, hostname) 自动注册 | N / Account |
| **Contact** | 接管号下的某个粉丝；UI 上叫"接管"，每个独立设 Persona / autoreply，admin 可设 Provider override | N / Inbox |

**关键拆分：**
- *Contact 是接管单元。* 每个 Contact 独立选 Persona、独立开关 autoreply。Provider 默认走全局默认；admin 可给 Inbox / Contact 单独 override。
- *Inbox 提供默认值。* 新粉丝进入时继承 Inbox 的默认 Persona / Provider override；之后两边各改各的。
- *Bridge ↔ Inbox 是 1:N。* 一台主播 PC 一个 Bridge daemon，可以同时服务这台机器上的多个平台账号。

---

## 设计原则

**没有"幽灵默认值"。** DB 不存任何 column-level default；所有字段在创建时由调用方显式传入。前端要给"默认选项"，就拉全部可能的值，把视觉默认显式发出来——后端不替用户做选择。

**Bridge 永远不做策略决定。** Bridge 只做平台收发 + 物理拟人（打字延迟）。是否回复、用哪个人设、回什么内容，全部 Studio 决定。多 Channel 扩展时（chat → wechat → feishu）只是写新 adapter，Studio 不用动。

**Studio 不直连任何 Channel。** Studio 不再有任何平台 SDK / 客户端代码。所有"跟平台说话"都经过 Bridge。这样 Studio 干净、好部署、好测试。

**Bridge 不持有长期凭据。** Bridge daemon 没有任何持久 token；每次起来都用主播的 Studio 账号密码 + hostname 重新换 session token。Bridge 行按 (account, hostname) 自动 upsert，没有"先在 UI 建 Bridge → 拷 token"的流程。平台凭据（chat 用户名密码、未来微信 hook 路径等）通过 CLI 参数传入，留在主播本机，永远不会上传 Studio。

---

## 典型场景

**单主播 alice：1 人设、2 个平台**
- 1 Persona, 1 Bridge（alice 自己的 Mac）, 2 Inbox（alice@chat、alice@wechat）

**MCN 运营 op：管 5 个微信号、各自人设**
- 5 Persona, 5 Bridge（5 台 PC，因为微信桌面端单设备登录约束）, 5 Inbox

**MCN 运营 op2：一台机器上同时挂 wechat + feishu，但只有一个人设**
- 1 Persona, 1 Bridge（一台机器）, 2 Inbox（wechat + feishu，绑同一个 Bridge 同一个 persona）

---

## 怎么跑起来

### 1. Chat sandbox（dogfood Channel）

```bash
cd services/chat
docker compose up -d --build
docker compose exec -T chat-api uv run python -m chat.cli create-account \
  --username alice --password Alice123 --display-name 主播alice
```

Chat 后台在 http://localhost:23456 。

### 2. Studio

```bash
cd services/studio
docker compose up -d --build
```

Studio 后台在 http://localhost:23457 。

第一次打开 Studio 时，如果数据库里没有任何账号，登录页会进入初始化模式：填写用户名、密码和显示名，直接创建首个 `admin` 并登录。之后账号都在 Web「设置」里管理，不需要再用命令行操作 Studio 账号。

后台操作顺序（推荐）：
1. admin 在 **设置** → 新建全局默认 Provider、创建普通 user
2. 普通 user 登录后在 **人设** → 新建至少一个人设
3. 在主播 PC 上启动 Bridge daemon（见下）—— Bridge / Inbox 会自动出现在 Studio
4. **接管** → 选粉丝、设人设 / 开 autoreply、写关系卡
5. 在「接管」tab 配置 Contact 的人设和 autoreply；Bridge 积累一定消息后可创建 distill job 自动产出 Persona + Card
6. 创建蒸馏任务，未显式指定 Provider 时使用全局默认 Provider

### 3. Bridge daemon

直接拿主播的 Studio 账号密码 + 该机器要登的 chat 账号起来：

```bash
cd services/bridge
docker compose run --rm bridge \
  --studio-username=demo --studio-password=demo123 \
  --studio-url=http://host.docker.internal:23457 \
  --chat-inbox 'base_url=http://host.docker.internal:23456,username=alice,password=Alice123'
```

- 默认连云端 `https://studio.laborster.com`，本地联调用 `--studio-url` 覆盖。
- 想让一个 Bridge 同时挂多个 chat 账号：再加一行 `--chat-inbox '...'`。

启动后 Bridge 会：
1. 用账号密码 + hostname 调 `/api/bridge/handshake`，按 (account, hostname) upsert Bridge 行，发回一次性 session token。
2. 报告它登入的每个 chat 账号，Studio 自动 upsert Inbox。
3. 之后所有 heartbeat / inbound / outbound 都用 session token；bridge 重启 = 重新 handshake = 新 token。

撤掉一个 Bridge：在 web 「Bridges」tab 点 revoke，daemon 下次调用会被 401，需要重启才能复活（拿新 token）。

---

## 账号管理

Studio 账号管理主路径是 Web「设置」：

- 首次初始化：没有任何账号时，在登录页创建首个 admin。
- admin：创建普通用户、列出账号、停用/启用账号、重置任意账号密码。
- 普通 user：在设置页修改自己的密码。

CLI 仅保留为运维救援入口；Chat sandbox 账号目前仍用 CLI：

```bash
cd services/chat
docker compose exec -T chat-api uv run python -m chat.cli list-accounts
```

⚠️ Docker 起的服务跟本地裸跑的服务是**两份独立的存储**（docker volume vs `services/*/storage/`）。账号互不可见，要在哪边管账号就用对应的命令。

---

## 持久化

| 项目 | 存储 |
| --- | --- |
| Chat | docker volume `chat-storage`（chat.db + 附件） |
| Studio | docker volume `studio-storage`（studio.db + uploads/） |
| Bridge | 无任何持久化；CLI 参数即全部状态 |

---

## 现状

- ✅ Chat sandbox 完整可用
- ✅ Studio：Account / Persona / Inbox（自动）/ Bridge（自动）/ Contact / Distill 全齐
- ✅ Bridge 协议：账号密码握手 / heartbeat（带 inbox 同步）/ incoming / outbound 长轮询 / ack
- ✅ Reply LLM brain：ReplyScanner + 静默期防抖 + chunks 写 outbound + per-contact provider override
- ✅ Bridge daemon：零配置 CLI，多 adapter 共享一条到 Studio 的连接
- ✅ Studio 前端：接管 / 设备 / 人设 / 设置，内置 admin 账号管理和 Provider 管理
- ⏳ 真微信 adapter：等 chat sandbox 路径线上跑稳之后再加
- ⏳ Bridge 本地离线缓存（断网时落盘 incoming，下次连上再推）
- ⏳ Studio Bridge `offline` 自动转换（心跳 N 秒不到自动切 offline）

---

## 设计备注

- **Bridge 自注册：** 没有"先在 UI 建 Bridge → 拷 token"。每次握手就是一次 Studio 账号登录，按 (account, hostname) upsert Bridge 行。daemon 连续重启拿新 token，状态最少。
- **Studio 不直连 Channel：** 早期 Studio 直接调 Chat 接口创建 user / bulk-import / poll，把 Chat 当微信模拟器。这条路下线了，由 Bridge 桥接。Chat sandbox 现在跟未来真微信完全对称——Bridge 把它们一视同仁。
- **不存默认值：** 每条 INSERT 显式赋值。schema 演化、字段重命名、字段语义变更都能在 git diff 里看清——而不是依赖 sqlalchemy 的某行 `default=False` 在某次重启时悄悄改掉行为。
- **三个独立项目：** services/chat、services/studio、services/bridge 各有自己的 `pyproject.toml`、`uv.lock`、`Dockerfile`、`compose.yaml`，互不依赖。

## TODO

- ✅ chat/studio：不再通过 Nginx 或 FastAPI 直接暴露 storage。
- ✅ chat/studio：API Dockerfile 去掉 `EXPOSE`；容器内仍监听 `0.0.0.0` 供 Nginx 在 compose network 内访问。
- ✅ chat/studio：状态 / 类型字段改为集中 `StrEnum`。
- ✅ studio：Account 分 admin / user，两级用户。
- ✅ studio：Provider 由 admin 在设置页统一配置，普通 user UI 无感。
- ✅ studio：账号创建、列表、停用/启用、重置密码进入 Web 设置页；首次 admin 可在登录页初始化。
- ⏳ 迁移 PostgreSQL。