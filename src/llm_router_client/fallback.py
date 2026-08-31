"""Fallback-chain walker: generalize super-bin's llm_retry.py.

``with_fallbacks`` tries the primary model first, retries with backoff on
transient/429 errors, and walks down the chain to fallbacks. Retry counts
are lib-side defaults (YAGNI), not per-chain-entry data in the DB.
"""

import asyncio
from typing import Awaitable, Callable, TypeVar

from .client import ModelConfig
from .pydantic_ai import resolve_raw

T = TypeVar("T")

RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


class ChainExhaustedError(Exception):
    """All models and retry attempts in the chain have been exhausted."""

    def __init__(self, purpose: str, last_error: Exception):
        self.purpose = purpose
        self.last_error = last_error
        super().__init__(
            f"chain exhausted for purpose {purpose!r}; last error: {last_error}"
        )


async def with_fallbacks(
    purpose: str,
    call_fn: Callable[[ModelConfig], Awaitable[T]],
    *,
    max_per_model: int = 2,
    backoff_base_ms: float = 500,
    backoff_max_ms: float = 10_000,
    base_url: str | None = None,
) -> T:
    """Walk the resolved chain, retrying each model with exponential backoff.

    Args:
        purpose: the purpose key to resolve.
        call_fn: async callable receiving one ``ModelConfig``; raise on failure.
        max_per_model: retry cap per chain entry before walking to the next.
        backoff_base_ms: initial backoff in milliseconds.
        backoff_max_ms: ceiling for the backoff (ignoring Retry-After).
        base_url: override the router URL for this call.

    Returns:
        The return value from the first successful ``call_fn`` invocation.

    Raises:
        ChainExhaustedError: if the entire chain is walked without a success.
    """
    chain = resolve_raw(purpose, base_url=base_url)
    if not chain:
        raise ChainExhaustedError(purpose, RuntimeError("empty chain"))
    last_error: Exception | None = None
    for model in chain:
        for attempt in range(1, max_per_model + 1):
            try:
                return await call_fn(model)
            except Exception as exc:
                last_error = exc
                retryable = getattr(
                    exc, "status_code", None
                ) in RETRYABLE_STATUS_CODES or isinstance(
                    exc, (TimeoutError, asyncio.TimeoutError)
                )
                if not retryable:
                    break
                # compute delay (respect Retry-After if present)
                retry_after = getattr(exc, "retry_after", None)
                if isinstance(retry_after, (int, float)):
                    delay_ms = min(float(retry_after) * 1000, backoff_max_ms)
                else:
                    delay_ms = min(
                        backoff_base_ms * (2 ** (attempt - 1)), backoff_max_ms
                    )
                await asyncio.sleep(delay_ms / 1000)
    raise ChainExhaustedError(purpose, last_error or RuntimeError("no models in chain"))
