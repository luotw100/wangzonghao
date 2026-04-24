"""Distill pipeline: rolling fold — convert chat exports → per-person style.md + memory.md."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from prettytable import PrettyTable

from robot.clients import ProviderClient
from robot.distill.converter import convert_messages
from robot.distill.packer import Window, pack_windows, parse_text_lines, split_sessions

PROMPTS_DIR = Path(__file__).parent / "prompts"
FOLD_PROMPT = (PROMPTS_DIR / "fold.md").read_text(encoding="utf-8")

# Regex to parse the output: ===== Name ===== ... --- style --- ... --- memory --- ...
_PERSON_BLOCK_RE = re.compile(
    r"={3,}\s*(.+?)\s*={3,}\s*-{3,}\s*style\s*-{3,}\s*(.*?)\s*-{3,}\s*memory\s*-{3,}\s*(.*?)(?=\n={3,}\s|\Z)",
    re.DOTALL,
)


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


def _build_profiles_block(profiles: dict[str, dict[str, str]], participants: set[str]) -> str:
    """Build the current profiles section for the fold prompt."""
    parts: list[str] = []
    for name in sorted(participants):
        p = profiles.get(name, {"style": "空", "memory": "空"})
        parts.append(f"===== {name} =====\n")
        parts.append(f"--- style ---\n{p['style']}\n")
        parts.append(f"--- memory ---\n{p['memory']}\n")
    return "\n".join(parts)


def _build_fold_user_message(
    window: Window,
    total_windows: int,
    profiles: dict[str, dict[str, str]],
) -> str:
    """Build the user message for a fold call."""
    participants = sorted(window.participants)
    profiles_block = _build_profiles_block(profiles, window.participants)
    return (
        f"```yaml\n"
        f"window: {window.window_id}/{total_windows}\n"
        f"time_range: \"{window.time_range}\"\n"
        f"participants: {json.dumps(participants, ensure_ascii=False)}\n"
        f"```\n\n"
        f"当前档案：\n\n{profiles_block}\n\n"
        f"以下是聊天记录：\n\n"
        f"{window.text}"
    )


def _parse_fold_output(output: str) -> dict[str, dict[str, str]]:
    """Parse fold output into {name: {style, memory}}."""
    results: dict[str, dict[str, str]] = {}
    for match in _PERSON_BLOCK_RE.finditer(output):
        name = match.group(1).strip()
        style = match.group(2).strip()
        memory = match.group(3).strip()
        results[name] = {"style": style, "memory": memory}
    return results


async def run_fold(
    client: ProviderClient,
    base_url: str,
    api_key: str,
    model: str,
    window: Window,
    total_windows: int,
    profiles: dict[str, dict[str, str]],
    intermediate_dir: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    """Run one fold step: update profiles with a new window."""
    user_message = _build_fold_user_message(window, total_windows, profiles)
    prefix = intermediate_dir / f"fold_{window.window_id:02d}"
    prefix.with_suffix(".input.txt").write_text(
        f"[SYSTEM]\n{FOLD_PROMPT}\n\n[USER]\n{user_message}", encoding="utf-8"
    )
    messages = [
        {"role": "system", "content": FOLD_PROMPT},
        {"role": "user", "content": user_message},
    ]
    result, usage = await client.complete_chat(base_url, api_key, model, messages)
    prefix.with_suffix(".output.txt").write_text(result, encoding="utf-8")

    updated = _parse_fold_output(result)
    if not updated:
        print(f"  ⚠️ Window {window.window_id}: 无法解析输出，跳过更新")
        return profiles, usage

    # Merge: update existing profiles, add new ones
    merged = dict(profiles)
    for name, data in updated.items():
        merged[name] = data
    return merged, usage


async def run_pipeline(
    input_paths: list[str],
    api_base: str,
    api_key: str,
    model: str,
    output_dir: str,
    request_timeout: float,
    max_windows: int = 0,
) -> None:
    """Run the rolling fold distill pipeline."""
    exports = load_chat_exports(input_paths)

    if not exports:
        print("没有有效的聊天数据。")
        return

    # Step 1: Convert all exports to plain text and merge
    print(f"📄 加载了 {len(exports)} 个聊天文件")
    all_lines: list[str] = []
    for session_name, messages in exports:
        lines = convert_messages(messages)
        print(f"  {session_name}: {len(messages)} 条原始消息 → {len(lines)} 条有效消息")
        all_lines.extend(lines)

    # Step 2: Parse, split sessions, pack windows
    text_messages = parse_text_lines(all_lines)
    text_messages.sort(key=lambda m: m.timestamp)
    sessions = split_sessions(text_messages)
    windows = pack_windows(sessions)
    if max_windows > 0:
        windows = windows[:max_windows]
    print(f"📦 切分为 {len(sessions)} 个 session，打包为 {len(windows)} 个窗口")

    for w in windows:
        print(f"  Window {w.window_id}: {len(w.messages)} 条消息，{w.time_range}，参与者: {', '.join(sorted(w.participants))}")

    # Step 3: Rolling fold
    print(f"\n🔄 开始滚动蒸馏（共 {len(windows)} 步）...")
    client = ProviderClient(request_timeout=request_timeout)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    intermediate_dir = output_path / "intermediate"
    intermediate_dir.mkdir(exist_ok=True)

    profiles: dict[str, dict[str, str]] = {}  # {name: {style, memory}}
    token_rows: list[tuple] = []

    for window in windows:
        print(f"  Fold {window.window_id}/{len(windows)} 开始...")
        profiles, usage = await run_fold(
            client, api_base, api_key, model, window, len(windows), profiles, intermediate_dir,
        )
        token_rows.append((
            f"Fold {window.window_id}",
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            usage.get("total_tokens", 0),
        ))
        print(f"  Fold {window.window_id}/{len(windows)} 完成 ✓  ({usage.get('total_tokens', '?')} tokens)")

    await client.close()

    # Step 4: Save per-person output
    for name, data in profiles.items():
        person_dir = output_path / name
        person_dir.mkdir(exist_ok=True)
        (person_dir / "style.md").write_text(data["style"], encoding="utf-8")
        (person_dir / "memory.md").write_text(data["memory"], encoding="utf-8")
        print(f"  ✅ {person_dir}/style.md + memory.md")

    # Token usage table
    total_prompt = sum(r[1] for r in token_rows)
    total_completion = sum(r[2] for r in token_rows)
    total_total = sum(r[3] for r in token_rows)

    table = PrettyTable(["阶段", "prompt", "completion", "total"])
    table.align["阶段"] = "l"
    table.align["prompt"] = "r"
    table.align["completion"] = "r"
    table.align["total"] = "r"
    for row in token_rows:
        table.add_row(row)
    table.add_divider()
    table.add_row(["合计", total_prompt, total_completion, total_total])
    print(f"\n{table}")
    print(f"🎉 完成！共提取 {len(profiles)} 人的档案。")


def main() -> None:
    parser = argparse.ArgumentParser(description="Distill: 从聊天记录蒸馏出风格档案和记忆账本")
    parser.add_argument("--input", nargs="+", required=True, help="WeFlow JSON 文件路径，支持多个文件")
    parser.add_argument("--api-base", required=True, help="LLM API base URL")
    parser.add_argument("--api-key", required=True, help="LLM API key")
    parser.add_argument("--model", required=True, help="LLM 模型名称")
    parser.add_argument("--output-dir", required=True, help="输出目录")
    parser.add_argument("--request-timeout", type=float, default=120.0, help="LLM 请求超时（秒）")
    parser.add_argument("--max-windows", type=int, default=0, help="最多处理几个窗口（0=不限制，调试用）")
    args = parser.parse_args()

    asyncio.run(
        run_pipeline(
            input_paths=args.input,
            api_base=args.api_base,
            api_key=args.api_key,
            model=args.model,
            output_dir=args.output_dir,
            request_timeout=args.request_timeout,
            max_windows=args.max_windows,
        )
    )


if __name__ == "__main__":
    main()
