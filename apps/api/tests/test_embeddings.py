"""Synthetic-only tests: never download model weights or use X content in CI."""

from __future__ import annotations

import math
import os
from typing import Any

import httpx
import pytest

from bipme.intelligence.embeddings import (
    E5_CHECKPOINT_REVISION,
    E5TextEmbedder,
    EmbeddingIdentity,
    RemoteEmbeddingError,
    RemoteTextEmbedder,
    e5_from_environment,
    embedder_from_environment,
)

REV = "a" * 40


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append((texts, kwargs))
        return [[1.0] + [0.0] * 383 for _ in texts]


def identity() -> EmbeddingIdentity:
    return EmbeddingIdentity(
        "intfloat/multilingual-e5-small", E5_CHECKPOINT_REVISION, 384, "e5-prefix-strip-v1"
    )


def test_batch_query_and_passage_prefixes_and_cpu() -> None:
    model = FakeModel()
    calls: list[tuple[str, str]] = []

    def loader(name: str, revision: str) -> FakeModel:
        calls.append((name, revision))
        return model

    encoder = E5TextEmbedder(identity(), model_loader=loader)
    queries = encoder.encode(["  Building a startup  ", "Python lessons"], role="query")
    passages = encoder.encode(["Creator lessons"], role="passage")
    assert [len(vector) for vector in queries + passages] == [384, 384, 384]
    assert calls == [
        (identity().model_id, E5_CHECKPOINT_REVISION),
        (identity().model_id, E5_CHECKPOINT_REVISION),
    ]
    assert model.calls[0][0] == ["query: Building a startup", "query: Python lessons"]
    assert model.calls[1][0] == ["passage: Creator lessons"]
    assert model.calls[0][1]["normalize_embeddings"] is True
    assert model.calls[0][1]["device"] == "cpu"


def test_no_model_loading_for_empty_batch() -> None:
    encoder = E5TextEmbedder(identity(), model_loader=lambda *_: pytest.fail("unexpected load"))
    assert encoder.encode([], role="passage") == []


@pytest.mark.parametrize("role", ["not-a-role", "", "queries"])
def test_invalid_role_is_rejected(role: str) -> None:
    encoder = E5TextEmbedder(identity(), model_loader=lambda *_: pytest.fail("unexpected load"))
    with pytest.raises(ValueError, match="role"):
        encoder.encode(["example"], role=role)  # type: ignore[arg-type]


def test_blank_inputs_are_rejected() -> None:
    encoder = E5TextEmbedder(identity(), model_loader=lambda *_: pytest.fail("unexpected load"))
    with pytest.raises(ValueError, match="non-empty"):
        encoder.encode([" "], role="query")


def test_bare_string_is_rejected_before_model_load() -> None:
    encoder = E5TextEmbedder(identity(), model_loader=lambda *_: pytest.fail("unexpected load"))
    with pytest.raises(ValueError, match="single string"):
        encoder.encode("example", role="query")


def test_revision_required_and_index_changes_with_preprocessing() -> None:
    with pytest.raises(ValueError, match="immutable"):
        EmbeddingIdentity("intfloat/multilingual-e5-small", "main", 384, "e5-v1")
    old = identity()
    new = EmbeddingIdentity(old.model_id, REV, 384, "e5-v2")
    assert old.index_key != new.index_key
    next_embedding = EmbeddingIdentity(
        old.model_id, REV, 384, old.preprocessing_version, embedding_version="2"
    )
    assert old.index_key != next_embedding.index_key


def test_shape_and_non_finite_values_are_rejected() -> None:
    class WrongSize(FakeModel):
        def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    encoder = E5TextEmbedder(identity(), model_loader=lambda *_: WrongSize())
    with pytest.raises(ValueError, match="dimensionality"):
        encoder.encode(["test"], role="passage")

    class BadVector(FakeModel):
        def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
            return [[math.nan] + [0.0] * 383 for _ in texts]

    encoder = E5TextEmbedder(identity(), model_loader=lambda *_: BadVector())
    with pytest.raises(ValueError, match="Non-finite"):
        encoder.encode(["test"], role="passage")

    class Unnormalized(FakeModel):
        def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
            return [[1.01] + [0.0] * 383 for _ in texts]

    encoder = E5TextEmbedder(identity(), model_loader=lambda *_: Unnormalized())
    with pytest.raises(ValueError, match="Unnormalized"):
        encoder.encode(["test"], role="passage")


def test_configuration_requires_pinned_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIPME_EMBEDDING_REVISION", raising=False)
    assert e5_from_environment().identity.revision == E5_CHECKPOINT_REVISION
    monkeypatch.setenv("BIPME_EMBEDDING_REVISION", REV)
    assert e5_from_environment().identity.revision == REV
    assert e5_from_environment().identity.dimensions == 384

    monkeypatch.setenv("BIPME_EMBEDDING_MODEL", "unsupported/model")
    with pytest.raises(ValueError, match="only supports"):
        e5_from_environment()


def test_provider_selection_is_explicit_and_remote_preserves_identity(monkeypatch):
    monkeypatch.delenv("BIPME_EMBEDDING_PROVIDER", raising=False)
    assert isinstance(embedder_from_environment(), E5TextEmbedder)
    monkeypatch.setenv("BIPME_EMBEDDING_PROVIDER", "remote")
    monkeypatch.setenv("BIPME_EMBEDDING_REMOTE_URL", "https://private.example")
    monkeypatch.setenv("BIPME_EMBEDDING_REMOTE_TOKEN", "synthetic-secret")
    remote = embedder_from_environment()
    assert isinstance(remote, RemoteTextEmbedder)
    assert remote.identity == identity()
    monkeypatch.setenv("BIPME_EMBEDDING_PROVIDER", "unknown")
    with pytest.raises(ValueError, match="BIPME_EMBEDDING_PROVIDER"):
        embedder_from_environment()


def _remote(handler):
    return RemoteTextEmbedder(
        identity(),
        endpoint="https://private.example",
        token="synthetic-secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.parametrize("role", ["query", "passage"])
def test_remote_posts_bearer_and_role_with_checked_identity(role):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "model": identity().model_id,
                "revision": identity().revision,
                "dimensions": 384,
                "embeddings": [[1.0] + [0.0] * 383],
            },
        )

    vectors = _remote(handler).encode(["synthetic only"], role=role)
    assert len(vectors[0]) == 384
    assert captured[0].headers["Authorization"] == "Bearer synthetic-secret"
    assert captured[0].url.path == "/embed"
    assert captured[0].read() == b'{"texts":["synthetic only"],"role":"' + role.encode() + b'"}'


@pytest.mark.parametrize(
    "payload",
    [
        {"model": "other", "revision": REV, "dimensions": 384, "embeddings": []},
        {
            "model": "intfloat/multilingual-e5-small",
            "revision": REV,
            "dimensions": 384,
            "embeddings": [],
        },
        {
            "model": "intfloat/multilingual-e5-small",
            "revision": E5_CHECKPOINT_REVISION,
            "dimensions": 384,
        },
        {
            "model": "intfloat/multilingual-e5-small",
            "revision": E5_CHECKPOINT_REVISION,
            "dimensions": 384,
            "embeddings": [[0.0] * 383],
        },
        {
            "model": "intfloat/multilingual-e5-small",
            "revision": E5_CHECKPOINT_REVISION,
            "dimensions": 384,
            "embeddings": [[0.0] * 384],
        },
        {
            "model": "intfloat/multilingual-e5-small",
            "revision": E5_CHECKPOINT_REVISION,
            "dimensions": 384,
            "embeddings": [[float("nan")] + [0.0] * 383],
        },
        {
            "model": "intfloat/multilingual-e5-small",
            "revision": E5_CHECKPOINT_REVISION,
            "dimensions": 384,
            "embeddings": [[0.5] + [0.0] * 383],
        },
    ],
)
def test_remote_rejects_mismatched_or_invalid_service_vectors(payload):
    with pytest.raises(RemoteEmbeddingError):
        _remote(lambda request: httpx.Response(200, json=payload)).encode(
            ["synthetic"], role="query"
        )


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_remote_maps_auth_and_service_failures_without_leaking(status):
    with pytest.raises(RemoteEmbeddingError) as error:
        _remote(
            lambda request: httpx.Response(status, text="synthetic-secret creator text")
        ).encode(["synthetic creator text"], role="passage")
    assert "synthetic-secret" not in str(error.value)
    assert "creator text" not in str(error.value)


def test_remote_maps_network_failure_without_leaking_text_or_token():
    def handler(request):
        raise httpx.ReadTimeout("synthetic-secret synthetic creator text", request=request)

    with pytest.raises(RemoteEmbeddingError) as error:
        _remote(handler).encode(["synthetic creator text"], role="query")
    assert "synthetic-secret" not in str(error.value)
    assert "creator text" not in str(error.value)
    assert error.value.__cause__ is None


def test_remote_rejects_oversized_response_without_parsing_it():
    with pytest.raises(RemoteEmbeddingError, match="response is too large"):
        _remote(lambda request: httpx.Response(200, content=b" " * (256 * 1024 + 1))).encode(
            ["synthetic"], role="query"
        )


def test_remote_accepts_existing_api_text_limit():
    captured = []

    def handler(request):
        captured.append(request.read())
        return httpx.Response(
            200,
            json={
                "model": identity().model_id,
                "revision": identity().revision,
                "dimensions": 384,
                "embeddings": [[1.0] + [0.0] * 383],
            },
        )

    assert len(_remote(handler).encode(["x" * 10000], role="query")) == 1
    assert len(httpx.Response(200, content=captured[0]).json()["texts"][0]) == 10000


def test_remote_requires_https_and_bounds_requests():
    with pytest.raises(ValueError, match="HTTPS"):
        RemoteTextEmbedder(identity(), endpoint="http://localhost", token="x")
    with pytest.raises(ValueError, match="timeout"):
        RemoteTextEmbedder(
            identity(), endpoint="https://private.example", token="x", timeout_seconds=61
        )
    for endpoint in (
        "https://user:password@private.example",
        "https://private.example?token=secret",
        "https://private.example/#fragment",
    ):
        with pytest.raises(ValueError, match="HTTPS"):
            RemoteTextEmbedder(identity(), endpoint=endpoint, token="x")
    encoder = RemoteTextEmbedder(
        identity(), endpoint="https://private.example", token="x", max_batch_size=1
    )
    with pytest.raises(ValueError, match="bounds"):
        encoder.encode(["one", "two"], role="passage")
    for bounds in ({"max_batch_size": 9}, {"max_text_chars": 10001}):
        with pytest.raises(ValueError, match="bounds"):
            RemoteTextEmbedder(identity(), endpoint="https://private.example", token="x", **bounds)


@pytest.mark.parametrize("value", [True, 1e308])
def test_remote_rejects_boolean_or_overflowing_vector_values(value):
    payload = {
        "model": identity().model_id,
        "revision": identity().revision,
        "dimensions": 384,
        "embeddings": [[value] + [0.0] * 383],
    }
    with pytest.raises(RemoteEmbeddingError):
        _remote(lambda request: httpx.Response(200, json=payload)).encode(
            ["synthetic"], role="query"
        )


@pytest.mark.skipif(
    os.getenv("BIPME_RUN_LIVE_EMBEDDING_SMOKE") != "1", reason="opt-in model download"
)
def test_live_cpu_semantic_smoke() -> None:
    """Synthetic examples only; explicitly opt in after downloading the pinned weights."""
    encoder = e5_from_environment()
    passages = [
        "A simple guide to baking sourdough bread with a starter.",
        "Debugging errors in a Python web application.",
        "Training for a half marathon with gradual weekly runs.",
        "Making fluffy pancakes for breakfast.",
    ]
    queries = [
        "How do I bake bread with a starter?",
        "How can I fix bugs in Python software?",
        "How should I prepare for a long distance running race?",
    ]
    passage_vectors = encoder.encode(passages, role="passage")
    query_vectors = encoder.encode(queries, role="query")
    assert all(len(vector) == 384 for vector in passage_vectors + query_vectors)
    assert all(
        math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, abs_tol=1e-3)
        for vector in passage_vectors + query_vectors
    )
    for expected, query in enumerate(query_vectors):
        similarities = [
            sum(x * y for x, y in zip(query, passage, strict=True)) for passage in passage_vectors
        ]
        assert max(range(len(similarities)), key=similarities.__getitem__) == expected
