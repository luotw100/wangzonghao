"""Tiny urllib JSON helper shared by the Studio and Chat clients."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class Unauthorized(RuntimeError):
    """HTTP 401 — session token revoked or invalid."""


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: Any | None = None,
    timeout: float = 10.0,
) -> Any:
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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise Unauthorized() from None
        detail = exc.read().decode("utf-8", "replace")
        raise HttpError(exc.code, detail) from None
    except urllib.error.URLError as exc:
        raise HttpError(0, str(exc.reason)) from None
