"""Distill pipeline: convert chat exports → style.md + memory.md."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import yaml

from robot.clients import ProviderClient
from robot.distill.converter import convert_messages
from robot.distill.packer import Window, pack_windows, parse_text_lines, split_sessions

PROMPTS_DIR = Path(__file__).parent / "prompts"
L1_PROMPT = (PROMPTS_DIR / "L1.md").read_text(encoding="utf-8")
L2_PROMPT = (PROMPTS_DIR / "L2.md").read_text(encoding="utf-8")

SPLIT_MARKER = "---SPLIT---"


type PeopleConfig = dict[str, Any]


def load_people(people_path: str) -> tuple[str, PeopleConfig]:
    """Load people.yaml and return (me_wxid, people_dict)."""
    path = Path(people_path)
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    me_wxid = data["me"]
    people = data["people"]
    return me_wxid, people


def load_chat_exports(input_paths: list[str]) -> list[tuple[str, list[dict[str, Any]]]]:
    """Load WeFlow JSON exports. Returns list of (session_name, messages)."""
    results: list[tuple[str, list[dict[str, Any]]]] = []
    for file_path in input_paths:
        path = Path(file_path)
        if not path.exists():
            print(f"警告: 找不到文件 {path}")
            continue
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        session_name = data.get("session", {}).get("displayName", path.stem)
        messages = data.get("messages", [])
        if messages:
            results.append((session_name, messages))
    return results


def _build_participants_yaml(window: Window, people: PeopleConfig, me_wxid: str) -> str:
    """Build the participants YAML block for a window's metadata."""
    participants: dict[str, dict[str, str]] = {}

    for nickname in window.participants:
        # Find the person config by nickname
        if nickname == "我":
            person = people.get(me_wxid, {})
        else:
            person = next(
                (p for p in people.values() if p.get("nickname") == nickname),
                next((p for p in people.values() if p.get("name") == nickname), {}),
            )

        entry: dict[str, str] = {}
        if person.get("name"):
            entry["name"] = person["name"]
        if person.get("gender"):
            entry["gender"] = person["gender"]
        if person.get("age"):
            entry["age"] = str(person["age"])
        if person.get("notes"):
            # Flatten multi-line notes to single line for YAML block
            entry["notes"] = person["notes"].strip().replace("\n", "；")

        if entry:
            participants[nickname] = entry

    lines = ["participants:"]
    for nick, info in participants.items():
        lines.append(f"  {nick}:")
        for k, v in info.items():
            lines.append(f"    {k}: \"{v}\"")
    return "\n".join(lines)


def build_l1_user_message(window: Window, total_windows: int, people: PeopleConfig, me_wxid: str) -> str:
    """Build the user message for an L1 call."""
    participants_yaml = _build_participants_yaml(window, people, me_wxid)
    return (
        f"```yaml\n"
        f"window_id: {window.window_id}\n"
        f"total_windows: {total_windows}\n"
        f"time_range: \"{window.time_range}\"\n"
        f"{participants_yaml}\n"
        f"```\n\n"
        f"以下是聊天记录：\n\n"
        f"{window.text}"
    )


def build_l2_user_message(l1_results: list[str]) -> str:
    """Build the user message for the L2 call."""
    parts = [f"共 {len(l1_results)} 个窗口分析结果：\n"]
    for i, result in enumerate(l1_results, 1):
        parts.append(f"Window {i}:\n{result}\n")
    return "\n".join(parts)


async def run_l1(
    client: ProviderClient,
    base_url: str,
    api_key: str,
    model: str,
    window: Window,
    total_windows: int,
    people: PeopleConfig,
    me_wxid: str,
    intermediate_dir: Path,
) -> tuple[str, dict]:
    """Run L1 extraction on a single window."""
    user_message = build_l1_user_message(window, total_windows, people, me_wxid)
    prefix = intermediate_dir / f"window_{window.window_id:02d}"
    prefix.with_suffix(".input.txt").write_text(
        f"[SYSTEM]\n{L1_PROMPT}\n\n[USER]\n{user_message}", encoding="utf-8"
    )
    messages = [
        {"role": "system", "content": L1_PROMPT},
        {"role": "user", "content": user_message},
    ]
    result, usage = await client.complete_chat(base_url, api_key, model, messages)
    prefix.with_suffix(".output.json").write_text(result, encoding="utf-8")
    return result, usage


async def run_l2(
    client: ProviderClient,
    base_url: str,
    api_key: str,
    model: str,
    l1_results: list[str],
    intermediate_dir: Path,
) -> tuple[str, dict]:
    """Run L2 aggregation on all L1 results."""
    user_message = build_l2_user_message(l1_results)
    (intermediate_dir / "l2.input.txt").write_text(
        f"[SYSTEM]\n{L2_PROMPT}\n\n[USER]\n{user_message}", encoding="utf-8"
    )
    messages = [
        {"role": "system", "content": L2_PROMPT},
        {"role": "user", "content": user_message},
    ]
    result, usage = await client.complete_chat(base_url, api_key, model, messages)
    (intermediate_dir / "l2.output.txt").write_text(result, encoding="utf-8")
    return result, usage


async def run_pipeline(
    input_paths: list[str],
    people_path: str,
    api_base: str,
    api_key: str,
    model: str,
    output_dir: str,
    request_timeout: float,
    concurrency: int,
    max_windows: int = 0,
) -> None:
    """Run the full distill pipeline."""
    me_wxid, people = load_people(people_path)
    exports = load_chat_exports(input_paths)

    if not exports:
        print("没有有效的聊天数据。")
        return

    # Step 1: Convert all exports to plain text and merge
    print(f"📄 加载了 {len(exports)} 个聊天文件")
    all_lines: list[str] = []
    for session_name, messages in exports:
        lines = convert_messages(messages, people, me_wxid)
        print(f"  {session_name}: {len(messages)} 条原始消息 → {len(lines)} 条有效消息")
        all_lines.extend(lines)

    # Step 2: Parse, split sessions, pack windows
    text_messages = parse_text_lines(all_lines)
    text_messages.sort(key=lambda m: m.timestamp)
    sessions = split_sessions(text_messages)
    windows = pack_windows(sessions)
    if max_windows > 0:
        windows = windows[:max_windows]
        print(f"📦 切分为 {len(sessions)} 个 session，打包为 {len(windows)} 个窗口（--max-windows={max_windows}）")
    else:
        print(f"📦 切分为 {len(sessions)} 个 session，打包为 {len(windows)} 个窗口")

    for w in windows:
        print(f"  Window {w.window_id}: {len(w.messages)} 条消息，我的消息 {w.my_message_count} 条，{w.time_range}")

    # Step 3: L1 — parallel extraction
    print(f"\n🔍 开始 L1 提取（并发={concurrency}）...")
    client = ProviderClient(request_timeout=request_timeout)
    semaphore = asyncio.Semaphore(concurrency)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    intermediate_dir = output_path / "intermediate"
    intermediate_dir.mkdir(exist_ok=True)

    total_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async def run_l1_with_semaphore(window: Window) -> tuple[int, str]:
        async with semaphore:
            print(f"  L1 Window {window.window_id}/{len(windows)} 开始...")
            result, usage = await run_l1(client, api_base, api_key, model, window, len(windows), people, me_wxid, intermediate_dir)
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)
            print(f"  L1 Window {window.window_id}/{len(windows)} 完成 ✓  ({usage.get('total_tokens', '?')} tokens)")
            return window.window_id, result

    tasks = [run_l1_with_semaphore(w) for w in windows]
    l1_raw_results = await asyncio.gather(*tasks)
    l1_raw_results_sorted = sorted(l1_raw_results, key=lambda x: x[0])
    l1_results = [result for _, result in l1_raw_results_sorted]
    print(f"  L1 合计: prompt={total_usage['prompt_tokens']}, completion={total_usage['completion_tokens']}, total={total_usage['total_tokens']}")

    # Step 4: L2 — aggregation
    print("\n📊 开始 L2 聚合...")
    l2_result, l2_usage = await run_l2(client, api_base, api_key, model, l1_results, intermediate_dir)
    for k in total_usage:
        total_usage[k] += l2_usage.get(k, 0)
    print(f"  L2: prompt={l2_usage.get('prompt_tokens', '?')}, completion={l2_usage.get('completion_tokens', '?')}, total={l2_usage.get('total_tokens', '?')}")
    await client.close()

    # Step 5: Split and save output
    if SPLIT_MARKER in l2_result:
        parts = l2_result.split(SPLIT_MARKER, 1)
        style_md = parts[0].strip()
        memory_md = parts[1].strip()
    else:
        print("⚠️ L2 输出中没有找到 ---SPLIT--- 分隔符，整体保存为 style.md")
        style_md = l2_result.strip()
        memory_md = ""

    (output_path / "style.md").write_text(style_md, encoding="utf-8")
    print(f"  ✅ {output_path / 'style.md'}")

    if memory_md:
        (output_path / "memory.md").write_text(memory_md, encoding="utf-8")
        print(f"  ✅ {output_path / 'memory.md'}")

    print(f"\n🎉 完成！总计消耗: prompt={total_usage['prompt_tokens']}, completion={total_usage['completion_tokens']}, total={total_usage['total_tokens']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Distill: 从聊天记录蒸馏出风格档案和记忆账本")
    parser.add_argument("--input", nargs="+", required=True, help="WeFlow JSON 文件路径，支持多个文件")
    parser.add_argument("--people", required=True, help="people.yaml 配置文件路径")
    parser.add_argument("--api-base", required=True, help="LLM API base URL")
    parser.add_argument("--api-key", required=True, help="LLM API key")
    parser.add_argument("--model", required=True, help="LLM 模型名称")
    parser.add_argument("--output-dir", default="output", help="输出目录")
    parser.add_argument("--request-timeout", type=float, default=120.0, help="LLM 请求超时（秒）")
    parser.add_argument("--concurrency", type=int, default=3, help="L1 并发数")
    parser.add_argument("--max-windows", type=int, default=0, help="最多处理几个窗口（0=不限制，调试用）")
    args = parser.parse_args()

    asyncio.run(
        run_pipeline(
            input_paths=args.input,
            people_path=args.people,
            api_base=args.api_base,
            api_key=args.api_key,
            model=args.model,
            output_dir=args.output_dir,
            request_timeout=args.request_timeout,
            concurrency=args.concurrency,
            max_windows=args.max_windows,
        )
    )


if __name__ == "__main__":
    main()
