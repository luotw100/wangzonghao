"""Desktop sidecar: the real bridge runtime behind a localhost HTTP API.

This is route 2 — the renderer never talks to Studio directly. Everything
goes through here:

    /local/<method>   thin projection of gui.bridge_api.Api (the same
                      surface the pywebview js_api exposed), driving the
                      Supervisor + actors + sqlite-as-truth runtime.
    /studio/<path>    transparent reverse proxy to STUDIO_BASE_URL/api/*,
                      with the bridge's stored Studio token attached here
                      so the token never reaches the renderer.

Contract with Electron main (see electron/sidecar.ts):
    * Bind 127.0.0.1 on a kernel-assigned port.
    * Print exactly one line to stdout: "BRIDGE_READY port=<P> token=<T>".
    * Require "Authorization: Bearer <T>" on every request but /health.
    * SIGTERM → stop the daemon cleanly, then exit.

The runtime package under laborster_bridge/ is the canonical Bridge
daemon — the same package the bridge-host container installs and runs
headless. Its design (polling actors, no notifies) is intentional.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import ssl
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from laborster_bridge import config
from laborster_bridge.gui.bridge_api import Api
from laborster_bridge.http import HttpError, Unauthorized, request_json

# Same CA story as laborster_bridge.http: pin certifi so frozen builds can
# verify the Cloudflare-fronted Studio/S3 endpoints.
try:
    import certifi

    _SSL_CTX: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = None


def _encode_multipart(fields: dict, filename: str, mime: str, file_bytes: bytes) -> tuple[bytes, str]:
    """Build a multipart/form-data body for an S3 presigned POST.

    The file part must come last (S3 ignores anything after it).
    """
    boundary = "----laborster" + secrets.token_hex(16)
    out = bytearray()
    for k, v in fields.items():
        out += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
        ).encode("utf-8")
    out += (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    out += file_bytes
    out += f"\r\n--{boundary}--\r\n".encode("utf-8")
    return bytes(out), f"multipart/form-data; boundary={boundary}"

APP_NAME = "LaborsterDesktop"
TOKEN = secrets.token_urlsafe(24)

# Allowlist: only these Api methods are reachable. GET = read-only no-arg
# views; POST = mutations whose JSON body becomes kwargs.
READ_METHODS = frozenset(
    {"account", "accounts", "channels", "status", "platforms"}
)
WRITE_METHODS = frozenset(
    {
        "login",
        "logout",
        "use_account",
        "remove_account",
        "channel_rm",
        "flow_begin",
        "flow_submit",
        "flow_poll",
        "flow_cancel",
        "flow_persist",
        "open_data_dir",
    }
)

# Single lock serializes every Api call. The runtime's own actor threads
# keep polling underneath; this only stops two concurrent HTTP requests
# from mutating commands.Context (login/account-switch) at once.
_api_lock = threading.Lock()


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def _studio_token(api: Api) -> str | None:
    store = api._ctx.store
    return store.kv_get("studio_token") if store is not None else None


def _machine_id(api: Api) -> str | None:
    store = api._ctx.store
    return store.kv_get("machine_id") if store is not None else None


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        # ---- helpers --------------------------------------------------

        def _send_json(self, status: int, body) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _check_auth(self) -> bool:
            if self.headers.get("Authorization", "") != f"Bearer {TOKEN}":
                self._send_json(401, {"error": "unauthorized"})
                return False
            return True

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8", "replace")
            if not raw:
                return {}
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"_": parsed}

        # ---- routing --------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/health":
                self._send_json(200, {"ok": True})
                return
            # Media is loaded via <img>/<audio>/<video> which cannot send an
            # Authorization header — authenticate via the local token in the
            # query string instead, then stream bytes from Studio.
            if parsed.path.startswith("/studio/chat/media/"):
                self._media_proxy(parsed)
                return
            if not self._check_auth():
                return
            if parsed.path == "/local/logs":
                qs = urllib.parse.parse_qs(parsed.query)
                n = int((qs.get("n") or ["200"])[0])
                with _api_lock:
                    self._send_json(200, api.logs(n))
                return
            method = self._local_method(parsed.path)
            if method in READ_METHODS:
                with _api_lock:
                    self._send_json(200, getattr(api, method)())
                return
            if parsed.path.startswith("/studio/"):
                self._proxy_studio("GET", parsed)
                return
            self._send_json(404, {"error": "not_found", "path": parsed.path})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlsplit(self.path)
            if not self._check_auth():
                return
            if parsed.path == "/local/chat_upload":
                self._chat_upload(parsed)
                return
            if parsed.path.startswith("/studio/"):
                self._proxy_studio("POST", parsed)
                return
            method = self._local_method(parsed.path)
            if method not in WRITE_METHODS:
                self._send_json(404, {"error": "not_found", "path": parsed.path})
                return
            try:
                kwargs = self._read_body()
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid_json"})
                return
            with _api_lock:
                try:
                    result = getattr(api, method)(**kwargs)
                except TypeError as exc:
                    self._send_json(400, {"error": f"bad_args: {exc}"})
                    return
            self._send_json(200, result)

        def do_PATCH(self) -> None:  # noqa: N802
            self._proxy_or_404("PATCH")

        def do_PUT(self) -> None:  # noqa: N802
            self._proxy_or_404("PUT")

        def do_DELETE(self) -> None:  # noqa: N802
            self._proxy_or_404("DELETE")

        def _proxy_or_404(self, http_method: str) -> None:
            if not self._check_auth():
                return
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path.startswith("/studio/"):
                self._proxy_studio(http_method, parsed)
                return
            self._send_json(404, {"error": "not_found", "path": parsed.path})

        @staticmethod
        def _local_method(path: str) -> str:
            return path[len("/local/"):] if path.startswith("/local/") else ""

        # ---- studio reverse proxy -------------------------------------

        def _proxy_studio(self, http_method: str, parsed) -> None:
            rest = parsed.path[len("/studio/"):]
            url = f"{config.STUDIO_BASE_URL}/api/{rest}"
            if parsed.query:
                url = f"{url}?{parsed.query}"
            try:
                body = self._read_body() if http_method != "GET" else None
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid_json"})
                return
            # Long-poll endpoints carry ?timeout=<secs>; give the upstream
            # request that much headroom plus slack so we don't cut it short.
            timeout = 20.0
            qs = urllib.parse.parse_qs(parsed.query)
            if "timeout" in qs:
                try:
                    timeout = float(qs["timeout"][0]) + 10
                except ValueError:
                    pass
            machine_id = _machine_id(api)
            try:
                result = request_json(
                    http_method,
                    url,
                    token=_studio_token(api),
                    body=body,
                    timeout=timeout,
                    headers={"X-Machine-Id": machine_id} if machine_id else None,
                )
            except Unauthorized:
                self._send_json(401, {"error": "studio_unauthorized"})
                return
            except HttpError as exc:
                self._send_json(exc.status or 502, {"error": exc.body})
                return
            self._send_json(200, result)

        # ---- chat media (binary) + upload (multipart) -----------------

        def _media_proxy(self, parsed) -> None:
            qs = urllib.parse.parse_qs(parsed.query)
            if (qs.get("token") or [""])[0] != TOKEN:
                self._send_json(401, {"error": "unauthorized"})
                return
            key = parsed.path[len("/studio/chat/media/"):]
            studio_tok = _studio_token(api) or ""
            up = (
                f"{config.STUDIO_BASE_URL}/api/chat/media/{key}"
                f"?token={urllib.parse.quote(studio_tok)}"
            )
            req = urllib.request.Request(up, method="GET")
            req.add_header("User-Agent", "laborster-bridge/0.1")
            try:
                with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
                    data = resp.read()
                    ctype = resp.headers.get("Content-Type", "application/octet-stream")
            except urllib.error.HTTPError as exc:
                self.send_response(exc.code)
                self.end_headers()
                return
            except Exception:
                self.send_response(502)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _chat_upload(self, parsed) -> None:
            qs = urllib.parse.parse_qs(parsed.query)
            filename = (qs.get("filename") or ["file"])[0]
            mime = (qs.get("mime") or ["application/octet-stream"])[0]
            length = int(self.headers.get("Content-Length") or 0)
            file_bytes = self.rfile.read(length) if length > 0 else b""

            try:
                presign = request_json(
                    "POST",
                    f"{config.STUDIO_BASE_URL}/api/chat/uploads/presign",
                    token=_studio_token(api),
                    body={"filename": filename, "mime_type": mime},
                )
            except Unauthorized:
                self._send_json(401, {"error": "studio_unauthorized"})
                return
            except HttpError as exc:
                self._send_json(exc.status or 502, {"error": exc.body})
                return

            body, ctype = _encode_multipart(presign["fields"], filename, mime, file_bytes)
            req = urllib.request.Request(presign["upload_url"], data=body, method="POST")
            req.add_header("Content-Type", ctype)
            try:
                urllib.request.urlopen(req, timeout=60, context=_SSL_CTX).close()
            except urllib.error.HTTPError as exc:
                self._send_json(502, {"error": f"上传失败: HTTP {exc.code}"})
                return
            except Exception as exc:  # noqa: BLE001
                self._send_json(502, {"error": f"上传失败: {exc}"})
                return
            self._send_json(200, {"storage_key": presign["storage_key"]})

    return Handler


def main() -> int:
    data_dir = _default_data_dir()
    try:
        config.set_state_root(str(data_dir))
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"cannot create data dir {data_dir}: {exc}\n")
        return 2

    # Resolve the live Studio API host from discovery before any Studio call /
    # the reverse proxy below. Caches last-known-good under the state root.
    config.resolve_studio_base_url()

    api = Api()
    api.autostart()

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
    port = server.server_address[1]

    def _shutdown(*_a) -> None:
        try:
            api.shutdown()
        finally:
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    sys.stdout.write(f"BRIDGE_READY port={port} token={TOKEN}\n")
    sys.stdout.flush()
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
