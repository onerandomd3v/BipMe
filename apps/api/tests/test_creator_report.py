"""Synthetic report-engine tests; never fetch live X or use a model provider."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from bipme.intelligence.baselines import BaselineRequest, OutcomeObservation, build_creator_baseline
from bipme.intelligence.content_patterns import (
    PersonalPostProfile,
    compare_personal_content_patterns,
)
from bipme.intelligence.creator_goals import CreatorGoalsSnapshot
from bipme.intelligence.creator_report import (
    PersonalMetricCohort,
    assemble_creator_report,
)
from bipme.intelligence.post_profiles import PostProfileInput, extract_post_profile
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
    # Ambiguous duplicates invalidate the source baseline rather than
    # silently reusing its quantiles from a different observation set.
    assert report.personal_cohorts == ()
    assert report.personal_findings[0].evidence_strength == "Insufficient"


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
    assert len(included) == 10


def _twenty_observations() -> tuple[OutcomeObservation, ...]:
    return tuple(
        replace(record, post_id=f"post-{idx}", value=float(idx + 1))
        for idx, record in enumerate((_observations()[0],) * 20)
    )


def _twenty_baseline():
    return build_creator_baseline(
        _twenty_observations(),
        BaselineRequest(
            creator_key="creator",
            metric="replies",
            metric_definition="observed reply count",
            window="age:24h",
            as_of=NOW,
        ),
    )


def _twenty_profiles() -> tuple[PersonalPostProfile, ...]:
    results: list[PersonalPostProfile] = []
    for idx in range(20):
        # This is synthetic creator-declared topic metadata, not text inference.
        topic = "build" if idx in (0, 15, 16, 17, 18, 19) else "misc"
        profile = extract_post_profile(
            PostProfileInput(
                text="A developer note",
                observed_at=NOW - timedelta(days=4),
                features_as_of=NOW - timedelta(days=3),
                creator_key="creator",
                media_types=(),
                declared_topic=topic,
            )
        )
        results.append(PersonalPostProfile(f"post-{idx}", profile))
    return tuple(results)


def test_goal_aligned_content_pattern_has_measured_support() -> None:
    original = _bundle()
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{idx}" for idx in range(20)),
    )
    report = assemble_creator_report(
        replace(original, personal_evidence=(evidence,)),
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
        personal_profiles=_twenty_profiles(),
    )
    matches = [
        pattern
        for pattern in report.content_patterns
        if pattern.feature == "declared_topic" and pattern.feature_value == "build"
    ]
    assert matches and matches[0].strong_count >= 3
    assert report.experiments
    assert report.experiments[0].goal == "conversation"
    assert report.experiments[0].evidence_ids == (evidence.evidence_id,)
    assert "causal" in " ".join(report.experiments[0].limitations)
    assert report.to_json() == report.to_json()


def test_future_cross_creator_and_duplicate_profiles_are_not_compared() -> None:
    records = _twenty_profiles()
    future_profile = replace(records[19].profile, features_as_of=NOW + timedelta(days=1))
    other_profile = replace(records[18].profile, creator_key="other")
    bad = (
        records[:18]
        + (PersonalPostProfile("post-18", other_profile),)
        + (PersonalPostProfile("post-19", future_profile),)
        + (records[17],)
    )
    original = _bundle()
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{idx}" for idx in range(20)),
    )
    report = assemble_creator_report(
        replace(original, personal_evidence=(evidence,)),
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
        personal_profiles=bad,
    )
    assert report.experiments == ()
    assert all(
        "post-17" not in (*pattern.strong_post_ids, *pattern.weak_post_ids)
        for pattern in report.content_patterns
    )


def test_missing_descriptors_do_not_create_report_hypotheses() -> None:
    original = _bundle()
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{idx}" for idx in range(20)),
    )
    report = assemble_creator_report(
        replace(original, personal_evidence=(evidence,)),
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
    )
    assert report.content_patterns == ()
    assert report.experiments == ()


def test_codex_baseline_definition_mismatch_fails_closed() -> None:
    other_definition = tuple(
        replace(item, metric_definition="replies per thousand impressions", value=1.0)
        for item in _observations()
    )
    report = assemble_creator_report(
        _bundle(),
        personal_baselines=(_baseline(),),
        personal_outcomes=other_definition,
    )
    assert report.personal_findings[0].evidence_strength == "Insufficient"
    assert report.personal_cohorts == ()


def test_codex_future_definition_does_not_poison_eligible_report() -> None:
    future = replace(
        _observations()[0],
        post_id="future-post",
        metric_definition="impressions-normalized replies",
        observed_at=NOW + timedelta(days=1),
    )
    original = assemble_creator_report(
        _bundle(), personal_baselines=(_baseline(),), personal_outcomes=_observations()
    )
    extended = assemble_creator_report(
        _bundle(),
        personal_baselines=(_baseline(),),
        personal_outcomes=_observations() + (future,),
    )
    assert original.personal_findings == extended.personal_findings
    assert original.personal_cohorts == extended.personal_cohorts


def test_codex_one_post_claim_does_not_inherit_moderate_strength() -> None:
    original = _bundle()
    single_post = replace(original.personal_evidence[0], post_ids=("post-9",))
    report = assemble_creator_report(
        replace(original, personal_evidence=(single_post,)),
        personal_baselines=(_baseline(),),
        personal_outcomes=_observations(),
    )
    assert report.personal_findings[0].evidence_strength == "Insufficient"
    assert not any(
        "At least 8 effective posts" in reason for reason in report.personal_findings[0].limitations
    )


def test_codex_missing_topology_is_not_counted_as_absence() -> None:
    profiles = _twenty_profiles()
    selected = []
    for record in profiles[:16]:
        topology = "original" if record.post_id.startswith("post-") else None
        if int(record.post_id.split("-")[1]) >= 9:
            topology = None
        selected.append(replace(record, profile=replace(record.profile, topology=topology)))
    cohort = PersonalMetricCohort(
        metric="replies",
        metric_definition="observed reply count",
        window="age:24h",
        evidence_strength="Moderate",
        strong_post_ids=tuple(f"post-{i}" for i in range(8)),
        typical_post_ids=(),
        weak_post_ids=tuple(f"post-{i}" for i in range(8, 16)),
        excluded_count=0,
        limitations=(),
    )
    patterns = compare_personal_content_patterns("creator", NOW, (cohort,), tuple(selected))
    assert not any(pattern.feature == "topology" for pattern in patterns)


def test_codex_rejected_claim_cannot_reappear_as_experiment() -> None:
    original = _bundle()
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{idx}" for idx in range(20)) + ("not-owned",),
    )
    report = assemble_creator_report(
        replace(original, personal_evidence=(evidence,)),
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
        personal_profiles=_twenty_profiles(),
    )
    assert report.personal_findings[0].evidence_strength == "Insufficient"
    assert report.experiments == ()
