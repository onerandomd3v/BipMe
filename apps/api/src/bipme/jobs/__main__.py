"""Run the PostgreSQL worker as ``python -m bipme.jobs``."""

from __future__ import annotations

import asyncio
import signal
import sys

from bipme.jobs.metric_snapshots import HANDLER_NAME, build_metric_snapshot_handler
from bipme.jobs.runtime import (
    JobRuntimeSettings,
    configure_windows_event_loop,
    create_runtime,
    run_worker_supervised,
)


async def _run() -> None:
    handler = build_metric_snapshot_handler()
    runtime = create_runtime(
        JobRuntimeSettings.from_env(),
        handlers={HANDLER_NAME: handler} if handler is not None else None,
    )
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signum, stop_event.set)
    try:
        async with runtime.app.open_async():
            await run_worker_supervised(runtime, stop_event)
    finally:
        runtime.close()


def main() -> None:
    """Run under an explicit event-loop and cooperative shutdown policy."""
    configure_windows_event_loop()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
