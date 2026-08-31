"""Resolution: expand an assignment's ordered chain into concrete specs.

An assignment stores a plain JSON array of ``provider/model`` strings, ordered
with the primary first and fallbacks after. Resolution turns each entry into a
connection spec ``{provider, model, base_url, api_key}`` by looking the provider
up by its ``prefix``. The model string is passed through verbatim — models are
not required to be pre-registered in the detected catalog.
"""

import json
from typing import Dict, List, Optional

from sqlmodel import Session, select

from ..models import Assignment, Provider


class ResolveError(Exception):
    """Raised when a chain or provider reference cannot be resolved."""


def resolve(chain: List[str], providers: Dict[str, Provider]) -> List[dict]:
    """Expand a chain of ``provider/model`` strings into connection specs.

    Args:
        chain: e.g. ``["openai/gpt-4o-mini", "anthropic/claude-3-haiku"]``.
        providers: prefix -> Provider mapping (only active providers).

    Returns:
        List of ``{provider, model, base_url, api_key}`` dicts in chain order.

    Raises:
        ResolveError: on a malformed entry or unknown provider prefix.
    """
    out: List[dict] = []
    for entry in chain:
        if "/" not in entry:
            raise ResolveError(
                f"invalid chain entry (expected 'provider/model'): {entry!r}"
            )
        prefix, model = entry.split("/", 1)
        provider = providers.get(prefix)
        if provider is None:
            raise ResolveError(f"unknown provider prefix in chain: {prefix!r}")
        out.append(
            {
                "provider": provider.name,
                "model": model,
                "base_url": provider.base_url,
                "api_key": provider.api_key,
            }
        )
    return out


def resolve_purpose(session: Session, key: str) -> Optional[List[dict]]:
    """Resolve a purpose key to its expanded connection chain, or None if the
    purpose has no (active) assignment.

    Raises:
        ResolveError: if the assignment's stored chain is malformed.
    """
    assignment = session.exec(
        select(Assignment).where(Assignment.key == key, Assignment.active)
    ).first()
    if assignment is None:
        return None
    providers = {
        p.prefix: p for p in session.exec(select(Provider).where(Provider.active)).all()
    }
    return resolve(_load_chain(assignment.chain), providers)


def _load_chain(raw: str) -> List[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ResolveError("assignment chain is not valid JSON") from exc
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ResolveError("assignment chain must be a JSON list of strings")
    return list(value)


def json_dump_chain(chain: List[str]) -> str:
    """Serialize a chain for storage as a compact JSON array of strings."""
    return json.dumps(chain)
