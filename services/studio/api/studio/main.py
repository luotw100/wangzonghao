"""Laborster Studio API — thin app that mounts all routers."""

from contextlib import asynccontextmanager

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


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
    contacts,
    distill,
    inboxes,
    personas,
)

app.include_router(auth.router)
app.include_router(personas.router)
app.include_router(bridges.router)
app.include_router(inboxes.router)
app.include_router(contacts.router)
app.include_router(distill.router)
app.include_router(bridge_protocol.router)