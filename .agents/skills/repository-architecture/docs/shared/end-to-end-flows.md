# End-to-End Flows / 端到端流程

## 1. Chat sandbox 手动聊天流程

```text
浏览器打开 Chat web
  → POST /api/auth/login（Studio 的 auth_sessions）
  → 写入 AuthSession

创建联系人
  → POST /api/chat/contacts
  → 写入 Chat Contact
  → get_or_create_direct_conversation()
  → 写入 Chat Conversation

发送 self/contact 消息
  → POST /api/chat/conversations/{conversation_id}/messages
  → 写入 Chat Message（含 msg_type）
  → 更新 conversation.updated_at
  → pg_notify 触发 long-poll 唤醒

媒体发送
  → POST /api/chat/uploads/presign → 获取 Chat S3 upload URL
  → 客户端 PUT 二进制
  → POST /api/chat/conversations/{id}/messages (msg_type=image/audio/..., content=storage_key)

读取 live messages
  → GET /api/chat/conversations/{conversation_id}/messages/after?last_id=N&limit=L&timeout=T
  → 服务端 long-poll（LISTEN/NOTIFY 驱动）到有新消息或 timeout
```

## 2. Bridge 启动并把 Chat 绑定到 Studio

```text
REPL 启动（--state / /state 指定状态目录）
  → 无 studio_token → /login：用户输 Studio 账号密码
      → POST Studio /api/bridge/handshake（唯一用 Studio 密码的调用）
      → Studio 校验账号密码，按 (account_id, machine_id) 找/建 Bridge
      → create_auth_session 签发 account session token（与 web 共用 auth_sessions）
      → 返回 token、account_id、username、machine_id
      → 后续 /api/bridge/* 带 Bearer token + X-Machine-Id 头
      → 写入本地 SQLite kv 表（studio_token、machine_id）；Studio 密码用完即弃，绝不落盘
  → 有 studio_token → 直接复用，不需密码、不重新 handshake

每个 Channel（chat 平台账号）：/channel add 时
  → ChatAdapter LoginFlow 完成（chat 复用 Studio session token）
  → ChatAdapter.resolve_self() → GET /api/auth/me
  → platform_self_id = Chat account.id

ChannelWorker._connect()
  → factory.make_provider() → 构建 credential provider（读取 store.kv 中的 studio_token）
  → factory.build() → 创建 adapter 实例
  → adapter.platform_self_id / platform_self_display_name
  → POST Studio /api/bridge/inboxes [{platform, platform_self_id, display_name}]
  → Studio upsert/绑定 Inbox

BridgeRuntime 绑定 adapters
  → 用 (platform, platform_self_id) 找到 inbox_id
  → 每个 adapter 启动一个 ChannelWorker
  → 启动 heartbeat / upload pump / outbound loop / takeover watcher
```

## 3. 对方消息进入 Studio

```text
对方在 Chat sandbox 发送消息
  → Chat API 写 chat.messages

ChatAdapter.fetch_new(conv_id, since)
  → GET /api/chat/conversations/{id}/messages/after
  → 返回新消息列表

UploadActor（每 1s 运行）
  → 读取 atomic takeovers 快照（frozenset of "inbox_id|conv_id"）
  → store.get_unsent() 取 takeovers 集合内的未发送消息
  → studio.push_incoming(messages) 批量推到 Studio
  → store.mark_sent(ids)

Studio bridge_incoming()
  → 校验 Inbox 属于当前 Bridge
  → 按 (inbox_id, platform_conversation_id) 找或创建 Conversation（不存在则建 kind='unknown' 占位行）
  → 按 (conversation_id, client_id) 去重
  → 插入 Message(sender_id=对方平台ID, msg_type=m.msg_type)
  → 如果 conversation.takeover && conversation.reply_policy == 'autoreply'，后续由 ReplyScanner 处理
```

## 4. Studio 自动回复流程

```text
Studio worker 启动
  → python -m studio.worker --request-timeout 120
  → StudioRuntime.start()
  → DistillScanner 每 5s 扫描
  → ReplyScanner 每 2s 扫描

ReplyScanner
  → list_pending_conversation_ids()
  → 对每个未 in-flight 的 conversation 创建 asyncio.Task

maybe_reply(conversation_id)
  → _decide() 8-gate 校验
  → gate 不通过（静默期未到等）→ 更新 last_reply_round_at 并返回
  → 构造 system + user messages
  → ProviderClient.complete_chat()（走 Conversation.provider_id）
  → 写 LlmLog(purpose='reply')
  → 解析 JSON {"messages": [...]}
  → 每个 chunk 插入独立 OutboundMessage(msg_type='text', status='pending', send_after=计算打字节奏)
  → 更新 conversation.last_reply_round_at
```

`_decide()` 当前 8-gate：

1. Conversation 存在且 `status == 'active'`。
2. Conversation `reply_policy == 'autoreply'`。
3. Inbox 存在。
4. Provider 有 API key。
5. Persona 存在。
6. History 非空。
7. 最新消息来自 counterpart（sender_id IS NOT NULL）。
8. 最新 counterpart 消息距离当前 ≥ QUIET_SECONDS（6 秒）。

## 5. Bridge 发送 outbound

```text
OutboundActor（长轮询）
  → GET Studio /api/bridge/outbound?timeout=30
  → 获取当前 Bridge 绑定 Inbox 下的 pending outbound（send_after 已到，按 id ASC）

每个 OutboundMessage
  → 按 inbox_id 找 ChannelWorker
  → worker.send_outbound(item)
  → adapter.send(conv_id, OutboundPayload)
  → 发送成功：Bridge 下次 inbound 推送 from_self 消息
  → Studio bridge_incoming() 收到 sender_id=NULL 的 from_self 消息
  → Studio 按 (conversation_id, content) 匹配 PENDING outbound 自动标记 delivered
```

无显式 ack 端点。Outbound 状态流转：`pending → delivered`（from_self inbound 自动匹配）或 `pending → canceled`（Inbox/Bridge 删除时批量标记）。

## 6. Distill pipeline

```text
Studio web distill API
  → POST /api/distill-jobs
  → 写 DistillJob(status='pending')

StudioRuntime DistillScanner 每 5s
  → 找 pending jobs（排除 busy conversation_ids 和 busy target_persona_ids）
  → 标记 running
  → run_distill(job)

run_distill()
  → 加载 Account（取 distill_provider_id）、Persona、ProviderConfig
  → 列出 DistillJob.conversation_ids 中的 active Conversations
  → 每个有消息的 Conversation：
       DB Message 转 TextMessage
       按 30 分钟间隔切 session
       pack 到 40k token window
       每个 window：
          用当前 persona_md/card_md + window text 构造 fold prompt
          调 LLM（走 Account.distill_provider_id）
          写 LlmLog(purpose='distill')
          解析 ===== Character Persona ===== + ===== Contact Card ===== 两段
          覆盖 Persona.persona_md 和 Conversation.card_md
          更新 progress JSONB
  → 成功标 done，异常标 failed
```

当前 distill 是 rolling fold。LLM 输出是完整覆盖版本，不是 diff。