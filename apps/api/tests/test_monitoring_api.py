"""Focused read-only coverage for the creator monitoring lifecycle contract."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_outlooks import observation
from test_outlooks import request as outlook_request

from bipme.api.analysis import _build_api_response
from bipme.api.app import create_app
from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
)
from bipme.api.schemas import AcceptedHypothesis
from bipme.intelligence.outlooks import build_distribution_outlook
from bipme.persistence.base import Base
from bipme.persistence.models import (
    CanonicalPost,
    Creator,
    CreatorProcessingPermission,
    DraftAssessment,
    OutcomeObservationRecord,
    ScheduledJob,
)

CREATOR_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_CREATOR_ID = UUID("22222222-2222-4222-8222-222222222222")
ASSESSMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
FOREIGN_ASSESSMENT_ID = UUID("44444444-4444-4444-8444-444444444444")
POST_ID = UUID("55555555-5555-4555-8555-555555555555")
NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


@pytest.fixture
def monitoring_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    tables = [
        Creator.__table__,
        CreatorProcessingPermission.__table__,
        DraftAssessment.__table__,
        CanonicalPost.__table__,
        ScheduledJob.__table__,
        OutcomeObservationRecord.__table__,
    ]
    postgres_only: list[tuple[object, CheckConstraint]] = []
    for table in tables:
        for constraint in list(table.constraints):
            if isinstance(constraint, CheckConstraint) and any(
                marker in str(constraint.sqltext) for marker in ("jsonb_typeof", "left(")
            ):
                postgres_only.append((table, constraint))
                table.constraints.remove(constraint)
    try:
        Base.metadata.create_all(engine, tables=tables)
    finally:
        for table, constraint in postgres_only:
            table.constraints.add(constraint)

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    outlook = build_distribution_outlook(
        outlook_request(
            matches=(str(POST_ID),),
            outcomes=(
                observation(
                    str(POST_ID),
                    10.0,
                    published_at=NOW - timedelta(hours=1),
                    observed_at=NOW - timedelta(minutes=30),
                ),
            ),
        )
    )
    outlook = outlook.__class__(**{**outlook.__dict__, "assessment_id": str(ASSESSMENT_ID)})
    hypothesis = AcceptedHypothesis(
        question="Will this format improve impressions?",
        metric="impressions",
        metric_definition="impressions-v1",
        unit="impressions",
        window_kind="age_aligned",
        window_key="age:24h",
        expected_direction="higher",
    )
    response = _build_api_response(
        outlook, assessed_at=NOW - timedelta(days=1), accepted_hypothesis=hypothesis
    )
    snapshot = response.model_dump(mode="json")
    with factory() as db:
        db.add_all((Creator(id=CREATOR_ID), Creator(id=OTHER_CREATOR_ID)))
        db.add(
            CreatorProcessingPermission(
                creator_id=CREATOR_ID,
                revision=1,
                source_kind="personal_history",
                allowed=True,
                policy_version="synthetic-test",
                recorded_at=NOW - timedelta(days=1),
            )
        )
        db.add_all(
            (
                DraftAssessment(
                    id=ASSESSMENT_ID,
                    creator_id=CREATOR_ID,
                    assessment_key="monitoring-test",
                    assessed_at=NOW - timedelta(days=1),
                    content_fingerprint=outlook.content_fingerprint,
                    outlook_version="distribution-outlook-v1",
                    decision_snapshot=snapshot,
                    accepted_hypothesis=hypothesis.model_dump(mode="json"),
                ),
                DraftAssessment(
                    id=FOREIGN_ASSESSMENT_ID,
                    creator_id=OTHER_CREATOR_ID,
                    assessment_key="foreign-monitoring-test",
                    assessed_at=NOW - timedelta(days=1),
                    content_fingerprint=outlook.content_fingerprint,
                    outlook_version="distribution-outlook-v1",
                    decision_snapshot={**snapshot, "assessment_id": str(FOREIGN_ASSESSMENT_ID)},
                    accepted_hypothesis=hypothesis.model_dump(mode="json"),
                ),
                CanonicalPost(
                    id=POST_ID,
                    creator_id=CREATOR_ID,
                    platform="x",
                    external_post_id="987654321",
                    published_at=NOW - timedelta(hours=1),
                    availability="available",
                    topology="original",
                    source="x_authorized_publication_verification",
                    source_assessment_id=ASSESSMENT_ID,
                    version_match_state="match",
                    provenance={},
                ),
            )
        )
        windows = (
            ("age:5m", None, None),
            ("age:15m", "succeeded", None),
            ("age:30m", "cancelled", "window_missed"),
            ("age:1h", "cancelled", "budget_exhausted"),
            ("age:2h", "revoked", "connection_unavailable"),
            ("age:6h", "needs_reconciliation", "ambiguous_billing"),
            ("age:24h", "failed", "rate_limited"),
        )
        for index, (window_key, outcome, failure_code) in enumerate(windows):
            window_seconds = {
                "age:5m": 5 * 60,
                "age:15m": 15 * 60,
                "age:30m": 30 * 60,
                "age:1h": 60 * 60,
                "age:2h": 2 * 60 * 60,
                "age:6h": 6 * 60 * 60,
                "age:24h": 24 * 60 * 60,
            }[window_key]
            due = NOW - timedelta(hours=1) + timedelta(seconds=window_seconds)
            db.add(
                ScheduledJob(
                    creator_id=CREATOR_ID,
                    idempotency_key=f"post-observation:{POST_ID}:{window_key}",
                    handler_name="bipme.jobs.metric_snapshot",
                    arguments={
                        "post_id": str(POST_ID),
                        "external_post_id": "987654321",
                        "window_key": window_key,
                        "window_seconds": window_seconds,
                        "scheduled_at_epoch": int(due.timestamp()),
                    },
                    input_digest=(f"{index:064x}"),
                    scheduled_at=due,
                    finished_at=NOW if outcome else None,
                    outcome=outcome,
                    failure_code=failure_code,
                )
            )
        db.add_all(
            (
                OutcomeObservationRecord(
                    post_id=POST_ID,
                    creator_id=CREATOR_ID,
                    published_at=NOW - timedelta(hours=1),
                    metric_name="impressions",
                    metric_definition="impressions-v1",
                    metric_unit="impressions",
                    metric_value=Decimal("42"),
                    state="observed",
                    window_kind="age_aligned",
                    window_key="age:15m",
                    observed_at=NOW - timedelta(minutes=40),
                    idempotency_key=f"x-post-observation:{POST_ID}:age:15m:impressions",
                    provenance={
                        "source": "x_authorized_post_metrics",
                        "endpoint": "/2/tweets/{id}",
                        "scheduled_at": (
                            NOW - timedelta(hours=1) + timedelta(minutes=15)
                        ).isoformat(),
                        "window_key": "age:15m",
                        "observed_age_seconds": 20 * 60,
                    },
                ),
                OutcomeObservationRecord(
                    post_id=POST_ID,
                    creator_id=CREATOR_ID,
                    published_at=NOW - timedelta(hours=1),
                    metric_name="likes",
                    metric_definition="likes-v1",
                    metric_unit="likes",
                    metric_value=None,
                    state="missing",
                    window_kind="age_aligned",
                    window_key="age:15m",
                    observed_at=NOW - timedelta(minutes=40),
                    idempotency_key=f"x-post-observation:{POST_ID}:age:15m:likes",
                    provenance={
                        "source": "x_authorized_post_metrics",
                        "endpoint": "/2/tweets/{id}",
                        "scheduled_at": (
                            NOW - timedelta(hours=1) + timedelta(minutes=15)
                        ).isoformat(),
                        "window_key": "age:15m",
                        "observed_age_seconds": 20 * 60,
                        "missing_reason": "not_returned",
                    },
                ),
            )
        )
        db.commit()

    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "true")
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT", "2025-12-01T00:00:00Z")
    app = create_app()
    app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(CREATOR_ID)
    app.dependency_overrides[get_current_time] = lambda: NOW

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db_session] = override_db
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def test_monitoring_returns_windows_states_and_actual_observation_time(monitoring_api) -> None:
    client, factory = monitoring_api
    with factory() as db:
        before_jobs = db.scalars(select(ScheduledJob)).all()
        before_observations = db.scalars(select(OutcomeObservationRecord)).all()

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/monitoring")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assessment_id"] == str(ASSESSMENT_ID)
    assert body["published_post"]["external_post_id"] == "987654321"
    windows = {item["window_key"]: item for item in body["windows"]}
    assert set(windows) == {
        "age:5m",
        "age:15m",
        "age:30m",
        "age:1h",
        "age:2h",
        "age:6h",
        "age:12h",
        "age:24h",
    }
    assert windows["age:5m"]["execution_state"] == "pending"
    assert windows["age:15m"]["execution_state"] == "completed"
    observations = {item["metric"]: item for item in windows["age:15m"]["observations"]}
    assert observations["impressions"]["observed_at"] == (
        NOW - timedelta(minutes=40)
    ).isoformat().replace("+00:00", "Z")
    assert Decimal(observations["impressions"]["value"]) == Decimal("42")
    assert observations["likes"]["state"] == "missing"
    assert windows["age:30m"]["execution_state"] == "missed"
    assert windows["age:1h"]["execution_state"] == "budget_blocked"
    assert windows["age:2h"]["execution_state"] == "unavailable"
    assert windows["age:6h"]["execution_state"] == "needs_reconciliation"
    assert windows["age:12h"]["execution_state"] == "not_scheduled"
    assert windows["age:24h"]["execution_state"] == "rate_limited"
    assert windows["age:15m"]["scheduled_at"] != observations["impressions"]["observed_at"]

    with factory() as db:
        assert len(db.scalars(select(ScheduledJob)).all()) == len(before_jobs)
        assert len(db.scalars(select(OutcomeObservationRecord)).all()) == len(before_observations)


def test_monitoring_hides_foreign_assessment(monitoring_api) -> None:
    client, _ = monitoring_api
    response = client.get(
        f"/api/v1/creators/me/draft-assessments/{FOREIGN_ASSESSMENT_ID}/monitoring"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "assessment_not_found"


def test_monitoring_reports_pending_without_publication(monitoring_api) -> None:
    client, factory = monitoring_api
    with factory.begin() as db:
        post = db.get(CanonicalPost, POST_ID)
        assert post is not None
        db.delete(post)

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/monitoring")
    assert response.status_code == 200
    assert response.json()["state"] == "publication_pending"
    assert response.json()["windows"] == []


def test_monitoring_withholds_observations_after_permission_revocation(monitoring_api) -> None:
    client, factory = monitoring_api
    with factory.begin() as db:
        db.add(
            CreatorProcessingPermission(
                creator_id=CREATOR_ID,
                revision=2,
                source_kind="personal_history",
                allowed=False,
                policy_version="synthetic-revocation",
                recorded_at=NOW - timedelta(minutes=1),
            )
        )

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/monitoring")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "monitoring_unavailable"
    assert all(not window["observations"] for window in body["windows"])
    assert "permission or source policy" in body["limitations"][0]


def test_monitoring_ignores_malformed_receipts_without_inventing_window_state(
    monitoring_api,
) -> None:
    client, factory = monitoring_api
    with factory.begin() as db:
        receipt = db.scalar(select(ScheduledJob).where(ScheduledJob.creator_id == CREATOR_ID))
        assert receipt is not None
        receipt.arguments = {**receipt.arguments, "window_key": "unexpected-window"}

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/monitoring")
    assert response.status_code == 200
    body = response.json()
    assert "unrecognized window" in " ".join(body["limitations"])
    assert all(window["window_key"] != "unexpected-window" for window in body["windows"])


def test_monitoring_validates_receipt_identity_and_due_time(monitoring_api) -> None:
    client, factory = monitoring_api
    with factory.begin() as db:
        receipt = db.scalar(
            select(ScheduledJob).where(
                ScheduledJob.creator_id == CREATOR_ID,
                ScheduledJob.idempotency_key == f"post-observation:{POST_ID}:age:15m",
            )
        )
        assert receipt is not None
        receipt.arguments = {**receipt.arguments, "window_seconds": 300}

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/monitoring")
    assert response.status_code == 200
    body = response.json()
    window = next(item for item in body["windows"] if item["window_key"] == "age:15m")
    assert window["execution_state"] == "not_scheduled"
    assert window["receipt_id"] is None
    assert "integrity validation" in " ".join(body["limitations"])


def test_monitoring_allowlists_missing_reason_and_observation_identity(monitoring_api) -> None:
    client, factory = monitoring_api
    with factory.begin() as db:
        observation_row = db.scalar(
            select(OutcomeObservationRecord).where(OutcomeObservationRecord.metric_name == "likes")
        )
        assert observation_row is not None
        observation_row.provenance = {
            **observation_row.provenance,
            "missing_reason": "provider-secret-detail",
        }
        db.add(
            OutcomeObservationRecord(
                post_id=POST_ID,
                creator_id=CREATOR_ID,
                published_at=NOW - timedelta(hours=1),
                metric_name="retweets",
                metric_definition="retweets-v1",
                metric_unit="count",
                metric_value=Decimal("9"),
                state="observed",
                window_kind="mature_cumulative",
                window_key="age:15m",
                observed_at=NOW - timedelta(minutes=40),
                idempotency_key=f"x-post-observation:{POST_ID}:age:15m:retweets",
                provenance={
                    "source": "x_authorized_post_metrics",
                    "endpoint": "/2/tweets/{id}",
                    "scheduled_at": (NOW - timedelta(minutes=45)).isoformat(),
                    "window_key": "age:15m",
                    "observed_age_seconds": 20 * 60,
                },
            )
        )

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/monitoring")
    assert response.status_code == 200
    body = response.json()
    observations = next(item for item in body["windows"] if item["window_key"] == "age:15m")[
        "observations"
    ]
    by_metric = {item["metric"]: item for item in observations}
    assert by_metric["likes"]["missing_reason"] is None
    assert "retweets" not in by_metric


def test_monitoring_auth_failure_uses_standard_error_contract(monitoring_api) -> None:
    client, _ = monitoring_api
    from bipme.api.errors import ApiError

    client.app.dependency_overrides[get_authenticated_creator] = lambda: (_ for _ in ()).throw(
        ApiError(401, "session_invalid", "The creator session is no longer valid.")
    )
    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/monitoring")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_invalid"


def test_monitoring_openapi_is_typed_and_read_only() -> None:
    from bipme.api.app import create_app

    operation = create_app().openapi()["paths"][
        "/api/v1/creators/me/draft-assessments/{assessment_id}/monitoring"
    ]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/MonitoringReadResponse"
    )
    assert "401" in operation["responses"]
