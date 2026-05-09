"""Laborster Studio API — thin app that mounts all routers."""

from fastapi import FastAPI

from studio.db import ensure_database
from studio.routers import (
    accounts,
    archives,
    auth,
    bridge_protocol,
    bridges,
    contacts,
    inboxes,
    personas,
    providers,
)

ensure_database()

app = FastAPI(title="Laborster Studio API")

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(providers.router)
app.include_router(personas.router)
app.include_router(bridges.router)
app.include_router(inboxes.router)
app.include_router(contacts.router)
app.include_router(archives.router)
app.include_router(bridge_protocol.router)
