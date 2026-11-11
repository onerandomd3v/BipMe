"""Read-only creator monitoring lifecycle and metric observation API."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends
from procrastinate.jobs import Status
from pydantic import Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from bipme.api.creator_reports import _latest_permission
from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
)
from bipme.api.errors import ApiError
from bipme.api.schemas import DraftAnalysisResponse, ErrorResponse, StrictModel
from bipme.api.source_policy import KNOWN_X_SOURCES, x_history_policy_verified_at
from bipme.jobs.metric_snapshots import HANDLER_NAME, OBSERVATION_WINDOWS
from bipme.jobs.service import QUEUE, TASK_NAME
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
    value: Decimal | None
    state: Literal["observed", "missing", "invalid"]
    published_at: datetime
    observed_at: datetime
    observed_age_seconds: float
    window_kind: Literal["mature_cumulative", "age_aligned"]
    window_key: str = Field(min_length=1, max_length=100)
    source: Literal["authorized_x_api", "unknown"]
    missing_reason: Literal["not_returned", "invalid_value"] | None = None


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

_PUBLIC_MISSING_REASONS = {"not_returned", "invalid_value"}
_METRIC_SOURCE = "x_authorized_post_metrics"
_METRIC_SOURCE_ENDPOINT = "/2/tweets/{id}"
_WINDOWS_BY_KEY = {window.key: window for window in OBSERVATION_WINDOWS}
_KNOWN_RUNNER_STATUSES = {status.value for status in Status}


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
    if receipt.outcome is None:
        if runner_status == Status.DOING.value:
            return "running"
        if runner_status == Status.TODO.value:
            return "pending"
    return "unknown"


def _runner_status(db: Session, receipt: ScheduledJob) -> str:
    runner_job_id = receipt.runner_job_id
    if runner_job_id is None:
        return "unknown"
    try:
        row = (
            db.execute(
                text(
                    "SELECT id, queue_name, task_name, args, status::text AS status "
                    "FROM procrastinate_jobs WHERE id = :job_id"
                ),
                {"job_id": runner_job_id},
            )
            .mappings()
            .one_or_none()
        )
    except SQLAlchemyError:
        # A receipt remains useful when the optional queue table is temporarily
        # unavailable; never turn that into a fabricated terminal state.
        db.rollback()
        return "unknown"
    if row is None:
        return "unknown"
    args = row.get("args")
    status = row.get("status")
    if (
        row.get("id") != runner_job_id
        or row.get("queue_name") != QUEUE
        or row.get("task_name") != TASK_NAME
        or not isinstance(args, dict)
        or args.get("receipt_id") != str(receipt.id)
        or not isinstance(status, str)
        or status not in _KNOWN_RUNNER_STATUSES
    ):
        return "unknown"
    return status


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


def _observation(
    row: OutcomeObservationRecord, post: CanonicalPost
) -> MonitoringObservationResponse:
    provenance = row.provenance if isinstance(row.provenance, dict) else {}
    raw_missing_reason = provenance.get("missing_reason")
    missing_reason = (
        cast(Literal["not_returned", "invalid_value"], raw_missing_reason)
        if raw_missing_reason in _PUBLIC_MISSING_REASONS
        else None
    )
    return MonitoringObservationResponse(
        id=row.id,
        metric=row.metric_name,
        metric_definition=row.metric_definition,
        unit=row.metric_unit,
        value=row.metric_value,
        state=cast(Literal["observed", "missing", "invalid"], row.state),
        published_at=row.published_at,
        observed_at=row.observed_at,
        observed_age_seconds=(row.observed_at - post.published_at).total_seconds(),
        window_kind="age_aligned",
        window_key=row.window_key,
        source="authorized_x_api",
        missing_reason=missing_reason,
    )


def _valid_observation(row: OutcomeObservationRecord, post: CanonicalPost) -> bool:
    """Accept only immutable, COD-363 age-aligned observations for this publication."""
    provenance = row.provenance if isinstance(row.provenance, dict) else {}
    window = _WINDOWS_BY_KEY.get(row.window_key)
    if (
        row.creator_id != post.creator_id
        or row.post_id != post.id
        or row.published_at != post.published_at
        or row.window_kind != "age_aligned"
        or window is None
        or provenance.get("source") != _METRIC_SOURCE
        or provenance.get("endpoint") != _METRIC_SOURCE_ENDPOINT
        or provenance.get("window_key") != row.window_key
    ):
        return False
    expected_key = f"x-post-observation:{post.id}:{row.window_key}:{row.metric_name}"
    if row.idempotency_key != expected_key:
        return False
    try:
        scheduled_at = datetime.fromisoformat(str(provenance["scheduled_at"]))
    except (KeyError, TypeError, ValueError):
        return False
    if scheduled_at.tzinfo is None:
        return False
    due_at = post.published_at.astimezone(UTC) + window.offset
    if scheduled_at.astimezone(UTC) != due_at:
        return False
    observed_age = provenance.get("observed_age_seconds")
    if not isinstance(observed_age, (int, float, str)):
        return False
    try:
        if abs(float(observed_age) - (row.observed_at - post.published_at).total_seconds()) > 1e-6:
            return False
    except (TypeError, ValueError):
        return False
    return row.observed_at >= post.published_at


def _valid_receipt(job: ScheduledJob, post: CanonicalPost, window_key: str) -> bool:
    """Validate a durable receipt against the scheduler's canonical identity."""
    window = _WINDOWS_BY_KEY[window_key]
    args = job.arguments
    if not isinstance(args, dict):
        return False
    due_at = post.published_at.astimezone(UTC) + window.offset
    try:
        scheduled_epoch = int(args["scheduled_at_epoch"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return (
        job.handler_name == HANDLER_NAME
        and job.idempotency_key == f"post-observation:{post.id}:{window.key}"
        and args.get("post_id") == str(post.id)
        and args.get("external_post_id") == post.external_post_id
        and args.get("window_key") == window.key
        and args.get("window_seconds") == window.seconds
        and scheduled_epoch == int(due_at.timestamp())
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
            and x_history_policy_verified_at(now) is not None
            and post.source in KNOWN_X_SOURCES
        )
        expected_keys = [
            f"post-observation:{post.id}:{window.key}" for window in OBSERVATION_WINDOWS
        ]
        jobs = db.scalars(
            select(ScheduledJob)
            .where(
                ScheduledJob.creator_id == creator.creator_id,
                ScheduledJob.handler_name == HANDLER_NAME,
                ScheduledJob.idempotency_key.in_(expected_keys),
            )
            .order_by(ScheduledJob.scheduled_at, ScheduledJob.id)
        ).all()
        jobs_by_window: dict[str, ScheduledJob] = {}
        limitations: list[str] = []
        for job in jobs:
            window_key = (
                job.arguments.get("window_key") if isinstance(job.arguments, dict) else None
            )
            if not isinstance(window_key, str) or window_key not in _WINDOWS_BY_KEY:
                limitations.append("A stored monitoring receipt had an unrecognized window.")
                continue
            if not _valid_receipt(job, post, window_key):
                limitations.append("A stored monitoring receipt failed integrity validation.")
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
                        OutcomeObservationRecord.published_at == post.published_at,
                        OutcomeObservationRecord.window_kind == "age_aligned",
                        OutcomeObservationRecord.window_key.in_(tuple(_WINDOWS_BY_KEY)),
                        OutcomeObservationRecord.observed_at <= now,
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
            if not _valid_observation(row, post):
                limitations.append("A stored metric observation failed integrity validation.")
                continue
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
                execution_state = _execution_state(receipt, _runner_status(db, receipt))
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
