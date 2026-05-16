"""Interactive REPL — the only user surface. The process is the daemon."""

from __future__ import annotations

import getpass
import sys
import threading

from . import commands, config
from .events import Events

BANNER = "Laborster Bridge · 输入 /help 查看命令，/quit 退出"


def _ask_line(prompt: str) -> str:
    if sys.stdin.isatty():
        try:
            return input(prompt)
        except EOFError:
            return ""
    line = sys.stdin.readline()
    return line.rstrip("\n")


def _ask_secret(prompt: str) -> str:
    if sys.stdin.isatty():
        try:
            return getpass.getpass(prompt)
        except EOFError:
            return ""
    line = sys.stdin.readline()
    return line.rstrip("\n")


def _render(result: dict) -> None:
    if result.get("error"):
        print(f"  ! {result['error']}")
    for line in result.get("lines", []):
        print(line)


def _follow(events: Events) -> None:
    if not sys.stdin.isatty():
        print("  (-f 跟随仅在交互终端可用；以上为最近日志)")
        return
    stop = threading.Event()
    try:
        for ln in events.follow(stop):
            commands._print_log(ln)
    except KeyboardInterrupt:
        stop.set()
        print()


def run() -> int:
    events = Events()
    ctx = commands.Context(events, _ask_line, _ask_secret)
    print(BANNER)
    if not config.has_state_dir():
        print("  ! 无状态目录 — 用 /state <path> 设置（或重启时带 --state）")

    while True:
        try:
            raw = input("laborster> ") if sys.stdin.isatty() else sys.stdin.readline()
        except EOFError:
            raw = ""
        if not sys.stdin.isatty() and raw == "":
            break  # EOF on piped input
        line = raw.strip()
        if not line:
            if sys.stdin.isatty():
                continue
            break
        if line.startswith("/"):
            line = line[1:]
        parts = line.split()
        name, cmd_args = parts[0], parts[1:]

        handler = commands.DISPATCH.get(name)
        if not handler:
            print(f"  ! 未知命令: {name}（/help 查看）")
            continue
        if not config.has_state_dir() and name not in commands.NO_STATE_OK:
            print("  ! 需要先设置状态目录: /state <path>")
            continue

        try:
            result = handler(ctx, cmd_args)
        except config.NoStateError as exc:
            print(f"  ! {exc}")
            continue
        except Exception as exc:
            print(f"  ! 命令出错: {exc}")
            continue

        if result.get("quit"):
            print("bye")
            return 0
        if result.get("follow"):
            _follow(events)
            continue
        _render(result)

    if ctx.runtime and ctx.runtime.is_running():
        ctx.runtime.stop()
    return 0
