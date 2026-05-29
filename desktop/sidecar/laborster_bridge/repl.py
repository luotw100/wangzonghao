"""Interactive REPL — the only user surface. The process is the daemon.

Interactive (tty) mode uses prompt_toolkit: command history (↑/↓,
persisted to <state>/.history), Tab completion, and styled output.
Non-tty (piped) mode falls back to a plain stdin loop so the CLI stays
scriptable and testable.
"""

from __future__ import annotations

import sys
import threading

from . import commands, config
from .events import Events

BANNER = "Laborster Bridge · 输入 /help 查看命令，/quit 退出"

_TOP = [
    "help", "state", "login", "logout", "status",
    "account", "channel", "log", "studio", "quit",
]
_SUB = {
    "channel": ["list", "add", "rm", "relogin"],
    "account": ["list", "use", "remove"],
    "studio":  ["set", "reset"],
    "log":     ["-f"],
}


def _make_completer():
    """Slash-tolerant command completer.

    prompt_toolkit's word regex excludes '/', so NestedCompleter keyed
    "/channel" can't match the word "c" typed after "/", and an empty
    word ("/") yields nothing. This handles the optional leading '/'
    explicitly: bare "/" lists every command, "/c" -> channel, and
    "channel " (or "/channel ") completes the subcommands. Completions
    replace only the typed word, so the leading '/' is preserved.
    """
    from prompt_toolkit.completion import Completer, Completion

    class _CmdCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            lead = text.lstrip()
            body = lead[1:] if lead.startswith("/") else lead
            ends_space = body.endswith(" ")
            parts = body.split()

            if not parts or (len(parts) == 1 and not ends_space):
                word = parts[0] if parts else ""
                for name in _TOP:
                    if name.startswith(word):
                        yield Completion(name, start_position=-len(word))
                return

            subs = _SUB.get(parts[0], [])
            cur = "" if ends_space else parts[-1]
            for s in subs:
                if s.startswith(cur):
                    yield Completion(s, start_position=-len(cur))

    return _CmdCompleter()


# ---------- styled rendering (tty) ----------

def _build_style():
    from prompt_toolkit.styles import Style

    return Style.from_dict(
        {
            "err": "fg:#ff5f5f bold",
            "ok": "fg:#5fd75f",
            "warn": "fg:#ffd75f",
            "key": "fg:#5fafff",
            "dim": "fg:#8a8a8a",
            "head": "bold",
        }
    )


def _fmt_result(result: dict):
    """Yield (style_class, text) tuples for one command result."""
    if result.get("error"):
        yield ("class:err", f"  ✗ {result['error']}\n")
    for line in result.get("lines", []):
        s = line.strip()
        if any(k in line for k in ("成功", "已添加", "已删除", "已停止", "已登出", "online", " ok")):
            yield ("class:ok", line + "\n")
        elif any(k in line for k in ("失效", "失败", "错误", "offline", "无法", "超时")):
            yield ("class:err", line + "\n")
        elif "启动中" in line or "connecting" in line or "warn" in line:
            yield ("class:warn", line + "\n")
        elif " : " in line and not s.startswith("/"):
            k, _, v = line.partition(" : ")
            yield ("class:key", k + " : ")
            yield ("", v + "\n")
        elif s.startswith("/") or line.startswith("Laborster"):
            yield ("class:head", line + "\n")
        else:
            yield ("", line + "\n")


def _fmt_log(ln: dict):
    lvl = {"err": "class:err", "warn": "class:warn", "ok": "class:ok"}.get(ln["level"], "")
    return [
        ("class:dim", f"  {ln['t']} "),
        ("class:key", f"[{ln['src']}/"),
        (lvl, f"{ln['level']}] "),
        (lvl, ln["msg"] + "\n"),
    ]


# ---------- interactive (prompt_toolkit) ----------

def _run_interactive(events: Events) -> int:
    from prompt_toolkit import PromptSession, print_formatted_text
    from prompt_toolkit import prompt as ptk_prompt
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.history import FileHistory, InMemoryHistory
    from prompt_toolkit.patch_stdout import patch_stdout

    style = _build_style()
    completer = _make_completer()

    def pr(fragments) -> None:
        print_formatted_text(FormattedText(fragments), style=style)

    history_path: str | None = None
    session: PromptSession = PromptSession(
        history=InMemoryHistory(), completer=completer
    )

    def sync_history() -> None:
        nonlocal history_path, session
        if not config.has_state_root():
            return
        want = str(config.state_root() / ".history")
        if want != history_path:
            history_path = want
            session = PromptSession(
                history=FileHistory(want), completer=completer
            )

    # Sub-prompts (username/password) use a standalone prompt, NOT the
    # main session: reusing the session leaks is_password masking into
    # later prompts and would push credentials into command history.
    def ask_line(prompt: str) -> str:
        try:
            return ptk_prompt(prompt)
        except (EOFError, KeyboardInterrupt):
            return ""

    def ask_secret(prompt: str) -> str:
        try:
            return ptk_prompt(prompt, is_password=True)
        except (EOFError, KeyboardInterrupt):
            return ""

    ctx = commands.Context(events, ask_line, ask_secret)
    pr([("class:head", BANNER + "\n")])
    if not config.has_state_root():
        pr([("class:warn", "  无状态目录 — 用 /state <path> 设置（或重启带 --state）\n")])
    elif commands.autostart(ctx):
        pr([("class:ok", "  daemon 已自动连接（/status 查看）\n")])

    with patch_stdout():
        while True:
            sync_history()
            try:
                raw = session.prompt("laborster> ")
            except (EOFError, KeyboardInterrupt):
                raw = "/quit"
            line = raw.strip()
            if not line:
                continue
            if line.startswith("/"):
                line = line[1:]
            parts = line.split()
            name, cmd_args = parts[0], parts[1:]

            handler = commands.DISPATCH.get(name)
            if not handler:
                pr([("class:err", f"  ✗ 未知命令: {name}（/help 查看）\n")])
                continue
            if not config.has_state_root() and name not in commands.NO_STATE_OK:
                pr([("class:err", "  ✗ 需要先设置状态目录: /state <path>\n")])
                continue

            try:
                result = handler(ctx, cmd_args)
            except config.NoStateError as exc:
                pr([("class:err", f"  ✗ {exc}\n")])
                continue
            except Exception as exc:
                pr([("class:err", f"  ✗ 命令出错: {exc}\n")])
                continue

            if result.get("quit"):
                pr([("class:dim", "bye\n")])
                return 0
            for ln in result.get("logs", []):
                pr(_fmt_log(ln))
            if result.get("follow"):
                stop = threading.Event()
                try:
                    for ln in events.follow(stop):
                        pr(_fmt_log(ln))
                except KeyboardInterrupt:
                    stop.set()
                continue
            pr(list(_fmt_result(result)))


# ---------- non-interactive fallback ----------

def _run_plain(events: Events) -> int:
    def ask_line(prompt: str) -> str:
        return sys.stdin.readline().rstrip("\n")

    ctx = commands.Context(events, ask_line, ask_line)
    print(BANNER)
    if not config.has_state_root():
        print("  ! 无状态目录 — 用 /state <path> 设置（或重启时带 --state）")
    elif commands.autostart(ctx):
        print("  daemon 已自动连接（/status 查看）")

    while True:
        raw = sys.stdin.readline()
        if raw == "":
            break
        line = raw.strip()
        if not line:
            break
        if line.startswith("/"):
            line = line[1:]
        parts = line.split()
        name, cmd_args = parts[0], parts[1:]

        handler = commands.DISPATCH.get(name)
        if not handler:
            print(f"  ! 未知命令: {name}（/help 查看）")
            continue
        if not config.has_state_root() and name not in commands.NO_STATE_OK:
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
        for ln in result.get("logs", []):
            print(f"  {ln['t']} [{ln['src']}/{ln['level']}] {ln['msg']}")
        if result.get("error"):
            print(f"  ! {result['error']}")
        for line in result.get("lines", []):
            print(line)

    commands.cmd_quit(ctx, [])
    return 0


def run() -> int:
    if sys.stdin.isatty():
        return _run_interactive(Events())
    return _run_plain(Events())
