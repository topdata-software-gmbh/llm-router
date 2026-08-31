"""PydanticAI integration: build models from llm-router assignments.

``router_model(purpose)`` returns a ready-to-use ``OpenAIChatModel`` from the
first (primary) entry of the assignment chain. ``router_model_chain(purpose)``
returns the full ordered list for use with the fallback engine.
"""

import os
from typing import List, Optional

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .client import ModelConfig, resolve_chain


def _build(model: ModelConfig) -> OpenAIChatModel:
    """Build an OpenAIChatModel from a resolved ModelConfig."""
    provider = OpenAIProvider(
        base_url=model.base_url,
        api_key=model.api_key or os.environ.get("OPENAI_API_KEY"),
    )
    return OpenAIChatModel(model_name=model.model, provider=provider)


def router_model(purpose: str, *, base_url: Optional[str] = None) -> OpenAIChatModel:
    """Primary model for a purpose (picks chain[0])."""
    return _build(resolve_chain(purpose, base_url=base_url)[0])


def router_model_chain(
    purpose: str, *, base_url: Optional[str] = None
) -> List[OpenAIChatModel]:
    """Ordered pre-built models for the fallback engine (primary first)."""
    return [_build(c) for c in resolve_chain(purpose, base_url=base_url)]


def resolve_raw(purpose: str, *, base_url: Optional[str] = None) -> List[ModelConfig]:
    """Low-level escape hatch for non-PydanticAI consumers needing raw credentials."""
    return resolve_chain(purpose, base_url=base_url)
