from typing import Dict, List

import httpx

ALLOWED_BASE_URLS = {
    "https://api.deepseek.com",
}


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
        normalized = base_url.rstrip("/")
        if normalized not in ALLOWED_BASE_URLS:
            raise ValueError(f"Provider base_url {base_url!r} is not in the allowed list")
        response = await self.http.post(
            f"{normalized}/chat/completions",
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
