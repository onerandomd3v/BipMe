"""Synthetic tests for the official, budget-guarded X read boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import CheckConstraint, create_engine, event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import bipme.integrations.x_read as x_read_module
from bipme.auth.crypto import TokenCipher
from bipme.integrations.x_read import (
    HttpXReadProvider,
    XCreatorHistoryReader,
    XPage,
    XReadPricing,
    XReadSettings,
    XReadUnavailable,
)
from bipme.persistence.base import Base
from bipme.persistence.models import (
    APIUsageLedger,
    Creator,
    CreatorPlatformIdentity,
    XAccountConnection,
)
from bipme.persistence.usage import XUsageLimits, reconcile_x_usage

CREATOR_ID = UUID("11111111-1111-4111-8111-111111111111")
NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)
FERNET_KEY = Fernet.generate_key().decode("ascii")


class FakeReadProvider:
    def __init__(self, pages: list[XPage | Exception], *, max_request_attempts: int = 3) -> None:
        self.pages = pages
        self.max_request_attempts = max_request_attempts
        self.calls: list[tuple[str, str, int, str | None]] = []

    def creator_posts_page(self, *, access_token, user_id, max_results, pagination_token):
        self.calls.append((access_token, user_id, max_results, pagination_token))
        result = self.pages[len(self.calls) - 1]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def runtime():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def register_postgres_check_functions(dbapi_connection, _record):
        dbapi_connection.create_function(
            "decode", 2, lambda value, encoding: bytes.fromhex(value) if encoding == "hex" else b""
        )
        dbapi_connection.create_function(
            "substring", 3, lambda value, start, length: value[start - 1 : start - 1 + length]
        )
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    tables = [
        APIUsageLedger.__table__,
        Creator.__table__,
        CreatorPlatformIdentity.__table__,
        XAccountConnection.__table__,
    ]
    pg_constraints = []
    for table in tables:
        for constraint in list(table.constraints):
            if isinstance(constraint, CheckConstraint) and "substring(" in str(constraint.sqltext):
                pg_constraints.append((table, constraint))
                table.constraints.remove(constraint)
    try:
        Base.metadata.create_all(engine, tables=tables)
    finally:
        for table, constraint in pg_constraints:
            table.constraints.add(constraint)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    cipher = TokenCipher({"v1": FERNET_KEY}, "v1")
    with factory() as db:
        db.add(Creator(id=CREATOR_ID))
        identity = CreatorPlatformIdentity(
            id=uuid4(), creator_id=CREATOR_ID, platform="x", external_creator_id="987654321"
        )
        encrypted = cipher.encrypt("synthetic-access-token")
        db.add(identity)
        db.add(
            XAccountConnection(
                id=uuid4(),
                creator_id=CREATOR_ID,
                creator_identity_id=identity.id,
                platform="x",
                state="connected",
                scopes=["tweet.read", "users.read"],
                encrypted_access_token=encrypted.envelope,
                key_version=encrypted.key_version,
                access_token_expires_at=NOW + timedelta(hours=1),
            )
        )
        db.commit()
    yield factory, cipher
    engine.dispose()


def _post(post_id: str, *, metrics: dict | None = None) -> dict:
    return {
        "id": post_id,
        "text": f"synthetic post {post_id}",
        "created_at": "2026-11-01T10:00:00Z",
        **({"public_metrics": metrics} if metrics is not None else {}),
    }


def _page(rows: list[dict], token: str | None = None) -> XPage:
    return XPage(tuple(rows), token, NOW)


def _reader(provider, cipher, *, enabled=True, pricing=None, limits=None, settings=None):
    return XCreatorHistoryReader(
        provider=provider,
        cipher=cipher,
        settings=settings
        or XReadSettings(
            enabled=enabled,
            allowed_user_id="987654321",
            account_entitlement_verified=enabled,
            data_rights_verified=enabled,
            max_results=10,
            max_pages=3,
        ),
        pricing=pricing
        or XReadPricing(
            Decimal("0.001"),
            Decimal("0.002"),
            NOW - timedelta(hours=1),
            NOW + timedelta(hours=1),
            "operator-verified:test",
        ),
        limits=limits or XUsageLimits(*(Decimal("1.00") for _ in range(4))),
    )


def test_owner_history_paginates_normalizes_metrics_and_records_each_reservation(runtime):
    factory, cipher = runtime
    provider = FakeReadProvider(
        [
            _page([_post("p1", metrics={"like_count": 3, "reply_count": 1})], "next-1"),
            _page([_post("p2", metrics={"retweet_count": 2})]),
        ]
    )
    with factory() as db:
        result = _reader(provider, cipher).read(
            db, creator_id=CREATOR_ID, import_id="job-1", max_posts=10, now=NOW
        )
        rows = db.scalars(select(APIUsageLedger).order_by(APIUsageLedger.idempotency_key)).all()
        reconcile_x_usage(
            db,
            reservation_id=rows[0].id,
            actual_cost=Decimal("0.020"),
            usage_units=1,
            completed_at=NOW + timedelta(minutes=2),
        )
        reconciled = db.get(APIUsageLedger, rows[0].id)
    assert result.status == "complete"
    assert result.result_count == 2
    assert [call[3] for call in provider.calls] == [None, "next-1"]
    assert provider.calls[0][:2] == ("synthetic-access-token", "987654321")
    assert result.posts[0].source == "x_creator_authorized_history"
    assert result.posts[0].observed_at == NOW
    assert result.posts[0].metrics["like_count"].value == 3
    assert result.posts[0].metrics["impression_count"].missing_reason == "not_returned"
    assert result.posts[1].metrics["repost_count"].value == 2
    assert len(rows) == 2
    assert [row.estimated_cost for row in rows] == [
        Decimal("0.06300000"),
        Decimal("0.05700000"),
    ]
    assert reconciled is not None
    assert reconciled.estimated_cost == Decimal("0.06300000")
    assert reconciled.actual_cost == Decimal("0.02000000")
    assert reconciled.reconciliation_state == "reconciled"
    assert all("synthetic post" not in str(row.request_metadata) for row in rows)


def test_reservation_uses_provider_retry_bound_not_reader_defaults(runtime):
    factory, cipher = runtime
    provider = FakeReadProvider([_page([_post("p1")])], max_request_attempts=4)
    settings = XReadSettings(
        enabled=True,
        allowed_user_id="987654321",
        account_entitlement_verified=True,
        data_rights_verified=True,
        max_retries=0,
        max_results=10,
        max_pages=3,
    )
    with factory() as db:
        result = _reader(provider, cipher, settings=settings).read(
            db, creator_id=CREATOR_ID, import_id="retry-bound", max_posts=10, now=NOW
        )
        row = db.scalar(select(APIUsageLedger))
    assert result.status == "complete"
    assert row is not None
    assert row.estimated_cost == Decimal("0.08400000")


def test_locked_connection_reload_uses_rotated_credentials(runtime, monkeypatch):
    factory, cipher = runtime
    provider = FakeReadProvider([_page([_post("p1")])])
    reserve = x_read_module.reserve_x_usage

    def reserve_then_rotate(db, **kwargs):
        result = reserve(db, **kwargs)
        with factory() as other:
            connection = other.scalar(select(XAccountConnection))
            assert connection is not None
            encrypted = cipher.encrypt("rotated-access-token")
            connection.encrypted_access_token = encrypted.envelope
            connection.key_version = encrypted.key_version
            other.commit()
        return result

    monkeypatch.setattr(x_read_module, "reserve_x_usage", reserve_then_rotate)
    with factory() as db:
        result = _reader(provider, cipher).read(
            db, creator_id=CREATOR_ID, import_id="refresh-race", max_posts=10, now=NOW
        )
    assert result.status == "complete"
    assert provider.calls[0][0] == "rotated-access-token"


def test_later_connection_query_failure_preserves_completed_pages(runtime, monkeypatch):
    factory, cipher = runtime
    provider = FakeReadProvider([_page([_post("p1")], "next"), _page([_post("unused")])])
    with factory() as db:
        original_scalar = db.scalar
        connection_lookups = 0

        def fail_second_connection_lookup(statement, *args, **kwargs):
            nonlocal connection_lookups
            descriptions = getattr(statement, "column_descriptions", [])
            if descriptions and descriptions[0].get("entity") is XAccountConnection:
                connection_lookups += 1
                if connection_lookups == 3:
                    raise SQLAlchemyError("synthetic database outage")
            return original_scalar(statement, *args, **kwargs)

        monkeypatch.setattr(db, "scalar", fail_second_connection_lookup)
        result = _reader(provider, cipher).read(
            db, creator_id=CREATOR_ID, import_id="db-outage", max_posts=10, now=NOW
        )
    assert result.status == "partial"
    assert result.result_count == 1
    assert result.posts[0].external_post_id == "p1"
    assert result.unavailable_reason == "usage_controls_unavailable"
    assert len(provider.calls) == 1


def test_cost_exhaustion_and_stale_or_unknown_pricing_fail_before_provider(runtime):
    factory, cipher = runtime
    provider = FakeReadProvider([_page([_post("unused")])])
    with factory() as db:
        exhausted = _reader(
            provider,
            cipher,
            limits=XUsageLimits(*(Decimal("0.01") for _ in range(4))),
        ).read(db, creator_id=CREATOR_ID, import_id="job-cost", max_posts=10, now=NOW)
    assert exhausted.status == "unavailable"
    assert exhausted.unavailable_reason == "budget_exhausted"
    assert provider.calls == []

    expired = XReadPricing(
        Decimal("0.001"),
        Decimal("0.002"),
        NOW - timedelta(days=2),
        NOW - timedelta(days=1),
        "stale",
    )
    with factory() as db:
        stale = _reader(provider, cipher, pricing=expired).read(
            db, creator_id=CREATOR_ID, import_id="job-price", max_posts=10, now=NOW
        )
    assert stale.unavailable_reason == "pricing_unavailable"
    assert provider.calls == []


def test_external_rights_and_entitlement_gates_fail_closed(runtime):
    factory, cipher = runtime
    provider = FakeReadProvider([_page([_post("unused")])])
    settings = XReadSettings(
        enabled=True,
        allowed_user_id="987654321",
        max_results=10,
        max_pages=3,
    )
    with factory() as db:
        result = _reader(provider, cipher, settings=settings).read(
            db, creator_id=CREATOR_ID, import_id="external-gate", max_posts=10, now=NOW
        )
    assert result.unavailable_reason == "external_gate_unverified"
    assert provider.calls == []


def test_unknown_pricing_fails_closed_before_provider(runtime):
    factory, cipher = runtime
    provider = FakeReadProvider([_page([_post("unused")])])
    reader = XCreatorHistoryReader(
        provider=provider,
        cipher=cipher,
        settings=XReadSettings(
            enabled=True,
            allowed_user_id="987654321",
            account_entitlement_verified=True,
            data_rights_verified=True,
            max_results=10,
            max_pages=3,
        ),
        pricing=None,
        limits=XUsageLimits(*(Decimal("1.00") for _ in range(4))),
    )
    with factory() as db:
        result = reader.read(
            db, creator_id=CREATOR_ID, import_id="unknown-price", max_posts=10, now=NOW
        )
    assert result.unavailable_reason == "usage_controls_unavailable"
    assert provider.calls == []


def test_unpriced_existing_ledger_row_blocks_new_billable_requests(runtime):
    factory, cipher = runtime
    provider = FakeReadProvider([_page([_post("unused")])])
    with factory() as db:
        db.add(
            APIUsageLedger(
                creator_id=CREATOR_ID,
                provider="x",
                operation="unknown_prior_read",
                idempotency_key="unknown-prior-usage",
                request_metadata={},
                requested_at=NOW,
                reconciliation_state="pending",
            )
        )
        db.commit()
        result = _reader(provider, cipher).read(
            db, creator_id=CREATOR_ID, import_id="unknown-ledger", max_posts=10, now=NOW
        )
    assert result.unavailable_reason == "usage_controls_unavailable"
    assert provider.calls == []


def test_duplicate_job_does_not_call_provider_twice_and_partial_failure_is_explicit(runtime):
    factory, cipher = runtime
    provider = FakeReadProvider([_page([_post("p1")], "next"), XReadUnavailable("rate_limited")])
    reader = _reader(provider, cipher)
    with factory() as db:
        partial = reader.read(db, creator_id=CREATOR_ID, import_id="job-dup", max_posts=10, now=NOW)
    assert partial.status == "partial"
    assert partial.unavailable_reason == "rate_limited"
    assert partial.result_count == 1
    with factory() as db:
        duplicate = reader.read(
            db, creator_id=CREATOR_ID, import_id="job-dup", max_posts=10, now=NOW
        )
    assert duplicate.status == "unavailable"
    assert duplicate.unavailable_reason == "duplicate_job"
    assert len(provider.calls) == 2


def test_401_clears_local_credentials_and_requires_reauthorization(runtime):
    factory, cipher = runtime
    provider = FakeReadProvider([XReadUnavailable("reauthorization_required")])
    with factory() as db:
        result = _reader(provider, cipher).read(
            db, creator_id=CREATOR_ID, import_id="job-401", max_posts=10, now=NOW
        )
        connection = db.scalar(select(XAccountConnection))
        assert connection is not None
        assert connection.state == "reauth_required"
        assert connection.encrypted_access_token is None
        assert connection.encrypted_refresh_token is None
    assert result.unavailable_reason == "reauthorization_required"


def test_revoked_connection_and_disabled_or_niche_source_are_safe(runtime):
    factory, cipher = runtime
    provider = FakeReadProvider([_page([_post("unused")])])
    with factory() as db:
        disabled = _reader(provider, cipher, enabled=False).read(
            db, creator_id=CREATOR_ID, import_id="disabled", max_posts=10, now=NOW
        )
        connection = db.scalar(select(XAccountConnection))
        assert connection is not None
        connection.state = "revoked"
        connection.encrypted_access_token = None
        connection.encrypted_refresh_token = None
        connection.revoked_at = NOW
        db.commit()
        revoked = _reader(provider, cipher).read(
            db, creator_id=CREATOR_ID, import_id="revoked", max_posts=10, now=NOW
        )
        niche = _reader(provider, cipher).discover_niche()
    assert disabled.unavailable_reason == "disabled"
    assert revoked.unavailable_reason == "connection_unavailable"
    assert niche.unavailable_reason == "niche_search_not_verified"
    assert provider.calls == []


def test_http_provider_is_get_only_allowlisted_and_retries_429_with_bound():
    requests = []
    responses = [
        httpx.Response(429, headers={"Retry-After": "99"}),
        httpx.Response(200, json={"data": [], "meta": {}}),
    ]

    def handler(request):
        requests.append(request)
        return responses.pop(0)

    sleeps = []
    client = httpx.Client(base_url="https://api.x.com", transport=httpx.MockTransport(handler))
    provider = HttpXReadProvider(
        settings=XReadSettings(enabled=True, max_results=10, retry_max_seconds=1),
        http_client=client,
        sleeper=sleeps.append,
    )
    page = provider.creator_posts_page(
        access_token="synthetic-access-token",
        user_id="987654321",
        max_results=10,
        pagination_token=None,
    )
    assert page.posts == ()
    assert len(requests) == 2
    assert all(request.method == "GET" for request in requests)
    assert all(request.url.host == "api.x.com" for request in requests)
    assert requests[0].url.path == "/2/users/987654321/tweets"
    assert requests[0].url.params.get("max_results") == "10"
    assert sleeps == [1]
    with pytest.raises(XReadUnavailable, match="request_invalid"):
        provider.creator_posts_page(
            access_token="token", user_id="../me", max_results=10, pagination_token=None
        )


@pytest.mark.parametrize(
    ("status", "reason"),
    [(401, "reauthorization_required"), (403, "permission_denied"), (500, "provider_unavailable")],
)
def test_http_provider_maps_auth_and_server_failures_without_exposing_body(status, reason):
    client = httpx.Client(
        base_url="https://api.x.com",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="private payload")
        ),
    )
    provider = HttpXReadProvider(
        settings=XReadSettings(enabled=True, max_results=10, max_retries=0), http_client=client
    )
    with pytest.raises(XReadUnavailable, match=reason) as error:
        provider.creator_posts_page(
            access_token="synthetic-access-token",
            user_id="123",
            max_results=10,
            pagination_token=None,
        )
    assert "private payload" not in str(error.value)


def test_http_provider_bounds_timeout_retry():
    calls = 0
    sleeps = []

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(200, json={"data": [], "meta": {}})

    client = httpx.Client(base_url="https://api.x.com", transport=httpx.MockTransport(handler))
    provider = HttpXReadProvider(
        settings=XReadSettings(
            enabled=True,
            max_results=10,
            max_retries=1,
            retry_base_seconds=0.1,
            retry_max_seconds=0.5,
        ),
        http_client=client,
        sleeper=sleeps.append,
    )
    result = provider.creator_posts_page(
        access_token="synthetic-access-token",
        user_id="123",
        max_results=10,
        pagination_token=None,
    )
    assert result.posts == ()
    assert calls == 2
    assert sleeps == [0.1]
