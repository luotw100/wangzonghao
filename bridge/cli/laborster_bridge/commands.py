"""Slash-command handlers. Each returns a dict the REPL renders.

Return shape: {"lines": [str, ...]} for normal output, or
{"error": str}. Special key {"quit": True} ends the REPL.
"""

from __future__ import annotations

from . import config, state
from .chat_adapter import ChatAdapter
from .events import Events
from .http import HttpError, Unauthorized
from .runtime import BridgeRuntime
from .store import LocalStore
from .studio_client import StudioClient

HELP = """\
Laborster Bridge — 命令

  /help               显示本指南
  /state <path>       设置本会话的状态目录（无默认；每次启动都要指定）
  /login              输入 Studio 账号密码 → 换 token 落盘（之后自动连接）
  /logout             清除 Studio token（自动断开）
  /status             daemon 与各 channel 状态快照
  /channel add        输入 Chat 账号密码 → 换 token 存入（自动重连注册）
  /channel rm <n>     删除第 n 个 channel（见 /channel list）
  /channel list       列出已保存的 channel（不含任何凭据）
  /log [-f]           查看日志；-f 跟随（Ctrl-C 或 EOF 退出）
  /studio             打印 Studio 地址
  /quit               停 daemon 并退出
"""


class Context:
    def __init__(self, events: Events, ask_line, ask_secret) -> None:
        self.events = events
        self.runtime: BridgeRuntime | None = None
        self.ask_line = ask_line
        self.ask_secret = ask_secret


# --- runtime wiring ---

def _make_runtime(ctx: Context) -> BridgeRuntime:
    data = state.load()

    def get_token() -> str | None:
        return state.load().get("studio_token")

    def base_info() -> dict:
        d = state.load()
        return {
            "studio_url": config.STUDIO_BASE_URL,
            "username": d.get("username"),
            "machine_id": d.get("machine_id"),
            "bridge_id": d.get("bridge_id"),
        }

    # Token this runtime was built with. on_auth_error must only clear it
    # if it is still the stored token — a dying old runtime (started with
    # a stale token) must not wipe a token a fresh /login just wrote.
    token_at_start = data.get("studio_token")

    def on_auth_error() -> None:
        d = state.load()
        if d.get("studio_token") != token_at_start:
            return
        d.pop("studio_token", None)
        state.save(d)
        ctx.events.log("core", "err", "Studio token 已失效并清除，请重新 /login")

    return BridgeRuntime(
        StudioClient(get_token),
        list(data.get("channels", [])),
        LocalStore(str(config.db_file())),
        ctx.events,
        base_info,
        on_auth_error,
    )


def _stop_daemon(ctx: Context) -> None:
    if ctx.runtime and ctx.runtime.is_running():
        ctx.runtime.stop()
    ctx.runtime = None


def _ensure(ctx: Context) -> str | None:
    """Reconcile the daemon with persisted state.

    The daemon is not a user-visible concept: whenever a state dir is set
    and there is a Studio token + at least one channel, the daemon runs.
    Called on launch and after any state-mutating command (it always
    (re)starts when ready so a changed channel set re-registers).
    """
    if not config.has_state_dir():
        return None
    data = state.load()
    ready = bool(data.get("studio_token") and data.get("channels"))
    _stop_daemon(ctx)
    if not ready:
        return None
    ctx.runtime = _make_runtime(ctx)
    ctx.runtime.start()
    return "daemon 已自动连接（/status 查看）"


def autostart(ctx: Context) -> str | None:
    """Best-effort auto-start at REPL launch (state dir already set)."""
    return _ensure(ctx)


# --- commands ---

def cmd_help(ctx: Context, args: list[str]) -> dict:
    return {"lines": HELP.splitlines()}


def cmd_state(ctx: Context, args: list[str]) -> dict:
    if not args:
        if config.has_state_dir():
            return {"lines": [f"state dir: {config.state_dir()}"]}
        return {"error": "用法: /state <path>"}
    try:
        d = config.set_state_dir(args[0])
    except Exception as exc:
        return {"error": str(exc)}
    lines = [f"state dir: {d}"]
    msg = _ensure(ctx)
    if msg:
        lines.append(msg)
    return {"lines": lines}


def cmd_login(ctx: Context, args: list[str]) -> dict:
    username = ctx.ask_line("Studio 用户名: ").strip()
    password = ctx.ask_secret("Studio 密码: ")
    if not username or not password:
        return {"error": "用户名和密码不能为空"}
    data = state.load()
    try:
        r = StudioClient(lambda: None).handshake(
            username, password, data.get("machine_id")
        )
    except Unauthorized:
        return {"error": "账号或密码错误"}
    except HttpError as exc:
        return {"error": f"handshake 失败: {exc}"}
    data.update(
        {
            "username": username,
            "studio_token": r["token"],
            "machine_id": r["machine_id"],
            "bridge_id": r["bridge_id"],
        }
    )
    state.save(data)
    lines = [
        "登录成功",
        f"  bridge_id  : {r['bridge_id']}",
        f"  machine_id : {r['machine_id']}",
    ]
    msg = _ensure(ctx)
    if msg:
        lines.append(msg)
    elif not data.get("channels"):
        lines.append("还没有 channel — 执行 /channel add")
    return {"lines": lines}


def cmd_logout(ctx: Context, args: list[str]) -> dict:
    _stop_daemon(ctx)
    data = state.load()
    data.pop("studio_token", None)
    state.save(data)
    return {"lines": ["已登出，Studio token 已清除"]}


def cmd_channel(ctx: Context, args: list[str]) -> dict:
    if not args:
        return {"error": "用法: /channel add | rm <n> | list"}
    sub = args[0]
    data = state.load()
    channels = data.get("channels", [])

    if sub == "list":
        if not channels:
            return {"lines": ["（无 channel）"]}
        return {
            "lines": [f"  {i + 1}. {c['username']}" for i, c in enumerate(channels)]
        }

    if sub == "add":
        username = ctx.ask_line("Chat 用户名: ").strip()
        password = ctx.ask_secret("Chat 密码: ")
        if not username or not password:
            return {"error": "用户名和密码不能为空"}
        try:
            token, self_id = ChatAdapter.obtain_token(username, password)
        except Unauthorized:
            return {"error": "Chat 账号或密码错误"}
        except HttpError as exc:
            return {"error": f"Chat 登录失败: {exc}"}
        channels = [c for c in channels if c["username"] != username]
        channels.append({"username": username, "chat_token": token})
        data["channels"] = channels
        state.save(data)
        lines = [f"已添加 channel: {username} ({self_id})"]
        msg = _ensure(ctx)
        if msg:
            lines.append(msg)
        elif not data.get("studio_token"):
            lines.append("尚未登录 — 执行 /login 后自动连接")
        return {"lines": lines}

    if sub == "rm":
        if len(args) < 2 or not args[1].isdigit():
            return {"error": "用法: /channel rm <n>"}
        idx = int(args[1]) - 1
        if idx < 0 or idx >= len(channels):
            return {"error": "序号超出范围（见 /channel list）"}
        removed = channels.pop(idx)
        data["channels"] = channels
        state.save(data)
        _ensure(ctx)
        return {"lines": [f"已删除 channel: {removed['username']}"]}

    return {"error": "用法: /channel add | rm <n> | list"}


def cmd_status(ctx: Context, args: list[str]) -> dict:
    snap = ctx.events.snapshot()
    running = bool(ctx.runtime and ctx.runtime.is_running())
    lines = [
        f"status      : {snap.get('status', 'idle')}{'' if running else ' (daemon 未运行)'}",
        f"studio      : {snap.get('studio_url', config.STUDIO_BASE_URL)}",
        f"username    : {snap.get('username') or '-'}",
        f"bridge_id   : {snap.get('bridge_id') or '-'}",
        f"machine_id  : {snap.get('machine_id') or '-'}",
        f"in (5m)     : {snap.get('in_count_5m', 0)}",
        f"unsent      : {snap.get('outbound_pending', 0)}",
    ]
    if snap.get("last_error"):
        lines.append(f"last_error  : {snap['last_error']}")
    chans = snap.get("channels", [])
    if chans:
        lines.append("channels:")
        for c in chans:
            lines.append(
                f"  - {c['handle']} self={c.get('platform_self_id') or '-'} "
                f"peers={c.get('peers_count', 0)} "
                f"{'online' if c.get('online') else 'offline'}"
            )
    return {"lines": lines}


def cmd_log(ctx: Context, args: list[str]) -> dict:
    return {"logs": ctx.events.tail(50), "follow": "-f" in args}


def cmd_studio(ctx: Context, args: list[str]) -> dict:
    return {"lines": [config.STUDIO_BASE_URL]}


def cmd_quit(ctx: Context, args: list[str]) -> dict:
    _stop_daemon(ctx)
    return {"quit": True}


DISPATCH = {
    "help": cmd_help,
    "state": cmd_state,
    "login": cmd_login,
    "logout": cmd_logout,
    "status": cmd_status,
    "channel": cmd_channel,
    "log": cmd_log,
    "studio": cmd_studio,
    "quit": cmd_quit,
}

# Commands allowed before a state dir is set.
NO_STATE_OK = {"help", "state", "quit"}
