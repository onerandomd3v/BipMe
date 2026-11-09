"""Transactional submission and permanent idempotency receipts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from procrastinate import App
from psycopg import Connection as PsycopgConnection
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from bipme.persistence.models import ScheduledJob

QUEUE = "bipme"
TASK_NAME = "bipme.jobs.runtime.dispatch_receipt"


class IdempotencyConflict(ValueError):
    """An idempotency key was reused for different submitted input."""


def canonical_digest(
    *,
    handler_name: str,
    arguments: dict[str, Any],
    scheduled_at: datetime,
    required_x_connection_id: UUID | None,
    max_attempts: int,
) -> str:
    if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
        raise ValueError("scheduled_at_must_be_aware")
    payload = {
        "handler": handler_name,
        "arguments": arguments,
        "scheduled_at": scheduled_at.astimezone(UTC).isoformat(),
        "required_x_connection_id": (
            None if required_x_connection_id is None else str(required_x_connection_id)
        ),
        "max_attempts": max_attempts,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def schedule_job(
    db: Session,
    app: App,
    *,
    creator_id: UUID,
    idempotency_key: str,
    handler_name: str,
    arguments: dict[str, Any],
    scheduled_at: datetime,
    required_x_connection_id: UUID | None = None,
    max_attempts: int = 3,
) -> ScheduledJob:
    """Insert receipt and runner job in the caller-owned SQLAlchemy transaction."""
    if _IDENTIFIER.fullmatch(idempotency_key) is None:
        raise ValueError("invalid_idempotency_key")
    if len(handler_name) > 100 or _IDENTIFIER.fullmatch(handler_name) is None:
        raise ValueError("invalid_handler")
    if max_attempts < 1 or max_attempts > 10:
        raise ValueError("invalid_max_attempts")
    if scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
        raise ValueError("scheduled_at_must_be_aware")
    if not isinstance(arguments, dict) or not _identifier_tree(arguments):
        raise ValueError("arguments_must_be_bounded_identifiers")
    if len(json.dumps(arguments, separators=(",", ":"))) > 8192:
        raise ValueError("arguments_too_large")
    digest = canonical_digest(
        handler_name=handler_name,
        arguments=arguments,
        scheduled_at=scheduled_at,
        required_x_connection_id=required_x_connection_id,
        max_attempts=max_attempts,
    )
    db.flush()
    receipt_id = uuid4()
    result = db.execute(
        text(
            "INSERT INTO scheduled_jobs "
            "(id, creator_id, idempotency_key, handler_name, arguments, input_digest, "
            "required_x_connection_id, max_attempts, scheduled_at) "
            "VALUES (:id, :creator_id, :key, :handler, CAST(:args AS jsonb), :digest, "
            ":connection_id, :max_attempts, :scheduled_at) "
            "ON CONFLICT (creator_id, idempotency_key) DO NOTHING RETURNING id"
        ),
        {
            "id": receipt_id,
            "creator_id": creator_id,
            "key": idempotency_key,
            "handler": handler_name,
            "args": json.dumps(arguments, separators=(",", ":")),
            "digest": digest,
            "connection_id": required_x_connection_id,
            "max_attempts": max_attempts,
            "scheduled_at": scheduled_at,
        },
    )
    inserted = result.scalar_one_or_none()
    if inserted is None:
        prior = db.scalar(
            select(ScheduledJob).where(
                ScheduledJob.creator_id == creator_id,
                ScheduledJob.idempotency_key == idempotency_key,
            )
        )
        if prior is None or prior.input_digest != digest:
            raise IdempotencyConflict("idempotency_key_payload_conflict")
        return prior

    connection = db.connection().connection.driver_connection
    if not isinstance(connection, PsycopgConnection):
        raise TypeError("scheduling_requires_psycopg3_connection")
    app.perform_import_paths()
    queue_job_id = (
        app.tasks[TASK_NAME]
        .configure(
            connection=connection,
            queue=QUEUE,
            lock=str(receipt_id),
            queueing_lock=str(receipt_id),
            schedule_at=scheduled_at,
        )
        .defer(receipt_id=str(receipt_id))
    )
    receipt = db.get(ScheduledJob, receipt_id)
    assert receipt is not None
    receipt.runner_job_id = queue_job_id
    return receipt


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,255}$")


def _identifier_tree(value: Any, depth: int = 0) -> bool:
    if depth > 6:
        return False
    if isinstance(value, dict):
        return len(value) <= 32 and all(
            isinstance(key, str)
            and _IDENTIFIER.fullmatch(key) is not None
            and _identifier_tree(item, depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return len(value) <= 100 and all(_identifier_tree(item, depth + 1) for item in value)
    return (
        type(value) is int
        and 0 <= value <= 2**63 - 1
        or (isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None)
    )
