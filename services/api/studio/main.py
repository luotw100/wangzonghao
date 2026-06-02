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

import os
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from studio.notify import init_broker, shutdown_broker

# Threadpool sized for chat's long-poll fan-out (up to a few hundred
# clients each holding a sync DB session while waiting on the broker).
LONG_POLL_THREADPOOL_TOKENS = 500

# The portal is a different origin than the API; its login + download fetches
# are cross-origin and need CORS. Required and explicit (no default): a
# comma-separated list of allowed portal origin(s).
PORTAL_ORIGINS = [
    o.strip() for o in os.environ.get("PORTAL_ORIGINS", "").split(",") if o.strip()
]
if not PORTAL_ORIGINS:
    raise RuntimeError(
        "PORTAL_ORIGINS is required (comma-separated allowed portal origin(s) for CORS)"
    )


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=PORTAL_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    # Bearer token in a header, not a cookie — no credentialed requests.
    allow_credentials=False,
)

from studio.routers import (  # noqa: E402
    auth,
    bridge_protocol,
    bridges,
    conversations,
    distill,
    download,
    inboxes,
    personas,
)

app.include_router(auth.router)
app.include_router(personas.router)
app.include_router(bridges.router)
app.include_router(inboxes.router)
app.include_router(conversations.router)
app.include_router(distill.router)
app.include_router(download.router)
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
