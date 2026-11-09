"""Conservative, no-draft Creator Intelligence Report assembled from approved evidence.

The caller supplies already validated, permissioned evidence. This pure service
never fetches X data, calls an LLM, ranks creators, or predicts exposure.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Literal

from bipme.intelligence.baselines import (
    BASELINE_VERSION,
    BaselineRequest,
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
from bipme.intelligence.report_evidence import (
    REPORT_EVIDENCE_VERSION,
    CreatorReportEvidenceBundle,
    ReportEvidence,
)

REPORT_ALGORITHM_VERSION = "creator-intelligence-report-v1"
NICHE_FRESHNESS_DAYS = 30
SectionName = Literal["personal_history", "niche_observations", "limitations"]
ReportState = Literal["personal_and_niche", "personal_only_partial", "insufficient_evidence"]


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
    personal_cohorts: tuple[PersonalMetricCohort, ...]
    content_patterns: tuple[ContentPatternContrast, ...]
    limitations: tuple[str, ...]

    def to_json(self) -> str:
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
    raise TypeError(f"unsupported value: {type(value).__name__}")


def _finding(
    record: ReportEvidence, *, strength: EvidenceStrength, limits: tuple[str, ...]
) -> ReportFinding:
    return ReportFinding(
        section="personal_history" if record.pool == "personal" else "niche_observations",
        summary=record.statement,
        evidence_ids=(record.evidence_id,),
        source_ids=record.source_ids,
        supporting_post_ids=record.post_ids,
        evidence_strength=strength,
        limitations=tuple(dict.fromkeys((*record.limitations, *limits))),
        kind=record.kind,
    )


def _eligible_outcomes(
    bundle: CreatorReportEvidenceBundle,
    outcomes: tuple[OutcomeObservation, ...],
) -> tuple[OutcomeObservation, ...]:
    """Cut off future observations before any definition or support discovery."""
    return tuple(
        item
        for item in outcomes
        if item.creator_key == bundle.creator_key
        and item.published_at <= bundle.as_of
        and item.published_at <= item.observed_at <= bundle.as_of
    )


def _verified_baselines(
    bundle: CreatorReportEvidenceBundle,
    baselines: tuple[CreatorBaseline, ...],
    outcomes: tuple[OutcomeObservation, ...],
) -> tuple[tuple[CreatorBaseline, str], ...]:
    """Reconcile untyped baseline provenance with exact-definition eligible data.

    The v1 CreatorBaseline contract does not store metric_definition. Fail
    closed unless it can be reproduced from one definition and the *same*
    eligible post set, sample strength and thresholds. Segmented/shrunk
    baselines that cannot be safely reconstructed are not reused. This conservative\n    restriction remains until baseline provenance is part of the canonical contract.
    """
    verified: list[tuple[CreatorBaseline, str]] = []
    for baseline in baselines:
        supported = set(baseline.supporting_post_ids)
        matches = tuple(
            item
            for item in outcomes
            if item.metric == baseline.metric
            and item.window == baseline.window
            and item.post_id in supported
        )
        definitions = {item.metric_definition for item in matches}
        if len(definitions) != 1 or not matches:
            continue
        definition = next(iter(definitions))
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
        if (
            candidate.supporting_post_ids != baseline.supporting_post_ids
            or candidate.evidence_strength != baseline.evidence_strength
            or candidate.effective_sample_size != baseline.effective_sample_size
            or candidate.statistics != baseline.statistics
        ):
            continue
        verified.append((baseline, definition))
    return tuple(verified)


def _personal_metric_cohorts(
    bundle: CreatorReportEvidenceBundle,
    baselines: tuple[CreatorBaseline, ...],
    observations: tuple[OutcomeObservation, ...],
    definitions_by_dimension: dict[tuple[str, str], str],
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
        limits = [
            "Groups describe historical metric distributions, not content causes or expected lift.",
            "Quartile boundaries use the existing creator baseline, not niche data.",
        ]
        if excluded:
            limits.append(f"{excluded} incompatible or duplicate observation(s) excluded.")
        if baseline.statistics.outlier_count:
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
            )
        )
    return tuple(cohorts)


def assemble_creator_report(
    bundle: CreatorReportEvidenceBundle,
    *,
    personal_baselines: tuple[CreatorBaseline, ...] = (),
    personal_outcomes: tuple[OutcomeObservation, ...] = (),
    personal_profiles: tuple[PersonalPostProfile, ...] = (),
) -> CreatorIntelligenceReport:
    """Assemble deterministic source-traceable findings from validated evidence.

    Niche evidence outside a 30-day initial freshness gate is omitted from
    'current' findings. This gate is a conservative heuristic, not a platform
    temporal rule. Baselines are *personal only*, never applied to niche peers.
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
    eligible = _eligible_outcomes(bundle, personal_outcomes)
    verified = _verified_baselines(bundle, personal_baselines, eligible)
    baseline_by_dimension = {
        (baseline.metric, baseline.window): (baseline, definition)
        for baseline, definition in verified
    }
    definitions_by_dimension = {
        dimension: definition for dimension, (_, definition) in baseline_by_dimension.items()
    }

    personal: list[ReportFinding] = []
    for item in bundle.personal_evidence:
        strength: EvidenceStrength = "Insufficient"
        limits: tuple[str, ...] = ("No independently verified statistical support.",)
        if (
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
        personal.append(_finding(item, strength=strength, limits=limits))

    latest_valid_niche = {
        source.source_id
        for source in bundle.niche_sources
        if bundle.as_of - source.observed_at <= timedelta(days=NICHE_FRESHNESS_DAYS)
    }
    niche = tuple(
        _finding(item, strength="Low", limits=("Niche observations are descriptive only.",))
        for item in bundle.niche_evidence
        if item.kind == "observation"
        and all(source_id in latest_valid_niche for source_id in item.source_ids)
    )
    limitations = list(bundle.limitations)
    if bundle.niche_evidence and len(niche) != len(bundle.niche_evidence):
        limitations.append(
            "Some niche claims were excluded because they were stale or not observations."
        )
    if not niche:
        limitations.append("Current authorized niche evidence is unavailable; no trends inferred.")
    if not personal:
        limitations.append("No personal evidence; report cannot identify historical patterns.")
    if any(item.evidence_strength == "Insufficient" for item in personal):
        limitations.append("Some personal claims lack adequate comparable-history support.")

    cohorts = _personal_metric_cohorts(
        bundle, tuple(baseline for baseline, _ in verified), eligible, definitions_by_dimension
    )
    patterns = compare_personal_content_patterns(
        bundle.creator_key, bundle.as_of, cohorts, personal_profiles
    )
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
                for item in bundle.personal_evidence
                if item.kind == "observation"
                and any(
                    finding.evidence_ids == (item.evidence_id,)
                    and finding.evidence_strength in ("High", "Moderate")
                    for finding in personal
                )
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
            )
        )
    experiments = tuple(experiments_list)

    state: ReportState
    if not personal:
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
        niche_findings=niche,
        experiments=experiments,
        personal_cohorts=cohorts,
        content_patterns=patterns,
        limitations=tuple(dict.fromkeys(limitations)),
    )
