"""Thin client for Studio's /api/bridge/* endpoints.

The handshake takes the Studio account credentials directly; Studio mints
a per-handshake session token. All subsequent calls (heartbeat / incoming /
outbound long-poll / ack) use that token via Authorization: Bearer.

Two http clients are kept: one normal-timeout for control calls, one with
a longer timeout that's forgiving of long polls.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class StudioClient:
    def __init__(
        self,
        base_url: str,
        *,
        username: str,
        password: str,
        request_timeout: float = 60.0,
    ) -> None:
        self.base = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._token: Optional[str] = None
        self._http = httpx.AsyncClient(timeout=request_timeout)
        self._long_poll = httpx.AsyncClient(timeout=request_timeout + 30)

    @property
    def http(self) -> httpx.AsyncClient:
        return self._http

    async def close(self) -> None:
        await self._http.aclose()
        await self._long_poll.aclose()

    @property
    def _headers(self) -> Dict[str, str]:
        if not self._token:
            raise RuntimeError("StudioClient has no token; call handshake() first")
        return {"Authorization": f"Bearer {self._token}"}

    async def handshake(
        self, hostname: str, inboxes: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Login + register + report served inboxes in one call.

        inboxes: [{"platform": ..., "platform_self_id": ...}, ...].
        Studio resolves each pair to an inbox_id (auto-creating Inbox rows
        for first-time pairs) and returns the authoritative served list,
        plus a session token for subsequent /api/bridge/* calls.
        """
        r = await self._http.post(
            f"{self.base}/api/bridge/handshake",
            json={
                "username": self._username,
                "password": self._password,
                "hostname": hostname,
                "inboxes": inboxes,
            },
        )
        r.raise_for_status()
        data = r.json()
        self._token = str(data["token"])
        return data

    async def heartbeat(self) -> Dict[str, Any]:
        r = await self._http.post(
            f"{self.base}/api/bridge/heartbeat", headers=self._headers,
        )
        r.raise_for_status()
        return r.json()

    async def push_incoming(self, messages: List[Dict[str, Any]]) -> Dict[str, int]:
        if not messages:
            return {"accepted": 0, "deduped": 0, "rejected": 0}
        r = await self._http.post(
            f"{self.base}/api/bridge/incoming",
            json={"messages": messages},
            headers=self._headers,
        )
        r.raise_for_status()
        return r.json()

    async def long_poll_outbound(self, cursor: int, timeout_seconds: int) -> List[Dict[str, Any]]:
        r = await self._long_poll.get(
            f"{self.base}/api/bridge/outbound",
            params={"cursor": cursor, "timeout": timeout_seconds},
            headers=self._headers,
        )
        r.raise_for_status()
        return r.json()

    async def ack_outbound(
        self,
        outbound_id: int,
        result: str,
        platform_msg_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> None:
        body: Dict[str, Any] = {"result": result}
        if platform_msg_id is not None:
            body["platform_msg_id"] = platform_msg_id
        if reason is not None:
            body["reason"] = reason
        r = await self._http.post(
            f"{self.base}/api/bridge/outbound/{outbound_id}/ack",
            json=body,
            headers=self._headers,
        )
        r.raise_for_status()

    async def presign_upload(self, filename: str, mime_type: str) -> Dict[str, str]:
        """Request a presigned upload URL from Studio S3.

        Returns {"storage_key": "...", "upload_url": "..."}.
        Bridge PUTs the binary to upload_url, then uses storage_key as
        the content field in the incoming message.
        """
        r = await self._http.post(
            f"{self.base}/api/bridge/media/presign-upload",
            json={"filename": filename, "mime_type": mime_type},
            headers=self._headers,
        )
        r.raise_for_status()
        return r.json()

    async def get_media_url(self, storage_key: str) -> str:
        """Get a presigned GET URL for downloading media from Studio S3.

        Studio returns 302 redirect; we extract the Location header.
        """
        r = await self._http.get(
            f"{self.base}/api/bridge/media/{storage_key}",
            headers=self._headers,
            follow_redirects=False,
        )
        if r.status_code in (301, 302, 303, 307, 308):
            url = r.headers.get("location", "")
            if not url:
                raise RuntimeError(f"Studio returned redirect without Location header for {storage_key}")
            return url
        r.raise_for_status()
        raise RuntimeError(
            f"Studio media endpoint returned unexpected status {r.status_code} for {storage_key}"
        )
