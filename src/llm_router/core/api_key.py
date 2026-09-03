"""API key management.

Keys are stored plaintext in the database (validation requires matching the
full key). ``llm-router key list`` displays the full key values for all
registered keys. This module provides functions for creating, verifying,
listing, revoking, and deleting API keys. Keys are managed exclusively via
the local CLI (no API endpoint).
"""

import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from ..models import ApiKey

KEY_PREFIX = "sk-llmr-"
KEY_LENGTH = 48  # Total length including prefix


def _generate_random_string(length: int) -> str:
    """Generate a cryptographically secure random string."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_api_key() -> str:
    """Generate a new API key in the format ``sk-llmr-<random>``.

    Returns:
        The API key string, e.g. ``sk-llmr-x9K2fAbc...``.
    """
    random_part = _generate_random_string(KEY_LENGTH - len(KEY_PREFIX))
    return f"{KEY_PREFIX}{random_part}"


def create_api_key(session: Session, name: Optional[str] = None) -> ApiKey:
    """Create a new API key and store it plaintext in the database.

    Args:
        session: Database session.
        name: Optional label for the key (e.g., "digester-prod").

    Returns:
        The persisted ApiKey model (with its full plaintext ``key`` value).
    """
    api_key = ApiKey(
        key=generate_api_key(),
        name=name,
        active=True,
    )
    session.add(api_key)
    session.commit()
    session.refresh(api_key)
    return api_key


def verify_api_key(session: Session, presented_key: str) -> bool:
    """Verify a presented API key against stored plaintext keys.

    Args:
        session: Database session.
        presented_key: The raw API key from the ``X-API-Key`` header.

    Returns:
        True if the key exists and is active, False otherwise.
    """
    statement = select(ApiKey).where(
        ApiKey.key == presented_key,
        ApiKey.active == True,  # noqa: E712
    )
    api_key = session.exec(statement).first()

    if api_key is None:
        return False

    # Update last_used_at
    api_key.last_used_at = datetime.now(timezone.utc)
    session.add(api_key)
    session.commit()

    return True


def list_api_keys(session: Session) -> list[ApiKey]:
    """List all registered API keys (with their full plaintext values).

    Args:
        session: Database session.

    Returns:
        List of ApiKey models, oldest first.
    """
    keys = session.exec(select(ApiKey).order_by(ApiKey.created_at)).all()
    return list(keys)


def revoke_api_key(session: Session, key_id: int) -> bool:
    """Revoke an API key by setting it inactive.

    Args:
        session: Database session.
        key_id: The ID of the key to revoke.

    Returns:
        True if the key was found and revoked, False otherwise.
    """
    api_key = session.get(ApiKey, key_id)
    if api_key is None:
        return False

    api_key.active = False
    session.add(api_key)
    session.commit()
    return True


def delete_api_key(session: Session, key_id: int) -> bool:
    """Permanently delete an API key from the database.

    Args:
        session: Database session.
        key_id: The ID of the key to delete.

    Returns:
        True if the key was found and deleted, False otherwise.
    """
    api_key = session.get(ApiKey, key_id)
    if api_key is None:
        return False

    session.delete(api_key)
    session.commit()
    return True
