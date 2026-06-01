#!/usr/bin/env python3
"""scripts/loadtest.py — Full-client capacity load test.

Each simulated customer is "fully running": a real headless Bridge runtime
(``python -m laborster_bridge --headless``) for the bridge plane, PLUS a thin
stdlib renderer driver for the operator-UI polls and the chat-sandbox
``messages/after`` long-poll — i.e. the two planes the runtime does not cover
(those live in the Electron renderer, not the sidecar).

v1 scope: idle long-polls only. No message flow is generated; the bridge
``/api/bridge/outbound`` long-poll and the sandbox ``messages/after`` long-poll
just hang and time out, which is exactly the steady-state connection load we
want to map. ``--msg-rate`` is reserved for v2 and not wired yet.

Per simulated customer the server sees, steadily:
  * bridge: heartbeat 15s, takeovers 10s, outbound long-poll (re-armed)
  * UI:     /conversations 3s, /bridges + /inboxes 10s, /personas once
  * chat:   /chat/conversations 5s, messages/after long-poll (re-armed)

So each idle customer holds ~2 concurrent long-polls. Ramp ``--clients`` and
watch where latency / errors / PG connections degrade.

Same shape as seed.py / backup.sh / test.sh: env file first, then options.
The project name is read from the env file's COMPOSE_PROJECT_NAME, and the
user-api / admin-api container IPs are resolved live from compose labels — on
Linux the host routes straight to the container, so no published port and no
edge profile are needed. Bring the instance up with just the local profiles:

    docker compose --env-file .env.debug --profile storage --profile app up -d

Each run mints a fresh batch of randomly-named throwaway accounts (so reruns
never collide), creates them via the (unauthenticated) admin-api, then drives
the full client load. Account creation failure is fatal.

Run it with the sidecar's venv interpreter, NOT system python: this script is
pure stdlib, but it spawns the bridge runtime with its own ``sys.executable``,
so the launching interpreter must have the sidecar's deps (prompt_toolkit,
certifi). The runtime venv already has them — use it and the subprocess
inherits it (checked up front, before any account is created):

    desktop/sidecar/.venv/bin/python scripts/loadtest.py .env.debug --clients 100
    desktop/sidecar/.venv/bin/python scripts/loadtest.py .env.debug --clients 2 \
        --no-bridge --duration 120

(System python works only with --no-bridge, which skips the runtime entirely.)

To watch server-side connection counts, run a one-line ``psql`` on the stack
host yourself (see project notes) — that stays out of here.
"""

from __future__ import annotations

import argparse
import json
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SIDECAR_DIR = REPO_ROOT / "desktop" / "sidecar"
USER_PORT = 23456
ADMIN_PORT = 23457

# Cadences mirrored from the real clients:
#   desktop/src/queries.ts (renderer refetchInterval)
#   desktop/sidecar/laborster_bridge/runtime.py (bridge actors)
CONVERSATIONS_S = 3
BRIDGES_S = 10
INBOXES_S = 10
CHAT_CONVERSATIONS_S = 5
AFTER_TIMEOUT_S = 30  # chat messages/after long-poll server timeout

# Each run mints throwaway accounts under a fresh random batch tag, so reruns
# never collide: lt_<batch>_0000, lt_<batch>_0001, … sharing one password.
USERNAME_PREFIX = "lt"
ADMIN_ACCOUNTS_PATH = "/api/admin/accounts"


# --------------------------------------------------------------------------
# logging (ANSI, matches seed_dev.py)
# --------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"\033[36m[lt]\033[0m {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"\033[32m[ok]\033[0m {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"\033[33m[warn]\033[0m {msg}", flush=True)


def die(msg: str) -> "None":
    print(f"\033[31m[fail]\033[0m {msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------

@dataclass
class ClassStat:
    count: int = 0
    errors: int = 0
    # latency samples in ms; capped so a long run at high N stays bounded.
    samples: list[float] = field(default_factory=list)


class Metrics:
    SAMPLE_CAP = 50_000

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._classes: dict[str, ClassStat] = {}

    def record(self, name: str, elapsed_ms: float, ok_: bool) -> None:
        with self._lock:
            cs = self._classes.get(name)
            if cs is None:
                cs = self._classes[name] = ClassStat()
            cs.count += 1
            if not ok_:
                cs.errors += 1
            elif len(cs.samples) < self.SAMPLE_CAP:
                cs.samples.append(elapsed_ms)

    def snapshot(self) -> dict[str, ClassStat]:
        with self._lock:
            # shallow copy is enough for read-only summary
            return {k: ClassStat(v.count, v.errors, list(v.samples))
                    for k, v in self._classes.items()}


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = int(round((p / 100.0) * (len(sorted_vals) - 1)))
    return sorted_vals[max(0, min(k, len(sorted_vals) - 1))]


def print_summary(metrics: Metrics, elapsed_s: float) -> None:
    snap = metrics.snapshot()
    print()
    print("=" * 78)
    print(f"client-side summary  (run {elapsed_s:.0f}s)")
    print("-" * 78)
    print(f"{'CLASS':<32}{'count':>8}{'err':>6}{'p50':>8}{'p95':>8}{'p99':>8}  (ms)")
    for name in sorted(snap):
        cs = snap[name]
        s = sorted(cs.samples)
        # long-polls are *meant* to take ~30s; flag them so the numbers aren't
        # mistaken for latency regressions.
        tag = " (long-poll)" if "after" in name or "outbound" in name else ""
        print(f"{name:<32}{cs.count:>8}{cs.errors:>6}"
              f"{_pct(s, 50):>8.0f}{_pct(s, 95):>8.0f}{_pct(s, 99):>8.0f}{tag}")
    print("=" * 78)


# --------------------------------------------------------------------------
# HTTP (stdlib)
# --------------------------------------------------------------------------

def http_call(method: str, url: str, token: str | None = None,
              body: dict | None = None, timeout: float = 15.0) -> tuple[int, float, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8", "replace")
            return resp.status, (time.monotonic() - t0) * 1000, payload
    except urllib.error.HTTPError as exc:
        return exc.code, (time.monotonic() - t0) * 1000, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # URLError, timeout, conn reset, ...
        return 0, (time.monotonic() - t0) * 1000, str(exc)


# --------------------------------------------------------------------------
# env file + container-IP discovery (host → container, mirrors seed.py)
# --------------------------------------------------------------------------

def project_from_env_file(path: Path) -> str:
    """Read COMPOSE_PROJECT_NAME from a docker env file (KEY=VALUE lines)."""
    if not path.is_file():
        path = REPO_ROOT / path
    if not path.is_file():
        die(f"env file not found: {path}")
    project = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key.strip() == "COMPOSE_PROJECT_NAME":
            project = val.strip().strip('"').strip("'")
    if not project:
        die(f"{path}: COMPOSE_PROJECT_NAME not set")
    return project


def _docker(*args: str) -> str:
    try:
        out = subprocess.run(["docker", *args], capture_output=True, text=True, check=True)
    except FileNotFoundError:
        die("missing required command: docker")
    except subprocess.CalledProcessError as exc:
        die(f"docker {' '.join(args)} failed: {exc.stderr.strip()}")
    return out.stdout.strip()


def resolve_service_ip(project: str, service: str) -> str:
    """Container IP for one compose service of the project (live, by label)."""
    cid = _docker(
        "ps", "-q",
        "--filter", f"label=com.docker.compose.project={project}",
        "--filter", f"label=com.docker.compose.service={service}",
    )
    if not cid:
        die(f"no running {service} for project {project!r}. Start it first:\n"
            f"  docker compose --env-file <envfile> --profile storage --profile app up -d")
    cid = cid.splitlines()[0]
    ip = _docker("inspect", "-f",
                 "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", cid)
    if not ip:
        die(f"{service} container {cid[:12]} has no network IP")
    return ip


# --------------------------------------------------------------------------
# account creation (admin-api over HTTP; endpoint is unauthenticated)
# --------------------------------------------------------------------------

def create_accounts(admin_url: str, usernames: list[str], password: str) -> None:
    """Create every test account up front. Random names shouldn't collide, but
    a pre-existing account (409) is tolerated; any other non-2xx is fatal."""
    created = skipped = 0
    for u in usernames:
        code, _, payload = http_call(
            "POST", f"{admin_url}{ADMIN_ACCOUNTS_PATH}",
            body={"username": u, "password": password, "display_name": u},
            timeout=15.0)
        if code in (200, 201):
            created += 1
        elif code == 409 and "用户名已存在" in payload:
            # Only a genuine username clash is skippable. Random batch names
            # shouldn't clash, but a rerun with the same batch could.
            skipped += 1
        elif code == 409:
            # Other 409s mean the account was NOT created (e.g. "尚未配置任何
            # Provider") — silently skipping would hand handshake a non-existent
            # account and surface as a confusing 401. Fail loud instead.
            die(f"create account {u} rejected: HTTP 409 — {payload[:200]}\n"
                f"  (seed a provider first: python scripts/seed.py {{envfile}} scripts/seed.*.json)")
        else:
            die(f"create account {u} failed: HTTP {code} — {payload[:200]}\n"
                f"  (is admin-api reachable at {admin_url}?)")
    ok(f"accounts ready: {created} created, {skipped} already existed")


# --------------------------------------------------------------------------
# per-client
# --------------------------------------------------------------------------

@dataclass
class Client:
    username: str
    password: str
    base_url: str
    token: str = ""
    account_id: str = ""
    machine_id: str = ""
    conv_id: str = ""  # chat sandbox conversation for the after long-poll
    runtime: subprocess.Popen | None = None
    log_file: object = None


def handshake(c: Client) -> None:
    code, _, payload = http_call(
        "POST", f"{c.base_url}/api/bridge/handshake",
        body={"username": c.username, "password": c.password, "machine_id": None})
    if code != 200:
        die(f"handshake failed for {c.username}: HTTP {code} — {payload[:200]}")
    r = json.loads(payload)
    c.token, c.account_id, c.machine_id = r["token"], r["account_id"], r["machine_id"]


def check_runtime_importable() -> None:
    """The headless runtime is launched with sys.executable + cwd=sidecar, so
    that interpreter must import the sidecar's deps (prompt_toolkit via repl;
    certifi via http). Fail loud here instead of N silent subprocess crashes."""
    res = subprocess.run(
        [sys.executable, "-c", "import prompt_toolkit, certifi"],
        cwd=str(SIDECAR_DIR), capture_output=True, text=True)
    if res.returncode != 0:
        die("the bridge runtime needs prompt_toolkit + certifi in this Python "
            f"({sys.executable}).\n  install: {sys.executable} -m pip install prompt_toolkit certifi\n"
            f"  ({res.stderr.strip().splitlines()[-1] if res.stderr.strip() else 'import failed'})")


def start_runtime(c: Client, state_root: Path) -> None:
    # The headless runtime's --studio-url is the api base the bridge plane
    # talks to — same origin the renderer load uses.
    c.log_file = open(state_root / f"{c.username}.runtime.log", "w")
    c.runtime = subprocess.Popen(
        [sys.executable, "-m", "laborster_bridge", "--headless",
         "--studio-url", c.base_url, "--state", str(state_root),
         "--account-id", c.account_id, "--token", c.token,
         "--machine-id", c.machine_id, "--display-name", c.username],
        cwd=str(SIDECAR_DIR), stdout=c.log_file, stderr=subprocess.STDOUT)


def setup_sandbox(c: Client) -> None:
    """Create one chat contact (auto-creates its 1:1 conversation) and resolve
    the conversation id so the renderer's after long-poll has a target."""
    code, _, payload = http_call(
        "POST", f"{c.base_url}/api/chat/contacts", token=c.token,
        body={"nickname": f"{c.username}-peer"})
    if code not in (200, 409):
        warn(f"{c.username}: create contact HTTP {code} — {payload[:160]}")
    code, _, payload = http_call(
        "GET", f"{c.base_url}/api/chat/conversations", token=c.token)
    if code == 200:
        convs = json.loads(payload)
        if convs:
            c.conv_id = convs[0]["id"]
    if not c.conv_id:
        warn(f"{c.username}: no chat conversation; sandbox after-poll disabled")


def renderer_poll_loop(c: Client, m: Metrics, stop: threading.Event) -> None:
    """One thread driving all periodic (snappy) polls on a time scheduler."""
    base = c.base_url
    tasks: list[tuple[float, str, str]] = [
        (CONVERSATIONS_S, "ui.conversations", f"{base}/api/conversations"),
        (BRIDGES_S, "ui.bridges", f"{base}/api/bridges"),
        (INBOXES_S, "ui.inboxes", f"{base}/api/inboxes"),
        (CHAT_CONVERSATIONS_S, "chat.conversations", f"{base}/api/chat/conversations"),
    ]
    # personas: once at start, like usePersonas() (no refetchInterval).
    code, ms, _ = http_call("GET", f"{base}/api/personas", token=c.token)
    m.record("ui.personas", ms, code == 200)

    next_due = {name: 0.0 for _, name, _ in tasks}
    while not stop.is_set():
        now = time.monotonic()
        for interval, name, url in tasks:
            if now >= next_due[name]:
                code, ms, _ = http_call("GET", url, token=c.token)
                m.record(name, ms, code == 200)
                next_due[name] = now + interval
        stop.wait(0.5)


def renderer_after_loop(c: Client, m: Metrics, stop: threading.Event) -> None:
    """One thread holding the chat messages/after long-poll, re-armed on return.
    Mirrors useChatMessages() in desktop/src/ChatSandbox.tsx."""
    if not c.conv_id:
        return
    url = (f"{c.base_url}/api/chat/conversations/{c.conv_id}"
           f"/messages/after?last_id=0&timeout={AFTER_TIMEOUT_S}")
    while not stop.is_set():
        code, ms, _ = http_call("GET", url, token=c.token, timeout=AFTER_TIMEOUT_S + 8)
        m.record("chat.after", ms, code == 200)
        if code != 200:
            stop.wait(1.5)  # client retries after 1.5s on error


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Full-client capacity load test")
    p.add_argument("env_file", help="per-instance env file (e.g. .env.debug)")
    p.add_argument("--clients", type=int, required=True,
                   help="number of simulated customers (required, no default)")
    p.add_argument("--duration", type=int, default=None,
                   help="run seconds (default: run until Ctrl-C)")
    p.add_argument("--no-bridge", action="store_true", help="skip the bridge runtime plane")
    p.add_argument("--no-ui", action="store_true", help="skip the renderer (UI + sandbox) plane")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.clients < 1:
        die("--clients must be >= 1")

    # Resolve the instance: project from the env file, container IPs by label.
    project = project_from_env_file(Path(args.env_file))
    base_url = f"http://{resolve_service_ip(project, 'user-api')}:{USER_PORT}"
    admin_url = f"http://{resolve_service_ip(project, 'admin-api')}:{ADMIN_PORT}"
    state_root = Path(tempfile.mkdtemp(prefix="lt-state-"))

    # Fresh random batch per run so reruns never collide on usernames.
    batch = secrets.token_hex(3)
    password = secrets.token_urlsafe(12)
    usernames = [f"{USERNAME_PREFIX}_{batch}_{i:04d}" for i in range(args.clients)]
    dur = f"{args.duration}s" if args.duration else "until Ctrl-C"
    log(f"project={project}  clients={args.clients}  batch={batch}  duration={dur}")
    log(f"user-api={base_url}  admin-api={admin_url}")

    # phase 0: health
    code, _, _ = http_call("GET", f"{base_url}/api/health", timeout=10)
    if code != 200:
        die(f"api not healthy at {base_url} (GET /api/health → {code})")
    ok("api healthy")

    # phase 1: accounts (always created up front; failure is fatal)
    log(f"creating {len(usernames)} accounts via admin-api …")
    create_accounts(admin_url, usernames, password)

    # phase 2: handshake (mints token + bridge row per account)
    clients = [Client(username=u, password=password, base_url=base_url) for u in usernames]
    log("handshaking …")
    for c in clients:
        handshake(c)
    ok(f"handshook {len(clients)} accounts")

    # phase 3: start bridge runtimes
    if not args.no_bridge:
        check_runtime_importable()
        log("spawning headless bridge runtimes …")
        for c in clients:
            start_runtime(c, state_root)
        time.sleep(2)
        alive = sum(1 for c in clients if c.runtime and c.runtime.poll() is None)
        ok(f"runtimes alive: {alive}/{len(clients)}  (logs: {state_root}/*.runtime.log)")
        if alive < len(clients):
            warn("some runtimes exited early — check the per-client logs")

    # phase 4: renderer setup + loops
    metrics = Metrics()
    stop = threading.Event()
    if not args.no_ui:
        log("setting up sandbox conversations …")
        for c in clients:
            setup_sandbox(c)
        log("starting renderer drivers …")
        for c in clients:
            threading.Thread(target=renderer_poll_loop, args=(c, metrics, stop), daemon=True).start()
            threading.Thread(target=renderer_after_loop, args=(c, metrics, stop), daemon=True).start()

    # run
    ok(f"running {dur} — Ctrl-C to stop and print the summary")
    started = time.monotonic()
    try:
        stop.wait(args.duration)  # None ⇒ wait forever (until Ctrl-C)
    except KeyboardInterrupt:
        warn("interrupted")
    finally:
        stop.set()
        elapsed = time.monotonic() - started
        log("tearing down runtimes …")
        for c in clients:
            if c.runtime and c.runtime.poll() is None:
                c.runtime.send_signal(signal.SIGTERM)
        for c in clients:
            if c.runtime:
                try:
                    c.runtime.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    c.runtime.kill()
            if c.log_file:
                c.log_file.close()
        print_summary(metrics, elapsed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
