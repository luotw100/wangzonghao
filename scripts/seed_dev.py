#!/usr/bin/env python3
"""scripts/seed_dev.py — One-shot dev seed for internal testing.

Run after the instance is up (scripts/up-all.sh <config.json>). Driven by
that same JSON config, passed as the argument:

  python scripts/seed_dev.py scripts/.env.debug.json

Schema (see scripts/.env.example.json):

  {
    "seed": {
      "chat_url": "...",         # base URL of chat-api
      "studio_url": "...",       # base URL of studio-api
      "chat_users":   [{username, password, display}, ...],
      "studio_users": [{username, password, display}, ...],
      "providers":    [{name, base_url, model, api_key}, ...]
    }
  }

chat_users / studio_users are independent — if you want the same credentials
on both sides, duplicate the entries. Accounts that already exist surface
a warning and are left untouched.

Phasing matters: the studio Providers must exist before any studio account
is created, because `studio create-account` reads accounts.distill_provider_id
from the earliest-created Provider. So this script runs three serial phases:

  1. wait for chat-api + studio-api health (parallel)
  2. create the studio Providers in declared order (serial)  (must precede #3)
  3. create chat accounts + studio accounts                  (parallel)
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_DIR = REPO_ROOT / "services" / "chat"
STUDIO_DIR = REPO_ROOT / "services" / "studio"


def resolve_config_arg(argv: list[str]) -> Path:
    if len(argv) < 2 or not argv[1].strip():
        die("usage: scripts/seed_dev.py <config.json>   (e.g. scripts/.env.debug.json)")
    p = Path(argv[1])
    if not p.is_file():
        p = REPO_ROOT / argv[1]
    if not p.is_file():
        die(f"config not found: {argv[1]}")
    return p


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
    """Run zero-arg callables concurrently; re-raise the first failure.

    die() raises SystemExit, which ThreadPoolExecutor captures per-future and
    re-raises here on .result() — so fail-fast still aborts the script (after
    the in-flight batch drains), just from the main thread.
    """
    if not jobs:
        return
    if len(jobs) == 1:
        jobs[0]()
        return
    with ThreadPoolExecutor(max_workers=min(workers, len(jobs))) as ex:
        for fut in [ex.submit(j) for j in jobs]:
            fut.result()


# ---------- config dataclasses ----------

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
    project_name: str   # COMPOSE_PROJECT_NAME — must match what up-all.sh used
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


# ---------- http ----------

def http_request(method: str, url: str, token: str = "", body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    # Cloudflare Bot Fight Mode blocks the default Python-urllib UA with 403.
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


# ---------- CLI account creation (via docker compose exec) ----------

def docker_cli(project: str, service_dir: Path, service: str, module: str, subcommand: str,
               cli_args: list[str], label: str) -> None:
    # Explicit -p: seed_dev.py does not source the instance config into its
    # own env, so docker compose can't infer the project name from there.
    cmd = [
        "docker", "compose", "-p", project, "exec", "-T", service,
        "uv", "run", "python", "-m", module, subcommand, *cli_args,
    ]
    result = subprocess.run(cmd, cwd=service_dir, capture_output=True, text=True)
    if result.returncode == 0:
        ok(f"{label} ready")
    else:
        tail = (result.stderr or result.stdout).strip().splitlines()
        hint = tail[-1] if tail else "(no output)"
        warn(f"{label}: non-zero (likely already exists) — continuing: {hint}")


def create_chat_account(project: str, u: UserSpec) -> None:
    log(f"creating chat account: {u.username}")
    docker_cli(
        project, CHAT_DIR, "chat-api", "chat.cli", "create-account",
        ["--username", u.username, "--password", u.password, "--nickname", u.display],
        f"chat account {u.username}",
    )


def create_studio_account(project: str, u: UserSpec) -> None:
    log(f"creating studio account: {u.username}")
    docker_cli(
        project, STUDIO_DIR, "studio-api", "studio.cli", "create-account",
        ["--username", u.username, "--password", u.password, "--display-name", u.display],
        f"studio account {u.username}",
    )


def create_studio_provider(project: str, p: ProviderSpec) -> None:
    log(f"creating studio provider: {p.name}")
    docker_cli(
        project, STUDIO_DIR, "studio-api", "studio.cli", "create-provider",
        ["--name", p.name, "--base-url", p.base_url,
         "--api-key", p.api_key, "--model", p.model],
        f"studio provider {p.name}",
    )


# ---------- main ----------

def main() -> None:
    if subprocess.run(["which", "docker"], capture_output=True).returncode != 0:
        die("missing required command: docker")

    cfg = load_seed_config(resolve_config_arg(sys.argv))

    log(f"studio: {cfg.studio_url}  chat: {cfg.chat_url}")
    log(f"chat users  : {', '.join(u.username for u in cfg.chat_users)}")
    log(f"studio users: {', '.join(u.username for u in cfg.studio_users)}")
    log(f"providers   : {', '.join(p.name for p in cfg.providers)}  (first is default)")

    # phase 1: wait for both services
    run_parallel([
        lambda: wait_health(cfg.chat_url, "chat-api"),
        lambda: wait_health(cfg.studio_url, "studio-api"),
    ])

    # phase 2: studio providers, in declared order (serial so created_at
    # ordering is deterministic — the first entry becomes the default that
    # studio create-account binds new accounts to).
    for p in cfg.providers:
        create_studio_provider(cfg.project_name, p)

    # phase 3: accounts (chat + studio in parallel).
    run_parallel(
        [lambda u=u: create_chat_account(cfg.project_name, u) for u in cfg.chat_users]
        + [lambda u=u: create_studio_account(cfg.project_name, u) for u in cfg.studio_users]
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
