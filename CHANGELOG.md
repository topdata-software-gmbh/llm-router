# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project structure with README and CHANGELOG.
- FastAPI server with provider/model/assignment management and purpose resolution.
- Typer CLI (`scan`, `provider`, `assignment`, `catalog`, `resolve`).
- MCP server (`resolve_purpose`, `list_assignments`, `get_catalog`).
- Auto-detection of providers/models (env keys, local ports, `ollama list`).
- Shared `llm_router_client` library: `resolve_chain`, PydanticAI
  `router_model`/`router_model_chain`, and `with_fallbacks` chain walker.
- Alembic-managed SQLite schema (provider, model, assignment tables).

## [Unreleased]

### Added
- `/healthz` health check endpoint for service liveness probes (no auth required).
- `llm-router key` CLI command for managing API keys (local DB access only,
  **no API endpoint** for key management).
- `ApiKey` database model storing plaintext keys (`sk-llmr-...`).
- X-API-Key authentication on all endpoints except `/healthz` (skipped when no
  keys exist).
- Integration with the topdata-tools service registry (`tt health`, `tt auth check`).
- Alembic migration `4a832ee347e6` adding the `api_key` table.
