"""Headless bridge entrypoint.

A non-interactive subprocess mode: one process per Studio account, with
credentials injected via flags instead of a password prompt — intended
for a supervisor process to spawn. (Retained for a future cloud/host
supervisor; no in-repo caller today.) Differs from REPL/GUI only in
*how credentials arrive* (flags vs. password prompt) and *how lifecycle
signals surface* (SIGTERM + exit codes vs. /quit / window close); all
daemon reconcile logic lives in :mod:`laborster_bridge.commands`, same
as the other two frontends.

Only the ``chat`` adapter is registered in headless mode. The chat
``LoginFlow`` is degenerate so ``commands.ensure_chat_channel`` writes
the empty credential directly — equivalent to driving the flow to
``Done({})``.

Exit codes (a supervisor may map these to its own status):
  0  graceful shutdown via SIGTERM/SIGINT
  2  Studio token revoked (401 surfaced by HeartbeatActor) — auth_error
  3  startup/config error
  4  channel already bound by another online bridge (Studio 409) — the
     process exits so its heartbeat stops and a supervisor sees it go
     offline instead of a zombie "running".
"""

from __future__ import annotations

import signal
import sys
import threading

from . import commands, config
from .events import Events


def run(args) -> int:
    config.set_studio_base_url(args.studio_url)
    try:
        config.set_state_root(args.state)
    except Exception as exc:
        print(f"--state 无效: {exc}", file=sys.stderr)
        return 3

    events = Events()
    stop_event = threading.Event()
    auth_error_flag = threading.Event()
    conflict_flag = threading.Event()

    def _stub(_prompt: str) -> str:
        # Headless never prompts; if any code path tries, that's a bug.
        raise RuntimeError("headless mode: interactive prompt invoked")

    ctx = commands.Context(events, ask_line=_stub, ask_secret=_stub)

    msg = commands.install_studio_token(
        ctx,
        account_id=args.account_id,
        token=args.token,
        machine_id=args.machine_id,
        display_name=args.display_name,
    )
    if msg and msg.startswith("打开账号失败"):
        print(msg, file=sys.stderr)
        return 3

    commands.ensure_chat_channel(ctx)

    def _on_auth_error() -> None:
        auth_error_flag.set()
        stop_event.set()

    def _on_fatal() -> None:
        conflict_flag.set()
        stop_event.set()

    commands.start_daemon(
        ctx, extra_on_auth_error=_on_auth_error, extra_on_fatal=_on_fatal
    )

    # Mirror events.log() output to stdout (→ the supervisor's logs).
    # `follow()` blocks on a condvar — no polling, no missed lines
    # under load.
    def _log_pump() -> None:
        for ln in events.follow(stop_event):
            print(
                f"{ln['t']} [{ln['src']}/{ln['level']}] {ln['msg']}",
                flush=True,
            )

    threading.Thread(target=_log_pump, name="log-pump", daemon=True).start()

    def _handle_signal(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    print(
        f"headless bridge started · account={args.account_id} "
        f"machine_id={args.machine_id} studio={config.STUDIO_BASE_URL}",
        flush=True,
    )
    try:
        stop_event.wait()
    finally:
        # Same teardown path the REPL's /quit takes: stop daemon, close
        # store, release flock.
        commands.cmd_quit(ctx, [])

    if auth_error_flag.is_set():
        print("Studio session 已失效 — 退出码 2", flush=True)
        return 2
    if conflict_flag.is_set():
        print("channel 已被另一台在线 Bridge 占用 — 退出码 4", flush=True)
        return 4
    return 0
