"""Pure evidence-aware postmortem evaluation for immutable Distribution Outlooks.

COD-361 supplies a version-linked ``PublishedPost``; COD-363 supplies mapped
``OutcomeObservation`` records with exact metric/window identity and real timestamps.
This module deliberately owns no persistence, scheduling, provider calls, or reconstruction
of missed windows.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from bipme.intelligence.baselines import (
    MINIMUM_EFFECTIVE_SAMPLE,
    BaselineRequest,
    CreatorBaseline,
    OutcomeObservation,
    build_creator_baseline,
)
from bipme.intelligence.outlooks import DistributionOutlook, MetricEvidence, OutlookRange

VersionMatchState = Literal["match", "mismatch", "unknown"]
ExpectedDirection = Literal["higher", "lower", "no_direction"]
HypothesisStatus = Literal["supported", "contradicted", "inconclusive"]
ComparisonStatus = Literal["scored", "unavailable", "version_unverified"]
VersionState = Literal["verified", "unverified"]
POSTMORTEM_VERSION = "evidence-aware-postmortem-v1"


@dataclass(frozen=True)
class AcceptedHypothesis:
    """Creator-accepted, pre-publication expectation from COD-358."""

    question: str
    metric: str
    metric_definition: str
    unit: str
    window_kind: Literal["mature_cumulative", "age_aligned"]
    window_key: str
    expected_direction: ExpectedDirection

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.question,
                self.metric,
                self.metric_definition,
                self.unit,
                self.window_key,
            )
        ):
            raise ValueError("accepted hypothesis fields cannot be blank")
        if self.window_kind not in ("mature_cumulative", "age_aligned"):
            raise ValueError("accepted hypothesis window_kind is unsupported")
        if self.expected_direction not in ("higher", "lower", "no_direction"):
            raise ValueError("accepted hypothesis expected_direction is unsupported")

    @property
    def exact_metric_definition(self) -> str:
        return f"{self.metric_definition}|unit={self.unit}"

    @property
    def exact_window(self) -> str:
        return f"{self.window_kind}:{self.window_key}"


@dataclass(frozen=True)
class OriginalAssessment:
    """Immutable persisted assessment identity, snapshot and optional accepted hypothesis."""

    assessment_id: str
    assessment_record_id: str
    creator_key: str
    assessed_at: datetime
    content_fingerprint: str
    outlook: DistributionOutlook
    accepted_hypothesis: AcceptedHypothesis | None = None

    def __post_init__(self) -> None:
        _require_aware(self.assessed_at, "assessed_at")
        if not self.assessment_id.strip() or not self.assessment_record_id.strip():
            raise ValueError("assessment identities cannot be blank")
        if not self.creator_key.strip():
            raise ValueError("creator_key cannot be blank")
        if self.outlook.assessment_id != self.assessment_id:
            raise ValueError("outlook assessment identity does not match the original assessment")
        if self.outlook.content_fingerprint != self.content_fingerprint:
            raise ValueError("outlook fingerprint does not match the original assessment")
        if self.outlook.assessment_cutoff != self.assessed_at:
            raise ValueError("outlook cutoff does not match the original assessment timestamp")


@dataclass(frozen=True)
class PublishedPost:
    """Typed COD-361 publication link and its assessed-version verification result."""

    creator_key: str
    post_id: str
    published_at: datetime
    source_assessment_id: str
    version_match_state: VersionMatchState
    content_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.published_at, "published_at")
        if not all(
            value.strip() for value in (self.creator_key, self.post_id, self.source_assessment_id)
        ):
            raise ValueError("published post identity fields cannot be blank")
        if self.version_match_state not in ("match", "mismatch", "unknown"):
            raise ValueError("published post version_match_state is unsupported")


@dataclass(frozen=True)
class PostmortemRequest:
    """Pure COD-361/363 handoff plus the immutable COD-354 assessment."""

    assessment: OriginalAssessment
    published_post: PublishedPost
    historical_outcomes: tuple[OutcomeObservation, ...]
    published_outcomes: tuple[OutcomeObservation, ...]
    evaluated_at: datetime

    def __post_init__(self) -> None:
        _require_aware(self.evaluated_at, "evaluated_at")


@dataclass(frozen=True)
class MetricComparison:
    metric: str
    metric_definition: str
    window: str
    status: ComparisonStatus
    observed_value: float | None
    observed_at: datetime | None
    observation_age_seconds: float | None
    reference_range: OutlookRange | None
    deviation_from_median: float | None
    within_reference_range: bool | None
    relative_percentile: float | None
    matched_sample_count: int
    effective_sample_size: float
    comparison_post_ids: tuple[str, ...]
    limitations: tuple[str, ...]
    historical_median: float | None = None
    comparison_observations: tuple[OutcomeObservation, ...] = ()


@dataclass(frozen=True)
class HypothesisEvaluation:
    status: HypothesisStatus
    hypothesis: AcceptedHypothesis
    metric: str
    metric_definition: str
    window: str
    observed_value: float | None
    historical_median: float | None
    matched_sample_count: int
    effective_sample_size: float
    comparison_post_ids: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class PostmortemResult:
    version: str
    version_state: VersionState
    assessment_id: str
    published_post_id: str
    original_outlook: DistributionOutlook
    observed_outcomes: tuple[OutcomeObservation, ...]
    metric_comparisons: tuple[MetricComparison, ...]
    hypothesis_evaluation: HypothesisEvaluation | None
    limitations: tuple[str, ...]


def build_postmortem(request: PostmortemRequest) -> PostmortemResult:
    """Compare a version-verified publication with exact-age immutable evidence."""
    version_reasons = _version_limitations(request)
    version_verified = not version_reasons
    comparisons = tuple(
        _compare_metric(request, metric, version_verified, version_reasons)
        for metric in request.assessment.outlook.metrics
    )
    hypothesis = request.assessment.accepted_hypothesis
    hypothesis_result = (
        _evaluate_hypothesis(request, hypothesis, comparisons, version_verified, version_reasons)
        if hypothesis is not None
        else None
    )
    limitations = list(version_reasons)
    linked_observations = tuple(
        item
        for item in request.published_outcomes
        if item.post_id == request.published_post.post_id
        and item.creator_key == request.published_post.creator_key
    )
    if len(linked_observations) != len(request.published_outcomes):
        limitations.append("Observations unrelated to the linked post or creator were excluded.")
    visible_observations = tuple(
        item for item in linked_observations if item.observed_at <= request.evaluated_at
    )
    if len(visible_observations) != len(linked_observations):
        limitations.append("Observations recorded after the postmortem cutoff were excluded.")
    limitations.append(
        "Outcome differences and hypothesis labels are descriptive associations; they do not establish causality or platform amplification."
    )
    if not request.assessment.outlook.metrics:
        limitations.append("The original outlook contains no metric evidence to compare.")
    return PostmortemResult(
        version=POSTMORTEM_VERSION,
        version_state="verified" if version_verified else "unverified",
        assessment_id=request.assessment.assessment_id,
        published_post_id=request.published_post.post_id,
        original_outlook=request.assessment.outlook,
        observed_outcomes=visible_observations,
        metric_comparisons=comparisons,
        hypothesis_evaluation=hypothesis_result,
        limitations=tuple(dict.fromkeys(limitations)),
    )


def _require_aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _has_minimum_effective_sample(value: float) -> bool:
    return value >= MINIMUM_EFFECTIVE_SAMPLE or math.isclose(
        value, MINIMUM_EFFECTIVE_SAMPLE, rel_tol=1e-12, abs_tol=1e-12
    )


def _version_limitations(request: PostmortemRequest) -> tuple[str, ...]:
    assessment = request.assessment
    published = request.published_post
    reasons: list[str] = []
    if published.creator_key != assessment.creator_key:
        reasons.append("Published post creator does not match the assessment owner.")
    if published.source_assessment_id != assessment.assessment_record_id:
        reasons.append("Published post is linked to a different assessment record.")
    if published.version_match_state != "match":
        reasons.append(
            "Published content version is mismatched or unverified against the assessed draft."
        )
    if (
        published.content_fingerprint is not None
        and published.content_fingerprint != assessment.content_fingerprint
    ):
        reasons.append("Published content fingerprint does not match the assessed draft.")
    if published.published_at < assessment.assessed_at:
        reasons.append("Published post predates its assessment timestamp.")
    return tuple(reasons)


def _compare_metric(
    request: PostmortemRequest,
    metric: MetricEvidence,
    version_verified: bool,
    version_reasons: tuple[str, ...],
) -> MetricComparison:
    assessment = request.assessment
    published = request.published_post
    exact_identity = (metric.metric, metric.metric_definition, metric.window)
    published_rows = [
        item
        for item in request.published_outcomes
        if item.post_id == published.post_id
        and (item.metric, item.metric_definition, item.window) == exact_identity
    ]
    limitations: list[str] = []
    if any(item.creator_key != assessment.creator_key for item in published_rows):
        limitations.append("Cross-creator published observations were excluded.")
    rows = [item for item in published_rows if item.creator_key == assessment.creator_key]
    if not rows:
        if not version_verified:
            limitations.extend(version_reasons)
            return MetricComparison(
                metric.metric,
                metric.metric_definition,
                metric.window,
                "version_unverified",
                None,
                None,
                None,
                metric.outlook,
                None,
                None,
                None,
                0,
                0.0,
                (),
                tuple(dict.fromkeys(limitations)),
            )
        if any(item.post_id == published.post_id for item in request.published_outcomes):
            limitations.append(
                "No published observation matches the exact metric definition and window; other series are not substituted."
            )
        else:
            limitations.append("No observed outcome is available for this metric and window.")
        return _unavailable_comparison(metric, limitations)

    foreign_time_rows = [item for item in rows if item.published_at != published.published_at]
    if foreign_time_rows:
        limitations.append("Observation publication time does not match the linked post.")
    rows = [item for item in rows if item.published_at == published.published_at]
    if any(item.observed_at < item.published_at for item in rows):
        limitations.append("Observations before publication are invalid and were excluded.")
    rows = [item for item in rows if item.observed_at >= item.published_at]
    if any(item.observed_at > request.evaluated_at for item in rows):
        limitations.append("Future observations are not available at this postmortem cutoff.")
    rows = [item for item in rows if item.observed_at <= request.evaluated_at]
    if len(rows) > 1:
        limitations.append(
            "Multiple observations exist for this metric window; no snapshot was chosen arbitrarily."
        )
        return _unavailable_comparison(metric, limitations)
    if not rows:
        return _unavailable_comparison(
            metric,
            limitations or ["No observation was available by the postmortem cutoff."],
        )
    target = rows[0]
    age = target.observed_at - target.published_at
    if target.value is None:
        limitations.append("The published metric is explicitly missing; it is not treated as zero.")
        return _unavailable_comparison(
            metric,
            limitations,
            observed_at=target.observed_at,
            age_seconds=age.total_seconds(),
        )
    if target.value < 0 or not math.isfinite(target.value):
        limitations.append("The published metric is invalid and cannot be compared.")
        return _unavailable_comparison(
            metric,
            limitations,
            observed_value=target.value,
            observed_at=target.observed_at,
            age_seconds=age.total_seconds(),
        )
    if not version_verified:
        limitations.extend(version_reasons)
        return MetricComparison(
            metric.metric,
            metric.metric_definition,
            metric.window,
            "version_unverified",
            target.value,
            target.observed_at,
            age.total_seconds(),
            metric.outlook,
            None,
            None,
            None,
            0,
            0.0,
            (),
            tuple(dict.fromkeys(limitations)),
        )

    history, history_limitations = _matched_history(request, metric, age)
    limitations.extend(history_limitations)
    baseline = _matched_baseline(request, metric, history, float(target.value))
    support_count = len(history)
    if baseline.statistics is None or baseline.evidence_strength == "Insufficient":
        limitations.append(
            "Fewer than 3 effective equal-age historical observations support relative comparison."
        )
        return MetricComparison(
            metric.metric,
            metric.metric_definition,
            metric.window,
            "unavailable",
            target.value,
            target.observed_at,
            age.total_seconds(),
            metric.outlook,
            None,
            None,
            None,
            support_count,
            baseline.effective_sample_size,
            tuple(item.post_id for item in history),
            tuple(dict.fromkeys(limitations)),
            comparison_observations=history,
        )

    stats = baseline.statistics
    reference = metric.outlook
    deviation = float(target.value) - reference.median_p50 if reference else None
    within = reference.lower_p25 <= target.value <= reference.upper_p75 if reference else None
    if reference is None:
        limitations.append("The original outlook withheld a reference range for this metric.")
    limitations.append(
        "Equal-age historical associations do not show what caused the published outcome."
    )
    return MetricComparison(
        metric.metric,
        metric.metric_definition,
        metric.window,
        "scored",
        target.value,
        target.observed_at,
        age.total_seconds(),
        reference,
        deviation,
        within,
        stats.target_percentile_rank,
        support_count,
        baseline.effective_sample_size,
        tuple(item.post_id for item in history),
        tuple(dict.fromkeys(limitations)),
        historical_median=stats.p50,
        comparison_observations=history,
    )


def _unavailable_comparison(
    metric: MetricEvidence,
    limitations: list[str],
    *,
    observed_value: float | None = None,
    observed_at: datetime | None = None,
    age_seconds: float | None = None,
) -> MetricComparison:
    return MetricComparison(
        metric.metric,
        metric.metric_definition,
        metric.window,
        "unavailable",
        observed_value,
        observed_at,
        age_seconds,
        metric.outlook,
        None,
        None,
        None,
        0,
        0.0,
        (),
        tuple(dict.fromkeys(limitations)),
    )


def _matched_history(
    request: PostmortemRequest, metric: MetricEvidence, target_age: timedelta
) -> tuple[tuple[OutcomeObservation, ...], tuple[str, ...]]:
    assessment = request.assessment
    allowed_ids = set(metric.supporting_post_ids)
    if metric.outlook is not None:
        allowed_ids.intersection_update(metric.outlook.comparable_post_ids)
    relevant = {
        item.post_id: item.relevance
        for item in assessment.outlook.comparable_evidence
        if item.post_id in allowed_ids
    }
    candidates: list[OutcomeObservation] = []
    reasons: list[str] = []
    duplicate_keys: Counter[tuple[str, str, str, str, datetime]] = Counter()
    for item in request.historical_outcomes:
        if (item.metric, item.metric_definition, item.window) != (
            metric.metric,
            metric.metric_definition,
            metric.window,
        ):
            continue
        if item.creator_key != assessment.creator_key:
            reasons.append("Cross-creator historical observations were excluded.")
            continue
        if item.post_id not in allowed_ids:
            continue
        if item.published_at >= assessment.assessed_at or item.observed_at > assessment.assessed_at:
            reasons.append("Historical observations unavailable at assessment time were excluded.")
            continue
        if item.observed_at < item.published_at:
            reasons.append("Historical observations before publication were excluded.")
            continue
        if item.value is None or item.value < 0:
            reasons.append("Missing or invalid historical metric values were excluded.")
            continue
        if item.observed_at - item.published_at != target_age:
            reasons.append(
                "Historical observation age differs from the published observation; no time alignment was inferred."
            )
            continue
        duplicate_keys[
            (item.post_id, item.metric, item.metric_definition, item.window, item.observed_at)
        ] += 1
        candidates.append(item)

    duplicate_ids = {
        post_id
        for post_id, metric_name, definition, window, observed_at in duplicate_keys
        if duplicate_keys[(post_id, metric_name, definition, window, observed_at)] > 1
    }
    if duplicate_ids:
        reasons.append("Duplicate historical observations were excluded.")
    output = tuple(
        replace(item, weight=relevant[item.post_id])
        for item in sorted(candidates, key=lambda row: row.post_id)
        if item.post_id not in duplicate_ids
        and item.post_id in relevant
        and relevant[item.post_id] > 0
    )
    return output, tuple(dict.fromkeys(reasons))


def _matched_baseline(
    request: PostmortemRequest,
    metric: MetricEvidence,
    history: tuple[OutcomeObservation, ...],
    target_value: float,
) -> CreatorBaseline:
    return build_creator_baseline(
        history,
        BaselineRequest(
            creator_key=request.assessment.creator_key,
            metric=metric.metric,
            metric_definition=metric.metric_definition,
            window=metric.window,
            as_of=request.evaluated_at,
            target_value=target_value,
        ),
    )


def _evaluate_hypothesis(
    request: PostmortemRequest,
    hypothesis: AcceptedHypothesis,
    comparisons: tuple[MetricComparison, ...],
    version_verified: bool,
    version_reasons: tuple[str, ...],
) -> HypothesisEvaluation:
    identity = (hypothesis.metric, hypothesis.exact_metric_definition, hypothesis.exact_window)
    comparison = next(
        (
            item
            for item in comparisons
            if (item.metric, item.metric_definition, item.window) == identity
        ),
        None,
    )
    limitations: list[str] = []
    if not version_verified:
        limitations.extend(version_reasons)
    if comparison is None:
        limitations.append(
            "No original outlook evidence matches the accepted hypothesis metric/window."
        )
    elif comparison.status != "scored" or comparison.observed_value is None:
        limitations.extend(comparison.limitations)
    if hypothesis.expected_direction == "no_direction":
        limitations.append("The accepted hypothesis specified no expected direction.")
    if (
        not version_verified
        or comparison is None
        or comparison.status != "scored"
        or comparison.observed_value is None
        or comparison.matched_sample_count < 3
        or not _has_minimum_effective_sample(comparison.effective_sample_size)
        or comparison.relative_percentile is None
        or hypothesis.expected_direction == "no_direction"
    ):
        return HypothesisEvaluation(
            "inconclusive",
            hypothesis,
            hypothesis.metric,
            hypothesis.exact_metric_definition,
            hypothesis.exact_window,
            comparison.observed_value if comparison else None,
            None,
            comparison.matched_sample_count if comparison else 0,
            comparison.effective_sample_size if comparison else 0.0,
            comparison.comparison_post_ids if comparison else (),
            tuple(dict.fromkeys(limitations)),
        )

    median = comparison.historical_median
    assert median is not None
    if comparison.observed_value == median:
        status: HypothesisStatus = "inconclusive"
        limitations.append("Observed outcome ties the matched historical median.")
    else:
        observed_higher = comparison.observed_value > median
        expected_higher = hypothesis.expected_direction == "higher"
        status = "supported" if observed_higher == expected_higher else "contradicted"
    limitations.append(
        "This descriptive comparison does not show that the tested content feature caused the outcome."
    )
    return HypothesisEvaluation(
        status,
        hypothesis,
        hypothesis.metric,
        hypothesis.exact_metric_definition,
        hypothesis.exact_window,
        comparison.observed_value,
        median,
        comparison.matched_sample_count,
        comparison.effective_sample_size,
        comparison.comparison_post_ids,
        tuple(dict.fromkeys(limitations)),
    )
