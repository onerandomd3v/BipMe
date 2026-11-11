"""Source-specific gates for personal creator evidence."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID

KNOWN_X_SOURCES = frozenset(
    {"x_creator_authorized_history", "x_authorized_publication_verification"}
)
SYNTHETIC_DEMO_SOURCE = "synthetic_demo_fixture"


def x_history_policy_verified_at(as_of: datetime) -> datetime | None:
    """Require the existing operator gate and a cutoff-safe policy review timestamp."""
    value = os.getenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "false").strip().lower()
    if value not in {"1", "true", "yes", "on"}:
        return None
    raw_time = os.getenv("BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT")
    if not raw_time:
        return None
    try:
        verified_at = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    if verified_at.tzinfo is None or verified_at.utcoffset() is None or verified_at > as_of:
        return None
    return verified_at.astimezone(UTC)


def synthetic_demo_enabled_for(creator_id: UUID) -> bool:
    """Synthetic-only processing is opt-in, creator-bound, and non-production."""
    environment = os.getenv("BIPME_ENVIRONMENT", "").strip().lower()
    enabled = os.getenv("BIPME_SYNTHETIC_DEMO_ENABLED", "false").strip().lower()
    configured_creator = os.getenv("BIPME_SYNTHETIC_DEMO_CREATOR_ID", "").strip()
    configured_session_creator = os.getenv("BIPME_CREATOR_ID", "").strip()
    try:
        demo_creator_id = UUID(configured_creator)
        session_creator_id = UUID(configured_session_creator)
    except (ValueError, AttributeError):
        return False
    return (
        environment in {"development", "demo"}
        and enabled in {"1", "true", "yes", "on"}
        and os.getenv("BIPME_EMBEDDING_PROVIDER", "").strip().lower() == "synthetic_demo"
        and demo_creator_id == creator_id == session_creator_id
    )


def allowed_personal_history_sources(creator_id: UUID, as_of: datetime) -> frozenset[str]:
    """Select one provenance pool; synthetic evidence is never mixed with X evidence."""
    if synthetic_demo_enabled_for(creator_id):
        return frozenset({SYNTHETIC_DEMO_SOURCE})
    if x_history_policy_verified_at(as_of) is not None:
        return frozenset(KNOWN_X_SOURCES)
    return frozenset()
