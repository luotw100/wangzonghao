"""Thin client for Studio's /api/bridge/* endpoints."""

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
        self, machine_id: Optional[str], inboxes: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        body: Dict[str, object] = {
            "username": self._username,
            "password": self._password,
            "inboxes": inboxes,
        }
        if machine_id is not None:
            body["machine_id"] = machine_id
        r = await self._http.post(f"{self.base}/api/bridge/handshake", json=body)
        r.raise_for_status()
        data = r.json()
        self._token = str(data["token"])
        return data

    async def try_heartbeat(self) -> Optional[Dict[str, Any]]:
        r = await self._http.post(
            f"{self.base}/api/bridge/heartbeat", headers=self._headers,
        )
        if r.status_code == 401:
            return None
        r.raise_for_status()
        return r.json()

    @property
    def token(self) -> Optional[str]:
        return self._token

    @token.setter
    def token(self, value: Optional[str]) -> None:
        self._token = value

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

    async def check_or_presign_media(
        self, content_hash: str, filename: str, mime_type: str
    ) -> tuple[str, str, Optional[str]]:
        """Check if Studio already has a file with this hash; presign upload if not.

        Returns (status, storage_key, upload_url_or_None).
        status is "exists" (skip upload) or "new" (must PUT to upload_url).
        """
        r = await self._http.post(
            f"{self.base}/api/bridge/media/check-or-presign",
            json={"content_hash": content_hash, "filename": filename, "mime_type": mime_type},
            headers=self._headers,
        )
        r.raise_for_status()
        data = r.json()
        return data["status"], data["storage_key"], data.get("upload_url")

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
        r = await self._http.post(
            f"{self.base}/api/bridge/media/presign-upload",
            json={"filename": filename, "mime_type": mime_type},
            headers=self._headers,
        )
        r.raise_for_status()
        return r.json()

    async def get_media_url(self, storage_key: str) -> str:
        r = await self._http.get(
            f"{self.base}/api/bridge/media/{storage_key}",
            headers=self._headers,
            follow_redirects=False,
        )
        if r.status_code in (301, 302, 303, 307, 308):
            url = r.headers.get("location", "")
            if not url:
                raise RuntimeError(
                    f"Studio returned redirect without Location for {storage_key}"
                )
            return url
        r.raise_for_status()
        raise RuntimeError(
            f"Studio media endpoint returned unexpected status {r.status_code} for {storage_key}"
        )
