"""Focused HTTP coverage for creator-authenticated persisted postmortems."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_outlooks import AS_OF, observation
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
)

CREATOR_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_CREATOR_ID = UUID("22222222-2222-4222-8222-222222222222")
ASSESSMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
PUBLISHED_ID = UUID("44444444-4444-4444-8444-444444444444")
UNPUBLISHED_ASSESSMENT_ID = UUID("55555555-5555-4555-8555-555555555555")
FOREIGN_ASSESSMENT_ID = UUID("66666666-6666-4666-8666-666666666666")
NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)
WINDOW = "age_aligned:age:24h"
DEFINITION = "impressions-v1|unit=impressions"


@pytest.fixture
def postmortem_api(monkeypatch) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    tables = [
        Creator.__table__,
        CreatorProcessingPermission.__table__,
        DraftAssessment.__table__,
        CanonicalPost.__table__,
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
    with factory() as db:
        db.add_all((Creator(id=CREATOR_ID), Creator(id=OTHER_CREATOR_ID)))
        db.flush()
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
        metric_observations = tuple(
            observation(
                str(uuid5(NAMESPACE_URL, f"history-{index}")),
                float((index + 1) * 10),
                definition=DEFINITION,
                window=WINDOW,
            )
            for index in range(10)
        )
        base = outlook_request(
            matches=tuple(item.post_id for item in metric_observations),
            outcomes=metric_observations,
        )
        outlook = build_distribution_outlook(base)
        outlook = outlook.__class__(**{**outlook.__dict__, "assessment_id": str(ASSESSMENT_ID)})
        accepted_hypothesis = AcceptedHypothesis(
            question="Will this format improve impressions?",
            metric="impressions",
            metric_definition="impressions-v1",
            unit="impressions",
            window_kind="age_aligned",
            window_key="age:24h",
            expected_direction="higher",
        )
        response = _build_api_response(
            outlook, assessed_at=AS_OF, accepted_hypothesis=accepted_hypothesis
        )
        snapshot = response.model_dump(mode="json")
        assessment = DraftAssessment(
            id=ASSESSMENT_ID,
            creator_id=CREATOR_ID,
            assessment_key="postmortem-test",
            assessed_at=AS_OF,
            content_fingerprint=outlook.content_fingerprint,
            outlook_version="distribution-outlook-v1",
            decision_snapshot=snapshot,
            accepted_hypothesis=accepted_hypothesis.model_dump(mode="json"),
        )
        pending_snapshot = {**snapshot, "assessment_id": str(UNPUBLISHED_ASSESSMENT_ID)}
        foreign_snapshot = {**snapshot, "assessment_id": str(FOREIGN_ASSESSMENT_ID)}
        db.add_all(
            (
                assessment,
                DraftAssessment(
                    id=UNPUBLISHED_ASSESSMENT_ID,
                    creator_id=CREATOR_ID,
                    assessment_key="pending-test",
                    assessed_at=AS_OF,
                    content_fingerprint=outlook.content_fingerprint,
                    outlook_version="distribution-outlook-v1",
                    decision_snapshot=pending_snapshot,
                    accepted_hypothesis=accepted_hypothesis.model_dump(mode="json"),
                ),
                DraftAssessment(
                    id=FOREIGN_ASSESSMENT_ID,
                    creator_id=OTHER_CREATOR_ID,
                    assessment_key="foreign-test",
                    assessed_at=AS_OF,
                    content_fingerprint=outlook.content_fingerprint,
                    outlook_version="distribution-outlook-v1",
                    decision_snapshot=foreign_snapshot,
                    accepted_hypothesis=accepted_hypothesis.model_dump(mode="json"),
                ),
            )
        )
        for item in metric_observations:
            post_id = UUID(item.post_id)
            db.add(
                CanonicalPost(
                    id=post_id,
                    creator_id=CREATOR_ID,
                    platform="x",
                    external_post_id=str(post_id.int),
                    published_at=item.published_at,
                    availability="available",
                    topology="original",
                    source="x_creator_authorized_history",
                    provenance={},
                )
            )
            db.add(
                _record(
                    post_id, item.value, item.published_at, item.observed_at, f"history-{post_id}"
                )
            )
        db.add(
            CanonicalPost(
                id=PUBLISHED_ID,
                creator_id=CREATOR_ID,
                platform="x",
                external_post_id="987654321",
                published_at=AS_OF + timedelta(hours=1),
                availability="available",
                topology="original",
                source="x_authorized_publication_verification",
                source_assessment_id=ASSESSMENT_ID,
                version_match_state="match",
                provenance={},
            )
        )
        db.add(
            _record(
                PUBLISHED_ID,
                95.0,
                AS_OF + timedelta(hours=1),
                AS_OF + timedelta(hours=25),
                "published-target",
            )
        )
        db.commit()

    app = create_app()
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "true")
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT", "2026-11-08T00:00:00Z")
    app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(CREATOR_ID)
    app.dependency_overrides[get_current_time] = lambda: NOW

    def override_db() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db_session] = override_db
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def _record(
    post_id: UUID,
    value: float | None,
    published_at: datetime,
    observed_at: datetime,
    key: str,
) -> OutcomeObservationRecord:
    return OutcomeObservationRecord(
        post_id=post_id,
        creator_id=CREATOR_ID,
        published_at=published_at,
        metric_name="impressions",
        metric_definition="impressions-v1",
        metric_unit="impressions",
        metric_value=Decimal(str(value)) if value is not None else None,
        state="observed" if value is not None else "missing",
        window_kind="age_aligned",
        window_key="age:24h",
        observed_at=observed_at,
        idempotency_key=key,
        provenance={},
    )


def test_authenticated_read_returns_persisted_observation_and_equal_age_comparisons(
    postmortem_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = postmortem_api
    with factory() as db:
        before = db.get(DraftAssessment, ASSESSMENT_ID)
        assert before is not None
        original_snapshot = dict(before.decision_snapshot)

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/postmortem")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "evaluated"
    assert body["postmortem"]["version_state"] == "verified"
    comparison = body["postmortem"]["metric_comparisons"][0]
    assert comparison["status"] == "scored"
    assert comparison["observed_at"] == "2026-01-21T13:00:00Z"
    assert comparison["window_kind"] == "age_aligned"
    assert comparison["window_key"] == "age:24h"
    assert comparison["unit"] == "impressions"
    assert comparison["matched_sample_count"] == 10
    assert body["postmortem"]["observed_outcomes"][0]["observed_at"] == comparison["observed_at"]
    assert body["postmortem"]["observed_outcomes"][0]["state"] == "observed"
    assert body["postmortem"]["hypothesis_evaluation"]["status"] == "supported"
    with factory() as db:
        after = db.get(DraftAssessment, ASSESSMENT_ID)
        assert after is not None
        assert after.decision_snapshot == original_snapshot
        assert len(db.scalars(select(OutcomeObservationRecord)).all()) == 11


def test_missing_or_foreign_assessment_is_hidden_and_no_publication_is_explicit(
    postmortem_api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = postmortem_api
    absent = client.get(
        "/api/v1/creators/me/draft-assessments/77777777-7777-4777-8777-777777777777/postmortem"
    )
    assert absent.status_code == 404
    assert absent.json()["error"]["code"] == "assessment_not_found"

    foreign = client.get(
        f"/api/v1/creators/me/draft-assessments/{FOREIGN_ASSESSMENT_ID}/postmortem"
    )
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "assessment_not_found"

    pending = client.get(
        f"/api/v1/creators/me/draft-assessments/{UNPUBLISHED_ASSESSMENT_ID}/postmortem"
    )
    assert pending.status_code == 200
    assert pending.json()["state"] == "publication_pending"
    assert pending.json()["postmortem"] is None


def test_invalid_saved_snapshot_returns_sanitized_unavailable_error(postmortem_api) -> None:
    client, factory = postmortem_api
    with factory.begin() as db:
        assessment = db.get(DraftAssessment, ASSESSMENT_ID)
        assert assessment is not None
        assessment.decision_snapshot = {"corrupt": True}

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/postmortem")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "assessment_snapshot_invalid"
    assert "corrupt" not in response.text


def test_malformed_metric_window_during_response_assembly_is_sanitized(postmortem_api) -> None:
    client, factory = postmortem_api
    with factory.begin() as db:
        assessment = db.get(DraftAssessment, ASSESSMENT_ID)
        assert assessment is not None
        metrics = list(assessment.decision_snapshot["metrics"])
        metrics[0] = {**metrics[0], "window": "malformed"}
        assessment.decision_snapshot = {**assessment.decision_snapshot, "metrics": metrics}

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/postmortem")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "assessment_snapshot_invalid"
    assert "malformed" not in response.text


def test_postmortem_database_failure_returns_sanitized_unavailable_error(postmortem_api) -> None:
    client, _ = postmortem_api

    class FailingSession:
        def scalar(self, *_args, **_kwargs):
            raise SQLAlchemyError("synthetic database failure")

    client.app.dependency_overrides[get_db_session] = lambda: FailingSession()
    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/postmortem")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "postmortem_store_unavailable"
    assert "synthetic database failure" not in response.text


@pytest.mark.parametrize("verification_state", ["mismatch", "unknown"])
def test_unverified_publication_withholds_forecast_accuracy(
    postmortem_api, verification_state
) -> None:
    client, factory = postmortem_api
    with factory.begin() as db:
        post = db.get(CanonicalPost, PUBLISHED_ID)
        assert post is not None
        post.version_match_state = verification_state

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/postmortem")

    assert response.status_code == 200
    comparison = response.json()["postmortem"]["metric_comparisons"][0]
    assert response.json()["state"] == "version_unverified"
    assert comparison["status"] == "version_unverified"
    assert comparison["deviation_from_median"] is None
    assert comparison["relative_percentile"] is None
    assert comparison["matched_sample_count"] == 0


def test_synthetic_demo_postmortem_is_authenticated_labeled_and_unverified(
    postmortem_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = postmortem_api
    monkeypatch.setenv("BIPME_ENVIRONMENT", "development")
    monkeypatch.setenv("BIPME_SYNTHETIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("BIPME_SYNTHETIC_DEMO_CREATOR_ID", str(CREATOR_ID))
    monkeypatch.setenv("BIPME_CREATOR_ID", str(CREATOR_ID))
    monkeypatch.setenv("BIPME_EMBEDDING_PROVIDER", "synthetic_demo")
    with factory.begin() as db:
        posts = db.scalars(
            select(CanonicalPost).where(CanonicalPost.creator_id == CREATOR_ID)
        ).all()
        for post in posts:
            post.source = "synthetic_demo_fixture"
            post.provenance = {"source": "synthetic_demo_fixture", "synthetic_demo": True}
        target = db.get(CanonicalPost, PUBLISHED_ID)
        assert target is not None
        target.version_match_state = "unknown"

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/postmortem")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "version_unverified"
    assert body["postmortem"]["version_state"] == "unverified"
    assert "Synthetic demonstration data — not live X evidence." in body["limitations"]


def test_sparse_historical_evidence_is_explicitly_insufficient(postmortem_api) -> None:
    client, factory = postmortem_api
    with factory.begin() as db:
        history = db.scalars(
            select(OutcomeObservationRecord).where(OutcomeObservationRecord.post_id != PUBLISHED_ID)
        ).all()
        for record in history:
            record.metric_value = None
            record.state = "missing"

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/postmortem")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "insufficient_evidence"
    assert body["postmortem"]["metric_comparisons"][0]["status"] == "unavailable"
    assert body["postmortem"]["hypothesis_evaluation"]["status"] == "inconclusive"


def test_historical_snapshots_use_the_latest_observation_at_assessment_cutoff(
    postmortem_api,
) -> None:
    client, factory = postmortem_api
    with factory.begin() as db:
        original = db.scalar(
            select(OutcomeObservationRecord).where(OutcomeObservationRecord.post_id != PUBLISHED_ID)
        )
        assert original is not None
        db.add(
            _record(
                original.post_id,
                5.0,
                original.published_at,
                original.published_at + timedelta(hours=12),
                "earlier-history-snapshot",
            )
        )

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/postmortem")

    assert response.status_code == 200
    comparison = response.json()["postmortem"]["metric_comparisons"][0]
    assert comparison["matched_sample_count"] == 10


def test_revoked_personal_history_permission_withholds_persisted_observations(
    postmortem_api,
) -> None:
    client, factory = postmortem_api
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

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/postmortem")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "evidence_unavailable"
    assert body["postmortem"] is None
    assert "permission or source policy" in body["limitations"][0]


def test_outlook_without_metric_evidence_is_not_reported_as_monitoring_pending(
    postmortem_api,
) -> None:
    client, factory = postmortem_api
    with factory.begin() as db:
        assessment = db.get(DraftAssessment, ASSESSMENT_ID)
        assert assessment is not None
        assessment.decision_snapshot = {**assessment.decision_snapshot, "metrics": []}

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/postmortem")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "insufficient_evidence"
    assert body["postmortem"]["metric_comparisons"] == []


def test_linked_publication_without_any_observation_is_monitoring_pending(postmortem_api) -> None:
    client, factory = postmortem_api
    with factory.begin() as db:
        target = db.scalar(
            select(OutcomeObservationRecord).where(OutcomeObservationRecord.post_id == PUBLISHED_ID)
        )
        assert target is not None
        db.delete(target)

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/postmortem")

    assert response.status_code == 200
    assert response.json()["state"] == "monitoring_pending"
    comparison = response.json()["postmortem"]["metric_comparisons"][0]
    assert comparison["observed_value"] is None
    assert comparison["observed_at"] is None


def test_unavailable_linked_publication_keeps_its_identity_and_timestamp(postmortem_api) -> None:
    client, factory = postmortem_api
    with factory.begin() as db:
        post = db.get(CanonicalPost, PUBLISHED_ID)
        assert post is not None
        post.availability = "unavailable"

    response = client.get(f"/api/v1/creators/me/draft-assessments/{ASSESSMENT_ID}/postmortem")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "publication_unavailable"
    assert body["published_post"]["canonical_post_id"] == str(PUBLISHED_ID)
    assert body["published_post"]["published_at"] == "2026-01-20T13:00:00Z"
    assert body["published_post"]["availability"] == "unavailable"
    assert body["postmortem"] is None


def test_openapi_exposes_typed_authenticated_read_contract() -> None:
    from bipme.api.app import create_app

    operation = create_app().openapi()["paths"][
        "/api/v1/creators/me/draft-assessments/{assessment_id}/postmortem"
    ]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/PostmortemReadResponse"
    )
    assert "401" in operation["responses"]
