#!/usr/bin/env python3
"""scripts/seed_dev.py — One-shot dev seed for internal testing.

Run after the instance is up (scripts/up-all.sh <instance-file>). Driven by
that same instance file, passed as the argument:

  python scripts/seed_dev.py scripts/.env.0519

(copy scripts/.env.example for a new instance). All seed values are required
and explicit — nothing is defaulted, guessed, or skipped:

  - CHAT_SEED_USERS     users created in Chat
  - STUDIO_SEED_USERS   users created in Studio
  - PROVIDER_*          the single global Studio Provider (created via CLI)

CHAT_SEED_USERS and STUDIO_SEED_USERS are independent lists. If you want the
same credentials on both sides, write the same entries in both — the script
does not couple them.

Accounts + provider. Re-run after wiping volumes (docker compose down -v)
for a clean baseline. Accounts that already exist surface a warning and are
left untouched; re-running without a wipe creates an extra Provider row (the
newest becomes default).
"""

from __future__ import annotations

import json
import os
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


def resolve_env_arg(argv: list[str]) -> Path:
    """The instance/env file is argv[1]; resolve like up-all.sh does."""
    if len(argv) < 2 or not argv[1].strip():
        die("usage: scripts/seed_dev.py <instance-file>   (e.g. scripts/.env.0519)")
    p = Path(argv[1])
    if not p.is_file():
        p = REPO_ROOT / argv[1]
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


# ---------- env ----------

def load_env(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE per line, # comments, optional quotes.

    Does not override variables already set in the real environment.
    """
    if not path.is_file():
        die(f"env file not found: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_required(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        die(f"{key} is required (set it in the instance env file)")
    return value


# ---------- user spec ----------

@dataclass
class UserSpec:
    username: str
    password: str
    display: str


def parse_users(var_name: str) -> list[UserSpec]:
    """Parse a comma-separated list of strict `username:password:display`.

    Strict: the variable must be set; every comma item must contain exactly
    three non-empty colon-separated fields. No empty items, no defaults, no
    skipping — any deviation is a hard error.
    """
    raw = env_required(var_name)
    users: list[UserSpec] = []
    seen: set[str] = set()
    for index, chunk in enumerate(raw.split(","), start=1):
        item = chunk.strip()
        if not item:
            die(f"{var_name}: item #{index} is empty (no blank entries / trailing commas)")
        parts = [p.strip() for p in item.split(":")]
        if len(parts) != 3 or not all(parts):
            die(f"{var_name}: item #{index} must be exactly username:password:display, got {item!r}")
        username, password, display = parts
        if username in seen:
            die(f"{var_name}: duplicate username {username!r}")
        seen.add(username)
        users.append(UserSpec(username, password, display))
    return users


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

def docker_cli(service_dir: Path, service: str, module: str, subcommand: str,
               cli_args: list[str], label: str) -> None:
    cmd = [
        "docker", "compose", "exec", "-T", service,
        "uv", "run", "python", "-m", module, subcommand, *cli_args,
    ]
    result = subprocess.run(cmd, cwd=service_dir, capture_output=True, text=True)
    if result.returncode == 0:
        ok(f"{label} ready")
    else:
        tail = (result.stderr or result.stdout).strip().splitlines()
        hint = tail[-1] if tail else "(no output)"
        warn(f"{label}: non-zero (likely already exists) — continuing: {hint}")


def create_chat_account(u: UserSpec) -> None:
    log(f"creating chat account: {u.username}")
    docker_cli(
        CHAT_DIR, "chat-api", "chat.cli", "create-account",
        ["--username", u.username, "--password", u.password, "--nickname", u.display],
        f"chat account {u.username}",
    )


def create_studio_account(username: str, password: str, display: str) -> None:
    log(f"creating studio account: {username}")
    docker_cli(
        STUDIO_DIR, "studio-api", "studio.cli", "create-account",
        ["--username", username, "--password", password, "--display-name", display],
        f"studio account {username}",
    )


def studio_seed_provider() -> None:
    name = env_required("PROVIDER_NAME")
    base_url = env_required("PROVIDER_BASE_URL")
    model = env_required("PROVIDER_MODEL")
    api_key = env_required("PROVIDER_API_KEY")

    log(f"creating studio provider: {name}")
    docker_cli(
        STUDIO_DIR, "studio-api", "studio.cli", "create-provider",
        ["--name", name, "--base-url", base_url,
         "--api-key", api_key, "--model", model],
        f"studio provider {name}",
    )


# ---------- main ----------

def main() -> None:
    if subprocess.run(["which", "docker"], capture_output=True).returncode != 0:
        die("missing required command: docker")

    load_env(resolve_env_arg(sys.argv))

    chat_url = env_required("CHAT_URL")
    studio_url = env_required("STUDIO_URL")

    chat_users = parse_users("CHAT_SEED_USERS")
    studio_users = parse_users("STUDIO_SEED_USERS")

    log(f"studio: {studio_url}  chat: {chat_url}")
    log(f"chat users  : {', '.join(u.username for u in chat_users)}")
    log(f"studio users: {', '.join(u.username for u in studio_users)}")
    run_parallel([
        lambda: wait_health(chat_url, "chat-api"),
        lambda: wait_health(studio_url, "studio-api"),
    ])

    # chat accounts, studio accounts and the provider are mutually independent;
    # each is a slow `docker compose exec`, so this phase gains the most.
    run_parallel(
        [lambda u=u: create_chat_account(u) for u in chat_users]
        + [lambda u=u: create_studio_account(u.username, u.password, u.display)
           for u in studio_users]
        + [studio_seed_provider]
    )

    print()
    print("---")
    print("seed done. credentials:")
    for u in chat_users:
        print(f"  chat user   : {u.username} / {u.password}   ({chat_url})")
    for u in studio_users:
        print(f"  studio user : {u.username} / {u.password}   ({studio_url})")
    print()
    print("next: start bridge with the snippet shown on Studio → 设备 → 快速生成命令.")


if __name__ == "__main__":
    main()
