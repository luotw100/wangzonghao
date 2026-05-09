# Chat Backend / Chat 后端

## 入口文件

- FastAPI app：`services/chat/api/chat/main.py`
- DB：`services/chat/api/chat/db.py`
- Models：`services/chat/api/chat/models.py`
- Schemas：`services/chat/api/chat/schemas.py`
- Auth helpers：`services/chat/api/chat/auth_utils.py`
- CLI：`services/chat/api/chat/cli.py`

## DB 初始化

`db.py` 当前行为：

- 读取 `CHAT_STORAGE_DIR`，缺失时报错。
- 创建 `STORAGE_DIR`。
- SQLite 文件是 `${CHAT_STORAGE_DIR}/chat.db`。
- 暴露 `Base`、`SessionLocal`、`get_db()`、`ensure_database()`、`utc_now()`。

`main.py` import 时调用 `ensure_database()`。当前 API 不再把 storage 目录直接 mount 成静态路径。

## Models

| 表 | Model | 当前作用 |
| --- | --- | --- |
| `chat_accounts` | `Account` | Chat sandbox 登录账号。 |
| `chat_auth_sessions` | `AuthSession` | Bearer session。 |
| `chat_contacts` | `Contact` | 某账号下的联系人。 |
| `chat_conversations` | `Conversation` | 某账号与某联系人的一对一会话。 |
| `chat_messages` | `Message` | 会话消息。 |
| `chat_import_batches` | `ImportBatch` | 批量导入记录。 |

关系：

```text
Account
  ├─ Contact
  └─ Conversation
       ├─ Contact
       └─ Message
```

当前约束和字段事实：

- `Contact` 唯一约束：`(account_id, platform_contact_id)`。
- `Conversation` 唯一约束：`(account_id, contact_id)`。
- Contact / Conversation 通过 `is_deleted`、`deleted_at` 软删除。
- `Message.sender_type` 是 `self | contact`。
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

- Auth：`AccountRead`、`LoginRequest`、`LoginResponse`。
- Contacts：`ContactCreate`、`ContactUpdate`、`ContactRead`。
- Conversations：`ConversationCreate`、`ConversationUpdate`、`ConversationRead`。
- Messages/import：`MessageCreate`、`BulkMessageItem`、`BulkMessageImport`、`MessageRead`、`ConversationMessages`。
- Generic：`StatusResponse`。

## API endpoints

Auth：

- `GET /api/health`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

Contacts：

- `GET /api/contacts`
- `POST /api/contacts`
- `PUT /api/contacts/{contact_id}`
- `DELETE /api/contacts/{contact_id}`

Conversations：

- `GET /api/conversations`
- `POST /api/conversations`
- `GET /api/conversations/{conversation_id}`
- `PUT /api/conversations/{conversation_id}`
- `DELETE /api/conversations/{conversation_id}`

Messages：

- `POST /api/conversations/{conversation_id}/messages`
- `POST /api/connector/conversations/{conversation_id}/messages`
- `POST /api/conversations/{conversation_id}/messages/bulk`
- `GET /api/conversations/{conversation_id}/messages?last_id=N&timeout=T`

## 关键 helper

- `new_id(prefix, size)`：生成 id。
- `normalize_timestamp()`：去掉 timezone。
- `get_contact_or_404()` / `get_conversation_or_404()`：按 account 校验归属。
- `get_or_create_direct_conversation()`：恢复软删除会话或创建一对一会话。
- `add_message()`：校验 sender_type，写 Message，并更新 conversation timestamp。
- `get_messages_after_id()`：按 last id 拉消息。
- `build_messages_payload()`：返回 conversation + messages。

## Long polling

`GET /api/conversations/{conversation_id}/messages` 当前行为：

1. 每轮打开新的 DB session。
2. 查询 `Message.id > last_id`。
3. 有消息立即返回。
4. 到达 `timeout` 返回空 messages。
5. 每轮 sleep 最多 0.2 秒。

Chat web 和 Bridge ChatAdapter 都使用这个 endpoint。

## Connector endpoint

`POST /api/connector/conversations/{conversation_id}/messages` 当前只允许 `sender_type='self'`。当前 ChatAdapter 实际使用普通 message endpoint 并传 `sender_type='self'`，因为它以 Chat 账号身份登录。
