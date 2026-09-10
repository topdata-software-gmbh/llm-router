"""IAM-based auth dependency (Bearer JWT + IAM grants).

Verifies the caller's JWT and enforces coarse authorization for the
``llm`` resource type.  The old accept-any-key-when-empty-table pattern
is gone — auth is always enforced (fail-closed).
"""

# ruff: noqa: B008

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from iam_client.client import IamClient
from iam_client.errors import IamTokenError
from iam_client.fastapi import Caller

from .config import (
    LLM_ROUTER_IAM_API_KEY,
    LLM_ROUTER_IAM_BASE_URL,
    LLM_ROUTER_IAM_DECISION_TTL,
)

_client: IamClient | None = None


def get_iam_client() -> IamClient:
    """Return the shared IamClient singleton."""
    global _client
    if _client is None:
        _client = IamClient(
            base_url=LLM_ROUTER_IAM_BASE_URL,
            api_key=LLM_ROUTER_IAM_API_KEY,
            decision_ttl=LLM_ROUTER_IAM_DECISION_TTL,
        )
    return _client


def require_llm_scope(action: str):
    """Dependency factory for a Bearer-JWT caller authorized on ``llm``.

    Verifies the caller's JWT and enforces the coarse (any-grant) decision
    for ``action`` on resource type ``llm``.
    """

    async def _dependency(
        authorization: str | None = Header(default=None),
        client: IamClient = Depends(get_iam_client),
    ) -> Caller:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Missing or malformed Authorization header",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = authorization.removeprefix("Bearer ").strip()
        try:
            claims = client.verify_token(token)
        except IamTokenError as exc:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        principal = claims["sub"]
        if not client.grants(principal, "llm", action):
            raise HTTPException(status_code=403, detail="Forbidden")

        return Caller(
            principal=principal,
            principal_type=claims.get("typ", ""),
            claims=claims,
        )

    return _dependency
