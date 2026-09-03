"""FastAPI application factory and lifespan for the llm-router service.

Boot sequence wires the routers and initializes the database. The app is
exposed as a module-level ``app`` for uvicorn and a ``create_app()`` factory
for tests.

Auth: the ``/healthz`` endpoint stays keyless for liveness probes; every
other router is gated behind the ``verify_api_key`` dependency. When no API
keys exist in the database, verification is a no-op (zero-config dev mode).
"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI

from .auth import verify_api_key
from .db import init_db
from .routers import assignments, health, models, providers, resolve, scan


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="llm-router", version="0.2.0", lifespan=lifespan)
    # Health check endpoint - always keyless (used by `tt health` probes).
    app.include_router(health.router)
    # Authenticated endpoints.
    api = APIRouter(dependencies=[Depends(verify_api_key)])
    api.include_router(providers.router)
    api.include_router(models.router)
    api.include_router(assignments.router)
    api.include_router(resolve.router)
    api.include_router(scan.router)
    app.include_router(api)
    return app


app = create_app()
