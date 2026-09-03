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
