"""Conservative, no-draft Creator Intelligence Report assembled from approved evidence.

The caller supplies already validated, permissioned evidence. This pure service
never fetches X data, calls an LLM, ranks creators, or predicts exposure.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Literal

from bipme.intelligence.baselines import BASELINE_VERSION, CreatorBaseline, EvidenceStrength
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


def _goal_metric(goal: str, metric: str) -> bool:
    """Conservative label mapping; metrics are not interchangeable."""
    accepted = {
        "conversation": {"replies"},
        "reach": {"impressions"},
        "qualified_interest": {"link_clicks", "profile_clicks"},
        "authority": set(),
    }
    return metric in accepted.get(goal, set())


def assemble_creator_report(
    bundle: CreatorReportEvidenceBundle,
    *,
    personal_baselines: tuple[CreatorBaseline, ...] = (),
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
    for baseline in personal_baselines:
        if baseline.version != BASELINE_VERSION:
            raise ValueError("unsupported baseline version")
        if baseline.as_of != bundle.as_of:
            raise ValueError("baseline cutoff differs from report cutoff")
    baseline_by_dimension = {(b.metric, b.window): b for b in personal_baselines}

    personal: list[ReportFinding] = []
    for item in bundle.personal_evidence:
        strength: EvidenceStrength = "Insufficient"
        limits: tuple[str, ...] = ("No independently verified statistical support.",)
        if item.metric is not None and item.metric_window is not None:
            baseline = baseline_by_dimension.get((item.metric, item.metric_window))
            if baseline is not None:
                if set(item.post_ids).issubset(set(baseline.supporting_post_ids)):
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

    experiments: list[ReportExperiment] = []
    # Only repeated personal observations supported by an existing statistical
    # baseline may justify a testable, optional hypothesis.
    for item in bundle.personal_evidence:
        if len(experiments) >= 3 or item.kind != "observation" or len(item.post_ids) < 3:
            continue
        if item.metric is None or item.metric_definition is None or item.metric_window is None:
            continue
        baseline = baseline_by_dimension.get((item.metric, item.metric_window))
        if baseline is None or baseline.evidence_strength not in ("High", "Moderate"):
            continue
        if not set(item.post_ids).issubset(set(baseline.supporting_post_ids)):
            continue
        goal = next(
            (goal for goal in bundle.goals.priority_outcomes if _goal_metric(goal, item.metric)),
            None,
        )
        if goal is None:
            continue
        experiments.append(
            ReportExperiment(
                goal=goal,
                hypothesis=(
                    f"Test whether a repeatable approach associated with {item.metric} "
                    f"in the {item.metric_window} historical window is useful again."
                ),
                evidence_ids=(item.evidence_id,),
                supporting_post_ids=item.post_ids,
                metric=item.metric,
                metric_definition=item.metric_definition,
                metric_window=item.metric_window,
                limitations=(
                    "Observed associations are not causal; no future lift is guaranteed.",
                    "Compare against age-aligned observations and record the test outcome.",
                ),
            )
        )

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
        experiments=tuple(experiments),
        limitations=tuple(dict.fromkeys(limitations)),
    )
