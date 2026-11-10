"""Synthetic subprocess entry point; never imports an X transport."""

import asyncio
import os
import signal
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

from sqlalchemy import text
from sqlalchemy.orm import Session

from bipme.jobs.runtime import JobRuntimeSettings, create_runtime, run_worker_supervised
from bipme.persistence.models import ScheduledJob
from bipme.persistence.usage import XUsageLimits, reserve_x_usage


async def run() -> None:
    directory = Path(os.environ["WORKER_TEST_DIRECTORY"])
    mode = os.environ["WORKER_TEST_MODE"]

    def handler(db: Session, receipt: ScheduledJob) -> None:
        if mode == "billable":
            reservation = reserve_x_usage(
                db,
                creator_id=receipt.creator_id,
                operation="synthetic_snapshot",
                idempotency_key=f"scheduled-job:{receipt.id}",
                estimated_cost=Decimal("0.01"),
                limits=XUsageLimits(Decimal("1"), Decimal("1"), Decimal("1"), None),
                now=datetime.now(UTC),
            )
            assert not reservation.already_reserved
        provider = Mock()
        provider()
        provider.assert_called_once_with()
        db.execute(
            text("INSERT INTO synthetic_calls (receipt_id, process_id) VALUES (:id, :pid)"),
            {"id": receipt.id, "pid": os.getpid()},
        )
        db.commit()
        (directory / "entered").touch()
        if mode in {"blocked", "billable"}:
            # A parent-controlled barrier, with a fail-safe if the parent disappears.
            import time

            deadline = time.monotonic() + 90
            while not (directory / "release").exists():
                if time.monotonic() > deadline:
                    raise TimeoutError("synthetic_handler_barrier")
                time.sleep(0.02)
        if mode == "error":
            raise RuntimeError("synthetic_uncertain_outcome")

    runtime = create_runtime(JobRuntimeSettings.from_env(), handlers={"synthetic.process": handler})
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop.set)
    try:
        async with runtime.app.open_async():
            await run_worker_supervised(runtime, stop, graceful_timeout_seconds=0.1)
    finally:
        runtime.close()


if __name__ == "__main__":
    asyncio.run(run())
