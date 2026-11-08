"""Deterministic, evidence-backed creator decisions assembled from existing intelligence.

Retrieval relevance is fixed before outcomes are inspected. Outcomes are restricted to the
selected comparable IDs and their relevance is the only weight passed to the baseline
calculator. This service emits historical descriptions and optional test questions; it does
not estimate causal lift or a calibrated future-performance interval.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Literal

from bipme.intelligence.baselines import (
    BASELINE_VERSION,
    BaselineRequest,
    BaselineStatistics,
    CreatorBaseline,
    EvidenceStrength,
    OutcomeObservation,
    build_creator_baseline,
    weighted_quantile,
)
from bipme.intelligence.post_profiles import PROFILE_VERSION, PostProfile
from bipme.intelligence.retrieval import (
    RANKING_CONFIG_VERSION,
    RETRIEVAL_ALGORITHM_VERSION,
    CandidateExclusion,
    ComparableSet,
    DraftAssessment,
    RelevanceComponents,
)

OUTLOOK_ALGORITHM_VERSION = "distribution-outlook-v1"
OUTLOOK_CONFIG_VERSION = "distribution-outlook-config-v1"
_FINGERPRINT = re.compile(r"^sha256:[0-9a-f]{64}$")

DecisionState = Literal["supported", "insufficient_evidence"]
ObservationKind = Literal["repeatability", "outlier", "coverage_limitation"]
SuggestionKind = Literal["experiment_hypothesis"]


@dataclass(frozen=True)
class OutlookConfig:
    """Versioned conservative gates for descriptive metric outlooks."""

    minimum_metric_coverage: float = 0.60
    minimum_experiment_group_effective_sample: float = 3.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.minimum_metric_coverage) or not (
            0 < self.minimum_metric_coverage <= 1
        ):
            raise ValueError("minimum_metric_coverage must be in (0, 1]")
        if (
            not math.isfinite(self.minimum_experiment_group_effective_sample)
            or self.minimum_experiment_group_effective_sample < 3
        ):
            raise ValueError("experiment groups must require at least 3 effective observations")

    @property
    def algorithm_version(self) -> str:
        return OUTLOOK_ALGORITHM_VERSION

    @property
    def config_version(self) -> str:
        return (
            f"{OUTLOOK_CONFIG_VERSION}:coverage={self.minimum_metric_coverage!r}"
            f":experiment_group_n_eff={self.minimum_experiment_group_effective_sample!r}"
        )


@dataclass(frozen=True)
class OutlookRequest:
    """All inputs needed to assemble one immutable, as-of draft decision.

    ``content_fingerprint`` is validated but never generated here. The caller owns the
    canonicalization boundary and must provide a SHA-256 digest of the assessed version.
    ``comparable_profiles`` carries only versioned descriptive features, never raw text.
    """

    assessment: DraftAssessment
    content_fingerprint: str
    comparable_set: ComparableSet
    outcomes: tuple[OutcomeObservation, ...]
    comparable_profiles: tuple[tuple[str, PostProfile], ...] = ()
    config: OutlookConfig = OutlookConfig()

    def __post_init__(self) -> None:
        if not _FINGERPRINT.fullmatch(self.content_fingerprint):
            raise ValueError("content_fingerprint must be a validated SHA-256 fingerprint")
        if self.comparable_set.assessment_id != self.assessment.assessment_id:
            raise ValueError("comparable set assessment does not match the draft assessment")
        if self.comparable_set.as_of != self.assessment.as_of:
            raise ValueError("comparable set cutoff does not match the draft assessment")
        if self.comparable_set.embedding_identity != self.assessment.embedding_identity:
            raise ValueError("comparable set embedding identity does not match the assessment")
        if len({item.post_id for item in self.comparable_set.matches}) != len(
            self.comparable_set.matches
        ):
            raise ValueError("comparable set contains duplicate post IDs")
        if any(
            not math.isfinite(item.relevance) or not 0 <= item.relevance <= 1
            for item in self.comparable_set.matches
        ):
            raise ValueError("comparable relevance must be finite and in [0, 1]")
        if any(not item.post_id.strip() for item in self.comparable_set.matches):
            raise ValueError("comparable post IDs cannot be blank")
        profile_ids = [post_id for post_id, _ in self.comparable_profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("comparable profiles contain duplicate post IDs")
        match_ids = {item.post_id for item in self.comparable_set.matches}
        for post_id, profile in self.comparable_profiles:
            if post_id not in match_ids:
                raise ValueError("comparable profile is not part of the selected comparable set")
            if not post_id.strip():
                raise ValueError("comparable profile post ID cannot be blank")
            if profile.creator_key not in (None, self.assessment.creator_key):
                raise ValueError("comparable profile belongs to a different creator")
            for name, timestamp in (
                ("features_as_of", profile.features_as_of),
                ("input_observed_at", profile.input_observed_at),
            ):
                if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    raise ValueError(f"comparable profile {name} must be timezone-aware")
            if profile.features_as_of > self.assessment.as_of:
                raise ValueError("comparable profile features are after the assessment cutoff")
            if profile.input_observed_at > self.assessment.as_of:
                raise ValueError(
                    "comparable profile input was observed after the assessment cutoff"
                )
            if profile.creator_context_observed_at is not None:
                context_time = profile.creator_context_observed_at
                if context_time.tzinfo is None or context_time.utcoffset() is None:
                    raise ValueError(
                        "comparable profile creator context time must be timezone-aware"
                    )
                if context_time > self.assessment.as_of:
                    raise ValueError(
                        "comparable profile creator context is after the assessment cutoff"
                    )


@dataclass(frozen=True)
class ComparableEvidence:
    post_id: str
    relevance: float
    components: RelevanceComponents
    retrieval_position: int
    inclusion_reasons: tuple[str, ...]


@dataclass(frozen=True)
class OutlookRange:
    """Historical weighted P25–P75 reference range in the source metric's units."""

    kind: str
    lower_p25: float
    median_p50: float
    upper_p75: float
    comparable_post_ids: tuple[str, ...]
    effective_sample_size: float


@dataclass(frozen=True)
class MetricEvidence:
    metric: str
    metric_definition: str
    window: str
    evidence_strength: EvidenceStrength
    coverage: float
    eligible_post_count: int
    effective_sample_size: float
    supporting_post_ids: tuple[str, ...]
    statistics: BaselineStatistics | None
    exclusion_counts: tuple[tuple[str, int], ...]
    limitations: tuple[str, ...]
    outlook: OutlookRange | None


@dataclass(frozen=True)
class DecisionObservation:
    kind: ObservationKind
    explanation: str
    supporting_post_ids: tuple[str, ...]
    metric: str | None
    metric_definition: str | None
    window: str | None
    evidence_strength: EvidenceStrength
    evidence_statistics: BaselineStatistics | None
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class TestableSuggestion:
    kind: SuggestionKind
    label: str
    variable: str
    value: str
    rationale: str
    supporting_post_ids: tuple[str, ...]
    comparison_post_ids: tuple[str, ...]
    metric: str
    metric_definition: str
    window: str
    is_optional: bool = True


@dataclass(frozen=True)
class DistributionOutlook:
    assessment_id: str
    content_fingerprint: str
    decision_algorithm_version: str
    decision_config_version: str
    retrieval_version: str
    ranking_config_version: str
    retrieval_state: str
    retrieval_candidate_count: int
    retrieval_vector_candidate_count: int
    retrieval_eligible_count: int
    retrieval_excluded_count: int
    retrieval_truncated: bool
    retrieval_exclusions: tuple[CandidateExclusion, ...]
    retrieval_coverage_limitations: tuple[str, ...]
    baseline_version: str
    embedding_identity: str
    assessment_cutoff: datetime
    decision_state: DecisionState
    comparable_evidence: tuple[ComparableEvidence, ...]
    metrics: tuple[MetricEvidence, ...]
    observations: tuple[DecisionObservation, ...]
    suggestion: TestableSuggestion | None
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    exclusions: tuple[tuple[str, int], ...]

    def to_json(self) -> str:
        """Serialize the immutable result as stable JSON without raw provider payloads."""

        def encode(value: object) -> object:
            if isinstance(value, datetime):
                return value.isoformat()
            raise TypeError(f"unsupported JSON value: {type(value).__name__}")

        return json.dumps(asdict(self), default=encode, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class _MetricGroup:
    metric: str
    definition: str
    window: str
    records: tuple[OutcomeObservation, ...]
    baseline: CreatorBaseline
    coverage: float
    zero_weight_count: int
    limitations: tuple[str, ...]
    outlook: OutlookRange | None


def _profile_value(profile: PostProfile, variable: str) -> str | None:
    if variable == "declared_topic":
        return profile.declared_topic
    if variable == "declared_intent":
        return profile.declared_intent
    if variable == "content_format":
        return profile.content_format if profile.content_format != "unknown" else None
    if variable == "topology":
        return profile.topology
    if variable == "thread_role":
        return profile.thread_role
    return None


def _is_supported(baseline: CreatorBaseline, coverage: float, request: OutlookRequest) -> bool:
    return (
        request.comparable_set.algorithm_version == RETRIEVAL_ALGORITHM_VERSION
        and request.comparable_set.config_version == RANKING_CONFIG_VERSION
        and request.assessment.profile.version == PROFILE_VERSION
        and baseline.evidence_strength in ("High", "Moderate")
        and coverage >= request.config.minimum_metric_coverage
        and request.comparable_set.state == "matched"
        and not request.comparable_set.truncated
        and not request.comparable_set.coverage_limitations
        and baseline.statistics is not None
    )


def _metric_groups(request: OutlookRequest) -> tuple[_MetricGroup, ...]:
    relevance = {item.post_id: item.relevance for item in request.comparable_set.matches}
    comparable_ids = set(relevance)
    grouped: dict[tuple[str, str, str], list[OutcomeObservation]] = {}
    for outcome in request.outcomes:
        if outcome.post_id not in comparable_ids:
            continue
        grouped.setdefault((outcome.metric, outcome.metric_definition, outcome.window), []).append(
            outcome
        )

    results: list[_MetricGroup] = []
    for metric, definition, window in sorted(grouped):
        zero_weight_count = sum(
            relevance[item.post_id] <= 0 for item in grouped[(metric, definition, window)]
        )
        records = tuple(
            # Relevance is the only outcome weight. A common scale factor has no effect on
            # weighted quantiles or Kish effective sample size, so preserve retrieval scores.
            replace(item, weight=relevance[item.post_id])
            for item in grouped[(metric, definition, window)]
            if relevance[item.post_id] > 0
        )
        baseline = build_creator_baseline(
            records,
            BaselineRequest(
                creator_key=request.assessment.creator_key,
                metric=metric,
                metric_definition=definition,
                window=window,
                as_of=request.assessment.as_of,
            ),
        )
        coverage = (
            min(1.0, baseline.eligible_post_count / len(comparable_ids)) if comparable_ids else 0.0
        )
        limitations = list(baseline.reasons)
        if zero_weight_count:
            limitations.append(
                f"{zero_weight_count} outcome(s) belonged to zero-relevance comparables and were excluded from weighting."
            )
        if len(baseline.supporting_post_ids) < len(comparable_ids):
            limitations.append(
                f"Metric coverage is {coverage:.0%} across selected comparables; missing or excluded outcomes are not imputed."
            )
        if request.comparable_set.truncated:
            limitations.append(
                "Comparable retrieval was truncated; metric coverage may not represent full history."
            )
        if request.comparable_set.coverage_limitations:
            limitations.extend(request.comparable_set.coverage_limitations)
        if baseline.statistics is not None and _is_supported(baseline, coverage, request):
            stats = baseline.statistics
            outlook = OutlookRange(
                kind="historical_reference_p25_p75",
                lower_p25=stats.p25,
                median_p50=stats.p50,
                upper_p75=stats.p75,
                comparable_post_ids=baseline.supporting_post_ids,
                effective_sample_size=baseline.effective_sample_size,
            )
        else:
            outlook = None
            if (
                baseline.evidence_strength in ("High", "Moderate")
                and coverage < request.config.minimum_metric_coverage
            ):
                limitations.append(
                    f"Outlook withheld because coverage is below the configured {request.config.minimum_metric_coverage:.0%} minimum."
                )
            elif baseline.evidence_strength in ("High", "Moderate") and (
                request.comparable_set.truncated or request.comparable_set.coverage_limitations
            ):
                limitations.append(
                    "Outlook withheld because comparable retrieval coverage is incomplete."
                )
            elif (
                baseline.evidence_strength in ("High", "Moderate")
                and request.comparable_set.state != "matched"
            ):
                limitations.append(
                    "Outlook withheld because comparable retrieval did not reach its matched state."
                )
        results.append(
            _MetricGroup(
                metric,
                definition,
                window,
                records,
                baseline,
                coverage,
                zero_weight_count,
                tuple(dict.fromkeys(limitations)),
                outlook,
            )
        )
    return tuple(results)


def _raw_outlier_ids(group: _MetricGroup) -> tuple[str, ...]:
    baseline = group.baseline
    stats = baseline.statistics
    if stats is None or not baseline.supporting_post_ids:
        return ()
    eligible = set(baseline.supporting_post_ids)
    # Baseline support IDs already reflect creator, metric, window, cutoff, missing-value
    # and duplicate filtering. Use only those exact eligible records for the same fences.
    items = [item for item in group.records if item.post_id in eligible and item.value is not None]
    if not items:
        return ()
    p25 = weighted_quantile(
        [item.value for item in items if item.value is not None],
        [item.weight for item in items if item.value is not None],
        0.25,
    )
    p75 = weighted_quantile(
        [item.value for item in items if item.value is not None],
        [item.weight for item in items if item.value is not None],
        0.75,
    )
    iqr = p75 - p25
    lower, upper = p25 - 3 * iqr, p75 + 3 * iqr
    return tuple(
        sorted(
            item.post_id
            for item in items
            if item.value is not None and (item.value < lower or item.value > upper)
        )
    )


def _observations(groups: tuple[_MetricGroup, ...]) -> tuple[DecisionObservation, ...]:
    candidates = [
        group
        for group in groups
        if group.baseline.statistics is not None
        and group.baseline.evidence_strength != "Insufficient"
    ]
    candidates.sort(
        key=lambda group: (
            {"High": 0, "Moderate": 1, "Low": 2, "Insufficient": 3}[
                group.baseline.evidence_strength
            ],
            -group.baseline.effective_sample_size,
            group.metric,
            group.definition,
            group.window,
        )
    )
    output: list[DecisionObservation] = []
    if candidates:
        group = candidates[0]
        stats = group.baseline.statistics
        assert stats is not None
        strength_prefix = (
            "Low-strength descriptive evidence"
            if group.baseline.evidence_strength == "Low"
            else "Historical evidence"
        )
        explanation = (
            f"{strength_prefix}: {group.baseline.eligible_post_count} selected comparable posts had a "
            f"weighted median of {stats.p50:g} {group.metric} in the {group.window} window; "
            f"{stats.consistency_ratio:.0%} fell within the robust 3×IQR fences. This describes "
            "historical outcomes and does not establish why they occurred."
        )
        output.append(
            DecisionObservation(
                kind="repeatability",
                explanation=explanation,
                supporting_post_ids=group.baseline.supporting_post_ids,
                metric=group.metric,
                metric_definition=group.definition,
                window=group.window,
                evidence_strength=group.baseline.evidence_strength,
                evidence_statistics=stats,
                limitations=group.limitations,
            )
        )
        outliers = _raw_outlier_ids(group)
        if outliers and len(output) < 2:
            output.append(
                DecisionObservation(
                    kind="outlier",
                    explanation=(
                        f"{len(outliers)} selected historical post(s) fall beyond the robust 3×IQR "
                        f"fences for {group.metric} in the {group.window} window; this is an "
                        "exceptional observed result, not evidence of a repeatable outcome."
                    ),
                    supporting_post_ids=outliers,
                    metric=group.metric,
                    metric_definition=group.definition,
                    window=group.window,
                    evidence_strength=group.baseline.evidence_strength,
                    evidence_statistics=group.baseline.statistics,
                    limitations=("Outlier status is descriptive and does not identify its cause.",),
                )
            )
        if (
            not outliers
            and len(output) < 2
            and (group.baseline.evidence_strength in ("Low", "Insufficient") or group.coverage < 1)
        ):
            limitation = (
                group.limitations[-1] if group.limitations else "Metric support is incomplete."
            )
            output.append(
                DecisionObservation(
                    kind="coverage_limitation",
                    explanation=limitation,
                    supporting_post_ids=group.baseline.supporting_post_ids,
                    metric=group.metric,
                    metric_definition=group.definition,
                    window=group.window,
                    evidence_strength=group.baseline.evidence_strength,
                    evidence_statistics=group.baseline.statistics,
                    limitations=group.limitations,
                )
            )
    elif groups:
        group = groups[0]
        output.append(
            DecisionObservation(
                kind="coverage_limitation",
                explanation=group.limitations[0]
                if group.limitations
                else "No eligible metric outcomes support an interpretation.",
                supporting_post_ids=group.baseline.supporting_post_ids,
                metric=group.metric,
                metric_definition=group.definition,
                window=group.window,
                evidence_strength="Insufficient",
                evidence_statistics=group.baseline.statistics,
                limitations=group.limitations,
            )
        )
    return tuple(output[:2])


def _suggestion(
    request: OutlookRequest, groups: tuple[_MetricGroup, ...]
) -> TestableSuggestion | None:
    if (
        request.comparable_set.algorithm_version != RETRIEVAL_ALGORITHM_VERSION
        or request.comparable_set.config_version != RANKING_CONFIG_VERSION
        or request.assessment.profile.version != PROFILE_VERSION
        or request.comparable_set.state != "matched"
        or request.comparable_set.truncated
        or request.comparable_set.coverage_limitations
    ):
        return None
    profiles = dict(request.comparable_profiles)
    profiles = {
        post_id: profile
        for post_id, profile in profiles.items()
        if profile.version == PROFILE_VERSION
    }
    draft_profile = request.assessment.profile
    relevance = {item.post_id: item.relevance for item in request.comparable_set.matches}
    variables = ("declared_topic", "declared_intent", "content_format", "topology", "thread_role")
    for group in groups:
        baseline = group.baseline
        if group.outlook is None or baseline.evidence_strength not in ("High", "Moderate"):
            continue
        supported_ids = set(baseline.supporting_post_ids)
        observed = {
            item.post_id: item
            for item in group.records
            if item.post_id in supported_ids and item.value is not None
        }
        for variable in variables:
            proposed_value = _profile_value(draft_profile, variable)
            if proposed_value is None:
                continue
            matching = sorted(
                post_id
                for post_id in supported_ids
                if post_id in profiles
                and _profile_value(profiles[post_id], variable) == proposed_value
            )
            comparison = sorted(
                post_id
                for post_id in supported_ids
                if post_id in profiles
                and _profile_value(profiles[post_id], variable) is not None
                and _profile_value(profiles[post_id], variable) != proposed_value
            )
            matching_records = [observed[post_id] for post_id in matching if post_id in observed]
            comparison_records = [
                observed[post_id] for post_id in comparison if post_id in observed
            ]
            if len(matching_records) < 3 or len(comparison_records) < 3:
                continue
            match_weights = [relevance[item.post_id] for item in matching_records]
            comparison_weights = [relevance[item.post_id] for item in comparison_records]
            if (
                sum(match_weights) ** 2 / sum(weight * weight for weight in match_weights)
                < request.config.minimum_experiment_group_effective_sample
                or sum(comparison_weights) ** 2
                / sum(weight * weight for weight in comparison_weights)
                < request.config.minimum_experiment_group_effective_sample
            ):
                continue
            match_median = weighted_quantile(
                [item.value for item in matching_records if item.value is not None],
                match_weights,
                0.5,
            )
            comparison_median = weighted_quantile(
                [item.value for item in comparison_records if item.value is not None],
                comparison_weights,
                0.5,
            )
            if math.isclose(match_median, comparison_median, rel_tol=1e-12, abs_tol=1e-12):
                continue
            return TestableSuggestion(
                kind="experiment_hypothesis",
                label="Optional experiment",
                variable=variable,
                value=proposed_value,
                rationale=(
                    f"Among selected comparable posts, the {variable} group '{proposed_value}' had a "
                    f"weighted median of {match_median:g} {group.metric}; comparables with another "
                    f"known value had {comparison_median:g}. You may optionally test this approach "
                    f"and compare {group.metric} in the same {group.window} window. This observed "
                    "association does not show that the feature caused the outcome."
                ),
                supporting_post_ids=tuple(item.post_id for item in matching_records),
                comparison_post_ids=tuple(item.post_id for item in comparison_records),
                metric=group.metric,
                metric_definition=group.definition,
                window=group.window,
            )
    return None


def build_distribution_outlook(request: OutlookRequest) -> DistributionOutlook:
    """Assemble a deterministic draft decision without changing upstream retrieval evidence."""
    matches = request.comparable_set.matches
    comparable_evidence = tuple(
        ComparableEvidence(
            item.post_id,
            item.relevance,
            item.components,
            index,
            item.inclusion_reasons,
        )
        for index, item in enumerate(matches, start=1)
    )
    groups = _metric_groups(request)
    supported_retrieval_version = (
        request.comparable_set.algorithm_version == RETRIEVAL_ALGORITHM_VERSION
        and request.comparable_set.config_version == RANKING_CONFIG_VERSION
        and request.assessment.profile.version == PROFILE_VERSION
    )
    metric_evidence = tuple(
        MetricEvidence(
            metric=group.metric,
            metric_definition=group.definition,
            window=group.window,
            evidence_strength=group.baseline.evidence_strength,
            coverage=group.coverage,
            eligible_post_count=group.baseline.eligible_post_count,
            effective_sample_size=group.baseline.effective_sample_size,
            supporting_post_ids=group.baseline.supporting_post_ids,
            statistics=group.baseline.statistics,
            exclusion_counts=tuple(
                sorted(
                    {
                        **dict(group.baseline.exclusion_counts),
                        **(
                            {"zero_relevance_outcomes": group.zero_weight_count}
                            if group.zero_weight_count
                            else {}
                        ),
                    }.items()
                )
            ),
            limitations=group.limitations,
            outlook=group.outlook,
        )
        for group in groups
    )
    sufficiently_supported = any(group.outlook is not None for group in groups)
    limitations = list(request.comparable_set.coverage_limitations)
    if request.comparable_set.state != "matched":
        limitations.append(
            "Comparable retrieval did not reach the matched state; numeric Distribution Outlooks are withheld."
        )
    if not supported_retrieval_version:
        limitations.append(
            "Retrieval or profile version is unknown to this decision engine; draft-specific interpretations are withheld."
        )
    if not sufficiently_supported and matches:
        limitations.append(
            "Historical evidence does not meet the configured support and coverage requirements for an outlook range."
        )
    if matches and not request.outcomes:
        limitations.append(
            "No outcome observations were supplied for the selected comparables; outlook ranges and personalized guidance are withheld."
        )
    match_ids = {match.post_id for match in matches}
    outside = sum(item.post_id not in match_ids for item in request.outcomes)
    zero_relevance = sum(item.relevance <= 0 for item in matches)
    exclusions = tuple(
        (name, count)
        for name, count in sorted(
            {
                **({"outcomes_for_non_comparable_post": outside} if outside else {}),
                **({"zero_relevance_comparables": zero_relevance} if zero_relevance else {}),
            }.items()
        )
    )
    assumptions = (
        "Retrieval relevance is computed from descriptive draft and post features before outcomes are read.",
        "Positive comparable relevance is used as the outcome weight; outcomes cannot change comparable ordering or relevance.",
        "A suggestion requires the assessed feature and at least 3 effective measured posts in each of its comparison groups; unequal historical medians only justify a test question, not a causal claim.",
        "Metric values retain their supplied units and are grouped only by exact metric definition and observation window.",
        "The P25–P75 values are historical reference quantiles, not calibrated prediction intervals or guaranteed future results.",
    )
    return DistributionOutlook(
        assessment_id=request.assessment.assessment_id,
        content_fingerprint=request.content_fingerprint,
        decision_algorithm_version=request.config.algorithm_version,
        decision_config_version=request.config.config_version,
        retrieval_version=request.comparable_set.algorithm_version,
        ranking_config_version=request.comparable_set.config_version,
        retrieval_state=request.comparable_set.state,
        retrieval_candidate_count=request.comparable_set.candidate_count,
        retrieval_vector_candidate_count=request.comparable_set.vector_candidate_count,
        retrieval_eligible_count=request.comparable_set.eligible_count,
        retrieval_excluded_count=request.comparable_set.excluded_count,
        retrieval_truncated=request.comparable_set.truncated,
        retrieval_exclusions=request.comparable_set.exclusions,
        retrieval_coverage_limitations=request.comparable_set.coverage_limitations,
        baseline_version=BASELINE_VERSION,
        embedding_identity=request.comparable_set.embedding_identity.index_key,
        assessment_cutoff=request.assessment.as_of,
        decision_state="supported" if sufficiently_supported else "insufficient_evidence",
        comparable_evidence=comparable_evidence,
        metrics=metric_evidence,
        observations=_observations(groups) if supported_retrieval_version else (),
        suggestion=_suggestion(request, groups),
        assumptions=assumptions,
        limitations=tuple(dict.fromkeys(limitations)),
        exclusions=exclusions,
    )
