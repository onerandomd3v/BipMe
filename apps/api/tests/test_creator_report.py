"""Synthetic report-engine tests; never fetch live X or use a model provider."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from bipme.intelligence.baselines import BaselineRequest, OutcomeObservation, build_creator_baseline
from bipme.intelligence.creator_goals import CreatorGoalsSnapshot
from bipme.intelligence.creator_report import assemble_creator_report
from bipme.intelligence.report_evidence import (
    CreatorReportEvidenceBundle,
    ReportEvidence,
    ReportSource,
)

NOW = datetime(2026, 11, 9, tzinfo=UTC)


def _goals() -> CreatorGoalsSnapshot:
    return CreatorGoalsSnapshot(
        creator_key="creator",
        recorded_at=NOW - timedelta(days=5),
        niche="engineering",
        intended_audience="developers",
        priority_outcomes=("conversation",),
    )


def _source(pool: str, source_id: str, days_old: int = 1) -> ReportSource:
    return ReportSource(
        source_id=source_id,
        pool=pool,
        observed_at=NOW - timedelta(days=days_old),
        source_version="fixture-v1",
        authorization_basis="synthetic_test_fixture",
        coverage_note="Synthetic sample",
    )


def _evidence(pool: str, source_id: str, *, ids: tuple[str, ...]) -> ReportEvidence:
    return ReportEvidence(
        evidence_id=pool + "-claim",
        pool=pool,
        kind="observation",
        statement="Synthetic observed activity",
        source_ids=(source_id,),
        post_ids=ids,
        metric="replies",
        metric_definition="observed reply count",
        metric_window="age:24h",
        metric_value=5.0,
    )


def _bundle(niche_days: int | None = None) -> CreatorReportEvidenceBundle:
    ids = tuple(f"post-{index}" for index in range(10))
    return CreatorReportEvidenceBundle(
        creator_key="creator",
        as_of=NOW,
        goals=_goals(),
        personal_sources=(_source("personal", "owned"),),
        niche_sources=(_source("niche", "search", niche_days),) if niche_days is not None else (),
        personal_evidence=(_evidence("personal", "owned", ids=ids),),
        niche_evidence=(_evidence("niche", "search", ids=("other-post",)),)
        if niche_days is not None
        else (),
    )


def _observations() -> tuple[OutcomeObservation, ...]:
    observations = [
        OutcomeObservation(
            creator_key="creator",
            post_id=f"post-{index}",
            metric="replies",
            metric_definition="observed reply count",
            value=float(index + 1),
            published_at=NOW - timedelta(days=4),
            observed_at=NOW - timedelta(days=3),
            window="age:24h",
        )
        for index in range(10)
    ]
    return tuple(observations)


def _baseline():
    return build_creator_baseline(
        _observations(),
        BaselineRequest(
            creator_key="creator",
            metric="replies",
            metric_definition="observed reply count",
            window="age:24h",
            as_of=NOW,
        ),
    )


def test_report_is_deterministic_personal_only_and_goal_aligned() -> None:
    report = assemble_creator_report(
        _bundle(), personal_baselines=(_baseline(),), personal_outcomes=_observations()
    )
    assert report.state == "personal_only_partial"
    assert report.personal_findings[0].source_ids == ("owned",)
    assert report.niche_findings == ()
    assert report.experiments == ()
    assert report.personal_cohorts[0].strong_post_ids
    assert report.personal_cohorts[0].typical_post_ids
    assert report.personal_cohorts[0].weak_post_ids
    assert json.loads(report.to_json())["state"] == "personal_only_partial"
    assert report.to_json() == report.to_json()


def test_current_permissioned_niche_is_separate() -> None:
    report = assemble_creator_report(_bundle(niche_days=2))
    assert report.state == "personal_and_niche"
    assert report.niche_findings[0].source_ids == ("search",)
    assert report.personal_findings[0].source_ids == ("owned",)
    assert report.experiments == ()


def test_stale_niche_is_not_presented_as_current() -> None:
    report = assemble_creator_report(_bundle(niche_days=90))
    assert report.state == "personal_only_partial"
    assert report.niche_findings == ()
    assert any("stale" in item for item in report.limitations)


def test_empty_history_remains_insufficient_even_with_niche() -> None:
    bundle = replace(_bundle(niche_days=1), personal_evidence=())
    report = assemble_creator_report(bundle)
    assert report.state == "insufficient_evidence"
    assert report.experiments == ()


def test_mismatched_baseline_cutoff_fails_closed() -> None:
    baseline = replace(_baseline(), as_of=NOW - timedelta(days=1))
    with pytest.raises(ValueError, match="cutoff"):
        assemble_creator_report(_bundle(), personal_baselines=(baseline,))


def test_unsupported_evidence_ids_cannot_justify_experiments() -> None:
    bundle = _bundle()
    bad_claim = replace(
        bundle.personal_evidence[0],
        post_ids=("unknown", "post-1", "post-2"),
    )
    report = assemble_creator_report(
        replace(bundle, personal_evidence=(bad_claim,)),
        personal_baselines=(_baseline(),),
        personal_outcomes=_observations(),
    )
    assert report.experiments == ()
    assert report.personal_findings[0].evidence_strength == "Insufficient"


def test_missing_outcome_observations_cannot_establish_claim_strength() -> None:
    report = assemble_creator_report(_bundle(), personal_baselines=(_baseline(),))
    assert report.personal_findings[0].evidence_strength == "Insufficient"
    assert report.personal_cohorts == ()
    assert report.experiments == ()


def test_metric_definition_mismatch_is_not_comparable() -> None:
    bundle = _bundle()
    altered = replace(
        bundle.personal_evidence[0], metric_definition="replies per thousand impressions"
    )
    report = assemble_creator_report(
        replace(bundle, personal_evidence=(altered,)),
        personal_baselines=(_baseline(),),
        personal_outcomes=_observations(),
    )
    assert report.personal_findings[0].evidence_strength == "Insufficient"
    assert report.experiments == ()


def test_duplicate_outcome_excluded_from_strong_typical_weak_groups() -> None:
    duplicated = _observations() + (_observations()[0],)
    report = assemble_creator_report(
        _bundle(), personal_baselines=(_baseline(),), personal_outcomes=duplicated
    )
    cohort = report.personal_cohorts[0]
    included = cohort.strong_post_ids + cohort.typical_post_ids + cohort.weak_post_ids
    assert "post-0" not in included
    assert len(included) == 9
    assert cohort.excluded_count >= 2


def test_future_and_cross_creator_outcomes_are_excluded() -> None:
    records = _observations()
    future = replace(records[0], post_id="future", observed_at=NOW + timedelta(hours=1))
    other_creator = replace(records[1], post_id="another", creator_key="stranger")
    report = assemble_creator_report(
        _bundle(),
        personal_baselines=(_baseline(),),
        personal_outcomes=records + (future, other_creator),
    )
    cohort = report.personal_cohorts[0]
    included = cohort.strong_post_ids + cohort.typical_post_ids + cohort.weak_post_ids
    assert "future" not in included
    assert "another" not in included
    assert cohort.excluded_count >= 2
