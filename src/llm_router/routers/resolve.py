"""Resolution + catalog endpoints.

``GET /api/resolve/{purpose}`` is the primary contract consumed by clients: it
returns the ordered connection chain for a purpose. ``GET /api/catalog``
returns the full detected/hand-added provider + model catalog for management
UIs and inspection CLIs (e.g. `sb llm models` re-backed on this).
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..core.resolve import ResolveError, resolve_purpose
from ..db import DependsSession
from ..models import Model, Provider

router = APIRouter(prefix="/api", tags=["resolve"])
SessionDep = Depends(DependsSession())


class ResolveOut(BaseModel):
    purpose: str
    chain: List[dict]


class CatalogOut(BaseModel):
    providers: List[dict]
    models: List[dict]


@router.get("/resolve/{purpose}", response_model=ResolveOut)
def resolve(purpose: str, session: Session = SessionDep, response: Response = None):
    try:
        chain = resolve_purpose(session, purpose)
    except ResolveError as exc:
        raise HTTPException(422, str(exc)) from exc
    if chain is None:
        raise HTTPException(404, f"no assignment for purpose {purpose!r}")
    response.headers["cache-control"] = "no-store"
    return ResolveOut(purpose=purpose, chain=chain)


@router.get("/catalog", response_model=CatalogOut)
def catalog(session: Session = SessionDep):
    providers = session.exec(select(Provider).order_by(Provider.name)).all()
    models = session.exec(select(Model).order_by(Model.model)).all()
    return CatalogOut(
        providers=[p.model_dump() for p in providers],
        models=[m.model_dump() for m in models],
    )
