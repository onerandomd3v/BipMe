"""Fail-closed API dependencies for authentication, persistence and inference."""

from __future__ import annotations

import hmac
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from uuid import UUID

from fastapi import Header, Request
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from bipme.api.errors import ApiError
from bipme.auth.config import AuthSettings
from bipme.auth.crypto import csrf_token_for
from bipme.auth.sessions import active_session_by_cookie
from bipme.intelligence.embeddings import TextEmbedder, e5_from_environment
from bipme.persistence.models import CreatorPlatformIdentity


@dataclass(frozen=True)
class AuthenticatedCreator:
    """Server-verified creator identity expected from COD-346's session dependency."""

    creator_id: UUID
    session_id: UUID | None = None
    csrf_token: str | None = None


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


def get_authenticated_creator(
    request: Request,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> AuthenticatedCreator:
    """Resolve a live server-side session and require CSRF proof on unsafe methods."""
    settings = AuthSettings.from_environment()
    if not settings.session_storage_ready:
        raise ApiError(
            503,
            "authentication_not_configured",
            "Creator analysis is unavailable until secure account sessions are configured.",
        )
    cookie_token = request.cookies.get(settings.session_cookie_name)
    if cookie_token is None:
        raise ApiError(401, "authentication_required", "A private creator session is required.")
    try:
        factory = getattr(request.app.state, "auth_session_factory", None) or _session_factory()
        with factory() as db:
            record = active_session_by_cookie(db, cookie_token)
            now = datetime.now(UTC)
            if (
                record is None
                or record.creator_id != settings.creator_id
                or record.revoked_at is not None
                or record.expires_at <= now
            ):
                raise ApiError(401, "session_invalid", "The creator session is no longer valid.")
            if record.auth_method == "x_oauth":
                identity = db.scalar(
                    select(CreatorPlatformIdentity).where(
                        CreatorPlatformIdentity.id == record.x_identity_id,
                        CreatorPlatformIdentity.creator_id == record.creator_id,
                        CreatorPlatformIdentity.platform == "x",
                        CreatorPlatformIdentity.external_creator_id == settings.x_allowed_user_id,
                    )
                )
                if identity is None:
                    raise ApiError(
                        401, "session_invalid", "The creator session is no longer valid."
                    )
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            503, "authentication_unavailable", "Creator authentication is temporarily unavailable."
        ) from exc

    csrf_token = csrf_token_for(cookie_token)
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"} and (
        x_csrf_token is None or not hmac.compare_digest(x_csrf_token, csrf_token)
    ):
        raise ApiError(403, "csrf_validation_failed", "The request could not be verified.")
    return AuthenticatedCreator(record.creator_id, record.id, csrf_token)


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
