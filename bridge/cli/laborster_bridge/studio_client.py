"""Studio /api/bridge/* protocol client. Port of studio-client.ts.

The base URL is fixed (config.STUDIO_BASE_URL). The token is read lazily
through a callable so it can be cleared on 401 without rebuilding the
client.
"""

from __future__ import annotations

from typing import Callable

from . import config
from .http import request_json


class StudioClient:
    def __init__(
        self,
        get_token: Callable[[], str | None],
        get_machine_id: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._get_token = get_token
        self._get_machine_id = get_machine_id
        self._base = config.STUDIO_BASE_URL

    def _req(self, method: str, path: str, body=None, timeout: float = 20.0):
        # The session token is account-scoped (same table as the web
        # console). Which Bridge row this call belongs to is resolved
        # server-side from this machine_id, not from the token.
        machine_id = self._get_machine_id()
        return request_json(
            method,
            f"{self._base}{path}",
            token=self._get_token(),
            body=body,
            timeout=timeout,
            headers={"X-Machine-Id": machine_id} if machine_id else None,
        )

    def handshake(self, username: str, password: str, machine_id: str | None) -> dict:
        r = request_json(
            "POST",
            f"{self._base}/api/bridge/handshake",
            body={"username": username, "password": password, "machine_id": machine_id},
        )
        return {
            "token": r["token"],
            "bridge_id": r["bridge_id"],
            "machine_id": r["machine_id"],
            "account_id": r["account_id"],
        }

    @staticmethod
    def _inbox(i: dict) -> dict:
        # Mirrors Studio's BridgeInboxView (schemas.py): the wire format
        # intentionally hides account_id/bridge_id/enabled/default_persona_id;
        # we only need what the runtime actually consumes.
        return {
            "id": i["id"],
            "platform": i["platform"],
            "platform_self_id": i["platform_self_id"],
            "display_name": i["display_name"],
        }

    def register_inboxes(self, self_ids: list[tuple[str, str]]) -> dict:
        r = self._req(
            "POST",
            "/api/bridge/inboxes",
            {
                "inboxes": [
                    {"platform": platform, "platform_self_id": sid}
                    for platform, sid in self_ids
                ]
            },
        )
        return {
            "inboxes": [self._inbox(i) for i in r["inboxes"]],
            "cursor": r["cursor"],
        }

    def heartbeat(self) -> dict:
        r = self._req("POST", "/api/bridge/heartbeat")
        return {"inboxes": [self._inbox(i) for i in r["inboxes"]]}

    def push_incoming(self, messages: list[dict]) -> dict:
        return self._req(
            "POST",
            "/api/bridge/incoming",
            {
                "messages": [
                    {
                        "inbox_id": m["inbox_id"],
                        "peer_platform_id": m["peer_id"],
                        "peer_display_name": m["peer_display_name"],
                        "platform_msg_id": m["platform_msg_id"],
                        "sender_id": m["sender_id"],
                        "msg_type": m["msg_type"],
                        "content": m["content"],
                        "sent_at": m["sent_at"],
                    }
                    for m in messages
                ]
            },
        )

    def get_outbound(self, cursor: int, timeout_secs: int) -> list[dict]:
        res = self._req(
            "GET",
            f"/api/bridge/outbound?cursor={cursor}&timeout={timeout_secs}",
            timeout=timeout_secs + 5,
        )
        return [
            {
                "id": o["id"],
                "inbox_id": o["inbox_id"],
                "contact_id": o["contact_id"],
                "peer_platform_id": o["peer_platform_id"],
                "msg_type": o["msg_type"],
                "content": o["content"],
            }
            for o in res
        ]

    def ack_outbound(self, outbound_id: int, result: str, extra: str) -> None:
        payload = {"result": result}
        payload["platform_msg_id" if result == "sent" else "reason"] = extra
        self._req("POST", f"/api/bridge/outbound/{outbound_id}/ack", payload)

    def announce_peers(self, inbox_id: str, peers: list[dict]) -> None:
        self._req(
            "POST",
            "/api/bridge/peers",
            {
                "inbox_id": inbox_id,
                "peers": [
                    {"peer_platform_id": p["peer_platform_id"], "display_name": p["display_name"]}
                    for p in peers
                ],
            },
        )

    def get_active_peers(self) -> list[dict]:
        res = self._req("GET", "/api/bridge/active-peers")
        return [
            {"inbox_id": p["inbox_id"], "peer_platform_id": p["peer_platform_id"]}
            for p in res["peers"]
        ]
