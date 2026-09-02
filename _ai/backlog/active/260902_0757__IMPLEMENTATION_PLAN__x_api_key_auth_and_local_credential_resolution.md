---
filename: "_ai/backlog/active/260902_0757__IMPLEMENTATION_PLAN__x_api_key_auth_and_local_credential_resolution.md"
title: "X-API-Key Router Authentication and Client-Side Local LLM Credential Resolution"
createdAt: 2026-09-02 07:57
updatedAt: 2026-09-02 07:57
status: draft
priority: high
tags: [security, x-api-key, auth, pydantic-ai, llm-router-client, local-credentials]
estimatedComplexity: moderate
documentRevision: 1
documentType: IMPLEMENTATION_PLAN
---

# Implementation Plan: X-API-Key Router Auth & Client-Side Local LLM Credential Resolution

## 1. Problem Description
Currently, `llm-router` stores upstream vendor API keys centrally in SQLite and returns them in plaintext (`api_key: "sk-..."`) whenever `/api/resolve/{purpose}` is queried. This presents critical security and operational risks when exposing the service publicly for colleagues or remote projects:
1. **Upstream Key Leakage**: Anyone resolving a purpose receives root access to OpenAI/Anthropic/Groq credentials with zero spending governance or attribution.
2. **Missing Ingress Authentication**: The router has no auth mechanism, leaving it vulnerable to unauthenticated public queries.
3. **Incompatible Local Models**: Hardcoded `http://localhost:11434` endpoints fail across differing network perimeters.

## 2. Executive Summary
This plan transforms `llm-router` into a **zero-secret configuration plane** with `X-API-Key` header authentication, and empowers `llm_router_client` to resolve LLM credentials **locally** from caller environments before building PydanticAI models.

Key outcomes:
1. **Router Ingress Security**: FastAPI endpoints require a valid `X-API-Key` request header configured via `LLM_ROUTER_API_KEYS` (comma-separated list of valid client keys) or optional per-key DB table.
2. **Sanitized Resolution**: The router strips/omits upstream provider secrets from resolution payloads, returning strictly routing topology (`provider`, `model`, `base_url`).
3. **Client-Side Credential Resolver (`llm_router_client.credentials`)**: A local provider-to-env mapper resolves `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, etc., from the caller's local environment.
4. **PydanticAI Multi-Provider Factory (`llm_router_client.pydantic_ai`)**: Automatically creates the correct PydanticAI model class (e.g. `AnthropicModel`, `OpenAIChatModel`) attaching local keys and configured base URLs.
5. **Client Auth Injection**: `llm_router_client` sends `X-API-Key: $LLM_ROUTER_API_KEY` on all requests.

---

## 3. Project Environment Details
- **Project Name**: llm-router
- **Frontend root**: N/A
- **Backend root**: `src`
- **Python Version**: 3.12+ (managed by `uv`)
- **Key Dependencies**: FastAPI, PydanticAI (V2 / slim), SQLModel, Alembic, Typer, Rich, HTTPX

---

## 4. Phased Implementation Plan

### Phase 1: Router Server Authentication via `X-API-Key`

#### Objective:
Enforce `X-API-Key` header authentication on all API routes (`/api/*`), configurable via `LLM_ROUTER_API_KEYS` (or bypassed in dev if left unset).

```python
# [MODIFY] src/llm_router/config.py
```
```python
"""Application configuration."""

import os
from pathlib import Path
from typing import Set

# --- Runtime settings -----------------------------------------------------
DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent / "llm_router.db")
DATABASE_PATH = os.environ.get("LLM_ROUTER_DB", DEFAULT_DB_PATH)
DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

DEFAULT_BASE_URL = os.environ.get("LLM_ROUTER_URL", "http://localhost:8000")

# --- Security / Auth ------------------------------------------------------
# Comma-separated list of valid X-API-Key tokens. If empty, auth is disabled (dev mode).
def get_allowed_api_keys() -> Set[str]:
    raw = os.environ.get("LLM_ROUTER_API_KEYS", "").strip()
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}

# --- CLI conventions ------------------------------------------------------
CLI_CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
}
```

```python
# [NEW FILE] src/llm_router/auth.py
```
```python
"""Authentication dependency verifying X-API-Key headers."""

from typing import Optional
from fastapi import Header, HTTPException, status
from .config import get_allowed_api_keys


def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> Optional[str]:
    """Verify that incoming request provides a valid X-API-Key.
    
    If no keys are configured in LLM_ROUTER_API_KEYS, authentication is skipped
    to maintain zero-config local development backwards compatibility.
    """
    allowed_keys = get_allowed_api_keys()
    if not allowed_keys:
        return x_api_key

    if not x_api_key or x_api_key not in allowed_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_api_key
```

```python
# [MODIFY] src/llm_router/main.py
```
```python
"""FastAPI application factory and lifespan for the llm-router service."""

from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI

from .auth import verify_api_key
from .db import init_db
from .routers import assignments, models, providers, resolve, scan


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="llm-router",
        version="0.2.0",
        lifespan=lifespan,
        dependencies=[Depends(verify_api_key)],
    )
    app.include_router(providers.router)
    app.include_router(models.router)
    app.include_router(assignments.router)
    app.include_router(resolve.router)
    app.include_router(scan.router)
    return app


app = create_app()
```

---

### Phase 2: Sanitize Upstream Secrets in Resolution

#### Objective:
Remove or redact upstream `api_key` from resolve output so the router acts purely as a configuration registry.

```python
# [MODIFY] src/llm_router/core/resolve.py
```
```python
"""Resolution: expand an assignment's ordered chain into concrete connection specs."""

import json
from typing import Dict, List, Optional
from sqlmodel import Session, select
from ..models import Assignment, Provider


class ResolveError(Exception):
    """Raised when a chain or provider reference cannot be resolved."""


def resolve(chain: List[str], providers: Dict[str, Provider]) -> List[dict]:
    """Expand a chain of provider/model strings into connection specs without secrets."""
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
                "prefix": provider.prefix,
                "model": model,
                "base_url": provider.base_url,
            }
        )
    return out


def resolve_purpose(session: Session, key: str) -> Optional[List[dict]]:
    """Resolve a purpose key to its expanded connection chain without leaking credentials."""
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
    return json.dumps(chain)
```

---

### Phase 3: Client Library Authentication & Local Credential Resolver

#### Objective:
Implement `X-API-Key` sending in `llm_router_client` and create local environment credential resolution.

```python
# [MODIFY] src/llm_router_client/config.py
```
```python
"""LLM router client configuration."""

import os
from typing import Optional

DEFAULT_ROUTER_URL = "http://localhost:8000"


def router_url() -> str:
    """Base URL of the running llm-router service."""
    return os.environ.get("LLM_ROUTER_URL", DEFAULT_ROUTER_URL).rstrip("/")


def router_api_key() -> Optional[str]:
    """Client API key for authenticating with the llm-router service."""
    return os.environ.get("LLM_ROUTER_API_KEY")
```

```python
# [NEW FILE] src/llm_router_client/credentials.py
```
```python
"""Local LLM vendor API key resolution."""

import os
from typing import Dict, List, Optional, Union

# Provider name/prefix -> list of candidate env var names checked in order
DEFAULT_ENV_KEY_MAP: Dict[str, List[str]] = {
    "openai": ["OPENAI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "groq": ["GROQ_API_KEY"],
    "openrouter": ["OPENROUTER_API_KEY"],
    "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"],
    "cohere": ["COHERE_API_KEY"],
    "ollama": [],  # Local, requires no key
}


def get_local_api_key(
    provider: str,
    custom_map: Optional[Dict[str, Union[str, List[str]]]] = None,
) -> Optional[str]:
    """Look up the appropriate vendor API key from the local environment.
    
    Args:
        provider: Provider identifier (e.g. 'openai', 'anthropic', 'ollama').
        custom_map: Optional overrides for environment variable mappings.
        
    Returns:
        The resolved API key string or None if not required/not found.
    """
    provider_key = provider.lower().strip()
    env_keys: List[str] = []
    
    if custom_map and provider_key in custom_map:
        mapped = custom_map[provider_key]
        env_keys = [mapped] if isinstance(mapped, str) else list(mapped)
    elif provider_key in DEFAULT_ENV_KEY_MAP:
        env_keys = DEFAULT_ENV_KEY_MAP[provider_key]
    else:
        # Fallback heuristic: {PROVIDER}_API_KEY
        env_keys = [f"{provider_key.upper()}_API_KEY"]

    for key_name in env_keys:
        if val := os.environ.get(key_name):
            return val
            
    return None
```

```python
# [MODIFY] src/llm_router_client/client.py
```
```python
"""HTTP client for resolving purposes against the llm-router service."""

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx

from .config import router_api_key, router_url

DEFAULT_TTL_SECONDS = 300
_cache: dict[str, tuple[float, list["ModelConfig"]]] = {}


@dataclass
class ModelConfig:
    """Expanded connection spec for one provider/model pair."""

    provider: str
    model: str
    base_url: str
    prefix: Optional[str] = None
    api_key: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ModelConfig":
        return cls(
            provider=d["provider"],
            model=d["model"],
            base_url=d["base_url"],
            prefix=d.get("prefix"),
            api_key=d.get("api_key"),
        )


def _http_get(
    url: str,
    *,
    api_key: Optional[str] = None,
    timeout: float = 5.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> httpx.Response:
    """Send HTTP GET with X-API-Key header."""
    headers: Dict[str, str] = {}
    key = api_key or router_api_key()
    if key:
        headers["X-API-Key"] = key

    if transport is not None:
        with httpx.Client(transport=transport, headers=headers) as client:
            return client.get(url, timeout=timeout)
    return httpx.get(url, headers=headers, timeout=timeout)


def resolve_chain(
    purpose: str,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    use_cache: bool = True,
    ttl: float = DEFAULT_TTL_SECONDS,
    transport: Optional[httpx.BaseTransport] = None,
) -> List[ModelConfig]:
    """Fetch the ordered connection chain for a purpose from the router."""
    url = (base_url or router_url()).rstrip("/")
    if use_cache and purpose in _cache:
        expires, cached = _cache[purpose]
        if time.time() < expires:
            return cached
    resp = _http_get(
        f"{url}/api/resolve/{purpose}",
        api_key=api_key,
        transport=transport,
    )
    if resp.status_code == 401:
        raise PermissionError(
            f"Unauthorized: Invalid or missing X-API-Key for router at {url}. "
            "Set LLM_ROUTER_API_KEY."
        )
    if resp.status_code == 404:
        raise KeyError(
            f"no assignment for purpose {purpose!r} (router at {url}); "
            "run `llm-router assignment set`"
        )
    resp.raise_for_status()
    chain = [ModelConfig.from_dict(c) for c in resp.json()["chain"]]
    if use_cache:
        _cache[purpose] = (time.time() + ttl, chain)
    return chain


def clear_cache() -> None:
    _cache.clear()
```

---

### Phase 4: PydanticAI Multi-Provider Integration

#### Objective:
Support dynamic construction of PydanticAI models using resolved local credentials.

```python
# [MODIFY] src/llm_router_client/pydantic_ai.py
```
```python
"""PydanticAI integration: build models from llm-router assignments."""

from typing import Any, List, Optional

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from .client import ModelConfig, resolve_chain
from .credentials import get_local_api_key


def build_model(model_config: ModelConfig) -> Any:
    """Build a PydanticAI model from a ModelConfig with local credentials."""
    local_key = model_config.api_key or get_local_api_key(model_config.provider)

    # Provider specific builders
    provider_name = model_config.provider.lower()

    if provider_name == "anthropic":
        try:
            from pydantic_ai.models.anthropic import AnthropicModel
            return AnthropicModel(model_name=model_config.model, api_key=local_key)
        except ImportError:
            pass  # Fallback to OpenAI-compatible provider if anthropic package not installed

    # Default to OpenAI-compatible provider
    provider = OpenAIProvider(
        base_url=model_config.base_url,
        api_key=local_key,
    )
    return OpenAIChatModel(model_name=model_config.model, provider=provider)


def router_model(
    purpose: str,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Any:
    """Primary model for a purpose (picks chain[0])."""
    chain = resolve_chain(purpose, base_url=base_url, api_key=api_key)
    return build_model(chain[0])


def router_model_chain(
    purpose: str,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> List[Any]:
    """Ordered pre-built models for the fallback engine (primary first)."""
    chain = resolve_chain(purpose, base_url=base_url, api_key=api_key)
    return [build_model(c) for c in chain]


def resolve_raw(
    purpose: str,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> List[ModelConfig]:
    """Low-level escape hatch returning raw ModelConfigs with local keys attached."""
    configs = resolve_chain(purpose, base_url=base_url, api_key=api_key)
    for c in configs:
        if not c.api_key:
            c.api_key = get_local_api_key(c.provider)
    return configs
```

---

### Phase 5: Testing & Validation

#### Objective:
Update and add comprehensive tests for:
1. `X-API-Key` auth verification on API endpoints (401 when invalid, 200 when valid).
2. Sanitized `/api/resolve/{purpose}` responses without `api_key`.
3. Client `resolve_chain` passing `X-API-Key`.
4. `llm_router_client.credentials.get_local_api_key`.
5. PydanticAI model dynamic building.

```python
# [MODIFY] tests/test_api.py
```
```python
"""API-level tests for assignments, auth, and resolve endpoints."""

import pytest
from fastapi.testclient import TestClient
from llm_router.main import create_app


def _seed_provider(client):
    r = client.post(
        "/api/providers/upsert",
        json={
            "name": "openai",
            "prefix": "openai",
            "base_url": "https://api.openai.com/v1",
        },
    )
    assert r.status_code == 200
    return r.json()


def test_auth_enforced_when_keys_configured(monkeypatch, isolated_db):
    monkeypatch.setenv("LLM_ROUTER_API_KEYS", "secret-key-1,secret-key-2")
    client = TestClient(create_app())
    
    # 1. Without header -> 401
    r = client.get("/api/providers")
    assert r.status_code == 401
    
    # 2. With invalid header -> 401
    r = client.get("/api/providers", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 401
    
    # 3. With valid header -> 200
    r = client.get("/api/providers", headers={"X-API-Key": "secret-key-1"})
    assert r.status_code == 200


def test_resolve_returns_sanitized_chain(client):
    _seed_provider(client)
    client.put(
        "/api/assignments/acp:chat",
        json={
            "key": "acp:chat",
            "owner": "acp",
            "chain": ["openai/gpt-4o-mini"],
        },
    )
    r = client.get("/api/resolve/acp:chat")
    assert r.status_code == 200
    body = r.json()
    assert body["purpose"] == "acp:chat"
    assert body["chain"][0]["provider"] == "openai"
    assert body["chain"][0]["model"] == "gpt-4o-mini"
    assert "api_key" not in body["chain"][0] or body["chain"][0]["api_key"] is None
```

```python
# [NEW FILE] tests/test_credentials.py
```
```python
"""Tests for local credential resolution in llm_router_client."""

from llm_router_client.credentials import get_local_api_key


def test_get_local_api_key_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local-test")
    assert get_local_api_key("openai") == "sk-local-test"


def test_get_local_api_key_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-local-test")
    assert get_local_api_key("anthropic") == "ant-local-test"


def test_get_local_api_key_ollama():
    assert get_local_api_key("ollama") is None


def test_get_local_api_key_custom_map(monkeypatch):
    monkeypatch.setenv("MY_CUSTOM_KEY", "custom-123")
    assert get_local_api_key("custom", {"custom": "MY_CUSTOM_KEY"}) == "custom-123"
```

---

### Phase 6: Project Housekeeping & Documentation

#### Tasks:
1. Update `README.md` reflecting:
   - `X-API-Key` router security configuration (`LLM_ROUTER_API_KEYS`).
   - Local client credential resolution (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`).
   - Consumer client usage examples with PydanticAI.
2. Update `CHANGELOG.md` with the new authentication & security features.
3. Verify test suite: `uv run pytest`.

```markdown
# [MODIFY] README.md
```
*(Add `X-API-Key` setup instructions, client environment configuration, and PydanticAI examples).*

---

### Phase 7: Implementation Report Generation

Write the final implementation report to:
`_ai/backlog/reports/260902_0757__IMPLEMENTATION_REPORT__x_api_key_auth_and_local_credential_resolution.md`

YAML Frontmatter required:
```yaml
---
filename: "_ai/backlog/reports/260902_0757__IMPLEMENTATION_REPORT__x_api_key_auth_and_local_credential_resolution.md"
title: "Report: X-API-Key Router Auth and Client-Side Local LLM Credential Resolution"
createdAt: 2026-09-02 08:30
updatedAt: 2026-09-02 08:30
planFile: "_ai/backlog/active/260902_0757__IMPLEMENTATION_PLAN__x_api_key_auth_and_local_credential_resolution.md"
project: "llm-router"
status: completed
filesCreated: 2
filesModified: 6
filesDeleted: 0
tags: [security, x-api-key, auth, pydantic-ai, llm-router-client]
documentType: IMPLEMENTATION_REPORT
---
```

