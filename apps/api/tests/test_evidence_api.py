"""Synthetic PostgreSQL-backed evidence API contracts, isolation and boundedness."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from test_persistence_postgres import migrated_postgres as migrated_postgres

from bipme.api.app import create_app
from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
)
from bipme.api.errors import ApiError
from bipme.persistence.models import (
    CanonicalPost,
    Creator,
    CreatorHistoryImport,
    CreatorProcessingPermission,
    DraftAssessment,
    OutcomeObservationRecord,
)

# Keep the synthetic cutoff ahead of PostgreSQL server timestamps so the test does not
# accidentally classify freshly inserted fixture rows as "not known at cutoff".
NOW = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=5)
ROOT = "/api/v1/creators/me/history"


@pytest.fixture
def runtime(migrated_postgres, monkeypatch):
    base, schema = migrated_postgres
    engine = create_engine(
        base.url.update_query_dict({"options": f"-csearch_path={schema},public"})
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    owner, other = uuid4(), uuid4()
    ids = [UUID(int=i + uuid4().int // 100 * 100) for i in range(7)]
    with factory() as db:
        db.add_all([Creator(id=owner), Creator(id=other)])
        db.flush()
        db.add(
            CreatorProcessingPermission(
                creator_id=owner,
                revision=1,
                source_kind="personal_history",
                allowed=True,
                policy_version="synthetic",
                recorded_at=NOW - timedelta(days=3),
            )
        )
        for i, post_id in enumerate(ids):
            db.add(
                CanonicalPost(
                    id=post_id,
                    creator_id=other if i == 4 else owner,
                    platform="x",
                    external_post_id=str(post_id.int)[:18],
                    published_at=NOW - timedelta(days=1),
                    availability="deleted" if i == 5 else "unavailable" if i == 6 else "available",
                    deleted_at=NOW if i == 5 else None,
                    topology="original",
                    text=f"synthetic {i}",
                    source="creator_provided_archive" if i == 3 else "x_creator_authorized_history",
                    source_observed_at=NOW - timedelta(hours=2),
                    updated_at=NOW - timedelta(hours=3),
                    provenance={"secret": "must-not-disclose", "url": "https://evil.test"},
                )
            )
        db.flush()
        for i, state in enumerate(["observed", "missing", "invalid"]):
            db.add(
                OutcomeObservationRecord(
                    id=uuid4(),
                    post_id=ids[0],
                    creator_id=owner,
                    published_at=NOW - timedelta(days=1),
                    metric_name=f"metric-{i}",
                    metric_definition="exact-definition",
                    metric_unit="count",
                    metric_value=Decimal(0) if i == 0 else None,
                    state=state,
                    window_kind="mature_cumulative",
                    window_key="at_observation",
                    observed_at=NOW - timedelta(hours=1),
                    idempotency_key=str(uuid4()),
                    provenance={"secret": "must-not-disclose"},
                )
            )
        for i in range(55):
            db.add(
                OutcomeObservationRecord(
                    post_id=ids[1],
                    creator_id=owner,
                    published_at=NOW - timedelta(days=1),
                    metric_name="likes",
                    metric_definition="exact-likes",
                    metric_unit="count",
                    metric_value=i,
                    state="observed",
                    window_kind="age_aligned",
                    window_key="1h",
                    observed_at=NOW - timedelta(hours=3, minutes=i),
                    idempotency_key=str(uuid4()),
                )
            )
        assessment = DraftAssessment(
            id=uuid4(),
            creator_id=owner,
            assessment_key=str(uuid4()),
            assessed_at=NOW - timedelta(hours=2),
            content_fingerprint="sha256:" + "a" * 64,
            outlook_version="v1",
            decision_snapshot={"unchanged": True},
        )
        db.add(assessment)
        db.commit()
        assessment_id = assessment.id
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "true")
    monkeypatch.setenv(
        "BIPME_X_HISTORY_REPORT_PROCESSING_VERIFIED_AT", (NOW - timedelta(days=3)).isoformat()
    )
    app = create_app()
    app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(owner)
    app.dependency_overrides[get_current_time] = lambda: NOW

    def session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db_session] = session
    try:
        yield TestClient(app), factory, engine, owner, ids, assessment_id
    finally:
        engine.dispose()


def test_actual_metrics_and_sanitization(runtime):
    client, _, _, _, ids, _ = runtime
    result = client.get(f"{ROOT}/posts/{ids[0]}")
    assert result.status_code == 200, result.text
    post = result.json()
    assert (
        post["text"] == "synthetic 0"
        and post["source_url"] == f"https://x.com/i/status/{str(ids[0].int)[:18]}"
    )
    metrics = {m["state"]: m for m in post["observations"]}
    assert Decimal(metrics["observed"]["metric_value"]) == 0
    assert metrics["missing"]["metric_value"] is None and metrics["invalid"]["metric_value"] is None
    assert datetime.fromisoformat(metrics["observed"]["observed_at"]) == NOW - timedelta(hours=1)
    assert datetime.fromisoformat(metrics["observed"]["published_at"]) == NOW - timedelta(days=1)
    assert metrics["observed"]["observed_age_seconds"] == 23 * 3600
    assert metrics["observed"]["metric_definition"] == "exact-definition"
    assert metrics["observed"]["metric_unit"] == "count"
    assert metrics["observed"]["window_key"] == "at_observation"
    assert metrics["observed"]["window_kind"] == "mature_cumulative"
    assert "secret" not in result.text and "evil.test" not in result.text


def test_isolation_deleted_unavailable_and_batch(runtime):
    client, _, _, _, ids, _ = runtime
    for post_id in [*ids[4:], uuid4()]:
        assert client.get(f"{ROOT}/posts/{post_id}").status_code == 404
    response = client.get(
        f"{ROOT}/evidence",
        params=[("post_ids", str(i)) for i in [ids[0], ids[0], ids[4], ids[5], uuid4()]],
    )
    assert [p["id"] for p in response.json()["items"]] == [str(ids[0])]
    assert (
        client.get(f"{ROOT}/evidence", params=[("post_ids", str(ids[0]))] * 51).status_code == 422
    )
    assert client.get(f"{ROOT}/evidence").status_code == 422
    assert client.get(f"{ROOT}/posts", params={"limit": 51}).status_code == 422


def test_cursor_ties_exhaustion_and_validation(runtime):
    client, _, _, owner, ids, _ = runtime
    seen = []
    cursor = None
    for _ in range(5):
        result = client.get(
            f"{ROOT}/posts", params={"limit": 1, **({"cursor": cursor} if cursor else {})}
        ).json()
        seen.extend(p["id"] for p in result["items"])
        cursor = result["next_cursor"]
        if cursor is None:
            break
    assert seen == [str(i) for i in sorted(ids[:4], reverse=True)]
    assert len(set(seen)) == 4 and cursor is None
    for value in ["garbage", "😀", "a" * 2049]:
        assert client.get(f"{ROOT}/posts", params={"cursor": value}).status_code == 422
    cursor = client.get(f"{ROOT}/posts", params={"limit": 1}).json()["next_cursor"]
    client.app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(
        uuid4()
    )
    assert client.get(f"{ROOT}/posts", params={"cursor": cursor}).status_code == 422
    assert client.get(f"{ROOT}/posts").json()["items"] == []


def test_cutoff_excludes_later_observations_and_redacts_later_text(runtime):
    client, _, _, _, ids, assessment = runtime
    original = client.get(
        f"{ROOT}/posts/{ids[0]}", params={"assessment_id": str(assessment)}
    ).json()
    assert original["observations"] == []
    older = client.get(f"{ROOT}/posts/{ids[1]}", params={"assessment_id": str(assessment)}).json()
    assert len(older["observations"]) == 50 and older["observations_truncated"]
    assert older["observations"][0]["window_kind"] == "age_aligned"
    past = client.get(
        f"{ROOT}/posts/{ids[0]}", params={"as_of": (NOW - timedelta(hours=4)).isoformat()}
    ).json()
    assert past["text"] is None and past["source_observed_at"] is None
    assert past["freshness"] == "not_known_at_cutoff"
    assert client.get(f"{ROOT}/posts", params={"assessment_id": str(uuid4())}).status_code == 404
    for time in ["2026-11-10T11:00:00", (NOW + timedelta(days=1)).isoformat()]:
        assert client.get(f"{ROOT}/posts", params={"as_of": time}).status_code == 422


def test_permissions_policy_and_archive_metadata(runtime, monkeypatch):
    client, factory, _, owner, ids, _ = runtime
    archive = client.get(f"{ROOT}/posts/{ids[3]}").json()
    assert archive["source"] == "archive" and archive["disclosure"] == "source_policy_blocked"
    assert archive["text"] is None and archive["source_url"] is None
    with factory() as db:
        db.add(
            CreatorProcessingPermission(
                creator_id=owner,
                revision=2,
                source_kind="personal_history",
                allowed=False,
                policy_version="synthetic",
                recorded_at=NOW,
            )
        )
        db.commit()
    denied = client.get(f"{ROOT}/posts/{ids[0]}").json()
    assert (
        denied["disclosure"] == "permission_required"
        and denied["observations"] == []
        and denied["text"] is None
    )
    monkeypatch.delenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED")
    assert client.get(f"{ROOT}/posts/{ids[0]}").json()["source_url"] is None


def test_import_discovery_and_existing_detail_are_sanitized(runtime):
    client, factory, _, owner, _, _ = runtime
    assert client.get(f"{ROOT}/imports").json() == {"items": [], "truncated": False}
    with factory() as db:
        for i, status in enumerate(["running", "partial", "unavailable", "complete"]):
            db.add(
                CreatorHistoryImport(
                    creator_id=owner,
                    import_id=status,
                    requested_posts=10,
                    status=status,
                    started_at=NOW - timedelta(minutes=i),
                    source="x_creator_authorized_history",
                    provenance={"token": "must-not-disclose"},
                )
            )
        db.commit()
    result = client.get(f"{ROOT}/imports", params={"limit": 2})
    assert [r["status"] for r in result.json()["items"]] == ["running", "partial"]
    assert result.json()["truncated"] and "must-not-disclose" not in result.text
    assert client.get(f"{ROOT}/imports/complete").json()["provenance"] == {}


def test_queries_are_constant_and_no_writes(runtime):
    client, _, engine, _, _, _ = runtime
    statements = []

    def observe(_conn, _cursor, sql, _params, _context, _many):
        statements.append(sql)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        assert client.get(f"{ROOT}/posts").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(statements) == 3
    assert all(s.lstrip().upper().startswith("SELECT") for s in statements)


def test_auth_fails_before_db():
    app = create_app()

    def denied():
        raise ApiError(401, "authentication_required", "Sign in.")

    def forbidden():
        raise AssertionError("DB should not be queried")

    app.dependency_overrides[get_authenticated_creator] = denied
    app.dependency_overrides[get_db_session] = forbidden
    for path in [
        "/posts",
        "/evidence?post_ids=" + str(uuid4()),
        "/imports",
        "/posts/" + str(uuid4()),
    ]:
        assert TestClient(app).get(ROOT + path).status_code == 401


def test_blocked_policy_and_unknown_source_are_metadata_only(runtime, monkeypatch):
    client, factory, _, _, ids, _ = runtime
    monkeypatch.delenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED")
    blocked = client.get(f"{ROOT}/posts/{ids[0]}").json()
    assert blocked["disclosure"] == "source_policy_blocked" and blocked["observations"] == []
    assert blocked["text"] is None and blocked["source_url"] is None
    monkeypatch.setenv("BIPME_X_HISTORY_REPORT_PROCESSING_ALLOWED", "true")
    with factory() as db:
        post = db.get(CanonicalPost, ids[0])
        post.source = "unknown-private-source"
        db.commit()
    unknown = client.get(f"{ROOT}/posts/{ids[0]}").json()
    assert unknown["source"] == "unknown" and unknown["observations"] == []
    assert "unknown-private-source" not in str(unknown)


def test_untrusted_provenance_and_later_text_update(runtime):
    client, factory, _, _, ids, assessment = runtime
    from sqlalchemy import select

    with factory() as db:
        metric = db.scalar(
            select(OutcomeObservationRecord).where(OutcomeObservationRecord.post_id == ids[0])
        )
        metric.provenance = {
            "source": {"token": "secret"},
            "missing_reason": {"token": "secret"},
            "raw_payload": "secret",
        }
        post = db.get(CanonicalPost, ids[0])
        post.updated_at = NOW
        db.commit()
    response = client.get(f"{ROOT}/posts/{ids[0]}")
    assert response.status_code == 200 and "secret" not in response.text
    historical = client.get(
        f"{ROOT}/posts/{ids[0]}", params={"assessment_id": str(assessment)}
    ).json()
    assert historical["text"] is None and historical["disclosure"] == "not_known_at_cutoff"


def test_missing_permission_denies_content_and_invalid_urls_are_not_built(runtime):
    client, factory, _, owner, ids, _ = runtime
    from sqlalchemy import delete

    with factory() as db:
        db.execute(
            delete(CreatorProcessingPermission).where(
                CreatorProcessingPermission.creator_id == owner
            )
        )
        db.commit()
    response = client.get(f"{ROOT}/posts/{ids[0]}").json()
    assert response["disclosure"] == "permission_required" and response["observations"] == []


def test_database_failure_is_sanitized():
    app = create_app()

    class Broken:
        def scalar(self, *args, **kwargs):
            from sqlalchemy.exc import SQLAlchemyError

            raise SQLAlchemyError("private database credentials")

    app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(uuid4())
    app.dependency_overrides[get_db_session] = lambda: Broken()
    response = TestClient(app).get(f"{ROOT}/posts/{uuid4()}")
    assert response.status_code == 503 and "credentials" not in response.text
