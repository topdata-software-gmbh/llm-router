"""SQLModel ORM models for the llm-router.

Three tables:

- ``Provider``: an LLM endpoint (cloud or local) with its own base URL and
  (for cloud) API key. The ``prefix`` is the short key used in chain entries
  as ``prefix/model``.
- ``Model``: a model id belonging to a provider. This is the *detected
  catalog* — populated by ``scan`` and manual adds; it is what a management UI
  can pick from.
- ``Assignment``: maps a purpose key (``project:job``, e.g. ``git-digest:digest``)
  to an ordered chain of ``provider/model`` strings, stored as JSON text.

``Assignment.chain`` is intentionally **not** FK-constrained to ``Model``: an
assignment may reference a model that is not (yet) in the detected catalog.
The provider is looked up by prefix during resolution.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Provider(SQLModel, table=True):
    __tablename__ = "provider"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    prefix: str = Field(index=True, unique=True)
    base_url: str
    api_key: Optional[str] = None
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Model(SQLModel, table=True):
    __tablename__ = "model"

    id: Optional[int] = Field(default=None, primary_key=True)
    provider_id: int = Field(foreign_key="provider.id", index=True)
    model: str = Field(index=True)
    display_name: Optional[str] = None
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Assignment(SQLModel, table=True):
    __tablename__ = "assignment"

    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)
    owner: str = Field(index=True)
    description: Optional[str] = None
    chain: str = Field(default="[]")
    active: bool = True
    updated_at: datetime = Field(default_factory=utcnow)
