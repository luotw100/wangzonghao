from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx


class BaseAdapter(ABC):
    """Abstract base for message platform adapters (Chat, WeChat, Feishu, etc.)."""

    @abstractmethod
    async def list_conversations(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    async def get_conversation(self, conversation_id: str, include_deleted: bool = False) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def get_messages(
        self, conversation_id: str, last_id: int = 0, timeout: int = 0
    ) -> Dict[str, Any]:
        """Get messages. timeout=0 returns immediately, timeout>0 long-polls."""
        ...

    @abstractmethod
    async def send_message(self, conversation_id: str, sender_id: str, content: str) -> None:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


class ChatAdapter(BaseAdapter):
    """Adapter for our built-in Chat service."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        await self.http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ):
        response = await self.http.request(method, f"{self.base_url}{path}", params=params, json=json_body)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    async def list_conversations(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        return await self._request("GET", "/conversations", params={"include_deleted": include_deleted})

    async def get_conversation(self, conversation_id: str, include_deleted: bool = False) -> Dict[str, Any]:
        return await self._request("GET", f"/conversations/{conversation_id}", params={"include_deleted": include_deleted})

    async def get_messages(
        self, conversation_id: str, last_id: int = 0, timeout: int = 0
    ) -> Dict[str, Any]:
        return await self._request(
            "GET",
            f"/conversations/{conversation_id}/messages",
            params={"last_id": last_id, "timeout": timeout},
        )

    async def send_message(self, conversation_id: str, sender_id: str, content: str) -> None:
        await self._request(
            "POST",
            f"/conversations/{conversation_id}/messages",
            json_body={
                "sender_id": sender_id,
                "msg_type": "text",
                "content": content,
            },
        )


class ProviderClient:
    def __init__(self, request_timeout: float):
        self.http = httpx.AsyncClient(timeout=request_timeout)

    async def close(self):
        await self.http.aclose()

    async def complete_chat(
        self,
        base_url: str,
        api_key: str,
        model: str,
        messages: List[Dict[str, str]],
    ) -> tuple[str, Dict[str, int]]:
        response = await self.http.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.7,
            },
        )
        if not response.is_success:
            raise ValueError(f"LLM API error {response.status_code}: {response.text[:2000]}")
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage") or {}
        return content, {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }