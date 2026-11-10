"""COD-363 scheduling and durable-worker handler for post metric snapshots."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from procrastinate import App
from sqlalchemy import select
from sqlalchemy.orm import Session

from bipme.auth.config import AuthSettings
from bipme.auth.crypto import TokenCipher
from bipme.integrations.x_metric_snapshots import (
    SNAPSHOT_OPERATION,
    HttpXPostMetricsProvider,
    XMetricSnapshot,
    XMetricSnapshotReader,
    XMetricSnapshotSettings,
    XMetricSnapshotUnavailable,
)
from bipme.jobs.runtime import (
    JobRuntime,
    JobRuntimeSettings,
    RetryableHandlerError,
    TerminalJobError,
    create_runtime,
)
from bipme.jobs.service import schedule_job
from bipme.persistence.models import (
    APIUsageLedger,
    CanonicalPost,
    CreatorPlatformIdentity,
    OutcomeObservationRecord,
    ScheduledJob,
    XAccountConnection,
)

HANDLER_NAME = "bipme.jobs.metric_snapshot"
MISSED_WINDOW_GRACE = timedelta(minutes=5)


@dataclass(frozen=True)
class ObservationWindow:
    key: str
    seconds: int

    @property
    def offset(self) -> timedelta:
        return timedelta(seconds=self.seconds)


OBSERVATION_WINDOWS: tuple[ObservationWindow, ...] = (
    ObservationWindow("age:5m", 5 * 60),
    ObservationWindow("age:15m", 15 * 60),
    ObservationWindow("age:30m", 30 * 60),
    ObservationWindow("age:1h", 60 * 60),
    ObservationWindow("age:2h", 2 * 60 * 60),
    ObservationWindow("age:6h", 6 * 60 * 60),
    ObservationWindow("age:12h", 12 * 60 * 60),
    ObservationWindow("age:24h", 24 * 60 * 60),
)


@dataclass
class MetricSnapshotScheduler:
    """Submission facade used by the publication-link route and tests."""

    app: App
    reader: XMetricSnapshotReader
    runtime: JobRuntime | None = None

    def close(self) -> None:
        close = getattr(self.reader.provider, "close", None)
        try:
            if callable(close):
                close()
        finally:
            if self.runtime is not None:
                self.runtime.close()

    def schedule(
        self,
        db: Session,
        *,
        creator_id: UUID,
        post_id: UUID,
        required_x_connection_id: UUID,
        now: datetime,
    ) -> tuple[ScheduledJob, ...]:
        post = db.scalar(
            select(CanonicalPost).where(
                CanonicalPost.id == post_id,
                CanonicalPost.creator_id == creator_id,
                CanonicalPost.platform == "x",
                CanonicalPost.availability == "available",
                CanonicalPost.source_assessment_id.is_not(None),
            )
        )
        if post is None:
            return ()
        instant = now.astimezone(UTC)
        if not self.reader.settings.valid(instant):
            return ()
        connection = db.scalar(
            select(XAccountConnection)
            .join(
                CreatorPlatformIdentity,
                (CreatorPlatformIdentity.id == XAccountConnection.creator_identity_id)
                & (CreatorPlatformIdentity.creator_id == XAccountConnection.creator_id),
            )
            .where(
                XAccountConnection.id == required_x_connection_id,
                XAccountConnection.creator_id == creator_id,
                XAccountConnection.platform == "x",
                XAccountConnection.state == "connected",
                CreatorPlatformIdentity.platform == "x",
                CreatorPlatformIdentity.external_creator_id == self.reader.settings.allowed_user_id,
            )
        )
        if (
            connection is None
            or connection.encrypted_access_token is None
            or not {"tweet.read", "users.read"}.issubset(set(connection.scopes))
            or (
                connection.access_token_expires_at is not None
                and connection.access_token_expires_at <= instant
            )
        ):
            return ()
        attempts = self.reader.provider.max_request_attempts
        unit_cost = self.reader.settings.estimated_cost
        limits = self.reader.settings.limits
        per_post_limit = self.reader.settings.per_post_limit
        if unit_cost is None or limits is None or per_post_limit is None:
            return ()
        estimate = unit_cost * attempts
        budget = _budget_snapshot(
            db, creator_id=creator_id, post_id=post.external_post_id, now=instant
        )
        scheduled: list[ScheduledJob] = []
        for window in OBSERVATION_WINDOWS:
            due = post.published_at.astimezone(UTC) + window.offset
            if due > instant and not _budget_allows(
                budget,
                estimate=estimate,
                limits=limits,
                per_post_limit=per_post_limit,
            ):
                break
            runner_at = due if due > instant else instant
            job = schedule_job(
                db,
                self.app,
                creator_id=creator_id,
                idempotency_key=f"post-observation:{post.id}:{window.key}",
                handler_name=HANDLER_NAME,
                arguments={
                    "post_id": str(post.id),
                    "external_post_id": post.external_post_id,
                    "window_key": window.key,
                    "window_seconds": window.seconds,
                    "scheduled_at_epoch": int(due.timestamp()),
                },
                scheduled_at=runner_at,
                required_x_connection_id=required_x_connection_id,
                max_attempts=3,
            )
            scheduled.append(job)
            if due > instant:
                budget = _add_budget(budget, estimate)
        return tuple(scheduled)


def _budget_snapshot(
    db: Session, *, creator_id: UUID, post_id: str, now: datetime
) -> dict[str, Decimal]:
    rows = db.scalars(
        select(APIUsageLedger).where(
            APIUsageLedger.creator_id == creator_id,
            APIUsageLedger.provider == "x",
        )
    ).all()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    totals = {
        "total": Decimal("0"),
        "daily": Decimal("0"),
        "operation": Decimal("0"),
        "post": Decimal("0"),
    }
    for row in rows:
        charged = (
            row.actual_cost if row.reconciliation_state == "reconciled" else row.estimated_cost
        )
        if charged is None:
            continue
        totals["total"] += charged
        if row.requested_at >= day_start:
            totals["daily"] += charged
        if row.operation == SNAPSHOT_OPERATION:
            totals["operation"] += charged
            if row.request_metadata.get("post_id") == post_id:
                totals["post"] += charged
    return totals


def _budget_allows(
    budget: dict[str, Decimal],
    *,
    estimate: Decimal,
    limits: object,
    per_post_limit: Decimal | None,
) -> bool:
    if limits is None:
        return False
    total = getattr(limits, "total_usd", None)
    daily = getattr(limits, "daily_usd", None)
    operation = getattr(limits, "operation_usd", None)
    return bool(
        (total is None or budget["total"] + estimate <= total)
        and (daily is None or budget["daily"] + estimate <= daily)
        and (operation is None or budget["operation"] + estimate <= operation)
        and (per_post_limit is None or budget["post"] + estimate <= per_post_limit)
    )


def _add_budget(budget: dict[str, Decimal], estimate: Decimal) -> dict[str, Decimal]:
    return {key: value + estimate for key, value in budget.items()}


def handle_metric_snapshot(
    db: Session, receipt: ScheduledJob, reader: XMetricSnapshotReader
) -> None:
    args = receipt.arguments
    try:
        post_id = UUID(str(args["post_id"]))
        window_key = str(args["window_key"])
        due = datetime.fromtimestamp(int(args["scheduled_at_epoch"]), tz=UTC)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise TerminalJobError("invalid_snapshot_arguments") from None
    post = db.scalar(
        select(CanonicalPost).where(
            CanonicalPost.id == post_id,
            CanonicalPost.creator_id == receipt.creator_id,
            CanonicalPost.platform == "x",
        )
    )
    if post is None or post.availability != "available" or post.source_assessment_id is None:
        raise TerminalJobError("post_unavailable", outcome="cancelled")
    now = datetime.now(UTC)
    if now + timedelta(seconds=1) < due:
        raise RetryableHandlerError("window_not_due")
    if now > due + MISSED_WINDOW_GRACE:
        raise TerminalJobError("window_missed", outcome="cancelled")
    try:
        evidence = reader.observe(
            db,
            creator_id=receipt.creator_id,
            post=post,
            window_key=window_key,
            scheduled_at=due,
            now=now,
        )
    except XMetricSnapshotUnavailable as exc:
        if exc.ambiguous or exc.code in {
            "ambiguous_billing",
            "duplicate_request",
            "cached_evidence_invalid",
        }:
            raise TerminalJobError(exc.code, outcome="needs_reconciliation") from None
        if exc.code in {"connection_unavailable", "reauthorization_required", "permission_denied"}:
            raise TerminalJobError(exc.code, outcome="revoked") from None
        if exc.code in {"budget_exhausted", "external_gate_unverified", "post_unavailable"}:
            raise TerminalJobError(exc.code, outcome="cancelled") from None
        if exc.code == "post_not_found":
            # A provider 404 is not proof that the canonical post was deleted.
            # The handler transaction rolls back on terminal errors, so never
            # mutate availability without an explicit reconciliation transaction.
            raise TerminalJobError(exc.code, outcome="needs_reconciliation") from None
        raise TerminalJobError(exc.code) from None
    _persist_observations(db, receipt, post, window_key, due, evidence)


def _persist_observations(
    db: Session,
    receipt: ScheduledJob,
    post: CanonicalPost,
    window_key: str,
    scheduled_at: datetime,
    evidence: XMetricSnapshot,
) -> None:
    for metric_name, metric in evidence.metrics.items():
        key = f"x-post-observation:{post.id}:{window_key}:{metric_name}"
        existing = db.scalar(
            select(OutcomeObservationRecord).where(
                OutcomeObservationRecord.creator_id == receipt.creator_id,
                OutcomeObservationRecord.idempotency_key == key,
            )
        )
        if existing is not None:
            continue
        state = (
            "observed"
            if metric.value is not None
            else ("invalid" if metric.missing_reason == "invalid_value" else "missing")
        )
        db.add(
            OutcomeObservationRecord(
                post_id=post.id,
                creator_id=receipt.creator_id,
                published_at=post.published_at,
                metric_name=metric_name,
                metric_definition=metric.definition,
                metric_unit=metric.unit,
                metric_value=Decimal(metric.value) if metric.value is not None else None,
                state=state,
                window_kind="age_aligned",
                window_key=window_key,
                observed_at=evidence.observed_at,
                idempotency_key=key,
                provenance={
                    "source": evidence.source,
                    "endpoint": evidence.source_endpoint,
                    "scheduled_at": scheduled_at.astimezone(UTC).isoformat(),
                    "window_key": window_key,
                    "observed_age_seconds": (
                        evidence.observed_at - post.published_at
                    ).total_seconds(),
                    "missing_reason": metric.missing_reason,
                    "request_count": evidence.request_count,
                },
            )
        )


def make_handler(reader: XMetricSnapshotReader) -> Callable[[Session, ScheduledJob], None]:
    def handler(db: Session, receipt: ScheduledJob) -> None:
        handle_metric_snapshot(db, receipt, reader)

    return handler


def build_metric_snapshot_handler() -> Callable[[Session, ScheduledJob], None] | None:
    auth = AuthSettings.from_environment()
    settings = XMetricSnapshotSettings.from_environment()
    if not auth.token_encryption_ready:
        return None
    reader = XMetricSnapshotReader(
        provider=HttpXPostMetricsProvider(),
        cipher=TokenCipher(auth.token_encryption_keys, auth.active_token_key_version or ""),
        settings=settings,
    )
    return make_handler(reader)


def build_metric_snapshot_scheduler() -> MetricSnapshotScheduler | None:
    database_url = os.getenv("BIPME_DATABASE_URL")
    if not database_url:
        return None
    auth = AuthSettings.from_environment()
    settings = XMetricSnapshotSettings.from_environment()
    if not auth.token_encryption_ready or not settings.enabled:
        return None
    reader = XMetricSnapshotReader(
        provider=HttpXPostMetricsProvider(),
        cipher=TokenCipher(auth.token_encryption_keys, auth.active_token_key_version or ""),
        settings=settings,
    )
    # Use the same runtime factory as the worker. It registers TASK_NAME on
    # this producer App, so schedule_job can defer a real dispatch receipt.
    runtime = create_runtime(
        JobRuntimeSettings(database_url=database_url),
        handlers={HANDLER_NAME: make_handler(reader)},
    )
    return MetricSnapshotScheduler(app=runtime.app, reader=reader, runtime=runtime)
