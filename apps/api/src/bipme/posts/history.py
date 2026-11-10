"""Persistence boundary for bounded, authorized creator-history imports."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bipme.integrations.x_read import XReadPost, XReadResult
from bipme.persistence.models import CanonicalPost, CreatorHistoryImport, OutcomeObservationRecord

_IMPORT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
SOURCE = "x_creator_authorized_history"


class HistoryReader(Protocol):
    def read(
        self,
        db: Session,
        *,
        creator_id: UUID,
        import_id: str,
        max_posts: int,
        now: datetime | None = None,
    ) -> XReadResult: ...


def _summary(row: CreatorHistoryImport) -> dict[str, object]:
    return {
        "import_id": row.import_id,
        "status": row.status,
        "requested_posts": row.requested_posts,
        "pages_read": row.pages_read,
        "imported_posts": row.imported_posts,
        "next_page_available": row.next_page_available,
        "error_code": row.error_code,
        "source": row.source,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "provenance": row.provenance,
    }


class CreatorHistoryImporter:
    """Run one bounded adapter read and atomically normalize its returned records."""

    def __init__(self, reader: HistoryReader) -> None:
        self.reader = reader

    def import_history(
        self,
        db: Session,
        *,
        creator_id: UUID,
        import_id: str,
        max_posts: int,
        now: datetime | None = None,
    ) -> dict[str, object]:
        if not _IMPORT_ID.fullmatch(import_id) or not 1 <= max_posts <= 3200:
            raise ValueError("invalid import request")
        existing = db.scalar(
            select(CreatorHistoryImport).where(
                CreatorHistoryImport.creator_id == creator_id,
                CreatorHistoryImport.import_id == import_id,
            )
        )
        if existing is not None:
            return _summary(existing)
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        state = CreatorHistoryImport(
            creator_id=creator_id,
            import_id=import_id,
            requested_posts=max_posts,
            status="running",
            started_at=instant,
            source=SOURCE,
            provenance={
                "provider": "x",
                "endpoint": "/2/users/{id}/tweets",
                "observed_at": instant.isoformat(),
            },
        )
        db.add(state)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            winner = db.scalar(
                select(CreatorHistoryImport).where(
                    CreatorHistoryImport.creator_id == creator_id,
                    CreatorHistoryImport.import_id == import_id,
                )
            )
            if winner is not None:
                return _summary(winner)
            raise
        try:
            result = self.reader.read(
                db, creator_id=creator_id, import_id=import_id, max_posts=max_posts, now=now
            )
            imported = 0
            for post in result.posts:
                if self._upsert_post(db, creator_id, import_id, post):
                    imported += 1
            state.status = result.status
            state.completed_at = (now or datetime.now(UTC)).astimezone(UTC)
            state.pages_read = result.pages_read
            state.imported_posts = imported
            state.next_page_available = result.next_page_available
            state.error_code = result.unavailable_reason
            db.commit()
            return _summary(state)
        except Exception as exc:
            db.rollback()
            failed = db.scalar(
                select(CreatorHistoryImport).where(
                    CreatorHistoryImport.creator_id == creator_id,
                    CreatorHistoryImport.import_id == import_id,
                )
            )
            if failed is not None:
                failed.status = "unavailable"
                failed.completed_at = (now or datetime.now(UTC)).astimezone(UTC)
                failed.error_code = _failure_code(exc)
                failed.provenance = {
                    **failed.provenance,
                    "failure_code": failed.error_code,
                }
                try:
                    db.commit()
                except Exception:
                    db.rollback()
            raise

    @staticmethod
    def _upsert_post(db: Session, creator_id: UUID, import_id: str, post: XReadPost) -> bool:
        existing = db.scalar(
            select(CanonicalPost).where(
                CanonicalPost.platform == "x",
                CanonicalPost.external_post_id == post.external_post_id,
            )
        )
        if existing is not None:
            if existing.creator_id != creator_id:
                return False
            changed = False
            if existing.text is None:
                existing.text = post.text
                changed = True
            if existing.media_present is None and post.media_present is not None:
                existing.media_present = post.media_present
                changed = True
            post_id = existing.id
        else:
            existing = CanonicalPost(
                creator_id=creator_id,
                platform="x",
                external_post_id=post.external_post_id,
                published_at=post.published_at,
                availability="available",
                topology=post.topology,
                reply_to_external_post_id=post.reply_to_external_post_id,
                quoted_external_post_id=post.quoted_external_post_id,
                thread_id=post.thread_id,
                ingestion_key=f"x:{post.external_post_id}",
                text=post.text,
                media_present=post.media_present,
                source=post.source,
                source_endpoint=post.source_endpoint,
                source_observed_at=post.observed_at,
                provenance={
                    "source": post.source,
                    "endpoint": post.source_endpoint,
                    "import_id": import_id,
                    "observed_at": post.observed_at.isoformat(),
                },
            )
            try:
                with db.begin_nested():
                    db.add(existing)
                    db.flush()
            except IntegrityError:
                existing = db.scalar(
                    select(CanonicalPost).where(
                        CanonicalPost.platform == "x",
                        CanonicalPost.external_post_id == post.external_post_id,
                    )
                )
                if existing is None:
                    raise
                if existing.creator_id != creator_id:
                    return False
            post_id = existing.id
            changed = True
        for metric_name, metric in post.metrics.items():
            key = f"x-history:{import_id}:{post.external_post_id}:{metric_name}"
            present = metric.value is not None
            observation = db.scalar(
                select(OutcomeObservationRecord).where(
                    OutcomeObservationRecord.creator_id == creator_id,
                    OutcomeObservationRecord.idempotency_key == key,
                )
            )
            if observation is None:
                db.add(
                    OutcomeObservationRecord(
                        post_id=post_id,
                        creator_id=creator_id,
                        published_at=post.published_at,
                        metric_name=metric_name,
                        metric_definition=metric.definition,
                        metric_unit="count",
                        metric_value=Decimal(metric.value) if metric.value is not None else None,
                        state="observed"
                        if present
                        else ("invalid" if metric.missing_reason == "invalid_value" else "missing"),
                        window_kind="mature_cumulative",
                        window_key="at_observation",
                        observed_at=post.observed_at,
                        idempotency_key=key,
                        provenance={
                            "source": post.source,
                            "endpoint": post.source_endpoint,
                            "missing_reason": metric.missing_reason,
                        },
                    )
                )
                changed = True
        return changed


def import_summary(row: CreatorHistoryImport) -> dict[str, object]:
    """Serialize a persisted import state for the typed API response."""
    return _summary(row)


def _failure_code(exc: Exception) -> str:
    """Map an exception to a safe, stable status code without exposing internals."""
    if isinstance(exc, IntegrityError):
        return "persistence_conflict"
    code = getattr(exc, "code", None)
    if isinstance(code, str) and re.fullmatch(r"[a-z0-9_:-]{1,64}", code):
        return code
    return "import_failed"
