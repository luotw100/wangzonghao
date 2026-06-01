"""OpenAI-compatible LLM simulator for load tests (and the e2e suite).

Runs as the `fake-llm` compose service (hostname `fake-llm`, port 8080),
built from the api image so it has fastapi + uvicorn + httpx available.
Whitelisted in ``studio.clients.ALLOWED_BASE_URLS``.

Unlike a test stub that replies instantly, this models the *timing* of a
real provider so a load test sees realistic worker-side concurrency:

    total_latency = network_ms
                  + prompt_tokens   / prefill_tps     # 预填充：快、批量
                  + output_tokens   / decode_tps      # 解码：慢、逐 token

The worker is non-streaming (one POST, reads the whole body — see
``studio.clients.ProviderClient.complete_chat``), so we just sleep the
composed total and return once. ``prompt_tokens`` is estimated from the
incoming ``messages`` (history grows → prefill grows, naturally), and the
reply length drives ``output_tokens`` (so longer replies cost more decode
time *and* more downstream typing-cadence / outbound load).

Reply shape mimics human chat: mostly one short bubble, occasionally a few,
lengths right-skewed (short common, long rare) via a clamped log-normal.
Content is filler — only its length matters to the system under test. The
response is the ``{"messages": [...]}`` JSON that ReplyBrain._parse_chunks
expects, wrapped in an OpenAI chat.completion envelope with realistic usage.

All knobs are env vars with per-request header overrides (so a load script
can dial different conversations differently):

    FAKE_NET_MS=200          base network latency (ms)
    FAKE_PREFILL_TPS=3000    prefill throughput (prompt tokens / sec)
    FAKE_DECODE_TPS=50       decode throughput (output tokens / sec)
    FAKE_CHARS_PER_TOKEN=4   char→token estimate divisor
    FAKE_LEN_MIN=3           per-chunk min chars
    FAKE_LEN_MAX=100         per-chunk max chars
    FAKE_LEN_MEDIAN=12       per-chunk median chars (log-normal)
    FAKE_LEN_SIGMA=0.6       log-normal shape (bigger → longer tail)
    FAKE_CHUNK_WEIGHTS=0.7,0.2,0.1   P(1 chunk), P(2), P(3), …
    FAKE_PORT=8080

    headers: X-Fake-Net-Ms / X-Fake-Prefill-Tps / X-Fake-Decode-Tps
             override the corresponding env default for that one request.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import string

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse


# --------------------------------------------------------------------------
# config (env defaults; some overridable per-request via headers)
# --------------------------------------------------------------------------

def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


NET_MS = _f("FAKE_NET_MS", 200.0)
PREFILL_TPS = max(1.0, _f("FAKE_PREFILL_TPS", 3000.0))
DECODE_TPS = max(1.0, _f("FAKE_DECODE_TPS", 50.0))
CHARS_PER_TOKEN = max(1.0, _f("FAKE_CHARS_PER_TOKEN", 4.0))
LEN_MIN = int(_f("FAKE_LEN_MIN", 3))
LEN_MAX = int(_f("FAKE_LEN_MAX", 100))
LEN_MEDIAN = max(1.0, _f("FAKE_LEN_MEDIAN", 12.0))
LEN_SIGMA = max(0.01, _f("FAKE_LEN_SIGMA", 0.6))
PORT = int(_f("FAKE_PORT", 8080))


def _chunk_weights() -> list[float]:
    raw = os.environ.get("FAKE_CHUNK_WEIGHTS", "0.7,0.2,0.1")
    try:
        ws = [float(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        ws = [0.7, 0.2, 0.1]
    return ws or [1.0]


CHUNK_WEIGHTS = _chunk_weights()
# log-normal mu such that exp(mu) == median.
_LEN_MU = math.log(LEN_MEDIAN)

# Filler vocabulary: a few short Chinese words so generated text reads like
# chat and "字" counts are meaningful. Content is irrelevant to the SUT.
_WORDS = (
    "你好 在的 收到 好的 没问题 稍等 我看看 明白 对的 嗯嗯 可以 谢谢 "
    "今天 天气 不错 我们 一起 下午 开会 方案 已经 发你 麻烦 确认 一下 "
    "这个 问题 处理 完成 大概 需要 时间 辛苦 了 加油 晚点 联系 回头 再说"
).split()


# --------------------------------------------------------------------------
# reply synthesis
# --------------------------------------------------------------------------

def _est_tokens(text: str) -> int:
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def _prompt_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += len(c)
    return max(1, round(total / CHARS_PER_TOKEN))


def _sample_len() -> int:
    """Per-chunk char length: clamped right-skewed log-normal (short common)."""
    n = round(random.lognormvariate(_LEN_MU, LEN_SIGMA))
    return max(LEN_MIN, min(LEN_MAX, n))


def _make_chunk(target: int) -> str:
    """A readable-ish filler string of exactly `target` Chinese chars."""
    out: list[str] = []
    length = 0
    while length < target:
        w = random.choice(_WORDS)
        out.append(w)
        length += len(w)
    s = "".join(out)[:target]
    # Never return something that strips to empty (ReplyBrain drops those).
    return s if s.strip() else random.choice(string.ascii_lowercase) * target


def _make_reply() -> tuple[list[str], int]:
    """Return (chunks, output_tokens). Chunk count is right-skewed to 1."""
    k = random.choices(range(1, len(CHUNK_WEIGHTS) + 1), weights=CHUNK_WEIGHTS, k=1)[0]
    chunks = [_make_chunk(_sample_len()) for _ in range(k)]
    out_tokens = _est_tokens("".join(chunks))
    return chunks, out_tokens


# --------------------------------------------------------------------------
# app
# --------------------------------------------------------------------------

app = FastAPI()


def _hdr_float(request: Request, name: str, default: float) -> float:
    v = request.headers.get(name)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        return default


@app.get("/health")
async def health() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    try:
        req = await request.json()
    except Exception:
        return JSONResponse({"error": {"message": "invalid json"}}, status_code=400)

    messages = req.get("messages") or []
    model = req.get("model") or "fake-model"

    prompt_tokens = _prompt_tokens(messages)
    chunks, output_tokens = _make_reply()

    net_ms = _hdr_float(request, "x-fake-net-ms", NET_MS)
    prefill_tps = max(1.0, _hdr_float(request, "x-fake-prefill-tps", PREFILL_TPS))
    decode_tps = max(1.0, _hdr_float(request, "x-fake-decode-tps", DECODE_TPS))

    total_s = net_ms / 1000.0 + prompt_tokens / prefill_tps + output_tokens / decode_tps
    await asyncio.sleep(total_s)

    # ReplyBrain._parse_chunks wants {"messages": [<non-empty str>, ...]}.
    content = json.dumps({"messages": chunks}, ensure_ascii=False)
    payload = {
        "id": "fake-cmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content},
             "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": prompt_tokens + output_tokens,
        },
    }
    return JSONResponse(payload)


def main() -> None:
    import uvicorn
    print(
        f"fake-llm (async) on :{PORT}  net={NET_MS:.0f}ms "
        f"prefill={PREFILL_TPS:.0f}tps decode={DECODE_TPS:.0f}tps "
        f"len~lognorm(median={LEN_MEDIAN:.0f},σ={LEN_SIGMA},[{LEN_MIN},{LEN_MAX}]) "
        f"chunks~{CHUNK_WEIGHTS}",
        flush=True,
    )
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
