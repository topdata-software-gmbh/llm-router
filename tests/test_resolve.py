"""Unit tests for chain resolution."""

import pytest
from sqlmodel import Session

from llm_router.core.resolve import (
    ResolveError,
    json_dump_chain,
    resolve,
    resolve_purpose,
)
from llm_router.models import Assignment, Provider


def _providers():
    return {
        "openai": Provider(
            prefix="openai",
            name="openai",
            base_url="https://api.openai.com/v1",
            api_key="sk",
        ),
        "ollama": Provider(
            prefix="ollama", name="ollama", base_url="http://localhost:11434/v1"
        ),
    }


def test_resolve_expands_chain_in_order():
    chain = resolve(["openai/gpt-4o-mini", "ollama/llama3:latest"], _providers())
    assert len(chain) == 2
    assert chain[0]["provider"] == "openai"
    assert chain[0]["model"] == "gpt-4o-mini"
    assert chain[0]["base_url"] == "https://api.openai.com/v1"
    assert chain[0]["api_key"] == "sk"
    assert chain[1]["provider"] == "ollama"
    assert chain[1]["api_key"] is None


def test_resolve_rejects_malformed_entry():
    with pytest.raises(ResolveError):
        resolve(["no-slash"], _providers())


def test_resolve_rejects_unknown_provider():
    with pytest.raises(ResolveError):
        resolve(["nope/gpt-4o"], _providers())


def test_resolve_purpose_roundtrip(isolated_db):
    with Session(isolated_db) as session:
        session.add(
            Assignment(
                key="git-digest:digest",
                owner="git-digest",
                chain=json_dump_chain(
                    ["openai/gpt-4o-mini", "anthropic/claude-3-haiku"]
                ),
            )
        )
        session.add(
            Provider(
                prefix="openai",
                name="openai",
                base_url="https://api.openai.com/v1",
                api_key="sk",
            )
        )
        session.add(
            Provider(
                prefix="anthropic",
                name="anthropic",
                base_url="https://api.anthropic.com",
            )
        )
        session.commit()
        chain = resolve_purpose(session, "git-digest:digest")
    assert chain is not None
    assert chain[0]["model"] == "gpt-4o-mini"
    assert chain[1]["provider"] == "anthropic"


def test_resolve_purpose_missing(isolated_db):
    with Session(isolated_db) as session:
        assert resolve_purpose(session, "does:not-exist") is None


def test_resolve_purpose_malformed_chain(isolated_db):
    with Session(isolated_db) as session:
        session.add(
            Assignment(
                key="bad:chain",
                owner="bad",
                chain="not-json",
            )
        )
        session.add(Provider(prefix="openai", name="openai", base_url="http://x"))
        session.commit()
        with pytest.raises(ResolveError):
            resolve_purpose(session, "bad:chain")
