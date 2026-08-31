"""MCP server exposing llm-router resolution to agents.

Launch: ``llm-router-mcp`` (FastMCP stdio server). Tools:

- ``resolve_purpose``: expand a purpose to its ordered connection chain.
- ``list_assignments``: list assignment rows, optionally by owner.
- ``get_catalog``: the full detected/hand-added provider + model catalog.
"""

from typing import Optional

from mcp.server.fastmcp import FastMCP
from sqlmodel import Session, select

from ..core.resolve import ResolveError
from ..core.resolve import resolve_purpose as _resolve_purpose
from ..db import engine
from ..models import Assignment, Model, Provider

mcp = FastMCP("llm-router")


@mcp.tool()
def resolve_purpose(purpose: str) -> list[dict]:
    """Resolve a purpose ('project:job', e.g. 'git-digest:digest') to its ordered
    chain of {provider, model, base_url, api_key} entries, primary first.

    Raises ValueError if the purpose has no assignment or the chain is malformed.
    """
    with Session(engine) as session:
        try:
            chain = _resolve_purpose(session, purpose)
        except ResolveError as exc:
            raise ValueError(str(exc)) from exc
        if chain is None:
            raise ValueError(f"no assignment for purpose {purpose!r}")
        return chain


@mcp.tool()
def list_assignments(owner: Optional[str] = None) -> list[dict]:
    """List assignments, optionally filtered by owner namespace.

    Returns one dict per assignment: {key, owner, chain, active, description}.
    """
    with Session(engine) as session:
        q = select(Assignment)
        if owner:
            q = q.where(Assignment.owner == owner)
        return [
            {
                "key": a.key,
                "owner": a.owner,
                "chain": a.chain,
                "active": a.active,
                "description": a.description,
            }
            for a in session.exec(q.order_by(Assignment.owner, Assignment.key)).all()
        ]


@mcp.tool()
def get_catalog() -> dict:
    """Return the full provider + model catalog (detected and hand-added)."""
    with Session(engine) as session:
        providers = [p.model_dump() for p in session.exec(select(Provider)).all()]
        models = [m.model_dump() for m in session.exec(select(Model)).all()]
    return {"providers": providers, "models": models}
