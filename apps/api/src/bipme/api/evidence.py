"""Bounded stored evidence reads. No provider, ingestion or usage-accounting dependencies."""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, ValidationError
from sqlalchemy import and_, or_, select, true
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from bipme.api.creator_reports import _latest_permission
from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
)
from bipme.api.errors import ApiError
from bipme.api.schemas import ErrorResponse, StrictModel
from bipme.api.source_policy import (
    KNOWN_X_SOURCES,
    SYNTHETIC_DEMO_SOURCE,
    allowed_personal_history_sources,
)
from bipme.persistence.models import (
    CanonicalPost,
    CreatorHistoryImport,
    DraftAssessment,
    OutcomeObservationRecord,
)

router = APIRouter(prefix="/api/v1/creators/me/history", tags=["history evidence"])
_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 422, 503)
}
OBSERVATION_LIMIT = 50


class ObservationProvenance(StrictModel):
    source: Literal["authorized_x_api", "archive", "unknown", "synthetic_demo"]
    missing_reason: Literal["not_returned", "invalid_value", "unavailable"] | None = None


class MetricObservationEvidence(StrictModel):
    id: UUID
    metric_name: str
    metric_definition: str
    metric_unit: str
    metric_value: Decimal | None
    state: Literal["observed", "missing", "invalid"]
    window_kind: Literal["mature_cumulative", "age_aligned"]
    window_key: str
    observed_at: datetime
    published_at: datetime
    observed_age_seconds: float
    provenance: ObservationProvenance
    source: Literal["authorized_x_api", "archive", "unknown", "synthetic_demo"]


class PostEvidence(StrictModel):
    id: UUID
    published_at: datetime
    source: Literal["authorized_x_api", "archive", "unknown", "synthetic_demo"]
    text: str | None
    source_url: str | None
    disclosure: Literal[
        "permitted", "permission_required", "source_policy_blocked", "not_known_at_cutoff"
    ]
    source_observed_at: datetime | None
    freshness: Literal["recorded", "unknown", "not_known_at_cutoff"]
    observations: tuple[MetricObservationEvidence, ...]
    observations_truncated: bool
    source_label: str | None = None


class EvidencePage(StrictModel):
    items: tuple[PostEvidence, ...]
    as_of: datetime
    assessment_id: UUID | None
    next_cursor: str | None = None


class ImportStatus(StrictModel):
    import_id: str
    status: Literal["running", "complete", "partial", "unavailable"]
    requested_posts: int
    imported_posts: int
    pages_read: int
    next_page_available: bool
    started_at: datetime
    completed_at: datetime | None
    source: Literal["authorized_x_api", "archive", "unknown", "synthetic_demo"]


class ImportPage(StrictModel):
    items: tuple[ImportStatus, ...]
    truncated: bool


class Cursor(StrictModel):
    version: Literal[1] = 1
    owner: UUID
    as_of: AwareDatetime
    assessment_id: UUID | None
    published_at: AwareDatetime
    id: UUID


def source_kind(source: str) -> Literal["authorized_x_api", "archive", "unknown", "synthetic_demo"]:
    if source in KNOWN_X_SOURCES:
        return "authorized_x_api"
    if source == SYNTHETIC_DEMO_SOURCE:
        return "synthetic_demo"
    # This is a classification, not permission to process archive content. There
    # is currently no implemented source-specific archive display policy gate.
    return "archive" if source == "creator_provided_archive" else "unknown"


def cutoff(
    db: Session, owner: UUID, now: datetime, as_of: datetime | None, assessment_id: UUID | None
) -> datetime:
    if assessment_id is not None:
        if as_of is not None:
            raise ApiError(
                422, "ambiguous_evidence_cutoff", "Use as_of or assessment_id, not both."
            )
        assessment = db.scalar(
            select(DraftAssessment).where(
                DraftAssessment.id == assessment_id, DraftAssessment.creator_id == owner
            )
        )
        if assessment is None:
            raise ApiError(404, "assessment_not_found", "The requested assessment was not found.")
        as_of = assessment.assessed_at
    result = as_of or now
    if result.tzinfo is None or result.utcoffset() is None or result > now:
        raise ApiError(
            422,
            "invalid_evidence_cutoff",
            "Evidence cutoff must be timezone-aware and not in the future.",
        )
    return result


def visible(owner: UUID, as_of: datetime) -> tuple[ColumnElement[bool], ...]:
    return (
        CanonicalPost.creator_id == owner,
        CanonicalPost.availability == "available",
        CanonicalPost.published_at <= as_of,
    )


def build_evidence(
    db: Session, owner: UUID, posts: list[CanonicalPost], as_of: datetime, now: datetime
) -> tuple[PostEvidence, ...]:
    permission = _latest_permission(db, owner)
    granted = bool(permission and permission.allowed and permission.recorded_at <= now)
    allowed_sources = allowed_personal_history_sources(owner, now)
    permitted_ids = [p.id for p in posts if granted and p.source in allowed_sources]
    grouped: dict[UUID, list[OutcomeObservationRecord]] = {}
    if permitted_ids:
        # One indexed, bounded lateral lookup per selected post, in ONE DB query.
        # Unlike a window over all history, LIMIT stops each post's observation scan.
        selected = (
            select(OutcomeObservationRecord)
            .where(
                OutcomeObservationRecord.creator_id == owner,
                OutcomeObservationRecord.post_id == CanonicalPost.id,
                OutcomeObservationRecord.observed_at <= as_of,
            )
            .order_by(
                OutcomeObservationRecord.observed_at.desc(), OutcomeObservationRecord.id.desc()
            )
            .limit(OBSERVATION_LIMIT + 1)
            .correlate(CanonicalPost)
            .lateral()
        )
        observation = aliased(OutcomeObservationRecord, selected)
        for post_id, row in db.execute(
            select(CanonicalPost.id, observation)
            .select_from(CanonicalPost)
            .join(observation, true())
            .where(*visible(owner, as_of), CanonicalPost.id.in_(permitted_ids))
            .order_by(CanonicalPost.id, observation.observed_at.desc(), observation.id.desc())
        ):
            grouped.setdefault(post_id, []).append(row)
    result = []
    for post in posts:
        disclosure: Literal[
            "permitted", "permission_required", "source_policy_blocked", "not_known_at_cutoff"
        ] = "permitted"
        if not granted:
            disclosure = "permission_required"
        elif post.source not in allowed_sources:
            disclosure = "source_policy_blocked"
        elif (
            post.source_observed_at is None
            or post.source_observed_at > as_of
            or post.updated_at > as_of
        ):
            disclosure = "not_known_at_cutoff"
        # Observation timestamps have their own evidence identity and cutoff; a
        # later source/text refresh must not hide earlier real observations.
        rows = grouped.get(post.id, [])
        observations = tuple(
            MetricObservationEvidence(
                id=r.id,
                metric_name=r.metric_name,
                metric_definition=r.metric_definition,
                metric_unit=r.metric_unit,
                metric_value=r.metric_value,
                state=cast(Literal["observed", "missing", "invalid"], r.state),
                window_kind=cast(Literal["mature_cumulative", "age_aligned"], r.window_kind),
                window_key=r.window_key,
                observed_at=r.observed_at,
                published_at=r.published_at,
                observed_age_seconds=(r.observed_at - r.published_at).total_seconds(),
                source=source_kind(post.source),
                provenance=ObservationProvenance.model_validate(
                    {
                        "source": source_kind(str(r.provenance.get("source", "unknown"))),
                        "missing_reason": r.provenance.get("missing_reason")
                        if isinstance(r.provenance.get("missing_reason"), str)
                        and r.provenance.get("missing_reason")
                        in {"not_returned", "invalid_value", "unavailable"}
                        else None,
                    }
                ),
            )
            for r in rows[:OBSERVATION_LIMIT]
        )
        url = None
        if (
            disclosure == "permitted"
            and post.platform == "x"
            and re.fullmatch(r"[1-9][0-9]{0,19}", post.external_post_id)
            and int(post.external_post_id) <= 2**64 - 1
        ):
            url = f"https://x.com/i/status/{post.external_post_id}"
        freshness: Literal["recorded", "unknown", "not_known_at_cutoff"] = "unknown"
        source_time = post.source_observed_at
        if source_time is not None:
            freshness = "recorded" if source_time <= as_of else "not_known_at_cutoff"
        result.append(
            PostEvidence(
                id=post.id,
                published_at=post.published_at,
                source=source_kind(post.source),
                text=post.text if disclosure == "permitted" else None,
                source_url=url,
                disclosure=disclosure,
                source_observed_at=source_time
                if source_time is not None and source_time <= as_of
                else None,
                freshness=freshness,
                observations=observations,
                observations_truncated=len(rows) > OBSERVATION_LIMIT,
                source_label=(
                    "Synthetic demonstration data — not live X evidence"
                    if post.source == SYNTHETIC_DEMO_SOURCE
                    else None
                ),
            )
        )
    return tuple(result)


def store_error() -> ApiError:
    return ApiError(
        503, "history_evidence_unavailable", "Stored history evidence is temporarily unavailable."
    )


@router.get("/posts", response_model=EvidencePage, responses=_ERRORS)
def list_posts(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
    now: Annotated[datetime, Depends(get_current_time)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    as_of: AwareDatetime | None = None,
    assessment_id: UUID | None = None,
) -> EvidencePage:
    try:
        if as_of is not None and assessment_id is not None:
            raise ApiError(
                422, "ambiguous_evidence_cutoff", "Use as_of or assessment_id, not both."
            )
        position = None
        if cursor:
            try:
                position = Cursor.model_validate_json(
                    base64.b64decode(cursor.encode(), altchars=b"-_", validate=True)
                )
            except (ValueError, ValidationError, binascii.Error) as exc:
                raise ApiError(
                    422, "invalid_evidence_cursor", "The evidence cursor is invalid."
                ) from exc
            if (
                position.owner != creator.creator_id
                or position.assessment_id != assessment_id
                or (as_of is not None and as_of != position.as_of)
            ):
                raise ApiError(
                    422,
                    "invalid_evidence_cursor",
                    "The evidence cursor does not match this request.",
                )
        effective = (
            cutoff(db, creator.creator_id, now, as_of, assessment_id)
            if not position
            else cutoff(
                db,
                creator.creator_id,
                now,
                position.as_of if assessment_id is None else None,
                assessment_id,
            )
        )
        if position and position.as_of != effective:
            raise ApiError(422, "invalid_evidence_cursor", "The evidence cursor cutoff changed.")
        query = select(CanonicalPost).where(*visible(creator.creator_id, effective))
        if position:
            query = query.where(
                or_(
                    CanonicalPost.published_at < position.published_at,
                    and_(
                        CanonicalPost.published_at == position.published_at,
                        CanonicalPost.id < position.id,
                    ),
                )
            )
        posts = list(
            db.scalars(
                query.order_by(CanonicalPost.published_at.desc(), CanonicalPost.id.desc()).limit(
                    limit + 1
                )
            )
        )
        next_cursor = None
        if len(posts) > limit:
            last = posts[limit - 1]
            next_cursor = base64.urlsafe_b64encode(
                Cursor(
                    owner=creator.creator_id,
                    as_of=effective,
                    assessment_id=assessment_id,
                    published_at=last.published_at,
                    id=last.id,
                )
                .model_dump_json()
                .encode()
            ).decode()
        return EvidencePage(
            items=build_evidence(db, creator.creator_id, posts[:limit], effective, now),
            as_of=effective,
            assessment_id=assessment_id,
            next_cursor=next_cursor,
        )
    except SQLAlchemyError as exc:
        raise store_error() from exc


@router.get("/evidence", response_model=EvidencePage, responses=_ERRORS)
def batch_posts(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
    now: Annotated[datetime, Depends(get_current_time)],
    post_ids: Annotated[list[UUID], Query(min_length=1, max_length=50)],
    as_of: AwareDatetime | None = None,
    assessment_id: UUID | None = None,
) -> EvidencePage:
    try:
        effective = cutoff(db, creator.creator_id, now, as_of, assessment_id)
        posts = list(
            db.scalars(
                select(CanonicalPost)
                .where(*visible(creator.creator_id, effective), CanonicalPost.id.in_(post_ids))
                .order_by(CanonicalPost.published_at.desc(), CanonicalPost.id.desc())
            )
        )
        return EvidencePage(
            items=build_evidence(db, creator.creator_id, posts, effective, now),
            as_of=effective,
            assessment_id=assessment_id,
        )
    except SQLAlchemyError as exc:
        raise store_error() from exc


@router.get("/posts/{post_id}", response_model=PostEvidence, responses=_ERRORS)
def get_post(
    post_id: UUID,
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
    now: Annotated[datetime, Depends(get_current_time)],
    as_of: AwareDatetime | None = None,
    assessment_id: UUID | None = None,
) -> PostEvidence:
    try:
        effective = cutoff(db, creator.creator_id, now, as_of, assessment_id)
        post = db.scalar(
            select(CanonicalPost).where(
                *visible(creator.creator_id, effective), CanonicalPost.id == post_id
            )
        )
        if post is None:
            raise ApiError(
                404, "history_post_not_found", "The requested history post was not found."
            )
        return build_evidence(db, creator.creator_id, [post], effective, now)[0]
    except SQLAlchemyError as exc:
        raise store_error() from exc


@router.get("/imports", response_model=ImportPage, responses=_ERRORS)
def list_imports(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> ImportPage:
    try:
        rows = list(
            db.scalars(
                select(CreatorHistoryImport)
                .where(CreatorHistoryImport.creator_id == creator.creator_id)
                .order_by(CreatorHistoryImport.started_at.desc(), CreatorHistoryImport.id.desc())
                .limit(limit + 1)
            )
        )
        return ImportPage(
            items=tuple(
                ImportStatus(
                    import_id=r.import_id,
                    status=cast(Literal["running", "complete", "partial", "unavailable"], r.status),
                    requested_posts=r.requested_posts,
                    imported_posts=r.imported_posts,
                    pages_read=r.pages_read,
                    next_page_available=r.next_page_available,
                    started_at=r.started_at,
                    completed_at=r.completed_at,
                    source=source_kind(r.source),
                )
                for r in rows[:limit]
            ),
            truncated=len(rows) > limit,
        )
    except SQLAlchemyError as exc:
        raise store_error() from exc
