"""Liveness smoke test."""

from fastapi.testclient import TestClient

from bipme.api.app import app


def test_health_returns_ok() -> None:
    """The API exposes a stable liveness endpoint."""
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
