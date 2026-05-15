#!/usr/bin/env python3
"""scripts/seed_dev.py — One-shot dev seed for internal testing.

Run after `docker compose up -d --build` in services/chat and services/studio.
Everything is driven by scripts/.env (copy scripts/.env.example). All values
are required and explicit — nothing is defaulted, guessed, or skipped:

  - SEED_ADMIN_*        one Studio admin (used only to create the Provider)
  - CHAT_SEED_USERS     users created in Chat
  - STUDIO_SEED_USERS   users created in Studio (role=user)
  - PROVIDER_*          one shared Studio Provider (admin auth)

CHAT_SEED_USERS and STUDIO_SEED_USERS are independent lists. If you want the
same credentials on both sides, write the same entries in both — the script
does not couple them.

Accounts + provider only — no personas, contacts, or seed messages. Re-run
after wiping volumes (docker compose down -v) for a clean baseline. Accounts
that already exist surface a warning and are left untouched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_DIR = REPO_ROOT / "services" / "chat"
STUDIO_DIR = REPO_ROOT / "services" / "studio"
ENV_PATH = Path(__file__).resolve().parent / ".env"


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
        die(f"{key} is required (set it in scripts/.env)")
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

def docker_create(service_dir: Path, service: str, module: str, cli_args: list[str], label: str) -> None:
    cmd = [
        "docker", "compose", "exec", "-T", service,
        "uv", "run", "python", "-m", module, "create-account", *cli_args,
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
    docker_create(
        CHAT_DIR, "chat-api", "chat.cli",
        ["--username", u.username, "--password", u.password, "--nickname", u.display],
        f"chat account {u.username}",
    )


def create_studio_account(username: str, password: str, display: str, role: str) -> None:
    log(f"creating studio account: {username} ({role})")
    docker_create(
        STUDIO_DIR, "studio-api", "studio.cli",
        ["--username", username, "--password", password,
         "--display-name", display, "--role", role],
        f"studio account {username}",
    )


# ---------- Studio API ----------

def studio_login(studio_url: str, username: str, password: str) -> str:
    code, body = http_request(
        "POST", f"{studio_url}/api/auth/login",
        body={"username": username, "password": password},
    )
    if code != 200:
        die(f"studio admin login failed for {username} (HTTP {code}): {body}")
    try:
        token = json.loads(body).get("token", "")
    except json.JSONDecodeError:
        token = ""
    if not token:
        die(f"studio admin login returned no token: {body}")
    return token


def studio_seed_provider(studio_url: str, admin_token: str) -> None:
    name = env_required("PROVIDER_NAME")
    base_url = env_required("PROVIDER_BASE_URL")
    model = env_required("PROVIDER_MODEL")
    api_key = env_required("PROVIDER_API_KEY")

    code, body = http_request("GET", f"{studio_url}/api/provider-configs", token=admin_token)
    if code == 200 and len(json.loads(body)) > 0:
        ok("studio provider already configured — leaving untouched")
        return

    log(f"creating studio provider: {name}")
    code, body = http_request(
        "POST", f"{studio_url}/api/provider-configs", token=admin_token,
        body={"name": name, "base_url": base_url, "api_key": api_key, "default_model": model},
    )
    if code != 200:
        die(f"create provider failed (HTTP {code}): {body}")
    ok("studio provider created")


# ---------- main ----------

def main() -> None:
    if subprocess.run(["which", "docker"], capture_output=True).returncode != 0:
        die("missing required command: docker")

    load_env(ENV_PATH)

    chat_url = env_required("CHAT_URL")
    studio_url = env_required("STUDIO_URL")

    admin_user = env_required("SEED_ADMIN_USER")
    admin_pass = env_required("SEED_ADMIN_PASS")
    admin_display = env_required("SEED_ADMIN_DISPLAY")

    chat_users = parse_users("CHAT_SEED_USERS")
    studio_users = parse_users("STUDIO_SEED_USERS")

    log(f"studio: {studio_url}  chat: {chat_url}")
    log(f"admin: {admin_user}")
    log(f"chat users  : {', '.join(u.username for u in chat_users)}")
    log(f"studio users: {', '.join(u.username for u in studio_users)}")
    wait_health(chat_url, "chat-api")
    wait_health(studio_url, "studio-api")

    # Studio admin (studio-only — Chat has no admin concept).
    create_studio_account(admin_user, admin_pass, admin_display, "admin")

    for u in chat_users:
        create_chat_account(u)
    for u in studio_users:
        create_studio_account(u.username, u.password, u.display, "user")

    admin_token = studio_login(studio_url, admin_user, admin_pass)
    studio_seed_provider(studio_url, admin_token)

    print()
    print("---")
    print("seed done. credentials:")
    print(f"  studio admin: {admin_user} / {admin_pass}   ({studio_url})")
    for u in chat_users:
        print(f"  chat user   : {u.username} / {u.password}   ({chat_url})")
    for u in studio_users:
        print(f"  studio user : {u.username} / {u.password}   ({studio_url})")
    print()
    print("next: start bridge with the snippet shown on Studio → 设备 → 快速生成命令.")


if __name__ == "__main__":
    main()
