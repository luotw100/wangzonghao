"""Convert WeFlow JSON exports to plain text format."""

from __future__ import annotations

from datetime import datetime
from typing import Any

type Message = dict[str, Any]

# Message types to keep
KEEP_TYPES = {"文本消息", "引用消息"}
# Message types that may contain useful semantic info (e.g. [小程序] xxx)
MAYBE_KEEP_TYPES = {"其他消息"}
# Content patterns to filter out even if type matches
FILTER_CONTENT_PATTERNS = {"[图片]", "[文件]", "[语音]", "[视频]", "[撤回了一条消息]"}


def _should_keep(msg: Message) -> bool:
    """Decide whether a message should be kept in the output."""
    msg_type = msg.get("type", "")

    if msg_type in ("系统消息", "动画表情", "表情包", "图片消息", "视频消息", "语音消息"):
        return False

    content = (msg.get("content") or "").strip()
    if not content:
        return False

    if content in FILTER_CONTENT_PATTERNS:
        return False

    if msg_type in KEEP_TYPES:
        return True

    if msg_type in MAYBE_KEEP_TYPES:
        return True

    return False


def _resolve_sender(msg: Message) -> str | None:
    """Resolve the display name for a message sender.

    Returns None for chatroom system messages.
    """
    sender_key = msg.get("senderUsername", "")

    if "@chatroom" in sender_key:
        return None

    return msg.get("senderDisplayName") or sender_key


def _format_timestamp(msg: Message) -> str:
    """Format message timestamp to [YYYY-MM-DD HH:MM:SS]."""
    formatted = msg.get("formattedTime", "")
    if formatted:
        return formatted[:19]

    create_time = msg.get("createTime")
    if create_time is not None:
        dt = datetime.fromtimestamp(create_time)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    return "????-??-?? ??:??:??"


def _clean_content(content: str) -> str:
    """Clean up message content (trim whitespace/newlines)."""
    return content.strip()


def convert_messages(messages: list[Message]) -> list[str]:
    """Convert a list of WeFlow messages to plain text lines.

    Returns a list of formatted lines like:
        [2025-03-14 11:10:26] 白焕鹏: 明天下午三点不见不散
    """
    sorted_msgs = sorted(messages, key=lambda m: m.get("createTime", 0))
    lines: list[str] = []

    for msg in sorted_msgs:
        if not _should_keep(msg):
            continue

        sender = _resolve_sender(msg)
        if sender is None:
            continue

        timestamp = _format_timestamp(msg)
        content = _clean_content(msg.get("content", ""))
        if not content:
            continue

        lines.append(f"[{timestamp}] {sender}: {content}")

    return lines
