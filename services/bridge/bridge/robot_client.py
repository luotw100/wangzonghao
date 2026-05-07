"""Thin client for Robot's /api/bridge/* endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class RobotClient:
    def __init__(self, base_url: str, b_token: str, *, request_timeout: float = 60.0) -> None:
        self.base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {b_token}"}
        self._http = httpx.AsyncClient(timeout=request_timeout)
        self._long_poll = httpx.AsyncClient(timeout=request_timeout + 30)

    async def close(self) -> None:
        await self._http.aclose()
        await self._long_poll.aclose()

    async def handshake(self, hostname: str, platform_self_id: str) -> Dict[str, Any]:
        r = await self._http.post(
            f"{self.base}/api/bridge/handshake",
            json={"hostname": hostname, "platform_self_id": platform_self_id},
            headers=self._headers,
        )
        r.raise_for_status()
        return r.json()

    async def heartbeat(self) -> None:
        r = await self._http.post(f"{self.base}/api/bridge/heartbeat", headers=self._headers)
        r.raise_for_status()

    async def push_incoming(
        self,
        messages: List[Dict[str, Any]],
    ) -> Dict[str, int]:
        if not messages:
            return {"accepted": 0, "deduped": 0}
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
        outbound_id: str,
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
