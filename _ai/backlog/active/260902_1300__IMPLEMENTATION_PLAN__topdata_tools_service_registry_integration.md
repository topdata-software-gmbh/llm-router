---
filename: "_ai/backlog/active/260902_1300__IMPLEMENTATION_PLAN__topdata_tools_service_registry_integration.md"
title: "LLM Router Topdata-Tools Service Registry Integration"
createdAt: 2026-09-02 13:00
updatedAt: 2026-09-02 13:00
status: draft
priority: high
tags: [llm-router, topdata-tools, service-registry, auth, healthcheck, cli]
estimatedComplexity: moderate
documentRevision: 1
documentType: IMPLEMENTATION_PLAN
---

# Implementation Plan: LLM Router Topdata-Tools Service Registry Integration

## 1. Problem Description

The llm-router service exists at `/topdata/llm-router` on port 8202 but is not registered in the topdata-tools service registry (`topdata-tools/src/tt/core/service_registry.py`). This means:

1. **No health monitoring**: `tt health` and `tt auth check` commands don't include llm-router
2. **No API key validation**: No way to verify llm-router API keys via the unified `tt auth check` command
3. **Inconsistent with other services**: All other topdata microservices (package-service, site-service, backup-service, customer-showroom, nodes-service) are registered
4. **Missing health endpoint**: llm-router doesn't expose a `/healthz` endpoint for keyless liveness checks

## 2. Executive Summary

This plan integrates llm-router into the topdata-tools service registry by:

1. Adding a `/healthz` health check endpoint to llm-router
2. Registering llm-router in the topdata-tools service registry with correct port (8202)
3. Adding `llm_router_url` and `llm_router_api_key` settings to topdata-tools config
4. Updating documentation and changelogs for both projects

The integration follows the established pattern used by all other topdata microservices, ensuring consistency across the fleet.

## 3. Project Environment Details

### llm-router (Backend)
- **Project Name**: llm-router
- **Backend root**: `/topdata/llm-router/src/llm_router`
- **Python Version**: 3.12+ (managed by `uv`)
- **Port**: 8202
- **Key Dependencies**: FastAPI, SQLModel, Typer, Rich

### topdata-tools (CLI)
- **Project Name**: topdata-tools
- **CLI root**: `/topdata/topdata-tools/src/tt`
- **Python Version**: 3.12+ (managed by `uv`)
- **Key Dependencies**: Typer, Rich, HTTPX

---

## 4. Phased Implementation Plan

### Phase 1: Add Health Check Endpoint to llm-router

#### Objective:
Add a `/healthz` endpoint that returns service liveness without requiring authentication.

```python
# [NEW FILE] src/llm_router/routers/health.py
```
```python
"""Health check endpoint for liveness probes.

This endpoint does NOT require authentication and is used by
topdata-tools `tt health` for service availability checks.
"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    """Return service liveness status (no auth required)."""
    return {"status": "ok", "service": "llm-router"}
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
from .routers import assignments, health, models, providers, resolve, scan


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
    # Health check endpoint - no auth required (registered first, outside dependency)
    app.include_router(health.router)
    # Authenticated endpoints
    app.include_router(providers.router)
    app.include_router(models.router)
    app.include_router(assignments.router)
    app.include_router(resolve.router)
    app.include_router(scan.router)
    return app


app = create_app()
```

#### Constraints:
- The `/healthz` endpoint must NOT require authentication
- It must be registered before authenticated routes to avoid the dependency
- Response must be minimal JSON for fast parsing

---

### Phase 2: Register llm-router in topdata-tools Service Registry

#### Objective:
Add llm-router to the service registry with the correct port (8202) and health/probe paths.

```python
# [MODIFY] /topdata/topdata-tools/src/tt/core/service_registry.py
```
```python
"""Registry of Topdata microservices for cross-cutting diagnostics.

Drives ``tt health`` (keyless liveness) and ``tt auth`` (key validity) without
hardcoding the service list in the command modules (Open/Closed: add a service
by appending one ``ServiceSpec``).
"""

from __future__ import annotations

from dataclasses import dataclass

from tt.config import Settings


@dataclass(frozen=True)
class ServiceSpec:
    """Declarative description of a microservice for diagnostics."""

    name: str
    url_setting: str  # attribute name on Settings
    key_setting: str  # attribute name on Settings
    health_path: str  # keyless liveness path
    probe_path: str  # authenticated path used to validate the API key


# Printed top-to-bottom in diagnostic tables.
SERVICE_REGISTRY: tuple[ServiceSpec, ...] = (
    ServiceSpec(
        name="package-service",
        url_setting="package_service_url",
        key_setting="package_service_api_key",
        health_path="/healthz",
        probe_path="/api/v1/catalog",
    ),
    ServiceSpec(
        name="site-service",
        url_setting="site_service_url",
        key_setting="site_service_api_key",
        health_path="/healthz",
        probe_path="/api/v1/sites/__probe__",
    ),
    ServiceSpec(
        name="backup-service",
        url_setting="backup_service_url",
        key_setting="backup_service_api_key",
        health_path="/",
        probe_path="/api/v1/backups/__probe__/runs",
    ),
    ServiceSpec(
        name="customer-showroom",
        url_setting="customer_showroom_url",
        key_setting="customer_showroom_api_key",
        health_path="/",
        probe_path="/api/customers",
    ),
    ServiceSpec(
        name="nodes-service",
        url_setting="nodes_service_url",
        key_setting="nodes_service_api_key",
        health_path="/healthz",
        probe_path="/nodes",
    ),
    ServiceSpec(
        name="llm-router",
        url_setting="llm_router_url",
        key_setting="llm_router_api_key",
        health_path="/healthz",
        probe_path="/api/providers",
    ),
)


def get_spec(name: str) -> ServiceSpec:
    for spec in SERVICE_REGISTRY:
        if spec.name == name:
            return spec
    raise KeyError(f"unknown service: {name}")


def resolve_url(settings: Settings, spec: ServiceSpec) -> str:
    return str(getattr(settings, spec.url_setting))


def resolve_key(settings: Settings, spec: ServiceSpec) -> str:
    return str(getattr(settings, spec.key_setting))
```

---

### Phase 3: Add llm-router Settings to topdata-tools Config

#### Objective:
Add `llm_router_url` and `llm_router_api_key` settings with environment variable support.

```python
# [MODIFY] /topdata/topdata-tools/src/tt/config.py
```
```python
"""Central CLI settings and runtime environment configuration.

All hardcoded local dev machine facts (Docker container names, DB
credentials, file paths) live here so they are visible, documented and
overridable via ``TT_*`` environment variables.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

CLI_CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    """Runtime environment of the Topdata dev machine.

    Every field has a sane default matching the historical scripts and
    can be overridden with a ``TT_*`` environment variable.
    """

    mariadb_focus: str = "focus-mariadb"
    mariadb_sw67: str = "sw67-mariadb"
    www_sw67: str = "sw67-www"
    mariadb_cm: str = "cm-mariadb-main"
    www_cm: str = "cm-www"
    db_root_password: str = "11111"
    cm_compose_file: Path = Path("/btr/cm-docker/docker-compose.yaml")
    sw_bind_state: Path = Path("~/.sw-bind-state").expanduser()
    plugin_base: Path = Path("/topdata/sw6-plugins")
    mounts_conf: Path = PROJECT_ROOT / "misc" / "mount-sites.conf"
    ip_mapping_api_url: str = "https://api.topinfra.de/ip-mapping"
    ip_mapping_cache_file: Path = Path(
        "~/.cache/topdata/ip-mapping-cache.json"
    ).expanduser()
    ip_mapping_cache_ttl: int = 3600
    topinfra_api_key: str = ""
    wrapped_dir: Path = PROJECT_ROOT / "wrapped-scripts"
    mproc_dir: Path = PROJECT_ROOT / "misc" / "mproc"
    mproc_bin: str = "mprocs"
    # --- microservice operator clients (unified TT_* convention) ---
    package_service_url: str = "http://localhost:8200"
    package_service_api_key: str = ""
    site_service_url: str = "http://localhost:8211"
    site_service_api_key: str = ""
    backup_service_url: str = "http://localhost:8212"
    backup_service_api_key: str = ""
    customer_showroom_url: str = "http://localhost:8201"
    customer_showroom_api_key: str = ""
    nodes_service_url: str = "http://localhost:8210"
    nodes_service_api_key: str = ""
    llm_router_url: str = "http://localhost:8202"
    llm_router_api_key: str = ""
    site_service_sites_dir: Path = PROJECT_ROOT / "misc" / "sites"
    docs_dir: Path = PROJECT_ROOT / "docs"
    config_dir: Path = Path("~/.config/tt").expanduser()
    skeleton_theme_template: Path = Path("/topdata/topdata-theme-template-sw6")
    skeleton_output_dir: Path = Path(".")

    @property
    def config_file(self) -> Path:
        """Location of the tt config.toml (holds the ``[ui]`` section)."""
        return self.config_dir / "config.toml"


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build :class:`Settings`, preferring ``TT_*`` env vars over defaults."""
    env = os.environ if env is None else env
    return Settings(
        mariadb_focus=env.get("TT_MARIADB_FOCUS", "focus-mariadb"),
        mariadb_sw67=env.get("TT_MARIADB_SW67", "sw67-mariadb"),
        www_sw67=env.get("TT_WWW_SW67", "sw67-www"),
        mariadb_cm=env.get("TT_MARIADB_CM", "cm-mariadb-main"),
        www_cm=env.get("TT_WWW_CM", "cm-www"),
        db_root_password=env.get("TT_DB_PASSWORD", "11111"),
        cm_compose_file=Path(
            env.get("TT_CM_COMPOSE_FILE", "/btr/cm-docker/docker-compose.yaml")
        ),
        sw_bind_state=Path(
            env.get("TT_SW_BIND_STATE", "~/.sw-bind-state")
        ).expanduser(),
        plugin_base=Path(env.get("TT_PLUGIN_BASE", "/topdata/sw6-plugins")),
        mounts_conf=Path(
            env.get("TT_MOUNTS_CONF", str(PROJECT_ROOT / "misc" / "mount-sites.conf"))
        ),
        ip_mapping_api_url=env.get(
            "TT_IP_MAPPING_API_URL", "https://api.topinfra.de/ip-mapping"
        ),
        ip_mapping_cache_file=Path(
            env.get(
                "TT_IP_MAPPING_CACHE",
                str(Path("~/.cache/topdata/ip-mapping-cache.json").expanduser()),
            )
        ).expanduser(),
        ip_mapping_cache_ttl=int(env.get("TT_IP_MAPPING_TTL", "3600")),
        topinfra_api_key=env.get(
            "TT_TOPINFRA_API_KEY", env.get("TOPINFRA_API_KEY", "")
        ),
        wrapped_dir=Path(
            env.get("TT_WRAPPED_DIR", str(PROJECT_ROOT / "wrapped-scripts"))
        ),
        mproc_dir=Path(env.get("TT_MPROC_DIR", str(PROJECT_ROOT / "misc" / "mproc"))),
        mproc_bin=env.get("TT_MPROC_BIN", "mprocs"),
        package_service_url=env.get("TT_PACKAGE_SERVICE_URL", "http://localhost:8200"),
        package_service_api_key=env.get("TT_PACKAGE_SERVICE_API_KEY", ""),
        site_service_url=env.get("TT_SITE_SERVICE_URL", "http://localhost:8211"),
        site_service_api_key=env.get("TT_SITE_SERVICE_API_KEY", ""),
        backup_service_url=env.get("TT_BACKUP_SERVICE_URL", "http://localhost:8212"),
        backup_service_api_key=env.get("TT_BACKUP_SERVICE_API_KEY", ""),
        customer_showroom_url=env.get(
            "TT_CUSTOMER_SHOWROOM_URL", "http://localhost:8201"
        ),
        customer_showroom_api_key=env.get("TT_CUSTOMER_SHOWROOM_API_KEY", ""),
        nodes_service_url=env.get("TT_NODES_SERVICE_URL", "http://localhost:8210"),
        nodes_service_api_key=env.get("TT_NODES_SERVICE_API_KEY", ""),
        llm_router_url=env.get("TT_LLM_ROUTER_URL", "http://localhost:8202"),
        llm_router_api_key=env.get("TT_LLM_ROUTER_API_KEY", ""),
        site_service_sites_dir=Path(
            env.get("TT_SITE_SERVICE_SITES_DIR", str(PROJECT_ROOT / "misc" / "sites"))
        ),
        docs_dir=Path(env.get("TT_DOCS_DIR", str(PROJECT_ROOT / "docs"))),
        config_dir=Path(
            env.get("TT_CONFIG_DIR", str(Path("~/.config/tt").expanduser()))
        ).expanduser(),
        skeleton_theme_template=Path(
            env.get("TT_THEME_TEMPLATE_PATH", "/topdata/topdata-theme-template-sw6")
        ),
        skeleton_output_dir=Path(env.get("TT_SKELETON_OUTPUT_DIR", ".")),
    )


def load_config() -> dict[str, object]:
    """Parse the tt config.toml (``[ui]`` section etc.) via :class:`Settings`.

    A missing file yields ``{}``; an invalid TOML file raises
    :class:`tomllib.TOMLDecodeError` so misconfiguration fails loudly instead
    of silently using defaults.
    """
    path = load_settings().config_file
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)
```

---

### Phase 4: Testing

#### Objective:
Add tests for the new health check endpoint and verify service registry integration.

```python
# [NEW FILE] /topdata/llm-router/tests/test_health.py
```
```python
"""Tests for health check endpoint."""

from fastapi.testclient import TestClient


def test_healthz_returns_ok(client: TestClient):
    """Health endpoint should return 200 with status ok."""
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "llm-router"


def test_healthz_no_auth_required(client: TestClient):
    """Health endpoint should work without X-API-Key header."""
    response = client.get("/healthz")
    assert response.status_code == 200
```

```python
# [NEW FILE] /topdata/topdata-tools/tests/test_service_registry.py
```
```python
"""Tests for service registry including llm-router."""

from tt.core.service_registry import SERVICE_REGISTRY, get_spec, resolve_key, resolve_url
from tt.config import Settings


def test_llm_router_in_registry():
    """llm-router should be registered in SERVICE_REGISTRY."""
    names = [spec.name for spec in SERVICE_REGISTRY]
    assert "llm-router" in names


def test_llm_router_spec_values():
    """llm-router spec should have correct settings."""
    spec = get_spec("llm-router")
    assert spec.url_setting == "llm_router_url"
    assert spec.key_setting == "llm_router_api_key"
    assert spec.health_path == "/healthz"
    assert spec.probe_path == "/api/providers"


def test_llm_router_default_url():
    """Default llm-router URL should be localhost:8202."""
    settings = Settings()
    assert settings.llm_router_url == "http://localhost:8202"


def test_llm_router_env_override(monkeypatch):
    """TT_LLM_ROUTER_URL env var should override default."""
    monkeypatch.setenv("TT_LLM_ROUTER_URL", "http://custom:9999")
    settings = Settings()
    assert settings.llm_router_url == "http://custom:9999"


def test_resolve_llm_router_url():
    """resolve_url should return the configured URL for llm-router."""
    settings = Settings()
    spec = get_spec("llm-router")
    url = resolve_url(settings, spec)
    assert url == "http://localhost:8202"
```

---

### Phase 5: Project Housekeeping

#### Objective:
Update documentation and changelogs for both projects.

```markdown
# [MODIFY] /topdata/llm-router/README.md
```

Add a "Health Check" section documenting the `/healthz` endpoint:

```markdown
## Health Check

The service exposes a `/healthz` endpoint for liveness probes that does not require authentication:

```bash
curl http://localhost:8202/healthz
# {"status":"ok","service":"llm-router"}
```

This endpoint is used by `topdata-tools` for service availability monitoring.
```

```markdown
# [MODIFY] /topdata/llm-router/CHANGELOG.md
```

Add entry for health check endpoint:

```markdown
## [Unreleased]

### Added
- `/healthz` health check endpoint for service liveness probes (no auth required)
- Integration with topdata-tools service registry
```

```markdown
# [MODIFY] /topdata/topdata-tools/CHANGELOG.md
```

Add entry for llm-router registration:

```markdown
## [Unreleased]

### Added
- `llm-router` to service registry (`tt health`, `tt auth check`)
- `llm_router_url` and `llm_router_api_key` settings
- Environment variables: `TT_LLM_ROUTER_URL`, `TT_LLM_ROUTER_API_KEY`
```

---

## 5. Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TT_LLM_ROUTER_URL` | `http://localhost:8202` | llm-router service URL |
| `TT_LLM_ROUTER_API_KEY` | `""` | API key for authenticating with llm-router |

### Setting the API Key

```bash
# Option 1: Environment variable
export TT_LLM_ROUTER_API_KEY="sk-llmr-..."

# Option 2: In ~/.config/tt/config.toml (if implemented)
[llm_router]
url = "http://localhost:8202"
api_key = "sk-llmr-..."
```

---

## 6. Usage Examples

### Check llm-router Health

```bash
tt health
```

Expected output:

```
┌─────────────────┬─────────┬─────────┐
│ Service         │ Health  │ Auth    │
├─────────────────┼─────────┼─────────┤
│ package-service │ ok      │ ok      │
│ site-service    │ ok      │ ok      │
│ backup-service  │ ok      │ ok      │
│ llm-router      │ ok      │ ok      │  ← NEW
└─────────────────┴─────────┴─────────┘
```

### Validate llm-router API Key

```bash
tt auth check
```

Expected output (with valid key):

```
┌─────────────────┬───────────┬─────────┐
│ Service         │ Key set   │ Result  │
├─────────────────┼───────────┼─────────┤
│ package-service │ yes       │ ok      │
│ llm-router      │ yes       │ ok      │  ← NEW
└─────────────────┴───────────┴─────────┘
```

### Direct Health Check

```bash
# Without authentication
curl http://localhost:8202/healthz
# {"status":"ok","service":"llm-router"}

# With authentication (for other endpoints)
curl -H "X-API-Key: $TT_LLM_ROUTER_API_KEY" http://localhost:8202/api/providers
```

---

## 7. Implementation Report

Write the final implementation report to:

`_ai/backlog/reports/260902_1300__IMPLEMENTATION_REPORT__topdata_tools_service_registry_integration.md`

YAML Frontmatter required:

```yaml
---
filename: "_ai/backlog/reports/260902_1300__IMPLEMENTATION_REPORT__topdata_tools_service_registry_integration.md"
title: "Report: LLM Router Topdata-Tools Service Registry Integration"
createdAt: 2026-09-02 13:00
updatedAt: 2026-09-02 13:00
planFile: "_ai/backlog/active/260902_1300__IMPLEMENTATION_PLAN__topdata_tools_service_registry_integration.md"
project: "llm-router"
status: completed
filesCreated: 3
filesModified: 5
filesDeleted: 0
tags: [llm-router, topdata-tools, service-registry, auth, healthcheck]
documentType: IMPLEMENTATION_REPORT
---
```

---

## 8. Dependencies

### llm-router (no new dependencies)
- Already has FastAPI, SQLModel, Typer

### topdata-tools (no new dependencies)
- Already has HTTPX, Typer for service client calls

---

## 9. Rollback Plan

If issues arise:

1. **Remove health endpoint**: Delete `/topdata/llm-router/src/llm_router/routers/health.py` and revert `main.py`
2. **Remove from registry**: Delete llm-router entry from `service_registry.py`
3. **Remove settings**: Delete `llm_router_url` and `llm_router_api_key` from `config.py`

No database migrations required. No breaking changes to existing functionality.

---

## 10. Success Criteria

- [ ] `/healthz` endpoint returns 200 without authentication
- [ ] `tt health` shows llm-router as "ok"
- [ ] `tt auth check` validates llm-router API key
- [ ] `TT_LLM_ROUTER_URL` and `TT_LLM_ROUTER_API_KEY` env vars work
- [ ] All existing tests pass
- [ ] New tests added and passing
- [ ] Documentation updated
