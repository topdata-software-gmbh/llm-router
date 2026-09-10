"""API-level tests for auth, assignments and resolve endpoints.

Every non-health route is gated behind Bearer-JWT IAM auth. Tests use the
``iam_env`` fixture (mocked IAM) and mint real Ed25519-signed tokens.
"""


def _auth_header(iam_env, sub="1", typ="agent"):
    return {"Authorization": f"Bearer {iam_env['token'](sub, typ)}"}


def _grant(action: str, resource_id: str = "*") -> dict:
    return {
        "principal": "1",
        "resource_type": "llm",
        "resource_id": resource_id,
        "action": action,
    }


def _read(iam_env):
    iam_env["setup"](lambda params: [_grant("read")])


def _read_write(iam_env):
    iam_env["setup"](lambda params: [_grant("read"), _grant("write")])


def test_healthz_keyless(client):
    """Health endpoint requires no auth header."""
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_authenticated_route_requires_bearer(client):
    """Without a Bearer token the router rejects the request."""
    r = client.get("/api/providers")
    assert r.status_code == 401


def test_valid_token_no_grants_forbidden(client, iam_env):
    """A valid token with no grants is rejected (fail-closed)."""
    headers = _auth_header(iam_env)
    r = client.get("/api/providers", headers=headers)
    assert r.status_code == 403


def test_valid_token_with_grants_allowed(client, iam_env):
    """A valid token with a read grant passes the read gate."""
    _read(iam_env)
    r = client.get("/api/providers", headers=_auth_header(iam_env))
    assert r.status_code == 200


def test_write_requires_write_grant(client, iam_env):
    """Read-only grant is not enough to upsert a provider."""
    _read(iam_env)
    r = client.post(
        "/api/providers/upsert",
        headers=_auth_header(iam_env),
        json={
            "name": "openai",
            "prefix": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk",
        },
    )
    assert r.status_code == 403


def test_provider_upsert_and_list(client, iam_env):
    _read_write(iam_env)
    headers = _auth_header(iam_env)
    r = client.post(
        "/api/providers/upsert",
        headers=headers,
        json={
            "name": "openai",
            "prefix": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk",
        },
    )
    assert r.status_code == 200
    got = client.get("/api/providers", headers=headers)
    assert got.status_code == 200
    body = got.json()
    assert len(body) == 1
    assert body[0]["prefix"] == "openai"
    assert body[0]["api_key"] == "sk"


def test_assignment_upsert_roundtrip(client, iam_env):
    _read_write(iam_env)
    headers = _auth_header(iam_env)
    r = client.put(
        "/api/assignments/git-digest:digest",
        headers=headers,
        json={
            "key": "git-digest:digest",
            "owner": "git-digest",
            "chain": ["openai/gpt-4o-mini"],
        },
    )
    assert r.status_code == 200
    assert r.json()["chain"] == ["openai/gpt-4o-mini"]

    got = client.get("/api/assignments/git-digest:digest", headers=headers)
    assert got.status_code == 200
    assert got.json()["owner"] == "git-digest"


def test_assignment_requires_key_match(client, iam_env):
    _read_write(iam_env)
    r = client.put(
        "/api/assignments/other",
        headers=_auth_header(iam_env),
        json={"key": "mismatch", "owner": "x", "chain": []},
    )
    assert r.status_code == 400


def test_resolve_returns_chain(client, iam_env):
    _read_write(iam_env)
    headers = _auth_header(iam_env)
    client.post(
        "/api/providers/upsert",
        headers=headers,
        json={
            "name": "openai",
            "prefix": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk",
        },
    )
    r = client.put(
        "/api/assignments/acp:chat-db",
        headers=headers,
        json={
            "key": "acp:chat-db",
            "owner": "acp",
            "chain": ["openai/gpt-4o-mini", "openai/gpt-4o"],
        },
    )
    assert r.status_code == 200
    r = client.get("/api/resolve/acp:chat-db", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["purpose"] == "acp:chat-db"
    assert body["chain"][0]["provider"] == "openai"
    assert body["chain"][0]["model"] == "gpt-4o-mini"
    assert body["chain"][0]["api_key"] == "sk"
    assert len(body["chain"]) == 2


def test_resolve_unknown_purpose_404(client, iam_env):
    _read(iam_env)
    r = client.get("/api/resolve/nope:nope", headers=_auth_header(iam_env))
    assert r.status_code == 404


def test_resolve_unknown_provider_422(client, iam_env):
    _read_write(iam_env)
    headers = _auth_header(iam_env)
    client.put(
        "/api/assignments/x:y",
        headers=headers,
        json={"key": "x:y", "owner": "x", "chain": ["ghost/model"]},
    )
    r = client.get("/api/resolve/x:y", headers=headers)
    assert r.status_code == 422


def test_catalog(client, iam_env):
    _read_write(iam_env)
    headers = _auth_header(iam_env)
    client.post(
        "/api/providers/upsert",
        headers=headers,
        json={
            "name": "openai",
            "prefix": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk",
        },
    )
    r = client.get("/api/catalog", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["providers"]) == 1


def test_scan_persists_providers_and_models(client, iam_env, monkeypatch):
    _read_write(iam_env)
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    monkeypatch.setattr(
        "llm_router.routers.scan.detect_scan",
        lambda: type(
            "R",
            (),
            {
                "providers": [
                    type(
                        "P",
                        (),
                        {
                            "prefix": "openai",
                            "name": "openai",
                            "base_url": "http://x",
                            "api_key": None,
                        },
                    )()
                ],
                "models": [],
            },
        )(),
    )
    headers = _auth_header(iam_env)
    r = client.post("/api/scan", headers=headers)
    assert r.status_code == 200
    assert r.json()["providers_added"] == 1
    got = client.get("/api/providers", headers=headers)
    assert len(got.json()) == 1


def test_write_endpoint_no_write_grant_forbidden(client, iam_env):
    """Write endpoints reject callers holding only read grants."""
    _read(iam_env)
    r = client.put(
        "/api/assignments/x:y",
        headers=_auth_header(iam_env),
        json={"key": "x:y", "owner": "x", "chain": []},
    )
    assert r.status_code == 403


def test_malformed_auth_header_rejected(client, iam_env):
    """A non-Bearer Authorization header is rejected."""
    r = client.get(
        "/api/providers", headers={"Authorization": "X-API-Key abc"}
    )
    assert r.status_code == 401


def test_invalid_token_rejected(client, iam_env):
    """A token we did not sign is rejected."""
    r = client.get(
        "/api/providers", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert r.status_code == 401


def test_healthz_stays_keyless_even_authenticated(client, iam_env):
    """Health stays reachable regardless of auth state."""
    assert client.get("/healthz").status_code == 200
    assert client.get(
        "/healthz", headers={"Authorization": "Bearer garbage"}
    ).status_code == 200
