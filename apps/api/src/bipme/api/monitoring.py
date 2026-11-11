"""Read-only creator monitoring lifecycle and metric observation API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from bipme.api.creator_reports import _latest_permission, _x_history_policy_verified_at
from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
)
from bipme.api.errors import ApiError
from bipme.api.evidence import KNOWN_X_SOURCES
from bipme.api.schemas import DraftAnalysisResponse, ErrorResponse, StrictModel
from bipme.jobs.metric_snapshots import HANDLER_NAME, OBSERVATION_WINDOWS
from bipme.persistence.models import (
    CanonicalPost,
    DraftAssessment,
    OutcomeObservationRecord,
    ScheduledJob,
)

router = APIRouter(prefix="/api/v1/creators/me", tags=["monitoring"])

MonitoringState = Literal[
    "publication_pending",
    "publication_unavailable",
    "monitoring_unavailable",
    "monitoring_pending",
    "monitoring_running",
    "monitoring_partial",
    "monitoring_complete",
    "needs_reconciliation",
]
ExecutionState = Literal[
    "not_scheduled",
    "pending",
    "running",
    "completed",
    "skipped",
    "missed",
    "cancelled",
    "unavailable",
    "rate_limited",
    "budget_blocked",
    "needs_reconciliation",
    "failed",
    "unknown",
]
MeasurementState = Literal["not_available", "partial", "available"]


class MonitoringPublicationResponse(StrictModel):
    canonical_post_id: UUID
    external_post_id: str
    published_at: datetime
    availability: Literal["available", "unavailable", "deleted"]
    version_match_state: Literal["match", "mismatch", "unknown"]


class MonitoringObservationResponse(StrictModel):
    id: UUID
    metric: str = Field(min_length=1, max_length=100)
    metric_definition: str = Field(min_length=1, max_length=255)
    unit: str = Field(min_length=1, max_length=64)
    value: float | None
    state: Literal["observed", "missing", "invalid"]
    published_at: datetime
    observed_at: datetime
    observed_age_seconds: float
    window_kind: Literal["mature_cumulative", "age_aligned"]
    window_key: str = Field(min_length=1, max_length=100)
    source: Literal["authorized_x_api", "unknown"]
    missing_reason: str | None = None


class MonitoringWindowResponse(StrictModel):
    window_kind: Literal["age_aligned"] = "age_aligned"
    window_key: str
    due_at: datetime
    scheduled_at: datetime | None
    finished_at: datetime | None
    execution_state: ExecutionState
    measurement_state: MeasurementState
    failure_code: str | None
    receipt_id: UUID | None
    observations: tuple[MonitoringObservationResponse, ...]


class MonitoringReadResponse(StrictModel):
    state: MonitoringState
    assessment_id: UUID
    assessed_at: datetime
    original_outlook: DraftAnalysisResponse
    published_post: MonitoringPublicationResponse | None
    windows: tuple[MonitoringWindowResponse, ...]
    limitations: tuple[str, ...] = Field(default=())


_PUBLIC_FAILURE_CODES = {
    "window_missed",
    "window_skipped",
    "skipped",
    "budget_exhausted",
    "external_gate_unverified",
    "connection_unavailable",
    "reauthorization_required",
    "permission_denied",
    "ambiguous_billing",
    "duplicate_request",
    "cached_evidence_invalid",
    "rate_limited",
    "post_unavailable",
    "post_not_found",
    "retry_limit_exhausted",
    "handler_outcome_uncertain",
    "worker_lost_during_billable_operation",
}


def _safe_failure_code(value: str | None) -> str | None:
    if value is None:
        return None
    return value if value in _PUBLIC_FAILURE_CODES else "job_failed"


def _execution_state(receipt: ScheduledJob, runner_status: str | None) -> ExecutionState:
    failure = receipt.failure_code
    if receipt.outcome == "succeeded":
        return "completed"
    if receipt.outcome == "needs_reconciliation":
        return "needs_reconciliation"
    if receipt.outcome == "revoked":
        return "unavailable"
    if receipt.outcome == "cancelled":
        if failure in {"window_skipped", "skipped"}:
            return "skipped"
        if failure == "window_missed":
            return "missed"
        if failure in {"budget_exhausted", "external_gate_unverified"}:
            return "budget_blocked"
        if failure in {"connection_unavailable", "reauthorization_required", "permission_denied"}:
            return "unavailable"
        return "cancelled"
    if receipt.outcome == "failed":
        if failure == "rate_limited":
            return "rate_limited"
        if failure in {"ambiguous_billing", "duplicate_request", "cached_evidence_invalid"}:
            return "needs_reconciliation"
        return "failed"
    if runner_status == "doing":
        return "running"
    if runner_status == "failed":
        return "failed"
    if runner_status in {"todo", "succeeded"} or runner_status is None:
        return "pending"
    return "unknown"


def _runner_status(db: Session, runner_job_id: int | None) -> str | None:
    if runner_job_id is None:
        return None
    try:
        row = (
            db.execute(
                text("SELECT status::text AS status FROM procrastinate_jobs WHERE id = :job_id"),
                {"job_id": runner_job_id},
            )
            .mappings()
            .one_or_none()
        )
    except SQLAlchemyError:
        # A receipt remains useful when the optional queue table is temporarily
        # unavailable; never turn that into a fabricated terminal state.
        db.rollback()
        return None
    return None if row is None else str(row["status"])


def _publication(post: CanonicalPost) -> MonitoringPublicationResponse:
    return MonitoringPublicationResponse(
        canonical_post_id=post.id,
        external_post_id=post.external_post_id,
        published_at=post.published_at,
        availability=cast(Literal["available", "unavailable", "deleted"], post.availability),
        version_match_state=cast(
            Literal["match", "mismatch", "unknown"], post.version_match_state or "unknown"
        ),
    )


def _source(provenance: object) -> Literal["authorized_x_api", "unknown"]:
    if isinstance(provenance, dict) and str(provenance.get("source", "")).startswith("x"):
        return "authorized_x_api"
    return "unknown"


def _observation(
    row: OutcomeObservationRecord, post: CanonicalPost
) -> MonitoringObservationResponse:
    provenance = row.provenance if isinstance(row.provenance, dict) else {}
    raw_missing_reason = provenance.get("missing_reason")
    return MonitoringObservationResponse(
        id=row.id,
        metric=row.metric_name,
        metric_definition=row.metric_definition,
        unit=row.metric_unit,
        value=float(row.metric_value) if row.metric_value is not None else None,
        state=cast(Literal["observed", "missing", "invalid"], row.state),
        published_at=row.published_at,
        observed_at=row.observed_at,
        observed_age_seconds=(row.observed_at - post.published_at).total_seconds(),
        window_kind=cast(Literal["mature_cumulative", "age_aligned"], row.window_kind),
        window_key=row.window_key,
        source=_source(provenance),
        missing_reason=str(raw_missing_reason) if raw_missing_reason is not None else None,
    )


def _top_level_state(windows: tuple[MonitoringWindowResponse, ...]) -> MonitoringState:
    states = {item.execution_state for item in windows}
    if "needs_reconciliation" in states:
        return "needs_reconciliation"
    if "running" in states:
        return "monitoring_running"
    if states <= {"not_scheduled", "pending"}:
        return "monitoring_pending"
    if windows and all(item.execution_state == "completed" for item in windows):
        return "monitoring_complete"
    return "monitoring_partial"


def _snapshot(assessment: DraftAssessment) -> DraftAnalysisResponse:
    try:
        return DraftAnalysisResponse.model_validate(
            {
                key: value
                for key, value in assessment.decision_snapshot.items()
                if key != "_cod361_linking"
            }
        )
    except (ValidationError, TypeError, ValueError, KeyError) as exc:
        raise ApiError(
            503, "assessment_snapshot_invalid", "The saved assessment is unavailable."
        ) from exc


@router.get(
    "/draft-assessments/{assessment_id}/monitoring",
    response_model=MonitoringReadResponse,
    summary="Read creator-scoped monitoring receipts and observations",
    description=(
        "Reads only the authenticated creator's persisted assessment, publication, durable "
        "monitoring receipts and outcome observations. This GET never calls X, enqueues work, "
        "reserves usage or mutates persisted state."
    ),
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def read_monitoring(
    assessment_id: UUID,
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
    now: Annotated[datetime, Depends(get_current_time)],
) -> MonitoringReadResponse:
    try:
        assessment = db.scalar(
            select(DraftAssessment).where(
                DraftAssessment.id == assessment_id,
                DraftAssessment.creator_id == creator.creator_id,
            )
        )
        if assessment is None:
            raise ApiError(404, "assessment_not_found", "The requested assessment was not found.")
        outlook = _snapshot(assessment)
        post = db.scalar(
            select(CanonicalPost).where(
                CanonicalPost.source_assessment_id == assessment.id,
                CanonicalPost.creator_id == creator.creator_id,
                CanonicalPost.platform == "x",
            )
        )
        if post is None:
            return MonitoringReadResponse(
                state="publication_pending",
                assessment_id=assessment.id,
                assessed_at=assessment.assessed_at,
                original_outlook=outlook,
                published_post=None,
                windows=(),
                limitations=("No linked publication is available yet.",),
            )
        publication = _publication(post)
        if post.availability != "available":
            return MonitoringReadResponse(
                state="publication_unavailable",
                assessment_id=assessment.id,
                assessed_at=assessment.assessed_at,
                original_outlook=outlook,
                published_post=publication,
                windows=(),
                limitations=("The linked publication is unavailable.",),
            )

        permission = _latest_permission(db, creator.creator_id)
        monitoring_allowed = bool(
            permission
            and permission.allowed
            and permission.recorded_at <= now
            and _x_history_policy_verified_at(now) is not None
            and post.source in KNOWN_X_SOURCES
        )
        jobs = db.scalars(
            select(ScheduledJob)
            .where(
                ScheduledJob.creator_id == creator.creator_id,
                ScheduledJob.handler_name == HANDLER_NAME,
            )
            .order_by(ScheduledJob.scheduled_at, ScheduledJob.id)
        ).all()
        jobs_by_window: dict[str, ScheduledJob] = {}
        limitations: list[str] = []
        for job in jobs:
            if not isinstance(job.arguments, dict) or job.arguments.get("post_id") != str(post.id):
                continue
            window_key = job.arguments.get("window_key")
            if not isinstance(window_key, str) or window_key not in {
                item.key for item in OBSERVATION_WINDOWS
            }:
                limitations.append("A stored monitoring receipt had an unrecognized window.")
                continue
            jobs_by_window.setdefault(window_key, job)

        rows: list[OutcomeObservationRecord] = []
        if monitoring_allowed:
            rows = list(
                db.scalars(
                    select(OutcomeObservationRecord)
                    .where(
                        OutcomeObservationRecord.creator_id == creator.creator_id,
                        OutcomeObservationRecord.post_id == post.id,
                    )
                    .order_by(
                        OutcomeObservationRecord.observed_at,
                        OutcomeObservationRecord.id,
                    )
                ).all()
            )
        else:
            limitations.append(
                "Metric observations are withheld because current permission or source policy does not allow monitoring reads."
            )

        observations_by_window: dict[str, list[MonitoringObservationResponse]] = {}
        for row in rows:
            try:
                observation = _observation(row, post)
            except (ValidationError, TypeError, ValueError):
                limitations.append("A stored metric observation was malformed and was withheld.")
                continue
            observations_by_window.setdefault(observation.window_key, []).append(observation)

        windows: list[MonitoringWindowResponse] = []
        for window in OBSERVATION_WINDOWS:
            receipt = jobs_by_window.get(window.key)
            observations = tuple(observations_by_window.get(window.key, ()))
            measurement_state: MeasurementState = (
                "not_available"
                if not observations
                else "partial"
                if any(item.state != "observed" for item in observations)
                else "available"
            )
            if receipt is None:
                execution_state: ExecutionState = "not_scheduled"
                scheduled_at = None
                finished_at = None
                failure_code = None
                receipt_id = None
            else:
                execution_state = _execution_state(
                    receipt, _runner_status(db, receipt.runner_job_id)
                )
                scheduled_at = receipt.scheduled_at
                finished_at = receipt.finished_at
                failure_code = _safe_failure_code(receipt.failure_code)
                receipt_id = receipt.id
            due_at = post.published_at.astimezone(UTC) + window.offset
            windows.append(
                MonitoringWindowResponse(
                    window_key=window.key,
                    due_at=due_at,
                    scheduled_at=scheduled_at,
                    finished_at=finished_at,
                    execution_state=execution_state,
                    measurement_state=measurement_state,
                    failure_code=failure_code,
                    receipt_id=receipt_id,
                    observations=observations,
                )
            )
        if not monitoring_allowed:
            state: MonitoringState = "monitoring_unavailable"
        else:
            state = _top_level_state(tuple(windows))
        return MonitoringReadResponse(
            state=state,
            assessment_id=assessment.id,
            assessed_at=assessment.assessed_at,
            original_outlook=outlook,
            published_post=publication,
            windows=tuple(windows),
            limitations=tuple(dict.fromkeys(limitations)),
        )
    except ApiError:
        raise
    except SQLAlchemyError as exc:
        raise ApiError(
            503, "monitoring_store_unavailable", "Monitoring data is temporarily unavailable."
        ) from exc
