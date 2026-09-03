"""Authentication dependency verifying X-API-Key headers.

This module verifies API keys against the database of stored plaintext keys.
Keys are managed via the local CLI only (no API for key management).
"""

from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlmodel import Session

from .core.api_key import verify_api_key as _verify_api_key
from .db import DependsSession

SessionDep = Depends(DependsSession())


def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    session: Session = SessionDep,
) -> Optional[str]:
    """Verify that incoming request provides a valid X-API-Key.

    If no keys exist in the database, authentication is skipped
    to maintain zero-config local development backwards compatibility.

    Args:
        x_api_key: The X-API-Key header value.
        session: Database session (injected by FastAPI).

    Returns:
        The verified API key string.

    Raises:
        HTTPException: If the key is invalid or missing.
    """
    return _verify_key(x_api_key, session)


def _verify_key(x_api_key: Optional[str], session: Session) -> Optional[str]:
    """Internal verification logic."""
    from sqlmodel import select

    from .models import ApiKey

    # Check if any keys exist
    any_keys = session.exec(select(ApiKey).limit(1)).first()
    if any_keys is None:
        # No keys configured - dev mode, skip auth
        return x_api_key

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not _verify_api_key(session, x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return x_api_key
