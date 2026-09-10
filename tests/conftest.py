"""Shared pytest fixtures.

Tests use an isolated in-memory SQLite DB via a temporary DATABASE_PATH that
is reset before each test so no state leaks between cases.

IAM-auth tests mint a real Ed25519 keypair, serve a matching JWKS and
parameterized ``/auth/grants`` decisions via respx, so routes exercise the
actual ``iam_client`` verify/grants path without a live IAM.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

TEST_DB = Path(__file__).parent / "test_llm_router.db"

IAM_TEST_BASE = "http://iam-test"
KID = "test-ed25519-1"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _make_jwk(private_key: Ed25519PrivateKey) -> dict[str, str]:
    raw = private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "x": _b64u(raw),
        "kid": KID,
        "alg": "EdDSA",
        "use": "sig",
    }


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """Point the app at a throwaway SQLite file and create tables fresh."""
    if TEST_DB.exists():
        TEST_DB.unlink()
    monkeypatch.setenv("LLM_ROUTER_DB", str(TEST_DB))
    # Force re-import of the config (it reads DATABASE_PATH from env at import)
    # and the db module against the new path, then reload any module holding a
    # reference to the old engine (the MCP server).
    import importlib

    import llm_router.config as config_mod
    import llm_router.db as db_mod

    importlib.reload(config_mod)
    importlib.reload(db_mod)
    from llm_router import db as fresh_db

    fresh_db.init_db()
    import llm_router.mcp.server as mcp_mod

    importlib.reload(mcp_mod)
    yield fresh_db.engine
    if TEST_DB.exists():
        TEST_DB.unlink()


@pytest.fixture(autouse=True)
def _reset_iam_client():
    """Reset the cached IamClient so each test binds a fresh one to its env."""
    from llm_router import iam_deps

    iam_deps._client = None
    yield
    iam_deps._client = None


@pytest.fixture()
def iam_env(monkeypatch):
    """Wire llm-router env to a mocked IAM; mint tokens; mock IAM endpoints.

    Yields helpers:
      - ``token(sub, typ)``: mint a signed Bearer JWT for ``sub``.
      - ``setup(grants_fn)``: configure the IAM grants mock.
    Defaults to no grants.
    """
    from llm_router import iam_deps

    private_key = Ed25519PrivateKey.generate()
    jwk = _make_jwk(private_key)

    monkeypatch.setenv("LLM_ROUTER_IAM_BASE_URL", IAM_TEST_BASE)
    monkeypatch.setenv("LLM_ROUTER_IAM_API_KEY", "sk-tdiam-llm-router-test")
    # iam_deps reads these constants at import time, so patch the module
    # globals (a fresh client is rebuilt per test via `_reset_iam_client`).
    monkeypatch.setattr(iam_deps, "LLM_ROUTER_IAM_BASE_URL", IAM_TEST_BASE)
    monkeypatch.setattr(
        iam_deps, "LLM_ROUTER_IAM_API_KEY", "sk-tdiam-llm-router-test"
    )
    monkeypatch.setattr(iam_deps, "LLM_ROUTER_IAM_DECISION_TTL", 15.0)

    def _token(
        sub: str | int = "1",
        typ: str = "agent",
        *,
        extra: dict[str, Any] | None = None,
    ) -> str:
        claims: dict[str, Any] = {
            "sub": str(sub),
            "typ": typ,
            "iat": int(time.time()),
            "exp": int(time.time()) + 900,
        }
        if extra:
            claims.update(extra)
        return jwt.encode(
            claims, private_key, algorithm="EdDSA", headers={"kid": KID}
        )

    def _grants(request) -> httpx.Response:
        params = dict(request.url.params)
        grants = _grants_fn(params)
        action = params.get("action")
        if action:
            grants = [g for g in grants if g.get("action") == action]
        return httpx.Response(200, json={"grants": grants})

    def _no_grants(params: dict) -> list:
        return []

    _grants_fn = _no_grants

    with respx.mock(base_url=IAM_TEST_BASE, assert_all_called=False) as router:
        router.get("/.well-known/jwks.json").respond(
            200, json={"keys": [jwk]}
        )
        router.get("/auth/grants").mock(side_effect=_grants)
        router.get("/auth/check").respond(
            200, json={"allowed": False}
        )

        def setup(grants_fn=None):
            nonlocal _grants_fn
            if grants_fn is not None:
                _grants_fn = grants_fn

        yield {
            "token": _token,
            "setup": setup,
            "base_url": IAM_TEST_BASE,
            "private_key": private_key,
        }
        iam_deps._client = None


@pytest.fixture
def client(isolated_db):
    """FastAPI TestClient with the isolated DB."""
    from fastapi.testclient import TestClient

    from llm_router.main import create_app

    app = create_app()
    return TestClient(app)


@pytest.fixture
def session(isolated_db):
    """SQLModel session bound to the isolated test DB."""
    from sqlmodel import Session

    with Session(isolated_db) as s:
        yield s


def _grant(resource_id: str, action: str, resource_type: str = "llm") -> dict:
    return {
        "principal": "1",
        "resource_type": resource_type,
        "resource_id": resource_id,
        "action": action,
    }


def grant_all(action: str, resource_type: str = "llm") -> dict:
    """Wildcard grant for ``action`` on the given resource type."""
    return _grant("*", action, resource_type)
