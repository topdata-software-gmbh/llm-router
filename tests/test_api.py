"""API-level tests for assignments and resolve endpoints."""


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


def test_provider_upsert_and_list(client):
    _seed_provider(client)
    got = client.get("/api/providers")
    assert got.status_code == 200
    body = got.json()
    assert len(body) == 1
    assert body[0]["prefix"] == "openai"
    assert body[0]["api_key"] == "sk"


def test_assignment_upsert_roundtrip(client):
    _seed_provider(client)
    r = client.put(
        "/api/assignments/git-digest:digest",
        json={
            "key": "git-digest:digest",
            "owner": "git-digest",
            "chain": ["openai/gpt-4o-mini"],
        },
    )
    assert r.status_code == 200
    assert r.json()["chain"] == ["openai/gpt-4o-mini"]

    got = client.get("/api/assignments/git-digest:digest")
    assert got.status_code == 200
    assert got.json()["owner"] == "git-digest"


def test_assignment_requires_key_match(client):
    r = client.put(
        "/api/assignments/other",
        json={"key": "mismatch", "owner": "x", "chain": []},
    )
    assert r.status_code == 400


def test_resolve_returns_chain(client):
    _seed_provider(client)
    client.put(
        "/api/assignments/acp:chat-db",
        json={
            "key": "acp:chat-db",
            "owner": "acp",
            "chain": ["openai/gpt-4o-mini", "openai/gpt-4o"],
        },
    )
    r = client.get("/api/resolve/acp:chat-db")
    assert r.status_code == 200
    body = r.json()
    assert body["purpose"] == "acp:chat-db"
    assert body["chain"][0]["provider"] == "openai"
    assert body["chain"][0]["model"] == "gpt-4o-mini"
    assert body["chain"][0]["api_key"] == "sk"
    assert len(body["chain"]) == 2


def test_resolve_unknown_purpose_404(client):
    r = client.get("/api/resolve/nope:nope")
    assert r.status_code == 404


def test_resolve_unknown_provider_422(client):
    client.put(
        "/api/assignments/x:y",
        json={"key": "x:y", "owner": "x", "chain": ["ghost/model"]},
    )
    r = client.get("/api/resolve/x:y")
    assert r.status_code == 422


def test_catalog(client):
    _seed_provider(client)
    r = client.get("/api/catalog")
    assert r.status_code == 200
    body = r.json()
    assert len(body["providers"]) == 1


def test_scan_persists_providers_and_models(client, monkeypatch):
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
    r = client.post("/api/scan")
    assert r.status_code == 200
    assert r.json()["providers_added"] == 1
    got = client.get("/api/providers")
    assert len(got.json()) == 1
