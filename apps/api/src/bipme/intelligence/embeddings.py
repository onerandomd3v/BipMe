"""Replaceable CPU text embeddings; no X-content access in this module."""

from __future__ import annotations

import json
import math
import os
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import httpx

E5_CHECKPOINT_REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"
E5_MODEL_ID = "intfloat/multilingual-e5-small"
E5_PREPROCESSING_VERSION = "e5-prefix-strip-v1"
EmbeddingRole = Literal["query", "passage"]
_SHA = re.compile(r"^[0-9a-f]{40}$")
_MAX_REMOTE_RESPONSE_BYTES = 256 * 1024


@dataclass(frozen=True)
class EmbeddingIdentity:
    """Configuration that defines a comparable vector space and reindex boundary."""

    model_id: str
    revision: str
    dimensions: int
    preprocessing_version: str
    normalized: bool = True
    embedding_version: str = "1"

    def __post_init__(self) -> None:
        if not self.model_id or not _SHA.fullmatch(self.revision):
            raise ValueError("Model ID and immutable 40-character checkpoint revision are required")
        if self.dimensions <= 0 or not self.preprocessing_version or not self.embedding_version:
            raise ValueError(
                "Positive dimensions, preprocessing and embedding versions are required"
            )

    @property
    def index_key(self) -> str:
        """A stable identifier for rows using the same model and preprocessing."""
        return (
            f"{self.model_id}@{self.revision}:"
            f"{self.dimensions}:{self.preprocessing_version}:"
            f"embedding={self.embedding_version}:normalized={self.normalized}"
        )


class TextEmbedder(Protocol):
    """Retrieval algorithms must depend on this interface, not on E5 or a vendor."""

    @property
    def identity(self) -> EmbeddingIdentity: ...

    def encode(self, texts: Sequence[str], *, role: EmbeddingRole) -> list[list[float]]: ...


@lru_cache(maxsize=2)
def _load_model(model_id: str, revision: str) -> Any:
    """Load once per process from the pinned checkpoint."""
    try:
        sentence_transformers = import_module("sentence_transformers")
    except ImportError as exc:
        raise RuntimeError(
            "Local embedding inference requires sentence-transformers. "
            "Install the locked API dependencies with uv sync."
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
        if isinstance(texts, str):
            raise ValueError("texts must be a sequence of strings, not a single string")
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
            if not math.isclose(norm, 1.0, rel_tol=1e-3, abs_tol=1e-3):
                raise ValueError("Unnormalized or zero vector returned by model")
            result.append(values)
        if len(result) != len(texts):
            raise ValueError("Encoder output row count differs from input row count")
        return result


class RemoteEmbeddingError(RuntimeError):
    """Safe failure from the configured remote embedding service."""


class RemoteTextEmbedder:
    """Authenticated, bounded client for a private E5-compatible inference endpoint."""

    def __init__(
        self,
        identity: EmbeddingIdentity,
        *,
        endpoint: str,
        token: str,
        timeout_seconds: float = 10.0,
        max_batch_size: int = 8,
        max_text_chars: int = 10000,
        max_concurrency: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        if identity != EmbeddingIdentity(
            E5_MODEL_ID, E5_CHECKPOINT_REVISION, 384, E5_PREPROCESSING_VERSION
        ):
            raise ValueError(
                "Remote service requires the configured immutable E5 embedding identity"
            )
        try:
            parsed_endpoint = urlsplit(endpoint)
            endpoint_is_safe = (
                parsed_endpoint.scheme == "https"
                and bool(parsed_endpoint.hostname)
                and parsed_endpoint.username is None
                and parsed_endpoint.password is None
                and not parsed_endpoint.query
                and not parsed_endpoint.fragment
            )
        except ValueError:
            endpoint_is_safe = False
        if (
            not endpoint_is_safe
            or not token
            or token != token.strip()
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 60
        ):
            raise ValueError(
                "Remote embeddings require an HTTPS endpoint, token and timeout from 0 to 60 seconds"
            )
        if (
            not 1 <= max_batch_size <= 8
            or not 1 <= max_text_chars <= 10000
            or not 1 <= max_concurrency <= 16
        ):
            raise ValueError("Invalid remote embedding bounds")
        self._identity = identity
        self._endpoint = endpoint.rstrip("/") + "/embed"
        self._token = token
        self._max_batch_size = max_batch_size
        self._max_text_chars = max_text_chars
        self._client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)
        self._owns_client = client is None
        self._slots = threading.BoundedSemaphore(max_concurrency)

    @property
    def identity(self) -> EmbeddingIdentity:
        return self._identity

    def encode(self, texts: Sequence[str], *, role: EmbeddingRole) -> list[list[float]]:
        if role not in ("query", "passage"):
            raise ValueError("role must be 'query' or 'passage'")
        if isinstance(texts, str):
            raise ValueError("texts must be a sequence of strings, not a single string")
        if not texts:
            return []
        if len(texts) > self._max_batch_size or any(
            not isinstance(text, str) or not text.strip() or len(text) > self._max_text_chars
            for text in texts
        ):
            raise ValueError("Embedding batch exceeds configured bounds or contains invalid text")
        if not self._slots.acquire(blocking=False):
            raise RemoteEmbeddingError("Embedding service concurrency limit reached")
        try:
            try:
                with self._client.stream(
                    "POST",
                    self._endpoint,
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={"texts": [text.strip() for text in texts], "role": role},
                ) as response:
                    if response.status_code in (401, 403):
                        raise RemoteEmbeddingError("Embedding service authorization failed")
                    if response.status_code >= 500:
                        raise RemoteEmbeddingError("Embedding service is unavailable")
                    response.raise_for_status()
                    response_body = bytearray()
                    for chunk in response.iter_bytes():
                        response_body.extend(chunk)
                        if len(response_body) > _MAX_REMOTE_RESPONSE_BYTES:
                            raise RemoteEmbeddingError("Embedding service response is too large")
                    payload = json.loads(response_body)
            except RemoteEmbeddingError:
                raise
            except (httpx.HTTPError, ValueError):
                raise RemoteEmbeddingError("Embedding service request failed") from None
            if not isinstance(payload, dict) or (
                type(payload.get("model")) is not str
                or type(payload.get("revision")) is not str
                or type(payload.get("dimensions")) is not int
                or payload["model"] != self._identity.model_id
                or payload["revision"] != self._identity.revision
                or payload["dimensions"] != self._identity.dimensions
            ):
                raise RemoteEmbeddingError(
                    "Embedding service identity does not match configured vector space"
                )
            vectors = payload.get("embeddings")
            if not isinstance(vectors, list) or len(vectors) != len(texts):
                raise RemoteEmbeddingError("Embedding service returned an invalid vector count")
            result: list[list[float]] = []
            for vector in vectors:
                if not isinstance(vector, list) or len(vector) != self._identity.dimensions:
                    raise RemoteEmbeddingError(
                        "Embedding service returned an invalid vector dimension"
                    )
                try:
                    if any(type(value) not in (int, float) for value in vector):
                        raise ValueError("non-numeric vector value")
                    values = [float(value) for value in vector]
                except (TypeError, ValueError, OverflowError):
                    raise RemoteEmbeddingError(
                        "Embedding service returned malformed vector data"
                    ) from None
                try:
                    norm = math.sqrt(math.fsum(value * value for value in values))
                except (OverflowError, ValueError):
                    norm = math.inf
                if not all(math.isfinite(value) for value in values) or not math.isclose(
                    norm, 1.0, rel_tol=1e-3, abs_tol=1e-3
                ):
                    raise RemoteEmbeddingError(
                        "Embedding service returned an invalid normalized vector"
                    )
                result.append(values)
            return result
        finally:
            self._slots.release()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def e5_from_environment() -> E5TextEmbedder:
    """Choose the configured local model and pinned checkpoint without X data."""
    model_id = os.getenv("BIPME_EMBEDDING_MODEL", E5_MODEL_ID)
    revision = os.getenv("BIPME_EMBEDDING_REVISION", E5_CHECKPOINT_REVISION)
    return E5TextEmbedder(
        EmbeddingIdentity(
            model_id=model_id,
            revision=revision,
            dimensions=384,
            preprocessing_version=E5_PREPROCESSING_VERSION,
        )
    )


def embedder_from_environment() -> TextEmbedder:
    """Select local CPU or explicitly configured private remote inference."""
    provider = os.getenv("BIPME_EMBEDDING_PROVIDER", "local").strip().lower()
    if provider == "local":
        return e5_from_environment()
    if provider != "remote":
        raise ValueError("BIPME_EMBEDDING_PROVIDER must be 'local' or 'remote'")
    endpoint = os.getenv("BIPME_EMBEDDING_REMOTE_URL", "").strip()
    token = os.getenv("BIPME_EMBEDDING_REMOTE_TOKEN", "")
    return RemoteTextEmbedder(
        EmbeddingIdentity(E5_MODEL_ID, E5_CHECKPOINT_REVISION, 384, E5_PREPROCESSING_VERSION),
        endpoint=endpoint,
        token=token,
        timeout_seconds=float(os.getenv("BIPME_EMBEDDING_TIMEOUT_SECONDS", "10")),
    )
