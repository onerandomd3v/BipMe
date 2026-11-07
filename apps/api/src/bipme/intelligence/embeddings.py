"""Replaceable CPU text embeddings; no X-content access in this module."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from typing import Any, Literal, Protocol

EmbeddingRole = Literal["query", "passage"]
_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class EmbeddingIdentity:
    """Configuration that defines a comparable vector space and reindex boundary."""

    model_id: str
    revision: str
    dimensions: int
    preprocessing_version: str
    normalized: bool = True

    def __post_init__(self) -> None:
        if not self.model_id or not _SHA.fullmatch(self.revision):
            raise ValueError("Model ID and immutable 40-character checkpoint revision are required")
        if self.dimensions <= 0 or not self.preprocessing_version:
            raise ValueError("Positive dimensions and preprocessing version are required")

    @property
    def index_key(self) -> str:
        """A stable identifier for rows using the same model and preprocessing."""
        return (
            f"{self.model_id}@{self.revision}:"
            f"{self.dimensions}:{self.preprocessing_version}:normalized={self.normalized}"
        )


class TextEmbedder(Protocol):
    """Retrieval algorithms must depend on this interface, not on E5 or a vendor."""

    @property
    def identity(self) -> EmbeddingIdentity: ...

    def encode(self, texts: Sequence[str], *, role: EmbeddingRole) -> list[list[float]]: ...


@lru_cache(maxsize=2)
def _load_model(model_id: str, revision: str) -> Any:
    """Load once per process. SentenceTransformers is an optional runtime dependency."""
    try:
        sentence_transformers = import_module("sentence_transformers")
    except ImportError as exc:
        raise RuntimeError(
            "Local embedding inference requires sentence-transformers. "
            "Install it via uv and regenerate uv.lock before deployment."
        ) from exc
    return sentence_transformers.SentenceTransformer(
        model_id, revision=revision, device="cpu", trust_remote_code=False
    )


class E5TextEmbedder:
    """CPU-first E5 implementation of TextEmbedder, with explicit query/passage rules."""

    def __init__(
        self,
        identity: EmbeddingIdentity,
        *,
        batch_size: int = 16,
        model_loader: Callable[[str, str], Any] = _load_model,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if identity.dimensions != 384:
            raise ValueError("multilingual-e5-small requires 384-dimensional embeddings")
        if identity.model_id != "intfloat/multilingual-e5-small":
            raise ValueError("E5TextEmbedder only supports intfloat/multilingual-e5-small")
        if not identity.normalized:
            raise ValueError("E5 embeddings must be normalized for cosine retrieval")
        self._identity = identity
        self._batch_size = batch_size
        self._model_loader = model_loader

    @property
    def identity(self) -> EmbeddingIdentity:
        return self._identity

    def encode(self, texts: Sequence[str], *, role: EmbeddingRole) -> list[list[float]]:
        if role not in ("query", "passage"):
            raise ValueError("role must be 'query' or 'passage'")
        if not texts:
            return []
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("Every text must be a non-empty string")
        # Prefixes are mandatory in the published E5 inference recipe.
        prefixed = [f"{role}: {text.strip()}" for text in texts]
        model = self._model_loader(self._identity.model_id, self._identity.revision)
        vectors = model.encode(
            prefixed,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            device="cpu",
        )
        result: list[list[float]] = []
        for row in vectors:
            values = [float(x) for x in row]
            if len(values) != self._identity.dimensions:
                raise ValueError("Model output dimensionality differs from configured vector index")
            if not all(math.isfinite(x) for x in values):
                raise ValueError("Non-finite embedding value")
            norm = math.sqrt(sum(x * x for x in values))
            if not math.isclose(norm, 1.0, rel_tol=0.02, abs_tol=0.02):
                raise ValueError("Unnormalized or zero vector returned by model")
            result.append(values)
        if len(result) != len(texts):
            raise ValueError("Encoder output row count differs from input row count")
        return result


def e5_from_environment() -> E5TextEmbedder:
    """Choose a pinned local checkpoint without embedding secrets or X data."""
    revision = os.getenv("BIPME_EMBEDDING_REVISION", "")
    return E5TextEmbedder(
        EmbeddingIdentity(
            model_id="intfloat/multilingual-e5-small",
            revision=revision,
            dimensions=384,
            preprocessing_version="e5-prefix-strip-v1",
        )
    )
