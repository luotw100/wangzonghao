import os


def _read_upload_max_size_bytes() -> int:
    val = os.environ.get("UPLOAD_MAX_SIZE_MB")
    if not val:
        raise RuntimeError("UPLOAD_MAX_SIZE_MB environment variable is required")
    mb = int(val)
    if mb <= 0:
        raise RuntimeError("UPLOAD_MAX_SIZE_MB must be a positive integer")
    return mb * 1024 * 1024


UPLOAD_MAX_SIZE_BYTES = _read_upload_max_size_bytes()

# 浏览器可直接渲染为活动内容的 MIME 都拒掉，避免存储型 XSS。
DISALLOWED_UPLOAD_MIME_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
}

# 同步栈下每个长轮询占一个线程，FastAPI 默认 40 太小。
LONG_POLL_THREADPOOL_TOKENS = 500
LONG_POLL_INTERVAL_SECONDS = 0.5
