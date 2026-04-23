"""Scan WeFlow JSON exports and generate a people.yaml template."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


def scan_senders(file_paths: list[str]) -> dict[str, str]:
    """Extract unique senderUsername -> senderDisplayName mappings.

    Skips chatroom keys (containing @chatroom).
    """
    senders: dict[str, str] = {}
    for file_path in file_paths:
        path = Path(file_path)
        if not path.exists():
            print(f"警告: 找不到文件 {path}")
            continue
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        for msg in data.get("messages", []):
            key = msg.get("senderUsername", "")
            if not key or "@chatroom" in key:
                continue
            if key not in senders:
                senders[key] = msg.get("senderDisplayName", "")
    return senders


def build_people_yaml(senders: dict[str, str]) -> dict:
    """Build a people.yaml structure with TODO placeholders."""
    people = {}
    for key, display_name in senders.items():
        people[key] = {
            "name": display_name,
            "nickname": "",  # TODO
            "gender": "",  # TODO
            "age": "",  # TODO
            "notes": "TODO: 基础信息\n",
        }
    return {"me": "TODO: 填入蒸馏目标的 wxid", "people": people}


def main() -> None:
    parser = argparse.ArgumentParser(description="扫描微信导出 JSON，生成 people.yaml 模板")
    parser.add_argument("inputs", nargs="+", help="WeFlow JSON 文件路径，支持多个文件")
    parser.add_argument("-o", "--output", default="people.yaml", help="输出文件路径")
    args = parser.parse_args()

    senders = scan_senders(args.inputs)
    if not senders:
        print("未找到任何发送者，请检查输入文件。")
        return

    people_data = build_people_yaml(senders)

    output_path = Path(args.output)
    with output_path.open("w", encoding="utf-8") as f:
        yaml.dump(people_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"✅ 已生成 {output_path}，包含 {len(senders)} 个人")
    print("请手动填写每个人的 nickname、gender、age、notes，并设置 me 字段为蒸馏目标的 wxid。")


if __name__ == "__main__":
    main()
