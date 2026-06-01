#!/usr/bin/env python3
"""scripts/loadtest.py — Full-client capacity load test (v2: live message flow).

Simulates N desktop clients scattered on real machines. Each client is a real
headless Bridge runtime (``python -m laborster_bridge --headless``) bound to the
chat-sandbox channel (the dogfood stand-in until a real IM channel exists), plus
a thin host-side driver that plays the *other party* and measures responsiveness.

Per client the harness sets up M "takeovers" — each takeover is one chat
conversation flipped to AI autoreply (takeover + persona + provider→fake-llm).
The harness then plays the peer: it posts messages into each conversation at
``--msg-rate`` msgs/sec. The runtime's chat adapter forwards them to Studio,
the worker calls fake-llm, and the reply flows back into the chat conversation;
the harness times peer-message → AI-reply-visible (reply lag).

Knobs (the only things a capacity sweep should turn):
    --clients   N    number of simulated desktop clients
    --takeovers M    autoreply conversations per client
    --msg-rate  λ    peer messages per second, per takeover
    --duration  s    steady-state seconds (default: until Ctrl-C)

So the offered inbound load is N×M×λ msgs/sec, each triggering one LLM round.
Ramp --clients (or M, or λ), watch where reply-lag / errors degrade — that knee
is the capacity. This script reports only client-observable signals; it makes no
assumption about where the server bottleneck is.

Same shape as seed.py / backup.sh / test.sh: env file first, then options. The
project name is read from the env file's COMPOSE_PROJECT_NAME; the user-api /
admin-api container IPs are resolved live from compose labels (on Linux the host
routes straight to the container, so no published port / edge profile needed):

    docker compose --env-file .env.debug --profile storage --profile app up -d

Each run mints a fresh batch of randomly-named throwaway accounts (so reruns
never collide), ensures a fake-llm provider exists, creates the accounts, then
drives the full client load. Account creation failure is fatal.

Run it with the sidecar's venv interpreter, NOT system python: the launching
interpreter spawns the bridge runtime with its own ``sys.executable``, so it must
carry the sidecar's deps (prompt_toolkit, certifi). The runtime venv has them:

    desktop/sidecar/.venv/bin/python scripts/loadtest.py .env.debug \
        --clients 10 --takeovers 3 --msg-rate 0.1 --duration 120

(System python works only with --no-bridge, which skips the runtime — but then
nothing forwards peer messages, so the reply flow won't turn. --no-bridge is for
debugging the harness/UI load alone.)
"""

from __future__ import annotations

import argparse
import json
import random
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

# Cadences mirrored from the real renderer (desktop/src/queries.ts).
CONVERSATIONS_S = 3
BRIDGES_S = 10
INBOXES_S = 10
CHAT_CONVERSATIONS_S = 5
AFTER_TIMEOUT_S = 30  # chat messages/after long-poll server timeout

# fake-llm provider (hostname resolves inside the docker network only; the
# worker — not this host — calls it, so that's fine).
FAKE_LLM_BASE_URL = "http://fake-llm:8080/v1"
FAKE_LLM_MODEL = "fake-model"

USERNAME_PREFIX = "lt"
ADMIN_ACCOUNTS_PATH = "/api/admin/accounts"

# Peer message vocabulary (content is irrelevant to the SUT; only flow matters).
_PEER_LINES = [
    "在吗", "你好", "这个怎么弄", "帮我看下", "急", "有空吗", "谢谢啦",
    "好的好的", "我再想想", "明天可以吗", "多少钱", "发个链接", "收到没",
]


# --------------------------------------------------------------------------
# logging (ANSI)
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
    samples: list[float] = field(default_factory=list)


class Metrics:
    SAMPLE_CAP = 100_000

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
            return {k: ClassStat(v.count, v.errors, list(v.samples))
                    for k, v in self._classes.items()}


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = int(round((p / 100.0) * (len(sorted_vals) - 1)))
    return sorted_vals[max(0, min(k, len(sorted_vals) - 1))]


def print_summary(metrics: Metrics, elapsed_s: float, replies: int, peers: int) -> None:
    snap = metrics.snapshot()
    print()
    print("=" * 84)
    print(f"client-side summary  (steady-state {elapsed_s:.0f}s)")
    print("-" * 84)
    print(f"{'CLASS':<24}{'count':>9}{'err':>7}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}  (ms)")
    for name in sorted(snap):
        cs = snap[name]
        s = sorted(cs.samples)
        tag = ""
        if name == "reply.lag":
            tag = "  <-- end-to-end peer→reply"
        elif "after" in name:
            tag = "  (long-poll; timeouts expected)"
        print(f"{name:<24}{cs.count:>9}{cs.errors:>7}"
              f"{_pct(s,50):>9.0f}{_pct(s,95):>9.0f}{_pct(s,99):>9.0f}{_pct(s,100):>9.0f}{tag}")
    print("-" * 84)
    rate = replies / elapsed_s if elapsed_s > 0 else 0
    print(f"peer messages sent: {peers}   AI replies observed: {replies}   "
          f"reply throughput: {rate:.2f}/s")
    print("=" * 84)


# --------------------------------------------------------------------------
# HTTP (stdlib)
# --------------------------------------------------------------------------

def http_call(method: str, url: str, token: str | None = None,
              body: dict | None = None, timeout: float = 15.0,
              machine: str | None = None) -> tuple[int, float, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if machine:
        req.add_header("X-Machine-Id", machine)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8", "replace")
            return resp.status, (time.monotonic() - t0) * 1000, payload
    except urllib.error.HTTPError as exc:
        return exc.code, (time.monotonic() - t0) * 1000, exc.read().decode("utf-8", "replace")
    except Exception as exc:
        return 0, (time.monotonic() - t0) * 1000, str(exc)


# --------------------------------------------------------------------------
# env file + container-IP discovery (host → container, mirrors seed.py)
# --------------------------------------------------------------------------

def project_from_env_file(path: Path) -> str:
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
# provider + account setup (admin-api, unauthenticated)
# --------------------------------------------------------------------------

def ensure_fake_llm_provider(admin_url: str, tag: str) -> str:
    """Create a ProviderConfig pointing at fake-llm, return its id. Account
    creation needs a provider to exist; conversations need one to autoreply."""
    code, _, payload = http_call(
        "POST", f"{admin_url}/api/admin/providers",
        body={"name": f"fakellm-{tag}", "base_url": FAKE_LLM_BASE_URL,
              "model": FAKE_LLM_MODEL, "api_key": "sk-fake"})
    if code in (200, 201):
        return json.loads(payload)["id"]
    # Reuse any existing fake-llm provider on 409 / re-run.
    code, _, lp = http_call("GET", f"{admin_url}/api/admin/providers")
    if code == 200:
        for p in json.loads(lp):
            if p.get("base_url", "").rstrip("/") == FAKE_LLM_BASE_URL.rstrip("/"):
                return p["id"]
        if json.loads(lp):
            return json.loads(lp)[0]["id"]
    die(f"could not create or find a fake-llm provider: HTTP {code} — {payload[:200]}")


def create_accounts(admin_url: str, usernames: list[str], password: str) -> None:
    created = skipped = 0
    for u in usernames:
        code, _, payload = http_call(
            "POST", f"{admin_url}{ADMIN_ACCOUNTS_PATH}",
            body={"username": u, "password": password, "display_name": u},
            timeout=15.0)
        if code in (200, 201):
            created += 1
        elif code == 409 and "用户名已存在" in payload:
            skipped += 1
        elif code == 409:
            die(f"create account {u} rejected: HTTP 409 — {payload[:200]}\n"
                f"  (seed a provider first: python scripts/seed.py {{envfile}} scripts/seed.*.json)")
        else:
            die(f"create account {u} failed: HTTP {code} — {payload[:200]}\n"
                f"  (is admin-api reachable at {admin_url}?)")
    ok(f"accounts ready: {created} created, {skipped} already existed")


# --------------------------------------------------------------------------
# per-client / per-takeover state
# --------------------------------------------------------------------------

@dataclass
class Takeover:
    contact_id: str = ""
    chat_conv_id: str = ""     # chat-sandbox conversation id
    studio_conv_id: str = ""   # studio conversation id (platform_conversation_id == chat_conv_id)
    last_seen_id: int = 0      # cursor for the reply observer
    last_peer_ts: float = 0.0  # monotonic of the most recent peer post
    awaiting: bool = False     # a peer msg is pending an AI reply
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass
class Client:
    username: str
    password: str
    base_url: str
    admin_url: str
    token: str = ""
    account_id: str = ""
    machine_id: str = ""
    persona_id: str = ""
    runtime: subprocess.Popen | None = None
    log_file: object = None
    takeovers: list[Takeover] = field(default_factory=list)


def handshake(c: Client) -> None:
    code, _, payload = http_call(
        "POST", f"{c.base_url}/api/bridge/handshake",
        body={"username": c.username, "password": c.password, "machine_id": None})
    if code != 200:
        die(f"handshake failed for {c.username}: HTTP {code} — {payload[:200]}")
    r = json.loads(payload)
    c.token, c.account_id, c.machine_id = r["token"], r["account_id"], r["machine_id"]


def check_runtime_importable() -> None:
    res = subprocess.run(
        [sys.executable, "-c", "import prompt_toolkit, certifi"],
        cwd=str(SIDECAR_DIR), capture_output=True, text=True)
    if res.returncode != 0:
        die("the bridge runtime needs prompt_toolkit + certifi in this Python "
            f"({sys.executable}).\n  install: {sys.executable} -m pip install prompt_toolkit certifi\n"
            f"  ({res.stderr.strip().splitlines()[-1] if res.stderr.strip() else 'import failed'})")


def start_runtime(c: Client, state_root: Path) -> None:
    c.log_file = open(state_root / f"{c.username}.runtime.log", "w")
    c.runtime = subprocess.Popen(
        [sys.executable, "-m", "laborster_bridge", "--headless",
         "--studio-url", c.base_url, "--state", str(state_root),
         "--account-id", c.account_id, "--token", c.token,
         "--machine-id", c.machine_id, "--display-name", c.username],
        cwd=str(SIDECAR_DIR), stdout=c.log_file, stderr=subprocess.STDOUT)


# --------------------------------------------------------------------------
# takeover ignition (host-side; the runtime forwards peer→studio)
# --------------------------------------------------------------------------

def create_persona(c: Client) -> None:
    code, _, payload = http_call(
        "POST", f"{c.base_url}/api/personas", token=c.token,
        body={"name": f"p-{c.username}", "persona_md": "你是测试助手，简洁回复。",
              "timezone": "UTC"})
    if code not in (200, 201):
        die(f"{c.username}: create persona HTTP {code} — {payload[:160]}")
    c.persona_id = json.loads(payload)["id"]


def _chat_conv_for_contact(c: Client, contact_id: str) -> str:
    code, _, payload = http_call("GET", f"{c.base_url}/api/chat/conversations", token=c.token)
    if code != 200:
        return ""
    for conv in json.loads(payload):
        if conv.get("contact_id") == contact_id:
            return conv["id"]
    return ""


def _studio_conv_map(c: Client) -> dict[str, str]:
    """One fetch of the account's studio conversations → {platform_conversation_id: id}."""
    code, _, payload = http_call("GET", f"{c.base_url}/api/conversations", token=c.token)
    if code != 200:
        return {}
    out: dict[str, str] = {}
    for item in json.loads(payload):
        conv = item.get("conversation", item)
        pcid = conv.get("platform_conversation_id")
        if pcid:
            out[pcid] = conv["id"]
    return out


# Ignition is split into three batch phases (see main phase 4) so the per-takeover
# wait on the runtime's 2s discovery cadence happens ONCE for the whole fleet,
# not serially per conversation:
#   A. create_takeover_stub  — contact + chat conv + first peer message (no wait)
#   B. resolve_studio_convs  — one wait loop until all studio convs materialise
#   C. ignite_takeover       — takeover + autoreply + persona + provider

def create_takeover_stub(c: Client, idx: int) -> Takeover | None:
    """Create a chat contact (auto-creates its 1:1 conversation) and post the
    first peer message so the runtime will forward it. No waiting here."""
    code, _, payload = http_call(
        "POST", f"{c.base_url}/api/chat/contacts", token=c.token,
        body={"nickname": f"{c.username}-peer{idx}"})
    if code not in (200, 201):
        warn(f"{c.username}#{idx}: create contact HTTP {code} — {payload[:140]}")
        return None
    t = Takeover(contact_id=json.loads(payload)["id"])
    t.chat_conv_id = _chat_conv_for_contact(c, t.contact_id)
    if not t.chat_conv_id:
        warn(f"{c.username}#{idx}: no chat conversation for contact")
        return None
    _post_peer(c, t)  # first peer message → runtime forwards → studio conv appears
    return t


def resolve_studio_convs(clients: list[Client], timeout: float = 90.0) -> int:
    """Batch-wait: poll each client's conversation list (once per round) until
    every stub's studio conversation has materialised. Returns the count resolved.
    One wait for the whole fleet, bounded by the runtime's forwarding cadence —
    not per-takeover."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = False
        for c in clients:
            if all(t.studio_conv_id for t in c.takeovers):
                continue
            cmap = _studio_conv_map(c)
            for t in c.takeovers:
                if not t.studio_conv_id and t.chat_conv_id in cmap:
                    t.studio_conv_id = cmap[t.chat_conv_id]
            if any(not t.studio_conv_id for t in c.takeovers):
                pending = True
        if not pending:
            break
        time.sleep(1.0)
    return sum(1 for c in clients for t in c.takeovers if t.studio_conv_id)


def ignite_takeover(c: Client, t: Takeover, provider_id: str) -> bool:
    """Flip the (now-materialised) studio conversation to AI autoreply."""
    code, _, payload = http_call(
        "PATCH", f"{c.base_url}/api/conversations/{t.studio_conv_id}", token=c.token,
        body={"takeover": True, "reply_policy": "autoreply", "persona_id": c.persona_id})
    if code != 200:
        warn(f"{c.username}: ignite PATCH HTTP {code} — {payload[:140]}")
        return False
    code, _, payload = http_call(
        "PATCH", f"{c.admin_url}/api/admin/conversations/{t.studio_conv_id}/provider",
        body={"provider_id": provider_id})
    if code not in (200, 204):
        warn(f"{c.username}: set-provider HTTP {code} — {payload[:140]}")
        return False
    return True


# --------------------------------------------------------------------------
# peer driver + reply observer (the "other party" + responsiveness metric)
# --------------------------------------------------------------------------

def _post_peer(c: Client, t: Takeover) -> bool:
    """Post one peer message into the chat conversation (sender_id=contact)."""
    code, ms, _ = http_call(
        "POST", f"{c.base_url}/api/chat/conversations/{t.chat_conv_id}/messages",
        token=c.token,
        body={"messages": [{"msg_type": "text",
                            "content": random.choice(_PEER_LINES),
                            "sender_id": t.contact_id}]})
    return code == 200


def peer_loop(c: Client, t: Takeover, m: Metrics, rate: float, stop: threading.Event) -> None:
    """Play the other party: post into this conversation at `rate` msgs/sec."""
    while not stop.is_set():
        interval = (1.0 / rate) if rate > 0 else 3600.0
        # ±40% jitter so arrivals aren't lockstep across conversations.
        stop.wait(interval * random.uniform(0.6, 1.4))
        if stop.is_set():
            break
        t0 = time.monotonic()
        good = _post_peer(c, t)
        m.record("peer.send", (time.monotonic() - t0) * 1000, good)
        if good:
            with t.lock:
                t.last_peer_ts = time.monotonic()
                t.awaiting = True


def reply_observer(c: Client, t: Takeover, m: Metrics, stop: threading.Event) -> None:
    """Hold the chat messages/after long-poll; when a from_self (AI reply)
    message appears while we're awaiting one, record the end-to-end reply lag.
    This is also the renderer's after-poll load."""
    while not stop.is_set():
        url = (f"{c.base_url}/api/chat/conversations/{t.chat_conv_id}"
               f"/messages/after?last_id={t.last_seen_id}&timeout={AFTER_TIMEOUT_S}")
        code, ms, payload = http_call("GET", url, token=c.token, timeout=AFTER_TIMEOUT_S + 8)
        m.record("chat.after", ms, code == 200)
        if code != 200:
            stop.wait(1.5)
            continue
        try:
            msgs = json.loads(payload).get("messages", [])
        except Exception:
            continue
        for msg in msgs:
            t.last_seen_id = max(t.last_seen_id, int(msg["id"]))
            # from_self (sender_id is None) == AI reply posted by the runtime.
            if msg.get("sender_id") is None:
                with t.lock:
                    if t.awaiting:
                        lag = (time.monotonic() - t.last_peer_ts) * 1000
                        m.record("reply.lag", lag, True)
                        t.awaiting = False


def renderer_poll_loop(c: Client, m: Metrics, stop: threading.Event) -> None:
    """Periodic snappy renderer polls (one thread per client)."""
    base = c.base_url
    tasks = [
        (CONVERSATIONS_S, "ui.conversations", f"{base}/api/conversations"),
        (BRIDGES_S, "ui.bridges", f"{base}/api/bridges"),
        (INBOXES_S, "ui.inboxes", f"{base}/api/inboxes"),
        (CHAT_CONVERSATIONS_S, "ui.chat_conversations", f"{base}/api/chat/conversations"),
    ]
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


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Full-client capacity load test (live message flow)")
    p.add_argument("env_file", help="per-instance env file (e.g. .env.debug)")
    p.add_argument("--clients", type=int, required=True, help="simulated desktop clients")
    p.add_argument("--takeovers", type=int, default=1, help="autoreply conversations per client")
    p.add_argument("--msg-rate", type=float, default=0.1,
                   help="peer messages per second, per takeover (default 0.1 = one per 10s)")
    p.add_argument("--duration", type=int, default=None, help="steady-state seconds (default: Ctrl-C)")
    p.add_argument("--no-bridge", action="store_true",
                   help="skip the bridge runtime (debug harness only; reply flow will NOT turn)")
    p.add_argument("--no-ui", action="store_true", help="skip renderer polls")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.clients < 1:
        die("--clients must be >= 1")
    if args.takeovers < 1:
        die("--takeovers must be >= 1")

    project = project_from_env_file(Path(args.env_file))
    base_url = f"http://{resolve_service_ip(project, 'user-api')}:{USER_PORT}"
    admin_url = f"http://{resolve_service_ip(project, 'admin-api')}:{ADMIN_PORT}"
    state_root = Path(tempfile.mkdtemp(prefix="lt-state-"))

    batch = secrets.token_hex(3)
    password = secrets.token_urlsafe(12)
    usernames = [f"{USERNAME_PREFIX}_{batch}_{i:04d}" for i in range(args.clients)]
    dur = f"{args.duration}s" if args.duration else "until Ctrl-C"
    log(f"project={project}  clients={args.clients}  takeovers={args.takeovers}  "
        f"msg-rate={args.msg_rate}/s  batch={batch}  duration={dur}")
    log(f"offered inbound ≈ {args.clients * args.takeovers * args.msg_rate:.2f} msgs/s "
        f"({args.clients}×{args.takeovers}×{args.msg_rate})")
    log(f"user-api={base_url}  admin-api={admin_url}")

    # phase 0: health
    code, _, _ = http_call("GET", f"{base_url}/api/health", timeout=10)
    if code != 200:
        die(f"api not healthy at {base_url} (GET /api/health → {code})")
    ok("api healthy")

    # phase 1: provider + accounts
    provider_id = ensure_fake_llm_provider(admin_url, batch)
    ok(f"fake-llm provider: {provider_id}")
    log(f"creating {len(usernames)} accounts …")
    create_accounts(admin_url, usernames, password)

    # phase 2: handshake + persona
    clients = [Client(username=u, password=password, base_url=base_url, admin_url=admin_url)
               for u in usernames]
    log("handshaking + creating personas …")
    for c in clients:
        handshake(c)
        create_persona(c)
    ok(f"handshook {len(clients)} accounts")

    # phase 3: bridge runtimes (must be up before takeover ignition — they
    # forward peer→studio).
    if args.no_bridge:
        warn("--no-bridge: no runtime to forward peer messages; reply flow will NOT turn")
    else:
        check_runtime_importable()
        log("spawning headless bridge runtimes …")
        for c in clients:
            start_runtime(c, state_root)
        time.sleep(3)
        alive = sum(1 for c in clients if c.runtime and c.runtime.poll() is None)
        ok(f"runtimes alive: {alive}/{len(clients)}  (logs: {state_root}/*.runtime.log)")
        if alive < len(clients):
            warn("some runtimes exited early — check the per-client logs")

    # phase 4: takeover ignition — batched in 3 sweeps so the wait on the
    # runtime's 2s forward cadence happens once for the whole fleet, not per
    # takeover (was the multi-minute stall at large M).
    want = args.clients * args.takeovers
    # 4a: create all contacts + first peer messages (fast; no waiting)
    log(f"creating {want} chat contacts + first messages …")
    for c in clients:
        for i in range(args.takeovers):
            t = create_takeover_stub(c, i)
            if t:
                c.takeovers.append(t)
    # 4b: one batch wait for every studio conversation to materialise
    log("waiting for studio conversations to materialise (one batch wait) …")
    resolved = resolve_studio_convs(clients)
    if resolved < want:
        warn(f"only {resolved}/{want} studio convs appeared (runtime cadence/forwarding?)")
    # 4c: ignite all materialised takeovers; keep only the live ones
    log("igniting (takeover + autoreply + persona + provider) …")
    total_t = 0
    for c in clients:
        live: list[Takeover] = []
        for t in c.takeovers:
            if t.studio_conv_id and ignite_takeover(c, t, provider_id):
                live.append(t)
                total_t += 1
        c.takeovers = live
    if total_t == 0:
        die("no takeovers ignited — flow cannot turn (check runtime logs)")
    ok(f"takeovers live: {total_t}/{want}")

    # phase 5: steady-state load — peer drivers + reply observers + renderer
    metrics = Metrics()
    stop = threading.Event()
    threads: list[threading.Thread] = []
    for c in clients:
        if not args.no_ui:
            threads.append(threading.Thread(target=renderer_poll_loop, args=(c, metrics, stop), daemon=True))
        for t in c.takeovers:
            threads.append(threading.Thread(target=peer_loop, args=(c, t, metrics, args.msg_rate, stop), daemon=True))
            threads.append(threading.Thread(target=reply_observer, args=(c, t, metrics, stop), daemon=True))
    for th in threads:
        th.start()

    ok(f"running {dur} — Ctrl-C to stop and print the summary  ({len(threads)} driver threads)")
    started = time.monotonic()
    try:
        stop.wait(args.duration)
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
        snap = metrics.snapshot()
        replies = snap.get("reply.lag", ClassStat()).count
        peers = snap.get("peer.send", ClassStat()).count
        print_summary(metrics, elapsed, replies, peers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
