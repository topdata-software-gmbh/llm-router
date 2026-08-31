"""Scan endpoint: re-run detection and persist new providers/models.

Scanning populates the pickable catalog. It never touches assignments.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from ..core.detect import scan as detect_scan
from ..db import DependsSession
from ..models import Model, Provider

router = APIRouter(prefix="/api", tags=["scan"])
SessionDep = Depends(DependsSession())


class ScanOut(BaseModel):
    providers_detected: int
    providers_added: int
    models_detected: int


@router.post("/scan", response_model=ScanOut)
def run_scan(session: Session = SessionDep):
    result = detect_scan()
    existing_prefixes = {p.prefix for p in session.exec(select(Provider)).all()}
    added = 0
    for prov in result.providers:
        if prov.prefix in existing_prefixes:
            continue
        session.add(
            Provider(
                name=prov.name,
                prefix=prov.prefix,
                base_url=prov.base_url,
                api_key=prov.api_key,
            )
        )
        existing_prefixes.add(prov.prefix)
        added += 1
    # Persist detected Ollama models against the existing ollama provider (if any).
    ollama_provider = session.exec(
        select(Provider).where(Provider.prefix == "ollama")
    ).first()
    registered = 0
    if ollama_provider is not None:
        known = {
            m.model
            for m in session.exec(
                select(Model).where(Model.provider_id == ollama_provider.id)
            ).all()
        }
        for dm in result.models:
            if dm.model in known:
                continue
            session.add(Model(provider_id=ollama_provider.id, model=dm.model))
            known.add(dm.model)
            registered += 1
    session.commit()
    return ScanOut(
        providers_detected=len(result.providers),
        providers_added=added,
        models_detected=registered,
    )
