"""Synthetic-only tests: never download model weights or use X content in CI."""

from __future__ import annotations

import math
import os
from typing import Any

import pytest

from bipme.intelligence.embeddings import (
    E5_CHECKPOINT_REVISION,
    E5TextEmbedder,
    EmbeddingIdentity,
    e5_from_environment,
)

REV = "a" * 40


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def encode(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append((texts, kwargs))
        return [[1.0] + [0.0] * 383 for _ in texts]


def identity() -> EmbeddingIdentity:
    return EmbeddingIdentity("intfloat/multilingual-e5-small", REV, 384, "e5-prefix-strip-v1")


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
    assert calls == [(identity().model_id, REV), (identity().model_id, REV)]
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
