"""Shared pytest fixtures.

Tests use an isolated in-memory SQLite DB via a temporary DATABASE_PATH that
is reset before each test so no state leaks between cases.
"""

from pathlib import Path

import pytest

TEST_DB = Path(__file__).parent / "test_llm_router.db"


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    """Point the app at a throwaway SQLite file and create tables fresh."""
    if TEST_DB.exists():
        TEST_DB.unlink()
    monkeypatch.setenv("LLM_ROUTER_DB", str(TEST_DB))
    # Force re-import of the db module against the new path, then reload any
    # module holding a reference to the old engine (the MCP server).
    import importlib

    import llm_router.db as db_mod

    importlib.reload(db_mod)
    from llm_router import db as fresh_db

    fresh_db.init_db()
    import llm_router.mcp.server as mcp_mod

    importlib.reload(mcp_mod)
    yield fresh_db.engine
    if TEST_DB.exists():
        TEST_DB.unlink()


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
