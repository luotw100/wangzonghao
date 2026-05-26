"""Studio LLM 客户端。

ProviderClient 是对 OpenAI-compatible /chat/completions 接口的薄封装，
由 ReplyBrain 和 DistillPipeline 共享使用（各自持有独立实例）。
ALLOWED_BASE_URLS 是运营侧维护的白名单，防止 SSRF 攻击（新增 Provider 时需同步更新此列表）。
"""

from typing import Dict, List

import httpx

# Provider base_url 白名单：只允许向已知可信的 LLM API 发起请求，防止 SSRF。
# 新增支持的 Provider 时需在此处添加对应的 base_url。
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
    # 测试桩：仅在 docker 测试网络内可解析（hostname=fake-llm），prod 无影响
    "http://fake-llm:8080/v1",
}


class ProviderClient:
    """OpenAI-compatible LLM 调用客户端。

    封装 /chat/completions 请求，供 ReplyBrain（maybe_reply）和
    DistillPipeline（run_distill）调用。
    每个使用方持有独立实例（独立 httpx.AsyncClient），用完后调用 close()。
    """

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
        """向指定 Provider 发起一次 chat completion 请求。

        吃：base_url（必须在 ALLOWED_BASE_URLS 白名单内）+ api_key + model + messages
        吐：(response_text, usage_dict)
            response_text — choices[0].message.content
            usage_dict    — {prompt_tokens, completion_tokens, total_tokens}
        """
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
