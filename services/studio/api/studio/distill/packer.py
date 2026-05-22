"""将消息列表拆分为 session，再打包成 LLM 处理窗口（Window）。

两步处理：
  1. split_sessions：按时间间隔（SESSION_GAP_SECONDS）将消息序列切割成多个 session
     （同一 session 内消息间隔 ≤ 30 分钟，不同 session 之间有较长间隔）
  2. pack_windows：将 session 顺序填入 Window，每个 Window 不超过 WINDOW_TOKEN_LIMIT 个 token
     不跨 Window 分割 session（session 是最小打包单元）

⚠ 输入消息必须按 timestamp 排好序后再传入，packer 本身不排序。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

# 超过此时间间隔（秒）的相邻消息视为两个不同 session
SESSION_GAP_SECONDS = 30 * 60  # 30 分钟

# 每个 Window 的 token 上限（粗估），超出则新开一个 Window
WINDOW_TOKEN_LIMIT = 40_000

# Token 估算：中英文混合取 2 字符/token（中文约 0.6 token/字，ASCII 约 0.25 token/字）
CHARS_PER_TOKEN = 2


@dataclass
class TextMessage:
    """单条已解析的文本消息，timestamp 是真实发送时间（不是 DB id 顺序）。"""

    timestamp: datetime
    sender: str     # "我" 或 "对方"
    content: str
    raw_line: str   # 原始格式化行，用于 token 估算和 Window 渲染


@dataclass
class Window:
    """一个发送给 LLM fold 的消息窗口，包含若干完整 session。

    window_id 从 1 起，顺序递增（不代表时间顺序以外的任何语义）。
    """

    window_id: int
    sessions: list[list[TextMessage]] = field(default_factory=list)

    @property
    def messages(self) -> list[TextMessage]:
        return [m for s in self.sessions for m in s]

    @property
    def time_range(self) -> str:
        msgs = self.messages
        if not msgs:
            return ""
        start = msgs[0].timestamp.strftime("%Y-%m-%d")
        end = msgs[-1].timestamp.strftime("%Y-%m-%d")
        if start == end:
            return start
        return f"{start} ~ {end}"

    @property
    def text(self) -> str:
        """Render messages with relative timestamps within each session."""
        lines: list[str] = []
        for session in self.sessions:
            if not session:
                continue
            if lines:
                lines.append("")  # blank line between sessions
            first = session[0]
            lines.append(f"[{first.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {first.sender}: {first.content}")
            prev_ts = first.timestamp
            for msg in session[1:]:
                delta = int((msg.timestamp - prev_ts).total_seconds())
                rel = f"+{delta}s" if delta < 60 else f"+{delta // 60}m"
                lines.append(f"[{rel}] {msg.sender}: {msg.content}")
                prev_ts = msg.timestamp
        return "\n".join(lines)

    @property
    def participants(self) -> set[str]:
        return {m.sender for m in self.messages}

    @property
    def session_count(self) -> int:
        return len(self.sessions)


def parse_text_lines(lines: list[str]) -> list[TextMessage]:
    """Parse plain text format lines into TextMessage objects."""
    messages: list[TextMessage] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Expected format: [2025-03-14 11:10] 鹏哥: 消息内容
        if not line.startswith("["):
            continue
        bracket_end = line.find("]")
        if bracket_end == -1:
            continue
        timestamp_str = line[1:bracket_end]
        rest = line[bracket_end + 2:]  # skip "] "
        colon_pos = rest.find(": ")
        if colon_pos == -1:
            continue
        sender = rest[:colon_pos]
        content = rest[colon_pos + 2:]
        try:
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        messages.append(TextMessage(timestamp=timestamp, sender=sender, content=content, raw_line=line))
    return messages


def split_sessions(messages: list[TextMessage]) -> list[list[TextMessage]]:
    """按时间间隔（SESSION_GAP_SECONDS）将消息序列切割成 session 列表。

    输入必须已按 timestamp 升序排列。相邻消息间隔 > SESSION_GAP_SECONDS 时产生新 session。
    """
    if not messages:
        return []
    sessions: list[list[TextMessage]] = []
    current: list[TextMessage] = [messages[0]]
    for msg in messages[1:]:
        gap = (msg.timestamp - current[-1].timestamp).total_seconds()
        if gap > SESSION_GAP_SECONDS:
            sessions.append(current)
            current = [msg]
        else:
            current.append(msg)
    sessions.append(current)
    return sessions


def _estimate_tokens(messages: list[TextMessage]) -> int:
    """Estimate token count for a list of messages."""
    total_chars = sum(len(m.raw_line) for m in messages)
    return total_chars // CHARS_PER_TOKEN


def pack_windows(sessions: list[list[TextMessage]]) -> list[Window]:
    """将 session 列表顺序打包成 Window 列表，每个 Window 不超过 WINDOW_TOKEN_LIMIT token。

    不跨 Window 分割 session（session 是最小单元）。
    若单个 session 本身就超过 token 限制，仍单独成一个 Window（不截断内容）。
    """
    if not sessions:
        return []

    windows: list[Window] = []
    window_id = 1
    i = 0

    while i < len(sessions):
        window_sessions: list[list[TextMessage]] = []
        total_tokens = 0

        while i < len(sessions):
            s_tokens = _estimate_tokens(sessions[i])
            if total_tokens + s_tokens > WINDOW_TOKEN_LIMIT and window_sessions:
                break
            window_sessions.append(sessions[i])
            total_tokens += s_tokens
            i += 1

        windows.append(Window(window_id=window_id, sessions=window_sessions))
        window_id += 1

    return windows
