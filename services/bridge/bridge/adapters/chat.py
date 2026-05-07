"""Chat sandbox adapter.

The Chat sandbox stands in for "platform A" while we dogfood the bridge
protocol. The bridge logs into a chat account (which is the streamer's
on-chat identity) and round-robin polls all of that account's conversations.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional

import httpx

from bridge.adapters.base import Adapter, IncomingMessage, register_adapter

logger = logging.getLogger(__name__)


def _required(d: dict, key: str) -> str:
    v = d.get(key)
    if not v:
        raise SystemExit(f"chat adapter inbox config requires '{key}'")
    return str(v)


def _build_chat_adapter(raw_config: dict) -> Adapter:
    return ChatAdapter(
        base_url=_required(raw_config, "chat_base_url"),
        username=_required(raw_config, "chat_username"),
        password=_required(raw_config, "chat_password"),
    )


def _parse_iso(s: str) -> datetime:
    # Chat returns naive ISO without timezone; treat as UTC.
    if s.endswith("Z"):
        s = s[:-1]
    return datetime.fromisoformat(s)


class ChatAdapter(Adapter):
    platform = "chat"

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._http: Optional[httpx.AsyncClient] = None
        self._token: Optional[str] = None
        self._self_account_id: Optional[str] = None
        # Per-conversation state: keyed by conversation_id
        self._threads: Dict[str, Dict[str, object]] = {}
        # Refresh-conversations interval in stream loop
        self._poll_sleep = 2.0

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    @property
    def _auth_headers(self) -> Dict[str, str]:
        if not self._token:
            raise RuntimeError("chat adapter not logged in")
        return {"Authorization": f"Bearer {self._token}"}

    async def login(self) -> str:
        r = await self.http.post(
            f"{self.base}/api/auth/login",
            json={"username": self.username, "password": self.password},
        )
        r.raise_for_status()
        data = r.json()
        self._token = data["token"]
        self._self_account_id = data["account"]["id"]
        logger.info("chat: logged in as %s (id=%s)", self.username, self._self_account_id)
        return self._self_account_id  # type: ignore[return-value]

    async def _refresh_threads(self) -> None:
        r = await self.http.get(f"{self.base}/api/conversations", headers=self._auth_headers)
        r.raise_for_status()
        for conv in r.json():
            cid = conv["id"]
            contact = conv["contact"]
            entry = self._threads.get(cid)
            if entry is None:
                self._threads[cid] = {
                    "peer_id": contact["id"],
                    "peer_display_name": contact["display_name"],
                    "last_msg_id": 0,
                }
            else:
                entry["peer_display_name"] = contact["display_name"]

    def _conv_id_for_peer(self, peer_id: str) -> Optional[str]:
        for cid, t in self._threads.items():
            if t["peer_id"] == peer_id:
                return cid
        return None

    async def _fetch_conv_messages(self, conv_id: str, last_id: int) -> List[Dict[str, object]]:
        r = await self.http.get(
            f"{self.base}/api/conversations/{conv_id}/messages",
            params={"last_id": last_id, "timeout": 0},
            headers=self._auth_headers,
        )
        r.raise_for_status()
        return r.json().get("messages", [])

    def _msg_to_incoming(self, conv_state: Dict[str, object], m: Dict[str, object]) -> IncomingMessage:
        role = "self" if m["sender_type"] == "self" else "counterpart"
        return IncomingMessage(
            peer_id=str(conv_state["peer_id"]),
            peer_display_name=str(conv_state["peer_display_name"]),
            platform_msg_id=str(m["id"]),
            role=role,
            content=str(m["content"]),
            sent_at=_parse_iso(str(m["created_at"])),
        )

    async def list_initial_messages(self, since_ms: int) -> List[IncomingMessage]:
        await self._refresh_threads()
        out: List[IncomingMessage] = []
        for cid, conv_state in self._threads.items():
            msgs = await self._fetch_conv_messages(cid, last_id=0)
            for m in msgs:
                out.append(self._msg_to_incoming(conv_state, m))
                if int(m["id"]) > int(conv_state["last_msg_id"]):
                    conv_state["last_msg_id"] = int(m["id"])
        return out

    async def stream_incoming(self) -> AsyncIterator[IncomingMessage]:
        while True:
            try:
                await self._refresh_threads()
                yielded = 0
                for cid, conv_state in list(self._threads.items()):
                    msgs = await self._fetch_conv_messages(cid, int(conv_state["last_msg_id"]))
                    for m in msgs:
                        yield self._msg_to_incoming(conv_state, m)
                        yielded += 1
                        if int(m["id"]) > int(conv_state["last_msg_id"]):
                            conv_state["last_msg_id"] = int(m["id"])
                if yielded == 0:
                    await asyncio.sleep(self._poll_sleep)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 401:
                    logger.warning("chat: session expired, re-login")
                    await self.login()
                else:
                    logger.error("chat poll http error: %s", exc)
                    await asyncio.sleep(self._poll_sleep)
            except Exception as exc:
                logger.error("chat poll error: %s", exc)
                await asyncio.sleep(self._poll_sleep)

    async def send_text(self, peer_id: str, content: str) -> str:
        conv_id = self._conv_id_for_peer(peer_id)
        if conv_id is None:
            await self._refresh_threads()
            conv_id = self._conv_id_for_peer(peer_id)
        if conv_id is None:
            raise ValueError(f"chat: no conversation for peer_id {peer_id}")
        r = await self.http.post(
            f"{self.base}/api/conversations/{conv_id}/messages",
            json={"sender_type": "self", "msg_type": "text", "content": content},
            headers=self._auth_headers,
        )
        r.raise_for_status()
        platform_msg_id = str(r.json().get("id"))
        # Pre-bump our cursor so we don't immediately re-yield our own send.
        # The next poll will see the message but skip it (or yield it once,
        # which is fine — Studio dedups by external_id).
        return platform_msg_id

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None


register_adapter("chat", _build_chat_adapter)
