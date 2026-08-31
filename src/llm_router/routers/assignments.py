"""Assignment (purpose) endpoints.

An assignment maps a purpose key (``project:job``) to an ordered chain of
``provider/model`` strings. The chain's primary entry is first; the rest are
fallbacks the client walks. The same concept appears in the API as "purpose"
(the resolve key) and the entity is the ``assignment`` table.
"""

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import DependsSession
from ..models import Assignment

router = APIRouter(prefix="/api/assignments", tags=["assignments"])
SessionDep = Depends(DependsSession())


class AssignmentIn(BaseModel):
    key: str
    owner: str
    description: Optional[str] = None
    chain: List[str]


class AssignmentOut(AssignmentIn):
    id: int


def _to_out(assignment: Assignment) -> AssignmentOut:
    """Map a DB row (chain stored as JSON text) to the API schema (list)."""
    try:
        chain = json.loads(assignment.chain)
    except json.JSONDecodeError:
        chain = []
    return AssignmentOut(
        id=assignment.id,
        key=assignment.key,
        owner=assignment.owner,
        description=assignment.description,
        chain=chain,
    )


@router.put("/{purpose}", response_model=AssignmentOut)
def upsert(purpose: str, body: AssignmentIn, session: Session = SessionDep):
    if body.key != purpose:
        raise HTTPException(400, "path purpose must equal body.key")
    existing = session.exec(select(Assignment).where(Assignment.key == purpose)).first()
    if existing is None:
        existing = Assignment(key=purpose)
        session.add(existing)
    existing.owner = body.owner
    existing.description = body.description
    existing.chain = json.dumps(body.chain)
    session.commit()
    session.refresh(existing)
    return _to_out(existing)


@router.get("/{purpose}", response_model=AssignmentOut | None)
def get(purpose: str, session: Session = SessionDep):
    existing = session.exec(select(Assignment).where(Assignment.key == purpose)).first()
    if existing is None:
        return None
    return _to_out(existing)


@router.get("", response_model=List[AssignmentOut])
def list_all(session: Session = SessionDep):
    rows = session.exec(
        select(Assignment).order_by(Assignment.owner, Assignment.key)
    ).all()
    return [_to_out(a) for a in rows]
