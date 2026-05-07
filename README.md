# Laborster

Laborster 是一个**通用拟人化私聊接管服务**：让 AI 替你的主播 / 销售 / 自由职业者，在长期私聊场景里自动回复联系人，保温关系。

> 当前阶段聚焦「主播-粉丝」场景，命名上保持中性（Character / Contact）以兼容未来扩展。详细产品定位与规则参见 [AGENTS.md](./AGENTS.md)。

---

## 仓库结构

仓库已经被拆成两个**完全独立的项目**，共用一个 git 仓库只是为了管理方便。各自有自己的 `pyproject.toml` / `uv.lock` / `Dockerfile` / `compose.yaml` / `nginx.conf` / 前端 web/，互不依赖：

| 项目 | 路径 | 角色 |
| --- | --- | --- |
| **Chat** | [services/chat/](services/chat/) | 通用聊天 Adapter（微信模拟器） |
| **Robot** | [services/robot/](services/robot/) | Character / Contact / Distill / LLM Provider 管理 |

长期目标是 `平台(A) <-> 本地客户端(B) <-> Robot(C)`：微信 / 飞书 / QQ / Chat 都属于 A，未来新开发的本地客户端 B 是唯一桥梁，Robot 不直接连真实平台。**当前 Chat 和 Robot 互不通信**——历史的 robot↔chat 直连接口已经全部下线，等 B 上线时通过 B 重接。

---

## Chat 服务

### 启动

```bash
cd services/chat
CHAT_HTTP_PORT=23458 docker compose up -d --build
```

打开 http://localhost:23458 。

### 账号管理（CLI）

```bash
cd services/chat
CHAT_HTTP_PORT=23458 docker compose exec -T chat-api \
  uv run python -m chat.cli create-account \
  --username demo --password demo123 --display-name 演示账号

CHAT_HTTP_PORT=23458 docker compose exec -T chat-api \
  uv run python -m chat.cli list-accounts

CHAT_HTTP_PORT=23458 docker compose exec -T chat-api \
  uv run python -m chat.cli reset-password --username demo --password 新密码
```

### 本地裸跑

```bash
cd services/chat/api
CHAT_STORAGE_DIR=$PWD/.storage uv run uvicorn chat.main:app --host 0.0.0.0 --port 23456

# 另开终端起前端
cd services/chat/web && npm install && npm run dev
```

⚠️ Docker volume `chat-storage` 与本地 `.storage/` 是完全分开的两份 DB。

---

## Robot 服务

### 启动

```bash
cd services/robot
ROBOT_HTTP_PORT=23457 docker compose up -d --build
```

打开 http://localhost:23457 。

### 账号管理（CLI）

跟 Chat 完全同构：

```bash
cd services/robot
ROBOT_HTTP_PORT=23457 docker compose exec -T robot-api \
  uv run python -m robot.cli create-account \
  --username alice --password Alice123 --display-name 主播小A

ROBOT_HTTP_PORT=23457 docker compose exec -T robot-api \
  uv run python -m robot.cli list-accounts

ROBOT_HTTP_PORT=23457 docker compose exec -T robot-api \
  uv run python -m robot.cli reset-password --username alice --password 新密码
```

### 本地裸跑

```bash
# Robot API
cd services/robot/api
ROBOT_STORAGE_DIR=$PWD/../storage uv run uvicorn robot.main:app --host 0.0.0.0 --port 23457

# Robot Worker（蒸馏后台进程）
cd services/robot/api
ROBOT_STORAGE_DIR=$PWD/../storage uv run python -m robot.worker --request-timeout 120

# Robot 前端
cd services/robot/web && npm install && npm run dev
```

存储目录在 `services/robot/storage/`，docker compose bind-mount，宿主机能直接 `cat storage/robot.db` / 看 `storage/uploads/`。

---

## 数据模型

三个核心原语（在 Robot 里）：

| 原语 | 数量 | 角色 |
| --- | --- | --- |
| **Character** | 1 / Account | 主播本人。包含 Persona（风格 + 生活情境） |
| **Contact** | N / Character | 粉丝。包含 Card（备注名 / 关系档位 / 共享过的事实 等） |
| **ChatArchive** | N / Character | 上传的 WeFlow 聊天记录原文，蒸馏读它 |

**Persona 和 Card 怎么来**：上传历史聊天 → 蒸馏（rolling fold over LLM）→ 自动生成 → 主播校对。

未来 Robot 会把 Persona + Card + 完整对话历史一起喂给 LLM，由 B（本地客户端）把回复转发回真实聊天平台。

---

## 数据库

### Chat: `chat.db`（在 chat docker volume）

| 表 | 说明 |
| --- | --- |
| `chat_accounts` | Chat 登录账号 |
| `chat_auth_sessions` | 登录会话 |
| `chat_contacts` | 每个账号的本地联系人 |
| `chat_conversations` | 一对一会话 |
| `chat_messages` | 实时消息 + bulk-import 历史 |

### Robot: `robot.db`（在 services/robot/storage/）

| 表 | 说明 |
| --- | --- |
| `accounts` | Robot 登录账号（CLI 管理） |
| `auth_sessions` | Bearer token sessions |
| `provider_configs` | LLM Provider |
| `characters` | 主播本人。`wechat_wxid_self` 字段告诉蒸馏哪条消息是 self |
| `contacts` | 粉丝。`(character_id, wechat_wxid)` 唯一 |
| `chat_archives` | 上传的 WeFlow 文件清单（保留原始文件路径，便于重蒸） |
| `messages` | 历史消息（蒸馏的输入） |
| `distill_jobs` | 蒸馏任务（pending/running/done/failed + progress JSON） |
| `llm_logs` | LLM 调用日志（目前只有 distill） |

---

## API 速览

### Chat (`/api/*`)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/login` | username/password 登录，返回 token |
| GET | `/auth/me` | 当前账号 |
| POST | `/auth/logout` | 登出 |
| GET/POST/PUT/DELETE | `/contacts` | 联系人 CRUD |
| GET/POST/PUT/DELETE | `/conversations` | 会话 CRUD |
| GET | `/conversations/{id}/messages?last_id=&timeout=` | 长轮询拉消息 |
| POST | `/conversations/{id}/messages` | 发消息 |
| POST | `/conversations/{id}/messages/bulk` | bulk import（保留历史 timestamp） |

### Robot (`/api/*`)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/auth/login` | username/password 登录，返回 token |
| GET | `/auth/me` | 当前账号 |
| POST | `/auth/logout` | 登出 |
| GET/POST/PUT/DELETE | `/provider-configs` | Provider CRUD |
| GET/POST | `/characters` | Character CRUD |
| GET/PUT/DELETE | `/characters/{id}` | 单个 Character |
| GET | `/characters/{id}/contacts` | 列出该 Character 的粉丝 |
| GET/PUT | `/contacts/{id}` | Contact 读 / 改备注名 / Card |
| GET/POST | `/characters/{id}/chat-archives` | multipart 上传 + 列表 |
| GET/POST | `/characters/{id}/distill-jobs` | 触发蒸馏 + 列表 |
| GET | `/distill-jobs/{id}` | 查蒸馏进度 |

---

## 主播 Onboarding 流程

```
1. CLI 创建一个 Robot 账号
2. 用账号登录 Robot 后台
3. Provider tab → 新建 Provider Config
4. 顶部「新建主播」→ 填名字、self_wxid、绑 Provider
5. 「档案」抽屉 → 上传 WeFlow JSON（指明 self_wxid）
   ↓
   robot-api 解析文件 → 写 robot.db (Contact + messages)
6. 「蒸馏」抽屉 → 「开始蒸馏」→ 等几分钟（worker 后台跑）
7. 「人设」/ 联系人卡片 → 校对自动生成的 Persona / Cards
8. 等 B 上线后接回真实聊天平台
```

---

## 设计备注

- **Robot ↔ 平台之间不再直连**：早期 Robot 直接调 Chat 的接口（创建 chat user / bulk-import / poll），实质把 Chat 当成"微信模拟器"。这条路在重构中已经全部下线，未来由 B 桥接。
- **三原语严格分离**：Character 的人设和 Contact 的卡片是不同生命周期的资产。Robot 现在没有 Session 表，连接器逻辑全部移交 B。
- **蒸馏的产出是非对称的**：一份 Character Persona 全 Character 共享，N 份 Contact Card 各属各的粉丝。fold prompt（[services/robot/api/robot/distill/prompts/fold.md](services/robot/api/robot/distill/prompts/fold.md)）按这个形态写。
- **目前未实现 / 未来再做**：B（本地客户端）、live reply 链路、search-tool（基于 corpus 的事实召回）、Playbook、增量蒸馏、多 adapter（真实微信 / 企微 / 飞书）。
