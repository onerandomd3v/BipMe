"""Chronological, synthetic-first diagnostics for Distribution Outlook references.

COD-354's P25–P75 values are historical reference ranges, not calibrated prediction
intervals. This harness therefore calls coverage a *reference-range coverage rate* and
reports it descriptively. It replays the existing outlook builder at each recorded
assessment cutoff; held-out observations are labels only and never enter that outlook.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from bipme.intelligence.baselines import (
    OutcomeObservation,
    effective_sample_size,
    weighted_quantile,
)
from bipme.intelligence.outlooks import (
    DistributionOutlook,
    OutlookRequest,
    build_distribution_outlook,
)

BACKTEST_VERSION = "distribution-outlook-walk-forward-v1"
EvidenceBand = Literal["High", "Moderate", "Low", "Insufficient"]
OutcomeDirection = Literal["below", "within", "above"]
SelectionBasis = Literal["complete_archive", "sampled", "unknown"]
_BANDS: tuple[EvidenceBand, ...] = ("High", "Moderate", "Low", "Insufficient")


@dataclass(frozen=True)
class OutlookBacktestCase:
    """One immutable pre-publication outlook and its later, held-out metric observation."""

    case_id: str
    target_post_id: str
    target_published_at: datetime
    outlook_request: OutlookRequest
    target_observation: OutcomeObservation
    comparable_publication_times: tuple[tuple[str, datetime], ...]


@dataclass(frozen=True)
class BacktestSpec:
    """Exact metric and report cutoff used for one deterministic evaluation run."""

    creator_key: str
    metric: str
    metric_definition: str
    window: str
    evaluation_as_of: datetime
    selection_basis: SelectionBasis = "unknown"
    minimum_band_samples: int = 3


@dataclass(frozen=True)
class BacktestExclusion:
    """Counts for records deliberately omitted from prediction or scoring."""

    name: str
    count: int


@dataclass(frozen=True)
class BacktestCaseResult:
    """Per-cutoff replay diagnostics; ``None`` means the requested score is unsupported."""

    case_id: str
    assessment_cutoff: datetime
    evidence_strength: EvidenceBand
    metric_coverage: float | None
    prior_observation_count: int
    prior_effective_sample_size: float
    target_value: float | None
    reference_range_covered: bool | None
    absolute_percentile_error: float | None
    predicted_direction: OutcomeDirection | None
    observed_direction: OutcomeDirection | None
    direction_correct: bool | None
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class EvidenceBandQuality:
    """Descriptive score aggregates and denominator for one COD-354 evidence band."""

    evidence_strength: EvidenceBand
    replay_count: int
    scored_count: int
    reference_range_coverage: float | None
    percentile_scored_count: int
    median_absolute_percentile_error: float | None
    percentile_error_sample_adequate: bool
    direction_scored_count: int
    direction_accuracy: float | None
    sample_adequate: bool
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class OutlierSensitivity:
    """Coverage recomputed after excluding historical 3x-IQR outlier observations."""

    scored_count: int
    outliers_excluded: int
    reference_range_coverage: float | None
    outlier_excluded_coverage: float | None


@dataclass(frozen=True)
class CalibrationQualityReport:
    """Versioned deterministic report. Metrics are descriptive, not probability claims."""

    version: str
    creator_key: str
    metric: str
    metric_definition: str
    window: str
    evaluation_as_of: datetime
    selection_basis: SelectionBasis
    replay_count: int
    scored_count: int
    exclusions: tuple[BacktestExclusion, ...]
    evidence_bands: tuple[EvidenceBandQuality, ...]
    outlier_sensitivity: OutlierSensitivity
    cases: tuple[BacktestCaseResult, ...]
    limitations: tuple[str, ...]


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _validate(case: OutlookBacktestCase, spec: BacktestSpec) -> None:
    _aware(spec.evaluation_as_of, "evaluation_as_of")
    _aware(case.target_published_at, "target_published_at")
    request = case.outlook_request
    cutoff = request.assessment.as_of
    _aware(cutoff, "assessment_cutoff")
    if not case.case_id.strip() or not case.target_post_id.strip():
        raise ValueError("case_id and target_post_id are required")
    if request.assessment.creator_key != spec.creator_key:
        raise ValueError("backtest assessment creator does not match spec")
    if request.assessment.as_of >= case.target_published_at:
        raise ValueError("assessment cutoff must precede target publication")
    target = case.target_observation
    if (target.creator_key, target.post_id) != (spec.creator_key, case.target_post_id):
        raise ValueError("target observation identity does not match backtest case")
    if (target.metric, target.metric_definition, target.window) != (
        spec.metric,
        spec.metric_definition,
        spec.window,
    ):
        raise ValueError("target observation metric definition and window must match spec")
    if target.published_at != case.target_published_at:
        raise ValueError("target observation publication time must match case")
    if target.observed_at <= cutoff:
        raise ValueError("held-out target observation must be recorded after assessment cutoff")
    if target.observed_at < case.target_published_at:
        raise ValueError("target observation cannot precede target publication")
    if case.target_post_id in {item.post_id for item in request.comparable_set.matches}:
        raise ValueError("held-out target cannot also be a comparable")
    publication_times = dict(case.comparable_publication_times)
    if len(publication_times) != len(case.comparable_publication_times):
        raise ValueError("comparable publication times contain duplicate post IDs")
    for post_id, published_at in case.comparable_publication_times:
        _aware(published_at, f"comparable publication time for {post_id}")
    match_ids = {item.post_id for item in request.comparable_set.matches}
    if match_ids != set(publication_times):
        raise ValueError("publication times must cover exactly the selected comparables")
    if any(value > cutoff for value in publication_times.values()):
        raise ValueError("a selected comparable was published after the assessment cutoff")


def _deduplicated_request(
    request: OutlookRequest,
) -> tuple[OutlookRequest, int, set[tuple[str, str, str, str, str]]]:
    """Deduplicate exact keys only among timestamp-eligible as-of observations."""
    grouped: dict[tuple[str, str, str, str, str], list[OutcomeObservation]] = defaultdict(list)
    cutoff = request.assessment.as_of
    for item in request.outcomes:
        if (
            item.published_at > cutoff
            or item.observed_at > cutoff
            or item.observed_at < item.published_at
        ):
            continue
        grouped[
            (item.creator_key, item.post_id, item.metric, item.metric_definition, item.window)
        ].append(item)
    duplicates = {key for key, values in grouped.items() if len(values) > 1}
    clean = tuple(
        item
        for item in request.outcomes
        if not (
            (
                item.published_at <= cutoff
                and item.observed_at <= cutoff
                and item.observed_at >= item.published_at
            )
            and (item.creator_key, item.post_id, item.metric, item.metric_definition, item.window)
            in duplicates
        )
    )
    return (
        replace(request, outcomes=clean),
        sum(len(grouped[key]) for key in duplicates),
        duplicates,
    )


def _eligible_history(
    request: OutlookRequest, spec: BacktestSpec, duplicate_keys: set[tuple[str, str, str, str, str]]
) -> list[OutcomeObservation]:
    cutoff = request.assessment.as_of
    selected = {item.post_id: item.relevance for item in request.comparable_set.matches}
    output: list[OutcomeObservation] = []
    for item in request.outcomes:
        if item.creator_key != spec.creator_key or item.post_id not in selected:
            continue
        if (item.metric, item.metric_definition, item.window) != (
            spec.metric,
            spec.metric_definition,
            spec.window,
        ):
            continue
        key = (item.creator_key, item.post_id, item.metric, item.metric_definition, item.window)
        if key in duplicate_keys:
            continue
        if (
            item.published_at > cutoff
            or item.observed_at > cutoff
            or item.observed_at < item.published_at
            or item.value is None
            or item.value < 0
        ):
            continue
        weight = selected[item.post_id]
        if weight > 0:
            output.append(replace(item, weight=weight))
    return sorted(output, key=lambda item: (item.published_at, item.post_id))


def _eligible_creator_history(
    request: OutlookRequest,
    spec: BacktestSpec,
    duplicate_keys: set[tuple[str, str, str, str, str]],
) -> list[OutcomeObservation]:
    """Return unweighted creator history for the directional reference median."""
    cutoff = request.assessment.as_of
    output: list[OutcomeObservation] = []
    for item in request.outcomes:
        key = (item.creator_key, item.post_id, item.metric, item.metric_definition, item.window)
        if key in duplicate_keys or item.creator_key != spec.creator_key:
            continue
        if (item.metric, item.metric_definition, item.window) != (
            spec.metric,
            spec.metric_definition,
            spec.window,
        ):
            continue
        if (
            item.published_at > cutoff
            or item.observed_at > cutoff
            or item.observed_at < item.published_at
            or item.value is None
            or item.value < 0
        ):
            continue
        output.append(replace(item, weight=1.0))
    return sorted(output, key=lambda item: (item.published_at, item.post_id))


def _percentile(value: float, history: list[OutcomeObservation]) -> float | None:
    if not history:
        return None
    total = math.fsum(item.weight for item in history)
    below = math.fsum(item.weight for item in history if _value(item) < value)
    tied = math.fsum(item.weight for item in history if _value(item) == value)
    return 100.0 * (below + tied / 2) / total


def _value(item: OutcomeObservation) -> float:
    """Require a known observation value; missing values must never become numeric zero."""
    if item.value is None:
        raise ValueError("missing observations cannot enter backtest arithmetic")
    return item.value


def _score_case(
    case: OutlookBacktestCase,
    spec: BacktestSpec,
    outlook: DistributionOutlook,
    history: list[OutcomeObservation],
    creator_history: list[OutcomeObservation],
) -> tuple[BacktestCaseResult, bool]:
    metric = next(
        (
            item
            for item in outlook.metrics
            if (item.metric, item.metric_definition, item.window)
            == (spec.metric, spec.metric_definition, spec.window)
        ),
        None,
    )
    strength: EvidenceBand = metric.evidence_strength if metric else "Insufficient"
    history_weights = [item.weight for item in history]
    limitations: list[str] = []
    target = case.target_observation
    if target.value is None:
        limitations.append("Target metric is missing; missing values are not imputed as zero.")
    if target.observed_at > spec.evaluation_as_of:
        limitations.append("Target observation was not yet available at the report cutoff.")
    if metric is None or metric.outlook is None:
        limitations.append(
            "No supported COD-354 reference range exists for this exact metric/window."
        )
    if len(history) < 3:
        limitations.append(
            "Fewer than 3 known, compatible prior observations support percentile scoring."
        )
    if target.value is None or target.observed_at > spec.evaluation_as_of or metric is None:
        return (
            BacktestCaseResult(
                case.case_id,
                case.outlook_request.assessment.as_of,
                strength,
                metric.coverage if metric else None,
                len(history),
                effective_sample_size(history_weights),
                target.value,
                None,
                None,
                None,
                None,
                None,
                tuple(limitations),
            ),
            False,
        )

    interval = metric.outlook
    covered = (
        (
            target.value is not None
            and interval is not None
            and interval.lower_p25 <= target.value <= interval.upper_p75
        )
        if interval
        else None
    )
    percentile = _percentile(float(target.value), history) if len(history) >= 3 else None
    percentile_error = abs(percentile - 50.0) if percentile is not None else None
    direction: OutcomeDirection | None = None
    actual_direction: OutcomeDirection | None = None
    direction_correct: bool | None = None
    if interval is not None and creator_history:
        values, weights = (
            [_value(item) for item in creator_history],
            [item.weight for item in creator_history],
        )
        benchmark = weighted_quantile(values, weights, 0.5)
        predicted: OutcomeDirection = (
            "above"
            if interval.lower_p25 > benchmark
            else "below"
            if interval.upper_p75 < benchmark
            else "within"
        )
        observed: OutcomeDirection = (
            "above"
            if target.value > benchmark
            else "below"
            if target.value < benchmark
            else "within"
        )
        direction, actual_direction, direction_correct = predicted, observed, predicted == observed
    if percentile_error is None:
        limitations.append("Percentile error is unavailable without 3 compatible prior outcomes.")
    if direction_correct is None:
        limitations.append(
            "Directional comparison is unavailable without a supported range and prior baseline."
        )
    return (
        BacktestCaseResult(
            case.case_id,
            case.outlook_request.assessment.as_of,
            strength,
            metric.coverage if metric else None,
            len(history),
            effective_sample_size(history_weights),
            target.value,
            covered,
            percentile_error,
            direction,
            actual_direction,
            direction_correct,
            tuple(limitations),
        ),
        interval is not None,
    )


def _median(values: list[float]) -> float | None:
    return weighted_quantile(values, [1.0] * len(values), 0.5) if values else None


def evaluate_distribution_outlooks(
    cases: tuple[OutlookBacktestCase, ...], spec: BacktestSpec
) -> CalibrationQualityReport:
    """Replay outlooks in cutoff order, score mature held-out labels and report gaps.

    A case carries the immutable COD-354 inputs that were available at its historical
    assessment cutoff. The builder itself applies outcome ``observed_at`` eligibility;
    profile and creator-context timestamps are validated by ``OutlookRequest``. Target
    observations are kept outside the request and are never passed to the outlook builder.
    """
    _aware(spec.evaluation_as_of, "evaluation_as_of")
    if not all(
        value.strip()
        for value in (spec.creator_key, spec.metric, spec.metric_definition, spec.window)
    ):
        raise ValueError("creator_key, metric, metric_definition and window are required")
    if spec.minimum_band_samples < 1:
        raise ValueError("minimum_band_samples must be positive")
    if spec.selection_basis not in ("complete_archive", "sampled", "unknown"):
        raise ValueError("unsupported selection_basis")
    for case in cases:
        _validate(case, spec)
    ordered = tuple(
        sorted(cases, key=lambda item: (item.outlook_request.assessment.as_of, item.case_id))
    )
    if len({case.case_id for case in ordered}) != len(ordered):
        raise ValueError("backtest case IDs must be unique")
    post_ids = [case.target_post_id for case in ordered]
    duplicate_target_ids = {post_id for post_id, count in Counter(post_ids).items() if count > 1}
    exclusions: Counter[str] = Counter()
    if duplicate_target_ids:
        exclusions["duplicate_target_post"] += sum(
            post_id in duplicate_target_ids for post_id in post_ids
        )

    results: list[BacktestCaseResult] = []
    outlier_coverage: list[bool] = []
    all_coverage: list[bool] = []
    outliers_excluded = 0
    replay_count = 0
    for case in ordered:
        if case.target_post_id in duplicate_target_ids:
            continue
        if case.target_observation.observed_at > spec.evaluation_as_of:
            exclusions["target_not_observed_by_evaluation_cutoff"] += 1
        request = case.outlook_request
        clean_request, duplicate_count, duplicate_keys = _deduplicated_request(request)
        exclusions["duplicate_outcome_record"] += duplicate_count
        exclusions["future_or_unobserved_comparable_outcome"] += sum(
            item.observed_at > request.assessment.as_of
            or item.published_at > request.assessment.as_of
            for item in clean_request.outcomes
        )
        exclusions["incompatible_metric_or_window"] += sum(
            (item.metric, item.metric_definition, item.window)
            != (spec.metric, spec.metric_definition, spec.window)
            for item in clean_request.outcomes
        )
        exclusions["cross_creator_outcome"] += sum(
            item.creator_key != spec.creator_key for item in clean_request.outcomes
        )
        selected_ids = {match.post_id for match in request.comparable_set.matches}
        exclusions["missing_comparable_value"] += sum(
            item.creator_key == spec.creator_key
            and item.post_id in selected_ids
            and (item.metric, item.metric_definition, item.window)
            == (spec.metric, spec.metric_definition, spec.window)
            and item.value is None
            and item.published_at <= request.assessment.as_of
            and item.observed_at <= request.assessment.as_of
            and item.observed_at >= item.published_at
            for item in clean_request.outcomes
        )
        exclusions["observation_before_publication"] += sum(
            item.creator_key == spec.creator_key
            and item.post_id in selected_ids
            and (item.metric, item.metric_definition, item.window)
            == (spec.metric, spec.metric_definition, spec.window)
            and item.observed_at < item.published_at
            for item in clean_request.outcomes
        )
        exclusions["negative_comparable_value"] += sum(
            item.creator_key == spec.creator_key
            and item.post_id in selected_ids
            and (item.metric, item.metric_definition, item.window)
            == (spec.metric, spec.metric_definition, spec.window)
            and item.value is not None
            and item.value < 0
            and item.published_at <= request.assessment.as_of
            and item.observed_at <= request.assessment.as_of
            and item.observed_at >= item.published_at
            for item in clean_request.outcomes
        )
        replay = build_distribution_outlook(clean_request)
        history = _eligible_history(clean_request, spec, duplicate_keys)
        creator_history = _eligible_creator_history(clean_request, spec, duplicate_keys)
        result, has_range = _score_case(case, spec, replay, history, creator_history)
        results.append(result)
        replay_count += 1
        if case.target_observation.value is None:
            exclusions["missing_target_value"] += 1
        elif case.target_observation.observed_at <= spec.evaluation_as_of and has_range:
            all_coverage.append(bool(result.reference_range_covered))
            interval = next(
                item.outlook
                for item in replay.metrics
                if (item.metric, item.metric_definition, item.window)
                == (spec.metric, spec.metric_definition, spec.window)
            )
            assert interval is not None
            values = [_value(item) for item in history]
            weights = [item.weight for item in history]
            p25, p75 = (
                weighted_quantile(values, weights, 0.25),
                weighted_quantile(values, weights, 0.75),
            )
            iqr = p75 - p25
            retained = [item for item in history if p25 - 3 * iqr <= _value(item) <= p75 + 3 * iqr]
            outliers_excluded += len(history) - len(retained)
            if retained:
                values2, weights2 = (
                    [_value(item) for item in retained],
                    [item.weight for item in retained],
                )
                low, high = (
                    weighted_quantile(values2, weights2, 0.25),
                    weighted_quantile(values2, weights2, 0.75),
                )
                outlier_coverage.append(low <= float(case.target_observation.value) <= high)

    by_band: dict[EvidenceBand, list[BacktestCaseResult]] = {band: [] for band in _BANDS}
    for result in results:
        by_band[result.evidence_strength].append(result)
    band_reports: list[EvidenceBandQuality] = []
    for band in _BANDS:
        rows = by_band[band]
        scored = [item for item in rows if item.reference_range_covered is not None]
        errors = [
            item.absolute_percentile_error
            for item in rows
            if item.absolute_percentile_error is not None
        ]
        directions = [item.direction_correct for item in rows if item.direction_correct is not None]
        adequate = len(scored) >= spec.minimum_band_samples
        percentile_adequate = len(errors) >= spec.minimum_band_samples
        reasons: list[str] = []
        if not adequate:
            reasons.append(
                f"Fewer than {spec.minimum_band_samples} scored cases; band metrics are descriptive and sparse."
            )
        if not errors:
            reasons.append("No compatible prior samples support percentile-error reporting.")
        elif not percentile_adequate:
            reasons.append(
                f"Fewer than {spec.minimum_band_samples} percentile-scored cases; percentile error is sparse."
            )
        band_reports.append(
            EvidenceBandQuality(
                band,
                len(rows),
                len(scored),
                sum(bool(item.reference_range_covered) for item in scored) / len(scored)
                if scored
                else None,
                len(errors),
                _median(errors),
                percentile_adequate,
                len(directions),
                sum(bool(item) for item in directions) / len(directions) if directions else None,
                adequate,
                tuple(reasons),
            )
        )
    limitations = [
        "Synthetic or selected retrospective cases verify behavior and time boundaries, not real-world predictive performance.",
        "COD-354 P25–P75 values are historical reference ranges; coverage is descriptive and is not probability calibration.",
        "Percentile error is the held-out outcome's weighted midrank distance from the historical median (50th percentile).",
        "Directional accuracy compares the outlook range and held-out value with the pre-cutoff unweighted creator-history median; it is not causal evidence.",
        "Selection bias, platform changes and missing private X signals can limit representativeness; no X ranking mechanism is inferred.",
        "COD-364 should consume the same immutable original outlook and version-matched, equal-age observation contract when its postmortem implementation is available.",
    ]
    if spec.selection_basis != "complete_archive":
        limitations.append(
            "Input history is sampled or its completeness is unknown; outcome rates may reflect selection bias."
        )
    return CalibrationQualityReport(
        BACKTEST_VERSION,
        spec.creator_key,
        spec.metric,
        spec.metric_definition,
        spec.window,
        spec.evaluation_as_of,
        spec.selection_basis,
        replay_count,
        len(all_coverage),
        tuple(
            BacktestExclusion(name, count) for name, count in sorted(exclusions.items()) if count
        ),
        tuple(band_reports),
        OutlierSensitivity(
            len(all_coverage),
            outliers_excluded,
            sum(all_coverage) / len(all_coverage) if all_coverage else None,
            sum(outlier_coverage) / len(outlier_coverage) if outlier_coverage else None,
        ),
        tuple(results),
        tuple(limitations),
    )
