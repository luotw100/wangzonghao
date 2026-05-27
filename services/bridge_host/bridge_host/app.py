"""bridge-host — operator-managed supervisor for chat-only bridges.

One subprocess per Studio account. Admin-api drives the lifecycle via
the HTTP endpoints here; no auto-recovery, no auto-restart — this
service is intentionally dumb so the operator owns the lifecycle.

State here is in-memory only: pid + Popen handle keyed by account_id.
On restart bridge-host comes up with zero subprocesses; admin sees stale
``running`` rows in the panel and must click Restart explicitly. That's
the deal we agreed to in design — bridge-host is an executor, not the
source of truth for liveness.

Subprocess args: see ``laborster_bridge.__main__``.

Security note: the Studio session token is passed to the subprocess
as a CLI argument, so it is visible in ``/proc/<pid>/cmdline`` and
``ps``. This is acceptable because bridge-host runs in a single-tenant
container on the docker internal network — only the operator has shell
access. If that ever changes, switch to an env var or stdin handshake.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

STATE_ROOT = Path(os.environ.get("BRIDGE_STATE_ROOT", "/data"))

app = FastAPI(
    title="Laborster bridge-host",
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json",
)


class _Process:
    __slots__ = ("popen", "started_at")

    def __init__(self, popen: subprocess.Popen, started_at: float) -> None:
        self.popen = popen
        self.started_at = started_at


_procs: dict[str, _Process] = {}
_lock = threading.Lock()


def _alive(p: _Process) -> bool:
    return p.popen.poll() is None


class SpawnIn(BaseModel):
    account_id: str
    token: str
    machine_id: str
    studio_url: str
    display_name: str


class StopIn(BaseModel):
    account_id: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "tracked": len(_procs)}


@app.post("/spawn")
def spawn(body: SpawnIn) -> dict:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)

    with _lock:
        existing = _procs.get(body.account_id)
        if existing is not None and _alive(existing):
            # Idempotent on its face but the new token would be wasted;
            # admin-api is expected to call /stop first. We surface 409 so
            # the operator notices.
            raise HTTPException(409, "subprocess already running for account")

        cmd = [
            "python", "-m", "laborster_bridge",
            "--headless",
            "--state", str(STATE_ROOT),
            "--studio-url", body.studio_url,
            "--account-id", body.account_id,
            "--token", body.token,
            "--machine-id", body.machine_id,
            "--display-name", body.display_name,
        ]
        try:
            # Inherit stdout/stderr so subprocess output (the headless
            # log-pump + startup banner) lands in `docker logs bridge-host`.
            # Lines from different accounts interleave; the bridge log
            # prefixes carry account context (machine_id in the banner,
            # `chN` in worker logs).
            popen = subprocess.Popen(  # noqa: S603
                cmd,
                stdout=None,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            raise HTTPException(500, f"spawn failed: {exc}")
        _procs[body.account_id] = _Process(popen, time.time())
        return {"pid": popen.pid}


@app.post("/stop")
def stop(body: StopIn) -> dict:
    with _lock:
        proc = _procs.pop(body.account_id, None)
    if proc is None:
        return {"stopped": False, "reason": "not tracked"}
    if not _alive(proc):
        return {"stopped": True, "exit_code": proc.popen.returncode}

    try:
        proc.popen.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        return {"stopped": True, "exit_code": proc.popen.returncode}

    try:
        proc.popen.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.popen.kill()
        proc.popen.wait(timeout=2)

    return {"stopped": True, "exit_code": proc.popen.returncode}


@app.get("/status")
def status() -> dict:
    out: dict[str, dict] = {}
    with _lock:
        for aid, p in _procs.items():
            rc = p.popen.poll()
            out[aid] = {
                "pid": p.popen.pid,
                "alive": rc is None,
                "exit_code": rc,
                "started_at": p.started_at,
            }
    return {"subprocesses": out}
