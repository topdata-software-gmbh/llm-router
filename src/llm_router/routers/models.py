"""Model catalog endpoints.

Models are the *detected/hand-added* catalog; they are what a management UI or
CLI can offer when building an assignment chain. Resolution itself does not
require a model to be pre-registered here.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import DependsSession
from ..models import Model, Provider

router = APIRouter(prefix="/api/models", tags=["models"])
SessionDep = Depends(DependsSession())


class ModelIn(BaseModel):
    provider_prefix: str
    model: str
    display_name: Optional[str] = None
    active: bool = True


class ModelOut(ModelIn):
    id: int
    provider_id: int


@router.get("", response_model=List[ModelOut])
def list_models(session: Session = SessionDep):
    rows = session.exec(
        select(Model, Provider)
        .join(Provider, Model.provider_id == Provider.id)
        .order_by(Provider.name, Model.model)
    ).all()
    return [
        {
            "id": m.id,
            "provider_id": m.provider_id,
            "provider_prefix": p.prefix,
            "model": m.model,
            "display_name": m.display_name,
            "active": m.active,
        }
        for m, p in rows
    ]


@router.post("/upsert", response_model=ModelOut)
def upsert_model(body: ModelIn, session: Session = SessionDep):
    provider = session.exec(
        select(Provider).where(Provider.prefix == body.provider_prefix)
    ).first()
    if provider is None:
        raise HTTPException(404, f"unknown provider prefix {body.provider_prefix!r}")
    existing = session.exec(
        select(Model).where(Model.provider_id == provider.id, Model.model == body.model)
    ).first()
    if existing is None:
        existing = Model(provider_id=provider.id, model=body.model)
        session.add(existing)
    existing.display_name = body.display_name
    existing.active = body.active
    session.commit()
    session.refresh(existing)
    out = ModelOut(
        id=existing.id,
        provider_id=existing.provider_id,
        provider_prefix=provider.prefix,
        model=existing.model,
        display_name=existing.display_name,
        active=existing.active,
    )
    return out
