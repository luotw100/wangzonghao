from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from chat.config import LONG_POLL_THREADPOOL_TOKENS
from chat.limiter import limiter
from chat.routers import auth, contacts, conversations, health, media, messages, uploads


@asynccontextmanager
async def lifespan(app: FastAPI):
    anyio.to_thread.current_default_thread_limiter().total_tokens = LONG_POLL_THREADPOOL_TOKENS
    yield


app = FastAPI(
    title="Laborster Chat",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

for module in (health, auth, contacts, conversations, messages, uploads, media):
    app.include_router(module.router)
