---
filename: "_ai/backlog/active/260902_0757__IMPLEMENTATION_PLAN__x_api_key_auth_and_local_credential_resolution.md"
title: "X-API-Key Router Auth, Client-Side Local Credentials & Client Repo Split"
createdAt: 2026-09-02 07:57
updatedAt: 2026-09-02 08:30
status: draft
priority: high
tags: [security, x-api-key, auth, pydantic-ai, llm-router-client, local-credentials]
estimatedComplexity: complex
documentRevision: 2
documentType: IMPLEMENTATION_PLAN
---

# Implementation Plan: X-API-Key Router Auth, Client-Side Local Credentials & Client Repo Split

## 1. Problem Description
Currently, `llm-router` stores upstream vendor API keys centrally in SQLite and returns them in plaintext (`api_key: "sk-..."`) whenever `/api/resolve/{purpose}` is queried. This presents critical security and operational risks when exposing the service publicly for colleagues or remote projects:
1. **Upstream Key Leakage**: Anyone resolving a purpose receives root access to OpenAI/Anthropic/Groq credentials with zero spending governance or attribution. Keys leak through **four** routes, not just `/api/resolve`: the resolve core, `GET /api/providers`, `GET /api/catalog`, and the MCP `get_catalog`/`resolve_purpose` tools — all return `api_key` in plaintext today.
2. **Missing Ingress Authentication**: The router has no auth mechanism, leaving it vulnerable to unauthenticated public queries.
3. **Incompatible Local Models**: Hardcoded `http://localhost:11434` endpoints fail across differing network perimeters.
4. **Existing Consumer Coupling**: `digester` (the fleet member already migrated onto the router) consumes the **server-supplied `api_key`** via `router_model()`/`resolve_chain()` (see §8.1). Removing the key server-side without migrating the client *and* the consumer in lockstep would silently break `digester`'s model construction and fallback behavior.
5. **Client library entangled with the server**: `llm_router_client` ships inside this repo (same wheel: `pyproject.toml` `[tool.hatch.build.targets.wheel].packages = ["src/llm_router", "src/llm_router_client"]`). Consumers (digester) depend on the whole server package for a client they import alone. The server is gaining auth + zero-secret behavior — changes that must not force consumers onto server release train/surface area.

## 2. Executive Summary
This plan transforms `llm-router` into a **zero-secret configuration plane** with `X-API-Key` header authentication, and empowers `llm_router_client` to resolve LLM credentials **locally** from caller environments before building PydanticAI models.

Key outcomes:
1. **Router Ingress Security**: FastAPI endpoints require a valid `X-API-Key` request header configured via `LLM_ROUTER_API_KEYS` (comma-separated list of valid client keys). No per-key DB table in v1 (YAGNI — single-admin fleet, env config suffices); dev degrades to no-auth with a startup warning when unset.
2. **Minimal Resolve Contract**: The router returns strictly routing topology per chain entry — `{prefix, model, base_url}` (single provider identifier, **no** `provider`/`prefix` split, no `api_key`) — on **every** surface (`/api/resolve/{purpose}`, `GET /api/providers`, `GET /api/catalog`, MCP tools) via a single shared `provider_public()` serializer.
3. **Client-Side Credential Resolver (`llm_router_client.credentials`)**: A local provider-to-env mapper resolves `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, etc., from the caller's local environment.
4. **PydanticAI Multi-Provider Factory (`llm_router_client.pydantic_ai`)**: Explicit provider→model-class map (OpenAI/Groq → `OpenAIChatModel`, Anthropic → `AnthropicModel`, Google → `GeminiModel`, ...) with a **loud error for unsupported providers** (no silent OpenAI-compatible fallback).
5. **Client Auth Injection**: `llm_router_client` sends `X-API-Key: $LLM_ROUTER_API_KEY` on all requests.
6. **Client library extracted to `/topdata/llm-router-client`** (package `llm-router-client`, import namespace `llm_router_client` unchanged). Consumers depend on the small client repo; the server repo keeps the FastAPI app/CLI/MCP/DB.
7. **Atomic Migration**: Server-side key-stripping + minimal contract (Phases 2) and client-side local-key attachment (Phases 3–4) ship **and the existing consumer `digester` is updated (Phase 8) in the same release** — there is no intermediate state where a consumer loses its key or reads a removed field.

Release note: secrets are removed from the router entirely; the router becomes a pure **configuration plane** (prefixes/models/base URLs) and every consumer resolves credentials from its own environment. Naming (provider family derivation, display labels) is owned by the client, not the server.

---

## 3. Project Environment Details
- **Project Name**: llm-router
- **Frontend root**: N/A
- **Backend root**: `src`
- **Python Version**: 3.12+ (managed by `uv`)
- **Key Dependencies**: FastAPI, PydanticAI (V2 / slim), SQLModel, Alembic, Typer, Rich, HTTPX

---

## 4. Phased Implementation Plan

### Phase 0: Extract `llm_router_client` into `/topdata/llm-router-client`

#### Objective:
Move the client library out of this repo into a standalone project so consumers depend on a small, independently-versioned package. Import namespace `llm_router_client` and module layout stay **byte-identical** — the existing `digester` imports (`from llm_router_client...`) keep working, only the dependency path changes.

#### Tasks:
1. Scaffold `/topdata/llm-router-client` (package `llm-router-client`, pyproject with `[project] name = "llm-router-client"`, `dependencies = ["httpx", "pydantic-ai-slim", ...]`, scripts none). The user has already created the repo root; add `pyproject.toml`, `src/llm_router_client/`, `tests/`.
2. `git mv` the client modules from this repo → new repo:
   - `src/llm_router_client/__init__.py`, `client.py`, `config.py`, `credentials.py` (new), `pydantic_ai.py`, `fallback.py`
   - `tests/test_client.py`, `tests/test_fallback.py` (and any client-only tests)
3. Remove `src/llm_router_client` and client tests from this repo's `pyproject.toml` `[tool.hatch.build.targets.wheel].packages` (keep only `src/llm_router`).
4. Point the consumer (`digester`) at the new repo: `llm-router = { path = "/home/marc/devel/llm-router" }` → `llm-router-client = { path = "/topdata/llm-router-client" }` (see Phase 8).
5. Both repos `uv run pytest` green before proceeding.

```toml
# [NEW FILE] /topdata/llm-router-client/pyproject.toml (key parts)
[project]
name = "llm-router-client"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["httpx>=0.27", "pydantic-ai-slim[openai]>=0.1"]
[project.optional-dependencies]
anthropic = ["pydantic-ai-slim[anthropic]"]
google = ["pydantic-ai-slim[google-gla]"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "ruff>=0.3", "mypy>=1.8"]
```

See `ADR__260902-1__client-library-as-separate-project.md` for rationale.

---

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

### Phase 2: Sanitize Upstream Secrets & Emit Minimal Resolve Contract

#### Objective:
Remove `api_key` from **every** server output surface and emit the **minimal topology contract** — `{prefix, model, base_url}` per chain entry (single provider identifier, no `provider`/`prefix` split, no `api_key`). Centralize logic in one serializer (`provider_public()`) used by the resolve core, the providers router, the catalog endpoint, and the MCP server — so no surface can regress into leaking keys or re-introducing the redundant split.

See `ADR__260902-2__minimal-resolve-contract.md` for the contract decision.

```python
# [NEW FILE] src/llm_router/serialize.py
```
```python
"""Public serializers: guarantee provider secrets never leave the server.

All output surfaces (resolve, providers, catalog, MCP) must route through
``provider_public`` so an ``api_key`` can only ever be written, never read back.
The public contract is minimal: ``{prefix, base_url}`` — ``prefix`` is the single
provider identifier (chain/lookup key); clients own naming and credential
derivation.
"""
from typing import Dict

from .models import Provider


def provider_public(p: Provider) -> Dict[str, object]:
    """The provider fields safe to expose to callers (never ``api_key``)."""
    return {
        "prefix": p.prefix,
        "base_url": p.base_url,
    }
```

```python
# [MODIFY] src/llm_router/core/resolve.py
```
```python
"""Resolution: expand an assignment's ordered chain into concrete connection specs.

Resolution returns the minimal public contract per entry: ``{prefix, model,
base_url}`` — never the provider's ``api_key`` and no redundant ``provider``/
``prefix`` split. Credentials and naming are resolved client-side, so the router
acts as a pure configuration plane.
"""

import json
from typing import Dict, List, Optional

from sqlmodel import Session, select

from ..models import Assignment, Provider
from ..serialize import provider_public


class ResolveError(Exception):
    """Raised when a chain or provider reference cannot be resolved."""


def resolve(chain: List[str], providers: Dict[str, Provider]) -> List[dict]:
    """Expand a chain of ``provider/model`` strings into sanitized specs."""
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
        spec = provider_public(provider)
        spec["model"] = model
        out.append(spec)
    return out


def resolve_purpose(session: Session, key: str) -> Optional[List[dict]]:
    """Resolve a purpose key to its expanded connection chain without secrets."""
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

```python
# [MODIFY] src/llm_router/routers/providers.py  — do NOT return api_key
```
```python
class ProviderOut(BaseModel):
    prefix: str
    base_url: str
    id: int
    active: bool = True


@router.get("", response_model=List[ProviderOut])
def list_providers(session: Session = SessionDep):
    return session.exec(select(Provider).order_by(Provider.name)).all()
```

(`ProviderOut` exposes `{prefix, base_url}` — no `api_key`, no redundant `name`/`provider` split. `POST /upsert` still **accepts** `api_key` for write-path convenience; only reads strip it.)

```python
# [MODIFY] src/llm_router/routers/resolve.py  — catalog must not leak keys
```
```python
from ..serialize import provider_public

@router.get("/catalog", response_model=CatalogOut)
def catalog(session: Session = SessionDep):
    providers = session.exec(select(Provider).order_by(Provider.name)).all()
    models = session.exec(select(Model).order_by(Model.model)).all()
    return CatalogOut(
        providers=[provider_public(p) for p in providers],
        models=[m.model_dump() for m in models],
    )
```

```python
# [MODIFY] src/llm_router/mcp/server.py  — MCP surfaces must be sanitized too
```
```python
from ..serialize import provider_public

@mcp.tool()
def get_catalog() -> dict:
    with Session(engine) as session:
        providers = [provider_public(p) for p in session.exec(select(Provider)).all()]
        models = [m.model_dump() for m in session.exec(select(Model)).all()]
    return {"providers": providers, "models": models}
```

(`resolve_purpose` in the MCP server already calls `core.resolve_purpose`, so it is sanitised automatically by the Phase 2 core change — only `get_catalog` needed the explicit serializer.)

#### Constraints:
- `api_key` is **write-only**: `scan`, `POST /api/providers/upsert`, and the CLI may keep setting it, but no read path may return it.
- Existing tests that assert `api_key is returned` **must be updated**, not just augmented (see Phase 5).

---

### Phase 3: Client Library (`/topdata/llm-router-client`) — Auth & Local Credential Resolver

#### Objective:
Implement `X-API-Key` sending in `llm_router_client` and create local environment credential resolution. **All Phase 3–4 edits happen in the standalone `/topdata/llm-router-client` repo** (package `llm-router-client`, import namespace `llm_router_client` unchanged — see `ADR__260902-1__client-library-as-separate-project.md`). The paths below are relative to that repo (`src/llm_router_client/...`).

```python
# [MODIFY] src/llm_router_client/config.py  (in /topdata/llm-router-client)
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
# [NEW FILE] src/llm_router_client/credentials.py  (in /topdata/llm-router-client)
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
# [MODIFY] src/llm_router_client/client.py  (in /topdata/llm-router-client)
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
    """Expanded connection spec for one provider/model pair.

    ``provider`` is the human/derived name; the wire carries the provider's
    stable ``prefix``, which the client uses as the single identifier and to
    look up local credentials. ``provider`` defaults to ``prefix``.
    """

    provider: str
    model: str
    base_url: str
    prefix: str = ""
    api_key: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ModelConfig":
        prefix = d["prefix"]
        return cls(
            provider=prefix,          # client owns naming; derive from prefix
            model=d["model"],
            base_url=d["base_url"],
            prefix=prefix,
            api_key=d.get("api_key"),  # always None on the wire post-Phase-2
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
Explicitly construct the correct PydanticAI model class per provider, attaching **local** credentials resolved from the caller environment. No silent "default to OpenAI-compatible" fallback — an unknown provider errors loudly so misconfiguration is caught at build time, not at runtime with a confusing connect failure.

```python
# [MODIFY] src/llm_router_client/pydantic_ai.py  (in /topdata/llm-router-client)
```
```python
"""PydanticAI integration: build models from llm-router assignments.

Credentials are resolved from the local environment (never the router wire),
via :func:`llm_router_client.credentials.get_local_api_key`. Every supported
provider is mapped to its concrete PydanticAI model class; unknown providers
raise a clear error instead of silently misrouting.
"""

from typing import Any, Callable, Dict, List, Optional

from .client import ModelConfig, resolve_chain
from .credentials import get_local_api_key


def _openai_compatible(name: str, **kw) -> dict:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    provider = OpenAIProvider(base_url=kw["base_url"], api_key=kw["api_key"])
    return OpenAIChatModel(model_name=name, provider=provider)


def _anthropic(name: str, **kw) -> Any:
    from pydantic_ai.models.anthropic import AnthropicModel

    return AnthropicModel(model_name=name, api_key=kw["api_key"])


def _gemini(name: str, **kw) -> Any:
    from pydantic_ai.models.gemini import GeminiModel

    return GeminiModel(model_name=name, api_key=kw["api_key"])


# provider name -> (model builder fn, required env var candidate list)
_PROVIDER_BUILDERS: Dict[str, Callable[..., Any]] = {
    "openai": _openai_compatible,
    "groq": _openai_compatible,       # OpenAI-compatible API surface
    "openrouter": _openai_compatible, # OpenAI-compatible API surface
    "mistral": _openai_compatible,    # OpenAI-compatible API surface
    "anthropic": _anthropic,
    "gemini": _gemini,
    "google": _gemini,
}


def build_model(model_config: ModelConfig) -> Any:
    """Build a PydanticAI model from a ModelConfig with local credentials."""
    provider_name = model_config.provider.lower()
    builder = _PROVIDER_BUILDERS.get(provider_name)
    if builder is None:
        # ollama and other local endpoints may need no key; treat unknown
        # providers as OpenAI-compatible ONLY when base_url is present and
        # the provider carries no key requirement. Otherwise fail loudly.
        if model_config.base_url:
            builder = _openai_compatible
        else:
            raise ValueError(
                f"unsupported provider {model_config.provider!r}: no builder mapped "
                "and no base_url to fall back on; add a builder or a base_url"
            )
    key = model_config.api_key or get_local_api_key(provider_name)
    return builder(model_config.model, base_url=model_config.base_url, api_key=key)


def router_model(
    purpose: str, *, base_url: Optional[str] = None, api_key: Optional[str] = None
) -> Any:
    """Primary model for a purpose (picks chain[0])."""
    chain = resolve_chain(purpose, base_url=base_url, api_key=api_key)
    return build_model(chain[0])


def router_model_chain(
    purpose: str, *, base_url: Optional[str] = None, api_key: Optional[str] = None
) -> List[Any]:
    """Ordered pre-built models for the fallback engine (primary first)."""
    chain = resolve_chain(purpose, base_url=base_url, api_key=api_key)
    return [build_model(c) for c in chain]


def resolve_raw(
    purpose: str, *, base_url: Optional[str] = None, api_key: Optional[str] = None
) -> List[ModelConfig]:
    """Low-level escape hatch returning raw ModelConfigs with local keys attached."""
    configs = resolve_chain(purpose, base_url=base_url, api_key=api_key)
    for c in configs:
        if not c.api_key:
            c.api_key = get_local_api_key(c.provider)
    return configs
```

#### Note on provider extras:
`pyproject.toml` currently installs only `pydantic-ai-slim[openai]`. To support `_anthropic`/`_gemini`, add the matching extras (`[anthropic]`, `[google-gla]`, `[groq]` is covered by openai) as **optional** extras on `llm-router` and the consumer `digester`, so the builder imports succeed. Keep the default runtime (server + basic client) on the openai extra only; `build_model` still raises clearly if an extra is missing.

#### Fallback compatibility:
`fallback.with_fallbacks` calls `resolve_raw`, so after this Phase every `ModelConfig` handed to `call_fn` carries a locally-attached `api_key`. This preserves the existing fallback contract for consumers (digester) with **no change to their callbacks**.

---

### Phase 5: Testing & Validation

#### Objective:
Update and add comprehensive tests for:
1. `X-API-Key` auth verification on API endpoints (401 when invalid/missing, 200 when valid).
2. **Sanitized + minimal output on every surface** — `/api/resolve/{purpose}`, `GET /api/providers`, `GET /api/catalog`, and the MCP `get_catalog`/`resolve_purpose` — asserts **no `api_key`** and **no `provider`/`prefix` split** (`{prefix, model, base_url}` only).
3. Client `resolve_chain` sends `X-API-Key` and tolerates a sanitized (keyless) response; `ModelConfig.provider` derives from `prefix`. (Client tests live in `/topdata/llm-router-client`.)
4. `llm_router_client.credentials.get_local_api_key` (in `/topdata/llm-router-client`).
5. PydanticAI model building — explicit provider dispatch, unknown-provider error, Anthropic/Gemini extras path (in `/topdata/llm-router-client`).
6. **Update pre-existing assertions** that expected `api_key`/`provider` in responses (`tests/test_api.py::test_provider_upsert_and_list` (asserts `api_key == "sk"`), `test_resolve_returns_chain` (asserts `api_key == "sk"` and `provider`), `tests/test_mcp.py::test_mcp_resolve_purpose`). These are **changed** (not only added-to) because the contract reverses from exposing to withholding secrets and the redundant split.

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
            "api_key": "sk",
        },
    )
    assert r.status_code == 200
    return r.json()


def test_provider_list_does_not_leak_api_key(client):
    _seed_provider(client)
    body = client.get("/api/providers").json()
    assert body[0]["prefix"] == "openai"
    assert "api_key" not in body[0]


def test_auth_enforced_when_keys_configured(isolated_db):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("LLM_ROUTER_API_KEYS", "secret-key-1,secret-key-2")
    try:
        client = TestClient(create_app())
        assert client.get("/api/providers").status_code == 401
        assert (
            client.get(
                "/api/providers", headers={"X-API-Key": "wrong-key"}
            ).status_code
            == 401
        )
        assert (
            client.get(
                "/api/providers", headers={"X-API-Key": "secret-key-1"}
            ).status_code
            == 200
        )
    finally:
        monkeypatch.undo()


def test_resolve_returns_sanitized_chain(client):
    _seed_provider(client)
    client.put(
        "/api/assignments/acp:chat",
        json={"key": "acp:chat", "owner": "acp", "chain": ["openai/gpt-4o-mini"]},
    )
    r = client.get("/api/resolve/acp:chat")
    assert r.status_code == 200
    body = r.json()
    assert body["purpose"] == "acp:chat"
    assert body["chain"][0]["prefix"] == "openai"      # single identifier
    assert "provider" not in body["chain"][0]          # no redundant split
    assert body["chain"][0]["model"] == "gpt-4o-mini"
    assert "api_key" not in body["chain"][0]


def test_catalog_does_not_leak_api_key(client):
    _seed_provider(client)
    body = client.get("/api/catalog").json()
    assert body["providers"][0]["prefix"] == "openai"
    assert "api_key" not in body["providers"][0]
```

```python
# [MODIFY] tests/test_client.py  (in /topdata/llm-router-client) — client sends X-API-Key; tolerates keyless response
```
```python
from llm_router_client.config import router_url

def test_resolve_chain_sends_x_api_key(monkeypatch):
    seen = {}

    def handler(request):
        seen["header"] = request.headers.get("X-API-Key")
        return httpx.Response(
            200,
            json={
                "purpose": "demo:job",
                "chain": [
                    {"prefix": "openai", "model": "gpt-4o-mini",
                     "base_url": "http://x"}  # minimal contract: no api_key, no provider
                ],
            },
        )

    clear_cache()
    monkeypatch.setenv("LLM_ROUTER_API_KEY", "client-key-1")
    chain = resolve_chain(
        "demo:job", base_url="http://router", use_cache=False,
        transport=_transport(handler),
    )
    assert seen["header"] == "client-key-1"
    assert chain[0].api_key is None           # resolved key is local, not wire
    assert chain[0].prefix == "openai"
    assert chain[0].provider == "openai"      # provided is derived from prefix
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
1. Update `llm-router` README.md reflecting:
   - `X-API-Key` router security configuration (`LLM_ROUTER_API_KEYS`).
   - The **minimal resolve contract** (`{prefix, model, base_url}`) — clients own naming/credentials.
   - Pointer to the separate `llm-router-client` repo for consumption.
2. Update the new `llm-router-client` README.md: local credential resolution (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, ...), `X-API-Key` send, PydanticAI usage examples, fallback engine.
3. Update both `CHANGELOG.md` files with the new auth/security/contract/split features.
4. Verify test suites **in both repos**: `uv run pytest` in `/topdata/llm-router` and `/topdata/llm-router-client`.
5. Update the `llm-router` config.py module docstring (currently claims "no auth / no TLS, single admin, trusted LAN") to reflect the new auth posture.

```markdown
# [MODIFY] /topdata/llm-router/README.md
```
*(Add `X-API-Key` setup instructions, minimal-contract docs, and a pointer to `/topdata/llm-router-client` for consumers.)*

---

### Phase 7: Implementation Report Generation

Write the final implementation report to:
`_ai/backlog/reports/260902_0757__IMPLEMENTATION_REPORT__x_api_key_auth_and_local_credential_resolution.md`

(The report lives in the `llm-router` repo; a companion report for the `llm-router-client` repo and the `digester` consumer should be referenced, since the change spans three repos — Phase 0 split, router auth/contract, client credentials, consumer migration.)

YAML Frontmatter required:
```yaml
---
filename: "_ai/backlog/reports/260902_0757__IMPLEMENTATION_REPORT__x_api_key_auth_and_local_credential_resolution.md"
title: "Report: X-API-Key Router Auth, Client-Side Local Credentials & Client Repo Split"
createdAt: 2026-09-02 08:30
updatedAt: 2026-09-02 08:30
planFile: "_ai/backlog/active/260902_0757__IMPLEMENTATION_PLAN__x_api_key_auth_and_local_credential_resolution.md"
project: "llm-router"
status: completed
filesCreated: 2
filesModified: 6
filesDeleted: 0
consumerUpdates: ["digester -> /topdata/llm-router-client"]
tags: [security, x-api-key, auth, pydantic-ai, llm-router-client, local-credentials]
documentType: IMPLEMENTATION_REPORT
---
```

---

### Phase 8: Update the Existing Consumer (`digester`)

#### Objective:
Migrate `digester` — the only fleet member actually consuming the router today — onto the new client repo, the auth model, and the minimal contract. This must land **in the same release** as Phases 2–4 (atomic migration) so no consumer loses a key or reads a removed field.

#### Context (verified today):
- Dependency: `pyproject.toml` has `llm-router = { path = "/home/marc/devel/llm-router" }` — the whole server package, for a client-only consumer.
- Usages:
  - `src/config.py:51` — `from llm_router_client.pydantic_ai import router_model; return router_model(_purpose(task))`
  - `src/config.py:61` — `from llm_router_client.client import resolve_chain; entry = resolve_chain(_purpose(task))[0]; return f"{entry.provider}/{entry.model}"` (`model_label`)
  - `tests/conftest.py:31-38` — stubs `llm_router_client.client.resolve_chain` and `llm_router_client.pydantic_ai.router_model` with a fake `ModelConfig(provider="test", ..., api_key=None)`.
- No `LLM_ROUTER_API_KEY` / `LLM_ROUTER_URL` set today; no `.env` present.

#### Tasks:
1. **Repo path**: `pyproject.toml` → `llm-router-client = { path = "/topdata/llm-router-client" }`. The `llm_router_client` import namespace is unchanged, so no import edits are needed in `src/`.
2. **Add router auth env**: document/provide `LLM_ROUTER_API_KEY` (and confirm `LLM_ROUTER_URL`) in digester's runtime environment / docs. The client reads it via `router_api_key()`.
3. **Add provider key envs**: the server no longer sends `api_key`; `digester` relies on the client's `get_local_api_key` → `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/... from the caller env. Ensure those vars are set wherever digester runs.
4. **Verify field compatibility**: `ModelConfig` now derives `provider` from `prefix` — `model_label()` still returns `f"{entry.provider}/{entry.model}"` which reads the derived `provider` (= old behavior). No change required, but assert in tests.
5. **Add provider extras** if digester's assignments use Anthropic/Gemini: `uv add "llm-router-client[anthropic]"` etc.
6. **Tests**: update `tests/conftest.py` if the fake `ModelConfig` needs a `prefix` (the new class keeps `prefix` defaulting, so existing fake still constructs); add a test asserting `get_model(task)` reads a local key (e.g. monkeypatch `OPENAI_API_KEY`) — no network needed (client stubs).
7. **Run**: `uv run pytest` in digester green; `uv run digester summary ...` smoke test against a local router with auth enabled.

#### Compatibility note:
`fallback.with_fallbacks` (`resolve_raw`) attaches local keys to each `ModelConfig` before calling `call_fn` — digester's callbacks are unchanged. Direct `resolve_chain` callers (digester's `model_label`) get `api_key=None` (they only use provider/model — fine).

