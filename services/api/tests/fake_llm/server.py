"""Tiny OpenAI-compatible LLM stub used by the test suite.

Listens on :8080 inside the docker network as the `fake-llm` service.
Returns deterministic JSON-formatted replies in the shape ReplyBrain's
``_parse_chunks`` expects (``{"messages": [...]}``).

Reply policy: echo the latest "user" message split into one chunk. If
the message starts with a control prefix it is recognised:

  ``FAKE_MULTI:<n>:<text>`` → returns n chunks each equal to ``<text>``
  ``FAKE_EMPTY``            → returns ``{"messages": []}`` (intentional silence)
  ``FAKE_ERROR``            → responds with HTTP 500

Everything else: returns ``{"messages": ["echo: <last user content>"]}``.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _build_reply(messages: list[dict]) -> tuple[int, dict]:
    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user = str(m.get("content", ""))
            break

    # The worker wraps history into JSON, so the literal user content sent
    # by the test is embedded inside last_user, not the whole string.
    # Match by substring instead of equality.
    if "FAKE_ERROR" in last_user:
        return 500, {"error": {"message": "fake llm forced error"}}
    if "FAKE_EMPTY" in last_user:
        chunks: list[str] = []
    elif "FAKE_MULTI:" in last_user:
        # Find the directive and parse `FAKE_MULTI:<n>:<text>` up to a
        # closing quote (we get embedded JSON, so a quote bounds it).
        idx = last_user.index("FAKE_MULTI:")
        tail = last_user[idx + len("FAKE_MULTI:"):]
        end = tail.find('"')
        if end == -1:
            end = len(tail)
        directive = tail[:end]
        try:
            n_s, text = directive.split(":", 1)
            n = int(n_s)
        except Exception:
            n = 1
            text = directive
        chunks = [text for _ in range(max(1, n))]
    else:
        chunks = [f"echo: {last_user[:200]}"]

    content = json.dumps({"messages": chunks}, ensure_ascii=False)
    payload = {
        "id": "fake-cmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "fake-model",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    return 200, payload


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n) if n else b"{}"
        try:
            req = json.loads(raw)
        except Exception:
            self.send_error(400, "invalid json")
            return
        status, body = _build_reply(req.get("messages") or [])
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_error(404)

    def log_message(self, format, *args):  # noqa: A002
        # Quiet logs; uncomment for debugging.
        return


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    print("fake-llm listening on :8080", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
