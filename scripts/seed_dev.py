#!/usr/bin/env python3
"""scripts/seed_dev.py — One-shot dev seed for internal testing.

Run after `docker compose up -d --build` in services/chat and services/studio.
Everything is driven by scripts/.env (copy scripts/.env.example). All values
are required and explicit — nothing is defaulted, guessed, or skipped:

  - CHAT_SEED_USERS     users created in Chat
  - STUDIO_SEED_USERS   users created in Studio
  - PROVIDER_*          the single global Studio Provider (created via CLI)

After accounts exist, every ChatLab JSON in misc/seed_chats/out/ is imported
into Chat as historical conversations (login → create contact → bulk send).
Each file's meta.ownerId is the streamer and MUST be a username in
CHAT_SEED_USERS — any JSON whose owner is not a seeded chat user is a hard
error (the .env user list and the seed chats must line up exactly).

CHAT_SEED_USERS and STUDIO_SEED_USERS are independent lists. If you want the
same credentials on both sides, write the same entries in both — the script
does not couple them.

Accounts + provider + imported seed chats. Re-run after wiping volumes
(docker compose down -v) for a clean baseline. Accounts that already exist
surface a warning and are left untouched; contacts that already exist cause
the matching seed chat to be skipped (so a no-wipe re-run won't duplicate
messages); re-running without a wipe creates an extra Provider row (the
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
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_DIR = REPO_ROOT / "services" / "chat"
STUDIO_DIR = REPO_ROOT / "services" / "studio"
SEED_CHATS_DIR = REPO_ROOT / "misc" / "seed_chats" / "out"
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


# ---------- parallel ----------

def run_parallel(jobs: list, workers: int = 8) -> None:
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
         "--api-key", api_key, "--default-model", model],
        f"studio provider {name}",
    )


# ---------- seed chats (ChatLab JSON → Chat history) ----------

def load_seed_chats() -> list[tuple[Path, dict]]:
    """Read every misc/seed_chats/out/*.json. Hard-fail on any malformed file."""
    if not SEED_CHATS_DIR.is_dir():
        die(f"seed chats dir not found: {SEED_CHATS_DIR} "
            f"(run: python3 misc/seed_chats/generate.py)")
    files = sorted(SEED_CHATS_DIR.glob("*.json"))
    if not files:
        die(f"no seed chat JSON in {SEED_CHATS_DIR}")
    out: list[tuple[Path, dict]] = []
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            die(f"{path.name}: invalid JSON ({exc})")
        meta = doc.get("meta") or {}
        members = doc.get("members") or []
        if meta.get("type") != "private":
            die(f"{path.name}: meta.type must be 'private'")
        owner = meta.get("ownerId")
        if not owner:
            die(f"{path.name}: missing meta.ownerId")
        if len(members) != 2:
            die(f"{path.name}: private chat needs exactly 2 members")
        if not any(m.get("platformId") == owner for m in members):
            die(f"{path.name}: ownerId {owner!r} not among members")
        out.append((path, doc))
    return out


def validate_chats_match_users(chats: list[tuple[Path, dict]],
                               chat_users: list[UserSpec]) -> None:
    """Every JSON owner must be a seeded Chat username — else hard error."""
    known = {u.username for u in chat_users}
    bad = sorted({
        doc["meta"]["ownerId"]
        for _, doc in chats
        if doc["meta"]["ownerId"] not in known
    })
    if bad:
        die(f"seed chats reference unknown chat user(s) {bad} — "
            f"CHAT_SEED_USERS has {sorted(known)}. "
            f"Fix scripts/.env or misc/seed_chats so they line up.")


def chat_login(chat_url: str, u: UserSpec) -> str:
    code, body = http_request(
        "POST", f"{chat_url}/api/auth/login",
        body={"username": u.username, "password": u.password},
    )
    if code != 200:
        die(f"chat login failed for {u.username}: HTTP {code} {body}")
    try:
        return json.loads(body)["token"]
    except (ValueError, KeyError):
        die(f"chat login for {u.username}: no token in response: {body}")


def iso_utc(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def import_one_chat(chat_url: str, token: str, owner: str, doc: dict) -> None:
    meta = doc["meta"]
    other = next(m for m in doc["members"] if m.get("platformId") != owner)
    fan_username = other.get("accountName") or other["platformId"]
    fan_nick = other.get("groupNickname") or fan_username
    remark = meta.get("name") or fan_nick

    code, body = http_request(
        "POST", f"{chat_url}/api/contacts", token=token,
        body={"nickname": fan_nick, "username": fan_username, "remark_name": remark},
    )
    if code == 409:
        warn(f"{owner} ← {remark}: contact exists, skipping (re-run after a wipe)")
        return
    if code not in (200, 201):
        die(f"{owner} ← {remark}: create contact failed: HTTP {code} {body}")
    contact_id = json.loads(body)["id"]

    code, body = http_request("GET", f"{chat_url}/api/conversations", token=token)
    if code != 200:
        die(f"{owner}: list conversations failed: HTTP {code} {body}")
    conv = next((c for c in json.loads(body) if c.get("contact_id") == contact_id), None)
    if not conv:
        die(f"{owner} ← {remark}: no conversation created for contact")

    msgs = [
        {
            "sender_id": None if m.get("sender") == owner else contact_id,
            "msg_type": "text",
            "content": m["content"],
            "created_at": iso_utc(int(m["timestamp"])),
        }
        for m in doc.get("messages", [])
        if m.get("type") == 0 and m.get("content")
    ]
    if not msgs:
        warn(f"{owner} ← {remark}: no text messages, skipping")
        return
    code, body = http_request(
        "POST", f"{chat_url}/api/conversations/{conv['id']}/messages",
        token=token, body={"messages": msgs},
    )
    if code != 200:
        die(f"{owner} ← {remark}: bulk send failed: HTTP {code} {body}")
    ok(f"{owner} ← {remark}: {len(msgs)} messages")


def import_owner_chats(chat_url: str, user: UserSpec, docs: list[dict]) -> None:
    """One owner's chats: single login, then sequential imports.

    Kept sequential within an owner — the imports share one token and each
    re-lists GET /api/conversations, so concurrent imports for the same owner
    would race on that list. Different owners are fully independent.
    """
    token = chat_login(chat_url, user)
    for doc in docs:
        import_one_chat(chat_url, token, user.username, doc)


def import_seed_chats(chat_url: str, chat_users: list[UserSpec]) -> None:
    chats = load_seed_chats()
    validate_chats_match_users(chats, chat_users)
    by_name = {u.username: u for u in chat_users}
    by_owner: dict[str, list[dict]] = {}
    for _, doc in chats:
        by_owner.setdefault(doc["meta"]["ownerId"], []).append(doc)
    log(f"importing {len(chats)} seed conversations across {len(by_owner)} owners")
    run_parallel([
        lambda o=owner, d=docs: import_owner_chats(chat_url, by_name[o], d)
        for owner, docs in by_owner.items()
    ])


# ---------- main ----------

def main() -> None:
    if subprocess.run(["which", "docker"], capture_output=True).returncode != 0:
        die("missing required command: docker")

    load_env(ENV_PATH)

    chat_url = env_required("CHAT_URL")
    studio_url = env_required("STUDIO_URL")

    chat_users = parse_users("CHAT_SEED_USERS")
    studio_users = parse_users("STUDIO_SEED_USERS")

    # Fail fast: seed chats and CHAT_SEED_USERS must line up before any work.
    validate_chats_match_users(load_seed_chats(), chat_users)

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

    import_seed_chats(chat_url, chat_users)

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
