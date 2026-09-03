# llm-router

A central LLM provider/model assignment resolver for a small fleet of
projects. It **resolves** purposes to ordered `{provider, model, base_url,
api_key}` chains — it is a directory, **not** a proxy; inference stays external.

Owns, in one place:

- **Providers** — base URL + API key (cloud keys live here, not in per-project env).
- **Models** — the detected/hand-added catalog.
- **Assignments** — a purpose key (`project:job`, e.g. `git-digest:digest`) mapped
  to an ordered chain of `provider/model` strings (primary first, fallbacks after).

Home-LAN only: single admin, trusted network. API keys are optional: if no
keys exist the service runs in zero-config dev mode (auth skipped); once a key
is registered, requests to everything except `/healthz` must carry an
`X-API-Key` header.

## Getting Started

Requires Python 3.12+ and `uv`.

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
uv run alembic upgrade head        # create SQLite schema
```

Run the server:

```bash
uv run uvicorn llm_router.main:app --reload
```

The database lives at `llm_router.db` by default; override with
`LLM_ROUTER_DB=/path/to/router.db`.

## Usage

Populate the catalog and an assignment, then resolve:

```bash
llm-router scan                          # detect providers/models from env + ollama + ports
llm-router provider add openai openai https://api.openai.com/v1 --api-key sk-...
llm-router assignment set git-digest:digest git-digest openai/gpt-4o-mini,anthropic/claude-3-haiku
llm-router resolve git-digest:digest     # print the expanded chain
```

HTTP API:

```text
GET  /api/providers            list providers
POST /api/providers/upsert     add/update a provider
GET  /api/models               list catalog models
POST /api/models/upsert        add/update a catalog model
PUT  /api/assignments/{purpose}  set an assignment chain
GET  /api/assignments/{purpose}  get an assignment
GET  /api/assignments          list assignments
GET  /api/resolve/{purpose}    resolve to ordered connection chain
GET  /api/catalog              full provider + model catalog
POST /api/scan                 re-run detection and persist new providers/models
```

MCP server (for agents):

```bash
llm-router-mcp
```

Tools: `resolve_purpose`, `list_assignments`, `get_catalog`.

## Client library

`llm_router_client` (in this repo) lets projects consume the router:

```python
from llm_router_client.pydantic_ai import router_model
from llm_router_client.fallback import with_fallbacks
```

Set `LLM_ROUTER_URL` (default `http://localhost:8000`).

## Health Check

The service exposes a `/healthz` endpoint for liveness probes that does not require authentication:

```bash
curl http://localhost:8202/healthz
# {"status":"ok","service":"llm-router"}
```

This endpoint is used by `topdata-tools` for service availability monitoring.

## API Key Management

API keys are managed exclusively via the local CLI with direct database access. There is **no API endpoint** for key management (security design).

Keys are stored **plaintext** in the database. `llm-router key list` shows the full key values for all registered keys.

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
  Name:      digester-prod
```

### List all keys

```bash
llm-router key list
```

Shows every registered key with its full plaintext value:

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

## Project layout

```
src/llm_router/          server: models, core (detect/resolve), routers, cli, mcp
src/llm_router_client/   shared client library for consumers
alembic/                 schema migrations
tests/                   pytest suite
```

## Relationships

`provider` holds credentials; `model` is the detected catalog; `assignment`
maps `project:job` → ordered `provider/model` chain. The chain is plain JSON
text and is deliberately not FK-constrained to `model` — an assignment may
reference a model not yet in the catalog.
