"""Tests for llm_router_client.resolve_chain and caching."""

import httpx
import pytest

from llm_router_client.client import ModelConfig, clear_cache, resolve_chain


def _transport(handler):
    return httpx.MockTransport(handler)


def _ok_handler(request, **kw):
    payload = kw.get("payload")
    if payload is None:
        payload = {
            "purpose": "demo:job",
            "chain": [
                {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "base_url": "http://x",
                    "api_key": "sk",
                },
                {
                    "provider": "ollama",
                    "model": "llama3",
                    "base_url": "http://l",
                    "api_key": None,
                },
            ],
        }
    return httpx.Response(200, json=payload)


def test_resolve_chain_returns_configs():
    clear_cache()
    chain = resolve_chain(
        "demo:job",
        base_url="http://router",
        use_cache=False,
        transport=_transport(_ok_handler),
    )
    assert isinstance(chain[0], ModelConfig)
    assert chain[0].provider == "openai"
    assert chain[0].model == "gpt-4o-mini"
    assert chain[1].api_key is None


def test_resolve_chain_404_raises_keyerror():
    def handler(request):
        return httpx.Response(404, json={"detail": "no assignment"})

    clear_cache()
    with pytest.raises(KeyError):
        resolve_chain(
            "missing:job",
            base_url="http://router",
            use_cache=False,
            transport=_transport(handler),
        )


def test_resolve_chain_cache_hit_skips_http():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return _ok_handler(request)

    clear_cache()
    _ = resolve_chain("c:j", base_url="http://router", transport=_transport(handler))
    _ = resolve_chain("c:j", base_url="http://router", transport=_transport(handler))
    assert calls["n"] == 1  # second call served from cache, no HTTP


def test_resolve_chain_server_500_raises():
    def handler(request):
        return httpx.Response(500, json={"detail": "boom"})

    clear_cache()
    with pytest.raises(httpx.HTTPStatusError):
        resolve_chain(
            "c:j",
            base_url="http://router",
            use_cache=False,
            transport=_transport(handler),
        )
