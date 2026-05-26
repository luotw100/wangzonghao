"""Laborster Studio API — single FastAPI app serving both the Studio
control plane and the embedded chat sandbox.

Chat lives under ``/api/chat/*``. Studio's own routes keep their flat
``/api/*`` shape. Auth is shared: a single bearer token issued by
``POST /api/auth/login`` authenticates both planes against
``auth.auth_sessions``.

Boundary: ``chat`` and ``studio`` packages must not import each other's
business code. The only allowed shared seam is ``studio.db`` (engine /
pool / Base infra), ``studio.deps`` / ``studio.models.Account`` (auth)
and ``studio.notify`` (LISTEN/NOTIFY broker).
"""

from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI

from studio.notify import init_broker, shutdown_broker

# Threadpool sized for chat's long-poll fan-out (up to a few hundred
# clients each holding a sync DB session while waiting on the broker).
LONG_POLL_THREADPOOL_TOKENS = 500


@asynccontextmanager
async def lifespan(app: FastAPI):
    anyio.to_thread.current_default_thread_limiter().total_tokens = LONG_POLL_THREADPOOL_TOKENS
    await init_broker()
    try:
        yield
    finally:
        await shutdown_broker()


app = FastAPI(
    title="Laborster Studio API",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

from studio.routers import (  # noqa: E402
    auth,
    bridge_protocol,
    bridges,
    conversations,
    distill,
    inboxes,
    personas,
)

app.include_router(auth.router)
app.include_router(personas.router)
app.include_router(bridges.router)
app.include_router(inboxes.router)
app.include_router(conversations.router)
app.include_router(distill.router)
app.include_router(bridge_protocol.router)

# --- Chat sandbox: mounted under /api/chat. Routers themselves carry
#     only their relative prefixes (e.g. /contacts, /conversations).
from chat.routers import (  # noqa: E402
    contacts as chat_contacts,
    conversations as chat_conversations,
    media as chat_media,
    messages as chat_messages,
    uploads as chat_uploads,
)

for _r in (chat_contacts, chat_conversations, chat_messages, chat_media, chat_uploads):
    app.include_router(_r.router, prefix="/api/chat")
