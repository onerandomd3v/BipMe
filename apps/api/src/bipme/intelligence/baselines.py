"""Deterministic creator-relative baselines over timestamped outcome observations.

This module has no persistence, X API, or retrieval dependency. Similarity weights and
segment paths are supplied by callers; outcome values never influence retrieval weights.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

BASELINE_VERSION = "creator-baseline-v1"
DEFAULT_SHRINKAGE_TAU = 8.0
MINIMUM_EFFECTIVE_SAMPLE = 3.0

EvidenceStrength = Literal["High", "Moderate", "Low", "Insufficient"]


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


@dataclass(frozen=True)
class OutcomeObservation:
    """One metric value measured for one post in one explicitly named window.

    Use distinct ``window`` values for mature cumulative totals and age-aligned snapshots
    (for example ``mature`` and ``age:1h``). ``None`` records a known missing value/window.
    """

    creator_key: str
    post_id: str
    metric: str
    metric_definition: str
    value: float | None
    published_at: datetime
    observed_at: datetime
    window: str
    weight: float = 1.0
    segment_path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.creator_key,
                self.post_id,
                self.metric,
                self.metric_definition,
                self.window,
            )
        ):
            raise ValueError(
                "creator_key, post_id, metric, metric_definition, and window are required"
            )
        _aware(self.published_at, "published_at")
        _aware(self.observed_at, "observed_at")
        if not math.isfinite(self.weight) or self.weight <= 0:
            raise ValueError("weight must be finite and positive")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("value must be finite or None")
        if any(not item.strip() for item in self.segment_path):
            raise ValueError("segment_path entries must be non-empty")


@dataclass(frozen=True)
class BaselineRequest:
    creator_key: str
    metric: str
    metric_definition: str
    window: str
    as_of: datetime
    segment_path: tuple[str, ...] = ()
    target_value: float | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.creator_key, self.metric, self.metric_definition, self.window)
        ):
            raise ValueError("creator_key, metric, metric_definition, and window are required")
        _aware(self.as_of, "as_of")
        if self.target_value is not None and not math.isfinite(self.target_value):
            raise ValueError("target_value must be finite or None")


@dataclass(frozen=True)
class BaselineStatistics:
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    minimum: float
    maximum: float
    iqr: float
    dispersion_ratio: float | None
    consistency_ratio: float
    outlier_count: int
    upper_outlier_count: int
    outlier_adjusted_p50: float
    median_shift_in_iqr: float
    maximum_weight_share: float
    target_percentile_rank: float | None


@dataclass(frozen=True)
class CreatorBaseline:
    version: str
    metric: str
    window: str
    as_of: datetime
    eligible_post_count: int
    supporting_post_ids: tuple[str, ...]
    effective_sample_size: float
    evidence_strength: EvidenceStrength
    selected_hierarchy_level: int | None
    shrinkage_weight: float | None
    statistics: BaselineStatistics | None
    exclusion_counts: tuple[tuple[str, int], ...]
    reasons: tuple[str, ...]


def weighted_quantile(values: list[float], weights: list[float], q: float) -> float:
    """Return the deterministic left-continuous inverse weighted empirical CDF."""
    if len(values) != len(weights) or not values:
        raise ValueError("values and weights must have equal, non-zero length")
    if not 0 <= q <= 1:
        raise ValueError("q must be between 0 and 1")
    if any(not math.isfinite(v) for v in values):
        raise ValueError("values must be finite")
    if any(not math.isfinite(w) or w <= 0 for w in weights):
        raise ValueError("weights must be finite and positive")
    pairs = sorted(zip(values, weights, strict=True), key=lambda pair: pair[0])
    threshold = q * math.fsum(weight for _, weight in pairs)
    cumulative_weights: list[float] = []
    for value, weight in pairs:
        cumulative_weights.append(weight)
        cumulative = math.fsum(cumulative_weights)
        if _at_least(cumulative, threshold):
            return value
    return pairs[-1][0]


def effective_sample_size(weights: list[float]) -> float:
    """Kish effective sample size for positive, not necessarily normalized weights."""
    if not weights:
        return 0.0
    if any(not math.isfinite(w) or w <= 0 for w in weights):
        raise ValueError("weights must be finite and positive")
    total = math.fsum(weights)
    return total * total / math.fsum(weight * weight for weight in weights)


def _stats(observations: list[OutcomeObservation], target: float | None) -> BaselineStatistics:
    values = [float(item.value) for item in observations if item.value is not None]
    weights = [item.weight for item in observations if item.value is not None]
    p10, p25, p50, p75, p90 = (
        weighted_quantile(values, weights, q) for q in (0.10, 0.25, 0.50, 0.75, 0.90)
    )
    iqr = p75 - p25
    scale = max(abs(p50), 1.0)
    lower_fence, upper_fence = p25 - 3 * iqr, p75 + 3 * iqr
    outliers = [value for value in values if value < lower_fence or value > upper_fence]
    retained = [
        (value, weight)
        for value, weight in zip(values, weights, strict=True)
        if lower_fence <= value <= upper_fence
    ]
    adjusted_p50 = (
        weighted_quantile([value for value, _ in retained], [weight for _, weight in retained], 0.5)
        if retained
        else p50
    )
    non_outlier_count = len(values) - len(outliers)
    return BaselineStatistics(
        p10=p10,
        p25=p25,
        p50=p50,
        p75=p75,
        p90=p90,
        minimum=min(values),
        maximum=max(values),
        iqr=iqr,
        dispersion_ratio=iqr / scale,
        consistency_ratio=non_outlier_count / len(values),
        outlier_count=len(outliers),
        upper_outlier_count=sum(value > upper_fence for value in values),
        outlier_adjusted_p50=adjusted_p50,
        median_shift_in_iqr=abs(p50 - adjusted_p50) / max(iqr, 1.0),
        maximum_weight_share=max(weights) / math.fsum(weights),
        target_percentile_rank=(
            100
            * (
                sum(weight for value, weight in zip(values, weights, strict=True) if value < target)
                + 0.5
                * sum(
                    weight for value, weight in zip(values, weights, strict=True) if value == target
                )
            )
            / math.fsum(weights)
            if target is not None
            else None
        ),
    )


def _classify(
    n_eff: float, stats: BaselineStatistics | None
) -> tuple[EvidenceStrength, tuple[str, ...]]:
    if not _at_least(n_eff, 3) or stats is None:
        return "Insufficient", (
            "Fewer than 3 effective eligible posts; no interpretation is justified.",
        )
    reasons: list[str] = []
    if (
        _at_least(n_eff, 20)
        and stats.consistency_ratio >= 0.70
        and stats.maximum_weight_share <= 0.20
    ):
        return "High", (
            "At least 20 effective posts, at least 70% within robust fences, and no dominant weight.",
        )
    if (
        _at_least(n_eff, 8)
        and stats.consistency_ratio >= 0.60
        and stats.maximum_weight_share <= 0.35
    ):
        return "Moderate", (
            "At least 8 effective posts with acceptable robust consistency and weight concentration.",
        )
    if _at_least(n_eff, 3):
        reasons.append(
            "At least 3 effective posts support only a low-strength descriptive baseline."
        )
    if stats.consistency_ratio < 0.60:
        reasons.append("High dispersion or outlier sensitivity reduces repeatability.")
    if stats.maximum_weight_share > 0.35:
        reasons.append("One observation carries more than 35% of the normalized weight.")
    return "Low", tuple(reasons)


def _at_least(value: float, threshold: float) -> bool:
    """Make mathematical threshold equality stable under ordinary float rounding."""
    return value >= threshold or math.isclose(value, threshold, rel_tol=1e-12, abs_tol=1e-12)


def build_creator_baseline(
    observations: list[OutcomeObservation] | tuple[OutcomeObservation, ...],
    request: BaselineRequest,
    *,
    shrinkage_tau: float = DEFAULT_SHRINKAGE_TAU,
) -> CreatorBaseline:
    """Build a weighted robust baseline, applying as-of and exact-window eligibility.

    The selected segment is the most specific prefix with effective N >= 3. Its quantiles
    shrink toward the immediately broader prefix with lambda=N_eff/(N_eff+tau). If no
    specific prefix reaches 3, the broader level is selected directly. These are initial
    engineering heuristics, not calibrated confidence probabilities.
    """
    if not math.isfinite(shrinkage_tau) or shrinkage_tau <= 0:
        raise ValueError("shrinkage_tau must be finite and positive")

    excluded: Counter[str] = Counter()
    candidates: list[OutcomeObservation] = []
    matching = [
        item
        for item in observations
        if item.creator_key == request.creator_key
        and item.metric == request.metric
        and item.metric_definition == request.metric_definition
    ]
    keys = Counter(
        (item.creator_key, item.post_id, item.metric, item.metric_definition, item.window)
        for item in matching
        if item.published_at <= request.as_of
        and item.observed_at <= request.as_of
        and item.observed_at >= item.published_at
    )
    for item in observations:
        if item.creator_key != request.creator_key:
            excluded["incompatible_creator"] += 1
            continue
        if item.metric != request.metric:
            excluded["incompatible_metric"] += 1
            continue
        if item.metric_definition != request.metric_definition:
            excluded["incompatible_metric_definition"] += 1
            continue
        if item.window != request.window:
            excluded["incompatible_window"] += 1
            continue
        if item.published_at > request.as_of:
            excluded["published_after_as_of"] += 1
            continue
        if item.observed_at < item.published_at:
            excluded["observed_before_publication"] += 1
            continue
        if item.observed_at > request.as_of:
            excluded["observed_after_as_of"] += 1
            continue
        if (
            keys[(item.creator_key, item.post_id, item.metric, item.metric_definition, item.window)]
            > 1
        ):
            excluded["duplicate_post_metric_window"] += 1
            continue
        if item.value is None:
            excluded["missing_metric_or_window"] += 1
            continue
        if item.value < 0:
            excluded["negative_metric"] += 1
            continue
        candidates.append(item)

    levels: list[tuple[int, list[OutcomeObservation]]] = []
    for level in range(len(request.segment_path), -1, -1):
        level_items = [
            item for item in candidates if item.segment_path[:level] == request.segment_path[:level]
        ]
        if level_items:
            levels.append((level, level_items))
    selected = next(
        (
            pair
            for pair in levels
            if _at_least(
                effective_sample_size([item.weight for item in pair[1]]), MINIMUM_EFFECTIVE_SAMPLE
            )
        ),
        levels[-1] if levels else (None, []),
    )
    selected_level, selected_items = selected
    if not selected_items or selected_level is None:
        reasons = ("No eligible observations for this metric and comparison window.",)
        return CreatorBaseline(
            BASELINE_VERSION,
            request.metric,
            request.window,
            request.as_of,
            0,
            (),
            0.0,
            "Insufficient",
            None,
            None,
            None,
            tuple(sorted(excluded.items())),
            reasons,
        )

    n_eff = effective_sample_size([item.weight for item in selected_items])
    stats = _stats(selected_items, request.target_value)
    shrinkage_weight: float | None = None
    broader = next((items for level, items in levels if level < selected_level), None)
    if broader is not None:
        broad_stats = _stats(broader, request.target_value)
        shrinkage_weight = n_eff / (n_eff + shrinkage_tau)
        p10 = shrinkage_weight * stats.p10 + (1 - shrinkage_weight) * broad_stats.p10
        p25 = shrinkage_weight * stats.p25 + (1 - shrinkage_weight) * broad_stats.p25
        p50 = shrinkage_weight * stats.p50 + (1 - shrinkage_weight) * broad_stats.p50
        p75 = shrinkage_weight * stats.p75 + (1 - shrinkage_weight) * broad_stats.p75
        p90 = shrinkage_weight * stats.p90 + (1 - shrinkage_weight) * broad_stats.p90
        shrunk_iqr = p75 - p25
        stats = BaselineStatistics(
            p10=p10,
            p25=p25,
            p50=p50,
            p75=p75,
            p90=p90,
            minimum=min(item.value for item in selected_items if item.value is not None),
            maximum=max(item.value for item in selected_items if item.value is not None),
            iqr=shrunk_iqr,
            dispersion_ratio=shrunk_iqr / max(abs(p50), 1.0),
            consistency_ratio=stats.consistency_ratio,
            outlier_count=stats.outlier_count,
            upper_outlier_count=stats.upper_outlier_count,
            outlier_adjusted_p50=stats.outlier_adjusted_p50,
            median_shift_in_iqr=stats.median_shift_in_iqr,
            maximum_weight_share=stats.maximum_weight_share,
            target_percentile_rank=stats.target_percentile_rank,
        )
    evidence, evidence_reasons = _classify(n_eff, stats)
    reason_list = list(evidence_reasons)
    if selected_level < len(request.segment_path):
        reason_list.append(
            f"Baseline backed off to hierarchy level {selected_level} of {len(request.segment_path)}."
        )
    if stats.outlier_count:
        reason_list.append(
            f"{stats.outlier_count} eligible observation(s) lie beyond the 3×IQR fences."
        )
    if stats.consistency_ratio < 1:
        reason_list.append(
            "Repeatability describes the share within robust fences; it does not establish causality."
        )
    return CreatorBaseline(
        version=BASELINE_VERSION,
        metric=request.metric,
        window=request.window,
        as_of=request.as_of,
        eligible_post_count=len(selected_items),
        supporting_post_ids=tuple(sorted(item.post_id for item in selected_items)),
        effective_sample_size=n_eff,
        evidence_strength=evidence,
        selected_hierarchy_level=selected_level,
        shrinkage_weight=shrinkage_weight,
        statistics=stats,
        exclusion_counts=tuple(sorted(excluded.items())),
        reasons=tuple(dict.fromkeys(reason_list)),
    )
