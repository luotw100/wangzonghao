# Studio Worker, Reply Brain, Distill / Worker、回复脑、蒸馏

## Worker 进程

`studio/worker.py` 是 worker CLI。

- `parse_args()` 要求显式传 `--request-timeout`。
- `run_worker()` 启动 `StudioRuntime` 后等待。
- Compose 当前命令：`uv run python -m studio.worker --request-timeout 120`。

## StudioRuntime

`studio/runtime.py` 当前同时运行三个 scanner loop。

### `RuntimeOptions`

- `request_timeout: float`：LLM HTTP request timeout。

### 生命周期

`start()`：

- 创建 reply 用的 `ProviderClient`。
- 启动 `_distill_scanner_loop()`。
- 启动 `_reply_scanner_loop()`。
- 启动 `_bridge_offline_scanner_loop()`。

`stop()`：

- cancel scanner tasks。
- cancel in-flight distill/reply tasks。
- 清空 task maps。
- 关闭 reply ProviderClient。

### DistillScanner

每 5 秒：

1. 查询所有 `status == RUNNING` 的 job，聚合出 `busy_conversations`（所有 running job 的 `conversation_ids` 并集）和 `busy_personas`（非空 `target_persona_id` 集合）。
2. 查询 `status == PENDING` 的 job，按 created_at 升序。
3. 清理已完成 in-flight tasks。
4. 逐个 pending job：已 in-flight 跳过；`conversation_ids` 与 `busy_conversations` 有交集则跳过（等下一轮）；`target_persona_id` 命中 `busy_personas` 则跳过。通过后把它的 contacts/persona 也加进 busy 集合（防止同一轮里两个冲突 pending job 都启动），创建 `_run_distill_job()` task。

冲突控制目的：串行化会重复写同一张 card 或同一个 persona 的 job；不冲突的 job 仍可并发。

`_run_distill_job(job_id, conversation_ids, target_persona_id, provider_config_id)`：

1. 重新查询 job，确认仍是 pending。
2. 标记 `running`，设置 `started_at`。
3. 定义 progress callback，更新 `DistillJob.progress`。
4. await `run_distill()`。
5. 异常时：status `failed`，写 `error_message` 和 `finished_at`。
6. 成功时：status `done`，写 `finished_at`。

### ReplyScanner

每 2 秒：

1. 调 `list_pending_conversation_ids()`。
2. 清理已完成 tasks。
3. 对未 in-flight 的 Conversation 创建 `_run_reply(conversation_id)` task。

`_run_reply()` 调 `maybe_reply()` 并记录 status log。

### BridgeOfflineScanner

每 30 秒：

1. 查询所有 `status == "online"` 且 `last_seen_at < now - 45s` 的 Bridge。
2. 将其 status 设为 `"offline"`。
3. heartbeat 收到请求时会实时标回 `"online"`。

离线判断使用 45 秒阈值（3 倍心跳间隔），容忍偶尔的网络抖动。

## Reply brain

文件：`studio/reply.py`。

### 常量

- `QUIET_SECONDS = 6`。
- `HISTORY_TAIL = 60`。

### `SYSTEM_INSTRUCTION`

当前 system prompt 要求模型：

- 像真实的人在私聊里回复。
- 不能承认 AI/机器人/程序身份。
- 不引导转账、打赏、付费、借钱，不讨论具体金额。
- 不主动约线下见面；对方提出时自然推脱。
- 保持人设一致。
- 不发露骨色情、暴力、违法内容。
- 回复像真人：短句、拆条、语气词、情绪、不完美。
- 只输出 JSON：`{"messages": ["第一条", "第二条"]}`。
- 空数组表示当前选择不回复。

### 决策结构

`_ReplyCtx` 包含：

- `conversation_id`
- `conversation_display_name`
- `persona_name`
- `persona_md`
- `card_md`
- provider `base_url`、`api_key`、`model`
- `inbox_id`
- `display_tz`：来自 `persona.timezone or "UTC"`，IANA 时区字符串，用于历史消息时间戳本地化。

`_ReplyDecision` 包含 skip reason、ctx、history。

### `_decide(db, conversation_id)` 当前 gates

任何 gate 不通过都会返回 skip reason：

1. Conversation 存在。
2. Conversation status 是 active。
3. Conversation `reply_policy == 'autoreply'`（`disabled` 时跳过）。
4. Inbox 存在。
5. Provider 由 `Conversation.provider_id` 指定（`pick_first_provider(db)` 兜底）。
6. Provider 存在且有 API key。
7. Persona 存在。
8. History 非空。
9. History 最新消息来自 counterpart。
10. 最新 counterpart 消息已超过 quiet period。

如果 skip reason 以 `等静默期` 开头，保持 `last_reply_round_at` 不变，下一轮 scanner 会重试。

永久 skip 会更新 `last_reply_round_at`。

### Prompt 构造

`_build_user_message()` 当前拼接：

1. `## 你的人设` + Persona markdown。
2. `## 关于对方（display_name）` + Conversation card。
3. `## 最近的对话` + `_format_history_lines(history, ctx.display_tz)`。
4. “现在轮到你回复了，按要求输出 JSON。”

历史格式：

```text
[05-09 12:00] 我: ...
[05-09 12:01] 对方: ...
```

时间戳通过 `ZoneInfo(display_tz)` 将 UTC-aware `m.timestamp` 转换为 persona 所在时区后格式化（`%m-%d %H:%M`）。`ZoneInfo` 失败时回退到 UTC。

### Parse 和 commit

`_parse_chunks(raw)`：

- 去掉 Markdown code fence。
- `json.loads()`。
- 读取 `messages` 数组。
- 只保留非空 string。

`maybe_reply()` 分三段：

1. DB session 中调用 `_decide()`。
2. 不持有 DB session 调 LLM。
3. 重新打开 DB session，写 `LlmLog`、解析、写 `OutboundMessage`、更新 `last_reply_round_at`。

LLM 调用异常时写 `LlmLog(response_raw='ERROR: ...')`。

### OutboundMessage 节奏

每个解析到的 chunk 写一条独立 `OutboundMessage`（`msg_type='text'`）。`send_after` 在 Studio 端计算：

- 首条：`now + THINK_DELAY (1.5s)`。
- 后续：前一条 `send_after + max(MIN, min(MAX, len(prev_chunk) / CHARS_PER_SEC))`。
- `TYPING_CHARS_PER_SECOND = 6.0`，`TYPING_MIN_DELAY = 1.0s`，`TYPING_MAX_DELAY = 12.0s`，`THINK_DELAY = 1.5s`。

Bridge 收到即发，不做延迟。

## Distill packer

文件：`studio/distill/packer.py`。

当前逻辑：

- 超过 30 分钟间隔切一个 session。
- window 上限估算 40,000 tokens。
- token 估算：`字符数 / 2`。
- 每个 session 第一条消息用完整时间戳，后续消息用 `+30s` / `+2m` 相对时间。

## Distill pipeline

文件：`studio/distill/pipeline.py`。

模型：一个 job = `conversation_ids`（1..N）+ 可选 `target_persona_id`。**只有一条代码路径，没有 scope 枚举、没有按粒度分叉。** 唯一的条件是"是否设置了 target persona"：

- 设置了 → 同一组 fold 同时累积写入该 persona 的 `persona_md`。
- 为 None（单粉丝关系卡刷新）→ fold 输出的 Persona 段被丢弃，persona 不动。

`conversation_ids` 长度 1 = 单粉丝刷新；长度 N = 建人设。两者走完全相同的迭代。

当前流程：

1. `_load_ctx(target_persona_id, provider_config_id)`：persona 可选——设置了才查 Persona 拿 `persona_name` 和 `display_tz`，否则 `persona_id=None`、`persona_name=""`、`display_tz="UTC"`。始终校验 Provider active 且有 API key。加载 Account 的 `distill_provider_id` 对应的 ProviderConfig。
2. `run_distill(conversation_ids, target_persona_id, provider_config_id, ...)` 遍历传入的 `conversation_ids`（过滤掉不存在 / 无消息 / 无 window 的）。
3. 每个 runnable Conversation：
   - 读取消息，按 timestamp/id 升序；
   - `_fold_conversation()` 内查 Conversation 所属 Inbox 的 `platform_self_id` 作为 `character_wxid`；
   - `_messages_to_text_messages(msgs, ctx.display_tz)`；
   - split sessions；pack windows；顺序 fold 每个 window。
4. `_fold_conversation()` 每个 window 调一次 LLM。
5. `_parse_fold_output()` 提取 `Character Persona` 和 `Contact Card` 两段。
6. 解析到内容时：始终覆盖 `Conversation.card_md`；仅当 `ctx.persona_id` 非空时才覆盖 `Persona.persona_md`。
7. 每次 LLM 调用写 `LlmLog(purpose='distill')`，`persona_id` 可为 null，`inbox_id` 取该 Conversation 的 inbox。
8. progress callback 更新 conversations/windows 计数。

CLI（调试用）：传 `conversation_ids`（逗号分隔）、`target_persona_id`（可选）、`provider_config_id`、`request_timeout`。

## Fold prompt

文件：`studio/distill/prompts/fold.md`。

当前 prompt 要求模型作为分析师输出完整覆盖版本：

- `===== Character Persona =====`
- `===== Contact Card =====`

关键规则：

- 不编造。
- 使用原聊天相同语言。
- 保留旧的有效事实。
- 可变事实按时间线追踪。
- Persona 只描述 Character/主播本人。
- Contact Card 描述该粉丝和双方共享事实。

Contact Card 输出为 YAML-like 内容，包含 display name、互动时间、relationship tier、key traits、shared facts、notes。

## 当前 runtime 边界

当前 worker 是 scanner-based，不是 `docs/prompt-runtime-design-v2.md` 中描述的 full-duplex draft runtime。
