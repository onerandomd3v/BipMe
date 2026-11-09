"""Conservative, no-draft Creator Intelligence Report assembled from approved evidence.

The caller supplies already validated, permissioned evidence. This pure service
never fetches X data, calls an LLM, ranks creators, or predicts exposure.
"""

from __future__ import annotations

import json
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
)
from bipme.intelligence.content_patterns import (
    ContentPatternContrast,
    PersonalPostProfile,
    compare_personal_content_patterns,
)
from bipme.intelligence.creator_goals import CreatorOutcome
from bipme.intelligence.post_profiles import PROFILE_VERSION
from bipme.intelligence.report_evidence import (
    NICHE_FRESHNESS_DAYS,
    REPORT_EVIDENCE_VERSION,
    CreatorReportEvidenceBundle,
    ReportEvidence,
    ReportSource,
    niche_evidence_freshness,
)

REPORT_ALGORITHM_VERSION = "creator-intelligence-report-v2"
SectionName = Literal["personal_history", "niche_observations", "limitations"]
ReportState = Literal["personal_and_niche", "personal_only_partial", "insufficient_evidence"]
Freshness = Literal["current", "stale", "historical", "unknown"]
OpportunityKind = Literal["personal_pattern", "niche_intersection", "niche_gap"]


@dataclass(frozen=True)
class ReportFinding:
    section: SectionName
    summary: str
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    supporting_post_ids: tuple[str, ...]
    evidence_strength: EvidenceStrength
    limitations: tuple[str, ...]
    kind: Literal["observation", "inference", "hypothesis", "unknown"]
    freshness: Freshness = "unknown"
    observed_at: datetime | None = None
    published_at: datetime | None = None
    source_versions: tuple[tuple[str, str], ...] = ()
    metric: str | None = None
    metric_definition: str | None = None
    metric_window: str | None = None
    eligible_observation_count: int | None = None
    effective_sample_size: float | None = None
    baseline_statistics: BaselineStatistics | None = None
    outlier_post_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportExperiment:
    """Optional hypothesis, not a recommendation backed by causal analysis."""

    goal: str
    hypothesis: str
    evidence_ids: tuple[str, ...]
    supporting_post_ids: tuple[str, ...]
    metric: str
    metric_definition: str
    metric_window: str
    limitations: tuple[str, ...]
    opportunity_kind: OpportunityKind = "personal_pattern"
    evidence_strength: EvidenceStrength = "Low"
    feature: str | None = None
    feature_value: str | None = None
    personal_evidence_ids: tuple[str, ...] = ()
    personal_source_ids: tuple[str, ...] = ()
    personal_supporting_post_ids: tuple[str, ...] = ()
    niche_evidence_ids: tuple[str, ...] = ()
    niche_source_ids: tuple[str, ...] = ()
    niche_supporting_post_ids: tuple[str, ...] = ()
    freshness: Freshness = "historical"


@dataclass(frozen=True)
class ReportOpportunity:
    """A source-separated intersection or a precisely bounded exploratory gap."""

    kind: OpportunityKind
    summary: str
    evidence_strength: EvidenceStrength
    personal_evidence_ids: tuple[str, ...]
    personal_source_ids: tuple[str, ...]
    personal_post_ids: tuple[str, ...]
    niche_evidence_ids: tuple[str, ...]
    niche_source_ids: tuple[str, ...]
    niche_post_ids: tuple[str, ...]
    personal_source_versions: tuple[tuple[str, str], ...]
    niche_source_versions: tuple[tuple[str, str], ...]
    metric: str | None
    metric_definition: str | None
    metric_window: str | None
    freshness: Freshness
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class PersonalMetricCohort:
    """Exact-window, creator-only descriptive strong/typical/weak comparison."""

    metric: str
    metric_definition: str
    window: str
    evidence_strength: EvidenceStrength
    strong_post_ids: tuple[str, ...]
    typical_post_ids: tuple[str, ...]
    weak_post_ids: tuple[str, ...]
    excluded_count: int
    limitations: tuple[str, ...]
    exclusion_counts: tuple[tuple[str, int], ...] = ()
    eligible_post_ids: tuple[str, ...] = ()
    effective_sample_size: float = 0.0
    statistics: BaselineStatistics | None = None
    outlier_post_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    source_versions: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class CreatorIntelligenceReport:
    version: str
    evidence_version: str
    baseline_version: str
    creator_key: str
    as_of: datetime
    state: ReportState
    personal_findings: tuple[ReportFinding, ...]
    niche_findings: tuple[ReportFinding, ...]
    experiments: tuple[ReportExperiment, ...]
    opportunities: tuple[ReportOpportunity, ...]
    personal_cohorts: tuple[PersonalMetricCohort, ...]
    content_patterns: tuple[ContentPatternContrast, ...]
    limitations: tuple[str, ...]
    synthesis_mode: Literal["deterministic_fallback"] = "deterministic_fallback"

    def to_json(self) -> str:
        """Serialize the immutable report with stable key and tuple ordering."""
        return json.dumps(
            asdict(self),
            default=lambda value: (
                value.isoformat() if isinstance(value, datetime) else _unsupported(value)
            ),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )


def _unsupported(value: object) -> object:
    """Reject values outside the report's JSON-compatible data contract."""
    raise TypeError(f"unsupported value: {type(value).__name__}")


def _finding(
    record: ReportEvidence,
    *,
    strength: EvidenceStrength,
    limits: tuple[str, ...],
    sources: dict[str, ReportSource],
    freshness: Freshness,
) -> ReportFinding:
    """Create a report finding while retaining source versions and provenance."""
    source_versions = tuple(
        sorted((source_id, sources[source_id].source_version) for source_id in record.source_ids)
    )
    return ReportFinding(
        section="personal_history" if record.pool == "personal" else "niche_observations",
        summary=record.statement,
        evidence_ids=(record.evidence_id,),
        source_ids=record.source_ids,
        supporting_post_ids=record.post_ids,
        evidence_strength=strength,
        limitations=tuple(dict.fromkeys((*record.limitations, *limits))),
        kind=record.kind,
        freshness=freshness,
        observed_at=record.observed_at,
        published_at=record.published_at,
        source_versions=source_versions,
        metric=record.metric,
        metric_definition=record.metric_definition,
        metric_window=record.metric_window,
    )


def _authorized_sources(bundle: CreatorReportEvidenceBundle) -> dict[str, ReportSource]:
    """Return only permission attestations available by the report cutoff."""
    return {
        source.source_id: source
        for source in (*bundle.personal_sources, *bundle.niche_sources)
        if source.authorization_verified
    }


def _authorized_evidence(
    records: tuple[ReportEvidence, ...], sources: dict[str, ReportSource]
) -> tuple[ReportEvidence, ...]:
    """Keep claims whose complete source set passed authorization gating."""
    return tuple(
        record for record in records if all(source_id in sources for source_id in record.source_ids)
    )


def _eligible_outcomes(
    bundle: CreatorReportEvidenceBundle,
    outcomes: tuple[OutcomeObservation, ...],
    personal_evidence: tuple[ReportEvidence, ...],
) -> tuple[OutcomeObservation, ...]:
    """Cut off future and unprovenanced observations before definition discovery."""
    evidenced: set[tuple[str, str, str, str]] = {
        (item.metric, item.metric_definition, item.metric_window, post_id)
        for item in personal_evidence
        if item.kind == "observation"
        and item.metric is not None
        and item.metric_definition is not None
        and item.metric_window is not None
        for post_id in item.post_ids
    }
    return tuple(
        item
        for item in outcomes
        if item.creator_key == bundle.creator_key
        and item.published_at <= bundle.as_of
        and item.published_at <= item.observed_at <= bundle.as_of
        and (item.metric, item.metric_definition, item.window, item.post_id) in evidenced
    )


def _verified_baselines(
    bundle: CreatorReportEvidenceBundle,
    baselines: tuple[CreatorBaseline, ...],
    outcomes: tuple[OutcomeObservation, ...],
    all_outcomes: tuple[OutcomeObservation, ...],
    personal_evidence: tuple[ReportEvidence, ...],
) -> tuple[tuple[CreatorBaseline, str], ...]:
    """Reconcile baseline provenance with exact-definition eligible data.

    The v1 CreatorBaseline contract does not store metric_definition. Fail
    closed unless it can be reproduced from one definition and the *same*
    eligible post set, sample strength and thresholds. Segmented or shrunk
    baselines remain unavailable until their provenance can be reproduced.
    """
    verified: list[tuple[CreatorBaseline, str]] = []
    for baseline in baselines:
        supported = set(baseline.supporting_post_ids)
        supporting_matches = tuple(
            item
            for item in outcomes
            if item.metric == baseline.metric
            and item.window == baseline.window
            and item.post_id in supported
        )
        definitions = {item.metric_definition for item in supporting_matches}
        if len(definitions) != 1 or not supporting_matches:
            continue
        definition = next(iter(definitions))
        matches = tuple(
            item
            for item in outcomes
            if item.metric == baseline.metric
            and item.window == baseline.window
            and item.metric_definition == definition
        )
        candidate = build_creator_baseline(
            matches,
            BaselineRequest(
                creator_key=bundle.creator_key,
                metric=baseline.metric,
                metric_definition=definition,
                window=baseline.window,
                as_of=bundle.as_of,
            ),
        )
        evidenced_post_ids = {
            post_id
            for item in personal_evidence
            if item.kind == "observation"
            and item.metric == baseline.metric
            and item.metric_definition == definition
            and item.metric_window == baseline.window
            for post_id in item.post_ids
        }
        # Recompute exclusion metadata from the full input, restricted to the
        # same permissioned evidence IDs and exact metric identity. The report
        # statistics still come only from `matches`, which are eligible at the
        # assessment cutoff. This retains visible reasons for evidence-backed
        # rows filtered before replay (such as a future snapshot or owner key).
        evidenced_inputs = tuple(
            item
            for item in all_outcomes
            if item.metric == baseline.metric
            and item.metric_definition == definition
            and item.window == baseline.window
            and item.post_id in evidenced_post_ids
        )
        diagnostic = build_creator_baseline(
            evidenced_inputs,
            BaselineRequest(
                creator_key=bundle.creator_key,
                metric=baseline.metric,
                metric_definition=definition,
                window=baseline.window,
                as_of=bundle.as_of,
            ),
        )
        if (
            candidate.supporting_post_ids != baseline.supporting_post_ids
            or candidate.evidence_strength != baseline.evidence_strength
            or candidate.effective_sample_size != baseline.effective_sample_size
            or candidate.statistics != baseline.statistics
        ):
            continue
        # Keep statistics from eligible rows but retain separately recomputed,
        # permission-scoped exclusions from the full source input.
        verified.append(
            (replace(candidate, exclusion_counts=diagnostic.exclusion_counts), definition)
        )
    return tuple(verified)


def _personal_metric_cohorts(
    bundle: CreatorReportEvidenceBundle,
    baselines: tuple[CreatorBaseline, ...],
    observations: tuple[OutcomeObservation, ...],
    definitions_by_dimension: dict[tuple[str, str], str],
    personal_evidence: tuple[ReportEvidence, ...],
    sources: dict[str, ReportSource],
) -> tuple[PersonalMetricCohort, ...]:
    """Segment eligible, unique, same-creator measured outcomes; never cross niche pools.

    Quantile cut points come from the existing COD-353 baseline, not invented
    scores. Unknown/misaligned/future records are excluded rather than imputed.
    """
    cohorts: list[PersonalMetricCohort] = []
    for baseline in baselines:
        if baseline.statistics is None or baseline.evidence_strength == "Insufficient":
            continue
        definition = definitions_by_dimension.get((baseline.metric, baseline.window))
        if definition is None:
            continue
        allowed = set(baseline.supporting_post_ids)
        eligible: dict[str, OutcomeObservation] = {}
        duplicates: set[str] = set()
        excluded = 0
        for record in observations:
            if record.metric != baseline.metric or record.window != baseline.window:
                continue
            if record.metric_definition != definition:
                excluded += 1
                continue
            if (
                record.creator_key != bundle.creator_key
                or record.post_id not in allowed
                or record.published_at > bundle.as_of
                or record.observed_at > bundle.as_of
                or record.observed_at < record.published_at
                or record.value is None
                or record.value < 0
            ):
                excluded += 1
                continue
            if record.post_id in eligible:
                duplicates.add(record.post_id)
                excluded += 1
            else:
                eligible[record.post_id] = record
        for post_id in duplicates:
            del eligible[post_id]
            excluded += 1
        if len(eligible) < 3:
            continue
        stats = baseline.statistics
        low, high = stats.p25, stats.p75
        strong = tuple(
            sorted(
                id
                for id, record in eligible.items()
                if record.value is not None and record.value > high
            )
        )
        weak = tuple(
            sorted(
                id
                for id, record in eligible.items()
                if record.value is not None and record.value < low
            )
        )
        typical = tuple(
            sorted(
                id
                for id, record in eligible.items()
                if record.value is not None and low <= record.value <= high
            )
        )
        eligible_ids = tuple(sorted(eligible))
        support_records = tuple(
            item
            for item in personal_evidence
            if item.kind == "observation"
            and item.metric == baseline.metric
            and item.metric_definition == definition
            and item.metric_window == baseline.window
            and set(item.post_ids).intersection(eligible_ids)
        )
        evidenced_ids = {
            post_id
            for item in support_records
            for post_id in item.post_ids
            if post_id in eligible_ids
        }
        if not eligible_ids or not set(eligible_ids).issubset(evidenced_ids):
            continue
        evidence_ids = tuple(sorted(item.evidence_id for item in support_records))
        source_ids = tuple(
            sorted({source_id for item in support_records for source_id in item.source_ids})
        )
        lower_fence = stats.p25 - 3 * stats.iqr
        upper_fence = stats.p75 + 3 * stats.iqr
        outlier_ids = tuple(
            sorted(
                post_id
                for post_id, record in eligible.items()
                if record.value is not None
                and (record.value < lower_fence or record.value > upper_fence)
            )
        )
        limits = [
            "Groups describe historical metric distributions, not content causes or expected lift.",
            "Quartile boundaries use the existing creator baseline, not niche data.",
            "Strong/weak cohorts are selected by observed outcomes; content associations are subject to selection bias.",
        ]
        if excluded:
            limits.append(f"{excluded} incompatible or duplicate observation(s) excluded.")
        if baseline.exclusion_counts:
            limits.extend(
                f"Baseline excluded {count} observation(s): {reason}."
                for reason, count in baseline.exclusion_counts
            )
        if outlier_ids:
            limits.append("Baseline includes outliers; group interpretation is sensitive.")
        cohorts.append(
            PersonalMetricCohort(
                metric=baseline.metric,
                metric_definition=definition,
                window=baseline.window,
                evidence_strength=baseline.evidence_strength,
                strong_post_ids=strong,
                typical_post_ids=typical,
                weak_post_ids=weak,
                excluded_count=excluded,
                limitations=tuple(limits),
                eligible_post_ids=eligible_ids,
                effective_sample_size=baseline.effective_sample_size,
                statistics=stats,
                outlier_post_ids=outlier_ids,
                exclusion_counts=baseline.exclusion_counts,
                evidence_ids=evidence_ids,
                source_ids=source_ids,
                source_versions=tuple(
                    sorted(
                        (source_id, sources[source_id].source_version) for source_id in source_ids
                    )
                ),
            )
        )
    return tuple(cohorts)


def _cohort_findings(
    cohorts: tuple[PersonalMetricCohort, ...],
    observations: tuple[OutcomeObservation, ...],
    sources: dict[str, ReportSource],
) -> tuple[ReportFinding, ...]:
    """Summarize verified metric cohorts with their exact denominators and IDs."""
    findings: list[ReportFinding] = []
    for cohort in cohorts:
        statistics = cohort.statistics
        if statistics is None:
            continue
        count = len(cohort.eligible_post_ids)
        observed_at = max(
            (
                item.observed_at
                for item in observations
                if item.post_id in cohort.eligible_post_ids
                and item.metric == cohort.metric
                and item.metric_definition == cohort.metric_definition
                and item.window == cohort.window
            ),
            default=None,
        )
        summary = (
            f"For {cohort.metric} ({cohort.metric_definition}; {cohort.window}), "
            f"{len(cohort.strong_post_ids)} of {count} eligible posts were above P75, "
            f"{len(cohort.typical_post_ids)} were within P25–P75, and "
            f"{len(cohort.weak_post_ids)} were below P25. The creator-relative P50 was "
            f"{statistics.p50:g}; IQR was {statistics.iqr:g}; "
            f"{len(cohort.outlier_post_ids)} eligible post(s) crossed the robust outlier fences."
        )
        findings.append(
            ReportFinding(
                section="personal_history",
                summary=summary,
                evidence_ids=cohort.evidence_ids,
                source_ids=cohort.source_ids,
                supporting_post_ids=cohort.eligible_post_ids,
                evidence_strength=cohort.evidence_strength,
                limitations=cohort.limitations,
                kind="observation",
                freshness="historical",
                observed_at=observed_at,
                source_versions=cohort.source_versions,
                metric=cohort.metric,
                metric_definition=cohort.metric_definition,
                metric_window=cohort.window,
                eligible_observation_count=count,
                effective_sample_size=cohort.effective_sample_size,
                baseline_statistics=statistics,
                outlier_post_ids=cohort.outlier_post_ids,
            )
        )
    return tuple(findings)


def _pattern_findings(
    patterns: tuple[ContentPatternContrast, ...],
    cohorts: tuple[PersonalMetricCohort, ...],
) -> tuple[ReportFinding, ...]:
    """Render content contrasts as bounded historical associations."""
    findings: list[ReportFinding] = []
    cohort_by_dimension = {
        (cohort.metric, cohort.metric_definition, cohort.window): cohort for cohort in cohorts
    }
    for pattern in patterns:
        cohort = cohort_by_dimension.get(
            (pattern.metric, pattern.metric_definition, pattern.window)
        )
        if cohort is None:
            continue
        summary = (
            f"{pattern.feature}={pattern.feature_value} appeared in "
            f"{pattern.strong_count}/{pattern.strong_total} stronger posts and "
            f"{pattern.weak_count}/{pattern.weak_total} weaker posts for "
            f"{pattern.metric} ({pattern.metric_definition}; {pattern.window})."
        )
        findings.append(
            ReportFinding(
                section="personal_history",
                summary=summary,
                evidence_ids=cohort.evidence_ids,
                source_ids=cohort.source_ids,
                supporting_post_ids=tuple(
                    sorted(set(pattern.strong_group_post_ids + pattern.weak_group_post_ids))
                ),
                evidence_strength=cohort.evidence_strength,
                limitations=tuple(dict.fromkeys((*pattern.limitations, *cohort.limitations))),
                kind="inference",
                freshness="historical",
                source_versions=cohort.source_versions,
                metric=cohort.metric,
                metric_definition=cohort.metric_definition,
                metric_window=cohort.window,
                eligible_observation_count=len(
                    set(pattern.strong_group_post_ids + pattern.weak_group_post_ids)
                ),
                effective_sample_size=cohort.effective_sample_size,
                baseline_statistics=cohort.statistics,
                outlier_post_ids=tuple(
                    post_id
                    for post_id in cohort.outlier_post_ids
                    if post_id in pattern.strong_group_post_ids + pattern.weak_group_post_ids
                ),
            )
        )
    return tuple(findings)


def _profile_feature_value(profile: PersonalPostProfile, descriptor: str) -> str | None:
    """Read a supported creator descriptor, preserving unknown as missing."""
    value = {
        "topic": profile.profile.declared_topic,
        "content_format": (
            None if profile.profile.content_format == "unknown" else profile.profile.content_format
        ),
        "intent": profile.profile.declared_intent,
    }[descriptor]
    return value.casefold() if value is not None else None


def _complete_personal_feature_coverage(
    cohort: PersonalMetricCohort,
    descriptor: str,
    profiles: tuple[PersonalPostProfile, ...],
    creator_key: str,
    as_of: datetime,
) -> dict[str, str] | None:
    """Return complete supported profile metadata for every eligible post."""
    relevant = tuple(record for record in profiles if record.post_id in cohort.eligible_post_ids)
    if len(relevant) != len(cohort.eligible_post_ids):
        return None
    values: dict[str, str] = {}
    for record in relevant:
        profile = record.profile
        if (
            profile.creator_key != creator_key
            or profile.version != PROFILE_VERSION
            or profile.features_as_of > as_of
            or profile.input_observed_at > as_of
            or record.post_id in values
        ):
            return None
        try:
            value = _profile_feature_value(record, descriptor)
        except ValueError:
            return None
        if value is None:
            return None
        values[record.post_id] = value
    return values


def _fresh_niche_evidence(
    bundle: CreatorReportEvidenceBundle,
    niche_evidence: tuple[ReportEvidence, ...],
    all_sources: dict[str, ReportSource],
) -> tuple[tuple[ReportEvidence, ...], int, int, int]:
    """Return only current, permission-verified niche records plus exclusion counts."""
    current: list[ReportEvidence] = []
    unverified = stale = unknown_time = 0
    for item in niche_evidence:
        freshness = niche_evidence_freshness(bundle.as_of, item, all_sources)
        if freshness == "not_observation":
            continue
        if freshness == "unverified":
            unverified += 1
            continue
        if freshness == "unknown_time":
            unknown_time += 1
            continue
        if freshness == "stale":
            stale += 1
            continue
        current.append(item)
    return tuple(current), unverified, stale, unknown_time


def _one_evidence_covers_pattern(
    pattern: ContentPatternContrast,
    personal_evidence: tuple[ReportEvidence, ...],
    baseline_by_dimension: dict[tuple[str, str], tuple[CreatorBaseline, str]],
    personal_findings: tuple[ReportFinding, ...],
) -> ReportEvidence | None:
    """Find one strong claim that covers a full verified comparison denominator."""
    required = set(pattern.strong_group_post_ids + pattern.weak_group_post_ids)
    verified = baseline_by_dimension.get((pattern.metric, pattern.window))
    if verified is None or verified[1] != pattern.metric_definition:
        return None
    supported = set(verified[0].supporting_post_ids)
    return next(
        (
            item
            for item in personal_evidence
            if item.kind == "observation"
            and item.metric == pattern.metric
            and item.metric_definition == pattern.metric_definition
            and item.metric_window == pattern.window
            and required.issubset(item.post_ids)
            and set(item.post_ids).issubset(supported)
            and any(
                finding.evidence_ids == (item.evidence_id,)
                and finding.evidence_strength in ("High", "Moderate")
                for finding in personal_findings
            )
        ),
        None,
    )


def _niche_opportunities(
    bundle: CreatorReportEvidenceBundle,
    cohorts: tuple[PersonalMetricCohort, ...],
    patterns: tuple[ContentPatternContrast, ...],
    profiles: tuple[PersonalPostProfile, ...],
    niche_evidence: tuple[ReportEvidence, ...],
    sources: dict[str, ReportSource],
    baseline_by_dimension: dict[tuple[str, str], tuple[CreatorBaseline, str]],
    personal_findings: tuple[ReportFinding, ...],
) -> tuple[tuple[ReportOpportunity, ...], tuple[ReportExperiment, ...]]:
    """Join explicit recent niche descriptors to personal evidence without pooling metrics."""
    personal_feature = {
        "declared_topic": "topic",
        "content_format": "content_format",
        "declared_intent": "intent",
    }
    metric_goals = {
        "replies": "conversation",
        "impressions": "reach",
        "profile_clicks": "qualified_interest",
        "link_clicks": "qualified_interest",
    }
    groups: dict[tuple[str, str], list[ReportEvidence]] = {}
    for item in niche_evidence:
        if item.descriptor_name is None or item.descriptor_value is None or len(item.post_ids) != 1:
            continue
        key = (item.descriptor_name, item.descriptor_value.casefold())
        groups.setdefault(key, []).append(item)

    opportunities: list[ReportOpportunity] = []
    experiments: list[ReportExperiment] = []
    for (descriptor, value), records in sorted(groups.items()):
        post_ids = tuple(sorted({post_id for item in records for post_id in item.post_ids}))
        if len(post_ids) < 2:
            continue
        evidence_ids = tuple(sorted(item.evidence_id for item in records))
        source_ids = tuple(sorted({source_id for item in records for source_id in item.source_ids}))
        source_versions = tuple(
            sorted((source_id, sources[source_id].source_version) for source_id in source_ids)
        )
        mapped_pattern_name = next(
            (
                feature
                for feature, niche_descriptor in personal_feature.items()
                if niche_descriptor == descriptor
            ),
            None,
        )
        selected: (
            tuple[
                CreatorOutcome,
                PersonalMetricCohort,
                ContentPatternContrast | None,
                dict[str, str] | None,
            ]
            | None
        ) = None
        for goal in bundle.goals.priority_outcomes:
            for candidate in cohorts:
                if metric_goals.get(
                    candidate.metric
                ) != goal or candidate.evidence_strength not in ("High", "Moderate"):
                    continue
                matching_pattern = next(
                    (
                        pattern
                        for pattern in patterns
                        if pattern.metric == candidate.metric
                        and pattern.metric_definition == candidate.metric_definition
                        and pattern.window == candidate.window
                        and pattern.feature == mapped_pattern_name
                        and pattern.feature_value.casefold() == value
                        and pattern.strong_count >= 3
                        and pattern.strong_count * pattern.weak_total
                        > pattern.weak_count * pattern.strong_total
                    ),
                    None,
                )
                if matching_pattern is not None:
                    selected = (goal, candidate, matching_pattern, None)
                    break
                coverage = (
                    _complete_personal_feature_coverage(
                        candidate, descriptor, profiles, bundle.creator_key, bundle.as_of
                    )
                    if mapped_pattern_name is not None
                    else None
                )
                if coverage is not None and all(
                    feature_value != value for feature_value in coverage.values()
                ):
                    selected = (goal, candidate, None, coverage)
                    break
            if selected is not None:
                break
        if selected is None:
            continue
        goal, cohort, matching_pattern, coverage = selected
        kind: OpportunityKind
        personal_post_ids: tuple[str, ...]
        personal_limitations: tuple[str, ...]
        if matching_pattern is not None:
            kind = "niche_intersection"
            personal_post_ids = tuple(
                sorted(
                    set(
                        matching_pattern.strong_group_post_ids
                        + matching_pattern.weak_group_post_ids
                    )
                )
            )
            personal_limitations = matching_pattern.limitations
            summary = (
                f"The observed niche {descriptor}={value} also appears more often in the "
                f"creator's stronger than weaker {cohort.metric} group "
                f"({matching_pattern.strong_count}/{matching_pattern.strong_total} vs "
                f"{matching_pattern.weak_count}/{matching_pattern.weak_total})."
            )
        else:
            if coverage is None:
                continue
            kind = "niche_gap"
            personal_post_ids = cohort.eligible_post_ids
            personal_limitations = (
                f"All {len(coverage)} eligible creator profiles have known {descriptor} metadata and none match this observed niche descriptor.",
                "This is a coverage gap, not evidence that the niche approach improves creator performance.",
            )
            summary = (
                f"Recent authorized niche posts include {descriptor}={value}; that descriptor is "
                f"absent from {len(coverage)} eligible creator posts with known {descriptor} metadata."
            )
        opportunity = ReportOpportunity(
            kind=kind,
            summary=summary,
            evidence_strength=(cohort.evidence_strength if kind == "niche_intersection" else "Low"),
            personal_evidence_ids=cohort.evidence_ids,
            personal_source_ids=cohort.source_ids,
            personal_post_ids=personal_post_ids,
            niche_evidence_ids=evidence_ids,
            niche_source_ids=source_ids,
            niche_post_ids=post_ids,
            personal_source_versions=cohort.source_versions,
            niche_source_versions=source_versions,
            metric=cohort.metric,
            metric_definition=cohort.metric_definition,
            metric_window=cohort.window,
            freshness="current",
            limitations=tuple(
                dict.fromkeys(
                    (
                        *cohort.limitations,
                        *personal_limitations,
                        "Niche examples are a selected descriptive sample and are never pooled with creator outcome values.",
                        "This association does not establish causation, expected lift, or an X ranking mechanism.",
                    )
                )
            ),
        )
        opportunities.append(opportunity)
        if kind == "niche_intersection" and matching_pattern is not None:
            evidence = _one_evidence_covers_pattern(
                matching_pattern,
                tuple(
                    record
                    for record in bundle.personal_evidence
                    if record.kind == "observation"
                    and all(source_id in sources for source_id in record.source_ids)
                ),
                baseline_by_dimension,
                personal_findings,
            )
            if evidence is None or matching_pattern.strong_count < 3:
                continue
            hypothesis = (
                f"Test {descriptor}={value} in a new post and compare age-aligned "
                f"{cohort.metric} outcomes with a similar control; the observed association "
                "does not establish that the feature causes stronger performance."
            )
            experiments.append(
                ReportExperiment(
                    goal=goal,
                    hypothesis=hypothesis,
                    evidence_ids=(evidence.evidence_id,),
                    supporting_post_ids=personal_post_ids,
                    metric=cohort.metric,
                    metric_definition=cohort.metric_definition,
                    metric_window=cohort.window,
                    limitations=opportunity.limitations,
                    opportunity_kind="niche_intersection",
                    evidence_strength=cohort.evidence_strength,
                    feature=mapped_pattern_name,
                    feature_value=value,
                    personal_evidence_ids=(evidence.evidence_id,),
                    personal_source_ids=evidence.source_ids,
                    personal_supporting_post_ids=personal_post_ids,
                    niche_evidence_ids=evidence_ids,
                    niche_source_ids=source_ids,
                    niche_supporting_post_ids=post_ids,
                    freshness="current",
                )
            )
        elif kind == "niche_gap":
            hypothesis = (
                f"Test {descriptor}={value} once and observe age-aligned {cohort.metric} "
                "against the creator's historical baseline; this is an exploratory test, "
                "not a predicted improvement."
            )
            experiments.append(
                ReportExperiment(
                    goal=goal,
                    hypothesis=hypothesis,
                    evidence_ids=cohort.evidence_ids,
                    supporting_post_ids=cohort.eligible_post_ids,
                    metric=cohort.metric,
                    metric_definition=cohort.metric_definition,
                    metric_window=cohort.window,
                    limitations=opportunity.limitations,
                    opportunity_kind="niche_gap",
                    evidence_strength="Low",
                    feature=mapped_pattern_name,
                    feature_value=value,
                    personal_evidence_ids=cohort.evidence_ids,
                    personal_source_ids=cohort.source_ids,
                    personal_supporting_post_ids=cohort.eligible_post_ids,
                    niche_evidence_ids=evidence_ids,
                    niche_source_ids=source_ids,
                    niche_supporting_post_ids=post_ids,
                    freshness="current",
                )
            )
    return tuple(opportunities), tuple(experiments)


def assemble_creator_report(
    bundle: CreatorReportEvidenceBundle,
    *,
    personal_baselines: tuple[CreatorBaseline, ...] = (),
    personal_outcomes: tuple[OutcomeObservation, ...] = (),
    personal_profiles: tuple[PersonalPostProfile, ...] = (),
) -> CreatorIntelligenceReport:
    """Assemble a deterministic no-draft report with separate evidence pools.

    Only inputs with an explicit, as-of authorization attestation are considered.
    Personal baselines use creator-owned observations only. Niche descriptors are
    descriptive, freshness-gated context and never enter personal metric math.
    The deterministic template is the complete fallback when no LLM is available.
    """
    if bundle.version != REPORT_EVIDENCE_VERSION:
        raise ValueError("unsupported report evidence schema")
    if len(personal_baselines) != len({(b.metric, b.window) for b in personal_baselines}):
        raise ValueError("ambiguous duplicate personal baseline metric/window")
    for historical_baseline in personal_baselines:
        if historical_baseline.version != BASELINE_VERSION:
            raise ValueError("unsupported baseline version")
        if historical_baseline.as_of != bundle.as_of:
            raise ValueError("baseline cutoff differs from report cutoff")
    sources = _authorized_sources(bundle)
    personal_evidence = tuple(
        sorted(
            _authorized_evidence(bundle.personal_evidence, sources),
            key=lambda item: item.evidence_id,
        )
    )
    eligible = _eligible_outcomes(bundle, personal_outcomes, personal_evidence)
    verified = _verified_baselines(
        bundle, personal_baselines, eligible, personal_outcomes, personal_evidence
    )
    baseline_by_dimension = {
        (baseline.metric, baseline.window): (baseline, definition)
        for baseline, definition in verified
    }
    definitions_by_dimension = {
        dimension: definition for dimension, (_, definition) in baseline_by_dimension.items()
    }

    personal: list[ReportFinding] = []
    for item in personal_evidence:
        strength: EvidenceStrength = "Insufficient"
        limits: tuple[str, ...] = ("No independently verified statistical support.",)
        if item.kind == "observation" and (
            item.metric is not None
            and item.metric_definition is not None
            and item.metric_window is not None
        ):
            verified_pair = baseline_by_dimension.get((item.metric, item.metric_window))
            if verified_pair is not None and verified_pair[1] == item.metric_definition:
                baseline = verified_pair[0]
                support = set(baseline.supporting_post_ids)
                if item.post_ids and set(item.post_ids).issubset(support):
                    subset = tuple(
                        record
                        for record in eligible
                        if record.metric == item.metric
                        and record.metric_definition == item.metric_definition
                        and record.window == item.metric_window
                        and record.post_id in item.post_ids
                    )
                    finding_baseline = build_creator_baseline(
                        subset,
                        BaselineRequest(
                            creator_key=bundle.creator_key,
                            metric=item.metric,
                            metric_definition=item.metric_definition,
                            window=item.metric_window,
                            as_of=bundle.as_of,
                        ),
                    )
                    if set(finding_baseline.supporting_post_ids) == set(item.post_ids):
                        strength = finding_baseline.evidence_strength
                        limits = finding_baseline.reasons
                    else:
                        limits = ("Claim references unverified or duplicate observations.",)
                else:
                    limits = ("Evidence post IDs are not supported by the verified baseline.",)
            else:
                limits = ("Baseline provenance or metric definition could not be verified.",)
        personal.append(
            _finding(
                item,
                strength=strength,
                limits=limits,
                sources=sources,
                freshness="historical",
            )
        )

    cohorts = _personal_metric_cohorts(
        bundle,
        tuple(baseline for baseline, _ in verified),
        eligible,
        definitions_by_dimension,
        personal_evidence,
        sources,
    )
    cohorts = tuple(sorted(cohorts, key=lambda cohort: (cohort.metric, cohort.window)))
    cohort_findings = _cohort_findings(cohorts, eligible, sources)
    patterns = compare_personal_content_patterns(
        bundle.creator_key, bundle.as_of, cohorts, personal_profiles
    )
    personal.extend(cohort_findings)
    personal.extend(_pattern_findings(patterns, cohorts))

    has_personal_history = any(item.kind == "observation" for item in personal_evidence)
    if not has_personal_history:
        personal.append(
            ReportFinding(
                section="personal_history",
                summary="No permission-verified personal history observations were supplied; historical performance patterns remain unknown.",
                evidence_ids=(),
                source_ids=(),
                supporting_post_ids=(),
                evidence_strength="Insufficient",
                limitations=("Personal history data or its authorization was unavailable.",),
                kind="unknown",
                freshness="unknown",
            )
        )
    elif not cohorts:
        personal.append(
            ReportFinding(
                section="personal_history",
                summary="No personal performance cohort met the exact metric, provenance, sample and time-cutoff requirements; content performance differences remain unknown.",
                evidence_ids=tuple(item.evidence_id for item in personal_evidence),
                source_ids=tuple(
                    sorted(
                        {source_id for item in personal_evidence for source_id in item.source_ids}
                    )
                ),
                supporting_post_ids=tuple(
                    sorted({post_id for item in personal_evidence for post_id in item.post_ids})
                ),
                evidence_strength="Insufficient",
                limitations=(
                    "Missing, incompatible or insufficient outcome observations prevent a creator-relative comparison.",
                ),
                kind="unknown",
                freshness="historical",
            )
        )
    elif not patterns:
        first_cohort = cohorts[0]
        personal.append(
            ReportFinding(
                section="personal_history",
                summary="No content pattern met the known-feature denominator and comparison sample gates; this does not show that no difference exists.",
                evidence_ids=first_cohort.evidence_ids,
                source_ids=first_cohort.source_ids,
                supporting_post_ids=first_cohort.eligible_post_ids,
                evidence_strength="Insufficient",
                limitations=(
                    "Post Profiles or known descriptors were missing, sparse, or did not meet the descriptive contrast threshold.",
                ),
                kind="unknown",
                freshness="historical",
                source_versions=first_cohort.source_versions,
                metric=first_cohort.metric,
                metric_definition=first_cohort.metric_definition,
                metric_window=first_cohort.window,
                eligible_observation_count=len(first_cohort.eligible_post_ids),
                effective_sample_size=first_cohort.effective_sample_size,
                baseline_statistics=first_cohort.statistics,
            )
        )

    niche_evidence, unverified_niche_count, stale_niche_count, unknown_niche_time_count = (
        _fresh_niche_evidence(bundle, bundle.niche_evidence, sources)
    )
    niche = tuple(
        _finding(
            item,
            strength="Low",
            limits=(
                "Permission-verified niche observations are descriptive selected-sample context, not creator performance evidence.",
            ),
            sources=sources,
            freshness="current",
        )
        for item in sorted(niche_evidence, key=lambda item: item.evidence_id)
    )
    niche_findings = list(niche)
    limitations = list(bundle.limitations)
    if unverified_niche_count:
        limitations.append(
            f"{unverified_niche_count} niche observation(s) excluded because source authorization was not verified by the assessment time."
        )
    if stale_niche_count:
        limitations.append(
            f"{stale_niche_count} stale niche observation(s) excluded by the {NICHE_FRESHNESS_DAYS}-day publication/source freshness heuristic."
        )
    if unknown_niche_time_count:
        limitations.append(
            f"{unknown_niche_time_count} niche observation(s) excluded because publication or actual observation time was missing."
        )
    if not niche:
        limitations.append(
            "No current permission-verified niche evidence is available; no niche trend is inferred."
        )
        niche_findings.append(
            ReportFinding(
                section="niche_observations",
                summary="No current permission-verified niche observations with known publication and observation times were supplied; niche developments are unknown.",
                evidence_ids=(),
                source_ids=(),
                supporting_post_ids=(),
                evidence_strength="Insufficient",
                limitations=(
                    "This report does not fetch niche sources; rights, source availability and freshness must be established upstream.",
                ),
                kind="unknown",
                freshness="unknown",
            )
        )
    if not has_personal_history:
        limitations.append(
            "No permission-verified personal history observations; the report is insufficient for creator-performance interpretation."
        )
    if any(item.evidence_strength == "Insufficient" for item in personal):
        limitations.append("Some personal claims lack adequate comparable-history support.")

    # These are explicitly testable *hypotheses*, not causal explanations:
    # require creator-owned evidence spanning both comparison groups.
    metric_goals = {
        "replies": "conversation",
        "impressions": "reach",
        "profile_clicks": "qualified_interest",
        "link_clicks": "qualified_interest",
    }
    experiments_list: list[ReportExperiment] = []
    for pattern in patterns:
        if len(experiments_list) >= 3 or pattern.strong_count < 3:
            continue
        # A test hypothesis must not encourage features associated mainly with
        # the weaker group; cross-multiply to avoid rounding at the boundary.
        if pattern.strong_count * pattern.weak_total <= pattern.weak_count * pattern.strong_total:
            continue
        goal = metric_goals.get(pattern.metric)
        if goal is None or goal not in bundle.goals.priority_outcomes:
            continue
        # Evidence must cover *all* posts used in the prevalence denominators,
        # including feature-negative comparisons, not just positive examples.
        support = set((*pattern.strong_group_post_ids, *pattern.weak_group_post_ids))
        evidence = next(
            (
                item
                for item in personal_evidence
                if item.kind == "observation"
                and item.metric == pattern.metric
                and item.metric_definition == pattern.metric_definition
                and item.metric_window == pattern.window
                and support.issubset(set(item.post_ids))
                and set(item.post_ids).issubset(
                    set(
                        baseline_by_dimension[(pattern.metric, pattern.window)][
                            0
                        ].supporting_post_ids
                    )
                )
                and any(
                    finding.evidence_ids == (item.evidence_id,)
                    and finding.evidence_strength in ("High", "Moderate")
                    for finding in personal
                )
            ),
            None,
        )
        if evidence is None:
            continue
        experiments_list.append(
            ReportExperiment(
                goal=goal,
                hypothesis=(
                    f"Test {pattern.feature}={pattern.feature_value} in new posts; "
                    "compare age-aligned outcomes against a similar control."
                ),
                evidence_ids=(evidence.evidence_id,),
                supporting_post_ids=tuple(sorted(support)),
                metric=pattern.metric,
                metric_definition=pattern.metric_definition,
                metric_window=pattern.window,
                limitations=pattern.limitations,
                opportunity_kind="personal_pattern",
                evidence_strength=pattern_cohort.evidence_strength
                if (
                    pattern_cohort := next(
                        (
                            cohort
                            for cohort in cohorts
                            if cohort.metric == pattern.metric
                            and cohort.metric_definition == pattern.metric_definition
                            and cohort.window == pattern.window
                        ),
                        None,
                    )
                )
                is not None
                else "Low",
                feature=pattern.feature,
                feature_value=pattern.feature_value,
                personal_evidence_ids=(evidence.evidence_id,),
                personal_source_ids=evidence.source_ids,
                personal_supporting_post_ids=tuple(sorted(support)),
            )
        )

    niche_opportunities, niche_experiments = _niche_opportunities(
        bundle,
        cohorts,
        patterns,
        personal_profiles,
        niche_evidence,
        sources,
        baseline_by_dimension,
        tuple(personal),
    )
    personal_opportunities = tuple(
        ReportOpportunity(
            kind="personal_pattern",
            summary=(
                f"{pattern.feature}={pattern.feature_value} appeared in "
                f"{pattern.strong_count}/{pattern.strong_total} stronger posts and "
                f"{pattern.weak_count}/{pattern.weak_total} weaker posts for "
                f"{pattern.metric} ({pattern.metric_definition}; {pattern.window})."
            ),
            evidence_strength=next(
                cohort.evidence_strength
                for cohort in cohorts
                if (cohort.metric, cohort.metric_definition, cohort.window)
                == (pattern.metric, pattern.metric_definition, pattern.window)
            ),
            personal_evidence_ids=next(
                cohort.evidence_ids
                for cohort in cohorts
                if (cohort.metric, cohort.metric_definition, cohort.window)
                == (pattern.metric, pattern.metric_definition, pattern.window)
            ),
            personal_source_ids=next(
                cohort.source_ids
                for cohort in cohorts
                if (cohort.metric, cohort.metric_definition, cohort.window)
                == (pattern.metric, pattern.metric_definition, pattern.window)
            ),
            personal_post_ids=tuple(
                sorted(set(pattern.strong_group_post_ids + pattern.weak_group_post_ids))
            ),
            niche_evidence_ids=(),
            niche_source_ids=(),
            niche_post_ids=(),
            personal_source_versions=next(
                cohort.source_versions
                for cohort in cohorts
                if (cohort.metric, cohort.metric_definition, cohort.window)
                == (pattern.metric, pattern.metric_definition, pattern.window)
            ),
            niche_source_versions=(),
            metric=pattern.metric,
            metric_definition=pattern.metric_definition,
            metric_window=pattern.window,
            freshness="historical",
            limitations=pattern.limitations,
        )
        for pattern in patterns
        if metric_goals.get(pattern.metric) in bundle.goals.priority_outcomes
        and pattern.strong_count * pattern.weak_total > pattern.weak_count * pattern.strong_total
    )
    experiments = list(experiments_list)
    for niche_experiment in niche_experiments:
        experiments = [
            item
            for item in experiments
            if not (
                niche_experiment.opportunity_kind == "niche_intersection"
                and item.metric == niche_experiment.metric
                and item.feature == niche_experiment.feature
                and item.feature_value == niche_experiment.feature_value
            )
        ]
        if len(experiments) < 3:
            experiments.append(niche_experiment)
    opportunities = tuple(
        sorted(
            (*personal_opportunities, *niche_opportunities),
            key=lambda item: (
                item.metric or "",
                item.metric_window or "",
                item.kind,
                item.summary,
            ),
        )
    )
    experiment_results = tuple(experiments[:3])
    if niche_evidence and not niche_opportunities:
        limitations.append(
            "No defensible intersection or fully evidenced niche-history gap met the current feature and sample gates."
        )

    state: ReportState
    if not has_personal_history:
        state = "insufficient_evidence"
    elif niche:
        state = "personal_and_niche"
    else:
        state = "personal_only_partial"

    return CreatorIntelligenceReport(
        version=REPORT_ALGORITHM_VERSION,
        evidence_version=bundle.version,
        baseline_version=BASELINE_VERSION,
        creator_key=bundle.creator_key,
        as_of=bundle.as_of,
        state=state,
        personal_findings=tuple(personal),
        niche_findings=tuple(niche_findings),
        experiments=experiment_results,
        opportunities=opportunities,
        personal_cohorts=cohorts,
        content_patterns=patterns,
        limitations=tuple(dict.fromkeys(limitations)),
    )
