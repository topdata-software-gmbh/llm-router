"""Tests for API key management (CLI and verification)."""

from sqlmodel import Session

from llm_router.core.api_key import (
    create_api_key,
    delete_api_key,
    generate_api_key,
    list_api_keys,
    revoke_api_key,
    verify_api_key,
)
from llm_router.models import ApiKey


def test_generate_api_key_format():
    """Generated key should have sk-llmr- prefix."""
    key = generate_api_key()
    assert key.startswith("sk-llmr-")
    assert len(key) == 48


def test_generate_api_key_unique():
    """Each generated key should be unique."""
    keys = {generate_api_key() for _ in range(100)}
    assert len(keys) == 100


def test_create_and_verify_api_key(session: Session):
    """Creating a key should allow verification."""
    api_key = create_api_key(session, name="test-key")

    assert api_key.key.startswith("sk-llmr-")
    assert api_key.name == "test-key"
    assert api_key.active is True

    # Verify the key against its plaintext value
    assert verify_api_key(session, api_key.key) is True


def test_verify_invalid_key(session: Session):
    """Invalid key should fail verification."""
    assert verify_api_key(session, "sk-llmr-invalid") is False


def test_verify_revoked_key(session: Session):
    """Revoked key should fail verification."""
    api_key = create_api_key(session)
    revoke_api_key(session, api_key.id)

    assert verify_api_key(session, api_key.key) is False


def test_list_api_keys_shows_plaintext(session: Session):
    """list_api_keys should expose full plaintext key values."""
    key1 = create_api_key(session, name="key-1")
    key2 = create_api_key(session, name="key-2")

    keys = list_api_keys(session)
    assert len(keys) == 2
    # Full plaintext keys are retrievable via list
    assert keys[0].key == key1.key
    assert keys[1].key == key2.key


def test_revoke_api_key(session: Session):
    """Revoking a key should set it inactive."""
    api_key = create_api_key(session)

    success = revoke_api_key(session, api_key.id)
    assert success is True

    # Refresh and check
    session.refresh(api_key)
    assert api_key.active is False


def test_delete_api_key(session: Session):
    """Deleting a key should remove it from the database."""
    api_key = create_api_key(session)
    key_id = api_key.id

    success = delete_api_key(session, key_id)
    assert success is True

    # Verify deleted
    assert session.get(ApiKey, key_id) is None


def test_revoke_nonexistent_key(session: Session):
    """Revoking a nonexistent key should return False."""
    success = revoke_api_key(session, 99999)
    assert success is False


def test_protected_endpoint_requires_key_when_keys_exist(client, session):
    """Once a key exists, protected endpoints require X-API-Key.

    With no keys, auth is a no-op (dev mode). After creating one key,
    the same request must be rejected without the header and accepted
    with the correct key. /healthz stays keyless either way.
    """
    # Fresh client (no keys) - dev mode: endpoint reachable without header.
    assert client.get("/api/providers").status_code == 200

    api_key = create_api_key(session, name="probe")

    # No header -> 401
    r = client.get("/api/providers")
    assert r.status_code == 401

    # Wrong key -> 401
    r = client.get("/api/providers", headers={"X-API-Key": "sk-llmr-wrong"})
    assert r.status_code == 401

    # Correct key -> 200
    r = client.get("/api/providers", headers={"X-API-Key": api_key.key})
    assert r.status_code == 200

    # Health stays keyless
    assert client.get("/healthz").status_code == 200
