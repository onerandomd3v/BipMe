"""Private, server-managed creator session operations."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from bipme.auth.config import AuthSettings
from bipme.auth.crypto import csrf_token_for, secret_digest
from bipme.persistence.models import Creator, CreatorSession


@dataclass(frozen=True)
class IssuedCreatorSession:
    record: CreatorSession
    cookie_token: str
    csrf_token: str


def create_creator_session(
    db: Session,
    *,
    creator_id: UUID,
    auth_method: str,
    x_identity_id: UUID | None,
    settings: AuthSettings,
    now: datetime,
) -> IssuedCreatorSession:
    """Create an opaque random cookie and persist only its SHA-256 digest."""
    if not settings.session_storage_ready or settings.session_lifetime_seconds <= 0:
        raise ValueError("private sessions are not configured")
    if db.get(Creator, creator_id) is None:
        raise ValueError("configured creator is unavailable")
    cookie_token = secrets.token_urlsafe(32)
    record = CreatorSession(
        id=uuid4(),
        creator_id=creator_id,
        token_hash=secret_digest(cookie_token),
        auth_method=auth_method,
        x_identity_id=x_identity_id,
        created_at=now,
        expires_at=now + timedelta(seconds=settings.session_lifetime_seconds),
    )
    db.add(record)
    db.flush()
    return IssuedCreatorSession(record, cookie_token, csrf_token_for(cookie_token))


def active_session_by_cookie(db: Session, cookie_token: str) -> CreatorSession | None:
    """Look up an unexpired session without ever persisting its bearer secret."""
    if not cookie_token or len(cookie_token) > 256:
        return None
    return db.scalar(
        select(CreatorSession).where(CreatorSession.token_hash == secret_digest(cookie_token))
    )
