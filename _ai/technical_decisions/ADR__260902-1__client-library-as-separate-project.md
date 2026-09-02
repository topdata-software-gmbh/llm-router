---
title: Client library lives in a separate llm-router-client project
status: Accepted
date: 2026-09-02
deciders: Marc
tags: [llm-router, llm-router-client, packaging, architecture]
adrId: 260902-1
---

# Client library lives in a separate llm-router-client project

## Context
`llm_router_client` (resolve_chain, router_model, fallbacks, credentials) currently ships
inside the `llm-router` repo as a second package in the same wheel (`pyproject.toml`
`[tool.hatch.build.targets.wheel].packages = ["src/llm_router", "src/llm_router_client"]`).
Consumers (today `digester`) depend on the whole `llm-router` package even though they only
import `llm_router_client.*`. The router is now gaining server-side API-key auth and
switching to a zero-secret configuration plane, which changes the client/server contract and
release cadence independently. Coupling them forces consumers to track server release
history and surface area (auth, CLI, MCP, scan) they never use.

## Decision
Extract the client into its own project at `/topdata/llm-router-client`, package
`llm-router-client`, import namespace `llm_router_client` (unchanged). The `llm-router`
repo keeps only the server (FastAPI app, CLI, MCP, core resolve, providers/models/assignments
DB). The client repo owns:
- `llm_router_client.client` — `resolve_chain`, caching, `X-API-Key` injection.
- `llm_router_client.pydantic_ai` — model factory (`router_model`, `router_model_chain`,
  `resolve_raw`) with explicit per-provider build dispatch.
- `llm_router_client.credentials` — `get_local_api_key` env mapping.
- `llm_router_client.fallback` — `with_fallbacks` chain walker.

`digester` re-points `llm-router = { path = ... }` to the new repo path.

## Consequences
Positive:
- Consumers depend on a small, fast-evolving client; server auth/security changes stay in
  the server repo.
- Client can version/release independently of server schema and auth features.
- Clear ownership boundary: server supplies topology, client supplies credentials + models.

Negative:
- Two repos to manage; a breaking client/server contract change must be coordinated across
  both (addressed by the atomic-migration rule in the security plan).
- `digester` needs a one-line dependency path update.

## Alternatives Considered
- Keep client in the server repo (separate wheel only): no reduction in consumer-facing
  surface / history; rejected.
- Name the client differently (`llm-resolver`, `llm-client`): rejected — keeps the stable
  `llm_router_client` import namespace for zero consumer churn.

## Related Decisions
- `ADR__260902-2__minimal-resolve-contract.md` (server returns topology only; client owns naming/credentials)