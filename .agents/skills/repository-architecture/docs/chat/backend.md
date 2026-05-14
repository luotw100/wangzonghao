# Chat Backend / Chat 后端

## 入口文件

- FastAPI app：`services/chat/api/chat/main.py`
- DB：`services/chat/api/chat/db.py`
- Models：`services/chat/api/chat/models.py`
- Schemas：`services/chat/api/chat/schemas.py`
- Auth helpers：`services/chat/api/chat/auth_utils.py`
- CLI：`services/chat/api/chat/cli.py`
- Migration：`services/chat/api/chat/migrate.py`

## DB 初始化

`db.py` 当前行为：

- 读取 `DATABASE_URL`，缺失时报错。
- PostgreSQL 连接池：`pool_size=10, max_overflow=20`。
- 暴露 `Base`、`SessionLocal`、`get_db()`、`utc_now()`。
- `utc_now()` 返回时区感知的 UTC datetime。

`main.py` 通过 FastAPI lifespan 在 startup 时调用 `run_migrations()`（`chat/migrate.py`），自动执行 `alembic upgrade head`。CLI 在入口也调用 `run_migrations()`。

## Models

所有 DateTime 列使用 `timezone=True`（存储为 `timestamptz`）。所有自增主键使用 `BigInteger`。枚举字段使用 `CheckConstraint` 约束。所有 String 列有明确长度限制。

| 表 | Model | 当前作用 |
| --- | --- | --- |
| `chat_accounts` | `Account` | Chat sandbox 登录账号。 |
| `chat_auth_sessions` | `AuthSession` | Bearer session。 |
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

- `Account` 使用 `nickname`（不再是 `display_name`）。
- `Contact` 字段：`username`（平台侧联系人 id，原 `platform_contact_id`）、`nickname`（原 `display_name`）、`remark_name`（用户备注名，nullable）。唯一约束 `(account_id, username)`。
- `Conversation` 唯一约束：`(account_id, contact_id)`。
- Contact / Conversation 通过 `is_deleted`、`deleted_at` 软删除。
- `Message.sender_type` 是 `self | contact`，有 CHECK 约束。
- `Message.source` 是 `live | import`，有 CHECK 约束。
- `Message.msg_type` 是 `text | image | audio | video | file`，有 CHECK 约束。
- Bridge 的 ChatAdapter 会把 `sender_type='contact'` 映射为 Studio 的 `role='counterpart'`。
- Chat models 当前不使用 SQLAlchemy column defaults；创建记录时由应用层显式写入状态、软删除标记和时间戳。
- Chat 代码使用 `chat/enums.py` 中的 StrEnum 表达 status、sender_type、message type、message source 和 command status。

## Auth

`auth_utils.py`：

- `hash_password()`：PBKDF2-HMAC-SHA256。
- `verify_password()`：校验密码。
- `new_session_token()`：生成 bearer token。
- `hash_token()`：SHA256 token，用于 DB 存储。

`main.py` 中 `get_auth_session()`：

1. 要求 `Authorization: Bearer ...`。
2. 对 token hash 后查 `AuthSession`。
3. joined-load account。
4. 拒绝已删除或非 active account。
5. 更新 `last_seen_at`。

## Schemas

`schemas.py` 使用 `StrictModel(extra='forbid')`。

主要 schema：

- Auth：`AccountRead`、`AccountUpdate`（只有 `nickname`）、`LoginRequest`、`LoginResponse`。
- Contacts：`ContactCreate`（`nickname`、`username`、`remark_name`、`avatar_url`）、`ContactUpdate`（只有 `remark_name`；`username` 不可变）、`ContactRead`。
- Conversations：`ConversationRead`。
- Messages：`MessageCreate`、`MessageRead`、`ConversationMessages`、`MessageBulkItem`、`MessageBulkCreate`。
- Media：`UploadPresignRequest`、`UploadPresignResponse`。
- Generic：`StatusResponse`（含可选 `count` 字段）。

## API endpoints

Auth：

- `GET /api/health`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `PATCH /api/auth/me`：更新自己的 nickname（body: `AccountUpdate`）。

Contacts：

- `GET /api/contacts`
- `POST /api/contacts`
- `PUT /api/contacts/{contact_id}`
- `DELETE /api/contacts/{contact_id}`

Conversations：

- `GET /api/conversations`

Messages：

- `POST /api/conversations/{conversation_id}/messages`
- `POST /api/connector/conversations/{conversation_id}/messages`
- `POST /api/conversations/{conversation_id}/messages/bulk`：批量导入，body: `MessageBulkCreate`（list of `MessageBulkItem`），单个事务写入，保留插入顺序。
- `GET /api/conversations/{conversation_id}/messages?last_id=N&timeout=T[&before_id=M&limit=L]`：新增 `before_id` 参数支持向上翻页（拉 `id < before_id` 的旧消息，立即返回不 long-poll）。

Media：

- `POST /api/uploads/presign`：请求 presigned PUT URL，传入 `{filename, mime_type}`，返回 `{storage_key, upload_url}`。
- `GET /api/media/{storage_key}`：校验 auth + 所有权（storage_key 必须以 `media/{account_id}/` 开头），302 重定向到 presigned GET URL（5 分钟有效）。

## 关键 helper

- `new_id(prefix)`：生成 id，格式为 `{prefix}_{uuid4().hex}`（完整 128 bit UUID hex）。
- `normalize_timestamp()`：确保 datetime 带时区信息；naive datetime 补 UTC。
- `get_contact_or_404()` / `get_conversation_or_404()`：按 account 校验归属。
- `get_or_create_direct_conversation()`：恢复软删除会话或创建一对一会话。
- `add_message()`：校验 sender_type 和 msg_type（media 类型要求 content 必须以 `media/{account_id}/` 开头），写 Message，并更新 conversation timestamp。
- `get_messages_after_id()`：按 last id 拉消息（用于 long-poll）。
- `get_messages_before_id()`：按 before_id 倒序拉旧消息（用于向上翻页）。
- `build_messages_payload()`：返回 conversation + messages。

## 媒体消息流程

Chat sandbox 当前支持 5 种消息类型：`text`、`image`、`audio`、`video`、`file`。

### 数据模型

- `msg_type` CHECK 约束合法值：`text | image | audio | video | file`。
- `content` 语义：
  - `msg_type='text'`：content 是纯文本。
  - `msg_type ∈ {image, audio, video, file}`：content 是 S3 storage key，格式为 `media/{account_id}/{uuid4}`。
- 应用层校验：非 text 消息的 content 必须以 `media/{当前用户 account_id}/` 开头。

### 上传流程

1. 前端请求 `POST /api/uploads/presign`（带 `filename` 和 `mime_type`），后端生成 `storage_key`（`media/{account_id}/{uuid4}`）和 presigned PUT URL（15 分钟有效）。
2. 前端直接 PUT 文件到 presigned URL，数据不经过 Chat 后端。
3. 前端用 `POST /api/conversations/{id}/messages`（`msg_type` + `content=storage_key`）发送消息。

### 下载流程

- 前端请求 `GET /api/media/{storage_key}`（或 `GET /api/media/{storage_key}?token=xxx`），后端校验 auth + 所有权后 302 重定向到 presigned GET URL（5 分钟有效）。
- `<img>`、`<audio>`、`<video>` 等标签无法带 Authorization header，因此 `mediaUrl()` 函数在 URL 后附加 `?token=` 查询参数；后端 `_resolve_media_account` 依赖同时支持 Bearer header 和 `?token=` 两种认证方式。
- 文件数据不经过 Chat 后端，浏览器直接从 S3 下载。

### S3 工具

`s3.py` 当前行为：

- 内部 S3 操作（`s3_put`、`s3_get`、`s3_key_exists`、`s3_head_content_type`）使用 `_s3_client`，endpoint 为 `S3_ENDPOINT`（容器内地址）。
- Presigned URL 操作（`s3_presigned_put_url`、`s3_presigned_get_url`）使用 `_s3_public_client`，endpoint 为 `S3_PUBLIC_URL`（浏览器可达地址），因为 presigned URL 的签名绑定 host header。
- `s3_generate_storage_key(account_id)`：生成 `media/{account_id}/{uuid4}` 格式 key。
- `s3_presigned_put_url(key, content_type, expires=15min)`：生成 presigned PUT URL。
- `s3_presigned_get_url(key, filename=None, expires=5min)`：生成 presigned GET URL，可选带 `Content-Disposition`。
- `s3_head_content_type(key)`：获取 S3 对象的 Content-Type。

### 环境变量

- `UPLOAD_MAX_SIZE_MB`：必填，文件大小上限 MB，缺失时启动报错。
- `S3_PUBLIC_URL`：必填，浏览器可达的 S3 地址（如 `https://s3.laborster.com`），用于生成 presigned URL。缺失时启动报错。

## Long polling / 分页拉取

`GET /api/conversations/{conversation_id}/messages?last_id=N&timeout=T[&before_id=M&limit=L]` 当前行为：

**立即返回路径**（不 long-poll）：
- `before_id` 有值：调 `get_messages_before_id(before_id, limit or 100)`，返回 `id < before_id` 的最近 N 条（用于向上翻页）。
- `limit > 0` 且 `last_id == 0` 且 `timeout == 0`：调 `get_messages_after_id(0, limit)` 返回最新 N 条（初始加载有界拉取）。

**Long-poll 路径**：
1. 每轮打开新的 DB session。
2. 查询 `Message.id > last_id`。
3. 有消息立即返回。
4. 到达 `timeout` 返回空 messages。
5. 每轮 sleep 最多 0.2 秒。

`limit` 查询参数范围 `[0, 500]`；`before_id` 最小 1。

Chat web 和 Bridge ChatAdapter 都使用这个 endpoint。

## Connector endpoint

`POST /api/connector/conversations/{conversation_id}/messages` 当前只允许 `sender_type='self'`。当前 ChatAdapter 实际使用普通 message endpoint 并传 `sender_type='self'`，因为它以 Chat 账号身份登录。