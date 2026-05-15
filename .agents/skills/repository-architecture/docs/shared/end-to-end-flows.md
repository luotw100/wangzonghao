# End-to-End Flows / 端到端流程

## 1. Chat sandbox 手动聊天流程

```text
浏览器打开 Chat web
  → POST /api/auth/login
  → 写入 Chat AuthSession

创建联系人
  → POST /api/contacts
  → 写入 Chat Contact
  → get_or_create_direct_conversation()
  → 写入 Chat Conversation

发送 self/contact 消息
  → POST /api/conversations/{conversation_id}/messages
  → 写入 Chat Message（含 msg_type）
  → 更新 conversation.updated_at

媒体发送
  → POST /api/uploads/presign → 获取 Chat S3 upload URL
  → 客户端 PUT 二进制
  → POST /api/conversations/{id}/messages (msg_type=image/audio/..., content=storage_key)

读取 live messages
  → GET /api/conversations/{conversation_id}/messages?last_id=N&timeout=T
  → 服务端 long-poll 到有新消息或 timeout
```

## 2. Bridge 启动并把 Chat 绑定到 Studio

```text
bridge main 解析 CLI
  → --studio-username / --studio-password / --studio-url / --state-dir
  → N x --chat-inbox base_url=...,username=...,password=...

每个 InboxClaim
  → build_adapter('chat', raw_config)
  → ChatAdapter.login()
  → POST Chat /api/auth/login
  → platform_self_id = Chat account id

BridgeRuntime 加载本地 state
  → 如果存了 token，优先尝试心跳复用
  → 如果 token 过期或有新 inbox 声明，走 handshake
  → POST Studio /api/bridge/handshake
  → Studio 校验账号密码
  → 如果带 machine_id 则按 (account_id, machine_id) 找已有 Bridge，否则生成新的
  → 删除旧 BridgeSession，创建新 token
  → 按 (account_id, platform, platform_self_id) upsert Inbox
  → 返回 token、bridge_id、machine_id、account_id、inbox list、cursor
  → Bridge 保存 machine_id + token 到 state.json

BridgeRuntime 绑定 adapters
  → 用 (platform, platform_self_id) 找到 inbox_id
  → 每个 adapter 启动一个 inbound task
  → 执行 initial catch-up
  → 启动 heartbeat / inbound pump / outbound loop
```

## 3. 对方消息进入 Studio（含 media）

### 纯文本 incoming

```text
对方在 Chat sandbox 发送消息
  → Chat API 写 chat_messages(sender_type='contact', msg_type='text')

ChatAdapter.stream_incoming()
  → refresh conversations
  → 拉取每个 conversation 中 id > last_msg_id 的消息
  → sender_type='contact' 转为 role='counterpart'
  → yield IncomingMessage(peer_id, peer_display_name, platform_msg_id, role, msg_type='text', content, sent_at)

BridgeRuntime._adapter_inbound_loop()
  → 把 (inbox_id, IncomingMessage) 放入 inbound queue

BridgeRuntime._inbound_pump_loop()
  → 取第一条消息
  → 最多等待 0.4s 或凑满 30 条
  → msg_type == 'text'：直接 _to_payload
  → POST Studio /api/bridge/incoming

Studio bridge_incoming()
  → 校验 Inbox 属于当前 Bridge
  → 按 (inbox_id, peer_platform_id) upsert Contact
  → 按 external_id = live:{platform_msg_id} 去重
  → 插入 Message(role='counterpart', msg_type=m.msg_type)
  → 如果 inbox.enabled 且 contact.reply_policy == 'autoreply'，置 contact.pending_reply=True
```

### Media incoming

```text
对方在 Chat sandbox 发送语音
  → Chat API 写 chat_messages(sender_type='contact', msg_type='audio', content='media/acct_xxx/abc.mp3')

ChatAdapter.stream_incoming()
  → yield IncomingMessage(..., msg_type='audio', content='media/acct_xxx/abc.mp3')

BridgeRuntime._push_batch()
  → 检测 msg_type != 'text'
  → adapter.download_media('media/acct_xxx/abc.mp3')
       → GET Chat /api/media/{storage_key} → 跟随 redirect 到 Chat S3 下载二进制
  → studio.presign_upload(filename='media.mp3', mime_type='audio/mp3')
       → POST Studio /api/bridge/media/presign-upload → 返回 storage_key + upload_url
  → PUT 二进制到 upload_url (Studio S3)
  → content 替换为 Studio storage_key（如 media/br_xxx/def456.mp3）
  → msg_type 保持 'audio'
  → POST Studio /api/bridge/incoming

Studio bridge_incoming()
  → 插入 Message(role='counterpart', msg_type='audio', content='media/br_xxx/def456.mp3')
  → 后续流程同文本
```

## 4. Studio 自动回复流程

```text
Studio worker 启动
  → python -m studio.worker --request-timeout 120
  → StudioRuntime.start()
  → 创建 reply ProviderClient
  → DistillScanner 每 5s 扫描
  → ReplyScanner 每 2s 扫描

ReplyScanner
  → list_pending_contact_ids()
  → 对每个未 in-flight 的 contact 创建 task

maybe_reply(contact_id)
  → _decide() 重新校验 gates
  → 静默期未到：保持 pending_reply=True 并返回
  → 永久 skip：清除 pending_reply 并返回
  → 构造 system + user messages
  → ProviderClient.complete_chat()
  → 写 LlmLog(purpose='reply')
  → 解析 JSON {"messages": [...]}
  → 每个 chunk 插入独立 OutboundMessage(msg_type='text', status='pending', send_after=计算打字节奏)
  → 清除 contact.pending_reply
```

`_decide()` 当前 gate：

- Contact 存在且 `status == active`。
- Contact `reply_policy == 'autoreply'`。
- Inbox 存在且 enabled。
- Provider 来自 `contact.reply_provider_config_id or inbox.reply_provider_config_id or global default provider`。
- Provider 存在且有 API key。
- Persona 存在。
- History 非空。
- 最新消息来自 counterpart。
- 最新 counterpart 消息距离当前至少 6 秒。

当前 LLM 只产出纯文本回复，因此 OutboundMessage 的 `msg_type` 始终为 `text`。

## 5. Bridge 发送 outbound（含 media）

### 纯文本 outbound

```text
BridgeRuntime._outbound_loop()
  → GET Studio /api/bridge/outbound?cursor=N&timeout=30
  → 获取当前 Bridge 绑定 Inbox 下的 pending outbound

每个 OutboundMessage (msg_type='text')
  → 按 inbox_id 找 adapter
  → 校验 peer_platform_id
  → 跳过空 content
  → adapter.send_text(peer_platform_id, content)
  → POST Studio /api/bridge/outbound/{id}/ack result=sent
  → Studio 标记 delivered
```

### Media outbound

```text
每个 OutboundMessage (msg_type='audio', content='media/br_xxx/def456.mp3')
  → studio.get_media_url('media/br_xxx/def456.mp3')
       → GET Studio /api/bridge/media/{storage_key} → 302 到 Studio S3 presigned GET URL
  → 下载二进制 (data, mime_type)
  → adapter.upload_and_send_media(peer_id, 'audio', data, filename, mime_type)
       → POST Chat /api/uploads/presign → 获取 Chat S3 upload URL
       → PUT 二进制到 Chat S3
       → adapter.send(peer_id, 'audio', chat_storage_key)
            → POST Chat /api/conversations/{conv_id}/messages (msg_type='audio', content=chat_storage_key)
  → POST Studio /api/bridge/outbound/{id}/ack result=sent
  → Studio 标记 delivered
```

adapter 缺失、peer id 缺失或平台发送异常时，Bridge ack `failed` 并携带 reason。

## 6. Distill pipeline

```text
Studio web distill API
  → POST /api/distill-jobs
  → 写 DistillJob(status='pending')

StudioRuntime DistillScanner 每 5s
  → 找 pending jobs
  → 标记 running
  → run_distill(source_inbox_id, target_persona_id, resolved_provider_config_id)

run_distill()
  → 加载 Inbox、Persona、ProviderConfig
  → 列出 source Inbox 下 active Contacts
  → 每个有消息的 Contact：
       DB Message 转 TextMessage
       按 30 分钟间隔切 session
       pack 到 40k token window
       每个 window：
          用当前 persona/card + window text 构造 fold prompt
          调 LLM
          写 LlmLog(purpose='distill')
          解析 Character Persona + Contact Card 两段
          覆盖 Persona.persona_md 和 Contact.card_md
          更新 progress
  → 成功标 done，异常标 failed
```

当前 distill 是 rolling fold。LLM 输出是完整覆盖版本，不是 diff。
