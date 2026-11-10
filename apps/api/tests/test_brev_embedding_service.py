"""Contract tests for the reproducible Brev inference service."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

SERVER_PATH = Path(__file__).resolve().parents[3] / "infra" / "brev-embedding" / "app.py"
SPEC = importlib.util.spec_from_file_location("bipme_brev_embedding_service", SERVER_PATH)
assert SPEC is not None and SPEC.loader is not None
service = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = service
SPEC.loader.exec_module(service)


class FakeModel:
    def __init__(self, values: Any = None, dimension: int = 384) -> None:
        self.values = values
        self.dimension = dimension
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def encode(self, texts: list[str], **kwargs: Any) -> Any:
        self.calls.append((texts, kwargs))
        if self.values is not None:
            return self.values
        return [[1.0] + [0.0] * 383 for _ in texts]

    def get_sentence_embedding_dimension(self) -> int:
        return self.dimension


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeModel]:
    fake_model = FakeModel()
    monkeypatch.setenv("BIPME_EMBEDDING_TOKEN", "synthetic-secret")
    monkeypatch.setattr(service, "model", lambda: fake_model)
    monkeypatch.setattr(service, "inference_slot", service.threading.BoundedSemaphore(1))
    return TestClient(service.app), fake_model


def test_health_reports_the_pinned_model_identity(app_client) -> None:
    client, _ = app_client
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model": "intfloat/multilingual-e5-small",
        "revision": "fd1525a9fd15316a2d503bf26ab031a61d056e98",
        "dimensions": 384,
    }


@pytest.mark.parametrize("dimension,valid", [(384, True), (512, False)])
def test_model_loader_enforces_the_embedding_dimension(
    monkeypatch: pytest.MonkeyPatch, dimension: int, valid: bool
) -> None:
    fake_model = FakeModel(dimension=dimension)
    monkeypatch.setattr(service, "loaded_model", None)
    monkeypatch.setattr(
        service,
        "import_module",
        lambda name: SimpleNamespace(SentenceTransformer=lambda *args, **kwargs: fake_model),
    )
    if valid:
        assert service.model() is fake_model
    else:
        with pytest.raises(RuntimeError, match="dimension mismatch"):
            service.model()


def test_embed_requires_bearer_token_and_does_not_leak_it(app_client) -> None:
    client, fake_model = app_client
    response = client.post("/embed", json={"texts": ["synthetic text"], "role": "query"})
    assert response.status_code == 401
    assert "synthetic-secret" not in response.text
    assert fake_model.calls == []


@pytest.mark.parametrize("role", ["query", "passage"])
def test_embed_applies_role_prefix_and_returns_normalized_vectors(app_client, role: str) -> None:
    client, fake_model = app_client
    response = client.post(
        "/embed",
        headers={"Authorization": "Bearer synthetic-secret"},
        json={"texts": ["sample one", "sample two"], "role": role},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "intfloat/multilingual-e5-small"
    assert payload["revision"] == "fd1525a9fd15316a2d503bf26ab031a61d056e98"
    assert payload["dimensions"] == 384
    assert len(payload["embeddings"]) == 2
    assert fake_model.calls[0][0] == [f"{role}: sample one", f"{role}: sample two"]
    assert all(
        sum(value * value for value in vector) == pytest.approx(1.0)
        for vector in payload["embeddings"]
    )


def test_embed_rejects_oversized_request_before_json_parsing(app_client) -> None:
    client, _ = app_client
    body = b"{" + (b" " * service.MAX_REQUEST_BYTES)
    response = client.post(
        "/embed",
        content=body,
        headers={
            "Authorization": "Bearer synthetic-secret",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 413
    assert "synthetic-secret" not in response.text


def test_embed_enforces_role_and_api_text_limit(app_client) -> None:
    client, _ = app_client
    headers = {"Authorization": "Bearer synthetic-secret"}
    invalid_role = client.post("/embed", headers=headers, json={"texts": ["x"], "role": "other"})
    max_length = client.post(
        "/embed", headers=headers, json={"texts": ["x" * 10000], "role": "passage"}
    )
    too_long = client.post(
        "/embed", headers=headers, json={"texts": ["x" * 10001], "role": "passage"}
    )
    assert invalid_role.status_code == 422
    assert max_length.status_code == 200
    assert too_long.status_code == 422
    assert "x" * 40 not in too_long.text


def test_service_unavailable_and_busy_responses_are_safe(app_client) -> None:
    client, _ = app_client
    headers = {"Authorization": "Bearer synthetic-secret"}
    service.inference_slot.acquire()
    try:
        busy = client.post(
            "/embed", headers=headers, json={"texts": ["synthetic"], "role": "query"}
        )
    finally:
        service.inference_slot.release()
    assert busy.status_code == 503


def test_model_failure_does_not_return_source_text_or_secret(app_client, monkeypatch) -> None:
    client, _ = app_client

    def unavailable():
        raise RuntimeError("synthetic-secret synthetic private source text")

    monkeypatch.setattr(service, "model", unavailable)
    response = client.post(
        "/embed",
        headers={"Authorization": "Bearer synthetic-secret"},
        json={"texts": ["synthetic private source text"], "role": "passage"},
    )
    assert response.status_code == 503
    assert "synthetic-secret" not in response.text
    assert "private source text" not in response.text
