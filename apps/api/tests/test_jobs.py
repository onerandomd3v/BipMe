"""Unit coverage for bounded job identity and stalled-recovery decisions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from bipme.jobs.runtime import (
    await_shielded,
    configure_windows_event_loop,
    run_worker_supervised,
    stalled_recovery_action,
    stalled_retry_delay,
)
from bipme.jobs.service import IdempotencyConflict, _identifier_tree, canonical_digest


def _receipt(
    *, outcome: str | None = None, connection_id: object = None, max_attempts: int = 3
) -> SimpleNamespace:
    return SimpleNamespace(
        outcome=outcome,
        required_x_connection_id=connection_id,
        max_attempts=max_attempts,
    )


def test_digest_binds_every_retry_and_permission_input() -> None:
    at = datetime.now(UTC)
    base = {
        "handler_name": "history.snapshot",
        "arguments": {"post_id": "12345"},
        "scheduled_at": at,
        "required_x_connection_id": None,
        "max_attempts": 3,
    }
    expected = canonical_digest(**base)
    assert canonical_digest(**base) == expected
    assert canonical_digest(**{**base, "max_attempts": 4}) != expected
    assert canonical_digest(**{**base, "required_x_connection_id": uuid4()}) != expected
    assert canonical_digest(**{**base, "scheduled_at": at + timedelta(seconds=1)}) != expected


def test_identifier_arguments_reject_content_and_bound_nested_values() -> None:
    assert _identifier_tree({"post_id": "12345", "ids": ["a", "b"]})
    assert not _identifier_tree({"post_text": "hello world"})
    assert not _identifier_tree({"nested": {"token": "secret/value"}})


def test_stalled_recovery_retries_only_provider_independent_work() -> None:
    assert stalled_recovery_action(_receipt(), attempts=0) == "retry"
    assert stalled_recovery_action(_receipt(max_attempts=1), attempts=0) == "failed"
    assert stalled_recovery_action(_receipt(connection_id=uuid4()), attempts=0) == (
        "needs_reconciliation"
    )
    assert stalled_recovery_action(_receipt(outcome="succeeded"), attempts=0) == "finish"


def test_stalled_retry_backoff_is_capped() -> None:
    assert [stalled_retry_delay(attempt) for attempt in range(4)] == [1, 2, 4, 8]
    assert stalled_retry_delay(100) == 600


def test_digest_rejects_naive_schedule_time() -> None:
    with pytest.raises(ValueError):
        canonical_digest(
            handler_name="history.snapshot",
            arguments={},
            scheduled_at=datetime(2026, 11, 9),
            required_x_connection_id=None,
            max_attempts=3,
        )


def test_idempotency_conflict_is_specific_error() -> None:
    assert issubclass(IdempotencyConflict, ValueError)


def test_cancellation_drains_inflight_handler_thread() -> None:
    import threading

    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_work() -> None:
        started.set()
        release.wait(timeout=5)
        finished.set()

    async def exercise() -> None:
        task = asyncio.create_task(await_shielded(asyncio.to_thread(blocking_work)))
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0.03)
        assert not task.done()
        release.set()
        await task

    asyncio.run(exercise())
    assert finished.is_set()


def test_windows_runner_selects_selector_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import sys

    policies: list[object] = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(
        asyncio, "WindowsSelectorEventLoopPolicy", lambda: "selector", raising=False
    )
    monkeypatch.setattr(asyncio, "set_event_loop_policy", policies.append)
    configure_windows_event_loop()
    assert policies == ["selector"]


def test_recovery_failure_stops_worker_and_surfaces_sanitized_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bipme.jobs.runtime as runtime_module

    worker_started = asyncio.Event()
    worker_stopped = asyncio.Event()

    class FakeApp:
        async def run_worker_async(self, **_kwargs: object) -> None:
            worker_started.set()
            try:
                await asyncio.Future()
            finally:
                worker_stopped.set()

    async def broken_recovery(_runtime: object, _stop_event: asyncio.Event) -> None:
        await worker_started.wait()
        raise ValueError("sensitive database detail")

    monkeypatch.setattr(runtime_module, "recover_stalled_jobs", broken_recovery)

    async def exercise() -> None:
        stop_event = asyncio.Event()
        runtime = SimpleNamespace(app=FakeApp())
        with pytest.raises(RuntimeError, match="^stalled_recovery_failed$"):
            await run_worker_supervised(runtime, stop_event)  # type: ignore[arg-type]
        assert stop_event.is_set()
        assert worker_stopped.is_set()

    asyncio.run(exercise())


def test_recovery_observes_stop_before_stop_waiter_without_hanging_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bipme.jobs.runtime as runtime_module

    worker_stopped = asyncio.Event()
    real_wait = asyncio.wait

    class FakeApp:
        async def run_worker_async(self, **_kwargs: object) -> None:
            try:
                await asyncio.Future()
            finally:
                worker_stopped.set()

    async def recovery_sets_stop(_runtime: object, stop_event: asyncio.Event) -> None:
        stop_event.set()

    async def recovery_only_snapshot(
        tasks: set[asyncio.Task[object]], **_kwargs: object
    ) -> tuple[set[asyncio.Task[object]], set[asyncio.Task[object]]]:
        recovery_task = next(
            task for task in tasks if task.get_coro().__name__ == "recovery_sets_stop"
        )
        await recovery_task
        return {recovery_task}, tasks - {recovery_task}

    monkeypatch.setattr(runtime_module, "recover_stalled_jobs", recovery_sets_stop)
    monkeypatch.setattr(runtime_module.asyncio, "wait", recovery_only_snapshot)

    async def exercise() -> None:
        stop_event = asyncio.Event()
        runtime = SimpleNamespace(app=FakeApp())
        await run_worker_supervised(runtime, stop_event)  # type: ignore[arg-type]
        assert worker_stopped.is_set()

    try:
        asyncio.run(exercise())
    finally:
        monkeypatch.setattr(runtime_module.asyncio, "wait", real_wait)
