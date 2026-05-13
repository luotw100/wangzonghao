# Studio Worker, Reply Brain, Distill / Worker、回复脑、蒸馏

## Worker 进程

`studio/worker.py` 是 worker CLI。

- `parse_args()` 要求显式传 `--request-timeout`。
- `run_worker()` 启动 `StudioRuntime` 后等待。
- Compose 当前命令：`uv run python -m studio.worker --request-timeout 120`。

## StudioRuntime

`studio/runtime.py` 当前同时运行两个 scanner loop。

### `RuntimeOptions`

- `request_timeout: float`：LLM HTTP request timeout。

### 生命周期

`start()`：

- 创建 reply 用的 `ProviderClient`。
- 启动 `_distill_scanner_loop()`。
- 启动 `_reply_scanner_loop()`。

`stop()`：

- cancel scanner tasks。
- cancel in-flight distill/reply tasks。
- 清空 task maps。
- 关闭 reply ProviderClient。

### DistillScanner

每 5 秒：

1. 查询 `DistillJob.status == DistillJobStatus.PENDING`，按 created_at 升序。
2. 清理已完成 in-flight tasks。
3. 对未 in-flight 的 pending job 创建 `_run_distill_job()` task。

`_run_distill_job()`：

1. 重新查询 job，确认仍是 pending。
2. 标记 `running`，设置 `started_at`。
3. 定义 progress callback，更新 `DistillJob.progress`。
4. await `run_distill()`。
5. 异常时：status `failed`，写 `error_message` 和 `finished_at`。
6. 成功时：status `done`，写 `finished_at`。

### ReplyScanner

每 2 秒：

1. 调 `list_pending_contact_ids()`。
2. 清理已完成 tasks。
3. 对未 in-flight 的 Contact 创建 `_run_reply(contact_id)` task。

`_run_reply()` 调 `maybe_reply()` 并记录 status log。

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

- `contact_id`
- `contact_display_name`
- `persona_name`
- `persona_md`
- `card_md`
- provider `base_url`、`api_key`、`model`
- `inbox_id`

`_ReplyDecision` 包含 skip reason、ctx、history。

### `_decide(db, contact_id)` 当前 gates

任何 gate 不通过都会返回 skip reason：

1. Contact 存在。
2. Contact status 是 active。
3. Contact autoreply enabled。
4. Inbox 存在且 enabled。
5. Provider 从 `contact.reply_provider_config_id or inbox.reply_provider_config_id or global default provider` 解析到，且状态 active。
6. Provider 存在且有 API key。
7. Persona 存在。
8. History 非空。
9. History 最新消息来自 counterpart。
10. 最新 counterpart 消息已超过 quiet period。

如果 skip reason 以 `等静默期` 开头，`pending_reply` 保持 true，下一轮 scanner 会重试。

永久 skip 会清除 `pending_reply`。

### Prompt 构造

`_build_user_message()` 当前拼接：

1. `## 你的人设` + Persona markdown。
2. `## 关于对方（display_name）` + Contact card。
3. `## 最近的对话` + `_format_history_lines()`。
4. “现在轮到你回复了，按要求输出 JSON。”

历史格式：

```text
[05-09 12:00] 我: ...
[05-09 12:01] 对方: ...
```

### Parse 和 commit

`_parse_chunks(raw)`：

- 去掉 Markdown code fence。
- `json.loads()`。
- 读取 `messages` 数组。
- 只保留非空 string。

`maybe_reply()` 分三段：

1. DB session 中调用 `_decide()`。
2. 不持有 DB session 调 LLM。
3. 重新打开 DB session，写 `LlmLog`、解析、写 `OutboundMessage`、清 `pending_reply`。

LLM 调用异常时写 `LlmLog(response_raw='ERROR: ...')`，当前不清 `pending_reply`。解析异常时清 `pending_reply`。

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

当前流程：

1. `_load_ctx()` 加载 Inbox、target Persona、ProviderConfig，并校验 Provider active 且有 API key。
2. `run_distill()` 列出 source Inbox 下 active Contacts。
3. 每个有消息的 Contact：
   - 读取消息，按 timestamp/id 升序；
   - 转为 `TextMessage`；
   - split sessions；
   - pack windows；
   - 顺序 fold 每个 window。
4. `_fold_contact()` 每个 window 调一次 LLM。
5. `_parse_fold_output()` 提取 `Character Persona` 和 `Contact Card` 两段。
6. 解析到内容时覆盖 `Persona.persona_md` 和 `Contact.card_md`。
7. 每次 LLM 调用写 `LlmLog(purpose='distill')`。
8. progress callback 更新 contacts/windows 计数。

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
