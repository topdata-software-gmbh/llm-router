"""HTTP client for resolving purposes against the llm-router service.

Caches the last successful resolution per purpose (TTL) so batch scripts
survive transient router downtime — the router DB remains the source of truth.
"""

import time
from dataclasses import dataclass
from typing import List, Optional

import httpx

from .config import router_url

DEFAULT_TTL_SECONDS = 300
_cache: dict[str, tuple[float, list["ModelConfig"]]] = {}


@dataclass
class ModelConfig:
    """Expanded connection spec for one provider/model pair."""

    provider: str
    model: str
    base_url: str
    api_key: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ModelConfig":
        return cls(
            provider=d["provider"],
            model=d["model"],
            base_url=d["base_url"],
            api_key=d.get("api_key"),
        )


def _http_get(
    url: str,
    *,
    timeout: float = 5.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> httpx.Response:
    """Thin wrapper around GET so tests can inject a MockTransport."""
    if transport is not None:
        with httpx.Client(transport=transport) as client:
            return client.get(url, timeout=timeout)
    return httpx.get(url, timeout=timeout)


def resolve_chain(
    purpose: str,
    *,
    base_url: Optional[str] = None,
    use_cache: bool = True,
    ttl: float = DEFAULT_TTL_SECONDS,
    transport: Optional[httpx.BaseTransport] = None,
) -> List[ModelConfig]:
    """Fetch the ordered connection chain for a purpose from the router.

    The first entry is the primary; the rest are fallbacks in walk order.
    Raises ``KeyError`` if the purpose has no assignment (404) and
    ``httpx.HTTPStatusError`` for server-side 4xx/5xx errors.
    """
    url = (base_url or router_url()).rstrip("/")
    if use_cache and purpose in _cache:
        expires, cached = _cache[purpose]
        if time.time() < expires:
            return cached
    resp = _http_get(f"{url}/api/resolve/{purpose}", transport=transport)
    if resp.status_code == 404:
        raise KeyError(
            f"no assignment for purpose {purpose!r} "
            f"(router at {url}); run `llm-router assignment set`"
        )
    resp.raise_for_status()
    chain = [ModelConfig.from_dict(c) for c in resp.json()["chain"]]
    if use_cache:
        _cache[purpose] = (time.time() + ttl, chain)
    return chain


def clear_cache() -> None:
    """Drop the in-memory resolution cache (used in tests)."""
    _cache.clear()
