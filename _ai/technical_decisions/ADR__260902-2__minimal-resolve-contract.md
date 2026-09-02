---
title: Minimal resolve contract — server returns topology only, client owns naming
status: Accepted
date: 2026-09-02
deciders: Marc
tags: [llm-router, resolve-contract, api, client]
adrId: 260902-2
---

# Minimal resolve contract — server returns topology only, client owns naming

## Context
`GET /api/resolve/{purpose}` currently returns one object per chain entry with four keys:
`provider` (= `Provider.name`), `prefix`, `model`, and `base_url` (and today also `api_key`).
`Provider` carries both `name` and `prefix`, but in the real fleet they are always equal and
`prefix` is the stable, unique key used in chain entries (`openai/gpt-4o-mini`) and lookups.
Emitting both is redundant, and splitting naming concerns between server and client invites
drift (e.g. a client keying `get_local_api_key` off `provider` while the server changes which
field it fills). Also, credentials are moving client-side (zero-secret config plane), so the
server must stop sending `api_key` regardless.

## Decision
The server resolve response is minimal, public topology per chain entry:
`{ "prefix": "openai", "model": "gpt-4o-mini", "base_url": "https://api.openai.com/v1" }`.

- No `provider` field, no `api_key` field, no `prefix`+`provider` duplication.
- `prefix` is the single provider identifier (the unique chain/lookup key).
- The client (`llm-router-client`, `llm_router_client`) owns naming and derivation: mapping
  `prefix` -> provider family -> env vars via `credentials.get_local_api_key`, building
  display labels (`prefix/model`), and constructing the correct PydanticAI model class.
- The client's `ModelConfig` keeps a `provider` field only as a *derived* local convenience
  (defaults to `prefix`), so existing consumers don't need to change their attribute reads.

## Consequences
Positive:
- Single stable identifier in the wire format — no server/client naming splits.
- Smaller payload, no secret material; the router becomes a pure configuration plane.
- Credential/naming decisions live in one place (the client) where consumers can override via
  `custom_map`.

Negative:
- Wire-format change: any consumer that read `entry["provider"]` from a raw response must
  switch to `prefix` or use the client's `ModelConfig`. `digester` reads attribute access
  (`entry.provider`), so it is unaffected; this is part of the coordinated consumer migration.

## Alternatives Considered
- Keep both `provider` and `prefix` in the response: redundant, invites drift; rejected.
- Emit `provider` only (drop `prefix`): `prefix` is the real lookup key in chain entries and
  provider CLI; dropping it would break the chain syntax contract; rejected.

## Related Decisions
- `ADR__260902-1__client-library-as-separate-project.md`