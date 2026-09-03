"""Health check endpoint for liveness probes.

This endpoint does NOT require authentication and is used by
topdata-tools `tt health` for service availability checks.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    """Return service liveness status (no auth required)."""
    return {"status": "ok", "service": "llm-router"}
