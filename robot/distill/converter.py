"""Convert WeFlow JSON exports to plain text format."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

type Message = dict[str, Any]

# Message types to keep
KEEP_TYPES = {"文本消息", "引用消息"}
# Message types that may contain useful semantic info (e.g. [小程序] xxx)
MAYBE_KEEP_TYPES = {"其他消息"}
# Content patterns to filter out even if type matches
FILTER_CONTENT_PATTERNS = {"[图片]", "[文件]", "[语音]", "[视频]", "[撤回了一条消息]"}


def build_name_map(all_messages: list[list[Message]]) -> dict[str, str]:
    """Build wxid → canonical display name from all message lists.

    For each wxid, picks the most frequent senderDisplayName.
    Chatroom system accounts are excluded.
    """
    counts: dict[str, Counter[str]] = {}
    for messages in all_messages:
        for msg in messages:
            wxid = msg.get("senderUsername", "")
            if not wxid or "@chatroom" in wxid:
                continue
            display = msg.get("senderDisplayName", "")
            if not display:
                continue
            if wxid not in counts:
                counts[wxid] = Counter()
            counts[wxid][display] += 1

    return {wxid: counter.most_common(1)[0][0] for wxid, counter in counts.items()}


def should_keep(msg: Message) -> bool:
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


def message_timestamp(msg: Message) -> datetime:
    """Return the message timestamp as a naive datetime (UTC-equivalent local seconds)."""
    create_time = msg.get("createTime")
    if create_time is not None:
        return datetime.fromtimestamp(create_time)
    formatted = msg.get("formattedTime", "")
    if formatted:
        return datetime.strptime(formatted[:19], "%Y-%m-%d %H:%M:%S")
    raise ValueError("消息缺少时间戳（createTime / formattedTime 都没有）")


def clean_content(content: str) -> str:
    return content.strip()


