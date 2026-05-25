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

仓库结构里**两个独立项目**：

- [services/studio/](services/studio/) — 云端 server（Studio 控制台 + Chat sandbox 子包 + admin 面板 + worker + 两个 React 前端），同一份 PG 三 schema 隔离
- [bridge/cli/](bridge/cli/) — Bridge daemon（主播 PC 上的 Python REPL）

Chat sandbox 在代码上是 `services/studio/api/chat/` 子包，路由挂在 `/api/chat/*` 下；与 Studio 同进程跑，但仍只能被 Bridge HTTP 触达。

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

### 1. 起整套 server（单 compose）

```bash
cp infra/.env.example infra/.env  # 填 POSTGRES_*、MINIO_*、S3_PUBLIC_URL 等
scripts/up-all.sh scripts/.env.debug.json   # 实例配置，含 COMPOSE_PROJECT_NAME / CF_TUNNEL_TOKEN
scripts/seed_dev.py scripts/.env.debug.json # 建首个 Provider + 账号
```

- Studio 后台和 Chat 沙箱共域：`https://<your-domain>/studio` 和 `https://<your-domain>/chat`，共用一个登录。
- Admin 面板独立部署在另一个域 / 子路径，Cloudflare Access 在边缘做身份校验。

后台操作顺序（推荐）：
1. admin（通过 admin-web）→ 维护 Provider 池、创建普通 user
2. 普通 user 登录 → **人设** 新建至少一个人设
3. 在主播 PC 上启动 Bridge daemon（见下）—— Bridge / Inbox 自动出现在 Studio
4. **接管** → 选粉丝、设人设 / 开 autoreply、写关系卡；首条 Conversation 默认绑定 pick_first_provider
5. Bridge 积累一定消息后可创建 distill job 自动产出 Persona + Card

### 2. Bridge daemon

```bash
cd bridge/cli
uv run laborster-bridge --state ~/.laborster-bridge
# REPL 里：
#   /login <username>          (用 Studio 账号密码握手，会拿到 session token)
#   /channel add chat          (复用 studio token 自动建 chat channel，无需再输密码)
```

默认连云端 `https://studio.laborster.com`；本地联调时在 REPL 里 `/studio set http://host.docker.internal:23456` 覆盖。

启动后 Bridge 会：
1. 调 `/api/bridge/handshake` 用账号密码 + machine_id 换 session token；写进 `~/.laborster-bridge/<account_id>/state.db`（0600）。
2. `/channel add chat` 自动把当前 studio token 注入 chat channel。chat adapter 调用 `${STUDIO}/api/chat/*` 走同一份 token。
3. 之后 heartbeat / inbound / outbound 都用 session token；24h 滑动续期，401 才再输密码。

撤掉一个 Bridge：在 Studio「设备」tab 删它对应的行；daemon 下次调用会被 401。

---

## 账号管理

账号统一在 `auth.accounts`（PostgreSQL `auth` schema），由 admin 面板通过 admin-api 维护：

- admin：通过 admin-web（Cloudflare Access 鉴权）创建 / 列出 / 停用 / 重置账号密码。
- 普通 user：登录后在 Studio「设置」里改自己的密码。
- Chat sandbox **没有独立账号**，共用 `auth.accounts`：dogfood 时一个 user 既是 Studio 操作者也是 chat 沙箱身份。

---

## 持久化

| 项目 | 存储 |
| --- | --- |
| Server | 单 docker volume `pgdata`（PostgreSQL，三 schema：auth / studio / chat）+ MinIO bucket `${S3_BUCKET}` |
| Bridge | 状态目录 `<--state>/<account_id>/state.db`（sqlite，仅 token / machine_id / channel credentials / 消息中转表） |

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
- **两个独立项目：** `services/studio/`（云端 server，单进程挂 studio + chat + admin）和 `bridge/cli/`（主播 daemon）。Chat sandbox 是 server 内的子包，靠 PostgreSQL schema (`auth` / `studio` / `chat`) 和 Python 包纪律隔离；Bridge 仍以 HTTP 触达，Channel 边界没变。

## TODO

- ✅ chat/studio：不再通过 Nginx 或 FastAPI 直接暴露 storage。
- ✅ chat/studio：API Dockerfile 去掉 `EXPOSE`；容器内仍监听 `0.0.0.0` 供 Nginx 在 compose network 内访问。
- ✅ chat/studio：状态 / 类型字段改为集中 `StrEnum`。
- ✅ studio：Account 分 admin / user，两级用户。
- ✅ studio：Provider 由 admin 在设置页统一配置，普通 user UI 无感。
- ✅ studio：账号创建、列表、停用/启用、重置密码进入 Web 设置页；首次 admin 可在登录页初始化。
- ⏳ 迁移 PostgreSQL。