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

# 长轮询路由已转 async + LISTEN/NOTIFY，threadpool 只承载短查询，保留 500 以防其它 sync 路由突增。
LONG_POLL_THREADPOOL_TOKENS = 500
