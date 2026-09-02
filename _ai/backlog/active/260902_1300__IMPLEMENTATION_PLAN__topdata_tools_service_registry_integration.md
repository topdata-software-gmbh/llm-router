---
filename: "_ai/backlog/active/260902_1300__IMPLEMENTATION_PLAN__topdata_tools_service_registry_integration.md"
title: "LLM Router Topdata-Tools Service Registry Integration"
createdAt: 2026-09-02 13:00
updatedAt: 2026-09-02 13:00
status: draft
priority: high
tags: [llm-router, topdata-tools, service-registry, auth, healthcheck, cli, api-keys]
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
2. Adding a `llm-router key` CLI command for managing API keys (local DB access only, **no API endpoint**)
3. Registering llm-router in the topdata-tools service registry with correct port (8202)
4. Adding `llm_router_url` and `llm_router_api_key` settings to topdata-tools config
5. Updating documentation and changelogs for both projects

**Security Design**: API keys are managed exclusively via local CLI with direct database access. There is **NO API endpoint** for creating, listing, or revoking keys. This prevents remote key management and ensures keys are only created by administrators with direct server access.

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

### Phase 1b: Database Migration for ApiKey Table

#### Objective:
Create an Alembic migration to add the `api_key` table.

```python
# [NEW FILE] alembic/versions/xxxx_add_api_key_table.py
```
```python
"""Add api_key table for router authentication.

Revision ID: xxxx
Revises: 6096a058cfab
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers
revision = "xxxx"
down_revision = "6096a058cfab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_key",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("prefix", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_api_key_key_hash"), "api_key", ["key_hash"], unique=True)
    op.create_index(op.f("ix_api_key_prefix"), "api_key", ["prefix"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_api_key_prefix"), table_name="api_key")
    op.drop_index(op.f("ix_api_key_key_hash"), table_name="api_key")
    op.drop_table("api_key")
```

---

### Phase 2: Add API Key Management CLI (Local DB Access Only)

#### Objective:
Add a `llm-router key` CLI command for managing API keys directly in the database. **No API endpoint** - keys are managed exclusively via local CLI.

#### Security Design:
- Keys are stored **hashed** (SHA-256) in the database, never plaintext
- Only the hash is stored; the raw key is shown once on creation
- CLI requires direct database access (no remote key management)
- Keys follow the format `sk-llmr-<random>` for easy identification

```python
# [NEW FILE] src/llm_router/models.py (add to existing file)
```
```python
"""SQLModel ORM models for the llm-router.

Four tables:

- ``Provider``: an LLM endpoint (cloud or local) with its own base URL and
  (for cloud) API key. The ``prefix`` is the short key used in chain entries
  as ``prefix/model``.
- ``Model``: a model id belonging to a provider. This is the *detected
  catalog* — populated by ``scan`` and manual adds; it is what a management UI
  can pick from.
- ``Assignment``: maps a purpose key (``project:job``, e.g. ``git-digest:digest``)
  to an ordered chain of ``provider/model`` strings, stored as JSON text.
- ``ApiKey``: stores hashed API keys for authenticating to the router.
  Keys are hashed with SHA-256; the raw key is shown once on creation.

``Assignment.chain`` is intentionally **not** FK-constrained to ``Model``: an
assignment may reference a model that is not (yet) in the detected catalog.
The provider is looked up by prefix during resolution.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Provider(SQLModel, table=True):
    __tablename__ = "provider"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    prefix: str = Field(index=True, unique=True)
    base_url: str
    api_key: Optional[str] = None
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Model(SQLModel, table=True):
    __tablename__ = "model"

    id: Optional[int] = Field(default=None, primary_key=True)
    provider_id: int = Field(foreign_key="provider.id", index=True)
    model: str = Field(index=True)
    display_name: Optional[str] = None
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Assignment(SQLModel, table=True):
    __tablename__ = "assignment"

    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)
    owner: str = Field(index=True)
    description: Optional[str] = None
    chain: str = Field(default="[]")
    active: bool = True
    updated_at: datetime = Field(default_factory=utcnow)


class ApiKey(SQLModel, table=True):
    """Stores hashed API keys for router authentication.

    The raw key is only shown once on creation. The hash is stored
    for verification. Keys follow the format ``sk-llmr-<random>``.
    """

    __tablename__ = "api_key"

    id: Optional[int] = Field(default=None, primary_key=True)
    key_hash: str = Field(index=True, unique=True)
    prefix: str = Field(index=True)  # First 8 chars for display: "sk-llmr-..."
    name: Optional[str] = None  # Optional label for the key
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)
    last_used_at: Optional[datetime] = None
```

```python
# [NEW FILE] src/llm_router/core/api_key.py
```
```python
"""API key management with secure hashing.

Keys are stored as SHA-256 hashes. The raw key is only shown once
on creation. This module provides functions for creating, verifying,
and managing API keys.
"""

import hashlib
import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from ..models import ApiKey


KEY_PREFIX = "sk-llmr-"
KEY_LENGTH = 48  # Total length including prefix


def _generate_random_string(length: int) -> str:
    """Generate a cryptographically secure random string."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_api_key() -> str:
    """Generate a new API key in the format ``sk-llmr-<random>``.

    Returns:
        The raw API key string (shown once, never stored).
    """
    random_part = _generate_random_string(KEY_LENGTH - len(KEY_PREFIX))
    return f"{KEY_PREFIX}{random_part}"


def hash_api_key(raw_key: str) -> str:
    """Hash an API key using SHA-256.

    Args:
        raw_key: The raw API key string.

    Returns:
        The hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(raw_key.encode()).hexdigest()


def create_api_key(
    session: Session,
    name: Optional[str] = None,
) -> tuple[str, ApiKey]:
    """Create a new API key and store its hash in the database.

    Args:
        session: Database session.
        name: Optional label for the key (e.g., "digester-prod").

    Returns:
        Tuple of (raw_key, api_key_model). The raw key is shown once
        and cannot be retrieved later.
    """
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    prefix = raw_key[:8] + "..."  # "sk-llmr-..."

    api_key = ApiKey(
        key_hash=key_hash,
        prefix=prefix,
        name=name,
        active=True,
    )
    session.add(api_key)
    session.commit()
    session.refresh(api_key)

    return raw_key, api_key


def verify_api_key(session: Session, raw_key: str) -> bool:
    """Verify an API key against stored hashes.

    Args:
        session: Database session.
        raw_key: The raw API key to verify.

    Returns:
        True if the key is valid and active, False otherwise.
    """
    key_hash = hash_api_key(raw_key)
    statement = select(ApiKey).where(
        ApiKey.key_hash == key_hash,
        ApiKey.active == True,  # noqa: E712
    )
    api_key = session.exec(statement).first()

    if api_key is None:
        return False

    # Update last_used_at
    api_key.last_used_at = datetime.now(timezone.utc)
    session.add(api_key)
    session.commit()

    return True


def list_api_keys(session: Session) -> list[ApiKey]:
    """List all API keys (without revealing hashes).

    Args:
        session: Database session.

    Returns:
        List of ApiKey models.
    """
    return session.exec(select(ApiKey).order_by(ApiKey.created_at)).all()


def revoke_api_key(session: Session, key_id: int) -> bool:
    """Revoke an API key by setting it inactive.

    Args:
        session: Database session.
        key_id: The ID of the key to revoke.

    Returns:
        True if the key was found and revoked, False otherwise.
    """
    api_key = session.get(ApiKey, key_id)
    if api_key is None:
        return False

    api_key.active = False
    session.add(api_key)
    session.commit()
    return True


def delete_api_key(session: Session, key_id: int) -> bool:
    """Permanently delete an API key from the database.

    Args:
        session: Database session.
        key_id: The ID of the key to delete.

    Returns:
        True if the key was found and deleted, False otherwise.
    """
    api_key = session.get(ApiKey, key_id)
    if api_key is None:
        return False

    session.delete(api_key)
    session.commit()
    return True
```

```python
# [NEW FILE] src/llm_router/commands/key_cmd.py
```
```python
"""`llm-router key` — manage API keys for router authentication.

Keys are managed exclusively via this local CLI with direct database access.
There is NO API endpoint for key management (security design).
"""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..config import CLI_CONTEXT_SETTINGS
from ._common import console, get_session

app = typer.Typer(
    name="key",
    context_settings=CLI_CONTEXT_SETTINGS,
    no_args_is_help=True,
)


@app.command("generate")
def key_generate(
    name: Optional[str] = typer.Option(
        None, "--name", "-n", help="Optional label for the key"
    ),
):
    """Generate a new API key.

    The raw key is shown ONCE and cannot be retrieved later.
    Store it securely (e.g., in ~/.config/tt or environment variables).
    """
    from ..core.api_key import create_api_key

    with get_session() as session:
        raw_key, api_key = create_api_key(session, name=name)

    console.print("\n[green]✓ API key created successfully![/green]\n")
    console.print("[bold]Save this key now - it will NOT be shown again:[/bold]\n")
    console.print(f"  [cyan]{raw_key}[/cyan]\n")
    console.print(f"  Key ID:    {api_key.id}")
    console.print(f"  Prefix:    {api_key.prefix}")
    if api_key.name:
        console.print(f"  Name:      {api_key.name}")
    console.print()


@app.command("list")
def key_list():
    """List all registered API keys (without revealing full keys)."""
    from ..core.api_key import list_api_keys

    with get_session() as session:
        keys = list_api_keys(session)

    if not keys:
        console.print("[yellow]No API keys registered.[/yellow]")
        console.print("Generate one with: llm-router key generate")
        return

    table = Table(title="API Keys")
    table.add_column("ID", style="dim")
    table.add_column("Prefix", style="cyan")
    table.add_column("Name")
    table.add_column("Active")
    table.add_column("Created", style="dim")
    table.add_column("Last Used", style="dim")

    for key in keys:
        active_style = "green" if key.active else "red"
        active_text = "✓" if key.active else "✗"
        last_used = key.last_used_at.strftime("%Y-%m-%d %H:%M") if key.last_used_at else "never"

        table.add_row(
            str(key.id),
            key.prefix,
            key.name or "-",
            f"[{active_style}]{active_text}[/{active_style}]",
            key.created_at.strftime("%Y-%m-%d %H:%M"),
            last_used,
        )

    console.print(table)


@app.command("revoke")
def key_revoke(
    key_id: int = typer.Argument(..., help="ID of the key to revoke"),
    no_interaction: bool = typer.Option(
        False, "--no-interaction", "-n", help="Skip confirmation prompt"
    ),
):
    """Revoke an API key (sets it inactive, can be re-enabled)."""
    from ..core.api_key import revoke_api_key

    if not no_interaction:
        from ..utils import confirm

        if not confirm(f"Revoke API key {key_id}?", default=False):
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)

    with get_session() as session:
        success = revoke_api_key(session, key_id)

    if success:
        console.print(f"[green]✓ API key {key_id} revoked.[/green]")
    else:
        console.print(f"[red]✗ API key {key_id} not found.[/red]")
        raise typer.Exit(1)


@app.command("delete")
def key_delete(
    key_id: int = typer.Argument(..., help="ID of the key to permanently delete"),
    no_interaction: bool = typer.Option(
        False, "--no-interaction", "-n", help="Skip confirmation prompt"
    ),
):
    """Permanently delete an API key from the database.

    This is irreversible. Use `revoke` to temporarily disable a key.
    """
    from ..core.api_key import delete_api_key

    if not no_interaction:
        from ..utils import confirm

        if not confirm(
            f"PERMANENTLY delete API key {key_id}?\nThis cannot be undone.",
            default=False,
        ):
            console.print("[yellow]Aborted.[/yellow]")
            raise typer.Exit(0)

    with get_session() as session:
        success = delete_api_key(session, key_id)

    if success:
        console.print(f"[green]✓ API key {key_id} deleted.[/green]")
    else:
        console.print(f"[red]✗ API key {key_id} not found.[/red]")
        raise typer.Exit(1)
```

```python
# [MODIFY] src/llm_router/cli.py
```
```python
"""llm-router Typer CLI entry point.

Run ``llm-router --help`` (or ``-h``) for the available subcommands:
``scan``, ``provider``, ``assignment``, ``catalog``, ``resolve``, ``key``.
"""

import typer

from .commands import assignment_cmd, catalog_cmd, key_cmd, provider_cmd, scan_cmd
from .config import CLI_CONTEXT_SETTINGS

app = typer.Typer(
    name="llm-router",
    context_settings=CLI_CONTEXT_SETTINGS,
    no_args_is_help=True,
)

app.add_typer(scan_cmd.app, name="scan")
app.add_typer(provider_cmd.app, name="provider")
app.add_typer(assignment_cmd.app, name="assignment")
app.add_typer(catalog_cmd.app, name="catalog")
app.add_typer(key_cmd.app, name="key")


@app.command()
def resolve(purpose: str):
    """Resolve a purpose to its ordered provider/model connection chain.

    Example: llm-router resolve git-digest:digest
    """
    from .commands._common import get_session
    from .core.resolve import ResolveError, resolve_purpose

    with get_session() as session:
        try:
            chain = resolve_purpose(session, purpose)
        except ResolveError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from exc
    if chain is None:
        typer.echo(
            f"No assignment for purpose {purpose!r}. "
            f"Run `llm-router assignment set {purpose} <owner> <chain>`.",
            err=True,
        )
        raise typer.Exit(1)
    for entry in chain:
        typer.echo(
            f"{entry['provider']}/{entry['model']}  "
            f"[{entry['base_url']}] key={'yes' if entry['api_key'] else 'no'}"
        )


if __name__ == "__main__":
    app()
```

```python
# [MODIFY] src/llm_router/auth.py
```
```python
"""Authentication dependency verifying X-API-Key headers.

This module verifies API keys against the database of hashed keys.
Keys are managed via the local CLI only (no API for key management).
"""

from typing import Optional

from fastapi import Header, HTTPException, status
from sqlmodel import Session

from .core.api_key import verify_api_key as _verify_api_key
from .db import get_session


def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    session: Session = None,
) -> Optional[str]:
    """Verify that incoming request provides a valid X-API-Key.

    If no keys exist in the database, authentication is skipped
    to maintain zero-config local development backwards compatibility.

    Args:
        x_api_key: The X-API-Key header value.
        session: Database session (injected by FastAPI).

    Returns:
        The verified API key string.

    Raises:
        HTTPException: If the key is invalid or missing.
    """
    # Get a session if not provided (for backwards compatibility)
    if session is None:
        from .db import session_scope
        with session_scope() as s:
            return _verify_key(x_api_key, s)
    return _verify_key(x_api_key, session)


def _verify_key(x_api_key: Optional[str], session: Session) -> Optional[str]:
    """Internal verification logic."""
    from .models import ApiKey
    from sqlmodel import select

    # Check if any keys exist
    any_keys = session.exec(select(ApiKey).limit(1)).first()
    if any_keys is None:
        # No keys configured - dev mode, skip auth
        return x_api_key

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not _verify_api_key(session, x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return x_api_key
```

```python
# [NEW FILE] src/llm_router/utils.py
```
```python
"""Shared utilities for the llm-router CLI."""

import sys

from InquirerPy import inquirer, get_style


INQUIRER_CONFIRM_STYLE = get_style(
    {
        "question": "#ffffff bold",
        "pointer": "#FF9D00 bold",
        "highlighted": "#000000 bg:#FF9D00 bold",
        "instruction": "#808080",
        "text": "#ffffff",
    }
)

CONFIRM_CHOICES = [
    {"name": " Yes ", "value": True},
    {"name": " No  ", "value": False},
]


def confirm(message: str, default: bool = True) -> bool:
    """Ask a Yes/No question with a gum-style button UI.

    Falls back to `default` when no TTY is available (piped/CI input).
    """
    if not sys.stdin.isatty():
        return default
    return inquirer.select(
        message=message,
        choices=CONFIRM_CHOICES,
        default=" Yes " if default else " No  ",
        style=INQUIRER_CONFIRM_STYLE,
        qmark="",
        amark="",
    ).execute()
```

---

### Phase 3: Register llm-router in topdata-tools Service Registry

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
Add tests for health check endpoint, API key management, and service registry integration.

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
# [NEW FILE] /topdata/llm-router/tests/test_api_keys.py
```
```python
"""Tests for API key management (CLI and verification)."""

import pytest
from sqlmodel import Session

from llm_router.core.api_key import (
    create_api_key,
    delete_api_key,
    generate_api_key,
    hash_api_key,
    list_api_keys,
    revoke_api_key,
    verify_api_key,
)
from llm_router.models import ApiKey


def test_generate_api_key_format():
    """Generated key should have sk-llmr- prefix."""
    key = generate_api_key()
    assert key.startswith("sk-llmr-")
    assert len(key) == 48


def test_generate_api_key_unique():
    """Each generated key should be unique."""
    keys = {generate_api_key() for _ in range(100)}
    assert len(keys) == 100


def test_hash_api_key_deterministic():
    """Hashing the same key should produce the same hash."""
    key = "sk-llmr-test123"
    hash1 = hash_api_key(key)
    hash2 = hash_api_key(key)
    assert hash1 == hash2


def test_create_and_verify_api_key(session: Session):
    """Creating a key should allow verification."""
    raw_key, api_key = create_api_key(session, name="test-key")

    assert raw_key.startswith("sk-llmr-")
    assert api_key.name == "test-key"
    assert api_key.active is True

    # Verify the key
    assert verify_api_key(session, raw_key) is True


def test_verify_invalid_key(session: Session):
    """Invalid key should fail verification."""
    assert verify_api_key(session, "sk-llmr-invalid") is False


def test_verify_revoked_key(session: Session):
    """Revoked key should fail verification."""
    raw_key, api_key = create_api_key(session)
    revoke_api_key(session, api_key.id)

    assert verify_api_key(session, raw_key) is False


def test_list_api_keys(session: Session):
    """Should list all created keys."""
    create_api_key(session, name="key-1")
    create_api_key(session, name="key-2")

    keys = list_api_keys(session)
    assert len(keys) == 2
    assert keys[0].name == "key-1"
    assert keys[1].name == "key-2"


def test_revoke_api_key(session: Session):
    """Revoking a key should set it inactive."""
    raw_key, api_key = create_api_key(session)

    success = revoke_api_key(session, api_key.id)
    assert success is True

    # Refresh and check
    session.refresh(api_key)
    assert api_key.active is False


def test_delete_api_key(session: Session):
    """Deleting a key should remove it from the database."""
    _, api_key = create_api_key(session)
    key_id = api_key.id

    success = delete_api_key(session, key_id)
    assert success is True

    # Verify deleted
    assert session.get(ApiKey, key_id) is None


def test_revoke_nonexistent_key(session: Session):
    """Revoking a nonexistent key should return False."""
    success = revoke_api_key(session, 99999)
    assert success is False
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

Add sections for Health Check and API Key Management:

```markdown
## Health Check

The service exposes a `/healthz` endpoint for liveness probes that does not require authentication:

```bash
curl http://localhost:8202/healthz
# {"status":"ok","service":"llm-router"}
```

This endpoint is used by `topdata-tools` for service availability monitoring.

## API Key Management

API keys are managed exclusively via the local CLI with direct database access. There is **no API endpoint** for key management (security design).

### Generate a new key

```bash
llm-router key generate --name "digester-prod"
```

Output:
```
✓ API key created successfully!

Save this key now - it will NOT be shown again:

  sk-llmr-abc123xyz789...

  Key ID:    1
  Prefix:    sk-llmr-...
  Name:      digester-prod
```

### List all keys

```bash
llm-router key list
```

### Revoke a key

```bash
llm-router key revoke 1
```

### Delete a key (permanent)

```bash
llm-router key delete 1
```

### Using the key

Set the environment variable for clients:

```bash
export TT_LLM_ROUTER_API_KEY="sk-llmr-..."
```

Or use the header directly:

```bash
curl -H "X-API-Key: $TT_LLM_ROUTER_API_KEY" http://localhost:8202/api/providers
```
```

```markdown
# [MODIFY] /topdata/llm-router/CHANGELOG.md
```

Add entries for health check and key management:

```markdown
## [Unreleased]

### Added
- `/healthz` health check endpoint for service liveness probes (no auth required)
- `llm-router key` CLI command for managing API keys (local DB access only)
- `ApiKey` database model for storing hashed keys
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

### API Key Management (Local CLI Only)

```bash
# Generate a new API key
llm-router key generate --name "digester-prod"

# List all API keys
llm-router key list

# Revoke a key (sets inactive, can be re-enabled)
llm-router key revoke 1

# Permanently delete a key
llm-router key delete 1
```

### Set Environment Variable for Clients

```bash
# After generating a key, set it for topdata-tools
export TT_LLM_ROUTER_API_KEY="sk-llmr-..."
```

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
filesCreated: 6
filesModified: 6
filesDeleted: 0
tags: [llm-router, topdata-tools, service-registry, auth, healthcheck, api-keys]
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
2. **Remove key management CLI**: Delete `/topdata/llm-router/src/llm_router/commands/key_cmd.py` and `core/api_key.py`
3. **Remove ApiKey model**: Remove `ApiKey` class from `models.py`
4. **Downgrade migration**: `alembic downgrade <prev_revision>` to drop `api_key` table
5. **Remove from registry**: Delete llm-router entry from `service_registry.py`
6. **Remove settings**: Delete `llm_router_url` and `llm_router_api_key` from `config.py`

---

## 10. Success Criteria

- [ ] `/healthz` endpoint returns 200 without authentication
- [ ] `llm-router key generate` creates a new API key and shows it once
- [ ] `llm-router key list` shows all keys (without revealing hashes)
- [ ] `llm-router key revoke <id>` sets a key inactive
- [ ] `llm-router key delete <id>` permanently removes a key
- [ ] API verification works with valid keys, fails with invalid/revoked keys
- [ ] `tt health` shows llm-router as "ok"
- [ ] `tt auth check` validates llm-router API key
- [ ] `TT_LLM_ROUTER_URL` and `TT_LLM_ROUTER_API_KEY` env vars work
- [ ] All existing tests pass
- [ ] New tests added and passing
- [ ] Documentation updated
