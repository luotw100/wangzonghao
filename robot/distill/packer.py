"""Split plain text messages into sessions and pack into windows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

SESSION_GAP_SECONDS = 30 * 60  # 30 minutes
WINDOW_TOKEN_LIMIT = 10_000
MAX_WINDOW_TOKENS = 40_000  # Hard cap: never merge beyond this to stay within LLM context limits
OVERLAP_SESSIONS = 2
MIN_MY_MESSAGES = 10

# Rough token estimate: 1 Chinese char ≈ 0.6 tokens, 1 ASCII char ≈ 0.25 tokens
# For mixed Chinese text, ~2 chars per token is a safe approximation
CHARS_PER_TOKEN = 2


@dataclass
class TextMessage:
    """A single parsed text message."""

    timestamp: datetime
    sender: str
    content: str
    raw_line: str

    @property
    def is_me(self) -> bool:
        return self.sender == "我"


@dataclass
class Window:
    """A window of messages for L1 processing."""

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
    def my_message_count(self) -> int:
        return sum(1 for m in self.messages if m.is_me)

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
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        messages.append(TextMessage(timestamp=timestamp, sender=sender, content=content, raw_line=line))
    return messages


def split_sessions(messages: list[TextMessage]) -> list[list[TextMessage]]:
    """Split messages into sessions by time gap."""
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
    """Pack sessions into windows with overlap."""
    if not sessions:
        return []

    windows: list[Window] = []
    window_id = 1
    i = 0

    while i < len(sessions):
        window_sessions: list[list[TextMessage]] = []
        total_tokens = 0
        j = i

        while j < len(sessions):
            s_tokens = _estimate_tokens(sessions[j])
            if total_tokens + s_tokens > WINDOW_TOKEN_LIMIT and window_sessions:
                break
            window_sessions.append(sessions[j])
            total_tokens += s_tokens
            j += 1

        # Check minimum "my" message count
        my_count = sum(1 for s in window_sessions for m in s if m.is_me)
        new_tokens = _estimate_tokens([m for s in window_sessions for m in s])
        prev_tokens = _estimate_tokens(windows[-1].messages) if windows else 0
        can_merge = my_count < MIN_MY_MESSAGES and windows and (prev_tokens + new_tokens <= MAX_WINDOW_TOKENS)
        if can_merge:
            # Merge into previous window
            windows[-1].sessions.extend(window_sessions)
        else:
            windows.append(Window(window_id=window_id, sessions=window_sessions))
            window_id += 1

        # Next window starts with overlap
        i = max(i + 1, j - OVERLAP_SESSIONS)

    return windows
