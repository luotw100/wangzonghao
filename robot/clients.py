from typing import Any, Dict, List, Optional

import httpx


class ChatAPIClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(timeout=30.0)

    async def close(self):
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

    async def create_conversation(self, title: Optional[str]) -> Dict[str, Any]:
        return await self._request("POST", "/conversations", json_body={"title": title})

    async def list_conversations(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        return await self._request("GET", "/conversations", params={"include_deleted": include_deleted})

    async def get_conversation(self, conversation_id: str, include_deleted: bool = False) -> Dict[str, Any]:
        return await self._request("GET", f"/conversations/{conversation_id}", params={"include_deleted": include_deleted})

    async def update_conversation(self, conversation_id: str, title: Optional[str]) -> Dict[str, Any]:
        return await self._request("PUT", f"/conversations/{conversation_id}", json_body={"title": title})

    async def delete_conversation(self, conversation_id: str) -> Dict[str, Any]:
        return await self._request("DELETE", f"/conversations/{conversation_id}")

    async def restore_conversation(self, conversation_id: str) -> Dict[str, Any]:
        return await self._request("POST", f"/conversations/{conversation_id}/restore")

    async def send_message(self, conversation_id: str, content: str):
        await self._request(
            "POST",
            f"/conversations/{conversation_id}/messages",
            json_body={
                "role": "robot",
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
        """Returns (content, usage) where usage = {prompt_tokens, completion_tokens, total_tokens}."""
        response = await self.http.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.7,
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage") or {}
        return content, {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }