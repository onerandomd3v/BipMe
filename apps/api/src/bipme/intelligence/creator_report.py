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
    CreatorBaseline,
    EvidenceStrength,
    OutcomeObservation,
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


def _personal_metric_cohorts(
    bundle: CreatorReportEvidenceBundle,
    baselines: tuple[CreatorBaseline, ...],
    observations: tuple[OutcomeObservation, ...],
) -> tuple[PersonalMetricCohort, ...]:
    """Segment eligible, unique, same-creator measured outcomes; never cross niche pools.

    Quantile cut points come from the existing COD-353 baseline, not invented
    scores. Unknown/misaligned/future records are excluded rather than imputed.
    """
    cohorts: list[PersonalMetricCohort] = []
    for baseline in baselines:
        if baseline.statistics is None or baseline.evidence_strength == "Insufficient":
            continue
        definitions = {
            record.metric_definition
            for record in observations
            if record.metric == baseline.metric and record.window == baseline.window
            and record.creator_key == bundle.creator_key
        }
        if len(definitions) != 1:
            continue
        definition = next(iter(definitions))
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
        strong = tuple(sorted(id for id, record in eligible.items() if record.value > high))
        weak = tuple(sorted(id for id, record in eligible.items() if record.value < low))
        typical = tuple(sorted(
            id for id, record in eligible.items() if low <= record.value <= high
        ))
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
    baseline_by_dimension = {(b.metric, b.window): b for b in personal_baselines}
    # A baseline omits metric_definition; never accept a claim merely by matching
    # its metric name/window when the caller supplies a different definition.
    known_definitions: dict[tuple[str, str], set[str]] = {}
    for outcome in personal_outcomes:
        if outcome.creator_key == bundle.creator_key:
            known_definitions.setdefault((outcome.metric, outcome.window), set()).add(
                outcome.metric_definition
            )

    personal: list[ReportFinding] = []
    for item in bundle.personal_evidence:
        strength: EvidenceStrength = "Insufficient"
        limits: tuple[str, ...] = ("No independently verified statistical support.",)
        if item.metric is not None and item.metric_window is not None:
            baseline = baseline_by_dimension.get((item.metric, item.metric_window))
            definition_verified = (
                item.metric_definition is not None
                and known_definitions.get((item.metric, item.metric_window))
                == {item.metric_definition}
            )
            if baseline is not None and definition_verified:
                if item.post_ids and set(item.post_ids).issubset(set(baseline.supporting_post_ids)):
                    strength = baseline.evidence_strength
                    limits = baseline.reasons
                else:
                    limits = ("Evidence post IDs are not supported by the personal baseline.",)
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

    cohorts = _personal_metric_cohorts(bundle, personal_baselines, personal_outcomes)
    # Descriptors have not yet been joined to cohort contrasts; refrain from
    # generating hypotheses solely from repeated post IDs.
    experiments: tuple[ReportExperiment, ...] = ()

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
        limitations=tuple(dict.fromkeys(limitations)),
    )
