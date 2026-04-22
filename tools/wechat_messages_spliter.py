"""Split chat exports into time-based groups and generate a compressed Perfetto trace."""

from __future__ import annotations

import argparse
import glob
import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

MICROSECONDS_PER_SECOND = 1_000_000
DEFAULT_GAP_MINUTES = 30
DEFAULT_LAST_MESSAGE_DURATION_SECONDS = 10
DEFAULT_SPLIT_OUTPUT_PATH = "split_points.json"
DEFAULT_TRACE_OUTPUT_PATH = "trace.json"
TRACE_THREAD_ID = 0
GROUP_COLOR_NAME = "good"

type JsonDict = dict[str, Any]
type SplitPoints = dict[str, list[JsonDict]]


def format_trace_title(message: JsonDict, max_length: int = 15) -> str:
    """Build a compact title for a message trace event."""
    content = message.get("content")
    if isinstance(content, str):
        display_text = content
    elif content is None:
        display_text = f"[{message.get('type') or '无内容'}]"
    else:
        display_text = str(content)

    display_text = display_text.replace("\n", " ")
    if not display_text:
        return f"[{message.get('type') or '空消息'}]"

    if len(display_text) > max_length:
        return f"{display_text[:max_length]}..."
    return display_text


def format_real_time(timestamp: int | float) -> str:
    """Format a Unix timestamp for trace metadata display."""
    return datetime.fromtimestamp(timestamp).isoformat(sep=" ", timespec="seconds")


def get_message_real_time(message: JsonDict) -> str:
    """Return the best available human-readable time for a message."""
    formatted_time = message.get("formattedTime")
    if isinstance(formatted_time, str) and formatted_time.strip():
        return formatted_time

    create_time = message.get("createTime")
    if create_time is None:
        return ""
    return format_real_time(create_time)


def get_message_duration_seconds(group: Sequence[JsonDict], message_index: int) -> int | float:
    """Compute the visual duration for a message segment."""
    if message_index < len(group) - 1:
        next_message = group[message_index + 1]
        current_message = group[message_index]
        return max(next_message["createTime"] - current_message["createTime"], 0)
    return DEFAULT_LAST_MESSAGE_DURATION_SECONDS


def split_messages_by_gap(messages: Sequence[JsonDict], gap_seconds: int | float) -> list[list[JsonDict]]:
    """Split sorted messages into groups separated by the configured gap."""
    groups: list[list[JsonDict]] = []
    current_group: list[JsonDict] = []

    for message in messages:
        if not current_group:
            current_group.append(message)
            continue

        last_message = current_group[-1]
        time_diff = message["createTime"] - last_message["createTime"]
        if time_diff > gap_seconds:
            groups.append(current_group)
            current_group = [message]
            continue

        current_group.append(message)

    if current_group:
        groups.append(current_group)

    return groups


def expand_input_patterns(input_patterns: Sequence[str]) -> list[str]:
    """Expand command-line patterns into a flat list of file paths."""
    file_list: list[str] = []
    for pattern in input_patterns:
        file_list.extend(glob.glob(pattern))
    return file_list


def process_chat_data(file_paths: Sequence[str], gap_minutes: int) -> tuple[SplitPoints, list[JsonDict]]:
    """Build split points and trace events for the input chat exports."""
    gap_seconds = gap_minutes * 60
    all_split_points: SplitPoints = {}
    trace_events: list[JsonDict] = []

    for pid, file_path in enumerate(file_paths):
        path = Path(file_path)
        if not path.exists():
            print(f"警告: 找不到文件 {path}")
            continue

        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        session = data.get("session") or {}
        session_name = session.get("displayName", path.stem)
        messages = data.get("messages", [])
        if not messages:
            continue

        sorted_messages = sorted(messages, key=lambda message: message["createTime"])
        groups = split_messages_by_gap(sorted_messages, gap_seconds)
        file_splits: list[JsonDict] = []
        timeline_cursor_us = 0

        trace_events.append(
            {
                "name": "process_name",
                "ph": "M",
                "pid": pid,
                "args": {"name": session_name},
            }
        )

        for group_index, group in enumerate(groups, start=1):
            start_message = group[0]
            end_message = group[-1]
            message_durations_seconds = [
                get_message_duration_seconds(group, message_index)
                for message_index in range(len(group))
            ]
            group_duration_seconds = sum(message_durations_seconds)
            group_start_ts = timeline_cursor_us
            group_duration_us = int(group_duration_seconds * MICROSECONDS_PER_SECOND)

            file_splits.append(
                {
                    "groupId": group_index,
                    "startLocalId": start_message["localId"],
                    "endLocalId": end_message["localId"],
                    "startTime": start_message["createTime"],
                    "endTime": end_message["createTime"],
                    "messageCount": len(group),
                }
            )

            trace_events.append(
                {
                    "name": f"Group {group_index} ({len(group)} msgs)",
                    "cat": "group",
                    "ph": "X",
                    "ts": group_start_ts,
                    "dur": group_duration_us,
                    "pid": pid,
                    "tid": TRACE_THREAD_ID,
                    "cname": GROUP_COLOR_NAME,
                    "args": {
                        "realStartTime": get_message_real_time(start_message),
                        "realEndTime": get_message_real_time(end_message),
                        "realDurationSeconds": (
                            end_message["createTime"]
                            - start_message["createTime"]
                            + DEFAULT_LAST_MESSAGE_DURATION_SECONDS
                        ),
                        "visualDurationSeconds": group_duration_seconds,
                    },
                }
            )

            message_offset_us = 0
            for message_index, message in enumerate(group):
                message_duration_seconds = message_durations_seconds[message_index]
                message_duration_us = int(message_duration_seconds * MICROSECONDS_PER_SECOND)

                trace_events.append(
                    {
                        "name": format_trace_title(message),
                        "cat": "message",
                        "ph": "X",
                        "ts": group_start_ts + message_offset_us,
                        "dur": message_duration_us,
                        "pid": pid,
                        "tid": TRACE_THREAD_ID,
                        "args": {
                            "sender": message.get("senderDisplayName")
                            or message.get("senderUsername", "Unknown"),
                            "content": message.get("content"),
                            "type": message.get("type", ""),
                            "formattedTime": message.get("formattedTime", ""),
                            "realTime": get_message_real_time(message),
                            "visualDurationSeconds": message_duration_seconds,
                        },
                    }
                )
                message_offset_us += message_duration_us

            timeline_cursor_us += group_duration_us

        all_split_points[session_name] = file_splits

    return all_split_points, trace_events


def build_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for the chat splitter."""
    parser = argparse.ArgumentParser(description="聊天记录按时间线拆分并生成 Chrome Trace 可视化")
    parser.add_argument("inputs", nargs="+", help="输入的 JSON 文件路径，支持多个文件或通配符 (如 *.json)")
    parser.add_argument(
        "--gap-minutes",
        type=int,
        default=DEFAULT_GAP_MINUTES,
        help=f"判定为新分组的时间间隔（分钟），默认 {DEFAULT_GAP_MINUTES}",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=DEFAULT_SPLIT_OUTPUT_PATH,
        help="输出的拆分点位 JSON 文件名",
    )
    parser.add_argument(
        "--trace",
        "-t",
        default=DEFAULT_TRACE_OUTPUT_PATH,
        help="输出的 Chrome Trace 可视化 JSON 文件名",
    )
    return parser


def main() -> None:
    """Run the chat splitter command-line entrypoint."""
    parser = build_argument_parser()
    args = parser.parse_args()

    file_list = expand_input_patterns(args.inputs)
    if not file_list:
        print("未匹配到任何文件！请检查输入路径。")
        return

    print(f"正在处理 {len(file_list)} 个文件，时间间隔阈值：{args.gap_minutes} 分钟...")

    splits, traces = process_chat_data(file_list, args.gap_minutes)

    with Path(args.output).open("w", encoding="utf-8") as file:
        json.dump(splits, file, ensure_ascii=False, indent=2)
    print(f"✅ 拆分点位已保存至: {args.output}")

    trace_output = {"traceEvents": traces}
    with Path(args.trace).open("w", encoding="utf-8") as file:
        json.dump(trace_output, file, ensure_ascii=False)
    print(f"✅ Trace 可视化文件已保存至: {args.trace}")
    print("\n👉 可视化查看方式:")
    print("   打开浏览器访问 chrome://tracing 或 https://ui.perfetto.dev/")
    print(f"   然后将 {args.trace} 文件拖拽进去即可。")


if __name__ == "__main__":
    main()