"""Fail-closed API dependencies for authentication, persistence and inference."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from bipme.api.errors import ApiError
from bipme.intelligence.embeddings import TextEmbedder, e5_from_environment


@dataclass(frozen=True)
class AuthenticatedCreator:
    """Server-verified creator identity expected from COD-346's session dependency."""

    creator_id: UUID


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    database_url = os.getenv("BIPME_DATABASE_URL")
    if not database_url:
        raise ApiError(503, "database_unavailable", "The analysis database is unavailable.")
    return sessionmaker(
        bind=create_engine(database_url, pool_pre_ping=True), expire_on_commit=False
    )


def get_db_session() -> Iterator[Session]:
    """Yield a database session, failing with a safe error when configuration is absent."""
    try:
        factory = _session_factory()
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            503, "database_unavailable", "The analysis database is unavailable."
        ) from exc
    with factory() as session:
        yield session


def get_authenticated_creator() -> AuthenticatedCreator:
    """Fail closed until COD-346 provides a server-verified private session contract."""
    raise ApiError(
        503,
        "authentication_not_configured",
        "Creator analysis is unavailable until secure account sessions are configured.",
    )


def get_embedder() -> TextEmbedder:
    """Return the configured local encoder; no remote inference service is used."""
    try:
        return e5_from_environment()
    except Exception as exc:
        raise ApiError(
            503, "embedding_unavailable", "Draft analysis is temporarily unavailable."
        ) from exc


def get_current_time() -> datetime:
    """Return the server assessment instant as an aware UTC timestamp."""
    return datetime.now(UTC)
