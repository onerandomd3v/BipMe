"""Real PostgreSQL/process lifecycle evidence for COD-362 (POSIX CI)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from bipme.jobs.runtime import TASK_NAME, JobRuntimeSettings, create_runtime
from bipme.jobs.service import schedule_job
from bipme.persistence.models import Creator, CreatorPlatformIdentity, XAccountConnection

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX signal lifecycle evidence")
API = Path(__file__).parents[1]


@pytest.fixture
def database() -> Iterator[tuple[Engine, str]]:
    url = os.getenv("BIPME_TEST_DATABASE_URL")
    if not url:
        pytest.skip("BIPME_TEST_DATABASE_URL required")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    database_name = f"cod362_{uuid4().hex}"
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    isolated = admin.url.set(database=database_name)
    engine = create_engine(isolated)
    try:
        with engine.begin() as connection:
            config = Config(str(API / "alembic.ini"))
            config.set_main_option("script_location", str(API / "alembic"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.execute(
                text(
                    "CREATE TABLE synthetic_calls (receipt_id uuid, process_id integer, "
                    "called_at timestamptz NOT NULL DEFAULT clock_timestamp())"
                )
            )
        yield engine, isolated.render_as_string(hide_password=False)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{database_name}" WITH (FORCE)'))
        admin.dispose()


def row(engine: Engine, receipt_id: UUID):
    with engine.connect() as db:
        return db.execute(
            text(
                "SELECT s.outcome, s.failure_code, s.finished_at, j.status::text AS status, "
                "j.scheduled_at, j.attempts FROM scheduled_jobs s "
                "JOIN procrastinate_jobs j ON j.id=s.runner_job_id WHERE s.id=:id"
            ),
            {"id": receipt_id},
        ).one()


def scalar(engine: Engine, sql: str):
    with engine.connect() as db:
        return db.scalar(text(sql))


def wait_for(predicate, process: subprocess.Popen, *, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert process.poll() is None, f"worker exited unexpectedly: {process.returncode}"
        assert time.monotonic() < deadline, "worker condition timed out"
        time.sleep(0.02)


@contextmanager
def worker(url: str, directory: Path, mode: str = "success") -> Iterator[subprocess.Popen]:
    with (directory / f"{uuid4().hex}.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, str(API / "tests/process_worker.py")],
            cwd=API,
            env={
                **os.environ,
                "BIPME_DATABASE_URL": url,
                "WORKER_TEST_DIRECTORY": str(directory),
                "WORKER_TEST_MODE": mode,
            },
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            yield process
        except BaseException:
            log.seek(0)
            print(log.read())
            raise
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)


def submit(engine: Engine, url: str, *, delay: int = 0, billable: bool = False):
    runtime = create_runtime(JobRuntimeSettings(url))
    try:
        with Session(engine) as db:
            creator = Creator(id=uuid4())
            db.add(creator)
            db.flush()
            connection_id = None
            if billable:
                identity = CreatorPlatformIdentity(
                    id=uuid4(),
                    creator_id=creator.id,
                    platform="x",
                    external_creator_id=uuid4().hex,
                )
                db.add(identity)
                db.flush()
                connection = XAccountConnection(
                    id=uuid4(),
                    creator_id=creator.id,
                    creator_identity_id=identity.id,
                    platform="x",
                    state="connected",
                    scopes=["tweet.read"],
                    encrypted_access_token=b"BIPME-ENC\x01synthetic-ciphertext",
                    key_version="synthetic",
                )
                db.add(connection)
                db.flush()
                connection_id = connection.id
            scheduled_at = datetime.now(UTC) + timedelta(seconds=delay)
            arguments = dict(
                creator_id=creator.id,
                idempotency_key="process:verification",
                handler_name="synthetic.process",
                arguments={"test_id": "synthetic"},
                scheduled_at=scheduled_at,
                required_x_connection_id=connection_id,
            )
            receipt = schedule_job(db, runtime.app, **arguments)
            receipt_id = receipt.id
            db.commit()
            # A second submission must resolve to the same durable receipt/queue entry.
            assert schedule_job(db, runtime.app, **arguments).id == receipt_id
            db.commit()
            return receipt_id, scheduled_at
    finally:
        runtime.close()


@pytest.mark.parametrize("signum", [signal.SIGTERM, getattr(signal, "SIGKILL", 9)])
def test_delayed_job_survives_real_process_restart(database, tmp_path, signum) -> None:
    engine, url = database
    with worker(url, tmp_path) as first:
        wait_for(lambda: scalar(engine, "SELECT count(*) FROM procrastinate_workers") == 1, first)
        receipt_id, scheduled_at = submit(engine, url, delay=5)
        state = row(engine, receipt_id)
        assert state.status == "todo" and state.outcome is None
        assert state.scheduled_at == scheduled_at > datetime.now(UTC)
        assert scalar(engine, "SELECT count(*) FROM synthetic_calls") == 0
        first.send_signal(signum)
        first.wait(timeout=10)
        assert first.returncode == (0 if signum == signal.SIGTERM else -signal.SIGKILL)
        assert row(engine, receipt_id).status == "todo"
        with worker(url, tmp_path) as second:
            assert second.pid != first.pid
            wait_for(lambda: row(engine, receipt_id).status == "succeeded", second)
            state = row(engine, receipt_id)
            assert state.outcome == "succeeded" and state.finished_at >= scheduled_at
            assert state.scheduled_at == scheduled_at
            assert scalar(engine, "SELECT count(*) FROM synthetic_calls") == 1
            assert scalar(engine, "SELECT process_id FROM synthetic_calls") == second.pid
            assert scalar(engine, "SELECT min(called_at) FROM synthetic_calls") >= scheduled_at
            second.terminate()
            assert second.wait(timeout=10) == 0
    assert scalar(engine, "SELECT count(*) FROM procrastinate_jobs") == 1
    redeliver(engine, url, receipt_id)
    # A fresh process handles an actual duplicate dispatch without rerunning the handler.
    with worker(url, tmp_path) as third:
        wait_for(
            lambda: (
                scalar(engine, "SELECT count(*) FROM procrastinate_jobs WHERE status='succeeded'")
                == 2
            ),
            third,
        )
        third.terminate()
        assert third.wait(timeout=10) == 0
    assert scalar(engine, "SELECT count(*) FROM synthetic_calls") == 1


def redeliver(engine: Engine, url: str, receipt_id: UUID) -> None:
    runtime = create_runtime(JobRuntimeSettings(url))
    try:
        with engine.begin() as db:
            raw = db.connection.driver_connection
            runtime.app.tasks[TASK_NAME].configure(connection=raw).defer(receipt_id=str(receipt_id))
    finally:
        runtime.close()


def test_sigterm_drains_inflight_handler(database, tmp_path) -> None:
    engine, url = database
    receipt_id, _ = submit(engine, url)
    with worker(url, tmp_path, "blocked") as process:
        wait_for(lambda: (tmp_path / "entered").exists(), process)
        process.terminate()
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=0.3)
        assert row(engine, receipt_id).status == "doing"
        (tmp_path / "release").touch()
        assert process.wait(timeout=10) == 0
    assert row(engine, receipt_id).outcome == "succeeded"
    assert row(engine, receipt_id).status == "succeeded"
    assert scalar(engine, "SELECT count(*) FROM synthetic_calls") == 1


@pytest.mark.parametrize("mode", ["billable", "error"])
def test_uncertain_outcome_is_not_redelivered_after_restart(database, tmp_path, mode) -> None:
    engine, url = database
    receipt_id, _ = submit(engine, url, billable=True)
    with worker(url, tmp_path, mode) as first:
        wait_for(lambda: (tmp_path / "entered").exists(), first)
        if mode == "billable":
            assert row(engine, receipt_id).status == "doing"
            first.kill()
            assert first.wait(timeout=10) == -signal.SIGKILL
        else:
            wait_for(lambda: row(engine, receipt_id).status == "failed", first)
            first.terminate()
            assert first.wait(timeout=10) == 0
    with worker(url, tmp_path, mode) as second:
        # Genuine heartbeat expiry and supervised recovery; no database timestamp edits.
        wait_for(lambda: row(engine, receipt_id).status == "failed", second, timeout=65)
        redeliver(engine, url, receipt_id)
        wait_for(
            lambda: (
                scalar(engine, "SELECT count(*) FROM procrastinate_jobs WHERE status='failed'") == 2
            ),
            second,
            timeout=20,
        )
        state = row(engine, receipt_id)
        assert state.outcome == "needs_reconciliation"
        assert state.failure_code == (
            "worker_lost_during_billable_operation"
            if mode == "billable"
            else "handler_outcome_uncertain"
        )
        second.terminate()
        assert second.wait(timeout=10) == 0
    assert scalar(engine, "SELECT count(*) FROM synthetic_calls") == 1
    assert scalar(engine, "SELECT count(*) FROM api_usage_ledger") == (
        1 if mode == "billable" else 0
    )
    if mode == "billable":
        with engine.connect() as db:
            usage = db.execute(
                text(
                    "SELECT idempotency_key, estimated_cost, actual_cost, reconciliation_state "
                    "FROM api_usage_ledger"
                )
            ).one()
            assert usage.idempotency_key == f"scheduled-job:{receipt_id}"
            assert usage.estimated_cost == Decimal("0.01")
            assert usage.actual_cost is None
            assert usage.reconciliation_state == "pending"
