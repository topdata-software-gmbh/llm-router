"""Provider management endpoints.

The router owns provider credentials centrally. While credentials are
typically discovered by ``scan`` (which stores the API key from the
environment), manual add/update is the escape hatch.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import DependsSession
from ..models import Provider

router = APIRouter(prefix="/api/providers", tags=["providers"])
SessionDep = Depends(DependsSession())


class ProviderIn(BaseModel):
    name: str
    prefix: str
    base_url: str
    api_key: Optional[str] = None
    active: bool = True


class ProviderOut(ProviderIn):
    id: int


@router.get("", response_model=List[ProviderOut])
def list_providers(session: Session = SessionDep):
    return session.exec(select(Provider).order_by(Provider.name)).all()


@router.post("/upsert", response_model=ProviderOut)
def upsert_provider(body: ProviderIn, session: Session = SessionDep):
    existing = session.exec(
        select(Provider).where(Provider.prefix == body.prefix)
    ).first()
    if existing is None:
        existing = Provider(prefix=body.prefix)
        session.add(existing)
    existing.name = body.name
    existing.base_url = body.base_url
    existing.api_key = body.api_key
    existing.active = body.active
    session.commit()
    session.refresh(existing)
    return existing


@router.delete("/{prefix}")
def delete_provider(prefix: str, session: Session = SessionDep):
    obj = session.exec(select(Provider).where(Provider.prefix == prefix)).first()
    if obj is None:
        raise HTTPException(404, f"no provider with prefix {prefix!r}")
    session.delete(obj)
    session.commit()
    return {"ok": True, "prefix": prefix}
