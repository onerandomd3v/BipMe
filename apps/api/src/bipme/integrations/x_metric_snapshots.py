"""Read-only, budgeted X post metric snapshots for COD-363.

The provider boundary is deliberately small and mockable.  It returns canonical metric
values rather than exposing the X response shape to persistence or job code.
"""

from __future__ import annotations

import math
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from bipme.auth.crypto import TokenCipher, TokenEncryptionError
from bipme.persistence.models import (
    APIUsageLedger,
    CanonicalPost,
    CreatorPlatformIdentity,
    XAccountConnection,
)
from bipme.persistence.usage import (
    UsageBudgetError,
    XUsageLimits,
    complete_x_request,
    reserve_x_usage,
)

X_API_ORIGIN = "https://api.x.com"
SNAPSHOT_OPERATION = "post_metric_snapshot"
METRIC_FIELDS = {
    "like_count": ("like_count", "X public_metrics.like_count as returned at observation time"),
    "reply_count": ("reply_count", "X public_metrics.reply_count as returned at observation time"),
    "repost_count": (
        "retweet_count",
        "X public_metrics.retweet_count as returned at observation time",
    ),
    "quote_count": ("quote_count", "X public_metrics.quote_count as returned at observation time"),
    "bookmark_count": (
        "bookmark_count",
        "X public_metrics.bookmark_count as returned at observation time",
    ),
    "impression_count": (
        "impression_count",
        "X public_metrics.impression_count as returned at observation time",
    ),
}
_POST_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_USER_ID = re.compile(r"^[0-9]{1,32}$")
_PRICE_SOURCE = re.compile(r"^[A-Za-z0-9._:/-]{1,255}$")


class XMetricSnapshotUnavailable(Exception):
    """Safe provider failure. ``ambiguous`` means a paid request may have happened."""

    def __init__(self, code: str, *, ambiguous: bool = False, request_count: int = 0) -> None:
        super().__init__(code)
        self.code = code
        self.ambiguous = ambiguous
        self.request_count = request_count


@dataclass(frozen=True)
class XMetricSnapshot:
    external_post_id: str
    author_id: str
    published_at: datetime
    observed_at: datetime
    metrics: dict[str, XSnapshotMetric]
    source: str = "x_authorized_post_metrics"
    source_endpoint: str = "/2/tweets/{id}"
    request_count: int = 1


@dataclass(frozen=True)
class XSnapshotMetric:
    value: int | None
    definition: str
    unit: str = "count"
    missing_reason: str | None = None


class XPostMetricsProvider(Protocol):
    @property
    def max_request_attempts(self) -> int: ...

    def post_metrics(self, *, access_token: str, post_id: str) -> XMetricSnapshot: ...


class HttpXPostMetricsProvider:
    """Official GET /2/tweets/{id} adapter; no write endpoint exists here."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        max_retries: int = 2,
        http_client: httpx.Client | None = None,
        sleeper: Any = time.sleep,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("invalid snapshot timeout")
        if (
            not isinstance(max_retries, int)
            or isinstance(max_retries, bool)
            or not 0 <= max_retries <= 3
        ):
            raise ValueError("invalid snapshot retry count")
        self._max_retries = max_retries
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)
        self._sleep = sleeper

    @property
    def max_request_attempts(self) -> int:
        return self._max_retries + 1

    def post_metrics(self, *, access_token: str, post_id: str) -> XMetricSnapshot:
        if not _POST_ID.fullmatch(post_id) or not access_token:
            raise XMetricSnapshotUnavailable("request_invalid")
        path = f"/2/tweets/{quote(post_id, safe='')}"
        params = {"tweet.fields": "author_id,created_at,public_metrics"}
        requests = 0
        for attempt in range(self._max_retries + 1):
            requests += 1
            try:
                response = self._http.get(
                    f"{X_API_ORIGIN}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                    follow_redirects=False,
                )
            except (httpx.TimeoutException, httpx.HTTPError):
                if attempt >= self._max_retries:
                    raise XMetricSnapshotUnavailable(
                        "provider_unavailable", ambiguous=True, request_count=requests
                    ) from None
                self._sleep(min(2.0, 0.25 * float(2**attempt)))
                continue
            if response.status_code == 401:
                raise XMetricSnapshotUnavailable(
                    "reauthorization_required", ambiguous=True, request_count=requests
                )
            if response.status_code == 403:
                raise XMetricSnapshotUnavailable(
                    "permission_denied", ambiguous=True, request_count=requests
                )
            if response.status_code == 404:
                raise XMetricSnapshotUnavailable("post_not_found", request_count=requests)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self._max_retries:
                    raise XMetricSnapshotUnavailable(
                        "rate_limited" if response.status_code == 429 else "provider_unavailable",
                        ambiguous=True,
                        request_count=requests,
                    )
                self._sleep(min(2.0, 0.25 * float(2**attempt)))
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise XMetricSnapshotUnavailable(
                    "provider_rejected_request", ambiguous=True, request_count=requests
                )
            try:
                payload = response.json()
                data = payload["data"]
                returned_id = data["id"]
                author_id = data["author_id"]
                created_at = data["created_at"]
                if (
                    not isinstance(data, dict)
                    or not isinstance(returned_id, str)
                    or returned_id != post_id
                    or not _POST_ID.fullmatch(returned_id)
                    or not isinstance(author_id, str)
                    or not _USER_ID.fullmatch(author_id)
                    or not isinstance(created_at, str)
                ):
                    raise ValueError
                published_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if published_at.tzinfo is None or published_at.utcoffset() is None:
                    raise ValueError
                raw_metrics = data.get("public_metrics")
                if raw_metrics is not None and not isinstance(raw_metrics, dict):
                    raise ValueError
                metrics: dict[str, XSnapshotMetric] = {}
                for name, (field, definition) in METRIC_FIELDS.items():
                    value = raw_metrics.get(field) if isinstance(raw_metrics, dict) else None
                    if value is None:
                        metrics[name] = XSnapshotMetric(
                            None, definition, missing_reason="not_returned"
                        )
                    elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                        metrics[name] = XSnapshotMetric(value, definition)
                    else:
                        metrics[name] = XSnapshotMetric(
                            None, definition, missing_reason="invalid_value"
                        )
                return XMetricSnapshot(
                    external_post_id=returned_id,
                    author_id=author_id,
                    published_at=published_at.astimezone(UTC),
                    observed_at=datetime.now(UTC),
                    metrics=metrics,
                    request_count=requests,
                )
            except (KeyError, TypeError, ValueError, AttributeError):
                raise XMetricSnapshotUnavailable(
                    "invalid_provider_response", ambiguous=True, request_count=requests
                ) from None
        raise XMetricSnapshotUnavailable(
            "provider_unavailable", ambiguous=True, request_count=requests
        )

    def close(self) -> None:
        if self._owns_client:
            self._http.close()


@dataclass(frozen=True)
class XMetricSnapshotSettings:
    enabled: bool
    account_entitlement_verified: bool
    data_rights_verified: bool
    allowed_user_id: str | None
    estimated_cost: Decimal | None
    limits: XUsageLimits | None
    per_post_limit: Decimal | None
    pricing_observed_at: datetime | None = None
    pricing_expires_at: datetime | None = None
    pricing_source: str | None = None

    def valid(self, now: datetime) -> bool:
        return bool(
            self.enabled
            and self.account_entitlement_verified
            and self.data_rights_verified
            and _USER_ID.fullmatch(self.allowed_user_id or "")
            and _valid_money(self.estimated_cost)
            and _valid_money(self.per_post_limit)
            and self.limits is not None
            and self.limits.valid()
            and self.pricing_observed_at is not None
            and self.pricing_expires_at is not None
            and self.pricing_observed_at <= now < self.pricing_expires_at
            and _PRICE_SOURCE.fullmatch(self.pricing_source or "") is not None
        )

    @classmethod
    def from_environment(cls) -> XMetricSnapshotSettings:
        def flag(name: str) -> bool:
            return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}

        def money(name: str) -> Decimal | None:
            try:
                value = Decimal(os.environ[name])
            except (KeyError, InvalidOperation):
                return None
            return value if value.is_finite() and value > 0 else None

        def instant(name: str) -> datetime | None:
            try:
                value = datetime.fromisoformat(os.environ[name].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                return None
            return value if value.tzinfo is not None else None

        daily = money("BIPME_X_DAILY_COST_LIMIT_USD") or money(
            "BIPME_X_PUBLICATION_DAILY_COST_LIMIT_USD"
        )
        return cls(
            enabled=flag("BIPME_X_METRIC_SNAPSHOT_ENABLED"),
            account_entitlement_verified=flag("BIPME_X_ACCOUNT_ENTITLEMENT_VERIFIED"),
            data_rights_verified=flag("BIPME_X_METRIC_SNAPSHOT_DATA_RIGHTS_VERIFIED")
            or flag("BIPME_X_HISTORY_DATA_RIGHTS_VERIFIED"),
            allowed_user_id=os.getenv("BIPME_X_ALLOWED_USER_ID"),
            estimated_cost=money("BIPME_X_METRIC_SNAPSHOT_REQUEST_COST_USD"),
            limits=XUsageLimits(
                money("BIPME_X_METRIC_SNAPSHOT_TOTAL_LIMIT_USD"),
                daily or Decimal("0"),
                money("BIPME_X_METRIC_SNAPSHOT_OPERATION_LIMIT_USD"),
                None,
            ),
            per_post_limit=money("BIPME_X_METRIC_SNAPSHOT_PER_POST_LIMIT_USD"),
            pricing_observed_at=instant("BIPME_X_METRIC_SNAPSHOT_PRICING_OBSERVED_AT"),
            pricing_expires_at=instant("BIPME_X_METRIC_SNAPSHOT_PRICING_EXPIRES_AT"),
            pricing_source=os.getenv("BIPME_X_METRIC_SNAPSHOT_PRICING_SOURCE"),
        )


def _valid_money(value: Decimal | None) -> bool:
    exponent = value.as_tuple().exponent if isinstance(value, Decimal) else None
    return bool(
        isinstance(value, Decimal)
        and value.is_finite()
        and value > 0
        and value < Decimal("1000000000000")
        and isinstance(exponent, int)
        and exponent >= -8
    )


class XMetricSnapshotReader:
    """Reserve, revalidate, read, and cache one post snapshot."""

    def __init__(
        self,
        *,
        provider: XPostMetricsProvider,
        cipher: TokenCipher,
        settings: XMetricSnapshotSettings,
    ) -> None:
        self.provider = provider
        self.cipher = cipher
        self.settings = settings

    def observe(
        self,
        db: Session,
        *,
        creator_id: UUID,
        post: CanonicalPost,
        window_key: str,
        scheduled_at: datetime,
        now: datetime,
    ) -> XMetricSnapshot:
        if (
            post.creator_id != creator_id
            or post.platform != "x"
            or post.availability != "available"
        ):
            raise XMetricSnapshotUnavailable("post_unavailable")
        if not self.settings.valid(now):
            raise XMetricSnapshotUnavailable("external_gate_unverified")
        connection = db.scalar(
            select(XAccountConnection)
            .join(
                CreatorPlatformIdentity,
                (CreatorPlatformIdentity.id == XAccountConnection.creator_identity_id)
                & (CreatorPlatformIdentity.creator_id == XAccountConnection.creator_id),
            )
            .where(
                XAccountConnection.creator_id == creator_id,
                XAccountConnection.platform == "x",
                XAccountConnection.state == "connected",
                CreatorPlatformIdentity.platform == "x",
                CreatorPlatformIdentity.external_creator_id == self.settings.allowed_user_id,
            )
        )
        if connection is None:
            raise XMetricSnapshotUnavailable("connection_unavailable")
        if connection.access_token_expires_at and connection.access_token_expires_at <= now:
            raise XMetricSnapshotUnavailable("reauthorization_required")
        if not {"tweet.read", "users.read"}.issubset(set(connection.scopes)):
            raise XMetricSnapshotUnavailable("permission_denied")
        if connection.encrypted_access_token is None:
            raise XMetricSnapshotUnavailable("reauthorization_required")
        attempts = self.provider.max_request_attempts
        if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 4:
            raise XMetricSnapshotUnavailable("usage_controls_unavailable")
        unit_cost = self.settings.estimated_cost
        limits = self.settings.limits
        per_post_limit = self.settings.per_post_limit
        if unit_cost is None or limits is None or per_post_limit is None:
            raise XMetricSnapshotUnavailable("usage_controls_unavailable")
        key = f"x-post-observation:{creator_id}:{post.external_post_id}:{window_key}"
        try:
            reservation = reserve_x_usage(
                db,
                creator_id=creator_id,
                operation=SNAPSHOT_OPERATION,
                idempotency_key=key,
                estimated_cost=unit_cost * attempts,
                limits=limits,
                now=now,
                post_id=post.external_post_id,
                per_post_limit=per_post_limit,
                request_metadata={
                    "method": "GET",
                    "endpoint": "/2/tweets/{id}",
                    "post_id": post.external_post_id,
                    "window_key": window_key,
                    "scheduled_at": scheduled_at.astimezone(UTC).isoformat(),
                    "pricing_observed_at": self.settings.pricing_observed_at.isoformat(),  # type: ignore[union-attr]
                    "pricing_source_reference": (self.settings.pricing_source or "")[:255],
                    "cost_basis": "bounded_retry_envelope",
                },
            )
        except UsageBudgetError as exc:
            raise XMetricSnapshotUnavailable(exc.code) from None
        if reservation.already_reserved:
            ledger = db.get(APIUsageLedger, reservation.ledger_id)
            cached = (ledger.request_metadata if ledger is not None else {}).get(
                "snapshot_evidence"
            )
            if isinstance(cached, dict):
                try:
                    metrics = {
                        name: XSnapshotMetric(
                            value=(
                                item.get("value") if isinstance(item.get("value"), int) else None
                            ),
                            definition=str(item["definition"]),
                            unit=str(item["unit"]),
                            missing_reason=(
                                str(item["missing_reason"])
                                if item.get("missing_reason") is not None
                                else None
                            ),
                        )
                        for name, item in dict(cached["metrics"]).items()
                    }
                    evidence = XMetricSnapshot(
                        external_post_id=str(cached["external_post_id"]),
                        author_id=str(cached["author_id"]),
                        published_at=datetime.fromisoformat(str(cached["published_at"])),
                        observed_at=datetime.fromisoformat(str(cached["observed_at"])),
                        metrics=metrics,
                        source=str(cached.get("source", "x_authorized_post_metrics")),
                        source_endpoint=str(cached.get("source_endpoint", "/2/tweets/{id}")),
                        request_count=int(cached.get("request_count", 1)),
                    )
                    if (
                        evidence.external_post_id != post.external_post_id
                        or evidence.author_id != self.settings.allowed_user_id
                        or evidence.published_at != post.published_at
                        or evidence.observed_at.tzinfo is None
                        or evidence.observed_at < post.published_at
                    ):
                        raise ValueError
                    return evidence
                except (KeyError, TypeError, ValueError):
                    raise XMetricSnapshotUnavailable("cached_evidence_invalid") from None
            raise XMetricSnapshotUnavailable("ambiguous_billing", ambiguous=True)

        locked = db.scalar(
            select(XAccountConnection)
            .where(
                XAccountConnection.id == connection.id,
                XAccountConnection.creator_id == creator_id,
                XAccountConnection.platform == "x",
                XAccountConnection.state == "connected",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        identity = db.get(
            CreatorPlatformIdentity,
            locked.creator_identity_id if locked is not None else connection.creator_identity_id,
            populate_existing=True,
        )
        if (
            locked is None
            or locked.access_token_expires_at is not None
            and locked.access_token_expires_at <= now
            or not {"tweet.read", "users.read"}.issubset(set(locked.scopes))
            or locked.encrypted_access_token is None
            or identity is None
            or identity.creator_id != creator_id
            or identity.external_creator_id != self.settings.allowed_user_id
        ):
            _complete_failure(db, reservation.ledger_id, now)
            raise XMetricSnapshotUnavailable("connection_unavailable")
        try:
            token = self.cipher.decrypt(locked.encrypted_access_token, locked.key_version)
        except (TokenEncryptionError, TypeError):
            _complete_failure(db, reservation.ledger_id, now)
            raise XMetricSnapshotUnavailable("reauthorization_required") from None
        try:
            evidence = self.provider.post_metrics(access_token=token, post_id=post.external_post_id)
        except XMetricSnapshotUnavailable as exc:
            try:
                complete_x_request(
                    db,
                    reservation_id=reservation.ledger_id,
                    usage_units=0,
                    request_count=exc.request_count,
                    completed_at=max(now, datetime.now(UTC)),
                    response_received=False,
                )
            except UsageBudgetError:
                pass
            raise
        except Exception:
            _complete_failure(db, reservation.ledger_id, now)
            raise XMetricSnapshotUnavailable("provider_unavailable", ambiguous=True) from None
        if (
            evidence.external_post_id != post.external_post_id
            or evidence.author_id != self.settings.allowed_user_id
            or evidence.published_at != post.published_at
            or evidence.observed_at.tzinfo is None
            or evidence.observed_at < post.published_at
        ):
            _complete_failure(db, reservation.ledger_id, max(now, evidence.observed_at))
            raise XMetricSnapshotUnavailable("invalid_provider_response", ambiguous=True)
        ledger = db.get(APIUsageLedger, reservation.ledger_id)
        if ledger is None:
            raise XMetricSnapshotUnavailable("usage_controls_unavailable")
        ledger.request_metadata = {
            **ledger.request_metadata,
            "snapshot_evidence": {
                "external_post_id": evidence.external_post_id,
                "author_id": evidence.author_id,
                "published_at": evidence.published_at.isoformat(),
                "observed_at": evidence.observed_at.astimezone(UTC).isoformat(),
                "source": evidence.source,
                "source_endpoint": evidence.source_endpoint,
                "request_count": evidence.request_count,
                "metrics": {
                    name: {
                        "value": metric.value,
                        "definition": metric.definition,
                        "unit": metric.unit,
                        "missing_reason": metric.missing_reason,
                    }
                    for name, metric in evidence.metrics.items()
                },
            },
        }
        try:
            complete_x_request(
                db,
                reservation_id=reservation.ledger_id,
                usage_units=1,
                request_count=evidence.request_count,
                completed_at=evidence.observed_at.astimezone(UTC),
                response_received=True,
            )
        except UsageBudgetError as exc:
            raise XMetricSnapshotUnavailable(exc.code) from None
        return evidence


def _complete_failure(db: Session, reservation_id: UUID, now: datetime) -> None:
    try:
        complete_x_request(
            db,
            reservation_id=reservation_id,
            usage_units=0,
            request_count=0,
            completed_at=now.astimezone(UTC),
            response_received=False,
        )
    except UsageBudgetError:
        db.rollback()
