# Bridge Inbound 同步重构设计规范

本文档描述 Bridge inbound（平台 → Bridge → Studio）方向的完整重构方案，供实现者参考。Outbound 方向（Studio → Bridge → 平台）**不变**。

---

## 1. 背景与问题

### 当前实现的根本缺陷

Bridge 当前 inbound 分两条路径：
- 启动时调 `list_initial_messages(since_ms=0)` 拉全量消息推 Studio
- 之后调 `stream_incoming()` 用 in-memory cursor 增量推新消息

这带来以下问题：

1. **无法处理历史消息导入**：用户把手机数据导入 PC 微信后，导入的历史消息 id 比内存 cursor 小，`stream_incoming()` 看不到。
2. **重启全量重传**：每次重启都从 `since_ms=0` 拉全量，靠 Studio 端 `external_id` 唯一约束去重，浪费带宽。
3. **platform_msg_id 不可信跨设备**：不同设备、不同 import 路径对同一条消息可能分配不同的本地 id，以 `external_id = live:{platform_msg_id}` 作为跨设备去重键不够可靠。
4. **逻辑有分叉**：启动逻辑和运行逻辑是两套代码，维护成本高。

### 设计目标

- Bridge 本地持久化所有从平台获取的消息，标记 sent/unsent
- Studio 端基于内容 hash 去重，与设备无关、与 platform_msg_id 无关
- 生产者-消费者模型，逻辑无分叉
- 天然支持：首次启动、历史消息导入、断联补档、换机迁移

---

## 2. 核心模型

### 两层独立去重

| 层 | 位置 | 机制 | 目的 |
|---|---|---|---|
| 本地去重 | Bridge SQLite UNIQUE index | `local_hash` | 防止 Bridge 重复处理同一条平台消息 |
| 内容 hash 去重 | Studio `messages.msg_hash` | `msg_hash` UNIQUE per contact | 跨设备、跨 Bridge 实例防止重复入库 |

两层独立，各自兜底。哪怕 Bridge 本地去重有 bug 导致重传，Studio 的 msg_hash 会挡住。

### 生产者-消费者（两个 asyncio task）

**Producer（per inbox）**：
- 驱动 adapter 的 `scan()` 方法，持续产出消息（历史和实时统一处理，无分叉）
- 每条消息 INSERT 进本地 SQLite，已存在（`local_hash` 碰撞）则静默跳过
- 媒体消息：在此阶段下载平台文件 → 算 sha256 → 缓存到本地 → content 存 `"sha256:xxxx"`

**Consumer（全局一个）**：
- 持续读取本地 SQLite 中 `sent=0` 的消息
- 媒体消息：向 Studio 调 `check-or-presign`，若 Studio 已有该 hash，跳过 S3 上传
- 文本消息：直接发往 Studio `/api/bridge/incoming`
- Studio 返回 `accepted` 或 `deduped` 均标记 `sent=1`
- 发送失败则保持 `sent=0`，下次继续重试

---

## 3. Bridge 本地存储

### SQLite 数据库

路径：`{state_dir}/messages.db`

```sql
CREATE TABLE local_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,  -- 64-bit，Python sqlite3 INTEGER 即 64-bit
    inbox_id        TEXT    NOT NULL,
    peer_id         TEXT    NOT NULL,
    platform_msg_id TEXT,                               -- nullable；仅供本机 producer 用作增量 cursor
    sender_id       TEXT    NOT NULL,                   -- 发送方 platform id（替代 role，适配群聊）
    sent_at         TEXT    NOT NULL,                   -- UTC ISO8601，保留平台原始精度，不截断
    msg_type        TEXT    NOT NULL,                   -- text | image | audio | video | file
    content         TEXT    NOT NULL,                   -- text: 明文；media: "sha256:{hex}"
    local_hash      TEXT    NOT NULL,                   -- Bridge 端去重 hash（见下文定义）
    sent            INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX idx_local_hash ON local_messages(inbox_id, local_hash);
CREATE INDEX idx_unsent ON local_messages(sent) WHERE sent = 0;
CREATE INDEX idx_cursor ON local_messages(inbox_id, peer_id, platform_msg_id);
```

**初始化**：建库时执行 `PRAGMA journal_mode=WAL` 以支持 producer/consumer 并发读写。

### `local_hash` 计算规则

```
local_hash = SHA256(
    inbox_id  + "\x00" +
    peer_id   + "\x00" +
    sender_id + "\x00" +
    sent_at   + "\x00" +   # 平台原始字符串，不做任何 normalize
    msg_type  + "\x00" +
    content                 # text: 明文；media: "sha256:{hex}"
).hexdigest()
```

用 `\x00` 作为字段分隔符，防止不同字段拼接碰撞。

### `content` 字段规则

| msg_type | content 存什么 |
|---|---|
| text | 消息明文 |
| image / audio / video / file | `"sha256:" + sha256hex(文件二进制)` |

media 的 sha256 等价于 shell `sha256sum file.mp4` 的十六进制输出，**文件名不参与计算**。

### 媒体缓存目录

路径：`{state_dir}/media/{sha256hex}`（无扩展名）

- Producer 下载平台媒体 → 计算 sha256 → 写入此文件
- Consumer 从此文件读取字节 → 上传至 Studio S3
- **不自动清理**，用户自行清理，清理不影响程序行为
  - 若 Consumer 需要上传但缓存文件已被手动删除：尝试重新从平台下载；若平台也已删除，记录 warning 并将该条消息标为 `sent=1`（防止无限重试阻塞队列）

---

## 4. Adapter 合约变更

### 删除

```python
# 从 Adapter ABC 和所有实现中删除这两个方法
list_initial_messages(since_ms: int) -> list[IncomingMessage]
stream_incoming() -> AsyncIterator[IncomingMessage]
```

### 新增 `scan()`

```python
async def scan(
    self,
    cursors: dict[str, str | None]  # {peer_id: last_platform_msg_id or None}
) -> AsyncIterator[IncomingMessage]:
    """
    持续产出消息，历史和实时不分叉，永不返回（内部循环）。
    
    cursors 由 runtime 从 local_messages DB 查询后传入：
        SELECT peer_id, MAX(platform_msg_id)
        FROM local_messages
        WHERE inbox_id = ? AND platform_msg_id IS NOT NULL
        GROUP BY peer_id
    cursors 中未出现的 peer 视为首次扫描，从头拉取。
    cursors 在 scan() 内部随扫描进度更新（内存），不写回 DB（DB 通过 insert 自动更新）。
    """
```

### `IncomingMessage` 字段变更

```python
@dataclass
class IncomingMessage:
    peer_id:            str
    peer_display_name:  str
    platform_msg_id:    str | None   # 可为 None（平台不提供或不可信时）
    sender_id:          str          # 发送方 platform id（替代原 role 字段）
    msg_type:           str          # text | image | audio | video | file
    content:            str          # text: 明文；media: 平台侧 storage key（runtime 负责下载）
    sent_at:            datetime     # naive UTC，保留平台原始精度
```

**`sender_id` 语义**：
- 1:1 对话：自己发的 = `inbox.platform_self_id`，对方发的 = `peer_id`
- 群聊（未来）：即群成员的 platform id
- Studio 通过比对 `sender_id == inbox.platform_self_id` 判断是否为"自己发"

---

## 5. Studio 协议变更

### 5.1 新端点：`POST /api/bridge/media/check-or-presign`

**目的**：避免 Consumer 对已有文件重复上传 S3。

```json
Request:
{
  "content_hash": "sha256:abcdef0123...",
  "filename": "voice.mp3",
  "mime_type": "audio/mpeg"
}

Response（Studio 已有该 hash）:
{ "status": "exists", "storage_key": "media/br_xxx/abc" }

Response（Studio 没有）:
{ "status": "new", "storage_key": "media/br_xxx/xyz", "upload_url": "https://s3.../" }
```

Studio 实现：查询 `messages` 表中 `content_hash = ?` 的已有 storage_key（或维护独立的 `media_hashes` 表，视实现方便）。若存在，返回 existing storage_key；若不存在，走现有 presign-upload 逻辑。

### 5.2 `POST /api/bridge/incoming` 变更

**Request 字段变更**：

| 字段 | 变化 |
|---|---|
| `role` | **移除** |
| `sender_id` | **新增**，发送方 platform id |
| `content_hash` | **新增**，媒体消息时为 `"sha256:{hex}"`，文本消息省略此字段 |
| `platform_msg_id` | 保留，仍可为 null |

**Studio 处理逻辑**（每条消息，替换原有逻辑）：

1. 校验 inbox / contact（同现有）
2. Upsert contact（同现有）
3. 计算 `msg_hash`（见下文）
4. 检查 `UNIQUE(contact_id, msg_hash)`：命中 → `deduped += 1`，跳过；未命中 → INSERT
5. `accepted += 1`

**`msg_hash` 计算规则**（Studio 端）：

```
msg_hash = SHA256(
    contact_id   + "\x00" +
    sender_id    + "\x00" +
    sent_at      + "\x00" +   # 与 Bridge 存储/发送的原始字符串一致
    msg_type     + "\x00" +
    content_or_hash             # text: content 明文；media: content_hash 字段值（"sha256:xxx"）
).hexdigest()
```

重要：`sent_at` 字符串格式必须与 Bridge 存储时一致（不做 normalize），否则 local_hash 和 msg_hash 计算结果不一致，换机场景会重复入库。

### 5.3 `messages` 表迁移

```sql
ALTER TABLE messages ADD COLUMN msg_hash  TEXT;
ALTER TABLE messages ADD COLUMN sender_id TEXT;
CREATE UNIQUE INDEX idx_msg_hash ON messages(contact_id, msg_hash)
    WHERE msg_hash IS NOT NULL;   -- NULL 不参与唯一约束，兼容旧数据
```

旧行 `msg_hash = NULL`，不受影响。新行由 incoming endpoint 写入。

`external_id` 字段和其 UNIQUE 约束**保留**（兼容旧数据），但不再作为主要去重机制。`platform_msg_id` 仍写入 `external_id`（若非 null），作为辅助信息。

---

## 6. 代码文件组织与函数脉络

### Bridge 侧

#### 新增：`bridge/local_store.py`

```python
import hashlib, sqlite3
from dataclasses import dataclass
from pathlib import Path

@dataclass
class LocalMessage:
    id:              int | None   # None before insert
    inbox_id:        str
    peer_id:         str
    platform_msg_id: str | None
    sender_id:       str
    sent_at:         str          # 原始 ISO8601 字符串
    msg_type:        str
    content:         str          # text 明文 or "sha256:{hex}"
    local_hash:      str
    sent:            bool

def compute_local_hash(inbox_id, peer_id, sender_id, sent_at, msg_type, content) -> str:
    """SHA256 of null-separated fields. sent_at must be the raw platform string."""
    raw = "\x00".join([inbox_id, peer_id, sender_id, sent_at, msg_type, content])
    return hashlib.sha256(raw.encode()).hexdigest()

class LocalStore:
    def __init__(self, db_path: Path): ...

    def migrate(self):
        """CREATE TABLE IF NOT EXISTS + PRAGMA journal_mode=WAL."""

    def get_cursors(self, inbox_id: str) -> dict[str, str | None]:
        """
        SELECT peer_id, MAX(platform_msg_id) FROM local_messages
        WHERE inbox_id=? AND platform_msg_id IS NOT NULL GROUP BY peer_id.
        Returns {peer_id: last_platform_msg_id}.
        """

    def insert_message(self, msg: LocalMessage) -> bool:
        """
        INSERT OR IGNORE ... Returns True if inserted, False if local_hash already existed.
        """

    def get_unsent(self, limit: int = 50) -> list[LocalMessage]:
        """SELECT ... WHERE sent=0 ORDER BY id LIMIT ?"""

    def mark_sent(self, msg_id: int):
        """UPDATE local_messages SET sent=1 WHERE id=?"""
```

#### 修改：`bridge/adapters/base.py`

- 删除 `list_initial_messages`、`stream_incoming` 抽象方法
- 新增 `scan(cursors: dict[str, str | None]) -> AsyncIterator[IncomingMessage]` 抽象方法
- `IncomingMessage.role: str` → `IncomingMessage.sender_id: str`

#### 修改：`bridge/adapters/chat.py`

删除 `list_initial_messages`、`stream_incoming` 实现。

实现 `scan()`：

```python
async def scan(self, cursors: dict[str, str | None]) -> AsyncIterator[IncomingMessage]:
    while True:
        await self._refresh_threads()
        for peer_id, thread in self._threads.items():
            since_id = cursors.get(peer_id)        # last known platform_msg_id or None
            msgs = await self._fetch_since(thread, since_id)
            for m in msgs:
                yield m
                cursors[peer_id] = m.platform_msg_id   # 更新内存 cursor
        await asyncio.sleep(self._poll_sleep)

async def _fetch_since(self, thread, since_id: str | None) -> list[IncomingMessage]:
    """GET /api/conversations/{conv_id}/messages?last_id={since_id or 0}"""
    # 与原 stream_incoming 中的拉取逻辑相同，但参数来自外部 cursor
```

`send()` / `download_media()` / `upload_and_send_media()` 不变。

#### 修改：`bridge/studio_client.py`

- 新增方法：
  ```python
  async def check_or_presign_media(
      self, content_hash: str, filename: str, mime_type: str
  ) -> tuple[str, str, str | None]:
      """Returns (status, storage_key, upload_url_or_None)."""
  ```
- 修改 `push_incoming(messages)` payload：
  - `role` 字段 → `sender_id`
  - 媒体消息增加 `content_hash` 字段

#### 主要重写：`bridge/runtime.py`

**删除**：
- `_inbound_queue: asyncio.Queue`
- `_adapter_inbound_loop(inbox_id, adapter)`
- `_inbound_pump_loop()`
- `_push_batch(batch)` 及其 linger/media-upload 逻辑

**新增**：

```python
class BridgeRuntime:
    def __init__(self, ..., store: LocalStore, media_cache_dir: Path): ...

    async def _producer_loop(self, inbox_id: str, adapter: Adapter):
        """
        单个 inbox 的生产者。永不退出（除非 _stop 置位）。
        1. store.get_cursors(inbox_id) 取初始 cursor
        2. async for msg in adapter.scan(cursors):
             local_msg = await self._to_local_message(inbox_id, msg)
             store.insert_message(local_msg)   # OR IGNORE
        """

    async def _to_local_message(self, inbox_id: str, msg: IncomingMessage) -> LocalMessage:
        """
        文本消息：content = msg.content
        媒体消息：
          1. data, _ = await adapter.download_media(msg.content)
          2. sha256hex = hashlib.sha256(data).hexdigest()
          3. (media_cache_dir / sha256hex).write_bytes(data)  -- 覆盖写幂等
          4. content = f"sha256:{sha256hex}"
        计算 local_hash，构造 LocalMessage(sent=False)
        """

    async def _consumer_loop(self):
        """
        全局消费者。永不退出（除非 _stop 置位）。
        while not _stop:
            batch = store.get_unsent(limit=50)
            if not batch: sleep(1); continue
            for msg in batch:
                try:
                    storage_key = await self._resolve_content(msg)
                    await self._studio.push_one_incoming(msg, storage_key)
                    store.mark_sent(msg.id)
                except Exception:
                    log warning, continue（留 sent=0，下次重试）
        """

    async def _resolve_content(self, msg: LocalMessage) -> str:
        """
        text: 直接返回 content
        media:
          1. status, storage_key, upload_url = await studio.check_or_presign_media(
                 msg.content, filename, mime_type)
          2. if status == "exists": return storage_key
          3. if status == "new":
               cache_path = media_cache_dir / msg.content.removeprefix("sha256:")
               if not cache_path.exists():
                   尝试重新从平台下载（需要能找到对应 adapter）
                   失败则 mark_sent(msg.id) + log warning + return None（上层 skip）
               data = cache_path.read_bytes()
               PUT data to upload_url
               return storage_key
        """

    async def run(self):
        """
        启动顺序：
        1. 登录所有 adapter
        2. handshake / token 复用
        3. store.migrate()
        4. 对每个 inbox 启动 _producer_loop task
        5. 启动全局 _consumer_loop task
        6. 启动 _heartbeat_loop task（不变）
        7. 启动 outbound loop task（不变）
        8. await _stop event
        """
```

**不变**：`_heartbeat_loop()`、outbound loop 全部逻辑、media presign-upload（用于 outbound）、ack 逻辑。

#### 修改：`bridge/main.py`

- 从 `state_dir` 初始化 `LocalStore(db_path=state_dir / "messages.db")`
- `media_cache_dir = state_dir / "media"`，`mkdir(exist_ok=True)`
- 将两者传入 `BridgeRuntime`

---

## 7. 关键注意事项

### sent_at 精度与一致性（最容易踩的坑）

`sent_at` **必须原样保留平台给的字符串精度**。Bridge 存入 local_messages 用什么格式，发给 Studio 就用什么格式，Studio 计算 msg_hash 也用同一个字符串。

**反面教材**：Bridge 存秒精度（截断了毫秒），Studio 收到后拿原始毫秒计算 msg_hash → Bridge local_hash ≠ Studio msg_hash → 换机后所有媒体消息重复入库。

实现时：`sent_at` 在整个链路上始终是字符串，不 parse 成 datetime 再格式化，除非能保证 round-trip 精度一致。

### 同一秒内两条内容完全相同的文本消息

hash 碰撞 → 第二条被 Studio 去重（不入库）。**接受这个行为**，不设计 workaround。现实对话中极罕见，且无法不付出大代价地解决。

### 换机（新 state_dir）

1. `messages.db` 为空，producer 以 `cursors={}` 启动，`scan()` 从头拉取平台全量历史
2. 每条 INSERT local_messages（local_hash 去重，几乎无冲突）
3. Consumer 逐条发送，Studio 用 msg_hash 去重，大部分 `deduped`（若旧机器曾同步过）
4. **最坏情况**：O(全量消息) 次网络请求，每次 Studio 极快地 hash 查找后拒绝，一次性代价

### 历史消息导入（Bridge 运行中）

用户导入历史 → **重启 Bridge** → Producer 重新 `scan()` 从平台看到新导入的旧消息 → 不在 local_messages → INSERT → Consumer 发送 → Studio 接受（若旧机器没有过）或去重（若有过）。

结论：导入历史后重启 Bridge 即可，无需额外操作。这是 v1 的行为，文档中告知用户。

### SQLite WAL 并发

Producer（写）和 Consumer（读/写）是两个并发 asyncio task，同一进程，必须：
- 初始化时 `PRAGMA journal_mode=WAL`
- 每个 asyncio task 使用独立的 `sqlite3.Connection`（或用 `check_same_thread=False` 配合 asyncio.Lock）
- INSERT 使用 `INSERT OR IGNORE` 配合 UNIQUE index，不用先 SELECT 再 INSERT

### 媒体缓存文件缺失的处理

Consumer 需要上传但缓存文件被用户手动删除时：
1. 先尝试重新从平台下载（`adapter.download_media()`，但此时已无 platform storage key……）

> **已知限制**：`local_messages.content` 存的是 `sha256:xxx`（Bridge 算出的），不是平台原始 storage key，所以无法重新下载。如果缓存被删且 sent=0，该消息无法恢复。当前设计接受这个限制：**媒体缓存文件在 `sent=1` 之前不能删除**。文档/UI 中应告知用户。

实现上：遇到此情况，记录 warning，将该条消息标为 `sent=1`（跳过），不阻塞后续消息。

**改进方向（v2）**：`local_messages` 增加 `platform_content TEXT` 字段，存平台原始 storage key，以备重下。v1 不做。

---

## 8. 测试方法

### 单元测试（新增 `tests/bridge/test_local_store.py`）

- `compute_local_hash` 的确定性：相同输入每次相同输出
- `insert_message` 返回 True（新）/ False（重复 local_hash）
- `get_unsent` 只返回 `sent=0` 的行
- `mark_sent` 正确更新，后续 `get_unsent` 不再包含该行
- `get_cursors` 正确返回 per-peer `MAX(platform_msg_id)`
- 并发写：两个 thread 同时 insert 相同 local_hash，只有一条入库

### 集成测试（手动，使用 Chat sandbox）

**场景 A：正常首次运行**
1. 清空 `state_dir`（含 `messages.db`）
2. Chat sandbox 中建立若干对话，发送文本和媒体消息
3. 启动 Bridge，等待 Consumer 全部 sent
4. 验证：Studio 中 conversations/messages 数量与 Chat sandbox 一致

**场景 B：重启不重传**
1. 接场景 A，正常关闭 Bridge
2. 重启 Bridge，等待稳定
3. 验证：Studio 中消息数量不变，无重复

**场景 C：崩溃后补档**
1. Bridge 运行中，在 Chat sandbox 发送几条消息
2. 强制 kill Bridge（`kill -9`）
3. 再在 Chat sandbox 发几条消息
4. 重启 Bridge，等待 Consumer 处理完
5. 验证：Studio 中所有消息都在，无重复，kill 前后的消息均到达

**场景 D：换机（空 state_dir）**
1. Bridge A 运行过并同步完毕，Studio 有完整记录
2. 新建空 `state_dir`，启动 Bridge B（相同 Studio 账号）
3. 等待 Bridge B 完成全量扫描和 Consumer 发送
4. 验证：Studio 消息数量不变（全部被 msg_hash 去重），无重复

**场景 E：媒体消息**
1. Chat sandbox 发送图片/音频
2. Bridge 运行，等待 Consumer 处理
3. 验证：Studio 有对应媒体消息，`{state_dir}/media/` 下有缓存文件
4. 重启 Bridge → 验证 Studio 消息数量不增加（hash 去重正常）

**场景 F：check-or-presign 避免重复上传**
1. 场景 D 完成后，Bridge B 已经同步完所有消息
2. 新增一台 Bridge C（新 state_dir），让它处理同一个 inbox
3. 监控 Studio S3 请求日志，验证 Bridge C 在 `check-or-presign` 返回 `"exists"` 时没有上传

---

## 9. 验收标准

| 标准 | 验证方法 |
|---|---|
| 正常流程：Chat sandbox 消息全部到达 Studio | 场景 A |
| 重启后 Studio 无重复消息 | 场景 B |
| 崩溃恢复：断档消息补齐，无重复 | 场景 C |
| 换机：新机器同步后 Studio 无重复 | 场景 D |
| 媒体消息正常同步，media 缓存存在 | 场景 E |
| `check-or-presign` 对已有文件返回 `"exists"` | 场景 F |
| Outbound 仍正常工作 | 独立验证：Studio 发 outbound，Bridge 正确转发至 Chat |
| `messages.db` 可用 sqlite3 CLI 查询，字段完整 | `sqlite3 messages.db ".schema"` + `SELECT * FROM local_messages LIMIT 5` |
| Studio `messages` 表新增行有 `msg_hash`，不为 NULL | `SELECT count(*) FROM messages WHERE msg_hash IS NULL` 应为 0（新记录） |
| 无 `list_initial_messages` / `stream_incoming` 残留 | `grep -r "list_initial_messages\|stream_incoming" services/bridge/` 无结果 |
| Bridge adapter 实现了 `scan()` | 启动不报 `NotImplementedError` |
