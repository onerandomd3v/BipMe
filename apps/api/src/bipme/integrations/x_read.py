"""Bounded, read-only X timeline adapter with a shared durable spend reservation."""

from __future__ import annotations

import hashlib
import math
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from bipme.auth.crypto import TokenCipher, TokenEncryptionError
from bipme.persistence.models import CreatorPlatformIdentity, XAccountConnection
from bipme.persistence.usage import (
    UsageBudgetError,
    XUsageLimits,
    complete_x_request,
    reserve_x_usage,
)

X_API_ORIGIN = "https://api.x.com"
X_POST_FIELDS = "id,text,created_at,public_metrics,conversation_id,in_reply_to_user_id,referenced_tweets,attachments"
METRIC_DEFINITIONS = {
    "like_count": "X public_metrics.like_count as returned at observation time",
    "reply_count": "X public_metrics.reply_count as returned at observation time",
    "repost_count": "X public_metrics.retweet_count as returned at observation time",
    "quote_count": "X public_metrics.quote_count as returned at observation time",
    "bookmark_count": "X public_metrics.bookmark_count as returned at observation time",
    "impression_count": "X public_metrics.impression_count as returned at observation time",
}
METRIC_FIELD_MAP = {
    "like_count": "like_count",
    "reply_count": "reply_count",
    "repost_count": "retweet_count",
    "quote_count": "quote_count",
    "bookmark_count": "bookmark_count",
    "impression_count": "impression_count",
}
_USER_ID = re.compile(r"^[0-9]{1,32}$")
_IMPORT_ID = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
_PRICE_SOURCE = re.compile(r"^[A-Za-z0-9._:/-]{1,255}$")


class XReadUnavailable(Exception):
    """Typed safe read failure; code is a stable public reason without provider detail."""

    def __init__(self, code: str, *, request_count: int = 1) -> None:
        super().__init__(code)
        self.code = code
        self.request_count = request_count


@dataclass(frozen=True)
class XReadPricing:
    """Operator-verified conservative price inputs; intentionally has no defaults."""

    request_usd: Decimal
    result_usd: Decimal
    observed_at: datetime
    expires_at: datetime
    source_reference: str

    def estimate(self, requested_results: int, *, now: datetime) -> Decimal:
        if (
            not _valid_money(self.request_usd, allow_zero=True)
            or self.request_usd < 0
            or not _valid_money(self.result_usd, allow_zero=False)
            or self.result_usd <= 0
            or not _PRICE_SOURCE.fullmatch(self.source_reference)
            or self.observed_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or self.observed_at > now
            or self.expires_at <= now
            or not 1 <= requested_results <= 100
        ):
            raise XReadUnavailable("pricing_unavailable")
        return self.request_usd + self.result_usd * requested_results


def _valid_money(value: Decimal, *, allow_zero: bool) -> bool:
    exponent = value.as_tuple().exponent if isinstance(value, Decimal) else None
    return bool(
        isinstance(value, Decimal)
        and value.is_finite()
        and (value >= 0 if allow_zero else value > 0)
        and isinstance(exponent, int)
        and exponent >= -8
        and value < Decimal("1000000000000")
    )


@dataclass(frozen=True)
class XReadSettings:
    enabled: bool = False
    niche_search_enabled: bool = False
    allowed_user_id: str | None = None
    account_entitlement_verified: bool = False
    data_rights_verified: bool = False
    timeout_seconds: float = 8.0
    max_retries: int = 2
    max_concurrent_requests: int = 2
    max_pages: int = 4
    max_results: int = 100
    retry_base_seconds: float = 0.25
    retry_max_seconds: float = 2.0

    def valid(self) -> bool:
        return (
            math.isfinite(self.timeout_seconds)
            and self.timeout_seconds > 0
            and isinstance(self.max_retries, int)
            and not isinstance(self.max_retries, bool)
            and 0 <= self.max_retries <= 3
            and isinstance(self.max_concurrent_requests, int)
            and not isinstance(self.max_concurrent_requests, bool)
            and 1 <= self.max_concurrent_requests <= 8
            and isinstance(self.max_pages, int)
            and not isinstance(self.max_pages, bool)
            and 1 <= self.max_pages <= 32
            and isinstance(self.max_results, int)
            and not isinstance(self.max_results, bool)
            and 5 <= self.max_results <= 100
            and math.isfinite(self.retry_base_seconds)
            and math.isfinite(self.retry_max_seconds)
            and 0 <= self.retry_base_seconds <= self.retry_max_seconds <= 5
        )


@dataclass(frozen=True)
class XMetricValue:
    value: int | None
    definition: str
    missing_reason: str | None = None


@dataclass(frozen=True)
class XReadPost:
    external_post_id: str
    text: str
    published_at: datetime
    observed_at: datetime
    metrics: dict[str, XMetricValue]
    topology: str = "original"
    reply_to_external_post_id: str | None = None
    quoted_external_post_id: str | None = None
    thread_id: str | None = None
    media_present: bool | None = None
    source: str = "x_creator_authorized_history"
    source_endpoint: str = "/2/users/{id}/tweets"


@dataclass(frozen=True)
class XReadResult:
    status: str
    posts: tuple[XReadPost, ...] = ()
    pages_read: int = 0
    result_count: int = 0
    next_page_available: bool = False
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class XPage:
    posts: tuple[dict[str, Any], ...]
    next_token: str | None
    observed_at: datetime
    partial: bool = False
    request_count: int = 1


class XReadProvider(Protocol):
    """Mockable owner timeline provider; deliberately exposes no arbitrary URL method."""

    @property
    def max_request_attempts(self) -> int: ...

    def creator_posts_page(
        self,
        *,
        access_token: str,
        user_id: str,
        max_results: int,
        pagination_token: str | None,
    ) -> XPage: ...


class XNicheSearchProvider(Protocol):
    """Future COD-376 boundary kept separate from creator-owned history reads."""

    def search_public_posts(
        self,
        *,
        query: str,
        max_results: int,
        pagination_token: str | None,
    ) -> XPage: ...


class HttpXReadProvider:
    """HTTPX-backed GET adapter restricted to a single official X endpoint."""

    def __init__(
        self,
        *,
        settings: XReadSettings,
        http_client: httpx.Client | None = None,
        sleeper: Any = time.sleep,
    ) -> None:
        if not settings.valid():
            raise ValueError("invalid X read settings")
        self._settings = settings
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            timeout=httpx.Timeout(settings.timeout_seconds),
            follow_redirects=False,
            base_url=X_API_ORIGIN,
        )
        self._sleep = sleeper
        self._slots = threading.BoundedSemaphore(settings.max_concurrent_requests)

    @property
    def max_request_attempts(self) -> int:
        """Worst-case billable calls the transport may make for one page."""
        return self._settings.max_retries + 1

    def creator_posts_page(
        self,
        *,
        access_token: str,
        user_id: str,
        max_results: int,
        pagination_token: str | None,
    ) -> XPage:
        if (
            not _USER_ID.fullmatch(user_id)
            or not access_token
            or not 5 <= max_results <= self._settings.max_results
            or (
                pagination_token is not None
                and (len(pagination_token) > 512 or not pagination_token.isprintable())
            )
        ):
            raise XReadUnavailable("request_invalid")
        path = f"/2/users/{quote(user_id, safe='')}/tweets"
        params: dict[str, str | int] = {
            "max_results": max_results,
            "tweet.fields": X_POST_FIELDS,
            "exclude": "retweets",
        }
        if pagination_token is not None:
            params["pagination_token"] = pagination_token
        for attempt in range(self._settings.max_retries + 1):
            try:
                acquired = self._slots.acquire(timeout=self._settings.timeout_seconds)
                if not acquired:
                    raise XReadUnavailable("concurrency_limit", request_count=0)
                try:
                    response = self._http.get(
                        f"{X_API_ORIGIN}{path}",
                        params=params,
                        headers={"Authorization": f"Bearer {access_token}"},
                        follow_redirects=False,
                    )
                finally:
                    self._slots.release()
            except XReadUnavailable:
                raise
            except httpx.TimeoutException:
                if attempt >= self._settings.max_retries:
                    raise XReadUnavailable("timeout", request_count=attempt + 1) from None
                self._sleep(self._backoff(attempt, None))
                continue
            except httpx.HTTPError:
                if attempt >= self._settings.max_retries:
                    raise XReadUnavailable(
                        "provider_unavailable", request_count=attempt + 1
                    ) from None
                self._sleep(self._backoff(attempt, None))
                continue

            if response.status_code == 401:
                raise XReadUnavailable("reauthorization_required", request_count=attempt + 1)
            if response.status_code == 403:
                raise XReadUnavailable("permission_denied", request_count=attempt + 1)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self._settings.max_retries:
                    raise XReadUnavailable(
                        "rate_limited" if response.status_code == 429 else "provider_unavailable",
                        request_count=attempt + 1,
                    )
                self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise XReadUnavailable("provider_rejected_request")
            try:
                payload = response.json()
                rows = payload.get("data", [])
                meta = payload.get("meta", {})
                errors = payload.get("errors", [])
                if (
                    not isinstance(rows, list)
                    or not isinstance(meta, dict)
                    or not isinstance(errors, list)
                    or len(rows) > max_results
                ):
                    raise ValueError
                token = meta.get("next_token")
                if token is not None and (
                    not isinstance(token, str) or len(token) > 512 or not token.isprintable()
                ):
                    raise ValueError
                if any(not isinstance(row, dict) for row in rows):
                    raise ValueError
                return XPage(
                    tuple(rows),
                    token,
                    datetime.now(UTC),
                    partial=bool(errors),
                    request_count=attempt + 1,
                )
            except (ValueError, TypeError, AttributeError):
                raise XReadUnavailable(
                    "invalid_provider_response", request_count=attempt + 1
                ) from None
        raise XReadUnavailable("provider_unavailable")

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            try:
                return min(self._settings.retry_max_seconds, max(0.0, float(retry_after)))
            except ValueError:
                pass
        delay: float = self._settings.retry_base_seconds * float(2**attempt)
        return min(self._settings.retry_max_seconds, delay)

    def close(self) -> None:
        if self._owns_client:
            self._http.close()


class XCreatorHistoryReader:
    """Creator-owned history only; it enforces connection ownership before provider use."""

    def __init__(
        self,
        *,
        provider: XReadProvider,
        cipher: TokenCipher,
        settings: XReadSettings,
        pricing: XReadPricing | None,
        limits: XUsageLimits | None,
    ) -> None:
        self._provider = provider
        self._cipher = cipher
        self._settings = settings
        self._pricing = pricing
        self._limits = limits

    def read(
        self,
        db: Session,
        *,
        creator_id: UUID,
        import_id: str,
        max_posts: int,
        now: datetime | None = None,
    ) -> XReadResult:
        try:
            return self._read(
                db,
                creator_id=creator_id,
                import_id=import_id,
                max_posts=max_posts,
                now=now,
            )
        except SQLAlchemyError:
            db.rollback()
            return XReadResult("unavailable", unavailable_reason="usage_controls_unavailable")

    def _read(
        self,
        db: Session,
        *,
        creator_id: UUID,
        import_id: str,
        max_posts: int,
        now: datetime | None = None,
    ) -> XReadResult:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        fixed_request_time = now is not None
        if not self._settings.enabled:
            return XReadResult("unavailable", unavailable_reason="disabled")
        if (
            not self._settings.account_entitlement_verified
            or not self._settings.data_rights_verified
        ):
            return XReadResult("unavailable", unavailable_reason="external_gate_unverified")
        if not _USER_ID.fullmatch(self._settings.allowed_user_id or ""):
            return XReadResult("unavailable", unavailable_reason="account_allowlist_unavailable")
        if (
            not self._settings.valid()
            or self._pricing is None
            or self._limits is None
            or not self._limits.complete()
        ):
            return XReadResult("unavailable", unavailable_reason="usage_controls_unavailable")
        if (
            not _IMPORT_ID.fullmatch(import_id)
            or not 1 <= max_posts <= self._settings.max_pages * self._settings.max_results
        ):
            return XReadResult("unavailable", unavailable_reason="request_invalid")
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
            )
        )
        if connection is None:
            return XReadResult("unavailable", unavailable_reason="connection_unavailable")
        if connection.access_token_expires_at and connection.access_token_expires_at <= instant:
            return XReadResult("unavailable", unavailable_reason="reauthorization_required")
        if not {"tweet.read", "users.read"}.issubset(set(connection.scopes)):
            return XReadResult("unavailable", unavailable_reason="permission_denied")
        identity = db.get(CreatorPlatformIdentity, connection.creator_identity_id)
        if (
            identity is None
            or identity.creator_id != creator_id
            or identity.platform != "x"
            or identity.external_creator_id != self._settings.allowed_user_id
        ):
            return XReadResult("unavailable", unavailable_reason="connection_unavailable")
        if connection.encrypted_access_token is None:
            return XReadResult("unavailable", unavailable_reason="reauthorization_required")
        connection_id = connection.id

        page_size = min(self._settings.max_results, 100)
        max_pages = self._settings.max_pages
        import_hash = hashlib.sha256(import_id.encode("utf-8")).hexdigest()
        collected: list[XReadPost] = []
        pagination_token: str | None = None
        pages_read = 0
        for page_number in range(max_pages):
            request_time = instant if fixed_request_time else datetime.now(UTC)
            requested = min(page_size, max_posts - len(collected))
            if requested < 5:
                # X timeline endpoints require at least five per page. A final response may
                # contain fewer than requested; cap returned data locally below instead.
                requested = 5
            try:
                # Reserve the whole bounded retry envelope before the provider can issue
                # the first request. Retries may each be billable even when the page is not.
                attempts = self._provider.max_request_attempts
                if (
                    not isinstance(attempts, int)
                    or isinstance(attempts, bool)
                    or not 1 <= attempts <= 4
                ):
                    return self._finish(
                        collected, pages_read, pagination_token, "usage_controls_unavailable"
                    )
                estimate = self._pricing.estimate(requested, now=request_time) * Decimal(attempts)
                key = f"x-history:{import_hash}:{page_number}"
                reservation = reserve_x_usage(
                    db,
                    creator_id=creator_id,
                    operation="creator_history_posts_read",
                    idempotency_key=key,
                    estimated_cost=estimate,
                    limits=self._limits,
                    now=request_time,
                    import_id=import_hash,
                    request_metadata={
                        "method": "GET",
                        "endpoint": "/2/users/{id}/tweets",
                        "requested_results": requested,
                        "pricing_observed_at": self._pricing.observed_at.isoformat(),
                        "pricing_source_reference": self._pricing.source_reference[:255],
                        "cost_basis": "bounded_retry_envelope_of_request_plus_max_requested_results",
                        "estimated_cost_kind": "estimate",
                    },
                )
            except XReadUnavailable as exc:
                return self._finish(collected, pages_read, pagination_token, exc.code)
            except UsageBudgetError as exc:
                return self._finish(collected, pages_read, pagination_token, exc.code)
            if reservation.already_reserved:
                return self._finish(collected, pages_read, pagination_token, "duplicate_job")
            try:
                locked_connection = db.scalar(
                    select(XAccountConnection)
                    .execution_options(populate_existing=True)
                    .where(
                        XAccountConnection.id == connection_id,
                        XAccountConnection.creator_id == creator_id,
                        XAccountConnection.platform == "x",
                        XAccountConnection.state == "connected",
                    )
                    .with_for_update()
                )
                locked_identity = (
                    None
                    if locked_connection is None
                    else db.get(CreatorPlatformIdentity, locked_connection.creator_identity_id)
                )
            except SQLAlchemyError:
                db.rollback()
                return self._finish(
                    collected, pages_read, pagination_token, "usage_controls_unavailable"
                )
            if (
                locked_connection is None
                or locked_connection.access_token_expires_at is not None
                and locked_connection.access_token_expires_at <= request_time
                or not {"tweet.read", "users.read"}.issubset(set(locked_connection.scopes))
            ):
                complete_x_request(
                    db,
                    reservation_id=reservation.ledger_id,
                    usage_units=0,
                    request_count=0,
                    completed_at=max(request_time, datetime.now(UTC)),
                    response_received=False,
                )
                return self._finish(
                    collected, pages_read, pagination_token, "connection_unavailable"
                )
            if (
                locked_identity is None
                or locked_identity.creator_id != creator_id
                or locked_identity.platform != "x"
                or locked_identity.external_creator_id != self._settings.allowed_user_id
                or locked_connection.encrypted_access_token is None
            ):
                complete_x_request(
                    db,
                    reservation_id=reservation.ledger_id,
                    usage_units=0,
                    request_count=0,
                    completed_at=max(request_time, datetime.now(UTC)),
                    response_received=False,
                )
                return self._finish(
                    collected, pages_read, pagination_token, "connection_unavailable"
                )
            try:
                access_token = self._cipher.decrypt(
                    locked_connection.encrypted_access_token, locked_connection.key_version
                )
            except (TokenEncryptionError, TypeError):
                complete_x_request(
                    db,
                    reservation_id=reservation.ledger_id,
                    usage_units=0,
                    request_count=0,
                    completed_at=max(request_time, datetime.now(UTC)),
                    response_received=False,
                )
                return self._finish(
                    collected, pages_read, pagination_token, "reauthorization_required"
                )
            try:
                page = self._provider.creator_posts_page(
                    access_token=access_token,
                    user_id=locked_identity.external_creator_id,
                    max_results=requested,
                    pagination_token=pagination_token,
                )
            except XReadUnavailable as exc:
                if exc.code == "reauthorization_required":
                    locked_connection.state = "reauth_required"
                    locked_connection.encrypted_access_token = None
                    locked_connection.encrypted_refresh_token = None
                    locked_connection.access_token_expires_at = None
                try:
                    complete_x_request(
                        db,
                        reservation_id=reservation.ledger_id,
                        usage_units=0,
                        request_count=exc.request_count,
                        completed_at=max(request_time, datetime.now(UTC)),
                        response_received=False,
                    )
                except UsageBudgetError:
                    return self._finish(
                        collected, pages_read, pagination_token, "usage_controls_unavailable"
                    )
                return self._finish(collected, pages_read, pagination_token, exc.code)
            except Exception:
                try:
                    complete_x_request(
                        db,
                        reservation_id=reservation.ledger_id,
                        usage_units=0,
                        request_count=1,
                        completed_at=max(request_time, datetime.now(UTC)),
                        response_received=False,
                    )
                except UsageBudgetError:
                    return self._finish(
                        collected, pages_read, pagination_token, "usage_controls_unavailable"
                    )
                return self._finish(collected, pages_read, pagination_token, "provider_unavailable")
            try:
                complete_x_request(
                    db,
                    reservation_id=reservation.ledger_id,
                    usage_units=len(page.posts),
                    request_count=page.request_count,
                    completed_at=max(request_time, page.observed_at),
                    response_received=True,
                )
            except UsageBudgetError:
                return self._finish(
                    collected, pages_read, pagination_token, "usage_controls_unavailable"
                )
            pages_read += 1
            normalization_error = False
            seen_post_ids = {post.external_post_id for post in collected}
            for row in page.posts:
                if len(collected) >= max_posts:
                    break
                if _is_retweet(row):
                    continue
                try:
                    normalized = _normalize_post(row, page.observed_at)
                except (ValueError, TypeError, KeyError):
                    # Keep good records; malformed individual records make availability partial.
                    normalization_error = True
                    continue
                if normalized.external_post_id not in seen_post_ids:
                    collected.append(normalized)
                    seen_post_ids.add(normalized.external_post_id)
                if len(collected) >= max_posts:
                    break
            pagination_token = page.next_token
            if normalization_error or page.partial:
                return self._finish(
                    collected,
                    pages_read,
                    pagination_token,
                    "invalid_provider_response"
                    if normalization_error
                    else "partial_provider_response",
                )
            if len(collected) >= max_posts or pagination_token is None:
                break
        return self._finish(collected, pages_read, pagination_token, None)

    def discover_niche(self, *_args: object, **_kwargs: object) -> XReadResult:
        """Search stays unavailable until COD-375 verifies rights and account access."""
        if not self._settings.niche_search_enabled:
            return XReadResult("unavailable", unavailable_reason="niche_search_not_verified")
        return XReadResult("unavailable", unavailable_reason="niche_discovery_not_implemented")

    @staticmethod
    def _finish(
        collected: list[XReadPost], pages_read: int, token: str | None, error: str | None
    ) -> XReadResult:
        if collected and error:
            status = "partial"
        elif error:
            status = "unavailable"
        else:
            status = "complete"
        return XReadResult(
            status=status,
            posts=tuple(collected),
            pages_read=pages_read,
            result_count=len(collected),
            next_page_available=token is not None,
            unavailable_reason=error,
        )


def _normalize_post(row: dict[str, Any], observed_at: datetime) -> XReadPost:
    post_id, text, created_at = row.get("id"), row.get("text"), row.get("created_at")
    if not isinstance(post_id, str) or not post_id or not isinstance(text, str):
        raise ValueError
    if not isinstance(created_at, str):
        raise ValueError
    published_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if published_at.tzinfo is None:
        raise ValueError
    raw_metrics = row.get("public_metrics")
    metrics: dict[str, XMetricValue] = {}
    for name, field in METRIC_FIELD_MAP.items():
        value: int | None = None
        missing_reason = None
        if not isinstance(raw_metrics, dict) or field not in raw_metrics:
            missing_reason = "not_returned"
        elif (
            isinstance(raw_metrics[field], bool)
            or not isinstance(raw_metrics[field], int)
            or raw_metrics[field] < 0
        ):
            missing_reason = "invalid_value"
        else:
            value = raw_metrics[field]
        metrics[name] = XMetricValue(value, METRIC_DEFINITIONS[name], missing_reason)
    references = row.get("referenced_tweets")
    if not isinstance(references, list):
        references = []
    quoted_id = None
    reply_to_post_id = None
    topology = "original"
    for reference in references:
        if (
            isinstance(reference, dict)
            and reference.get("type") == "quoted"
            and isinstance(reference.get("id"), str)
        ):
            topology = "quote"
            quoted_id = reference["id"]
        elif (
            isinstance(reference, dict)
            and reference.get("type") == "replied_to"
            and isinstance(reference.get("id"), str)
        ):
            topology = "reply"
            reply_to_post_id = reference["id"]
    attachments = row.get("attachments")
    media_present = None
    if isinstance(attachments, dict) and isinstance(attachments.get("media_keys"), list):
        media_present = bool(attachments["media_keys"])
    thread_id = row.get("conversation_id")
    if not isinstance(thread_id, str):
        thread_id = None
    return XReadPost(
        external_post_id=post_id,
        text=text,
        published_at=published_at.astimezone(UTC),
        observed_at=observed_at.astimezone(UTC),
        metrics=metrics,
        topology=topology,
        reply_to_external_post_id=reply_to_post_id,
        quoted_external_post_id=quoted_id,
        thread_id=thread_id,
        media_present=media_present,
    )


def _is_retweet(row: dict[str, Any]) -> bool:
    """Return whether a provider row is a repost, even if exclude was ignored."""
    references = row.get("referenced_tweets")
    return isinstance(references, list) and any(
        isinstance(reference, dict) and reference.get("type") == "retweeted"
        for reference in references
    )
