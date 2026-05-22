"""Slash-command handlers. Each returns a dict the REPL renders.

Return shape: {"lines": [str, ...]} for normal output, or
{"error": str}. Special key {"quit": True} ends the REPL.

State model: under ``state_root`` there is one sub-directory per Studio
account containing ``state.db``. Exactly one account is "active" in this
process — its store is held by ``Context.store``. Startup auto-opens the
most recently used account; ``/account use`` switches; ``/login``
creates a new account dir when handshake returns an unseen account_id.
"""

from __future__ import annotations

from . import adapters, config, store as store_mod
from .events import Events
from .http import HttpError, Unauthorized
from .runtime import BridgeRuntime
from .store import Store, StoreLockError
from .studio_client import StudioClient

DEFAULT_CHANNEL_PLATFORM = "chat"

HELP = """\
Laborster Bridge — 命令

  /help                    显示本指南
  /state <path>            设置状态目录根（无默认；每次启动都要指定）
  /login                   输入 Studio 账号密码 → 落 token / machine_id
  /logout                  清除当前账号的 Studio token（自动断开）
  /status                  daemon 与各 channel 状态快照
  /account list            列出本机已绑定的所有 Studio 账号
  /account use <account>   切换到指定账号（按 id 或 username 前缀匹配）
  /account remove <acc>    彻底删除一个本地账号（含全部消息与凭据）
  /channel add [platform]  启动登录流绑定一个 channel（默认 platform=chat）
  /channel rm <n>          删除第 n 个 channel（见 /channel list）
  /channel list            列出已绑定 channel（不含任何凭据）
  /log [-f]                查看日志；-f 跟随（Ctrl-C 或 EOF 退出）
  /studio                  打印 Studio 地址
  /quit                    停 daemon 并退出
"""


class Context:
    def __init__(self, events: Events, ask_line, ask_secret) -> None:
        self.events = events
        self.runtime: BridgeRuntime | None = None
        self.store: Store | None = None
        self.account_id: str | None = None
        self.ask_line = ask_line
        self.ask_secret = ask_secret


# --- account lifecycle ---------------------------------------------------

def _close_account(ctx: Context) -> None:
    """Stop the daemon, close the store, release the flock."""
    _stop_daemon(ctx)
    if ctx.store is not None:
        ctx.store.close()
    ctx.store = None
    ctx.account_id = None


def _open_account(ctx: Context, account_id: str) -> str | None:
    """Open ``<state_root>/<account_id>/state.db`` and mark it active.

    Returns an error message string on failure, ``None`` on success.
    """
    if ctx.account_id == account_id and ctx.store is not None:
        return None
    _close_account(ctx)
    try:
        ctx.store = Store(config.db_path(account_id))
    except StoreLockError as exc:
        return str(exc)
    ctx.account_id = account_id
    return None


def _ensure(ctx: Context) -> str | None:
    """Reconcile the daemon with the active account's state.

    The daemon runs whenever the active account has a Studio token AND
    at least one channel. Called on launch and after every mutation.
    """
    if ctx.store is None:
        _stop_daemon(ctx)
        return None
    ready = bool(ctx.store.kv_get("studio_token") and ctx.store.channels())
    _stop_daemon(ctx)
    if not ready:
        return None
    ctx.runtime = _make_runtime(ctx)
    ctx.runtime.start()
    return "daemon 已自动连接（/status 查看）"


def _stop_daemon(ctx: Context) -> None:
    if ctx.runtime and ctx.runtime.is_running():
        ctx.runtime.stop()
    ctx.runtime = None


def _make_runtime(ctx: Context) -> BridgeRuntime:
    store = ctx.store
    assert store is not None
    account_id = ctx.account_id

    def get_token() -> str | None:
        return store.kv_get("studio_token")

    def get_machine_id() -> str | None:
        return store.kv_get("machine_id")

    def base_info() -> dict:
        return {
            "studio_url": config.STUDIO_BASE_URL,
            "username": store.kv_get("display_name"),
            "machine_id": store.kv_get("machine_id"),
            "account_id": account_id,
        }

    token_at_start = store.kv_get("studio_token")

    def on_auth_error() -> None:
        # Old runtimes (replaced by a fresh /login) must not clobber the
        # new token the user just stored.
        if store.kv_get("studio_token") != token_at_start:
            return
        store.kv_set("studio_token", None)
        ctx.events.log("core", "err", "Studio token 已失效并清除，请重新 /login")

    return BridgeRuntime(
        StudioClient(get_token, get_machine_id),
        store,
        ctx.events,
        base_info,
        on_auth_error,
    )


def autostart(ctx: Context) -> str | None:
    """At REPL launch: open the most-recently-used account, then reconcile."""
    if not config.has_state_root():
        return None
    accounts = store_mod.list_accounts(config.state_root())
    if not accounts:
        return None
    err = _open_account(ctx, accounts[0]["account_id"])
    if err:
        ctx.events.log("core", "err", err)
        return None
    return _ensure(ctx)


# --- LoginFlow runner (CLI side) ----------------------------------------

def _run_login_flow_cli(
    ctx: Context, platform: str
) -> tuple[adapters.Credential | None, str | None]:
    """Drive an adapter LoginFlow with the REPL's ask_line/ask_secret."""
    try:
        factory = adapters.get(platform)
    except KeyError:
        return None, (
            f"未知 platform: {platform}"
            f"（已注册: {', '.join(adapters.platforms())}）"
        )
    try:
        flow = factory.begin_login()
    except adapters.TransientError as exc:
        return None, f"启动登录失败: {exc}"

    while True:
        step = flow.current()
        if isinstance(step, adapters.Done):
            return step.credential, None
        if isinstance(step, adapters.Failed):
            return None, f"登录终止: {step.reason}"
        if isinstance(step, adapters.PromptInput):
            if step.error:
                ctx.events.log("login", "err", step.error)
            answers: dict[str, str] = {}
            for field in step.fields:
                prompt = f"{field.label}: "
                if field.secret:
                    answers[field.name] = ctx.ask_secret(prompt)
                else:
                    answers[field.name] = ctx.ask_line(prompt)
            try:
                flow.submit(answers)
            except adapters.TransientError as exc:
                return None, f"网络错误: {exc}"
            continue
        if isinstance(step, adapters.WaitForExternal):
            return None, "CLI 暂不支持需要等待外部交互的登录流（请用 GUI）"
        return None, f"未知 step 类型: {type(step).__name__}"


def _persist_channel(
    ctx: Context, platform: str, credential: adapters.Credential
) -> dict:
    """Add a credential row. Dedup by (platform, self_id) against existing rows."""
    if ctx.store is None:
        return {"error": "请先 /login"}
    factory = adapters.get(platform)
    try:
        self_id = factory.build(credential).platform_self_id
    except adapters.Unauthorized:
        return {"error": "凭据立即被拒绝（不应发生）"}
    except adapters.TransientError as exc:
        return {"error": f"无法解析 platform self id: {exc}"}

    # Drop any prior row for the same (platform, self_id).
    for ch in ctx.store.channels():
        if ch.platform != platform:
            continue
        try:
            existing = (
                adapters.get(platform).build(ch.credential).platform_self_id
            )
        except Exception:
            continue
        if existing == self_id:
            ctx.store.delete_channel(ch.id)

    ctx.store.add_channel(platform, credential)
    lines = [f"已绑定 channel: {platform} / {self_id}"]
    msg = _ensure(ctx)
    if msg:
        lines.append(msg)
    elif not ctx.store.kv_get("studio_token"):
        lines.append("尚未登录 — 执行 /login 后自动连接")
    return {"lines": lines}


# --- commands -----------------------------------------------------------

def cmd_help(ctx: Context, args: list[str]) -> dict:
    return {"lines": HELP.splitlines()}


def cmd_state(ctx: Context, args: list[str]) -> dict:
    if not args:
        if config.has_state_root():
            return {"lines": [f"state root: {config.state_root()}"]}
        return {"error": "用法: /state <path>"}
    try:
        d = config.set_state_root(args[0])
    except Exception as exc:
        return {"error": str(exc)}
    lines = [f"state root: {d}"]
    msg = autostart(ctx)
    if msg:
        lines.append(msg)
    return {"lines": lines}


def cmd_login(ctx: Context, args: list[str]) -> dict:
    if len(args) >= 2:
        username, password = args[0].strip(), args[1]
    else:
        username = ctx.ask_line("Studio 用户名: ").strip()
        password = ctx.ask_secret("Studio 密码: ")
    if not username or not password:
        return {"error": "用户名和密码不能为空"}

    # If currently active account already has a machine_id, prefer it
    # (re-login to the same account). Otherwise the server issues a new
    # one and we'll persist it into whichever account dir handshake
    # returns.
    machine_id = ctx.store.kv_get("machine_id") if ctx.store else None

    try:
        r = StudioClient(lambda: None).handshake(username, password, machine_id)
    except Unauthorized:
        return {"error": "账号或密码错误"}
    except HttpError as exc:
        return {"error": f"handshake 失败: {exc}"}

    account_id = r["account_id"]
    err = _open_account(ctx, account_id)
    if err:
        return {"error": err}
    assert ctx.store is not None
    ctx.store.kv_set("studio_token", r["token"])
    ctx.store.kv_set("machine_id", r["machine_id"])
    ctx.store.kv_set("display_name", username)

    lines = [
        "登录成功",
        f"  account_id : {account_id}",
        f"  machine_id : {r['machine_id']}",
    ]
    msg = _ensure(ctx)
    if msg:
        lines.append(msg)
    elif not ctx.store.channels():
        lines.append("还没有 channel — 执行 /channel add")
    return {"lines": lines}


def cmd_logout(ctx: Context, args: list[str]) -> dict:
    if ctx.store is None:
        return {"error": "当前没有活跃账号"}
    _stop_daemon(ctx)
    ctx.store.kv_set("studio_token", None)
    return {"lines": ["已登出，Studio token 已清除（其他状态保留）"]}


def _match_account(token: str) -> dict | None:
    """Match by exact account_id or unique display_name prefix."""
    accounts = store_mod.list_accounts(config.state_root())
    for a in accounts:
        if a["account_id"] == token:
            return a
    matches = [
        a for a in accounts
        if (a.get("display_name") or "").startswith(token)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def cmd_account(ctx: Context, args: list[str]) -> dict:
    if not args:
        return {"error": "用法: /account list | use <acc> | remove <acc>"}
    sub = args[0]

    if sub == "list":
        accounts = store_mod.list_accounts(config.state_root())
        if not accounts:
            return {"lines": ["（无账号 — 执行 /login）"]}
        lines = []
        for a in accounts:
            marker = "*" if a["account_id"] == ctx.account_id else " "
            name = a.get("display_name") or "-"
            flag = "logged-in" if a["has_token"] else "logged-out"
            lines.append(
                f"  {marker} {a['account_id']}  ({name})  "
                f"channels={a['channel_count']}  {flag}  "
                f"last={a.get('last_active_at') or '-'}"
            )
        return {"lines": lines}

    if sub == "use":
        if len(args) < 2:
            return {"error": "用法: /account use <account_id|name_prefix>"}
        target = _match_account(args[1])
        if not target:
            return {"error": f"未找到账号: {args[1]}（/account list 查看）"}
        err = _open_account(ctx, target["account_id"])
        if err:
            return {"error": err}
        lines = [
            f"已切换到账号 {target['account_id']}"
            f"  ({target.get('display_name') or '-'})"
        ]
        msg = _ensure(ctx)
        if msg:
            lines.append(msg)
        return {"lines": lines}

    if sub == "remove":
        if len(args) < 2:
            return {"error": "用法: /account remove <account_id|name_prefix>"}
        target = _match_account(args[1])
        if not target:
            return {"error": f"未找到账号: {args[1]}"}
        aid = target["account_id"]
        if ctx.account_id == aid:
            _close_account(ctx)
        # rm -rf the account dir
        import shutil
        try:
            shutil.rmtree(config.account_dir(aid))
        except OSError as exc:
            return {"error": f"删除失败: {exc}"}
        return {"lines": [f"已删除账号 {aid}"]}

    return {"error": "用法: /account list | use <acc> | remove <acc>"}


def cmd_channel(ctx: Context, args: list[str]) -> dict:
    if not args:
        return {"error": "用法: /channel add [platform] | rm <n> | list"}
    sub = args[0]
    if ctx.store is None:
        return {"error": "请先 /login"}
    channels = ctx.store.channels()

    if sub == "list":
        if not channels:
            return {"lines": ["（无 channel）"]}
        lines = []
        for i, c in enumerate(channels):
            try:
                self_id = (
                    adapters.get(c.platform).build(c.credential).platform_self_id
                )
                lines.append(f"  {i + 1}. {c.platform}  {self_id}")
            except Exception as exc:
                lines.append(f"  {i + 1}. {c.platform}  (无法解析: {exc})")
        return {"lines": lines}

    if sub == "add":
        platform = args[1].strip() if len(args) >= 2 else DEFAULT_CHANNEL_PLATFORM
        credential, err = _run_login_flow_cli(ctx, platform)
        if err is not None:
            return {"error": err}
        assert credential is not None
        return _persist_channel(ctx, platform, credential)

    if sub == "rm":
        if len(args) < 2 or not args[1].isdigit():
            return {"error": "用法: /channel rm <n>"}
        idx = int(args[1]) - 1
        if idx < 0 or idx >= len(channels):
            return {"error": "序号超出范围（见 /channel list）"}
        removed = channels[idx]
        ctx.store.delete_channel(removed.id)
        _ensure(ctx)
        return {"lines": [f"已删除 channel #{idx + 1} ({removed.platform})"]}

    return {"error": "用法: /channel add [platform] | rm <n> | list"}


def cmd_status(ctx: Context, args: list[str]) -> dict:
    snap = ctx.events.snapshot()
    running = bool(ctx.runtime and ctx.runtime.is_running())
    lines = [
        f"status      : {snap.get('status', 'idle')}{'' if running else ' (daemon 未运行)'}",
        f"studio      : {snap.get('studio_url', config.STUDIO_BASE_URL)}",
        f"account_id  : {snap.get('account_id') or ctx.account_id or '-'}",
        f"username    : {snap.get('username') or '-'}",
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
                f"  - {c.get('platform', '?')}/{c.get('platform_self_id') or '-'} "
                f"convs={c.get('conv_count', 0)} "
                f"{'online' if c.get('online') else 'offline'}"
            )
    return {"lines": lines}


def cmd_log(ctx: Context, args: list[str]) -> dict:
    return {"logs": ctx.events.tail(50), "follow": "-f" in args}


def cmd_studio(ctx: Context, args: list[str]) -> dict:
    return {"lines": [config.STUDIO_BASE_URL]}


def cmd_quit(ctx: Context, args: list[str]) -> dict:
    _close_account(ctx)
    return {"quit": True}


DISPATCH = {
    "help": cmd_help,
    "state": cmd_state,
    "login": cmd_login,
    "logout": cmd_logout,
    "status": cmd_status,
    "account": cmd_account,
    "channel": cmd_channel,
    "log": cmd_log,
    "studio": cmd_studio,
    "quit": cmd_quit,
}

NO_STATE_OK = {"help", "state", "quit"}
