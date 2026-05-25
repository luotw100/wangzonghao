#!/usr/bin/env python3
"""scripts/seed_dev.py — One-shot dev seed for the merged stack.

Run after the instance is up (scripts/up-all.sh <config.json>). Driven by
that same JSON config, passed as the argument:

  python scripts/seed_dev.py scripts/.env.debug.json

Schema (see scripts/.env.example.json):

  {
    "seed": {
      "studio_url":  "...",         # base URL of api (via CF tunnel)
      "users":       [{username, password, display}, ...],
      "providers":   [{name, base_url, model, api_key}, ...]
    }
  }

After merge there is a single account pool (auth.accounts). Each ``users``
entry creates one studio account that also doubles as the chat-sandbox
identity (chat has no separate login).

Phasing:
  1. wait for api health (via CF tunnel)
  2. create the first provider serially — it becomes the
     pick_first_provider default; then create the rest in parallel
  3. create accounts in one admin-api call (parallel inside the container)
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
    studio_url: str
    users: list[UserSpec]
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
        studio_url=_require_str(seed, "studio_url", "seed"),
        users=_parse_users(seed.get("users"), "seed.users"),
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
        ["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.yaml"),
         "-p", project, "exec", "-T", "admin-api",
         "python", "-c", _ADMIN_INNER],
        cwd=REPO_ROOT,
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
        "label": f"provider {p.name}",
    }


def account_call(u: UserSpec) -> dict:
    return {
        "path": "/accounts",
        "body": {"username": u.username, "password": u.password, "display_name": u.display},
        "label": f"account {u.username}",
    }


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

    log(f"studio: {cfg.studio_url}")
    log(f"users     : {', '.join(u.username for u in cfg.users)}")
    log(f"providers : {', '.join(pr.name for pr in cfg.providers)}  (first is default)")

    # phase 1: wait for api
    wait_health(cfg.studio_url, "api")

    # phase 2: providers (first one alone to win pick_first_provider race)
    log(f"creating default provider: {cfg.providers[0].name}")
    admin_exec(cfg.project_name, [provider_call(cfg.providers[0])])
    if cfg.providers[1:]:
        log(f"creating remaining providers: {', '.join(pr.name for pr in cfg.providers[1:])}")
        admin_exec(cfg.project_name, [provider_call(pr) for pr in cfg.providers[1:]])

    # phase 3: accounts
    if cfg.users:
        log(f"creating accounts: {', '.join(u.username for u in cfg.users)}")
        admin_exec(cfg.project_name, [account_call(u) for u in cfg.users])

    print()
    print("---")
    print(f"seed done. login at {cfg.studio_url} (chat sandbox at {cfg.studio_url}/chat):")
    for u in cfg.users:
        print(f"  {u.username} / {u.password}")
    print()
    print("next: start bridge with the snippet shown on Studio → 设备 → 快速生成命令.")


if __name__ == "__main__":
    main()
