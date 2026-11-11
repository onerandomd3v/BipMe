"""Fail-closed, creator-scoped reservations over the shared provider usage ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from bipme.persistence.models import APIUsageLedger, Creator


class UsageBudgetError(Exception):
    """Safe usage-control failure; does not include database/provider details."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class XUsageLimits:
    total_usd: Decimal | None
    daily_usd: Decimal
    operation_usd: Decimal | None
    import_usd: Decimal | None

    def valid(self) -> bool:
        values = (self.total_usd, self.daily_usd, self.operation_usd, self.import_usd)
        return (
            all(
                value is None or (isinstance(value, Decimal) and value.is_finite() and value > 0)
                for value in values
            )
            and isinstance(self.daily_usd, Decimal)
            and self.daily_usd.is_finite()
            and self.daily_usd > 0
        )

    def complete(self) -> bool:
        return (
            self.total_usd is not None
            and self.operation_usd is not None
            and self.import_usd is not None
        )


@dataclass(frozen=True)
class UsageReservation:
    ledger_id: UUID
    already_reserved: bool = False


def reserve_x_usage(
    db: Session,
    *,
    creator_id: UUID,
    operation: str,
    idempotency_key: str,
    estimated_cost: Decimal,
    limits: XUsageLimits,
    now: datetime,
    import_id: str | None = None,
    post_id: str | None = None,
    per_post_limit: Decimal | None = None,
    request_metadata: dict[str, Any] | None = None,
) -> UsageReservation:
    """Atomically reserve estimated spend before an X request.

    The creator row is the shared serialization point used by identity reads and other X
    operations. On PostgreSQL, FOR UPDATE makes the read/compare/insert sequence atomic.
    Existing idempotency keys never create a second charge or authorize another request.
    """
    instant = now.astimezone(UTC)
    if (
        not limits.valid()
        or not estimated_cost.is_finite()
        or estimated_cost <= 0
        or not operation.strip()
        or not idempotency_key.strip()
        or (post_id is not None and not post_id.strip())
        or (per_post_limit is not None and (not per_post_limit.is_finite() or per_post_limit <= 0))
    ):
        raise UsageBudgetError("usage_controls_unavailable")
    try:
        creator = db.scalar(select(Creator).where(Creator.id == creator_id).with_for_update())
        if creator is None:
            raise UsageBudgetError("usage_controls_unavailable")
        existing = db.scalar(
            select(APIUsageLedger).where(
                APIUsageLedger.provider == "x",
                APIUsageLedger.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.creator_id != creator_id or existing.operation != operation:
                raise UsageBudgetError("duplicate_job")
            return UsageReservation(existing.id, already_reserved=True)

        ledger_rows = db.scalars(
            select(APIUsageLedger).where(
                APIUsageLedger.creator_id == creator_id,
                APIUsageLedger.provider == "x",
            )
        ).all()
        day_start = instant.replace(hour=0, minute=0, second=0, microsecond=0)
        totals = Decimal("0")
        daily = Decimal("0")
        operation_total = Decimal("0")
        import_total = Decimal("0")
        post_total = Decimal("0")
        for row in ledger_rows:
            if row.estimated_cost is None and row.actual_cost is None:
                raise UsageBudgetError("usage_controls_unavailable")
            # Pending rows hold their estimate. Reconciled rows use actual provider usage,
            # including any amount above the prior estimate.
            if row.reconciliation_state == "reconciled":
                if row.actual_cost is None:
                    raise UsageBudgetError("usage_controls_unavailable")
                charged = row.actual_cost
            else:
                charged = row.estimated_cost or row.actual_cost or Decimal("0")
            totals += charged
            if row.requested_at >= day_start:
                daily += charged
            if row.operation == operation:
                operation_total += charged
            if import_id is not None and row.request_metadata.get("import_id") == import_id:
                import_total += charged
            if post_id is not None and row.request_metadata.get("post_id") == post_id:
                post_total += charged
        if (
            (limits.total_usd is not None and totals + estimated_cost > limits.total_usd)
            or daily + estimated_cost > limits.daily_usd
            or (
                limits.operation_usd is not None
                and operation_total + estimated_cost > limits.operation_usd
            )
            or (
                import_id is not None
                and limits.import_usd is not None
                and import_total + estimated_cost > limits.import_usd
            )
            or (
                post_id is not None
                and per_post_limit is not None
                and post_total + estimated_cost > per_post_limit
            )
        ):
            raise UsageBudgetError("budget_exhausted")

        metadata = dict(request_metadata or {})
        metadata["estimated_cost_usd"] = str(estimated_cost)
        metadata["budget_period"] = "utc_day"
        if import_id is not None:
            metadata["import_id"] = import_id
        if post_id is not None:
            metadata["post_id"] = post_id
        reservation_id = uuid4()
        db.add(
            APIUsageLedger(
                id=reservation_id,
                creator_id=creator_id,
                provider="x",
                operation=operation,
                idempotency_key=idempotency_key,
                request_metadata=metadata,
                requested_at=instant,
                estimated_cost=estimated_cost,
                currency="USD",
                reconciliation_state="pending",
            )
        )
        db.commit()
        return UsageReservation(reservation_id)
    except UsageBudgetError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise UsageBudgetError("usage_controls_unavailable") from None


def reconcile_x_usage(
    db: Session,
    *,
    reservation_id: UUID,
    actual_cost: Decimal,
    usage_units: int,
    completed_at: datetime,
) -> None:
    """Record provider-reported actual usage without changing the original estimate."""
    if not actual_cost.is_finite() or actual_cost < 0 or usage_units < 0:
        raise UsageBudgetError("usage_reconciliation_invalid")
    try:
        row = db.scalar(
            select(APIUsageLedger)
            .where(
                APIUsageLedger.id == reservation_id,
                APIUsageLedger.provider == "x",
            )
            .with_for_update()
        )
        if row is None or row.reconciliation_state == "reconciled":
            raise UsageBudgetError("usage_reservation_unavailable")
        row.actual_cost = actual_cost
        row.usage_units = usage_units
        row.completed_at = completed_at.astimezone(UTC)
        row.reconciliation_state = "reconciled"
        db.commit()
    except UsageBudgetError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise UsageBudgetError("usage_controls_unavailable") from None


def complete_x_request(
    db: Session,
    *,
    reservation_id: UUID,
    usage_units: int,
    request_count: int = 1,
    completed_at: datetime,
    response_received: bool,
) -> None:
    """Record request completion while leaving estimated charges pending reconciliation."""
    if usage_units < 0 or request_count < 0:
        raise UsageBudgetError("usage_reconciliation_invalid")
    try:
        row = db.scalar(
            select(APIUsageLedger)
            .where(
                APIUsageLedger.id == reservation_id,
                APIUsageLedger.provider == "x",
            )
            .with_for_update()
        )
        if row is None or row.completed_at is not None:
            raise UsageBudgetError("usage_reservation_unavailable")
        row.completed_at = completed_at.astimezone(UTC)
        row.usage_units = usage_units
        row.request_metadata = {
            **row.request_metadata,
            "response_received": response_received,
            "request_count": request_count,
            "estimated_cost_kind": "estimate_pending_actual_reconciliation",
        }
        db.commit()
    except UsageBudgetError:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        raise UsageBudgetError("usage_controls_unavailable") from None
