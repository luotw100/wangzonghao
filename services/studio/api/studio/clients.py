from typing import Dict, List

import httpx

ALLOWED_BASE_URLS = {
    # 国外
    "https://api.openai.com/v1",
    "https://generativelanguage.googleapis.com/v1beta/openai",
    "https://api.x.ai/v1",
    "https://api.mistral.ai/v1",
    "https://api.groq.com/openai/v1",
    "https://openrouter.ai/api/v1",
    "https://api.together.xyz/v1",
    # 国内
    "https://api.deepseek.com",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://open.bigmodel.cn/api/paas/v4",
    "https://api.moonshot.cn/v1",
    "https://api.lingyiwanwu.com/v1",
    "https://api.baichuan-ai.com/v1",
    "https://ark.cn-beijing.volces.com/api/v3",
    "https://api.stepfun.com/v1",
    "https://api.siliconflow.cn/v1",
    # 聚合
    "https://aixuny.com/v1",
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
