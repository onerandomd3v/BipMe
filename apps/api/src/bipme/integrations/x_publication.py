"""Gated, read-only verification of one creator-owned X publication."""

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
from bipme.persistence.models import CreatorPlatformIdentity, XAccountConnection
from bipme.persistence.usage import (
    UsageBudgetError,
    XUsageLimits,
    complete_x_request,
    reserve_x_usage,
)

X_API_ORIGIN = "https://api.x.com"
_POST_ID = re.compile(r"^[0-9]{1,32}$")
_USER_ID = re.compile(r"^[0-9]{1,32}$")


class XPublicationUnavailable(Exception):
    """Safe, stable failure from the publication verification boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PublishedPostEvidence:
    """Provider evidence used to attach one publication without trusting the caller."""

    external_post_id: str
    author_id: str
    text: str | None
    published_at: datetime
    topology: str = "original"
    media_present: bool | None = None
    reply_to_external_post_id: str | None = None
    quoted_external_post_id: str | None = None


class XPublishedPostProvider(Protocol):
    @property
    def max_request_attempts(self) -> int: ...

    def published_post(self, *, access_token: str, post_id: str) -> PublishedPostEvidence: ...


class HttpXPublishedPostProvider:
    """Official read-only single-post adapter; it has no write or publish operation."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        max_retries: int = 2,
        http_client: httpx.Client | None = None,
        sleeper: Any = time.sleep,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("invalid publication timeout")
        if (
            not isinstance(max_retries, int)
            or isinstance(max_retries, bool)
            or not 0 <= max_retries <= 3
        ):
            raise ValueError("invalid publication retry count")
        self._max_retries = max_retries
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)
        self._sleep = sleeper

    @property
    def max_request_attempts(self) -> int:
        return self._max_retries + 1

    def published_post(self, *, access_token: str, post_id: str) -> PublishedPostEvidence:
        if not _POST_ID.fullmatch(post_id) or not access_token:
            raise XPublicationUnavailable("request_invalid")
        path = f"/2/tweets/{quote(post_id, safe='')}"
        params = {"tweet.fields": "author_id,created_at,referenced_tweets,attachments"}
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.get(
                    f"{X_API_ORIGIN}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                    follow_redirects=False,
                )
            except httpx.TimeoutException:
                if attempt >= self._max_retries:
                    raise XPublicationUnavailable("timeout") from None
                self._sleep(min(2.0, 0.25 * float(2**attempt)))
                continue
            except httpx.HTTPError:
                if attempt >= self._max_retries:
                    raise XPublicationUnavailable("provider_unavailable") from None
                self._sleep(min(2.0, 0.25 * float(2**attempt)))
                continue

            if response.status_code == 401:
                raise XPublicationUnavailable("reauthorization_required")
            if response.status_code == 403:
                raise XPublicationUnavailable("permission_denied")
            if response.status_code == 404:
                raise XPublicationUnavailable("post_not_found")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self._max_retries:
                    raise XPublicationUnavailable(
                        "rate_limited" if response.status_code == 429 else "provider_unavailable"
                    )
                self._sleep(min(2.0, 0.25 * float(2**attempt)))
                continue
            if response.status_code < 200 or response.status_code >= 300:
                raise XPublicationUnavailable("provider_rejected_request")

            try:
                payload = response.json()
                data = payload["data"]
                if not isinstance(data, dict):
                    raise ValueError
                returned_id = data["id"]
                author_id = data["author_id"]
                text = data.get("text")
                created_at = data["created_at"]
                if (
                    not isinstance(returned_id, str)
                    or not _POST_ID.fullmatch(returned_id)
                    or returned_id != post_id
                    or not isinstance(author_id, str)
                    or not _USER_ID.fullmatch(author_id)
                    or (text is not None and not isinstance(text, str))
                    or not isinstance(created_at, str)
                ):
                    raise ValueError
                published_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if published_at.tzinfo is None or published_at.utcoffset() is None:
                    raise ValueError
                topology, reply_to_external_post_id, quoted_external_post_id = _references(
                    data.get("referenced_tweets")
                )
                media_present = _media_presence(data.get("attachments"))
                return PublishedPostEvidence(
                    external_post_id=returned_id,
                    author_id=author_id,
                    text=text,
                    published_at=published_at.astimezone(UTC),
                    topology=topology,
                    media_present=media_present,
                    reply_to_external_post_id=reply_to_external_post_id,
                    quoted_external_post_id=quoted_external_post_id,
                )
            except (KeyError, TypeError, ValueError, AttributeError):
                raise XPublicationUnavailable("invalid_provider_response") from None
        raise XPublicationUnavailable("provider_unavailable")

    def close(self) -> None:
        if self._owns_client:
            self._http.close()


def _references(value: object) -> tuple[str, str | None, str | None]:
    if value is None:
        return "original", None, None
    if not isinstance(value, list):
        raise ValueError("referenced_tweets must be a list")
    reply_to: str | None = None
    quoted: str | None = None
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("referenced_tweets entries must be objects")
        reference_type = item.get("type")
        reference_id = item.get("id")
        if not isinstance(reference_id, str) or not _POST_ID.fullmatch(reference_id):
            raise ValueError("referenced_tweets ids must be numeric")
        if reference_type == "replied_to":
            reply_to = reference_id
        elif reference_type == "quoted":
            quoted = reference_id
    if reply_to is not None:
        return "reply", reply_to, quoted
    if quoted is not None:
        return "quote", None, quoted
    return "original", None, None


def _media_presence(value: object) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("attachments must be an object")
    keys = value.get("media_keys")
    if not isinstance(keys, list) or any(not isinstance(item, str) for item in keys):
        raise ValueError("media_keys must be a string list")
    return bool(keys)


@dataclass(frozen=True)
class XPublicationSettings:
    enabled: bool
    account_entitlement_verified: bool
    data_rights_verified: bool
    allowed_user_id: str | None
    estimated_cost: Decimal | None
    limits: XUsageLimits | None

    @classmethod
    def from_environment(cls) -> XPublicationSettings:
        def flag(name: str) -> bool:
            return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}

        def money(name: str) -> Decimal | None:
            raw = os.getenv(name)
            if not raw:
                return None
            try:
                value = Decimal(raw)
            except InvalidOperation:
                return None
            return value if value.is_finite() and value > 0 else None

        daily = money("BIPME_X_PUBLICATION_DAILY_COST_LIMIT_USD")
        limits = XUsageLimits(
            money("BIPME_X_PUBLICATION_TOTAL_COST_LIMIT_USD"),
            daily or Decimal("0"),
            money("BIPME_X_PUBLICATION_OPERATION_COST_LIMIT_USD"),
            money("BIPME_X_PUBLICATION_IMPORT_COST_LIMIT_USD"),
        )
        return cls(
            enabled=flag("BIPME_X_PUBLICATION_LINK_ENABLED"),
            account_entitlement_verified=flag("BIPME_X_PUBLICATION_ACCOUNT_ENTITLEMENT_VERIFIED"),
            data_rights_verified=flag("BIPME_X_PUBLICATION_DATA_RIGHTS_VERIFIED"),
            allowed_user_id=os.getenv("BIPME_X_ALLOWED_USER_ID"),
            estimated_cost=money("BIPME_X_PUBLICATION_READ_ESTIMATED_COST_USD"),
            limits=limits if daily is not None else None,
        )


class XPublishedPostVerifier:
    """Budgeted, creator-owned verification with a final locked connection check."""

    def __init__(
        self,
        *,
        provider: XPublishedPostProvider,
        cipher: TokenCipher,
        settings: XPublicationSettings,
    ) -> None:
        self._provider = provider
        self._cipher = cipher
        self._settings = settings

    @property
    def authorized_user_id(self) -> str | None:
        """The immutable server-side X account allowlist used by this verifier."""
        return self._settings.allowed_user_id

    def close(self) -> None:
        close = getattr(self._provider, "close", None)
        if callable(close):
            close()

    def verify(
        self, db: Session, *, creator_id: UUID, post_id: str, now: datetime
    ) -> PublishedPostEvidence:
        settings = self._settings
        if (
            not settings.enabled
            or not settings.account_entitlement_verified
            or not settings.data_rights_verified
            or not _USER_ID.fullmatch(settings.allowed_user_id or "")
            or settings.estimated_cost is None
            or settings.limits is None
            or not settings.limits.valid()
        ):
            raise XPublicationUnavailable("external_gate_unverified")
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
                CreatorPlatformIdentity.external_creator_id == settings.allowed_user_id,
            )
        )
        if connection is None:
            raise XPublicationUnavailable("connection_unavailable")
        if connection.access_token_expires_at and connection.access_token_expires_at <= now:
            raise XPublicationUnavailable("reauthorization_required")
        if not {"tweet.read", "users.read"}.issubset(set(connection.scopes)):
            raise XPublicationUnavailable("permission_denied")
        if connection.encrypted_access_token is None:
            raise XPublicationUnavailable("reauthorization_required")

        attempts = self._provider.max_request_attempts
        if not isinstance(attempts, int) or isinstance(attempts, bool) or not 1 <= attempts <= 4:
            raise XPublicationUnavailable("usage_controls_unavailable")
        try:
            reservation = reserve_x_usage(
                db,
                creator_id=creator_id,
                operation="published_post_link_read",
                idempotency_key=f"x-publication-link:{creator_id}:{post_id}",
                estimated_cost=settings.estimated_cost * attempts,
                limits=settings.limits,
                now=now,
                request_metadata={
                    "method": "GET",
                    "endpoint": "/2/tweets/{id}",
                    "post_id": post_id,
                    "cost_basis": "bounded_retry_envelope",
                },
            )
        except UsageBudgetError as exc:
            raise XPublicationUnavailable(exc.code) from None
        if reservation.already_reserved:
            raise XPublicationUnavailable("duplicate_request")

        locked = db.scalar(
            select(XAccountConnection)
            .where(
                XAccountConnection.id == connection.id,
                XAccountConnection.creator_id == creator_id,
                XAccountConnection.platform == "x",
                XAccountConnection.state == "connected",
            )
            .with_for_update()
        )
        if (
            locked is None
            or locked.access_token_expires_at is not None
            and locked.access_token_expires_at <= now
            or not {"tweet.read", "users.read"}.issubset(set(locked.scopes))
            or locked.encrypted_access_token is None
        ):
            _complete_failure(db, reservation.ledger_id, now)
            raise XPublicationUnavailable("connection_unavailable")
        try:
            access_token = self._cipher.decrypt(locked.encrypted_access_token, locked.key_version)
            evidence = self._provider.published_post(access_token=access_token, post_id=post_id)
        except (TokenEncryptionError, TypeError):
            _complete_failure(db, reservation.ledger_id, now)
            raise XPublicationUnavailable("reauthorization_required") from None
        except XPublicationUnavailable:
            _complete_failure(db, reservation.ledger_id, now)
            raise
        except Exception:
            _complete_failure(db, reservation.ledger_id, now)
            raise XPublicationUnavailable("provider_unavailable") from None
        try:
            complete_x_request(
                db,
                reservation_id=reservation.ledger_id,
                usage_units=1,
                request_count=attempts,
                completed_at=now,
                response_received=True,
            )
        except UsageBudgetError as exc:
            raise XPublicationUnavailable(exc.code) from None
        return evidence


def _complete_failure(db: Session, reservation_id: UUID, now: datetime) -> None:
    try:
        complete_x_request(
            db,
            reservation_id=reservation_id,
            usage_units=0,
            request_count=0,
            completed_at=now,
            response_received=False,
        )
    except UsageBudgetError:
        db.rollback()


def build_x_publication_verifier(cipher: TokenCipher) -> XPublishedPostVerifier:
    settings = XPublicationSettings.from_environment()
    return XPublishedPostVerifier(
        provider=HttpXPublishedPostProvider(),
        cipher=cipher,
        settings=settings,
    )
