"""PostgreSQL-backed synthetic seeder transaction and idempotency coverage."""

from __future__ import annotations

import json
import os
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from bipme.api.app import create_app
from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
)
from bipme.api.source_policy import SYNTHETIC_DEMO_SOURCE
from bipme.devtools.synthetic_demo import (
    SyntheticDemoError,
    link_synthetic_publication,
    seed_synthetic_demo,
)
from bipme.persistence.models import (
    CanonicalPost,
    Creator,
    CreatorProcessingPermission,
    DraftAssessment,
    OutcomeObservationRecord,
    PostEmbedding,
    PostProfileRecord,
)

API_DIR = Path(__file__).parents[1]
CREATOR_ID = UUID("8aee3494-76a3-4a12-9c1d-56671a36c63a")
SEEDED_AT = datetime(2026, 11, 11, 10, tzinfo=UTC)


@pytest.fixture
def isolated_postgres(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    database_url = os.getenv("BIPME_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("BIPME_TEST_DATABASE_URL is required for synthetic demo PostgreSQL tests")
    base_engine = create_engine(database_url)
    schema = f"cod424_{uuid4().hex}"
    with base_engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        config = Config(str(API_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(API_DIR / "alembic"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        connection.commit()
    scoped_url = base_engine.url.update_query_dict({"options": f"-csearch_path={schema},public"})
    engine = create_engine(scoped_url)
    monkeypatch.setenv("BIPME_ENVIRONMENT", "development")
    monkeypatch.setenv("BIPME_SYNTHETIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("BIPME_SYNTHETIC_DEMO_CREATOR_ID", str(CREATOR_ID))
    monkeypatch.setenv("BIPME_CREATOR_ID", str(CREATOR_ID))
    monkeypatch.setenv("BIPME_SYNTHETIC_DEMO_DATABASE_NAME", base_engine.url.database or "")
    monkeypatch.setenv("BIPME_DATABASE_URL", scoped_url.render_as_string(hide_password=False))
    monkeypatch.setenv("BIPME_EMBEDDING_PROVIDER", "synthetic_demo")
    try:
        yield engine
    finally:
        engine.dispose()
        with base_engine.connect() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.commit()
        base_engine.dispose()


def _fixtures(tmp_path: Path, *, unknown_post: bool = False) -> tuple[Path, Path]:
    archive_path = tmp_path / "bipme_synthetic_x_archive.zip"
    records = [
        {
            "tweet": {
                "id_str": "demo-100",
                "created_at": "2026-01-01T00:00:00Z",
                "full_text": "Synthetic Python tips for developers",
                "favorite_count": 900,
            }
        },
        {
            "tweet": {
                "id_str": "demo-101",
                "created_at": "2026-01-02T00:00:00Z",
                "full_text": "Synthetic database design discussion",
                "favorite_count": 0,
            }
        },
    ]
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "data/tweets.js",
            "window.YTD.tweets.part0 = " + json.dumps(records) + ";",
        )
        archive.writestr("data/direct-messages.js", '[{"private":"ignored"}]')
    scenario_path = tmp_path / "bipme_synthetic_monitoring_scenarios.json"
    scenarios = {
        "scenarios": [
            {
                "scenario_id": "demo-observed",
                "post_id": "demo-100",
                "metric": "likes",
                "metric_definition": "synthetic_likes_v1",
                "metric_unit": "count",
                "state": "observed",
                "value": 8,
                "window_kind": "age_aligned",
                "window_key": "age:24h",
                "observed_at": "2026-01-02T00:00:00Z",
            },
            {
                "scenario_id": "demo-missing",
                "post_id": "demo-101",
                "metric": "likes",
                "metric_definition": "synthetic_likes_v1",
                "metric_unit": "count",
                "state": "missing",
                "value": None,
                "window_kind": "age_aligned",
                "window_key": "age:24h",
                "observed_at": "2026-01-03T00:00:00Z",
            },
            {
                "scenario_id": "demo-pending",
                "post_id": "demo-100",
                "metric": "likes",
                "metric_definition": "synthetic_likes_v1",
                "metric_unit": "count",
                "state": "pending",
                "observed_at": "2026-01-04T00:00:00Z",
            },
        ]
    }
    if unknown_post:
        scenarios["scenarios"].append(
            {
                "scenario_id": "bad-reference",
                "post_id": "missing-post",
                "metric": "likes",
                "metric_definition": "synthetic_likes_v1",
                "metric_unit": "count",
                "state": "observed",
                "value": 10,
                "window_kind": "age_aligned",
                "window_key": "age:24h",
                "observed_at": "2026-01-05T00:00:00Z",
            }
        )
    scenario_path.write_text(json.dumps(scenarios), encoding="utf-8")
    return archive_path, scenario_path


def test_postgres_seed_is_idempotent_and_preserves_synthetic_lineage(
    isolated_postgres: Engine, tmp_path: Path
) -> None:
    archive_path, scenario_path = _fixtures(tmp_path)
    with Session(isolated_postgres) as db:
        first = seed_synthetic_demo(
            db,
            archive_path=archive_path,
            scenarios_path=scenario_path,
            creator_id=CREATOR_ID,
            confirmed=True,
            now=SEEDED_AT,
        )
        db.commit()
        second = seed_synthetic_demo(
            db,
            archive_path=archive_path,
            scenarios_path=scenario_path,
            creator_id=CREATOR_ID,
            confirmed=True,
            now=SEEDED_AT,
        )
        db.commit()
        assert first == second
        assert db.scalar(select(func.count()).select_from(CanonicalPost)) == 2
        assert db.scalar(select(func.count()).select_from(PostProfileRecord)) == 2
        assert db.scalar(select(func.count()).select_from(PostEmbedding)) == 2
        observations = list(db.scalars(select(OutcomeObservationRecord)).all())
        assert len(observations) == 2
        assert {row.state for row in observations} == {"observed", "missing"}
        assert all(row.provenance["synthetic_demo"] is True for row in observations)
        posts = list(db.scalars(select(CanonicalPost)).all())
        assert all(row.source == "synthetic_demo_fixture" for row in posts)
        assert all(
            row.provenance["archive_counters"] == "excluded_without_observation_timestamps"
            for row in posts
        )
        assert all(row.source_observed_at == SEEDED_AT for row in posts)
        assert all(row.published_at != row.source_observed_at for row in posts)


def test_postgres_seed_rolls_back_all_rows_when_scenario_mapping_fails(
    isolated_postgres: Engine, tmp_path: Path
) -> None:
    archive_path, scenario_path = _fixtures(tmp_path, unknown_post=True)
    with Session(isolated_postgres) as db:
        with pytest.raises(SyntheticDemoError, match="absent from the archive"):
            seed_synthetic_demo(
                db,
                archive_path=archive_path,
                scenarios_path=scenario_path,
                creator_id=CREATOR_ID,
                confirmed=True,
                now=SEEDED_AT,
            )
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Creator)) == 0
        assert db.scalar(select(func.count()).select_from(CanonicalPost)) == 0
        assert db.scalar(select(func.count()).select_from(OutcomeObservationRecord)) == 0


def test_postgres_seed_refuses_other_creator_activity(
    isolated_postgres: Engine, tmp_path: Path
) -> None:
    archive_path, scenario_path = _fixtures(tmp_path)
    with Session(isolated_postgres) as db:
        db.add(Creator(id=UUID("11111111-1111-4111-8111-111111111111")))
        db.commit()
        with pytest.raises(SyntheticDemoError, match="other creator records"):
            seed_synthetic_demo(
                db,
                archive_path=archive_path,
                scenarios_path=scenario_path,
                creator_id=CREATOR_ID,
                confirmed=True,
                now=SEEDED_AT,
            )


def test_postgres_demo_publication_link_is_synthetic_and_unverified(
    isolated_postgres: Engine,
) -> None:
    assessment_id = UUID("33333333-3333-4333-8333-333333333333")
    with Session(isolated_postgres) as db:
        db.add(Creator(id=CREATOR_ID))
        db.add(
            DraftAssessment(
                id=assessment_id,
                creator_id=CREATOR_ID,
                assessment_key="demo-assessment",
                assessed_at=datetime(2026, 11, 10, tzinfo=UTC),
                content_fingerprint="sha256:" + "a" * 64,
                outlook_version="synthetic-demo-test",
                decision_snapshot={"decision_state": "insufficient_evidence"},
            )
        )
        db.commit()
        publication_id = link_synthetic_publication(
            db,
            creator_id=CREATOR_ID,
            assessment_id=assessment_id,
            published_at=datetime(2026, 11, 11, 9, tzinfo=UTC),
            confirmed=True,
            now=SEEDED_AT,
        )
        db.commit()
        post = db.get(CanonicalPost, publication_id)
        assert post is not None
        assert post.source == "synthetic_demo_fixture"
        assert post.source_assessment_id == assessment_id
        assert post.version_match_state == "unknown"
        assert post.provenance["simulated_publication"] is True
        assert post.source_observed_at == SEEDED_AT


def test_authenticated_report_draft_and_postmortem_paths_use_seeded_demo_evidence(
    isolated_postgres: Engine, tmp_path: Path
) -> None:
    archive, scenarios = _fixtures(tmp_path)
    factory = sessionmaker(isolated_postgres, expire_on_commit=False)
    with factory.begin() as db:
        seed_synthetic_demo(
            db,
            archive_path=archive,
            scenarios_path=scenarios,
            creator_id=CREATOR_ID,
            confirmed=True,
            now=SEEDED_AT,
        )
        db.add(
            CreatorProcessingPermission(
                creator_id=CREATOR_ID,
                revision=1,
                allowed=True,
                policy_version="synthetic-demo-user-consent",
                recorded_at=SEEDED_AT,
            )
        )

    current_time = SEEDED_AT + timedelta(days=1)
    app = create_app()

    def db_session() -> Iterator[Session]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(CREATOR_ID)
    app.dependency_overrides[get_db_session] = db_session
    app.dependency_overrides[get_current_time] = lambda: current_time
    client = TestClient(app)

    report = client.post(
        "/api/v1/creators/me/report",
        headers={"Idempotency-Key": "cod424-postgres-report"},
        json={"data_sources": ["personal_history"]},
    )
    assert report.status_code == 200, report.text
    assert report.json()["coverage"] == "personal_only_partial"
    assert report.json()["processing_permissions"]["personal_history"]["status"] == "included"
    assert "Synthetic demonstration data — not live X evidence" in str(report.json()["evidence"])

    draft = client.post(
        "/api/v1/creators/me/draft-assessments",
        headers={"Idempotency-Key": "cod424-postgres-draft"},
        json={"text": "A practical synthetic Python debugging checklist"},
    )
    assert draft.status_code == 200, draft.text
    assessment_id = UUID(draft.json()["assessment_id"])
    assert draft.json()["decision_state"] == "insufficient_evidence"
    assert "Synthetic demonstration data — not live X evidence." in draft.json()["limitations"]

    publication_time = current_time + timedelta(minutes=1)
    with factory.begin() as db:
        link_synthetic_publication(
            db,
            creator_id=CREATOR_ID,
            assessment_id=assessment_id,
            published_at=publication_time,
            confirmed=True,
            now=publication_time + timedelta(minutes=1),
        )
    app.dependency_overrides[get_current_time] = lambda: publication_time + timedelta(minutes=1)
    postmortem = client.get(f"/api/v1/creators/me/draft-assessments/{assessment_id}/postmortem")
    assert postmortem.status_code == 200, postmortem.text
    assert postmortem.json()["state"] == "version_unverified"
    assert "Synthetic demonstration data — not live X evidence." in postmortem.json()["limitations"]
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(CanonicalPost)
                .where(
                    CanonicalPost.creator_id == CREATOR_ID,
                    CanonicalPost.source == SYNTHETIC_DEMO_SOURCE,
                )
            )
            == 3
        )
