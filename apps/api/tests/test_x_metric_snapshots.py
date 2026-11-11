"""Synthetic tests for the COD-363 read-only metric snapshot boundary."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from bipme.integrations.x_metric_snapshots import (
    HttpXPostMetricsProvider,
    XMetricSnapshotSettings,
    XMetricSnapshotUnavailable,
)
from bipme.persistence.usage import XUsageLimits


def _settings() -> XMetricSnapshotSettings:
    now = datetime(2026, 11, 10, 12, tzinfo=UTC)
    return XMetricSnapshotSettings(
        enabled=True,
        account_entitlement_verified=True,
        data_rights_verified=True,
        allowed_user_id="987654321",
        estimated_cost=Decimal("0.001"),
        limits=XUsageLimits(Decimal("1"), Decimal("1"), Decimal("1"), None),
        per_post_limit=Decimal("0.01"),
        pricing_observed_at=now,
        pricing_expires_at=datetime(2026, 11, 10, 13, tzinfo=UTC),
        pricing_source="synthetic:test",
    )


def test_settings_require_explicit_external_gates() -> None:
    now = datetime(2026, 11, 10, 12, tzinfo=UTC)
    assert _settings().valid(now)
    disabled = replace(_settings(), enabled=False)
    assert not disabled.valid(now)


def test_http_provider_normalizes_partial_metrics() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "data": {
                    "id": "123456",
                    "author_id": "987654321",
                    "created_at": "2026-11-10T11:00:00Z",
                    "public_metrics": {"like_count": 3, "retweet_count": 2},
                }
            },
            request=request,
        )
    )
    client = httpx.Client(transport=transport)
    provider = HttpXPostMetricsProvider(http_client=client, max_retries=0)
    snapshot = provider.post_metrics(access_token="synthetic-token", post_id="123456")
    assert snapshot.external_post_id == "123456"
    assert snapshot.author_id == "987654321"
    assert snapshot.metrics["like_count"].value == 3
    assert snapshot.metrics["repost_count"].value == 2
    assert snapshot.metrics["reply_count"].missing_reason == "not_returned"
    assert snapshot.observed_at.tzinfo is not None
    client.close()


def test_http_provider_never_retries_without_a_bounded_attempt() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = HttpXPostMetricsProvider(http_client=client, max_retries=1, sleeper=lambda _: None)
    with pytest.raises(XMetricSnapshotUnavailable) as error:
        provider.post_metrics(access_token="synthetic-token", post_id="123456")
    assert error.value.code == "provider_unavailable"
    assert error.value.ambiguous
    assert error.value.request_count == 2
    assert calls == 2
    client.close()
