"""Configured Procrastinate runtime and receipt-fenced dispatch."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from procrastinate import App, JobContext, RetryStrategy
from procrastinate.jobs import Status
from procrastinate.psycopg_connector import PsycopgConnector
from procrastinate.sql import queries as procrastinate_queries
from procrastinate.sync_psycopg_connector import SyncPsycopgConnector
from psycopg import Connection as PsycopgConnection
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from bipme.persistence.models import Creator, ScheduledJob, XAccountConnection

logger = logging.getLogger(__name__)
QUEUE = "bipme"
TASK_NAME = "bipme.jobs.runtime.dispatch_receipt"
Handler = Callable[[Session, ScheduledJob], None]
_HANDLER_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")


class RetryableHandlerError(Exception):
    """A handler guarantees it failed before any external side effect."""


class TerminalJobError(Exception):
    """Sanitized signal that a non-success receipt must fail in runner state."""


@dataclass(frozen=True)
class JobRuntimeSettings:
    """Explicit validated PostgreSQL configuration for one API/worker runtime."""

    database_url: str

    def __post_init__(self) -> None:
        url = make_url(self.database_url)
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError("BIPME_DATABASE_URL_must_use_postgresql_psycopg")

    @classmethod
    def from_env(cls) -> JobRuntimeSettings:
        url = os.environ.get("BIPME_DATABASE_URL")
        if not url:
            raise ValueError("BIPME_DATABASE_URL_is_required")
        return cls(database_url=url)


@dataclass
class JobRuntime:
    """App, sessions, and fixed handler registry owned by one process."""

    app: App
    engine: Engine
    sessions: sessionmaker[Session]
    handlers: dict[str, Handler]

    def close(self) -> None:
        self.engine.dispose()


def create_runtime(
    settings: JobRuntimeSettings,
    *,
    handlers: Mapping[str, Handler] | None = None,
    retry_exponential_wait: int = 2,
) -> JobRuntime:
    """Construct runtime resources without reading process configuration at import time."""
    registered = dict(handlers or {})
    if any(_HANDLER_NAME.fullmatch(name) is None for name in registered):
        raise ValueError("invalid_handler_name")
    if not 1 <= retry_exponential_wait <= 60:
        raise ValueError("invalid_retry_backoff")
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    psycopg_url = make_url(settings.database_url).set(drivername="postgresql")
    app = App(
        connector=PsycopgConnector(conninfo=psycopg_url.render_as_string(hide_password=False))
    )
    runtime = JobRuntime(app=app, engine=engine, sessions=sessions, handlers=registered)

    @app.task(
        name=TASK_NAME,
        queue=QUEUE,
        pass_context=True,
        retry=RetryStrategy(
            max_attempts=10,
            exponential_wait=retry_exponential_wait,
            retry_exceptions=(RetryableHandlerError,),
        ),
    )
    async def dispatch(context: JobContext, receipt_id: str) -> None:
        """Run a bounded handler and drain its thread before worker cancellation returns."""
        task = asyncio.to_thread(_execute_receipt, runtime, UUID(receipt_id), context.job.attempts)
        await await_shielded(task)

    return runtime


async def await_shielded(awaitable: Awaitable[None]) -> None:
    """Drain sync work after cancellation so Procrastinate cannot release its claim early."""
    task = asyncio.ensure_future(awaitable)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # Deliberately consume cancellation only after the non-cancellable thread is done.
        # Returning its normal result keeps receipt and Procrastinate statuses aligned.
        await task


def _execute_receipt(runtime: JobRuntime, receipt_id: UUID, previous_attempts: int) -> None:
    with runtime.sessions() as execution_db:
        receipt = execution_db.scalar(
            select(ScheduledJob).where(ScheduledJob.id == receipt_id).with_for_update()
        )
        if receipt is None:
            raise TerminalJobError("receipt_unavailable")
        if receipt.outcome is not None:
            if receipt.outcome == "succeeded":
                return
            raise TerminalJobError("receipt_already_terminal")

        if execution_db.get(Creator, receipt.creator_id) is None:
            _finish_receipt(execution_db, receipt, "failed", "creator_unavailable")
            raise TerminalJobError("creator_unavailable")
        if receipt.required_x_connection_id is not None:
            connection = execution_db.scalar(
                select(XAccountConnection).where(
                    XAccountConnection.id == receipt.required_x_connection_id,
                    XAccountConnection.creator_id == receipt.creator_id,
                    XAccountConnection.platform == "x",
                    XAccountConnection.state == "connected",
                )
            )
            if connection is None:
                _finish_receipt(execution_db, receipt, "revoked", "connection_unavailable")
                raise TerminalJobError("connection_unavailable")
        handler = runtime.handlers.get(receipt.handler_name)
        if handler is None:
            _finish_receipt(execution_db, receipt, "failed", "handler_unavailable")
            raise TerminalJobError("handler_unavailable")

        # Hold the receipt fence only. The bounded handler gets its own Session so its
        # ledger code can commit and lock Creator/X connection rows without self-deadlock.
        try:
            with runtime.sessions() as handler_db:
                handler_receipt = handler_db.get(ScheduledJob, receipt_id)
                if handler_receipt is None:
                    raise RuntimeError("receipt_unavailable")
                handler(handler_db, handler_receipt)
                handler_db.commit()
        except RetryableHandlerError:
            if previous_attempts + 1 < receipt.max_attempts:
                execution_db.rollback()
                raise RetryableHandlerError("safe_retry") from None
            _finish_receipt(execution_db, receipt, "failed", "retry_limit_exhausted")
            raise TerminalJobError("retry_limit_exhausted") from None
        except Exception:
            _finish_receipt(
                execution_db, receipt, "needs_reconciliation", "handler_outcome_uncertain"
            )
            raise TerminalJobError("handler_outcome_uncertain") from None
        else:
            _finish_receipt(execution_db, receipt, "succeeded", None)


def _finish_receipt(
    db: Session, receipt: ScheduledJob, outcome: str, failure_code: str | None
) -> None:
    receipt.outcome = outcome
    receipt.failure_code = failure_code
    receipt.finished_at = datetime.now(UTC)
    db.commit()
    logger.info(
        "scheduled_job_finished",
        extra={"receipt_id": str(receipt.id), "outcome": outcome},
    )


def stalled_recovery_action(receipt: ScheduledJob, attempts: int) -> str:
    """Select recovery from current receipt state and bounded attempts."""
    if receipt.outcome is not None:
        return "finish"
    if receipt.required_x_connection_id is not None:
        return "needs_reconciliation"
    if attempts + 1 < receipt.max_attempts:
        return "retry"
    return "failed"


def stalled_retry_delay(attempts: int) -> int:
    """Bound retry backoff to at most ten minutes."""
    return int(min(2 ** max(0, attempts), 600))


async def recover_stalled_jobs(runtime: JobRuntime, stop_event: asyncio.Event) -> None:
    """Use heartbeat candidates and revalidate/transition each claim atomically."""
    while not stop_event.is_set():
        candidates = await runtime.app.job_manager.get_stalled_jobs(
            queue=QUEUE, task_name=TASK_NAME, seconds_since_heartbeat=30
        )
        for job in candidates:
            receipt_id = job.task_kwargs.get("receipt_id")
            if job.id is None or not isinstance(receipt_id, str):
                continue
            await await_shielded(
                asyncio.to_thread(
                    _recover_stalled_job,
                    runtime,
                    job.id,
                    receipt_id,
                )
            )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=15)
        except TimeoutError:
            continue


def _recover_stalled_job(runtime: JobRuntime, runner_job_id: int, receipt_text: str) -> None:
    try:
        receipt_id = UUID(receipt_text)
    except ValueError:
        return
    with runtime.sessions() as db:
        # Procrastinate prunes workers by deleting the worker row; its FK action then
        # updates jobs. Lock the worker first so pruning and recovery use the same order.
        candidate = (
            db.execute(
                text(
                    "SELECT id, queue_name, task_name, args, status::text AS status, attempts, worker_id "
                    "FROM procrastinate_jobs WHERE id = :job_id"
                ),
                {"job_id": runner_job_id},
            )
            .mappings()
            .one_or_none()
        )
        if (
            candidate is None
            or candidate["status"] != Status.DOING.value
            or candidate["queue_name"] != QUEUE
            or candidate["task_name"] != TASK_NAME
            or candidate["args"].get("receipt_id") != receipt_text
        ):
            return
        candidate_worker_id = candidate["worker_id"]
        heartbeat = None
        worker_was_pruned = False
        if candidate_worker_id is not None:
            worker = (
                db.execute(
                    text(
                        "SELECT id, last_heartbeat FROM procrastinate_workers "
                        "WHERE id = :id FOR UPDATE SKIP LOCKED"
                    ),
                    {"id": candidate_worker_id},
                )
                .mappings()
                .one_or_none()
            )
            if worker is None:
                # SKIP LOCKED alone cannot tell an active prune lock from a missing row.
                # A plain existence read distinguishes them without waiting on the lock.
                worker_exists = db.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM procrastinate_workers WHERE id=:id)"),
                    {"id": candidate_worker_id},
                )
                if worker_exists:
                    return
                worker_was_pruned = True
            else:
                heartbeat = worker["last_heartbeat"]

        receipt = db.scalar(
            select(ScheduledJob)
            .where(ScheduledJob.id == receipt_id)
            .with_for_update(skip_locked=True)
        )
        if receipt is None:
            return
        # With the worker (when present) and receipt fences held, lock and revalidate
        # the runner before changing either state. A concurrent claim/reassignment wins.
        runner = (
            db.execute(
                text(
                    "SELECT id, queue_name, task_name, args, status::text AS status, attempts, worker_id "
                    "FROM procrastinate_jobs WHERE id = :job_id FOR UPDATE SKIP LOCKED"
                ),
                {"job_id": runner_job_id},
            )
            .mappings()
            .one_or_none()
        )
        if (
            runner is None
            or runner["status"] != Status.DOING.value
            or runner["queue_name"] != QUEUE
            or runner["task_name"] != TASK_NAME
            or runner["args"].get("receipt_id") != receipt_text
            or (
                runner["worker_id"] != candidate_worker_id
                and not (worker_was_pruned and runner["worker_id"] is None)
            )
        ):
            return
        now = datetime.now(UTC)
        if heartbeat is not None and heartbeat > now - timedelta(seconds=30):
            return

        action = stalled_recovery_action(receipt, runner["attempts"])
        raw = db.connection().connection.driver_connection
        if not isinstance(raw, PsycopgConnection):
            raise TypeError("recovery_requires_psycopg3_connection")
        connector = SyncPsycopgConnector()
        if action == "finish":
            status = Status.SUCCEEDED if receipt.outcome == "succeeded" else Status.FAILED
            db.flush()
            connector.execute_query_one_with_connection(
                raw,
                query=procrastinate_queries["finish_job"],
                job_id=runner_job_id,
                status=status.value,
                delete_job=False,
            )
        elif action == "needs_reconciliation":
            receipt.outcome = "needs_reconciliation"
            receipt.failure_code = "worker_lost_during_billable_operation"
            receipt.finished_at = now
            db.flush()
            connector.execute_query_one_with_connection(
                raw,
                query=procrastinate_queries["finish_job"],
                job_id=runner_job_id,
                status=Status.FAILED.value,
                delete_job=False,
            )
        elif action == "retry":
            db.flush()
            connector.execute_query_one_with_connection(
                raw,
                query=procrastinate_queries["retry_job"],
                job_id=runner_job_id,
                retry_at=now + timedelta(seconds=stalled_retry_delay(runner["attempts"])),
                new_priority=None,
                new_queue_name=None,
                new_lock=None,
            )
        else:
            receipt.outcome = "failed"
            receipt.failure_code = "worker_retry_limit_exhausted"
            receipt.finished_at = now
            db.flush()
            connector.execute_query_one_with_connection(
                raw,
                query=procrastinate_queries["finish_job"],
                job_id=runner_job_id,
                status=Status.FAILED.value,
                delete_job=False,
            )
        db.commit()


async def run_worker_supervised(
    runtime: JobRuntime,
    stop_event: asyncio.Event,
    *,
    graceful_timeout_seconds: float = 30,
) -> None:
    """Cooperatively stop intake, drain work, then stop periodic recovery."""
    recovery_task = asyncio.create_task(recover_stalled_jobs(runtime, stop_event))
    worker_task = asyncio.create_task(
        runtime.app.run_worker_async(
            queues=[QUEUE],
            concurrency=4,
            wait=True,
            shutdown_graceful_timeout=graceful_timeout_seconds,
            install_signal_handlers=False,
            delete_jobs="never",
        )
    )
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        done, _ = await asyncio.wait(
            {worker_task, recovery_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if recovery_task in done:
            failed = recovery_task.cancelled() or recovery_task.exception() is not None
            if failed or not stop_event.is_set():
                stop_event.set()
                if not worker_task.done():
                    worker_task.cancel()
                    await asyncio.gather(worker_task, return_exceptions=True)
                # Do not expose connector/database exception details through worker logs.
                raise RuntimeError("stalled_recovery_failed") from None
        # Recovery can observe the externally-set event and finish before stop_task is
        # included in the completed snapshot. Key shutdown off the event itself so that
        # done-set ordering cannot leave the worker running indefinitely.
        if stop_event.is_set() and not worker_task.done():
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
        else:
            await worker_task
    finally:
        stop_event.set()
        stop_task.cancel()
        if not worker_task.done():
            worker_task.cancel()
        await asyncio.gather(worker_task, stop_task, return_exceptions=True)
        recovery_task.cancel()
        await asyncio.gather(recovery_task, return_exceptions=True)


def configure_windows_event_loop() -> None:
    """Select the Proactor-incompatible Windows event loop before asyncio.run."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
