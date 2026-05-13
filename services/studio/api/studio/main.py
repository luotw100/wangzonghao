"""Laborster Studio API — thin app that mounts all routers."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from studio.migrate import run_migrations


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    yield


app = FastAPI(title="Laborster Studio API", lifespan=lifespan)

from studio.routers import (  # noqa: E402
    accounts,
    auth,
    bridge_protocol,
    bridges,
    contacts,
    distill,
    inboxes,
    personas,
    providers,
)

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(providers.router)
app.include_router(personas.router)
app.include_router(bridges.router)
app.include_router(inboxes.router)
app.include_router(contacts.router)
app.include_router(distill.router)
app.include_router(bridge_protocol.router)