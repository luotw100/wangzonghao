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

| 概念 | 一句话 | 数量 |
| --- | --- | --- |
| **Account** | Studio 后台的登录账号，CLI 创建 | 1 |
| **Persona** | 人设 — 纯内容资产（markdown），多个 Inbox 可共享 | N / Account |
| **Bridge** | 注册在云端的 daemon 实例，跑在主播 PC 上 | N / Account |
| **Inbox** | 接管号 — 一个 Channel 上的身份；绑给某个 Bridge 来跑 | N / Account |
| **Contact** | 接管号下的某个对方，有自己的关系卡 | N / Inbox |
| **ProviderConfig** | LLM 后端配置池 | N / Account |
| **Archive** | 上传的 WeFlow JSON 历史聊天 | N / Account |
| **DistillJob** | 把一个 Inbox 的历史蒸出 Persona + 各 Contact 卡片 | N / Account |

**关键拆分：**
- *Bridge ↔ Inbox 是 1:N。* 一台主播 PC 一个 Bridge daemon，可以同时服务这台机器上的多个平台账号（微信 + 飞书 + chat 全装在一台 Mac 上常见）。
- *Persona 跟 Inbox 解耦。* 一个运营管 5 个微信号 = 5 个 Inbox（可能挂在 5 台 PC、5 个 Bridge 上）；这 5 个 Inbox 可以全部用同一个 Persona，也可以一号一人设。
- *粒度还可以再细：* 每个 Contact 都能 override 用别的人设；每个 Contact 都能单独开关 autoreply。

---

## 设计原则

**没有"幽灵默认值"。** DB 不存任何 column-level default；所有字段在创建时由调用方显式传入。前端要给"默认选项"，就拉全部可能的值，把视觉默认显式发出来——后端不替用户做选择。

**Bridge 永远不做策略决定。** Bridge 只做平台收发 + 物理拟人（打字延迟）。是否回复、用哪个人设、回什么内容，全部 Studio 决定。多 Channel 扩展时（chat → wechat → feishu）只是写新 adapter，Studio 不用动。

**Studio 不直连任何 Channel。** Studio 不再有任何平台 SDK / 客户端代码。所有"跟平台说话"都经过 Bridge。这样 Studio 干净、好部署、好测试。

**Bridge 用 TOML 配置，凭据本地存。** 跟 Cloudflare Tunnel 同构：Studio UI 控制"哪个 Inbox 绑给哪个 Bridge"；本地 `bridge.toml` 提供每个 Inbox 的平台凭据（chat 密码、飞书 app_secret、微信 hook 路径等）。Studio 永远看不到这些凭据。

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
docker compose exec -T studio-api uv run python -m studio.cli create-account \
  --username demo --password demo123 --display-name 演示
```

Studio 后台在 http://localhost:23457 。

后台操作顺序（推荐）：
1. **Provider** tab → 新建 LLM Provider
2. **人设** tab → 新建至少一个人设
3. **Bridges** tab → 新建一个 Bridge → 复制窗口里显示的整段 TOML（含 token）
4. **接管号** tab → 新建 Inbox → 选 platform、默认人设、绑定到刚才那个 Bridge
5. 在 Bridge 的 TOML 里加这个 Inbox 的 `[[inboxes]]` 配置块（含平台凭据）
6. 启动 Bridge daemon（见下）
7. **聊天档案** tab → 上传 WeFlow JSON（指明哪个 wxid 是"我" + 落地到哪个接管号）
8. **蒸馏** tab → 选 接管号 + 目标人设 + Provider → 开蒸

### 3. Bridge daemon

复制 `services/bridge/bridge.toml.example` 到 `bridge.toml`，填入 Studio UI 给的 token + 各 Inbox 的凭据，然后：

```bash
cd services/bridge
docker compose up --build
```

或本机裸跑（不用 docker）：

```bash
cd services/bridge
BRIDGE_CONFIG=$PWD/bridge.toml uv run python -m bridge.main
```

启动后 Bridge 会：
1. 读 TOML，知道自己应该 serve 哪些 Inbox
2. 跟 Studio 握手，Studio 把 `Inbox.bridge_id` 鉴权 / 绑定到这个 Bridge，并返回它实际可服务的 Inbox 列表
3. 为每个 Inbox 起一个 adapter（chat → 登录 chat 账号；未来 wechat → hook 桌面客户端）
4. 同时跑 heartbeat / inbound / outbound 三个循环——所有 Inbox 共享一条到 Studio 的连接

如果你在 Studio UI 里把某个 Inbox 改绑给别的 Bridge，下次心跳时本机 Bridge 会自动停掉对应 adapter。

---

## 账号 CLI

```bash
# Studio 账号
cd services/studio
docker compose exec -T studio-api uv run python -m studio.cli list-accounts
docker compose exec -T studio-api uv run python -m studio.cli reset-password --username demo --password 新密码

# Chat 账号（语法同构）
cd services/chat
docker compose exec -T chat-api uv run python -m chat.cli list-accounts
```

⚠️ Docker 起的服务跟本地裸跑的服务是**两份独立的存储**（docker volume vs `services/*/storage/`）。账号互不可见，要在哪边管账号就用对应的命令。

---

## 持久化

| 项目 | 存储 |
| --- | --- |
| Chat | docker volume `chat-storage`（chat.db + 附件） |
| Studio | bind-mount `services/studio/storage/`（studio.db + uploads/） |
| Bridge | 无服务端持久化；TOML 本地保存 |

---

## 现状

- ✅ Chat sandbox 完整可用
- ✅ Studio：Account / Persona / Bridge / Inbox / Contact / Archive / Distill 全齐
- ✅ Bridge 协议：handshake / heartbeat（带 inbox 同步）/ incoming / outbound 长轮询 / ack
- ✅ Reply LLM brain：ReplyScanner + 静默期防抖 + chunks 写 outbound
- ✅ Bridge daemon：TOML 配置，Cloudflare-tunnel 风格多 adapter 多路复用
- ✅ Studio 前端：6 个 tab（Bridges / Inboxes / Personas / Providers / Archives / Distill）
- ⏳ 真微信 adapter：等 chat sandbox 路径线上跑稳之后再加
- ⏳ Bridge 本地离线缓存（断网时落盘 incoming，下次连上再推）
- ⏳ Studio Bridge `offline` 自动转换（心跳 N 秒不到自动切 offline）

---

## 设计备注

- **Cloudflare-tunnel 形状的 Bridge：** 一台机器一个 daemon、一个 token、一份 TOML，多 Channel 多路复用。换机器就 revoke 旧 Bridge + 新建一个，所有 Inbox 重新绑过去。
- **Studio 不直连 Channel：** 早期 Studio 直接调 Chat 接口创建 user / bulk-import / poll，把 Chat 当微信模拟器。这条路下线了，由 Bridge 桥接。Chat sandbox 现在跟未来真微信完全对称——Bridge 把它们一视同仁。
- **不存默认值：** 每条 INSERT 显式赋值。schema 演化、字段重命名、字段语义变更都能在 git diff 里看清——而不是依赖 sqlalchemy 的某行 `default=False` 在某次重启时悄悄改掉行为。
- **三个独立项目：** services/chat、services/studio、services/bridge 各有自己的 `pyproject.toml`、`uv.lock`、`Dockerfile`、`compose.yaml`，互不依赖。

# TODO:
- chat/studio: 安全问题,storage可以被直接拉走
- chat/studio: Dockerfile里EXPOSE 23456/23457是否可以去掉?是否可以只监听localhost?以确保更加安全
- 数据库模型: 类似这样的,能不能用枚举之类的?更直观一些:status        = Column(String, nullable=False)              # 'active' | 'disabled'
- studio应该设计两级用户,一类是现在这样的用户(主播、销售...),一类是管理员
- studio里,对普通用户,应该对provider无感,由管理员在后台配置
- 易用性提升