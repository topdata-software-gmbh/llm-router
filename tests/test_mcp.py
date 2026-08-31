"""Tests for the MCP server tools."""

import json

import pytest
from sqlmodel import Session

from llm_router.models import Assignment, Provider


@pytest.mark.asyncio
async def test_mcp_tools_registered():
    from llm_router.mcp.server import mcp

    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert {"resolve_purpose", "list_assignments", "get_catalog"} <= names


@pytest.mark.asyncio
async def test_mcp_resolve_purpose(isolated_db):
    with Session(isolated_db) as session:
        session.add(
            Provider(
                prefix="openai", name="openai",
                base_url="https://api.openai.com/v1", api_key="sk",
            )
        )
        session.add(
            Assignment(
                key="demo:job",
                owner="demo",
                chain=json.dumps(["openai/gpt-4o-mini"]),
            )
        )
        session.commit()

    from llm_router.mcp import server as mcp_mod

    result = mcp_mod.resolve_purpose("demo:job")
    assert result[0]["provider"] == "openai"
    assert result[0]["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_mcp_resolve_unknown_raises():
    from llm_router.mcp import server as mcp_mod

    with pytest.raises(ValueError):
        mcp_mod.resolve_purpose("does:not-exist")
