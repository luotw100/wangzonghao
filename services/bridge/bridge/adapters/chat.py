"""Chat sandbox adapter.

The Chat sandbox stands in for "platform A" while we dogfood the bridge
protocol. The bridge logs into a chat account (which is the streamer's
on-chat identity) and polls all of that account's conversations.
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
from datetime import datetime, timezone
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
        base_url=_required(raw_config, "base_url"),
        username=_required(raw_config, "username"),
        password=_required(raw_config, "password"),
    )


def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class ChatAdapter(Adapter):
    platform = "chat"

    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._http: Optional[httpx.AsyncClient] = None
        self._token: Optional[str] = None
        self._self_account_id: Optional[str] = None
        # conv_id → {peer_id, peer_display_name}
        self._threads: Dict[str, Dict[str, object]] = {}
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
            display_name = (
                contact.get("remark_name")
                or contact.get("nickname")
                or contact.get("username")
                or contact["id"]
            )
            if cid not in self._threads:
                self._threads[cid] = {
                    "peer_id": contact["id"],
                    "peer_display_name": display_name,
                }
            else:
                self._threads[cid]["peer_display_name"] = display_name

    def _conv_id_for_peer(self, peer_id: str) -> Optional[str]:
        for cid, t in self._threads.items():
            if t["peer_id"] == peer_id:
                return cid
        return None

    async def _fetch_since(self, conv_id: str, since_id: int) -> List[Dict[str, object]]:
        r = await self.http.get(
            f"{self.base}/api/conversations/{conv_id}/messages",
            params={"last_id": since_id, "timeout": 0},
            headers=self._auth_headers,
        )
        r.raise_for_status()
        return r.json().get("messages", [])

    def _msg_to_incoming(
        self, conv_state: Dict[str, object], m: Dict[str, object]
    ) -> IncomingMessage:
        if m["sender_type"] == "self":
            sender_id = self._self_account_id or ""
        else:
            sender_id = str(conv_state["peer_id"])
        return IncomingMessage(
            peer_id=str(conv_state["peer_id"]),
            peer_display_name=str(conv_state["peer_display_name"]),
            platform_msg_id=str(m["id"]),
            sender_id=sender_id,
            msg_type=str(m.get("msg_type", "text")),
            content=str(m["content"]),
            sent_at=_parse_iso(str(m["created_at"])),
        )

    async def scan(
        self,
        cursors: dict[str, str | None],
    ) -> AsyncIterator[IncomingMessage]:
        """Continuously yield messages. Merges historical and live in one loop."""
        while True:
            try:
                await self._refresh_threads()
                yielded = 0
                for cid, conv_state in list(self._threads.items()):
                    peer_id = str(conv_state["peer_id"])
                    since_str = cursors.get(peer_id)
                    since_id = int(since_str) if since_str else 0
                    msgs = await self._fetch_since(cid, since_id)
                    for m in msgs:
                        yield self._msg_to_incoming(conv_state, m)
                        yielded += 1
                        msg_id = int(m["id"])
                        prev = int(cursors.get(peer_id) or 0)
                        if msg_id > prev:
                            cursors[peer_id] = str(msg_id)
                if yielded == 0:
                    await asyncio.sleep(self._poll_sleep)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 401:
                    logger.warning("chat: session expired, re-login")
                    await self.login()
                else:
                    logger.error("chat poll http error: %s", exc)
                    await asyncio.sleep(self._poll_sleep)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.error("chat poll error: %s", exc)
                await asyncio.sleep(self._poll_sleep)

    async def send(self, peer_id: str, msg_type: str, content: str) -> str:
        conv_id = self._conv_id_for_peer(peer_id)
        if conv_id is None:
            await self._refresh_threads()
            conv_id = self._conv_id_for_peer(peer_id)
        if conv_id is None:
            raise ValueError(f"chat: no conversation for peer_id {peer_id}")
        r = await self.http.post(
            f"{self.base}/api/conversations/{conv_id}/messages",
            json={"sender_type": "self", "msg_type": msg_type, "content": content},
            headers=self._auth_headers,
        )
        r.raise_for_status()
        return str(r.json().get("id"))

    async def send_text(self, peer_id: str, content: str) -> str:
        return await self.send(peer_id, "text", content)

    async def download_media(self, storage_key: str) -> tuple[bytes, str]:
        r = await self.http.get(
            f"{self.base}/api/media/{storage_key}",
            headers=self._auth_headers,
            follow_redirects=True,
        )
        r.raise_for_status()
        mime_type = r.headers.get("content-type", "application/octet-stream")
        return r.content, mime_type

    async def upload_and_send_media(
        self, peer_id: str, msg_type: str, data: bytes, filename: str, mime_type: str,
    ) -> str:
        conv_id = self._conv_id_for_peer(peer_id)
        if conv_id is None:
            await self._refresh_threads()
            conv_id = self._conv_id_for_peer(peer_id)
        if conv_id is None:
            raise ValueError(f"chat: no conversation for peer_id {peer_id}")

        presign_r = await self.http.post(
            f"{self.base}/api/uploads/presign",
            json={"filename": filename, "mime_type": mime_type},
            headers=self._auth_headers,
        )
        presign_r.raise_for_status()
        presign = presign_r.json()
        put_r = await self.http.put(
            presign["upload_url"], content=data, headers={"Content-Type": mime_type},
        )
        put_r.raise_for_status()
        return await self.send(peer_id, msg_type, presign["storage_key"])

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None


register_adapter("chat", _build_chat_adapter)
