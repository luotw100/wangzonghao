"""Chat sandbox HTTP polling adapter.

Token-only: the chat password is used exactly once at ``/channel add``
time to obtain a session token (:meth:`ChatAdapter.obtain_token`); the
daemon then runs purely off the stored token, recovering its own
account id via ``GET /api/auth/me``.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Iterator

from .. import config
from ..http import request_json
from . import AdapterFactory, register

_SCAN_BATCH = 200


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

    def _req(self, method: str, path: str, body=None, timeout: float = 20.0):
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
        """Poll every thread, draining each fully from its cursor.

        Per thread we page forward through ``/messages/after`` (id-ordered,
        ``last_id`` exclusive) a batch at a time until a short page proves
        the backlog is exhausted, so a thread with thousands of unseen
        messages is fully pulled rather than capped at one batch.
        """
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
                try:
                    since = int(cursors.get(thread["peer_id"]) or "0")
                except (TypeError, ValueError):
                    since = 0
                while not self._stopped:
                    try:
                        payload = self._req(
                            "GET",
                            f"/api/conversations/{thread['conv_id']}/messages/after"
                            f"?last_id={since}&limit={_SCAN_BATCH}",
                        )
                    except Exception:
                        break
                    msgs = payload["messages"]
                    for m in msgs:
                        since = int(m["id"])
                        cursors[thread["peer_id"]] = str(m["id"])
                        yielded = True
                        yield {
                            "peer_id": thread["peer_id"],
                            "peer_display_name": thread["display_name"],
                            "platform_msg_id": str(m["id"]),
                            "sender_id": (
                                self.platform_self_id
                                if m["sender_id"] is None
                                else thread["peer_id"]
                            ),
                            "msg_type": m.get("msg_type") or "text",
                            "content": m["content"],
                            "sent_at": _iso_z(m["created_at"]),
                        }
                    if len(msgs) < _SCAN_BATCH:
                        break
            if not yielded:
                time.sleep(2)

    def send(self, peer_id: str, content: str) -> str:
        thread = self._threads.get(peer_id)
        if not thread:
            raise RuntimeError(f"unknown peer {peer_id}")
        # sender_id omitted => the chat service records it as a self-sent
        # message. The send endpoint returns StatusResponse (no message id),
        # so there is no platform_msg_id to hand back.
        self._req(
            "POST",
            f"/api/conversations/{thread['conv_id']}/messages",
            {"messages": [{"msg_type": "text", "content": content}]},
        )
        return ""

    def stop(self) -> None:
        self._stopped = True


register(AdapterFactory(
    platform="chat",
    build=lambda token, label: ChatAdapter(token, label),
    obtain_token=ChatAdapter.obtain_token,
))
