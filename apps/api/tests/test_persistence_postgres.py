"""PostgreSQL integration coverage for persistence models and Alembic migrations."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.sync_psycopg_connector import SyncPsycopgConnector
from sqlalchemy import Engine, create_engine, inspect, make_url, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, StatementError
from sqlalchemy.orm import Session

from bipme.api.app import create_app
from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
    get_embedder,
)
from bipme.api.publications import get_x_publication_verifier
from bipme.integrations.x_publication import PublishedPostEvidence
from bipme.integrations.x_read import XReadPost
from bipme.intelligence.embeddings import EmbeddingIdentity
from bipme.intelligence.post_profiles import (
    CreatorContextSnapshot,
    PostProfileInput,
    extract_post_profile,
)
from bipme.intelligence.retrieval import VectorCandidateQuery
from bipme.jobs.runtime import (
    TASK_NAME,
    JobRuntime,
    JobRuntimeSettings,
    RetryableHandlerError,
    TerminalJobError,
    _execute_receipt,
    _recover_stalled_job,
    configure_windows_event_loop,
    create_runtime,
    run_worker_supervised,
)
from bipme.jobs.service import IdempotencyConflict, schedule_job
from bipme.persistence.base import EncryptedTokenEnvelope
from bipme.persistence.contracts import (
    comparable_candidate_from_records,
    pgvector_candidate_statement,
    post_profile_payload,
)
from bipme.persistence.models import (
    APIUsageLedger,
    CanonicalPost,
    Creator,
    CreatorGoalRevision,
    CreatorPlatformIdentity,
    CreatorProcessingPermission,
    CreatorReportSnapshot,
    DraftAssessment,
    OutcomeObservationRecord,
    PostEmbedding,
    PostProfileRecord,
    ScheduledJob,
    XAccountConnection,
)
from bipme.persistence.usage import (
    UsageBudgetError,
    XUsageLimits,
    reserve_x_usage,
)
from bipme.persistence.vector_candidates import PostgresVectorCandidateSource
from bipme.posts.history import CreatorHistoryImporter

API_DIR = Path(__file__).parents[1]
NOW = datetime(2026, 11, 8, 14, tzinfo=UTC)
REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"
IDENTITY = EmbeddingIdentity("intfloat/multilingual-e5-small", REVISION, 384, "e5-prefix-strip-v1")


@pytest.fixture(scope="module")
def migrated_postgres() -> Iterator[tuple[Engine, str]]:
    database_url = os.getenv("BIPME_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("BIPME_TEST_DATABASE_URL is required for PostgreSQL migration tests")

    engine = create_engine(database_url)
    schema = f"cod345_{uuid4().hex}"
    connection = engine.connect()
    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    connection.execute(text(f'SET search_path TO "{schema}", public'))
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    config.attributes["connection"] = connection
    try:
        # Exercise a clean forward migration, downgrade to the original pgvector base,
        # and a repeat forward migration in this isolated schema.
        command.upgrade(config, "head")
        connection.commit()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0006_creator_history_import"
        )
        command.downgrade(config, "0001_enable_vector")
        connection.commit()
        assert "canonical_posts" not in inspect(connection).get_table_names()
        assert connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
        command.upgrade(config, "head")
        connection.commit()
        tables = set(inspect(connection).get_table_names())
        expected = {
            "creators",
            "creator_platform_identities",
            "x_account_connections",
            "creator_sessions",
            "oauth_authorization_transactions",
            "draft_assessments",
            "canonical_posts",
            "post_profiles",
            "post_embeddings",
            "outcome_observations",
            "api_usage_ledger",
            "creator_goal_revisions",
            "creator_processing_permissions",
            "creator_report_snapshots",
            "creator_history_imports",
            "scheduled_jobs",
            "procrastinate_jobs",
            "procrastinate_workers",
            "procrastinate_events",
            "procrastinate_periodic_defers",
        }
        assert expected <= tables
        history_columns = {
            column["name"] for column in inspect(connection).get_columns("creator_history_imports")
        }
        assert {
            "import_id",
            "status",
            "requested_posts",
            "pages_read",
            "imported_posts",
            "next_page_available",
            "error_code",
            "provenance",
        } <= history_columns
        post_columns = {
            column["name"] for column in inspect(connection).get_columns("canonical_posts")
        }
        assert {
            "text",
            "media_present",
            "source",
            "source_endpoint",
            "source_observed_at",
            "provenance",
        } <= post_columns
        indexes = {index["name"] for index in inspect(connection).get_indexes("post_embeddings")}
        assert "ix_embeddings_e5_v1_cosine" in indexes
        assert "ix_posts_creator_published" in {
            index["name"] for index in inspect(connection).get_indexes("canonical_posts")
        }
        yield engine, schema
    finally:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        connection.commit()
        connection.close()
        engine.dispose()


@pytest.fixture
def session(migrated_postgres: tuple[Engine, str]) -> Iterator[Session]:
    engine, schema = migrated_postgres
    connection = engine.connect()
    connection.execute(text(f'SET search_path TO "{schema}", public'))
    connection.commit()
    db_session = Session(bind=connection)
    try:
        yield db_session
    finally:
        db_session.close()
        connection.close()


def _creator(session: Session) -> Creator:
    creator = Creator(id=uuid4())
    session.add(creator)
    session.flush()
    return creator


def test_report_first_snapshots_persist_owner_scoped_versions_and_idempotency(
    session: Session,
) -> None:
    creator = _creator(session)
    goals = CreatorGoalRevision(
        id=uuid4(),
        creator_id=creator.id,
        revision=1,
        goals_version="creator-goals-v1",
        recorded_at=NOW,
        niche="synthetic software education",
        intended_audience="synthetic early-career developers",
        priority_outcomes=["conversation"],
        preferred_styles=["technical_explainer"],
        language="English",
    )
    permission = CreatorProcessingPermission(
        id=uuid4(),
        creator_id=creator.id,
        revision=1,
        source_kind="personal_history",
        allowed=True,
        policy_version="creator-history-processing-v1",
        recorded_at=NOW,
    )
    session.add_all((goals, permission))
    session.flush()
    report = CreatorReportSnapshot(
        id=uuid4(),
        creator_id=creator.id,
        goals_revision_id=goals.id,
        idempotency_key="synthetic-report-001",
        request_fingerprint="a" * 64,
        generated_at=NOW,
        as_of=NOW,
        goals_revision=goals.revision,
        goals_version=goals.goals_version,
        evidence_version="creator-report-evidence-v2",
        report_version="creator-intelligence-report-v2",
        baseline_version="creator-baseline-v1",
        report_state="insufficient_evidence",
        report_snapshot={"state": "insufficient_evidence"},
        evidence_snapshot={"bundle": {"version": "creator-report-evidence-v2"}},
        permission_snapshot={"personal_history": {"status": "not_selected"}},
        freshness_snapshot={"personal_history": "unknown", "niche_discovery": "unavailable"},
    )
    session.add(report)
    session.flush()

    assert (
        session.scalar(
            select(CreatorReportSnapshot).where(
                CreatorReportSnapshot.id == report.id,
                CreatorReportSnapshot.creator_id == creator.id,
            )
        )
        is not None
    )
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                CreatorReportSnapshot(
                    id=uuid4(),
                    creator_id=creator.id,
                    goals_revision_id=goals.id,
                    idempotency_key="synthetic-report-001",
                    request_fingerprint="b" * 64,
                    generated_at=NOW + timedelta(seconds=1),
                    as_of=NOW + timedelta(seconds=1),
                    goals_revision=goals.revision,
                    goals_version=goals.goals_version,
                    evidence_version="creator-report-evidence-v2",
                    report_version="creator-intelligence-report-v2",
                    baseline_version="creator-baseline-v1",
                    report_state="insufficient_evidence",
                    report_snapshot={"state": "insufficient_evidence"},
                    evidence_snapshot={"bundle": {"version": "creator-report-evidence-v2"}},
                    permission_snapshot={"personal_history": {"status": "not_selected"}},
                    freshness_snapshot={
                        "personal_history": "unknown",
                        "niche_discovery": "unavailable",
                    },
                )
            )
            session.flush()


def _runtime_settings(engine: Engine, schema: str) -> JobRuntimeSettings:
    database_url = make_url(engine.url).update_query_dict(
        {"options": f"-csearch_path={schema},public"}
    )
    return JobRuntimeSettings(database_url=database_url.render_as_string(hide_password=False))


def _run_worker_once(runtime: JobRuntime) -> None:
    async def run() -> None:
        async with runtime.app.open_async():
            await runtime.app.run_worker_async(
                queues=["bipme"], wait=False, concurrency=1, delete_jobs="never"
            )

    _asyncio_run(run())


def _asyncio_run(coroutine: object) -> object:
    configure_windows_event_loop()
    return asyncio.run(coroutine)  # type: ignore[arg-type]


def test_job_receipt_and_queue_insert_share_caller_transaction(session: Session) -> None:
    """The permanent receipt and Procrastinate row commit or roll back together."""
    app = App(connector=SyncPsycopgConnector())

    @app.task(name="bipme.jobs.runtime.dispatch_receipt", queue="bipme")
    def dispatch(receipt_id: str) -> None:
        del receipt_id

    creator = _creator(session)
    session.flush()
    receipt = schedule_job(
        session,
        app,
        creator_id=creator.id,
        idempotency_key="archive:import:001",
        handler_name="archive.import",
        arguments={"import_id": "001"},
        scheduled_at=NOW + timedelta(minutes=5),
    )
    runner_id = receipt.runner_job_id
    receipt_id = receipt.id
    assert runner_id is not None
    session.rollback()
    assert session.get(ScheduledJob, receipt_id) is None
    assert (
        session.scalar(
            text("SELECT count(*) FROM procrastinate_jobs WHERE id = :id"), {"id": runner_id}
        )
        == 0
    )

    creator = _creator(session)
    receipt = schedule_job(
        session,
        app,
        creator_id=creator.id,
        idempotency_key="archive:import:001",
        handler_name="archive.import",
        arguments={"import_id": "001"},
        scheduled_at=NOW + timedelta(minutes=5),
    )
    session.commit()
    runner_id = receipt.runner_job_id
    assert runner_id is not None
    replay = schedule_job(
        session,
        app,
        creator_id=creator.id,
        idempotency_key="archive:import:001",
        handler_name="archive.import",
        arguments={"import_id": "001"},
        scheduled_at=NOW + timedelta(minutes=5),
    )
    assert replay.id == receipt.id
    with pytest.raises(IdempotencyConflict):
        schedule_job(
            session,
            app,
            creator_id=creator.id,
            idempotency_key="archive:import:001",
            handler_name="archive.import",
            arguments={"import_id": "002"},
            scheduled_at=NOW + timedelta(minutes=5),
        )
    assert (
        session.scalar(
            text("SELECT count(*) FROM procrastinate_jobs WHERE id = :id"), {"id": runner_id}
        )
        == 1
    )


def test_scheduled_job_orm_constraints_match_migration(session: Session) -> None:
    inspector = inspect(session.connection())
    orm_table = ScheduledJob.__table__
    orm_constraints = {constraint.name for constraint in orm_table.constraints}
    database_constraint_rows = [
        row
        for method in (
            inspector.get_check_constraints,
            inspector.get_unique_constraints,
            inspector.get_foreign_keys,
        )
        for row in method("scheduled_jobs")
    ]
    database_constraint_rows.append(inspector.get_pk_constraint("scheduled_jobs"))
    database_constraints = {
        constraint["name"] for constraint in database_constraint_rows if constraint.get("name")
    }
    assert database_constraints == orm_constraints
    assert {index.name for index in orm_table.indexes} == {
        index["name"]
        for index in inspector.get_indexes("scheduled_jobs")
        if not index.get("duplicates_constraint")
    }


def test_job_delay_survives_runtime_restart_and_duplicate_replay(
    migrated_postgres: tuple[Engine, str], session: Session
) -> None:
    engine, schema = migrated_postgres
    seen: list[str] = []
    runtime1 = create_runtime(
        _runtime_settings(engine, schema),
        handlers={"synthetic.snapshot": lambda _db, receipt: seen.append(str(receipt.id))},
    )
    try:
        creator = _creator(session)
        scheduled_at = datetime.now(UTC) + timedelta(minutes=10)
        receipt = schedule_job(
            session,
            runtime1.app,
            creator_id=creator.id,
            idempotency_key="snapshot:restart:01",
            handler_name="synthetic.snapshot",
            arguments={"post_id": "001"},
            scheduled_at=scheduled_at,
        )
        receipt_id = receipt.id
        runner_id = receipt.runner_job_id
        assert runner_id is not None
        session.commit()
        _run_worker_once(runtime1)
        assert seen == []
        runner_row = session.execute(
            text("SELECT status::text, scheduled_at FROM procrastinate_jobs WHERE id=:id"),
            {"id": runner_id},
        ).one()
        assert runner_row.status == "todo"
        assert runner_row.scheduled_at > datetime.now(UTC)
    finally:
        runtime1.close()

    runtime2 = create_runtime(
        _runtime_settings(engine, schema),
        handlers={"synthetic.snapshot": lambda _db, receipt: seen.append(str(receipt.id))},
    )
    try:
        session.execute(
            text("UPDATE procrastinate_jobs SET scheduled_at=NULL WHERE id=:id"),
            {"id": runner_id},
        )
        session.commit()

        async def run_restarted_worker() -> None:
            stop_event = asyncio.Event()
            async with runtime2.app.open_async():
                worker = asyncio.create_task(
                    run_worker_supervised(runtime2, stop_event, graceful_timeout_seconds=1)
                )
                for _ in range(100):
                    if seen:
                        break
                    await asyncio.sleep(0.05)
                stop_event.set()
                await worker

        _asyncio_run(run_restarted_worker())
        persisted = session.get(ScheduledJob, receipt_id)
        assert persisted is not None and persisted.outcome == "succeeded"
        assert seen == [str(receipt_id)]

        replay = schedule_job(
            session,
            runtime2.app,
            creator_id=persisted.creator_id,
            idempotency_key="snapshot:restart:01",
            handler_name="synthetic.snapshot",
            arguments={"post_id": "001"},
            scheduled_at=scheduled_at,
        )
        assert replay.id == receipt_id
        assert (
            session.scalar(
                text("SELECT count(*) FROM procrastinate_jobs WHERE args->>'receipt_id'=:id"),
                {"id": str(receipt_id)},
            )
            == 1
        )
        session.commit()
    finally:
        runtime2.close()


def test_two_workers_claim_once_and_shutdown_drains_past_grace(
    migrated_postgres: tuple[Engine, str], session: Session
) -> None:
    engine, schema = migrated_postgres
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    count_lock = threading.Lock()
    calls = 0

    def blocking_handler(_db: Session, _receipt: ScheduledJob) -> None:
        nonlocal calls
        with count_lock:
            calls += 1
        entered.set()
        release.wait(timeout=10)
        completed.set()

    settings = _runtime_settings(engine, schema)
    runtime1 = create_runtime(settings, handlers={"synthetic.block": blocking_handler})
    runtime2 = create_runtime(settings, handlers={"synthetic.block": blocking_handler})
    creator = _creator(session)
    receipt = schedule_job(
        session,
        runtime1.app,
        creator_id=creator.id,
        idempotency_key="snapshot:concurrent:01",
        handler_name="synthetic.block",
        arguments={"post_id": "002"},
        scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    receipt_id = receipt.id
    session.commit()

    async def exercise() -> None:
        stop1, stop2 = asyncio.Event(), asyncio.Event()
        async with runtime1.app.open_async(), runtime2.app.open_async():
            tasks = [
                asyncio.create_task(
                    run_worker_supervised(runtime1, stop1, graceful_timeout_seconds=0.05)
                ),
                asyncio.create_task(
                    run_worker_supervised(runtime2, stop2, graceful_timeout_seconds=0.05)
                ),
            ]
            assert await asyncio.to_thread(entered.wait, 10)
            stop1.set()
            stop2.set()
            await asyncio.sleep(0.15)
            assert any(not task.done() for task in tasks)
            release.set()
            await asyncio.gather(*tasks)

    try:
        _asyncio_run(exercise())
        assert completed.is_set()
        assert calls == 1
        persisted = session.get(ScheduledJob, receipt_id)
        assert persisted is not None and persisted.outcome == "succeeded"
    finally:
        release.set()
        runtime1.close()
        runtime2.close()


def _x_connection(
    session: Session, creator: Creator, *, state: str = "connected"
) -> XAccountConnection:
    identity = CreatorPlatformIdentity(
        id=uuid4(),
        creator_id=creator.id,
        platform="x",
        external_creator_id=str(uuid4().int)[:18],
    )
    session.add(identity)
    session.flush()
    connection = XAccountConnection(
        id=uuid4(),
        creator_id=creator.id,
        creator_identity_id=identity.id,
        platform="x",
        state=state,
        scopes=["tweet.read", "users.read"],
        encrypted_access_token=b"BIPME-ENC\x01synthetic-ciphertext"
        if state == "connected"
        else None,
        key_version="synthetic-test-key",
        revoked_at=datetime.now(UTC) if state == "revoked" else None,
    )
    session.add(connection)
    session.flush()
    return connection


def test_retry_limit_updates_receipt_and_runner_to_failed(
    migrated_postgres: tuple[Engine, str], session: Session
) -> None:
    engine, schema = migrated_postgres
    attempts = 0
    exhausted = threading.Event()

    def always_retry(_db: Session, _receipt: ScheduledJob) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            exhausted.set()
        raise RetryableHandlerError("synthetic-safe-before-side-effect")

    runtime = create_runtime(
        _runtime_settings(engine, schema),
        handlers={"synthetic.retry": always_retry},
        retry_exponential_wait=1,
    )
    creator = _creator(session)
    receipt = schedule_job(
        session,
        runtime.app,
        creator_id=creator.id,
        idempotency_key="retry:bounded:01",
        handler_name="synthetic.retry",
        arguments={"operation_id": "retry-01"},
        scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
        max_attempts=2,
    )
    receipt_id, runner_id = receipt.id, receipt.runner_job_id
    session.commit()
    assert runner_id is not None

    async def exercise() -> None:
        stop_event = asyncio.Event()
        async with runtime.app.open_async():
            worker = asyncio.create_task(
                run_worker_supervised(runtime, stop_event, graceful_timeout_seconds=1)
            )
            assert await asyncio.to_thread(exhausted.wait, 20)
            stop_event.set()
            await worker

    try:
        _asyncio_run(exercise())
        persisted = session.get(ScheduledJob, receipt_id)
        runner_state = session.execute(
            text("SELECT status::text FROM procrastinate_jobs WHERE id=:id"), {"id": runner_id}
        ).scalar_one()
        assert attempts == 2
        assert persisted is not None and persisted.outcome == "failed"
        assert runner_state == "failed"
    finally:
        runtime.close()


def test_revoked_connection_blocks_registered_handler(
    migrated_postgres: tuple[Engine, str], session: Session
) -> None:
    engine, schema = migrated_postgres
    called = False

    def should_not_run(_db: Session, _receipt: ScheduledJob) -> None:
        nonlocal called
        called = True

    runtime = create_runtime(
        _runtime_settings(engine, schema), handlers={"synthetic.x_read": should_not_run}
    )
    creator = _creator(session)
    connection = _x_connection(session, creator, state="revoked")
    receipt = schedule_job(
        session,
        runtime.app,
        creator_id=creator.id,
        idempotency_key="revoked:connection:01",
        handler_name="synthetic.x_read",
        arguments={"post_id": "003"},
        scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
        required_x_connection_id=connection.id,
    )
    receipt_id, runner_id = receipt.id, receipt.runner_job_id
    session.commit()
    assert runner_id is not None
    try:
        _run_worker_once(runtime)
        persisted = session.get(ScheduledJob, receipt_id)
        status = session.execute(
            text("SELECT status::text FROM procrastinate_jobs WHERE id=:id"), {"id": runner_id}
        ).scalar_one()
        assert not called
        assert persisted is not None and persisted.outcome == "revoked"
        assert status == "failed"
    finally:
        runtime.close()


def _mark_job_stalled(session: Session, runner_id: int) -> None:
    worker_id = session.execute(
        text("INSERT INTO procrastinate_workers DEFAULT VALUES RETURNING id")
    ).scalar_one()
    session.execute(
        text("UPDATE procrastinate_workers SET last_heartbeat=:heartbeat WHERE id=:worker_id"),
        {"heartbeat": datetime.now(UTC) - timedelta(minutes=5), "worker_id": worker_id},
    )
    session.execute(
        text(
            "UPDATE procrastinate_jobs SET status='doing', attempts=0, worker_id=:worker_id "
            "WHERE id=:runner_id"
        ),
        {"worker_id": worker_id, "runner_id": runner_id},
    )
    session.commit()


def test_stalled_recovery_skips_live_receipt_fence_then_retries_provider_independent_job(
    migrated_postgres: tuple[Engine, str], session: Session
) -> None:
    engine, schema = migrated_postgres
    runtime = create_runtime(_runtime_settings(engine, schema))
    creator = _creator(session)
    receipt = schedule_job(
        session,
        runtime.app,
        creator_id=creator.id,
        idempotency_key="recovery:receipt-fence:01",
        handler_name="synthetic.snapshot",
        arguments={"post_id": "recovery-01"},
        scheduled_at=datetime.now(UTC),
        max_attempts=3,
    )
    receipt_id, runner_id = receipt.id, receipt.runner_job_id
    assert runner_id is not None
    session.commit()
    _mark_job_stalled(session, runner_id)

    try:
        # A live receipt owner must make recovery skip this candidate via SKIP LOCKED.
        lock_connection = engine.connect()
        lock_connection.execute(text(f'SET search_path TO "{schema}", public'))
        lock_session = Session(bind=lock_connection)
        try:
            lock_session.execute(
                select(ScheduledJob).where(ScheduledJob.id == receipt_id).with_for_update()
            ).scalar_one()
            _recover_stalled_job(runtime, runner_id, str(receipt_id))
            assert (
                lock_session.scalar(
                    text("SELECT status::text FROM procrastinate_jobs WHERE id=:id"),
                    {"id": runner_id},
                )
                == "doing"
            )
        finally:
            lock_session.close()
            lock_connection.close()

        _recover_stalled_job(runtime, runner_id, str(receipt_id))
        state = session.execute(
            text(
                "SELECT status::text, attempts, scheduled_at FROM procrastinate_jobs WHERE id=:id"
            ),
            {"id": runner_id},
        ).one()
        assert state.status == "todo"
        assert state.attempts == 1
        assert state.scheduled_at > datetime.now(UTC)
        persisted = session.get(ScheduledJob, receipt_id)
        assert persisted is not None and persisted.outcome is None
    finally:
        runtime.close()


def test_concurrent_stalled_recovery_transitions_once(
    migrated_postgres: tuple[Engine, str], session: Session
) -> None:
    engine, schema = migrated_postgres
    runtime = create_runtime(_runtime_settings(engine, schema))
    creator = _creator(session)
    receipt = schedule_job(
        session,
        runtime.app,
        creator_id=creator.id,
        idempotency_key="recovery:concurrent:01",
        handler_name="synthetic.snapshot",
        arguments={"post_id": "recovery-02"},
        scheduled_at=datetime.now(UTC),
    )
    receipt_id, runner_id = receipt.id, receipt.runner_job_id
    assert runner_id is not None
    session.commit()
    _mark_job_stalled(session, runner_id)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(_recover_stalled_job, runtime, runner_id, str(receipt_id))
                for _ in range(2)
            ]
            for future in futures:
                future.result(timeout=10)
        row = session.execute(
            text("SELECT status::text, attempts FROM procrastinate_jobs WHERE id=:id"),
            {"id": runner_id},
        ).one()
        assert row.status == "todo"
        assert row.attempts == 1
        assert session.get(ScheduledJob, receipt_id).outcome is None
    finally:
        runtime.close()


def test_recovery_skips_prune_locked_worker_without_deadlock(
    migrated_postgres: tuple[Engine, str], session: Session
) -> None:
    engine, schema = migrated_postgres
    runtime = create_runtime(_runtime_settings(engine, schema))
    creator = _creator(session)
    receipt = schedule_job(
        session,
        runtime.app,
        creator_id=creator.id,
        idempotency_key="recovery:prune-lock-order:01",
        handler_name="synthetic.snapshot",
        arguments={"post_id": "recovery-prune"},
        scheduled_at=datetime.now(UTC),
    )
    receipt_id, runner_id = receipt.id, receipt.runner_job_id
    assert runner_id is not None
    session.commit()
    _mark_job_stalled(session, runner_id)
    worker_id = session.scalar(
        text("SELECT worker_id FROM procrastinate_jobs WHERE id=:id"), {"id": runner_id}
    )
    assert worker_id is not None

    lock_connection = engine.connect()
    lock_connection.execute(text(f'SET search_path TO "{schema}", public'))
    lock_session = Session(bind=lock_connection)
    try:
        # Model the prune transaction's worker-row delete lock. Recovery must acquire
        # worker-before-job with SKIP LOCKED and return, so prune can finish its FK update.
        lock_session.execute(
            text("SELECT id FROM procrastinate_workers WHERE id=:id FOR UPDATE"),
            {"id": worker_id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_recover_stalled_job, runtime, runner_id, str(receipt_id))
            future.result(timeout=5)
        assert (
            session.scalar(
                text("SELECT status::text FROM procrastinate_jobs WHERE id=:id"),
                {"id": runner_id},
            )
            == "doing"
        )
        state = session.execute(
            text("SELECT status::text, attempts FROM procrastinate_jobs WHERE id=:id"),
            {"id": runner_id},
        ).one()
        assert state.status == "doing"
        assert state.attempts == 0
        assert session.get(ScheduledJob, receipt_id).outcome is None
        lock_session.rollback()
    finally:
        lock_session.close()
        lock_connection.close()
        runtime.close()


def test_stalled_required_x_job_atomically_needs_reconciliation_and_fails(
    migrated_postgres: tuple[Engine, str], session: Session
) -> None:
    engine, schema = migrated_postgres
    runtime = create_runtime(_runtime_settings(engine, schema))
    creator = _creator(session)
    connection = _x_connection(session, creator)
    receipt = schedule_job(
        session,
        runtime.app,
        creator_id=creator.id,
        idempotency_key="recovery:billable-ambiguous:01",
        handler_name="synthetic.billable",
        arguments={"post_id": "recovery-03"},
        scheduled_at=datetime.now(UTC),
        required_x_connection_id=connection.id,
    )
    receipt_id, runner_id = receipt.id, receipt.runner_job_id
    assert runner_id is not None
    session.commit()
    _mark_job_stalled(session, runner_id)
    try:
        _recover_stalled_job(runtime, runner_id, str(receipt_id))
        state = session.execute(
            text("SELECT status::text FROM procrastinate_jobs WHERE id=:id"),
            {"id": runner_id},
        ).scalar_one()
        persisted = session.get(ScheduledJob, receipt_id)
        assert state == "failed"
        assert persisted is not None
        assert persisted.outcome == "needs_reconciliation"
        assert persisted.failure_code == "worker_lost_during_billable_operation"
        assert persisted.finished_at is not None
    finally:
        runtime.close()


def test_billable_duplicate_delivery_uses_one_receipt_reservation_and_call(
    migrated_postgres: tuple[Engine, str], session: Session
) -> None:
    engine, schema = migrated_postgres
    provider_calls = 0
    limits = XUsageLimits(
        total_usd=Decimal("1"),
        daily_usd=Decimal("1"),
        operation_usd=Decimal("1"),
        import_usd=None,
    )

    def fake_billable_handler(db: Session, receipt: ScheduledJob) -> None:
        nonlocal provider_calls
        reservation = reserve_x_usage(
            db,
            creator_id=receipt.creator_id,
            operation="synthetic_post_snapshot",
            idempotency_key=f"scheduled-job:{receipt.id}",
            estimated_cost=Decimal("0.01"),
            limits=limits,
            now=datetime.now(UTC),
            request_metadata={"endpoint": "/synthetic"},
        )
        if reservation.already_reserved:
            return
        provider_calls += 1

    runtime = create_runtime(
        _runtime_settings(engine, schema),
        handlers={"synthetic.billable": fake_billable_handler},
    )
    creator = _creator(session)
    connection = _x_connection(session, creator)
    receipt = schedule_job(
        session,
        runtime.app,
        creator_id=creator.id,
        idempotency_key="billable:duplicate:01",
        handler_name="synthetic.billable",
        arguments={"post_id": "004"},
        scheduled_at=datetime.now(UTC),
        required_x_connection_id=connection.id,
    )
    receipt_id = receipt.id
    session.commit()
    try:
        _execute_receipt(runtime, receipt_id, 0)
        _execute_receipt(runtime, receipt_id, 0)
        assert provider_calls == 1
        assert (
            session.scalar(
                select(APIUsageLedger).where(
                    APIUsageLedger.idempotency_key == f"scheduled-job:{receipt_id}"
                )
            )
            is not None
        )
        assert (
            session.scalar(
                select(APIUsageLedger.id).where(
                    APIUsageLedger.idempotency_key == f"scheduled-job:{receipt_id}"
                )
            )
            is not None
        )
        assert (
            session.scalar(
                text("SELECT count(*) FROM api_usage_ledger WHERE idempotency_key=:key"),
                {"key": f"scheduled-job:{receipt_id}"},
            )
            == 1
        )
        session.commit()
    finally:
        runtime.close()


def test_billable_crash_after_reservation_reconciles_without_redelivery(
    migrated_postgres: tuple[Engine, str], session: Session
) -> None:
    engine, schema = migrated_postgres
    provider_calls = 0
    limits = XUsageLimits(
        total_usd=Decimal("1"),
        daily_usd=Decimal("1"),
        operation_usd=Decimal("1"),
        import_usd=None,
    )

    class SimulatedProcessCrash(BaseException):
        pass

    def crash_after_provider_call(db: Session, receipt: ScheduledJob) -> None:
        nonlocal provider_calls
        reservation = reserve_x_usage(
            db,
            creator_id=receipt.creator_id,
            operation="synthetic_post_snapshot",
            idempotency_key=f"scheduled-job:{receipt.id}",
            estimated_cost=Decimal("0.01"),
            limits=limits,
            now=datetime.now(UTC),
            request_metadata={"endpoint": "/synthetic"},
        )
        assert not reservation.already_reserved
        provider_calls += 1
        # Emulate abrupt process loss after the durable reservation/provider call and
        # before _execute_receipt can commit its terminal receipt state.
        raise SimulatedProcessCrash()

    settings = _runtime_settings(engine, schema)
    runtime = create_runtime(settings, handlers={"synthetic.billable": crash_after_provider_call})
    creator = _creator(session)
    connection = _x_connection(session, creator)
    receipt = schedule_job(
        session,
        runtime.app,
        creator_id=creator.id,
        idempotency_key="billable:crash-window:01",
        handler_name="synthetic.billable",
        arguments={"post_id": "crash-window"},
        scheduled_at=datetime.now(UTC),
        required_x_connection_id=connection.id,
    )
    receipt_id, runner_id = receipt.id, receipt.runner_job_id
    assert runner_id is not None
    session.commit()
    restarted_runtime = None
    try:
        with pytest.raises(SimulatedProcessCrash):
            _execute_receipt(runtime, receipt_id, 0)
        assert session.get(ScheduledJob, receipt_id).outcome is None
        _mark_job_stalled(session, runner_id)

        _recover_stalled_job(runtime, runner_id, str(receipt_id))
        persisted = session.get(ScheduledJob, receipt_id)
        runner_state = session.scalar(
            text("SELECT status::text FROM procrastinate_jobs WHERE id=:id"),
            {"id": runner_id},
        )
        ledger_count = session.scalar(
            text("SELECT count(*) FROM api_usage_ledger WHERE idempotency_key=:key"),
            {"key": f"scheduled-job:{receipt_id}"},
        )
        assert persisted is not None and persisted.outcome == "needs_reconciliation"
        assert runner_state == "failed"
        assert ledger_count == 1
        assert provider_calls == 1

        # A fresh runtime in this process represents restart recovery; a duplicate
        # delivery short-circuits on the permanent receipt and cannot call the provider.
        restarted_runtime = create_runtime(
            settings, handlers={"synthetic.billable": crash_after_provider_call}
        )
        with pytest.raises(TerminalJobError, match="receipt_already_terminal"):
            _execute_receipt(restarted_runtime, receipt_id, 0)
        assert provider_calls == 1
        assert (
            session.scalar(
                text("SELECT count(*) FROM api_usage_ledger WHERE idempotency_key=:key"),
                {"key": f"scheduled-job:{receipt_id}"},
            )
            == 1
        )
    finally:
        if restarted_runtime is not None:
            restarted_runtime.close()
        runtime.close()


def _post(
    session: Session,
    creator_id: UUID,
    *,
    external_id: str | None = None,
    published_at: datetime = NOW - timedelta(hours=1),
    source_assessment_id: UUID | None = None,
) -> CanonicalPost:
    post = CanonicalPost(
        id=uuid4(),
        creator_id=creator_id,
        platform="x",
        external_post_id=external_id or str(uuid4()),
        published_at=published_at,
        availability="available",
        topology="original",
        source_assessment_id=source_assessment_id,
    )
    session.add(post)
    session.flush()
    return post


def _profile(
    session: Session,
    post: CanonicalPost,
    *,
    features_as_of: datetime,
    text_value: str | None = "A synthetic post",
    version: str = "post-profile-v1",
) -> PostProfileRecord:
    profile = extract_post_profile(
        PostProfileInput(
            text=text_value,
            observed_at=features_as_of,
            features_as_of=features_as_of,
            creator_key=str(post.creator_id),
            topology="original",
            media_types=(),
            creator_context=CreatorContextSnapshot(features_as_of, follower_count=12),
        ),
        version=version,
    )
    record = PostProfileRecord(
        id=uuid4(),
        post_id=post.id,
        creator_id=post.creator_id,
        profile_version=profile.version,
        features_as_of=profile.features_as_of,
        input_observed_at=profile.input_observed_at,
        creator_context_observed_at=profile.creator_context_observed_at,
        features=post_profile_payload(profile),
    )
    session.add(record)
    session.flush()
    return record


def _embedding(
    session: Session,
    post: CanonicalPost,
    *,
    generated_at: datetime,
    identity: EmbeddingIdentity = IDENTITY,
) -> PostEmbedding:
    row = PostEmbedding(
        id=uuid4(),
        post_id=post.id,
        creator_id=post.creator_id,
        model_id=identity.model_id,
        model_revision=identity.revision,
        dimensions=identity.dimensions,
        preprocessing_version=identity.preprocessing_version,
        normalized=identity.normalized,
        embedding_version=identity.embedding_version,
        embedding=[1.0, *([0.0] * 383)],
        generated_at=generated_at,
    )
    session.add(row)
    session.flush()
    return row


def test_migration_survives_clean_upgrade_downgrade_and_repeat_upgrade(
    migrated_postgres: tuple[Engine, str],
) -> None:
    engine, schema = migrated_postgres
    with engine.connect() as connection:
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        connection.commit()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0006_creator_history_import"
        )


def test_creator_scoped_ownership_and_post_ingestion_are_enforced(session: Session) -> None:
    creator_a, creator_b = _creator(session), _creator(session)
    post = _post(session, creator_a.id, external_id="x-post-001")

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                CanonicalPost(
                    id=uuid4(),
                    creator_id=creator_b.id,
                    platform="x",
                    external_post_id="x-post-001",
                    published_at=NOW,
                    availability="available",
                    topology="original",
                )
            )
            session.flush()

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                OutcomeObservationRecord(
                    id=uuid4(),
                    post_id=post.id,
                    creator_id=creator_b.id,
                    published_at=post.published_at,
                    metric_name="impressions",
                    metric_definition="public_impressions_v1",
                    metric_unit="impressions",
                    metric_value=Decimal("1"),
                    state="observed",
                    window_kind="mature_cumulative",
                    window_key="mature",
                    observed_at=NOW,
                    idempotency_key="owner-mismatch",
                    provenance={},
                )
            )
            session.flush()


def test_concurrent_history_post_upserts_share_one_canonical_row(
    migrated_postgres: tuple[Engine, str],
) -> None:
    """A duplicate canonical post is contained by the savepoint under real PostgreSQL."""
    engine, schema = migrated_postgres
    creator_id = uuid4()
    post = XReadPost(
        external_post_id="concurrent-history-post",
        text="synthetic concurrent post",
        published_at=NOW,
        observed_at=NOW,
        source="x_creator_authorized_history",
        source_endpoint="/2/users/{id}/tweets",
        topology="original",
        media_present=False,
        metrics={},
    )
    with engine.connect() as connection:
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        connection.commit()
        with Session(bind=connection) as db:
            db.add(Creator(id=creator_id))
            db.commit()

    barrier = threading.Barrier(2)
    outcomes: list[bool] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        connection = engine.connect()
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        connection.commit()
        db = Session(bind=connection)
        try:
            barrier.wait(timeout=10)
            imported = CreatorHistoryImporter._upsert_post(
                db, creator_id, "concurrent-import", post
            )
            db.commit()
            with lock:
                outcomes.append(imported)
        except BaseException as exc:
            with lock:
                errors.append(exc)
            db.rollback()
        finally:
            db.close()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        for future in futures:
            future.result(timeout=20)

    assert errors == []
    assert outcomes == [True, True] or outcomes == [True, False]
    with engine.connect() as connection:
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        connection.commit()
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM canonical_posts "
                    "WHERE creator_id = :creator_id AND external_post_id = :external_post_id"
                ),
                {"creator_id": str(creator_id), "external_post_id": post.external_post_id},
            )
            == 1
        )


def test_outcome_snapshots_are_idempotent_and_preserve_zero_missing_and_time(
    session: Session,
) -> None:
    creator = _creator(session)
    post = _post(session, creator.id)
    common = dict(
        id=uuid4(),
        post_id=post.id,
        creator_id=creator.id,
        published_at=post.published_at,
        metric_name="replies",
        metric_definition="public_reply_count_v1",
        metric_unit="replies",
        window_kind="age_aligned",
        window_key="age:1h",
        provenance={},
    )
    zero = OutcomeObservationRecord(
        **common,
        metric_value=Decimal("0"),
        state="observed",
        observed_at=post.published_at + timedelta(hours=1),
        idempotency_key="snapshot-1",
    )
    later = OutcomeObservationRecord(
        **{**common, "id": uuid4()},
        metric_value=Decimal("3"),
        state="observed",
        observed_at=post.published_at + timedelta(hours=2),
        idempotency_key="snapshot-2",
    )
    missing = OutcomeObservationRecord(
        **{**common, "id": uuid4()},
        metric_value=None,
        state="missing",
        observed_at=post.published_at + timedelta(hours=3),
        idempotency_key="snapshot-missing",
    )
    session.add_all([zero, later, missing])
    session.flush()

    rows = session.scalars(
        select(OutcomeObservationRecord).where(OutcomeObservationRecord.post_id == post.id)
    ).all()
    assert len(rows) == 3
    assert next(row for row in rows if row.state == "observed").metric_value == Decimal("0E-10")
    assert next(row for row in rows if row.state == "missing").metric_value is None
    assert {row.observed_at for row in rows} == {
        post.published_at + timedelta(hours=1),
        post.published_at + timedelta(hours=2),
        post.published_at + timedelta(hours=3),
    }

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                OutcomeObservationRecord(
                    **{**common, "id": uuid4()},
                    metric_value=Decimal("0"),
                    state="observed",
                    observed_at=zero.observed_at,
                    idempotency_key="duplicate-observation-time",
                )
            )
            session.flush()


def test_profile_and_embedding_versions_are_unique_and_creator_scoped(session: Session) -> None:
    creator_a, creator_b = _creator(session), _creator(session)
    post = _post(session, creator_a.id)
    profile = _profile(session, post, features_as_of=post.published_at + timedelta(minutes=1))

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                PostProfileRecord(
                    id=uuid4(),
                    post_id=post.id,
                    creator_id=creator_a.id,
                    profile_version=profile.profile_version,
                    features_as_of=profile.features_as_of,
                    input_observed_at=profile.input_observed_at,
                    creator_context_observed_at=profile.creator_context_observed_at,
                    features=profile.features,
                )
            )
            session.flush()

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                PostProfileRecord(
                    id=uuid4(),
                    post_id=post.id,
                    creator_id=creator_b.id,
                    profile_version="post-profile-v2",
                    features_as_of=NOW,
                    input_observed_at=NOW,
                    features={},
                )
            )
            session.flush()

    embedding = _embedding(session, post, generated_at=post.published_at + timedelta(minutes=2))
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                PostEmbedding(
                    id=uuid4(),
                    post_id=post.id,
                    creator_id=creator_a.id,
                    model_id=embedding.model_id,
                    model_revision=embedding.model_revision,
                    dimensions=embedding.dimensions,
                    preprocessing_version=embedding.preprocessing_version,
                    normalized=embedding.normalized,
                    embedding_version=embedding.embedding_version,
                    embedding=embedding.embedding,
                    generated_at=NOW,
                )
            )
            session.flush()

    replacement = _embedding(
        session,
        post,
        generated_at=NOW,
        identity=EmbeddingIdentity(
            IDENTITY.model_id,
            IDENTITY.revision,
            IDENTITY.dimensions,
            IDENTITY.preprocessing_version,
            IDENTITY.normalized,
            embedding_version="2",
        ),
    )
    assert replacement.embedding_version == "2"


def test_x_connection_ownership_revocation_and_ciphertext_boundary(session: Session) -> None:
    creator = _creator(session)
    identity = CreatorPlatformIdentity(
        id=uuid4(),
        creator_id=creator.id,
        platform="x",
        external_creator_id="x-user-001",
        handle="creator",
    )
    session.add(identity)
    session.flush()
    connection = XAccountConnection(
        id=uuid4(),
        creator_id=creator.id,
        creator_identity_id=identity.id,
        platform="x",
        state="connected",
        scopes=["tweet.read", "users.read"],
        encrypted_access_token=b"BIPME-ENC\x01synthetic-ciphertext-access",
        encrypted_refresh_token=b"BIPME-ENC\x01synthetic-ciphertext-refresh",
        key_version="kms-key-v1",
        access_token_expires_at=NOW + timedelta(hours=1),
        token_rotated_at=NOW,
    )
    session.add(connection)
    session.flush()
    assert connection.encrypted_access_token.startswith(b"BIPME-ENC\x01")
    assert connection.scopes == ["tweet.read", "users.read"]

    connection.state = "revoked"
    connection.revoked_at = NOW
    connection.encrypted_access_token = None
    connection.encrypted_refresh_token = None
    session.flush()
    assert session.get(XAccountConnection, connection.id).revoked_at == NOW

    with pytest.raises(StatementError, match="encrypted BIPME-ENC v1 envelopes"):
        with session.begin_nested():
            session.add(
                XAccountConnection(
                    id=uuid4(),
                    creator_id=creator.id,
                    creator_identity_id=identity.id,
                    platform="x",
                    state="connected",
                    scopes=[],
                    encrypted_access_token=b"plaintext-token-is-rejected",
                    key_version="kms-key-v1",
                )
            )
            session.flush()

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                XAccountConnection(
                    id=uuid4(),
                    creator_id=creator.id,
                    creator_identity_id=identity.id,
                    platform="x",
                    state="connected",
                    scopes=[],
                    encrypted_access_token=None,
                    key_version="kms-key-v1",
                )
            )
            session.flush()


def test_api_usage_ledger_enforces_idempotency_and_usage_bounds(session: Session) -> None:
    creator = _creator(session)
    row = APIUsageLedger(
        id=uuid4(),
        creator_id=creator.id,
        provider="x",
        operation="users.posts.read",
        idempotency_key="x-request-001",
        request_metadata={"endpoint": "users.posts", "limit": 10},
        requested_at=NOW,
        completed_at=NOW + timedelta(seconds=3),
        usage_units=7,
        currency="USD",
        estimated_cost=Decimal("0.01000000"),
        actual_cost=Decimal("0.00700000"),
        reconciliation_state="reconciled",
    )
    session.add(row)
    session.flush()
    assert session.get(APIUsageLedger, row.id).actual_cost == Decimal("0.00700000")

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                APIUsageLedger(
                    id=uuid4(),
                    creator_id=creator.id,
                    provider="x",
                    operation="users.posts.read",
                    idempotency_key="x-request-001",
                    request_metadata={},
                    requested_at=NOW,
                )
            )
            session.flush()


def test_concurrent_x_reservations_share_creator_lock_and_cannot_overspend(
    session: Session,
    migrated_postgres: tuple[Engine, str],
) -> None:
    engine, schema = migrated_postgres
    creator_id = uuid4()
    seed_connection = engine.connect()
    seed_connection.execute(text(f'SET search_path TO "{schema}", public'))
    seed_connection.execute(Creator.__table__.insert().values(id=creator_id))
    seed_connection.commit()
    seed_connection.close()
    limits = XUsageLimits(*(Decimal("0.015") for _ in range(4)))

    def reserve(key: str) -> str:
        connection = engine.connect()
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        connection.commit()
        concurrent_session = Session(bind=connection)
        try:
            reserve_x_usage(
                concurrent_session,
                creator_id=creator_id,
                operation="creator_history_posts_read",
                idempotency_key=key,
                estimated_cost=Decimal("0.010"),
                limits=limits,
                now=NOW,
            )
            return "reserved"
        except UsageBudgetError as exc:
            return exc.code
        finally:
            concurrent_session.close()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, ("parallel-a", "parallel-b")))
    assert sorted(results) == ["budget_exhausted", "reserved"]
    rows = session.scalars(
        select(APIUsageLedger).where(
            APIUsageLedger.creator_id == creator_id,
            APIUsageLedger.operation == "creator_history_posts_read",
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].estimated_cost == Decimal("0.01000000")


def test_assessment_snapshot_is_immutable_and_publication_link_is_single_creator_scoped(
    session: Session,
) -> None:
    creator_a, creator_b = _creator(session), _creator(session)
    assessment = DraftAssessment(
        id=uuid4(),
        creator_id=creator_a.id,
        assessment_key="assessment-001",
        assessed_at=NOW,
        content_fingerprint="sha256:" + "a" * 64,
        outlook_version="distribution-outlook-v1+distribution-outlook-config-v1",
        decision_snapshot={"decision_state": "insufficient_evidence", "suggestion": None},
        accepted_hypothesis=None,
    )
    session.add(assessment)
    session.flush()

    with pytest.raises(DBAPIError, match="draft assessment snapshots are immutable"):
        with session.begin_nested():
            assessment.decision_snapshot = {"decision_state": "supported"}
            session.flush()

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                CanonicalPost(
                    id=uuid4(),
                    creator_id=creator_b.id,
                    platform="x",
                    external_post_id="wrong-owner-publication",
                    published_at=NOW,
                    availability="available",
                    topology="original",
                    source_assessment_id=assessment.id,
                )
            )
            session.flush()

    linked = _post(session, creator_a.id, source_assessment_id=assessment.id)
    assert linked.source_assessment_id == assessment.id
    assert linked.version_match_state is None


def test_postgresql_candidate_source_returns_only_as_of_creator_and_exact_space_rows(
    session: Session,
) -> None:
    creator, other_creator = _creator(session), _creator(session)
    published_at = NOW - timedelta(hours=5)
    good_post = _post(session, creator.id, published_at=published_at)
    eligible_profile = _profile(
        session,
        good_post,
        features_as_of=published_at + timedelta(minutes=5),
    )
    # The latest profile is beyond the assessment cutoff; persistence must select the
    # earlier version visible at assessment time.
    _profile(session, good_post, features_as_of=NOW + timedelta(minutes=1))
    good_embedding = _embedding(
        session, good_post, generated_at=published_at + timedelta(minutes=6)
    )
    wrong_identity = EmbeddingIdentity(
        IDENTITY.model_id,
        "a" * 40,
        IDENTITY.dimensions,
        IDENTITY.preprocessing_version,
        IDENTITY.normalized,
        embedding_version="1",
    )
    _embedding(session, good_post, generated_at=NOW, identity=wrong_identity)

    _post(
        session,
        creator.id,
        published_at=NOW + timedelta(minutes=1),
    )
    other_post = _post(session, other_creator.id, published_at=published_at)
    _profile(
        session,
        other_post,
        features_as_of=published_at + timedelta(minutes=5),
    )
    _embedding(session, other_post, generated_at=published_at + timedelta(minutes=6))

    query = VectorCandidateQuery(
        creator_key=str(creator.id),
        as_of=NOW,
        embedding_identity=IDENTITY,
        query_embedding=(1.0, *([0.0] * 383)),
        limit=10,
    )
    row = session.execute(pgvector_candidate_statement(query)).one()
    post, profile, embedding = row
    candidate = comparable_candidate_from_records(post, profile, embedding)

    assert post.id == good_post.id
    assert profile.id == eligible_profile.id
    assert embedding.id == good_embedding.id
    assert candidate.creator_key == str(creator.id)
    assert candidate.available is True
    assert candidate.embedding_identity == IDENTITY
    assert candidate.embedding_observed_at == good_embedding.generated_at


def test_vector_candidate_source_reports_counts_truncation_and_storage_exclusions(
    session: Session,
) -> None:
    creator = _creator(session)
    eligible_ids: list[UUID] = []
    for index in range(3):
        post = _post(
            session,
            creator.id,
            published_at=NOW - timedelta(days=index + 2),
        )
        _profile(session, post, features_as_of=post.published_at + timedelta(minutes=5))
        _embedding(session, post, generated_at=post.published_at + timedelta(minutes=6))
        eligible_ids.append(post.id)

    missing_embedding = _post(session, creator.id, published_at=NOW - timedelta(days=8))
    _profile(
        session, missing_embedding, features_as_of=NOW - timedelta(days=8) + timedelta(minutes=5)
    )
    missing_profile = _post(session, creator.id, published_at=NOW - timedelta(days=9))
    _embedding(
        session, missing_profile, generated_at=NOW - timedelta(days=9) + timedelta(minutes=5)
    )
    unavailable = _post(session, creator.id, published_at=NOW - timedelta(days=10))
    unavailable.availability = "unavailable"
    _profile(session, unavailable, features_as_of=NOW - timedelta(days=10) + timedelta(minutes=5))
    _embedding(session, unavailable, generated_at=NOW - timedelta(days=10) + timedelta(minutes=6))
    future = _post(session, creator.id, published_at=NOW + timedelta(minutes=1))
    _profile(session, future, features_as_of=NOW + timedelta(minutes=2))
    _embedding(session, future, generated_at=NOW + timedelta(minutes=3))

    source = PostgresVectorCandidateSource(session)
    batch = source.search(
        VectorCandidateQuery(
            creator_key=str(creator.id),
            as_of=NOW,
            embedding_identity=IDENTITY,
            query_embedding=(1.0, *([0.0] * 383)),
            limit=2,
        )
    )

    assert len(batch.candidates) == 2
    assert [candidate.post_id for candidate in batch.candidates] == sorted(
        str(item) for item in eligible_ids
    )[:2]
    assert batch.total_candidate_count == 6
    assert batch.vector_candidate_count == 3
    assert batch.truncated is True
    exclusion_reasons = {item.post_id: item.reasons for item in batch.prefiltered_exclusions}
    assert "missing_embedding" in exclusion_reasons[str(missing_embedding.id)]
    assert "missing_post_profile" in exclusion_reasons[str(missing_profile.id)]
    assert "post_unavailable" in exclusion_reasons[str(unavailable.id)]
    assert str(future.id) not in exclusion_reasons


class _SyntheticEmbedder:
    identity = IDENTITY

    def encode(self, texts: Sequence[str], *, role: str) -> list[list[float]]:
        assert texts
        assert role == "query"
        return [[1.0, *([0.0] * 383)] for _ in texts]


def _authorized_client(session: Session, creator_id: UUID) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(creator_id)
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_embedder] = lambda: _SyntheticEmbedder()
    app.dependency_overrides[get_current_time] = lambda: NOW
    return TestClient(app)


def _seed_analysis_history(session: Session, creator_id: UUID) -> list[CanonicalPost]:
    posts: list[CanonicalPost] = []
    for index in range(9):
        published_at = NOW - timedelta(days=10 + index)
        post = _post(session, creator_id, published_at=published_at)
        _profile(session, post, features_as_of=published_at + timedelta(minutes=2))
        _embedding(session, post, generated_at=published_at + timedelta(minutes=3))
        session.add(
            OutcomeObservationRecord(
                id=uuid4(),
                post_id=post.id,
                creator_id=creator_id,
                published_at=published_at,
                metric_name="impressions",
                metric_definition="public_impressions_v1",
                metric_unit="impressions",
                metric_value=Decimal(index * 100),
                state="observed",
                window_kind="age_aligned",
                window_key="age:24h",
                observed_at=published_at + timedelta(hours=24),
                idempotency_key=f"analysis-history-{uuid4()}",
                provenance={"source": "synthetic"},
            )
        )
        posts.append(post)
    session.flush()
    return posts


def test_authorized_analysis_is_idempotent_immutable_and_excludes_future_outcomes(
    session: Session,
) -> None:
    creator = _creator(session)
    posts = _seed_analysis_history(session, creator.id)
    future_record = OutcomeObservationRecord(
        id=uuid4(),
        post_id=posts[0].id,
        creator_id=creator.id,
        published_at=posts[0].published_at,
        metric_name="impressions",
        metric_definition="public_impressions_v1",
        metric_unit="impressions",
        metric_value=Decimal("999999"),
        state="observed",
        window_kind="age_aligned",
        window_key="age:24h",
        observed_at=NOW + timedelta(hours=1),
        idempotency_key="future-analysis-outcome",
        provenance={"source": "synthetic_future"},
    )
    session.add(future_record)
    # An updated cumulative snapshot must replace the earlier value, not become a
    # duplicate eligible observation for the same post and exact series.
    session.add(
        OutcomeObservationRecord(
            id=uuid4(),
            post_id=posts[0].id,
            creator_id=creator.id,
            published_at=posts[0].published_at,
            metric_name="impressions",
            metric_definition="public_impressions_v1",
            metric_unit="impressions",
            metric_value=Decimal("50"),
            state="observed",
            window_kind="age_aligned",
            window_key="age:24h",
            observed_at=NOW - timedelta(minutes=1),
            idempotency_key="updated-first-post-snapshot",
            provenance={"source": "synthetic_refresh"},
        )
    )
    session.flush()

    client = _authorized_client(session, creator.id)
    body = {
        "text": "A synthetic creator draft\nasking a question?",
        "topology": "original",
        "media_types": [],
        "metric_preferences": [
            {
                "metric": "impressions",
                "definition": "public_impressions_v1",
                "unit": "impressions",
                "window_kind": "age_aligned",
                "window_key": "age:24h",
            }
        ],
        "accepted_hypothesis": {
            "question": "Does a question-led opening increase impressions?",
            "metric": "impressions",
            "metric_definition": "public_impressions_v1",
            "unit": "impressions",
            "window_kind": "age_aligned",
            "window_key": "age:24h",
            "expected_direction": "higher",
        },
    }
    first = client.post(
        "/api/v1/creators/me/draft-assessments",
        headers={"Idempotency-Key": "analysis-request-001"},
        json=body,
    )
    equivalent_retry = client.post(
        "/api/v1/creators/me/draft-assessments",
        headers={"Idempotency-Key": "analysis-request-001"},
        json={**body, "text": "A synthetic creator draft\r\nasking a question?"},
    )

    assert first.status_code == 201
    assert equivalent_retry.status_code == 201
    assert first.json() == equivalent_retry.json()
    payload = first.json()
    assert payload["decision_state"] == "supported"
    assert payload["accepted_hypothesis"] == body["accepted_hypothesis"]
    assert len(payload["comparable_evidence"]) == 9
    assert payload["versions"]["baseline"] == "creator-baseline-v1"
    metric = payload["metrics"][0]
    assert metric["statistics"]["maximum"] == 800.0
    assert metric["statistics"]["maximum"] < 999999
    assert metric["eligible_post_count"] == 9
    assert metric["statistics"]["minimum"] == 50.0
    assert metric["exclusion_counts"] == [["observed_after_as_of", 1]]
    assert metric["outlook"] is not None

    saved = session.get(DraftAssessment, UUID(payload["assessment_id"]))
    assert saved is not None
    assert saved.content_fingerprint == payload["input_fingerprint"]
    assert saved.accepted_hypothesis == body["accepted_hypothesis"]
    frozen_snapshot = saved.decision_snapshot

    changed_hypothesis = client.post(
        "/api/v1/creators/me/draft-assessments",
        headers={"Idempotency-Key": "analysis-request-001"},
        json={
            **body,
            "accepted_hypothesis": {
                **body["accepted_hypothesis"],
                "question": "A different accepted hypothesis?",
            },
        },
    )
    assert changed_hypothesis.status_code == 409

    changed = client.post(
        "/api/v1/creators/me/draft-assessments",
        headers={"Idempotency-Key": "analysis-request-001"},
        json={**body, "text": "Different draft"},
    )
    assert changed.status_code == 409
    assert session.get(DraftAssessment, saved.id).decision_snapshot == frozen_snapshot


def test_creator_baseline_endpoint_returns_exact_window_zero_values_and_scoped_history(
    session: Session,
) -> None:
    creator, other_creator = _creator(session), _creator(session)
    own_posts = _seed_analysis_history(session, creator.id)
    foreign_post = _post(session, other_creator.id, published_at=NOW - timedelta(days=40))
    session.add(
        OutcomeObservationRecord(
            id=uuid4(),
            post_id=foreign_post.id,
            creator_id=other_creator.id,
            published_at=foreign_post.published_at,
            metric_name="impressions",
            metric_definition="public_impressions_v1",
            metric_unit="impressions",
            metric_value=Decimal("900000"),
            state="observed",
            window_kind="age_aligned",
            window_key="age:24h",
            observed_at=foreign_post.published_at + timedelta(hours=24),
            idempotency_key="foreign-observation",
            provenance={},
        )
    )
    # Include a legitimate measured zero and an explicitly missing observation.
    zero = own_posts[0]
    row = session.scalar(
        select(OutcomeObservationRecord).where(OutcomeObservationRecord.post_id == zero.id)
    )
    assert row is not None
    row.metric_value = Decimal("0")
    session.add(
        OutcomeObservationRecord(
            id=uuid4(),
            post_id=zero.id,
            creator_id=creator.id,
            published_at=zero.published_at,
            metric_name="impressions",
            metric_definition="public_impressions_v1",
            metric_unit="impressions",
            metric_value=Decimal("25"),
            state="observed",
            window_kind="age_aligned",
            window_key="age:24h",
            observed_at=NOW - timedelta(minutes=2),
            idempotency_key="updated-zero-snapshot",
            provenance={"source": "synthetic_refresh"},
        )
    )
    missing_post = own_posts[1]
    session.add(
        OutcomeObservationRecord(
            id=uuid4(),
            post_id=missing_post.id,
            creator_id=creator.id,
            published_at=missing_post.published_at,
            metric_name="replies",
            metric_definition="public_reply_count_v1",
            metric_unit="replies",
            metric_value=None,
            state="missing",
            window_kind="age_aligned",
            window_key="age:24h",
            observed_at=NOW - timedelta(minutes=1),
            idempotency_key="missing-reply-count",
            provenance={"reason": "not_returned"},
        )
    )
    # An incompatible window observed after the cutoff must not affect a backtest.
    future_post = own_posts[2]
    session.add(
        OutcomeObservationRecord(
            id=uuid4(),
            post_id=future_post.id,
            creator_id=creator.id,
            published_at=future_post.published_at,
            metric_name="impressions",
            metric_definition="public_impressions_v1",
            metric_unit="impressions",
            metric_value=Decimal("1234"),
            state="observed",
            window_kind="age_aligned",
            window_key="age:6h",
            observed_at=NOW + timedelta(seconds=1),
            idempotency_key="future-incompatible-window",
            provenance={},
        )
    )
    session.flush()

    client = _authorized_client(session, creator.id)
    params = {
        "metric": "impressions",
        "definition": "public_impressions_v1",
        "unit": "impressions",
        "window_kind": "age_aligned",
        "window_key": "age:24h",
        "as_of": NOW.isoformat(),
    }
    response = client.get("/api/v1/creators/me/baseline", params=params)

    assert response.status_code == 200
    payload = response.json()
    assert payload["metric"] == {
        "metric": "impressions",
        "definition": "public_impressions_v1",
        "unit": "impressions",
        "window_kind": "age_aligned",
        "window_key": "age:24h",
    }
    assert payload["eligible_post_count"] == 9
    assert payload["statistics"]["minimum"] == 25.0
    assert payload["eligible_post_count"] == 9
    assert payload["statistics"]["maximum"] == 800.0
    assert str(foreign_post.id) not in payload["supporting_post_ids"]

    no_history = client.get(
        "/api/v1/creators/me/baseline",
        params={**params, "metric": "quotes", "definition": "public_quote_count_v1"},
    )
    assert no_history.status_code == 200
    assert no_history.json()["evidence_strength"] == "Insufficient"
    assert no_history.json()["statistics"] is None

    unsupported_window = client.get(
        "/api/v1/creators/me/baseline",
        params={**params, "window_key": "age:6h"},
    )
    assert unsupported_window.status_code == 422
    assert unsupported_window.json()["error"]["code"] == "unsupported_observation_window"

    unsupported_definition = client.get(
        "/api/v1/creators/me/baseline",
        params={**params, "definition": "unrecorded_definition_v9"},
    )
    assert unsupported_definition.status_code == 422
    assert unsupported_definition.json()["error"]["code"] == "unsupported_metric_definition"


def test_assessment_reads_are_creator_scoped_and_no_history_abstains(session: Session) -> None:
    creator_a, creator_b = _creator(session), _creator(session)
    client_a = _authorized_client(session, creator_a.id)
    response = client_a.post(
        "/api/v1/creators/me/draft-assessments",
        headers={"Idempotency-Key": "no-history-assessment"},
        json={"text": "A synthetic draft with no history."},
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["decision_state"] == "insufficient_evidence"
    assert payload["metrics"] == []
    assert payload["suggested_hypothesis"] is None

    client_b = _authorized_client(session, creator_b.id)
    foreign = client_b.get(f"/api/v1/creators/me/draft-assessments/{payload['assessment_id']}")
    assert foreign.status_code == 404


def test_postgres_manual_publication_link_preserves_immutable_assessment_and_owner(
    session: Session,
) -> None:
    creator = _creator(session)
    identity = CreatorPlatformIdentity(
        id=uuid4(),
        creator_id=creator.id,
        platform="x",
        external_creator_id="987654321",
    )
    session.add(identity)
    session.flush()
    session.add(
        XAccountConnection(
            id=uuid4(),
            creator_id=creator.id,
            creator_identity_id=identity.id,
            platform="x",
            state="connected",
            scopes=["tweet.read", "users.read"],
            encrypted_access_token=EncryptedTokenEnvelope.prefix + b"synthetic",
            key_version="v1",
            access_token_expires_at=NOW + timedelta(hours=1),
        )
    )
    assessment = DraftAssessment(
        id=uuid4(),
        creator_id=creator.id,
        assessment_key="postgres-cod361-assessment",
        assessed_at=NOW,
        content_fingerprint="sha256:" + "b" * 64,
        outlook_version="outlook-v1",
        decision_snapshot={
            "_cod361_linking": {
                "assessed_text_fingerprint": "sha256:" + "c" * 64,
                "topology": "original",
                "media_present": False,
            }
        },
        accepted_hypothesis=None,
    )
    session.add(assessment)
    session.commit()

    class FakeVerifier:
        def verify(self, _db: Session, *, creator_id: UUID, post_id: str, now: datetime):
            assert creator_id == creator.id
            assert post_id == "987654321"
            assert now == NOW + timedelta(minutes=10)
            return PublishedPostEvidence(
                external_post_id=post_id,
                author_id="987654321",
                text="published copy",
                published_at=NOW + timedelta(minutes=3),
                topology="original",
                media_present=False,
            )

    app = create_app()
    app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(creator.id)
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_current_time] = lambda: NOW + timedelta(minutes=10)
    app.dependency_overrides[get_x_publication_verifier] = lambda: FakeVerifier()
    response = TestClient(app).post(
        f"/api/v1/creators/me/draft-assessments/{assessment.id}/publication",
        json={"post_url_or_id": "https://x.com/creator/status/987654321"},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["assessment_id"] == str(assessment.id)
    assert payload["assessed_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert payload["external_post_id"] == "987654321"
    assert payload["version_match_state"] == "mismatch"
    post = session.scalar(
        select(CanonicalPost).where(CanonicalPost.external_post_id == "987654321")
    )
    assert post is not None
    assert post.source_assessment_id == assessment.id
    assert post.creator_id == creator.id


def test_postgres_duplicate_publication_links_resolve_to_one_attachment(
    session: Session,
    migrated_postgres: tuple[Engine, str],
) -> None:
    engine, schema = migrated_postgres
    creator = _creator(session)
    identity = CreatorPlatformIdentity(
        id=uuid4(),
        creator_id=creator.id,
        platform="x",
        external_creator_id="987654322",
    )
    session.add(identity)
    session.flush()
    session.add(
        XAccountConnection(
            id=uuid4(),
            creator_id=creator.id,
            creator_identity_id=identity.id,
            platform="x",
            state="connected",
            scopes=["tweet.read", "users.read"],
            encrypted_access_token=EncryptedTokenEnvelope.prefix + b"synthetic",
            key_version="v1",
            access_token_expires_at=NOW + timedelta(hours=1),
        )
    )
    assessment = DraftAssessment(
        id=uuid4(),
        creator_id=creator.id,
        assessment_key="postgres-cod361-concurrent-assessment",
        assessed_at=NOW,
        content_fingerprint="sha256:" + "d" * 64,
        outlook_version="outlook-v1",
        decision_snapshot={"_cod361_linking": {"topology": "original", "media_present": False}},
    )
    session.add(assessment)
    session.commit()

    class FakeVerifier:
        authorized_user_id = "987654322"

        def verify(self, _db: Session, *, creator_id: UUID, post_id: str, now: datetime):
            del creator_id, now
            return PublishedPostEvidence(
                external_post_id=post_id,
                author_id="987654322",
                text="same synthetic post",
                published_at=NOW + timedelta(minutes=4),
            )

    def request_once() -> tuple[int, str]:
        app = create_app()
        app.dependency_overrides[get_authenticated_creator] = lambda: AuthenticatedCreator(
            creator.id
        )
        app.dependency_overrides[get_current_time] = lambda: NOW + timedelta(minutes=10)
        app.dependency_overrides[get_x_publication_verifier] = lambda: FakeVerifier()

        def override_db() -> Iterator[Session]:
            connection = engine.connect()
            connection.execute(text(f'SET search_path TO "{schema}", public'))
            connection.commit()
            db = Session(bind=connection, expire_on_commit=False)
            try:
                yield db
            finally:
                db.close()
                connection.close()

        app.dependency_overrides[get_db_session] = override_db
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/creators/me/draft-assessments/{assessment.id}/publication",
                json={"post_url_or_id": "987654323"},
            )
            return response.status_code, response.text

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda _index: request_once(), range(2)))
    assert sorted(status for status, _body in statuses) == [200, 201], statuses
    assert (
        session.scalar(
            select(CanonicalPost).where(
                CanonicalPost.creator_id == creator.id,
                CanonicalPost.external_post_id == "987654323",
            )
        )
        is not None
    )
    assert (
        session.scalar(
            select(CanonicalPost.id).where(
                CanonicalPost.creator_id == creator.id,
                CanonicalPost.source_assessment_id == assessment.id,
            )
        )
        is not None
    )


def test_publication_verification_survives_attachment_rollback_without_second_paid_read(session):
    from cryptography.fernet import Fernet

    from bipme.auth.crypto import TokenCipher
    from bipme.integrations.x_publication import XPublicationSettings, XPublishedPostVerifier

    creator = _creator(session)
    connection = _x_connection(session, creator)
    identity = session.get(CreatorPlatformIdentity, connection.creator_identity_id)
    cipher = TokenCipher({"v1": Fernet.generate_key().decode()}, "v1")
    secret = cipher.encrypt("synthetic-token")
    connection.encrypted_access_token = secret.envelope
    connection.key_version = secret.key_version
    session.commit()

    class Provider:
        max_request_attempts = 1
        calls = 0

        def published_post(self, *, access_token, post_id):
            self.calls += 1
            return PublishedPostEvidence(
                external_post_id=post_id,
                author_id=identity.external_creator_id,
                text="synthetic publication",
                published_at=NOW - timedelta(minutes=1),
                media_present=False,
            )

    provider = Provider()
    verifier = XPublishedPostVerifier(
        provider=provider,
        cipher=cipher,
        settings=XPublicationSettings(
            enabled=True,
            account_entitlement_verified=True,
            data_rights_verified=True,
            allowed_user_id=identity.external_creator_id,
            estimated_cost=Decimal("0.01"),
            limits=XUsageLimits(Decimal("1"), Decimal("1"), Decimal("1"), None),
            pricing_observed_at=NOW - timedelta(days=1),
            pricing_expires_at=NOW + timedelta(days=1),
            pricing_source="synthetic-verified-price",
        ),
    )
    first = verifier.verify(session, creator_id=creator.id, post_id="999123456", now=NOW)
    # The caller's later attachment transaction can fail; evidence already committed
    # with the usage completion survives rollback and is reused by a reconstructed verifier.
    session.rollback()
    restarted = XPublishedPostVerifier(
        provider=provider, cipher=cipher, settings=verifier._settings
    )
    second = restarted.verify(session, creator_id=creator.id, post_id="999123456", now=NOW)
    assert provider.calls == 1
    assert second.external_post_id == first.external_post_id
    assert second.verified_at == first.verified_at == NOW
    assert second.text is None and second.text_fingerprint is not None
    usage = session.scalar(select(APIUsageLedger).where(APIUsageLedger.creator_id == creator.id))
    assert (
        usage is not None
        and usage.request_metadata["publication_evidence"]["text_fingerprint"]
        == second.text_fingerprint
    )
    assert "synthetic publication" not in str(usage.request_metadata)


def test_cod363_schedules_idempotent_windows_and_persists_partial_snapshot(
    migrated_postgres: tuple[Engine, str], session: Session
) -> None:
    """A linked post gets durable candidate receipts and exact partial observations."""
    from cryptography.fernet import Fernet

    from bipme.auth.crypto import TokenCipher
    from bipme.integrations.x_metric_snapshots import (
        XMetricSnapshot,
        XMetricSnapshotReader,
        XMetricSnapshotSettings,
        XMetricSnapshotUnavailable,
        XSnapshotMetric,
    )
    from bipme.jobs.metric_snapshots import MetricSnapshotScheduler, _persist_observations

    creator = _creator(session)
    external_user_id = str(creator.id.int)[:18]
    assessment = DraftAssessment(
        id=uuid4(),
        creator_id=creator.id,
        assessment_key="cod363-assessment-001",
        assessed_at=NOW - timedelta(hours=1),
        content_fingerprint="sha256:" + "a" * 64,
        outlook_version="distribution-outlook-v1",
        decision_snapshot={"version": "distribution-outlook-v1"},
    )
    session.add(assessment)
    session.flush()
    identity = CreatorPlatformIdentity(
        id=uuid4(),
        creator_id=creator.id,
        platform="x",
        external_creator_id=external_user_id,
    )
    cipher = TokenCipher({"v1": Fernet.generate_key().decode()}, "v1")
    encrypted = cipher.encrypt("synthetic-token")
    connection = XAccountConnection(
        id=uuid4(),
        creator_id=creator.id,
        creator_identity_id=identity.id,
        platform="x",
        state="connected",
        scopes=["tweet.read", "users.read"],
        encrypted_access_token=encrypted.envelope,
        key_version=encrypted.key_version,
        access_token_expires_at=NOW + timedelta(days=1),
    )
    post = CanonicalPost(
        id=uuid4(),
        creator_id=creator.id,
        platform="x",
        external_post_id="999123456",
        published_at=NOW,
        source_assessment_id=assessment.id,
        availability="available",
        topology="original",
        source="x_authorized_publication_verification",
        provenance={},
    )
    session.add_all((identity, connection, post))
    session.flush()

    class Provider:
        max_request_attempts = 1

        def post_metrics(self, *, access_token: str, post_id: str) -> XMetricSnapshot:
            assert access_token == "synthetic-token"
            return XMetricSnapshot(
                external_post_id=post_id,
                author_id=external_user_id,
                published_at=NOW,
                observed_at=NOW + timedelta(minutes=5),
                metrics={
                    "like_count": XSnapshotMetric(4, "synthetic likes"),
                    "impression_count": XSnapshotMetric(
                        None, "synthetic impressions", missing_reason="not_returned"
                    ),
                },
            )

    settings = XMetricSnapshotSettings(
        enabled=True,
        account_entitlement_verified=True,
        data_rights_verified=True,
        allowed_user_id=external_user_id,
        estimated_cost=Decimal("0.001"),
        limits=XUsageLimits(Decimal("1"), Decimal("1"), Decimal("1"), None),
        per_post_limit=Decimal("0.01"),
        pricing_observed_at=NOW - timedelta(hours=1),
        pricing_expires_at=NOW + timedelta(hours=1),
        pricing_source="synthetic:test",
    )
    reader = XMetricSnapshotReader(provider=Provider(), cipher=cipher, settings=settings)
    app = App(connector=SyncPsycopgConnector())

    @app.task(name=TASK_NAME, queue="bipme")
    def dispatch(receipt_id: str) -> None:
        del receipt_id

    scheduler = MetricSnapshotScheduler(app=app, reader=reader)
    first = scheduler.schedule(
        session,
        creator_id=creator.id,
        post_id=post.id,
        required_x_connection_id=connection.id,
        now=NOW,
    )
    second = scheduler.schedule(
        session,
        creator_id=creator.id,
        post_id=post.id,
        required_x_connection_id=connection.id,
        now=NOW,
    )
    assert len(first) == len(second) == 8
    assert len({job.id for job in first}) == 8

    evidence = reader.observe(
        session,
        creator_id=creator.id,
        post=post,
        window_key="age:5m",
        scheduled_at=NOW + timedelta(minutes=5),
        now=NOW + timedelta(minutes=5),
    )
    _persist_observations(session, first[0], post, "age:5m", NOW + timedelta(minutes=5), evidence)
    session.commit()
    rows = session.scalars(
        select(OutcomeObservationRecord).where(
            OutcomeObservationRecord.post_id == post.id,
            OutcomeObservationRecord.window_key == "age:5m",
        )
    ).all()
    assert {row.metric_name: row.state for row in rows} == {
        "like_count": "observed",
        "impression_count": "missing",
    }
    assert all(row.observed_at == NOW + timedelta(minutes=5) for row in rows)

    tight_reader = XMetricSnapshotReader(
        provider=Provider(),
        cipher=cipher,
        settings=XMetricSnapshotSettings(
            **{**settings.__dict__, "per_post_limit": Decimal("0.001")}
        ),
    )
    with pytest.raises(XMetricSnapshotUnavailable, match="budget_exhausted"):
        tight_reader.observe(
            session,
            creator_id=creator.id,
            post=post,
            window_key="age:15m",
            scheduled_at=NOW + timedelta(minutes=15),
            now=NOW + timedelta(minutes=15),
        )

    class FailingProvider(Provider):
        def post_metrics(self, *, access_token: str, post_id: str) -> XMetricSnapshot:
            raise XMetricSnapshotUnavailable(
                "provider_unavailable", ambiguous=True, request_count=1
            )

    failing_reader = XMetricSnapshotReader(
        provider=FailingProvider(), cipher=cipher, settings=settings
    )
    with pytest.raises(XMetricSnapshotUnavailable) as failure:
        failing_reader.observe(
            session,
            creator_id=creator.id,
            post=post,
            window_key="age:30m",
            scheduled_at=NOW + timedelta(minutes=30),
            now=NOW + timedelta(minutes=30),
        )
    assert failure.value.ambiguous
    failed_ledger = session.scalar(
        select(APIUsageLedger).where(APIUsageLedger.idempotency_key.endswith(":age:30m"))
    )
    assert failed_ledger is not None and failed_ledger.completed_at is not None
    assert failed_ledger.request_metadata["response_received"] is False

    connection.state = "revoked"
    connection.encrypted_access_token = None
    connection.encrypted_refresh_token = None
    connection.access_token_expires_at = None
    connection.revoked_at = NOW
    session.commit()
    with pytest.raises(XMetricSnapshotUnavailable, match="connection_unavailable"):
        reader.observe(
            session,
            creator_id=creator.id,
            post=post,
            window_key="age:1h",
            scheduled_at=NOW + timedelta(hours=1),
            now=NOW + timedelta(minutes=45),
        )
