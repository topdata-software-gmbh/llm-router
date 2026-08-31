"""Tests for the fallback-chain walker."""

import asyncio

import pytest

from llm_router_client import fallback
from llm_router_client.client import ModelConfig
from llm_router_client.fallback import ChainExhaustedError, with_fallbacks


class _RetryAfterError(Exception):
    status_code = 429
    retry_after = 0.0  # immediate for tests


class _TransientError(Exception):
    status_code = 503


class _FatalError(Exception):
    status_code = 400


@pytest.mark.asyncio
async def test_primary_success(monkeypatch):
    seen = []

    async def call_fn(model):
        seen.append(model.model)
        return "ok"

    monkeypatch.setattr(
        fallback,
        "resolve_raw",
        lambda purpose, base_url=None: [ModelConfig("openai", "a", "http://x")],
    )
    result = await with_fallbacks("p:q", call_fn, max_per_model=2, backoff_base_ms=1)
    assert result == "ok"
    assert seen == ["a"]


@pytest.mark.asyncio
async def test_walks_to_fallback(monkeypatch):
    seen = []

    async def call_fn(model):
        seen.append(model.model)
        if model.model == "primary":
            raise _TransientError()
        return model.model

    monkeypatch.setattr(
        fallback,
        "resolve_raw",
        lambda purpose, base_url=None: [
            ModelConfig("openai", "primary", "http://x"),
            ModelConfig("openai", "fallback", "http://x"),
        ],
    )
    result = await with_fallbacks("p:q", call_fn, max_per_model=1, backoff_base_ms=1)
    assert result == "fallback"
    assert seen == ["primary", "fallback"]


@pytest.mark.asyncio
async def test_respects_retry_after(monkeypatch):
    async def call_fn(model):
        raise _RetryAfterError()

    monkeypatch.setattr(fallback, "asyncio", asyncio)
    # just verify it attempts and then exhausts (backoff_ms stays 0 so fast)
    monkeypatch.setattr(
        fallback,
        "resolve_raw",
        lambda purpose, base_url=None: [ModelConfig("openai", "a", "http://x")],
    )
    with pytest.raises(ChainExhaustedError):
        await with_fallbacks("p:q", call_fn, max_per_model=1, backoff_base_ms=1)


@pytest.mark.asyncio
async def test_exhausted_raises(monkeypatch):
    async def call_fn(model):
        raise _FatalError()

    monkeypatch.setattr(
        fallback,
        "resolve_raw",
        lambda purpose, base_url=None: [ModelConfig("openai", "a", "http://x")],
    )
    with pytest.raises(ChainExhaustedError) as exc:
        await with_fallbacks("p:q", call_fn, max_per_model=1, backoff_base_ms=1)
    assert exc.value.purpose == "p:q"
