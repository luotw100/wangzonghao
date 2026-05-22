#!/usr/bin/env python3
"""scripts/seed_dev.py — One-shot dev seed for internal testing.

Run after the instance is up (scripts/up-all.sh <config.json>). Driven by
that same JSON config, passed as the argument:

  python scripts/seed_dev.py scripts/.env.debug.json

Schema (see scripts/.env.example.json):

  {
    "seed": {
      "chat_url":    "...",         # base URL of chat-api  (via CF tunnel)
      "studio_url":  "...",         # base URL of studio-api (via CF tunnel)
      "chat_users":   [{username, password, display}, ...],
      "studio_users": [{username, password, display}, ...],
      "providers":    [{name, base_url, model, api_key}, ...]
    }
  }

Phasing:
  1. wait for chat-api + studio-api health (parallel, via CF tunnel)
  2. create the first studio Provider serially — it becomes the pick_first_provider
     default; then create the rest in parallel (inside one docker compose exec)
  3. create chat accounts (one exec each, parallel from Python) +
     all studio accounts (one exec, parallel inside the container)
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_DIR = REPO_ROOT / "services" / "chat"
STUDIO_DIR = REPO_ROOT / "services" / "studio"

# Runs inside the admin-api container. Reads [{path, body, label}] from stdin,
# fires them all in parallel against the local admin API, prints results, exits
# non-zero if any call failed with a non-409 error.
_ADMIN_INNER = textwrap.dedent("""\
    import json, sys, urllib.request, urllib.error
    from concurrent.futures import ThreadPoolExecutor

    calls = json.load(sys.stdin)

    def do(c):
        data = json.dumps(c["body"]).encode()
        req = urllib.request.Request(
            "http://localhost:23457/api/admin" + c["path"],
            data=data, method="POST",
        )
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req):
                return c["label"], "ok", ""
        except urllib.error.HTTPError as e:
            return c["label"], str(e.code), e.read().decode("utf-8", "replace")[:200]

    failed = False
    with ThreadPoolExecutor() as ex:
        for label, code, body in ex.map(do, calls):
            if code == "ok":
                print(f"ok {label}")
            elif code == "409":
                print(f"skip {label} (already exists)")
            else:
                print(f"FAIL {label}: HTTP {code} — {body}", file=sys.stderr)
                failed = True
    sys.exit(1 if failed else 0)
""")


# ---------- logging ----------

def log(msg: str) -> None:
    print(f"\033[36m[seed]\033[0m {msg}")


def ok(msg: str) -> None:
    print(f"\033[32m[ok]\033[0m   {msg}")


def warn(msg: str) -> None:
    print(f"\033[33m[warn]\033[0m {msg}")


def die(msg: str) -> "None":
    print(f"\033[31m[fail]\033[0m {msg}", file=sys.stderr)
    raise SystemExit(1)


# ---------- parallel ----------

def run_parallel(jobs: list, workers: int = 32) -> None:
    if not jobs:
        return
    if len(jobs) == 1:
        jobs[0]()
        return
    with ThreadPoolExecutor(max_workers=min(workers, len(jobs))) as ex:
        for fut in [ex.submit(j) for j in jobs]:
            fut.result()


# ---------- config ----------

@dataclass
class UserSpec:
    username: str
    password: str
    display: str


@dataclass
class ProviderSpec:
    name: str
    base_url: str
    model: str
    api_key: str


@dataclass
class SeedConfig:
    project_name: str
    chat_url: str
    studio_url: str
    chat_users: list[UserSpec]
    studio_users: list[UserSpec]
    providers: list[ProviderSpec]


def _require_str(obj: dict, key: str, ctx: str) -> str:
    v = obj.get(key)
    if not isinstance(v, str) or not v.strip():
        die(f"{ctx}: missing or empty string field {key!r}")
    return v.strip()


def _parse_users(items: object, ctx: str) -> list[UserSpec]:
    if not isinstance(items, list) or not items:
        die(f"{ctx}: must be a non-empty list")
    out: list[UserSpec] = []
    seen: set[str] = set()
    for i, entry in enumerate(items, start=1):
        if not isinstance(entry, dict):
            die(f"{ctx}[{i}]: must be an object")
        u = UserSpec(
            username=_require_str(entry, "username", f"{ctx}[{i}]"),
            password=_require_str(entry, "password", f"{ctx}[{i}]"),
            display=_require_str(entry, "display", f"{ctx}[{i}]"),
        )
        if u.username in seen:
            die(f"{ctx}: duplicate username {u.username!r}")
        seen.add(u.username)
        out.append(u)
    return out


def _parse_providers(items: object, ctx: str) -> list[ProviderSpec]:
    if not isinstance(items, list) or not items:
        die(f"{ctx}: must be a non-empty list")
    out: list[ProviderSpec] = []
    seen: set[str] = set()
    for i, entry in enumerate(items, start=1):
        if not isinstance(entry, dict):
            die(f"{ctx}[{i}]: must be an object")
        p = ProviderSpec(
            name=_require_str(entry, "name", f"{ctx}[{i}]"),
            base_url=_require_str(entry, "base_url", f"{ctx}[{i}]"),
            model=_require_str(entry, "model", f"{ctx}[{i}]"),
            api_key=_require_str(entry, "api_key", f"{ctx}[{i}]"),
        )
        if p.name in seen:
            die(f"{ctx}: duplicate provider name {p.name!r}")
        seen.add(p.name)
        out.append(p)
    return out


def load_seed_config(path: Path) -> SeedConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"invalid JSON in {path}: {exc}")
    seed = raw.get("seed")
    if not isinstance(seed, dict):
        die(f"{path}: top-level `seed` object is required")
    compose = raw.get("compose")
    if not isinstance(compose, dict):
        die(f"{path}: top-level `compose` object is required")
    project = compose.get("COMPOSE_PROJECT_NAME")
    if not isinstance(project, str) or not project.strip():
        die(f"{path}: compose.COMPOSE_PROJECT_NAME is required")
    return SeedConfig(
        project_name=project.strip(),
        chat_url=_require_str(seed, "chat_url", "seed"),
        studio_url=_require_str(seed, "studio_url", "seed"),
        chat_users=_parse_users(seed.get("chat_users"), "seed.chat_users"),
        studio_users=_parse_users(seed.get("studio_users"), "seed.studio_users"),
        providers=_parse_providers(seed.get("providers"), "seed.providers"),
    )


# ---------- health ----------

def http_request(method: str, url: str, token: str = "", body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", "curl/8.0")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)


def wait_health(url: str, name: str, tries: int = 30) -> None:
    for _ in range(tries):
        code, _ = http_request("GET", f"{url}/api/health")
        if code == 200:
            ok(f"{name} healthy")
            return
        time.sleep(1)
    die(f"{name} not reachable at {url} — start the stack first")


# ---------- admin API (via docker compose exec) ----------

def admin_exec(project: str, calls: list[dict]) -> None:
    """Single docker compose exec; all calls run in parallel inside the container."""
    result = subprocess.run(
        ["docker", "compose", "-p", project, "exec", "-T", "admin-api",
         "python", "-c", _ADMIN_INNER],
        cwd=STUDIO_DIR,
        capture_output=True,
        text=True,
        input=json.dumps(calls),
    )
    for line in result.stdout.splitlines():
        if line.startswith("ok "):
            ok(line[3:])
        elif line.startswith("skip "):
            warn(line[5:])
    if result.returncode != 0:
        for line in result.stderr.splitlines():
            warn(line)
        die("one or more admin-api calls failed")


def provider_call(p: ProviderSpec) -> dict:
    return {
        "path": "/providers",
        "body": {"name": p.name, "base_url": p.base_url, "model": p.model, "api_key": p.api_key},
        "label": f"studio provider {p.name}",
    }


def account_call(u: UserSpec) -> dict:
    return {
        "path": "/accounts",
        "body": {"username": u.username, "password": u.password, "display_name": u.display},
        "label": f"studio account {u.username}",
    }


# ---------- chat CLI (unchanged) ----------

def create_chat_account(project: str, u: UserSpec) -> None:
    log(f"creating chat account: {u.username}")
    cmd = [
        "docker", "compose", "-p", project, "exec", "-T", "chat-api",
        "uv", "run", "python", "-m", "chat.cli", "create-account",
        "--username", u.username, "--password", u.password, "--nickname", u.display,
    ]
    result = subprocess.run(cmd, cwd=CHAT_DIR, capture_output=True, text=True)
    if result.returncode == 0:
        ok(f"chat account {u.username}")
    else:
        tail = (result.stderr or result.stdout).strip().splitlines()
        hint = tail[-1] if tail else "(no output)"
        warn(f"chat account {u.username}: non-zero (likely already exists) — {hint}")


# ---------- main ----------

def main() -> None:
    if subprocess.run(["which", "docker"], capture_output=True).returncode != 0:
        die("missing required command: docker")

    if len(sys.argv) < 2 or not sys.argv[1].strip():
        die("usage: scripts/seed_dev.py <config.json>   (e.g. scripts/.env.debug.json)")
    p = Path(sys.argv[1])
    if not p.is_file():
        p = REPO_ROOT / sys.argv[1]
    if not p.is_file():
        die(f"config not found: {sys.argv[1]}")

    cfg = load_seed_config(p)

    log(f"studio: {cfg.studio_url}  chat: {cfg.chat_url}")
    log(f"chat users  : {', '.join(u.username for u in cfg.chat_users)}")
    log(f"studio users: {', '.join(u.username for u in cfg.studio_users)}")
    log(f"providers   : {', '.join(p.name for p in cfg.providers)}  (first is default)")

    # phase 1: wait for both services (via CF tunnel)
    run_parallel([
        lambda: wait_health(cfg.chat_url, "chat-api"),
        lambda: wait_health(cfg.studio_url, "studio-api"),
    ])

    # phase 2: studio providers
    # First one serial — guaranteed earliest created_at, becomes pick_first_provider default.
    # Rest in parallel inside one exec.
    log(f"creating studio provider (default): {cfg.providers[0].name}")
    admin_exec(cfg.project_name, [provider_call(cfg.providers[0])])
    if cfg.providers[1:]:
        log(f"creating remaining providers: {', '.join(p.name for p in cfg.providers[1:])}")
        admin_exec(cfg.project_name, [provider_call(p) for p in cfg.providers[1:]])

    # phase 3: chat accounts (parallel docker compose exec from Python) +
    #          studio accounts (one docker compose exec, parallel inside)
    if cfg.studio_users:
        log(f"creating studio accounts: {', '.join(u.username for u in cfg.studio_users)}")
    studio_job = (
        [lambda: admin_exec(cfg.project_name, [account_call(u) for u in cfg.studio_users])]
        if cfg.studio_users else []
    )
    run_parallel(
        [lambda u=u: create_chat_account(cfg.project_name, u) for u in cfg.chat_users]
        + studio_job
    )

    print()
    print("---")
    print("seed done. credentials:")
    for u in cfg.chat_users:
        print(f"  chat user   : {u.username} / {u.password}   ({cfg.chat_url})")
    for u in cfg.studio_users:
        print(f"  studio user : {u.username} / {u.password}   ({cfg.studio_url})")
    print()
    print("next: start bridge with the snippet shown on Studio → 设备 → 快速生成命令.")


if __name__ == "__main__":
    main()
