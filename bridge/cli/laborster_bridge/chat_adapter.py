"""Chat sandbox HTTP polling adapter. Port of adapters/chat.ts.

Token-only: the chat password is used exactly once at `/channel add`
time to obtain a session token (``obtain_token``); the daemon then runs
purely off the stored token, recovering its own account id via
``GET /api/auth/me``.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Iterator

from . import config
from .http import request_json


def _iso_z(created_at: str) -> str:
    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class ChatAdapter:
    def __init__(self, token: str, label: str) -> None:
        self._base = config.CHAT_BASE_URL
        self._token = token
        self.label = label
        self._self_id: str | None = None
        self._threads: dict[str, dict] = {}  # peer_id -> {conv_id, peer_id, display_name}
        self._stopped = False

    # --- one-shot credential exchange (used only by /channel add) ---
    @staticmethod
    def obtain_token(username: str, password: str) -> tuple[str, str]:
        r = request_json(
            "POST",
            f"{config.CHAT_BASE_URL}/api/auth/login",
            body={"username": username, "password": password},
        )
        return r["token"], r["account"]["id"]

    def _req(self, method: str, path: str, body=None, timeout: float = 15.0):
        return request_json(
            method, f"{self._base}{path}", token=self._token, body=body, timeout=timeout
        )

    def resolve_self(self) -> str:
        me = self._req("GET", "/api/auth/me")
        self._self_id = me["id"]
        return self._self_id

    @property
    def platform_self_id(self) -> str:
        if not self._self_id:
            raise RuntimeError("not resolved")
        return self._self_id

    def _refresh_threads(self) -> None:
        convs = self._req("GET", "/api/conversations")
        for c in convs:
            contact = c["contact"]
            self._threads[contact["id"]] = {
                "conv_id": c["id"],
                "peer_id": contact["id"],
                "display_name": contact["nickname"] or contact["username"],
            }

    def list_peers(self) -> list[dict]:
        self._refresh_threads()
        return [
            {"peer_platform_id": t["peer_id"], "display_name": t["display_name"]}
            for t in self._threads.values()
        ]

    def scan(self, cursors: dict[str, str | None]) -> Iterator[dict]:
        while not self._stopped:
            try:
                self._refresh_threads()
            except Exception:
                time.sleep(2)
                continue

            yielded = False
            for thread in list(self._threads.values()):
                if self._stopped:
                    break
                since = 0
                try:
                    since = int(cursors.get(thread["peer_id"]) or "0")
                except (TypeError, ValueError):
                    since = 0
                try:
                    payload = self._req(
                        "GET",
                        f"/api/conversations/{thread['conv_id']}/messages"
                        f"?last_id={since}&limit=200",
                    )
                except Exception:
                    continue
                for m in payload["messages"]:
                    cursors[thread["peer_id"]] = str(m["id"])
                    yielded = True
                    yield {
                        "peer_id": thread["peer_id"],
                        "peer_display_name": thread["display_name"],
                        "platform_msg_id": str(m["id"]),
                        "sender_id": (
                            self.platform_self_id
                            if m["sender_type"] == "self"
                            else thread["peer_id"]
                        ),
                        "msg_type": m.get("msg_type") or "text",
                        "content": m["content"],
                        "sent_at": _iso_z(m["created_at"]),
                    }
            if not yielded:
                time.sleep(2)

    def send(self, peer_id: str, content: str) -> str:
        thread = self._threads.get(peer_id)
        if not thread:
            raise RuntimeError(f"unknown peer {peer_id}")
        r = self._req(
            "POST",
            f"/api/conversations/{thread['conv_id']}/messages",
            {"sender_type": "self", "msg_type": "text", "content": content},
        )
        return str(r["id"]) if r.get("id") is not None else ""

    def stop(self) -> None:
        self._stopped = True
