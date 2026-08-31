"""FastAPI application factory and lifespan for the llm-router service.

Boot sequence wires the routers and initializes the database. The app is
exposed as a module-level ``app`` for uvicorn and a ``create_app()`` factory
for tests.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import init_db
from .routers import assignments, models, providers, resolve, scan


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="llm-router", version="0.1.0", lifespan=lifespan)
    app.include_router(providers.router)
    app.include_router(models.router)
    app.include_router(assignments.router)
    app.include_router(resolve.router)
    app.include_router(scan.router)
    return app


app = create_app()
