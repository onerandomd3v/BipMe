"""Synthetic numerical tests for creator-relative baseline behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bipme.intelligence import baselines
from bipme.intelligence.baselines import (
    BASELINE_VERSION,
    BaselineRequest,
    OutcomeObservation,
    build_creator_baseline,
    effective_sample_size,
    weighted_quantile,
)

AS_OF = datetime(2026, 1, 1, tzinfo=UTC)


def obs(
    post_id: str,
    value: float | None,
    *,
    metric: str = "impressions",
    metric_definition: str | None = None,
    creator: str = "creator-1",
    window: str = "mature",
    published: datetime = AS_OF - timedelta(days=2),
    observed: datetime = AS_OF - timedelta(days=1),
    weight: float = 1.0,
    segment: tuple[str, ...] = (),
) -> OutcomeObservation:
    return OutcomeObservation(
        creator,
        post_id,
        metric,
        metric_definition or f"{metric}_v1",
        value,
        published,
        observed,
        window,
        weight,
        segment,
    )


def request(**kwargs: object) -> BaselineRequest:
    return BaselineRequest("creator-1", "impressions", "impressions_v1", "mature", AS_OF, **kwargs)  # type: ignore[arg-type]


def test_consistent_history_has_robust_quantiles_and_repeatability() -> None:
    result = build_creator_baseline([obs(str(i), float(i * 10)) for i in range(1, 9)], request())
    assert result.version == BASELINE_VERSION
    assert result.eligible_post_count == 8
    assert result.statistics is not None
    assert (result.statistics.p25, result.statistics.p50, result.statistics.p75) == (20, 40, 60)
    assert result.statistics.iqr == 40
    assert result.statistics.outlier_count == 0
    assert result.statistics.consistency_ratio == 1
    assert result.evidence_strength == "Moderate"


def test_extreme_viral_post_is_flagged_without_moving_median() -> None:
    values = [10.0] * 7 + [100_000.0]
    result = build_creator_baseline(
        [obs(str(i), value) for i, value in enumerate(values)], request()
    )
    assert result.statistics is not None
    assert result.statistics.p50 == 10
    assert result.statistics.outlier_count == 1
    assert result.statistics.upper_outlier_count == 1
    assert result.statistics.consistency_ratio == 7 / 8
    assert result.evidence_strength == "Moderate"
    assert any("3×IQR" in reason for reason in result.reasons)


@pytest.mark.parametrize(
    "values, expected", [([5.0], "Insufficient"), ([5.0, 5.0], "Insufficient")]
)
def test_small_samples_abstain(values: list[float], expected: str) -> None:
    result = build_creator_baseline(
        [obs(str(i), value) for i, value in enumerate(values)], request()
    )
    assert result.evidence_strength == expected
    assert result.eligible_post_count == len(values)
    assert result.statistics is not None


def test_empty_and_only_missing_history_abstains_explicitly() -> None:
    empty = build_creator_baseline([], request())
    missing = build_creator_baseline([obs("missing", None)], request())
    assert empty.statistics is None
    assert empty.evidence_strength == "Insufficient"
    assert dict(empty.exclusion_counts) == {}
    assert missing.statistics is None
    assert dict(missing.exclusion_counts) == {"missing_metric_or_window": 1}


def test_zero_is_a_valid_metric_and_other_supported_metrics_are_independent() -> None:
    inputs = [obs("a", 0), obs("b", 0), obs("c", 1), obs("x", 100, metric="replies")]
    result = build_creator_baseline(inputs, request())
    assert result.eligible_post_count == 3
    assert result.statistics is not None
    assert result.statistics.p50 == 0
    assert dict(result.exclusion_counts) == {"incompatible_metric": 1}


def test_mature_totals_and_age_aligned_windows_never_mix() -> None:
    inputs = [obs("mature", 300), obs("hour", 10, window="age:1h")]
    result = build_creator_baseline(inputs, request())
    assert result.eligible_post_count == 1
    assert result.supporting_post_ids == ("mature",)
    assert dict(result.exclusion_counts) == {"incompatible_window": 1}


def test_future_publication_and_future_observations_are_excluded_as_of() -> None:
    inputs = [
        obs("future-publish", 99, published=AS_OF + timedelta(seconds=1)),
        obs("future-observe", 88, observed=AS_OF + timedelta(seconds=1)),
        obs("valid", 7, published=AS_OF - timedelta(hours=2), observed=AS_OF - timedelta(hours=1)),
    ]
    result = build_creator_baseline(inputs, request())
    assert result.supporting_post_ids == ("valid",)
    assert dict(result.exclusion_counts) == {
        "observed_after_as_of": 1,
        "published_after_as_of": 1,
    }


def test_future_duplicate_does_not_change_an_earlier_baseline() -> None:
    historical = [obs(str(i), float(10 + i)) for i in range(3)]
    future_duplicate = obs("0", 99, observed=AS_OF + timedelta(seconds=1))
    before = build_creator_baseline(historical, request())
    after = build_creator_baseline(historical + [future_duplicate], request())
    assert before.evidence_strength == "Low"
    assert after.evidence_strength == before.evidence_strength
    assert after.supporting_post_ids == before.supporting_post_ids
    assert dict(after.exclusion_counts) == {"observed_after_as_of": 1}


def test_observation_timestamp_is_not_confused_with_publication_timestamp() -> None:
    published = AS_OF - timedelta(days=100)
    observed = AS_OF - timedelta(minutes=5)
    result = build_creator_baseline(
        [obs("p", 12, published=published, observed=observed)], request()
    )
    assert result.supporting_post_ids == ("p",)
    assert result.as_of == AS_OF


def test_weighted_quantiles_rank_and_effective_sample_are_deterministic() -> None:
    assert weighted_quantile([10, 20, 30, 40], [1, 1, 1, 1], 0) == 10
    assert weighted_quantile([10, 20, 30, 40], [1, 1, 1, 1], 0.5) == 20
    assert weighted_quantile([10, 20, 30, 40], [1, 1, 1, 1], 1) == 40
    assert weighted_quantile([10, 20, 30], [8, 1, 1], 0.75) == 10
    assert effective_sample_size([1, 1, 1, 1]) == 4
    assert effective_sample_size([9, 1]) == pytest.approx(100 / 82)
    boundary_values = [10.0] * 10 + [1000.0] * 10
    quantiles = (0.1, 0.25, 0.5, 0.75, 0.9)
    unit_quantiles = [weighted_quantile(boundary_values, [1.0] * 20, q) for q in quantiles]
    scaled_quantiles = [weighted_quantile(boundary_values, [0.1] * 20, q) for q in quantiles]
    assert scaled_quantiles == unit_quantiles
    tiny_weights = [1e-14] * 4
    assert [weighted_quantile([10, 20, 30, 40], tiny_weights, q) for q in quantiles] == [
        weighted_quantile([10, 20, 30, 40], [1.0] * 4, q) for q in quantiles
    ]
    assert weighted_quantile([10, 20, 30, 40], tiny_weights, 1) == 40
    result = build_creator_baseline(
        [obs("a", 1), obs("b", 2), obs("c", 3)], request(target_value=2)
    )
    assert result.statistics is not None
    assert result.statistics.target_percentile_rank == 50


def test_large_quantile_uses_one_stable_total_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    original_fsum = baselines.math.fsum

    def counted_fsum(values: object) -> float:
        nonlocal calls
        calls += 1
        return original_fsum(values)  # type: ignore[arg-type]

    monkeypatch.setattr(baselines.math, "fsum", counted_fsum)
    size = 20_000
    values = [float(index) for index in range(size)]
    weights = [0.1] * size
    assert weighted_quantile(values, weights, 0.5) == float(size // 2 - 1)
    assert calls == 1


def test_high_moderate_low_and_insufficient_thresholds_are_fixed() -> None:
    high = build_creator_baseline([obs(str(i), 10 + i % 3) for i in range(24)], request())
    moderate = build_creator_baseline([obs(str(i), 10 + i % 3) for i in range(8)], request())
    low = build_creator_baseline(
        [obs(str(i), 10 + i % 2, weight=4.7 if i == 0 else 1) for i in range(8)], request()
    )
    insufficient = build_creator_baseline(
        [obs("a", 10, weight=10), obs("b", 11), obs("c", 12)], request()
    )
    assert high.evidence_strength == "High"
    assert moderate.evidence_strength == "Moderate"
    assert low.evidence_strength == "Low"
    assert insufficient.evidence_strength == "Insufficient"


def test_fractional_equal_weights_do_not_drift_below_evidence_boundaries() -> None:
    low = build_creator_baseline([obs(str(i), 10, weight=0.3) for i in range(3)], request())
    high = build_creator_baseline([obs(str(i), 10, weight=0.1) for i in range(20)], request())
    assert low.effective_sample_size == pytest.approx(3)
    assert low.evidence_strength == "Low"
    assert high.effective_sample_size == pytest.approx(20)
    assert high.evidence_strength == "High"


def test_hierarchical_backoff_and_shrinkage_are_explained() -> None:
    observations = [obs(f"specific-{i}", 100, segment=("topic", "format")) for i in range(3)] + [
        obs(f"broad-{i}", 10, segment=("topic", "other")) for i in range(20)
    ]
    result = build_creator_baseline(observations, request(segment_path=("topic", "format")))
    assert result.selected_hierarchy_level == 2
    assert result.shrinkage_weight == pytest.approx(3 / 11)
    assert result.statistics is not None
    assert result.statistics.p50 == pytest.approx((3 / 11) * 100 + (8 / 11) * 10)
    assert result.statistics.iqr == pytest.approx(result.statistics.p75 - result.statistics.p25)
    assert result.statistics.dispersion_ratio == pytest.approx(
        result.statistics.iqr / abs(result.statistics.p50)
    )
    assert result.supporting_post_ids == ("specific-0", "specific-1", "specific-2")


def test_sparse_segment_backs_off_to_parent_and_reports_wider_support() -> None:
    inputs = [obs("specific", 100, segment=("topic", "format"))] + [
        obs(f"peer-{i}", 10, segment=("topic", "other")) for i in range(5)
    ]
    result = build_creator_baseline(inputs, request(segment_path=("topic", "format")))
    assert result.selected_hierarchy_level == 1
    assert result.eligible_post_count == 6
    assert len(result.supporting_post_ids) == 6
    assert any("backed off" in reason for reason in result.reasons)


def test_duplicate_incompatible_and_invalid_observations_are_explained() -> None:
    inputs = [
        obs("duplicate", 1),
        obs("duplicate", 2),
        obs("negative", -1),
        obs("other-window", 1, window="age:1h"),
        obs("other-definition", 1, metric_definition="impressions_v2"),
        obs("other-creator", 1, creator="creator-2"),
        obs("before-publish", 1, observed=AS_OF - timedelta(days=3)),
    ]
    result = build_creator_baseline(inputs, request(segment_path=("topic",)))
    assert result.eligible_post_count == 0
    assert result.statistics is None
    assert dict(result.exclusion_counts) == {
        "duplicate_post_metric_window": 2,
        "incompatible_creator": 1,
        "incompatible_metric_definition": 1,
        "incompatible_window": 1,
        "negative_metric": 1,
        "observed_before_publication": 1,
    }


def test_contract_validation_rejects_naive_time_bad_weight_and_non_finite_values() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        obs("naive", 1, observed=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="positive"):
        obs("bad-weight", 1, weight=0)
    with pytest.raises(ValueError, match="finite"):
        obs("nan", float("nan"))
    with pytest.raises(ValueError, match="finite"):
        BaselineRequest(
            "creator-1", "views", "views_v1", "age:1h", AS_OF, target_value=float("inf")
        )


def test_unsupported_calculation_version_is_not_silently_accepted() -> None:
    result = build_creator_baseline([obs("p", 1)], request())
    assert result.version == "creator-baseline-v1"
    assert result.version == BASELINE_VERSION
