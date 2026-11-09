"""Synthetic persistence tests for the bounded creator-history import seam."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

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
