"""Studio /api/bridge/* protocol client (v2 — 8 endpoints).

  POST /handshake                     password → token (+ account_id, username, machine_id)
  POST /inboxes                       register channels (with display_name)
  GET  /inboxes                       read current inbox set
  POST /heartbeat                     pure heartbeat
  POST /incoming                      push messages (client_id dedup)
  GET  /outbound                      long-poll PENDING (no cursor, no lease, no ack)
  POST /conversations                 upsert conversation metadata
  GET  /takeovers                     pull takeover conversation set

The session token is read lazily through ``get_token`` so we can clear it
on 401 without rebuilding the client. ``X-Machine-Id`` header is added
on every authed request so Studio can resolve the bridge.
"""

from __future__ import annotations

from typing import Callable

from . import config
from .http import HttpError, request_json


class StudioClient:
    def __init__(
        self,
        get_token: Callable[[], str | None],
        get_machine_id: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._get_token = get_token
        self._get_machine_id = get_machine_id

    def _req(self, method: str, path: str, body=None, timeout: float = 20.0):
        machine_id = self._get_machine_id()
        return request_json(
            method,
            f"{config.STUDIO_BASE_URL}{path}",
            token=self._get_token(),
            body=body,
            timeout=timeout,
            headers={"X-Machine-Id": machine_id} if machine_id else None,
        )

    # ---- 1. handshake -------------------------------------------------

    def handshake(
        self, username: str, password: str, machine_id: str | None
    ) -> dict:
        body = {
            "username": username,
            "password": password,
            "machine_id": machine_id,
        }
        url = f"{config.STUDIO_BASE_URL}/api/bridge/handshake"
        try:
            r = request_json("POST", url, body=body)
        except HttpError as exc:
            # A stale machine_id — e.g. this device was revoked from another
            # machine, so Studio no longer has its (account, machine_id) row —
            # returns 400 machine_id_invalid. The protocol contract is to drop
            # the local machine_id and retry without it; Studio then mints a
            # fresh one and re-creates the bridge row, so the legitimate owner
            # re-login self-heals instead of getting stuck on the 400.
            if not (machine_id and exc.status == 400 and "machine_id_invalid" in exc.body):
                raise
            body["machine_id"] = None
            r = request_json("POST", url, body=body)
        return {
            "token": r["token"],
            "account_id": r["account_id"],
            "username": r["username"],
            "machine_id": r["machine_id"],
        }

    # ---- 2/3. inboxes -------------------------------------------------

    @staticmethod
    def _inbox(i: dict) -> dict:
        return {
            "id": i["id"],
            "platform": i["platform"],
            "platform_self_id": i["platform_self_id"],
            "display_name": i["display_name"],
        }

    def register_inboxes(self, claims: list[dict]) -> list[dict]:
        """``claims`` items: ``{platform, platform_self_id, display_name}``.

        Returns the authoritative inbox list (each ``{id, platform,
        platform_self_id, display_name}``).
        """
        r = self._req(
            "POST",
            "/api/bridge/inboxes",
            {"inboxes": claims},
        )
        return [self._inbox(i) for i in r["inboxes"]]

    def get_inboxes(self) -> list[dict]:
        r = self._req("GET", "/api/bridge/inboxes")
        return [self._inbox(i) for i in r["inboxes"]]

    # ---- 4. heartbeat -------------------------------------------------

    def heartbeat(self) -> None:
        self._req("POST", "/api/bridge/heartbeat")

    # ---- 5. incoming --------------------------------------------------

    def push_incoming(self, messages: list[dict]) -> dict:
        """Each item: ``{inbox_id, platform_conversation_id, client_id,
        sender_id (str|None), msg_type, content, sent_at}``.
        """
        return self._req(
            "POST",
            "/api/bridge/incoming",
            {"messages": messages},
        )

    # ---- 6. outbound (long poll, no cursor) ---------------------------

    def get_outbound(self, timeout_secs: int) -> list[dict]:
        res = self._req(
            "GET",
            f"/api/bridge/outbound?timeout={timeout_secs}",
            timeout=timeout_secs + 5,
        )
        return [
            {
                "id": o["id"],
                "inbox_id": o["inbox_id"],
                "platform_conversation_id": o["platform_conversation_id"],
                "msg_type": o["msg_type"],
                "content": o["content"],
            }
            for o in res
        ]

    # ---- 7. conversations (metadata source of truth) ------------------

    def push_conversations(self, inbox_id: str, conversations: list[dict]) -> None:
        """``conversations`` items: ``{platform_conversation_id, kind,
        display_name, members:[{peer_platform_id, display_name}]}``.
        """
        self._req(
            "POST",
            "/api/bridge/conversations",
            {"inbox_id": inbox_id, "conversations": conversations},
        )

    # ---- 8. takeovers -------------------------------------------------

    def get_takeovers(self) -> list[dict]:
        res = self._req("GET", "/api/bridge/takeovers")
        return [
            {
                "inbox_id": t["inbox_id"],
                "platform_conversation_id": t["platform_conversation_id"],
            }
            for t in res["takeovers"]
        ]
