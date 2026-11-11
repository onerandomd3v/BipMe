"""Synthetic API tests for authenticated report-first creator onboarding."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bipme.api.app import create_app
from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
)
from bipme.persistence.base import Base
from bipme.persistence.models import (
    CanonicalPost,
    Creator,
    CreatorGoalRevision,
    CreatorProcessingPermission,
    CreatorReportSnapshot,
    OutcomeObservationRecord,
    PostProfileRecord,
)

CREATOR_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_CREATOR_ID = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)


@pytest.fixture
def report_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "false")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Creator.__table__,
        CreatorGoalRevision.__table__,
        CreatorProcessingPermission.__table__,
        CreatorReportSnapshot.__table__,
        CanonicalPost.__table__,
        PostProfileRecord.__table__,
        OutcomeObservationRecord.__table__,
    ]
    postgres_only: list[tuple[object, CheckConstraint]] = []
    for table in tables:
        for constraint in list(table.constraints):
            if isinstance(constraint, CheckConstraint) and "jsonb_typeof" in str(
                constraint.sqltext
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
        db.commit()
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


def _profile_payload(**overrides: object) -> dict[str, object]:
    return {
        "niche": "software engineering",
        "intended_audience": "early-career developers",
        "priority_outcomes": ["conversation", "authority"],
        "preferred_styles": ["technical_explainer", "personal_story"],
        "language": "English",
        **overrides,
    }


def _create_profile(client: TestClient) -> dict[str, object]:
    response = client.put("/api/v1/creators/me/profile", json=_profile_payload())
    assert response.status_code == 200, response.text
    return response.json()


def _grant_personal_history(client: TestClient) -> None:
    response = client.put(
        "/api/v1/creators/me/data-permissions", json={"allow_personal_history": True}
    )
    assert response.status_code == 200, response.text


def _seed_history(
    factory: sessionmaker[Session], *, creator_id: UUID = CREATOR_ID
) -> tuple[UUID, ...]:
    post_ids: list[UUID] = []
    with factory() as db:
        for index in range(4):
            post_id = uuid4()
            published = NOW - timedelta(days=10 - index)
            post_ids.append(post_id)
            db.add(
                CanonicalPost(
                    id=post_id,
                    creator_id=creator_id,
                    platform="x",
                    external_post_id=f"synthetic-{creator_id.hex[:4]}-{index}",
                    published_at=published,
                    availability="available",
                    topology="original",
                    source="x_creator_authorized_history",
                )
            )
            db.add(
                OutcomeObservationRecord(
                    id=uuid4(),
                    post_id=post_id,
                    creator_id=creator_id,
                    published_at=published,
                    metric_name="replies",
                    metric_definition="public_reply_count_v1",
                    metric_unit="replies",
                    metric_value=index + 1,
                    state="observed",
                    window_kind="age_aligned",
                    window_key="age:24h",
                    observed_at=published + timedelta(days=1),
                    idempotency_key=f"synthetic-observation-{creator_id.hex[:4]}-{index}",
                    provenance={"source": "synthetic_test_fixture"},
                )
            )
        db.commit()
    return tuple(post_ids)


def test_onboarding_without_draft_returns_awaiting_import_report(report_api) -> None:
    client, _factory = report_api
    profile = _create_profile(client)
    assert profile["revision"] == 1
    assert profile["creator_key"] == str(CREATOR_ID)

    result = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-onboarding-001"},
        json={},
    )

    assert result.status_code == 200, result.text
    body = result.json()
    assert body["coverage"] == "insufficient_evidence"
    assert body["report"]["state"] == "insufficient_evidence"
    assert body["report"]["creator_key"] == str(CREATOR_ID)
    assert body["report"]["personal_findings"][0]["kind"] == "unknown"
    assert body["processing_permissions"]["niche_discovery"]["external_requests"] == 0
    assert body["processing_permissions"]["external_synthesis"]["provider_calls"] == 0
    assert "draft" not in body


def test_report_endpoint_fails_closed_without_a_private_session() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/creators/me/report/latest")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_not_configured"


def test_profile_validation_and_revision_are_creator_declared(report_api) -> None:
    client, factory = report_api
    first = _create_profile(client)
    repeated = client.put("/api/v1/creators/me/profile", json=_profile_payload())
    changed = client.put(
        "/api/v1/creators/me/profile",
        json=_profile_payload(niche="developer education"),
    )

    assert repeated.json()["revision"] == 1
    assert changed.status_code == 200
    assert changed.json()["revision"] == 2
    assert changed.json()["niche"] == "developer education"
    with factory() as db:
        revisions = db.scalars(
            select(CreatorGoalRevision).where(CreatorGoalRevision.creator_id == CREATOR_ID)
        ).all()
    assert len(revisions) == 2
    assert first["intended_audience"] == "early-career developers"

    invalid = client.put(
        "/api/v1/creators/me/profile",
        json=_profile_payload(priority_outcomes=["viral"]),
    )
    duplicates = client.put(
        "/api/v1/creators/me/profile",
        json=_profile_payload(priority_outcomes=["conversation", "conversation"]),
    )
    assert invalid.status_code == 422
    assert duplicates.status_code == 422
    assert "audience_demographics" not in changed.json()


def test_personal_history_requires_creator_consent_and_default_off_policy_gate(report_api) -> None:
    client, factory = report_api
    _create_profile(client)
    _seed_history(factory)

    denied = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-no-consent-001"},
        json={"data_sources": ["personal_history"]},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "source_permission_required"

    _grant_personal_history(client)
    permission_status = client.get("/api/v1/creators/me/data-permissions").json()
    assert permission_status["personal_history"] == "granted"
    assert permission_status["x_history_processing"] == "blocked"
    result = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-source-gate-001"},
        json={"data_sources": ["personal_history"]},
    )
    body = result.json()
    assert result.status_code == 200
    assert body["coverage"] == "insufficient_evidence"
    assert (
        body["processing_permissions"]["personal_history"]["status"] == "blocked_by_source_policy"
    )
    assert body["evidence"]["observations"] == []


def test_selected_but_empty_history_is_explicitly_insufficient(report_api, monkeypatch) -> None:
    client, _factory = report_api
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "true")
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT", "2026-11-08T12:00:00Z")
    _create_profile(client)
    _grant_personal_history(client)

    result = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-empty-history-001"},
        json={"data_sources": ["personal_history"]},
    )

    assert result.status_code == 200
    body = result.json()
    assert body["coverage"] == "insufficient_evidence"
    assert body["report"]["experiments"] == []
    assert body["evidence"]["observations"] == []
    assert any(
        "No available creator-owned canonical history" in item for item in body["limitations"]
    )


def test_history_above_report_bound_is_withheld_without_sampling(report_api, monkeypatch) -> None:
    client, factory = report_api
    monkeypatch.setattr("bipme.api.creator_reports.MAX_REPORT_POSTS", 2)
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "true")
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT", "2026-11-08T12:00:00Z")
    _create_profile(client)
    _grant_personal_history(client)
    _seed_history(factory)

    response = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-bounded-history-001"},
        json={"data_sources": ["personal_history"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["coverage"] == "insufficient_evidence"
    assert body["evidence"]["observations"] == []
    assert body["processing_permissions"]["personal_history"]["status"] == "bounded_input_limit"
    assert any("no sample was selected" in item for item in body["limitations"])


def test_opted_in_report_is_deterministic_personal_only_and_creator_scoped(
    report_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = report_api
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "true")
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT", "2026-11-08T12:00:00Z")
    _create_profile(client)
    _grant_personal_history(client)
    own_ids = _seed_history(factory)
    _seed_history(factory, creator_id=OTHER_CREATOR_ID)

    request = {"data_sources": ["personal_history"]}
    first = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-personal-001"},
        json=request,
    )
    replay = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-personal-001"},
        json=request,
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200
    body = first.json()
    assert body["id"] == replay.json()["id"]
    assert body["coverage"] == "personal_only_partial"
    assert body["report"]["state"] == "personal_only_partial"
    assert body["goals_revision"] == 1
    assert body["goals_version"] == "creator-goals-v1"
    assert body["evidence_version"] == "creator-report-evidence-v2"
    assert body["report_version"] == "creator-intelligence-report-v2"
    assert body["freshness"]["niche_discovery"] == "unavailable"
    referenced_posts = {
        post_id
        for finding in body["report"]["personal_findings"]
        for post_id in finding["supporting_post_ids"]
    }
    assert referenced_posts
    assert referenced_posts <= {str(post_id) for post_id in own_ids}
    assert str(OTHER_CREATOR_ID) not in str(body["report"])

    latest = client.get("/api/v1/creators/me/report/latest")
    assert latest.status_code == 200
    assert latest.json()["status"] == "available"
    assert latest.json()["latest_report"]["id"] == body["id"]


def test_synthetic_demo_report_uses_source_gate_and_labels_lineage(
    report_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = report_api
    monkeypatch.setenv("BIPME_ENVIRONMENT", "development")
    monkeypatch.setenv("BIPME_SYNTHETIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("BIPME_SYNTHETIC_DEMO_CREATOR_ID", str(CREATOR_ID))
    monkeypatch.setenv("BIPME_CREATOR_ID", str(CREATOR_ID))
    monkeypatch.setenv("BIPME_EMBEDDING_PROVIDER", "synthetic_demo")
    _create_profile(client)
    _grant_personal_history(client)
    post_ids = _seed_history(factory)
    with factory.begin() as db:
        for post_id in post_ids:
            post = db.get(CanonicalPost, post_id)
            assert post is not None
            post.source = "synthetic_demo_fixture"
            post.provenance = {
                "source": "synthetic_demo_fixture",
                "synthetic_demo": True,
            }

    response = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-synthetic-demo-001"},
        json={"data_sources": ["personal_history"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coverage"] == "personal_only_partial"
    assert "Synthetic demonstration data — not live X evidence" in str(body["evidence"])
    assert "synthetic_demo_fixture" in str(body["evidence"])
    with factory() as db:
        snapshot = db.scalar(
            select(CreatorReportSnapshot).where(CreatorReportSnapshot.creator_id == CREATOR_ID)
        )
        assert snapshot is not None
        assert snapshot.permission_snapshot["personal_history"]["status"] == "included"
        assert snapshot.permission_snapshot["personal_history"]["source_policy_enabled"] is True


def test_reused_idempotency_key_with_different_profile_conflicts(report_api) -> None:
    client, _factory = report_api
    _create_profile(client)
    headers = {"Idempotency-Key": "report-reuse-001"}
    first = client.post("/api/v1/creators/me/report", headers=headers, json={})
    assert first.status_code == 200
    client.put(
        "/api/v1/creators/me/profile",
        json=_profile_payload(niche="creator tooling"),
    )
    conflict = client.post("/api/v1/creators/me/report", headers=headers, json={})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_reused"


def test_revocation_erases_derived_reports_and_profile_deletion_clears_api_owned_state(
    report_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = report_api
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "true")
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT", "2026-11-08T12:00:00Z")
    _create_profile(client)
    _grant_personal_history(client)
    _seed_history(factory)
    generated = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-delete-001"},
        json={"data_sources": ["personal_history"]},
    )
    assert generated.status_code == 200
    assert client.get("/api/v1/creators/me/report/latest").json()["status"] == "available"

    revoked = client.put(
        "/api/v1/creators/me/data-permissions", json={"allow_personal_history": False}
    )
    assert revoked.status_code == 200
    assert revoked.json()["personal_history"] == "revoked"
    assert client.get("/api/v1/creators/me/report/latest").json()["status"] == "awaiting_import"
    with factory() as db:
        assert db.scalars(select(CreatorReportSnapshot)).all() == []
        permissions = db.scalars(
            select(CreatorProcessingPermission).where(
                CreatorProcessingPermission.creator_id == CREATOR_ID
            )
        ).all()
    assert [item.allowed for item in permissions] == [True, False]

    deleted = client.delete("/api/v1/creators/me/profile")
    assert deleted.status_code == 204
    profile_state = client.get("/api/v1/creators/me/profile").json()
    assert profile_state == {"status": "not_configured", "profile": None}
    assert (
        client.get("/api/v1/creators/me/data-permissions").json()["personal_history"]
        == "not_granted"
    )


def test_report_read_is_creator_scoped_and_openapi_contract_is_published(report_api) -> None:
    client, _factory = report_api
    _create_profile(client)
    created = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-private-001"},
        json={},
    )
    assert created.status_code == 200
    report_id = created.json()["id"]

    app = client.app
    from bipme.api.dependencies import get_authenticated_creator

    app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(
        OTHER_CREATOR_ID
    )
    hidden = client.get(f"/api/v1/creators/me/reports/{report_id}")
    assert hidden.status_code == 404

    paths = app.openapi()["paths"]
    assert "/api/v1/creators/me/profile" in paths
    assert "/api/v1/creators/me/report" in paths
    assert "/api/v1/creators/me/report/latest" in paths
    report_post = paths["/api/v1/creators/me/report"]["post"]
    assert "Idempotency-Key" in str(report_post["parameters"])
    assert "CreatorReportResponse" in str(report_post["responses"]["200"])


def test_niche_source_selection_is_rejected_until_discovery_is_available(report_api) -> None:
    client, _factory = report_api
    _create_profile(client)
    response = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-no-niche-001"},
        json={"data_sources": ["niche_discovery"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_invalid_latest_observation_does_not_resurrect_an_older_value(
    report_api, monkeypatch
) -> None:
    client, factory = report_api
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "true")
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT", "2026-11-08T12:00:00Z")
    _create_profile(client)
    post_ids = _seed_history(factory)
    with factory() as db:
        post = db.get(CanonicalPost, post_ids[0])
        assert post is not None
        db.add(
            OutcomeObservationRecord(
                id=uuid4(),
                post_id=post.id,
                creator_id=CREATOR_ID,
                published_at=post.published_at,
                metric_name="replies",
                metric_definition="public_reply_count_v1",
                metric_unit="replies",
                metric_value=None,
                state="invalid",
                window_kind="age_aligned",
                window_key="age:24h",
                observed_at=NOW - timedelta(days=1),
                idempotency_key="synthetic-invalid-latest",
                provenance={"source": "synthetic_test_fixture"},
            )
        )
        db.commit()
    _grant_personal_history(client)

    response = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-invalid-latest-001"},
        json={"data_sources": ["personal_history"]},
    )

    assert response.status_code == 200, response.text
    outcomes = response.json()["evidence"]["observations"]
    assert len(outcomes) == 3
    assert str(post_ids[0]) not in {item["post_id"] for item in outcomes}


def test_missing_outcomes_are_gaps_and_do_not_become_measured_claims(
    report_api, monkeypatch
) -> None:
    client, factory = report_api
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "true")
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT", "2026-11-08T12:00:00Z")
    _create_profile(client)
    _seed_history(factory)
    with factory() as db:
        rows = db.scalars(
            select(OutcomeObservationRecord).where(
                OutcomeObservationRecord.creator_id == CREATOR_ID
            )
        ).all()
        for row in rows:
            row.state = "missing"
            row.metric_value = None
        db.commit()
    _grant_personal_history(client)

    response = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-missing-outcomes-001"},
        json={"data_sources": ["personal_history"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["coverage"] == "insufficient_evidence"
    assert len(body["evidence"]["observations"]) == 4
    assert all(item["value"] is None for item in body["evidence"]["observations"])
    assert len(body["evidence"]["missing_observations"]) == 4
    assert body["evidence"]["bundle"]["personal_evidence"] == []


def test_metric_definition_conflicts_are_excluded_without_failing_other_metrics(
    report_api, monkeypatch
) -> None:
    client, factory = report_api
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "true")
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT", "2026-11-08T12:00:00Z")
    _create_profile(client)
    post_ids = _seed_history(factory)
    with factory() as db:
        for index, post_id in enumerate(post_ids):
            post = db.get(CanonicalPost, post_id)
            assert post is not None
            db.add(
                OutcomeObservationRecord(
                    id=uuid4(),
                    post_id=post_id,
                    creator_id=CREATOR_ID,
                    published_at=post.published_at,
                    metric_name="replies",
                    metric_definition="public_reply_count_v2",
                    metric_unit="replies",
                    metric_value=index + 10,
                    state="observed",
                    window_kind="age_aligned",
                    window_key="age:24h",
                    observed_at=post.published_at + timedelta(days=1),
                    idempotency_key=f"synthetic-alternate-replies-{index}",
                    provenance={"source": "synthetic_test_fixture"},
                )
            )
            db.add(
                OutcomeObservationRecord(
                    id=uuid4(),
                    post_id=post_id,
                    creator_id=CREATOR_ID,
                    published_at=post.published_at,
                    metric_name="likes",
                    metric_definition="public_like_count_v1",
                    metric_unit="likes",
                    metric_value=index + 5,
                    state="observed",
                    window_kind="age_aligned",
                    window_key="age:24h",
                    observed_at=post.published_at + timedelta(days=1),
                    idempotency_key=f"synthetic-likes-{index}",
                    provenance={"source": "synthetic_test_fixture"},
                )
            )
        db.commit()
    _grant_personal_history(client)

    response = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "report-metric-definition-conflict-001"},
        json={"data_sources": ["personal_history"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    included_metrics = {item["metric"] for item in body["evidence"]["observations"]}
    excluded_metrics = {
        item["metric"] for item in body["evidence"]["excluded_ambiguous_observations"]
    }
    assert "replies" not in included_metrics
    assert "likes" in included_metrics
    assert excluded_metrics == {"replies"}
    assert any("multiple metric definitions" in item for item in body["limitations"])
