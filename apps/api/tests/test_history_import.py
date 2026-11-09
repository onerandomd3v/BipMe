"""Synthetic persistence tests for the bounded creator-history import seam."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from bipme.api.app import create_app
from bipme.api.dependencies import AuthenticatedCreator, get_authenticated_creator, get_db_session
from bipme.api.history import get_history_importer
from bipme.integrations.x_read import XMetricValue, XReadPost, XReadResult
from bipme.persistence.base import Base
from bipme.persistence.models import (
    CanonicalPost,
    Creator,
    CreatorHistoryImport,
    OutcomeObservationRecord,
)
from bipme.posts.history import CreatorHistoryImporter

CREATOR_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_CREATOR_ID = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)


class FakeHistoryReader:
    def __init__(self, result: XReadResult) -> None:
        self.result = result
        self.calls = 0

    def read(self, db: Session, *, creator_id, import_id, max_posts, now=None):
        self.calls += 1
        return self.result


def _runtime():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def sqlite_functions(connection, _record):
        connection.create_function("decode", 2, lambda value, encoding: bytes.fromhex(value))
        connection.create_function(
            "substring", 3, lambda value, start, length: value[start - 1 : start - 1 + length]
        )
        # The narrow seam fixture omits the unrelated draft-assessment table that
        # canonical_posts references; PostgreSQL integration tests cover FK wiring.
        connection.execute("PRAGMA foreign_keys=OFF")

    tables = [
        Creator.__table__,
        CanonicalPost.__table__,
        OutcomeObservationRecord.__table__,
        CreatorHistoryImport.__table__,
    ]
    removed = []
    for table in tables:
        for constraint in list(table.constraints):
            if isinstance(constraint, CheckConstraint) and "jsonb_typeof" in str(
                constraint.sqltext
            ):
                table.constraints.remove(constraint)
                removed.append((table, constraint))
    Base.metadata.create_all(engine, tables=tables)
    for table, constraint in removed:
        table.constraints.add(constraint)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(Creator(id=CREATOR_ID))
        db.commit()
    return engine, factory


def test_import_normalizes_provenance_missing_metrics_and_is_idempotent():
    engine, factory = _runtime()
    post = XReadPost(
        external_post_id="123",
        text="synthetic post",
        published_at=NOW,
        observed_at=NOW,
        source="x_creator_authorized_history",
        source_endpoint="/2/users/{id}/tweets",
        topology="quote",
        quoted_external_post_id="99",
        media_present=None,
        metrics={
            "like_count": XMetricValue(4, "likes at observation"),
            "impression_count": XMetricValue(None, "impressions at observation", "not_returned"),
        },
    )
    reader = FakeHistoryReader(XReadResult("complete", (post,), pages_read=1, result_count=1))
    importer = CreatorHistoryImporter(reader)
    with factory() as db:
        first = importer.import_history(
            db, creator_id=CREATOR_ID, import_id="synthetic-1", max_posts=5, now=NOW
        )
        second = importer.import_history(
            db, creator_id=CREATOR_ID, import_id="synthetic-1", max_posts=5, now=NOW
        )
        canonical = db.scalar(select(CanonicalPost))
        observations = db.scalars(select(OutcomeObservationRecord)).all()
    assert first["status"] == "complete"
    assert second == first
    assert reader.calls == 1
    assert canonical is not None
    assert canonical.external_post_id == "123"
    assert canonical.text == "synthetic post"
    assert canonical.media_present is None
    assert canonical.topology == "quote"
    assert canonical.provenance["source"] == "x_creator_authorized_history"
    assert {row.state for row in observations} == {"observed", "missing"}
    assert all(row.provenance["source"] == "x_creator_authorized_history" for row in observations)
    engine.dispose()


def test_partial_result_is_visible_in_status_state():
    engine, factory = _runtime()
    reader = FakeHistoryReader(
        XReadResult("partial", (), pages_read=1, unavailable_reason="rate_limited")
    )
    with factory() as db:
        summary = CreatorHistoryImporter(reader).import_history(
            db, creator_id=CREATOR_ID, import_id="partial-1", max_posts=5, now=NOW
        )
        state = db.scalar(select(CreatorHistoryImport))
    assert summary["status"] == "partial"
    assert summary["error_code"] == "rate_limited"
    assert state is not None
    assert state.completed_at == NOW
    engine.dispose()


def test_failure_after_running_commit_is_terminal_and_replayed():
    engine, factory = _runtime()

    class FailingReader:
        calls = 0

        def read(self, db, **kwargs):
            self.calls += 1
            raise RuntimeError("synthetic reader failure")

    reader = FailingReader()
    importer = CreatorHistoryImporter(reader)
    with factory() as db:
        with pytest.raises(RuntimeError, match="synthetic reader failure"):
            importer.import_history(
                db, creator_id=CREATOR_ID, import_id="failing-1", max_posts=5, now=NOW
            )
        failed = db.scalar(select(CreatorHistoryImport))
        replay = importer.import_history(
            db, creator_id=CREATOR_ID, import_id="failing-1", max_posts=5, now=NOW
        )
    assert failed is not None
    assert failed.status == "unavailable"
    assert failed.error_code == "import_failed"
    assert replay["status"] == "unavailable"
    assert reader.calls == 1
    engine.dispose()


def test_same_import_race_replays_winner_without_reading_twice():
    engine, factory = _runtime()
    reader = FakeHistoryReader(XReadResult("complete"))
    importer = CreatorHistoryImporter(reader)
    with factory() as db:
        original_commit = db.commit
        first_commit = True

        def commit_then_report_duplicate():
            nonlocal first_commit
            original_commit()
            if first_commit:
                first_commit = False
                raise IntegrityError("synthetic unique race", {}, Exception())

        db.commit = commit_then_report_duplicate  # type: ignore[method-assign]
        result = importer.import_history(
            db, creator_id=CREATOR_ID, import_id="race-1", max_posts=5, now=NOW
        )
    assert result["import_id"] == "race-1"
    assert result["status"] == "running"
    assert reader.calls == 0
    engine.dispose()


def test_foreign_canonical_post_is_not_overwritten():
    engine, factory = _runtime()
    post = XReadPost(
        external_post_id="foreign-post",
        text="creator two",
        published_at=NOW,
        observed_at=NOW,
        metrics={},
    )
    with factory() as db:
        db.add(Creator(id=OTHER_CREATOR_ID))
        db.add(
            CanonicalPost(
                creator_id=OTHER_CREATOR_ID,
                platform="x",
                external_post_id="foreign-post",
                published_at=NOW,
                availability="available",
                topology="original",
                ingestion_key="x:foreign-post",
                text="creator two",
            )
        )
        db.commit()
        result = CreatorHistoryImporter(
            FakeHistoryReader(XReadResult("complete", (post,), pages_read=1))
        ).import_history(db, creator_id=CREATOR_ID, import_id="ownership-1", max_posts=5, now=NOW)
        stored = db.scalar(
            select(CanonicalPost).where(CanonicalPost.external_post_id == "foreign-post")
        )
    assert result["imported_posts"] == 0
    assert stored is not None
    assert stored.creator_id == OTHER_CREATOR_ID
    assert stored.text == "creator two"
    engine.dispose()


def test_history_routes_validate_auth_fail_closed_and_scope_status():
    engine, factory = _runtime()
    app = create_app()

    def db_dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(CREATOR_ID)
    app.dependency_overrides[get_db_session] = db_dependency
    reader = FakeHistoryReader(XReadResult("complete", (), pages_read=1))
    app.dependency_overrides[get_history_importer] = lambda: CreatorHistoryImporter(reader)
    client = TestClient(app)
    created = client.post(
        "/api/v1/creators/me/history/imports",
        json={"import_id": "route-1", "max_posts": 20},
    )
    assert created.status_code == 200
    assert client.get("/api/v1/creators/me/history/imports/route-1").status_code == 200
    assert client.get("/api/v1/creators/me/history/imports/missing").status_code == 404
    assert (
        client.post(
            "/api/v1/creators/me/history/imports", json={"import_id": "too-large", "max_posts": 401}
        ).status_code
        == 422
    )

    app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(
        OTHER_CREATOR_ID
    )
    assert client.get("/api/v1/creators/me/history/imports/route-1").status_code == 404
    app.dependency_overrides.pop(get_history_importer)
    assert (
        client.post(
            "/api/v1/creators/me/history/imports", json={"import_id": "blocked"}
        ).status_code
        == 503
    )
    app.dependency_overrides.clear()
    engine.dispose()
