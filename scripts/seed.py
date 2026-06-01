#!/usr/bin/env python3
"""scripts/seed.py — One-shot dev seed, host-side, pure HTTP.

Talks to a running instance's admin-api over the Docker bridge network by
resolving the container's IP (Linux routes to it directly — no published
port needed) and POSTing to /api/admin. No `docker exec`, no public URL,
no edge dependency.

Usage (same shape as backup.sh / test.sh: env file first, then config):
    python scripts/seed.py .env.debug scripts/seed.debug.json

The project name is read from the env file's COMPOSE_PROJECT_NAME. The
instance must already be up with the `storage` + `app` profiles (admin-api
running). Config schema (see scripts/seed.example.json):

    {
      "users":     [{username, password, display}, ...],
      "providers": [{name, base_url, model, api_key}, ...]
    }

After merge there is a single account pool (auth.accounts); each user also
doubles as the chat-sandbox identity. Idempotent: existing accounts /
same-named providers return 409 and are reported as skipped.

Phasing mirrors create_account's needs:
  1. resolve admin-api IP, wait for readiness
  2. create the first provider serially (it wins pick_first_provider, the
     default every new account is pinned to); then the rest in parallel
  3. create accounts in parallel
"""

from __future__ import annotations

import argparse
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
ADMIN_PORT = 23457


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
    if not isinstance(raw, dict):
        die(f"{path}: top-level must be a JSON object")
    return SeedConfig(
        users=_parse_users(raw.get("users"), "users"),
        providers=_parse_providers(raw.get("providers"), "providers"),
    )


# ---------- admin-api discovery (host → container IP) ----------

def _docker(*args: str) -> str:
    try:
        out = subprocess.run(
            ["docker", *args], capture_output=True, text=True, check=True
        )
    except FileNotFoundError:
        die("missing required command: docker")
    except subprocess.CalledProcessError as exc:
        die(f"docker {' '.join(args)} failed: {exc.stderr.strip()}")
    return out.stdout.strip()


def resolve_admin_base(project: str) -> str:
    """Find the project's admin-api container and return http://<ip>:23457.

    Uses compose labels (not the <project>-admin-api-1 name) so it survives
    container-name quirks; IP is read live because it changes on recreate.
    """
    cid = _docker(
        "ps", "-q",
        "--filter", f"label=com.docker.compose.project={project}",
        "--filter", "label=com.docker.compose.service=admin-api",
    )
    if not cid:
        die(
            f"no running admin-api for project {project!r}. "
            f"Start it first, e.g.\n"
            f"  docker compose --env-file .env.{project} --profile storage --profile app up -d"
        )
    cid = cid.splitlines()[0]
    ip = _docker(
        "inspect", "-f",
        "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", cid,
    )
    if not ip:
        die(f"admin-api container {cid[:12]} has no network IP")
    return f"http://{ip}:{ADMIN_PORT}"


# ---------- HTTP ----------

def _post(base: str, path: str, body: dict) -> tuple[str, str]:
    """POST JSON. Returns ('ok'|'skip'|'fail', detail)."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15):
            return "ok", ""
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            return "skip", ""
        return "fail", f"HTTP {exc.code} — {exc.read().decode('utf-8', 'replace')[:200]}"
    except urllib.error.URLError as exc:
        return "fail", str(exc.reason)


def wait_ready(base: str, tries: int = 30) -> None:
    for _ in range(tries):
        try:
            with urllib.request.urlopen(base + "/api/admin/providers", timeout=5) as resp:
                if resp.status == 200:
                    ok(f"admin-api ready at {base}")
                    return
        except (urllib.error.HTTPError, urllib.error.URLError):
            pass
        time.sleep(1)
    die(f"admin-api not ready at {base} — is the app profile up and migrated?")


def _run(base: str, label: str, path: str, body: dict) -> bool:
    status, detail = _post(base, path, body)
    if status == "ok":
        ok(label)
        return True
    if status == "skip":
        warn(f"{label} (already exists)")
        return True
    warn(f"FAIL {label}: {detail}")
    return False


# ---------- env file ----------

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


# ---------- main ----------

def main() -> None:
    ap = argparse.ArgumentParser(description="One-shot dev seed via admin-api.")
    ap.add_argument("env_file", help="per-instance env file (e.g. .env.debug)")
    ap.add_argument("config", help="path to seed JSON (e.g. scripts/seed.debug.json)")
    args = ap.parse_args()

    project = project_from_env_file(Path(args.env_file))

    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        cfg_path = REPO_ROOT / args.config
    if not cfg_path.is_file():
        die(f"config not found: {args.config}")

    cfg = load_seed_config(cfg_path)
    log(f"project   : {project}")
    log(f"users     : {', '.join(u.username for u in cfg.users)}")
    log(f"providers : {', '.join(p.name for p in cfg.providers)}  (first is default)")

    base = resolve_admin_base(project)
    wait_ready(base)

    failed = False

    # phase 1: first provider alone — it wins the pick_first_provider default
    first = cfg.providers[0]
    log(f"creating default provider: {first.name}")
    failed |= not _run(
        base, f"provider {first.name}", "/api/admin/providers",
        {"name": first.name, "base_url": first.base_url, "model": first.model, "api_key": first.api_key},
    )

    # phase 2: remaining providers in parallel
    rest = cfg.providers[1:]
    if rest:
        log(f"creating remaining providers: {', '.join(p.name for p in rest)}")
        with ThreadPoolExecutor() as ex:
            results = ex.map(
                lambda p: _run(
                    base, f"provider {p.name}", "/api/admin/providers",
                    {"name": p.name, "base_url": p.base_url, "model": p.model, "api_key": p.api_key},
                ),
                rest,
            )
            failed |= not all(results)

    # phase 3: accounts in parallel (need a provider to exist first)
    log(f"creating accounts: {', '.join(u.username for u in cfg.users)}")
    with ThreadPoolExecutor() as ex:
        results = ex.map(
            lambda u: _run(
                base, f"account {u.username}", "/api/admin/accounts",
                {"username": u.username, "password": u.password, "display_name": u.display},
            ),
            cfg.users,
        )
        failed |= not all(results)

    if failed:
        die("one or more seed calls failed")

    print()
    print("---")
    print(f"seed done for project {project!r}:")
    for u in cfg.users:
        print(f"  {u.username} / {u.password}")


if __name__ == "__main__":
    main()
