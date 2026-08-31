"""Unit tests for the detection module."""

from llm_router.core.detect import (
    ENV_PROVIDERS,
    detect_from_env,
    detect_local_ports,
    detect_ollama_models,
    scan,
)


def test_detect_from_env_finds_configured_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    providers = detect_from_env()
    by_prefix = {p.prefix: p for p in providers}
    assert "openai" in by_prefix
    assert by_prefix["openai"].base_url == ENV_PROVIDERS["OPENAI_API_KEY"][1]
    assert by_prefix["openai"].api_key == "sk-test"
    assert "groq" in by_prefix
    # unrelated key should not create a provider
    assert "anthropic" not in by_prefix


def test_detect_from_env_empty(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert detect_from_env() == []


def test_detect_local_ports_probes(monkeypatch):
    monkeypatch.setattr(
        "llm_router.core.detect._probe_port",
        lambda host, port, timeout=0.5: port == 11434,
    )
    providers = detect_local_ports()
    prefixes = {p.prefix for p in providers}
    assert "ollama" in prefixes
    assert "lmstudy" not in prefixes


def test_detect_ollama_models_parses(monkeypatch):
    fake_out = (
        "NAME ID SIZE MODIFIED\nllama3.2:latest abc 2GB ago\nmistral xyz 4GB ago\n"
    )
    monkeypatch.setattr(
        "llm_router.core.detect.subprocess.run",
        lambda *a, **k: type("R", (), {"stdout": fake_out})(),
    )
    models = detect_ollama_models()
    ids = {m.model for m in models}
    assert "llama3.2:latest" in ids
    # missing :tag gets :latest appended
    assert "mistral:latest" in ids


def test_detect_ollama_models_missing_binary(monkeypatch):
    def fake_run(*a, **k):
        raise FileNotFoundError("ollama")

    monkeypatch.setattr("llm_router.core.detect.subprocess.run", fake_run)
    assert detect_ollama_models() == []


def test_scan_aggregates(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("llm_router.core.detect._probe_port", lambda *a, **k: False)
    monkeypatch.setattr(
        "llm_router.core.detect.subprocess.run",
        lambda *a, **k: type("R", (), {"stdout": "NAME ID\nllama3:latest abc\n"})(),
    )
    result = scan()
    assert any(p.prefix == "openai" for p in result.providers)
    assert any(m.provider == "ollama" for m in result.models)
