"""Tiny urllib JSON helper shared by the Studio and Chat clients."""

from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

# Frozen (PyInstaller) builds ship no system CA bundle, so the default
# SSL context can't verify the Cloudflare-fronted endpoints ("unable to
# get local issuer certificate"). Pin certifi's CA bundle, which is
# collected into the package by PyInstaller's certifi hook and is also
# correct for the plain CLI.
try:
    import certifi

    _SSL_CTX: ssl.SSLContext | None = ssl.create_default_context(
        cafile=certifi.where()
    )
except Exception:
    _SSL_CTX = None

# Transient statuses worth retrying. 0 = network / TLS drop (the cloudflared
# tunnel in front of the services is slow and occasionally tears down the
# connection mid-TLS: "UNEXPECTED_EOF_WHILE_READING").
_RETRY_STATUSES = {0, 502, 503, 504}
_RETRY_BACKOFF = (1.0, 2.0, 4.0)


class Unauthorized(RuntimeError):
    """HTTP 401 — session token revoked or invalid."""


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def _attempt(method: str, url: str, token: str | None, body: Any, timeout: float) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    # Cloudflare in front of the services blocks the default Python-urllib
    # User-Agent (403 code 1010); present a normal client UA.
    req.add_header("User-Agent", "laborster-bridge/0.1")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise Unauthorized() from None
        detail = exc.read().decode("utf-8", "replace")
        raise HttpError(exc.code, detail) from None
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise HttpError(0, str(reason)) from None


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: Any | None = None,
    timeout: float = 20.0,
) -> Any:
    """JSON request with bounded retry on transient failures.

    All protocol writes are replay-safe (handshake rebuilds the session;
    /incoming dedups by msg_hash; /inboxes upserts; ack is idempotent),
    so retrying a dropped connection cannot duplicate state.
    """
    last: HttpError | None = None
    for attempt in range(len(_RETRY_BACKOFF) + 1):
        try:
            return _attempt(method, url, token, body, timeout)
        except HttpError as exc:
            if exc.status not in _RETRY_STATUSES or attempt == len(_RETRY_BACKOFF):
                raise
            last = exc
            time.sleep(_RETRY_BACKOFF[attempt])
    assert last is not None
    raise last
