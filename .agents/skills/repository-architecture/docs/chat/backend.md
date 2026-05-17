# Chat Backend / Chat 后端

## 入口文件

- FastAPI app：`services/chat/api/chat/main.py`
- DB：`services/chat/api/chat/db.py`
- Models：`services/chat/api/chat/models.py`
- Schemas：`services/chat/api/chat/schemas.py`
- Auth helpers：`services/chat/api/chat/auth_utils.py`
- ID helper：`services/chat/api/chat/ids.py`
- Enums：`services/chat/api/chat/enums.py`
- S3：`services/chat/api/chat/s3.py`
- CLI：`services/chat/api/chat/cli.py`
- Migration：`services/chat/api/chat/migrate.py`

## DB 初始化

`db.py` 当前行为：

- 读取 `DATABASE_URL`，缺失时报错。
- PostgreSQL 连接池：`pool_size=10, max_overflow=20`。
- 暴露 `Base`、`SessionLocal`、`get_db()`、`utc_now()`。
- `utc_now()` 返回时区感知的 UTC datetime。

`main.py` 通过 FastAPI lifespan 在 startup 时调用 `run_migrations()`（`chat/migrate.py`，执行 `alembic upgrade head`），并调用 `_get_upload_max_size()` 校验 `UPLOAD_MAX_SIZE_MB`。CLI 在入口也调用 `run_migrations()`。

## Models

所有 DateTime 列使用 `timezone=True`。`Message.id` 用 `BigInteger` 自增，其余主键是 `String`。枚举字段用 `CheckConstraint` 约束。String 列有明确长度限制。

| 表 | Model | 当前作用 |
| --- | --- | --- |
| `chat_accounts` | `Account` | Chat sandbox 登录账号。 |
| `chat_auth_sessions` | `AuthSession` | Bearer session（id 是 token 的 SHA256）。 |
| `chat_contacts` | `Contact` | 某账号下的联系人。 |
| `chat_conversations` | `Conversation` | 某账号与某联系人的一对一会话。 |
| `chat_messages` | `Message` | 会话消息。 |

关系：

```text
Account
  ├─ Contact
  └─ Conversation
       ├─ Contact
       └─ Message
```

当前约束和字段事实：

- `Account`：`username`（unique）、`password_hash`、`nickname`、`status`（CHECK `active | disabled`）。
- `Contact`：`username`（平台侧联系人 id）、`nickname`、`remark_name`（nullable）。唯一约束 `(account_id, username)`。
- `Conversation`：`title`，唯一约束 `(account_id, contact_id)`。
- `Message`：`sender_id`（nullable，FK 到 `chat_contacts.id`；约定 self 消息 `sender_id=None`，contact 消息为该 contact id）、`msg_type`（CHECK `text | image | audio | video | file`）、`content`、`created_at`。
- 没有软删除字段；没有 `sender_type`、`source`、`avatar_url` 字段。
- 索引：`chat_messages` 有复合索引 `ix_chat_messages_conversation_id_id (conversation_id, id)`（长轮询与翻页的热路径）和 `account_id` 索引。
- Chat models 不使用 SQLAlchemy column defaults；创建记录时由应用层显式写入状态和时间戳。
- 状态/类型用 `chat/enums.py` 的 StrEnum：`AccountStatus`、`MessageType`、`CommandStatus`。

## Auth

`auth_utils.py`：

- `hash_password()`：PBKDF2-HMAC-SHA256，210000 轮，编码为 `pbkdf2_sha256$iterations$salt$hash`。
- `verify_password()`：`secrets.compare_digest` 比对。
- `new_session_token()`：`secrets.token_urlsafe(32)`。
- `hash_token()`：SHA256，session 表里存 hash 而非明文 token。

`main.py` 的鉴权统一走 `resolve_auth_session(db, raw_token)`：

1. 缺 token → 401。
2. token hash 后查 `AuthSession`，joined-load account。
3. account 不存在或非 active → 401。
4. 过期 → 删除 session 并 401。
5. 否则把 `expires_at` 滑动续期 24h 并 commit。

`get_auth_session` 依赖从 `Authorization: Bearer` 取 token；`_resolve_media_account` 依赖额外支持 `?token=` query（供无法带 header 的 `<img>/<audio>/<video>` 使用），两者都复用 `resolve_auth_session`。

## Schemas

`schemas.py` 用 `StrictModel(extra='forbid', from_attributes=True)`，并对字符串字段加 `Field` 长度约束（如 `nickname` 1–128/256、`content` 1–100000、`mime_type` 1–128 等），越界返回 422 而非 DB 500。

主要 schema：

- Auth：`AccountRead`、`AccountUpdate`（只有 `nickname`）、`LoginRequest`、`LoginResponse`。
- Contacts：`ContactCreate`（`nickname`、可选 `username`、可选 `remark_name`）、`ContactUpdate`（只有 `remark_name`）、`ContactRead`。
- Conversations：`ConversationRead`（含嵌套 `contact`）。
- Messages：`MessageSend`、`MessageSendRequest`（`messages: list[MessageSend]`，单发与批量导入共用）、`MessageRead`、`ConversationMessages`。
- Media：`UploadPresignRequest`（`filename`、`mime_type`）、`UploadPresignResponse`（`storage_key`、`upload_url`、`fields`）。
- Generic：`StatusResponse`（含可选 `count`）。

## API endpoints

Auth：

- `GET /api/health`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `PATCH /api/auth/me`：更新自己的 nickname。

Contacts：

- `GET /api/contacts`
- `POST /api/contacts`：创建联系人并建立一对一会话；`(account_id, username)` 冲突返回 409。
- `PUT /api/contacts/{contact_id}`：只更新 `remark_name`。

Conversations：

- `GET /api/conversations`

Messages：

- `POST /api/conversations/{conversation_id}/messages`：body `MessageSendRequest`，单事务写入一条或多条，保留顺序；非 text 消息的 `content` 必须以 `media/{account_id}/` 开头。
- `GET /api/conversations/{conversation_id}/messages/before?before_id=M&limit=L`：拉 `id < before_id` 的最近 L 条（倒序查、正序返回），用于向上翻页，立即返回。
- `GET /api/conversations/{conversation_id}/messages/after?last_id=N&limit=L&timeout=T`：拉 `id > last_id`，long-poll。

Media：

- `POST /api/uploads/presign`：传 `{filename, mime_type}`，返回 presigned POST 表单 `{storage_key, upload_url, fields}`。`mime_type` 在 `DISALLOWED_UPLOAD_MIME_TYPES`（`text/html`、`application/xhtml+xml`、`image/svg+xml`）中时返回 400。
- `GET /api/media/{storage_key}`：校验 auth + 所有权（key 必须以 `media/{account_id}/` 开头），302 重定向到 presigned GET URL。

## 关键 helper

- `chat/ids.py` `new_id(prefix)`：`{prefix}_{uuid4().hex}`，main 与 cli 共用。
- `normalize_timestamp()`：naive datetime 补 UTC。
- `get_contact_or_404()` / `get_conversation_or_404()`：按 account 校验归属。
- `get_or_create_direct_conversation()`：复用或创建一对一会话。
- `resolve_auth_session()` / `_bearer_token()`：共享 token 解析逻辑。

## 媒体消息流程

支持 5 种消息类型：`text`、`image`、`audio`、`video`、`file`。

### 数据模型

- `content` 语义：`text` 时是纯文本；`image/audio/video/file` 时是 S3 storage key（`media/{account_id}/{uuid4}`）。
- 应用层校验：非 text 消息的 content 必须以 `media/{当前 account_id}/` 开头。

### 上传流程

1. 前端 `POST /api/uploads/presign`。后端拒绝危险 `mime_type`，生成 `storage_key`，用 `s3_presigned_post` 生成 presigned POST（绑定 `Content-Type`，并用 `content-length-range` 把对象大小上限设为 `UPLOAD_MAX_SIZE_MB`，由 S3 在服务端强制）。
2. 前端用 `FormData`（先 append `fields`，再 append `file`）POST 到 `upload_url`，数据不经过 Chat 后端。
3. 前端用 `POST .../messages`（`msg_type` + `content=storage_key`）发送消息。

### 下载流程

- `GET /api/media/{storage_key}`（可带 `?token=`）校验 auth + 所有权后 302 到 presigned GET URL。
- serve_media 查该 storage_key 对应消息的 `msg_type`：只有 `image/audio/video` 内联（不带 Content-Disposition）；其余类型（含尚未关联消息的 blob）强制 `Content-Disposition: attachment`，避免内联渲染导致存储型 XSS。

### S3 工具（`s3.py`）

- 内部 client 用 `S3_ENDPOINT`，presigned 操作用 `S3_PUBLIC_URL`（presigned 签名绑定 host）。
- `s3_generate_storage_key(account_id)`：生成 `media/{account_id}/{uuid4}`。
- `s3_presigned_post(key, content_type, max_bytes, expires=15min)`：presigned POST，含 `Content-Type` 条件和 `content-length-range`。
- `s3_presigned_get_url(key, force_attachment=False, expires=5min)`：presigned GET，`force_attachment` 时设 `ResponseContentDisposition=attachment`。

### 环境变量

- `UPLOAD_MAX_SIZE_MB`：必填，正整数；作为 presigned POST 的 `content-length-range` 上限由 S3 强制。
- `S3_ENDPOINT`、`S3_PUBLIC_URL`、`S3_ACCESS_KEY`、`S3_SECRET_KEY`、`S3_BUCKET`：必填，缺失启动报错。

## Long polling / 分页拉取

`GET .../messages/after` 是同步 `def` endpoint，由 FastAPI 在 threadpool 执行，阻塞式 DB 查询和 `time.sleep` 不会卡事件循环。当前行为：

1. 进入时开一个 `SessionLocal`，先 `get_conversation_or_404` 取一次 conversation。
2. 循环：`db.expire_all()` 后查 `Message.id > last_id`（按 id 升序，可选 `limit`）。
3. 有消息或已到 `timeout` → 返回。
4. 否则 `time.sleep(max(0, min(0.2, timeout - elapsed)))` 后重试。
5. 退出时关闭 session。

`/messages/before` 立即返回，不 long-poll。`limit` 范围 `[0, 500]`（before 为 `[1, 500]`，默认 100），`before_id` 最小 1。

Chat web 和 Bridge ChatAdapter 都使用这两个 endpoint。ChatAdapter 以 Chat 账号身份登录，发消息走普通 messages endpoint 并把 self 消息的 `sender_id` 置空。
