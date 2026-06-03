"""Tiny JSON-over-HTTP helper shared by the Studio and Chat clients.

Backed by a process-wide urllib3 connection pool so every request reuses a
kept-alive TLS connection instead of paying a fresh TCP+TLS handshake — the
dominant cost on the cross-border path to the Cloudflare-fronted services.
"""

from __future__ import annotations

import json
import time
from typing import Any

import urllib3

# Frozen (PyInstaller) builds ship no system CA bundle, so verification of
# the Cloudflare-fronted endpoints would fail ("unable to get local issuer
# certificate"). Pin certifi's CA bundle, which PyInstaller collects into
# the package and is also correct for the plain CLI. If certifi is somehow
# unavailable, fall back to the system trust store.
try:
    import certifi

    _CA_CERTS: str | None = certifi.where()
except Exception:
    _CA_CERTS = None

# One pool for the whole process: the sidecar's reverse-proxy threads and the
# bridge daemon's actor threads share it. maxsize covers the steady-state
# polls plus a couple of concurrent 30s long-polls and still keeps every
# request on a reused connection; block=False (the default) means any excess
# concurrency degrades to a throwaway connection rather than blocking.
_pool = urllib3.PoolManager(
    maxsize=10,
    ca_certs=_CA_CERTS,
    cert_reqs="CERT_REQUIRED",
)

# Transient statuses worth retrying. 0 = network / TLS drop (the relay in
# front of the services occasionally tears down the connection mid-TLS).
_RETRY_STATUSES = {0, 502, 503, 504}
_RETRY_BACKOFF = (1.0, 2.0, 4.0)


class Unauthorized(RuntimeError):
    """HTTP 401 — session token revoked or invalid."""


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def _attempt(
    method: str,
    url: str,
    token: str | None,
    body: Any,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    # Cloudflare in front of the services blocks the default urllib3
    # User-Agent (403 code 1010); present a normal client UA.
    hdrs = {"User-Agent": "laborster-bridge/0.1"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    for k, v in (headers or {}).items():
        if v is not None:
            hdrs[k] = v
    try:
        # retries=False: the caller's bounded retry loop owns replay
        # semantics. Split the timeout so a 30s long-poll's read window
        # doesn't also stretch the connect phase.
        resp = _pool.request(
            method,
            url,
            body=data,
            headers=hdrs,
            timeout=urllib3.Timeout(connect=10.0, read=timeout),
            retries=False,
            redirect=False,
            preload_content=True,
        )
    except urllib3.exceptions.HTTPError as exc:
        # MaxRetryError / NewConnectionError / ReadTimeoutError /
        # ProtocolError / SSLError all subclass HTTPError — treat as a
        # transient network/TLS drop (status 0) so the retry loop kicks in.
        raise HttpError(0, str(exc)) from None
    # urllib3 does not raise on 4xx/5xx — branch on the status ourselves.
    if resp.status == 401:
        raise Unauthorized() from None
    raw = resp.data.decode("utf-8", "replace")
    if resp.status >= 400:
        raise HttpError(resp.status, raw)
    return json.loads(raw) if raw else None


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: Any | None = None,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
) -> Any:
    """JSON request with bounded retry on transient failures.

    All protocol writes are replay-safe (handshake rebuilds the session;
    /incoming dedups by msg_hash; /inboxes upserts; ack is idempotent),
    so retrying a dropped connection cannot duplicate state.
    """
    last: HttpError | None = None
    for attempt in range(len(_RETRY_BACKOFF) + 1):
        try:
            return _attempt(method, url, token, body, timeout, headers)
        except HttpError as exc:
            if exc.status not in _RETRY_STATUSES or attempt == len(_RETRY_BACKOFF):
                raise
            last = exc
            time.sleep(_RETRY_BACKOFF[attempt])
    assert last is not None
    raise last
