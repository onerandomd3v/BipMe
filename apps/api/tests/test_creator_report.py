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
    observed_at = NOW - timedelta(days=days_old)
    return ReportSource(
        source_id=source_id,
        pool=pool,
        observed_at=observed_at,
        source_version="fixture-v1",
        authorization_basis="synthetic_test_fixture",
        coverage_note="Synthetic sample",
        authorization_verified=True,
        authorization_verified_at=observed_at - timedelta(hours=1),
    )


def _evidence(
    pool: str,
    source_id: str,
    *,
    ids: tuple[str, ...],
    niche_days: int = 1,
) -> ReportEvidence:
    if pool == "niche":
        observed_at = NOW - timedelta(days=niche_days)
        published_at = observed_at
    else:
        observed_at = NOW - timedelta(days=3)
        published_at = NOW - timedelta(days=4)
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
        observed_at=observed_at,
        published_at=published_at,
    )


def _niche_descriptor_evidence(
    evidence_id: str,
    post_id: str,
    descriptor_value: str,
    *,
    descriptor_name: str = "topic",
) -> ReportEvidence:
    return ReportEvidence(
        evidence_id=evidence_id,
        pool="niche",
        kind="observation",
        statement=f"Synthetic observed niche {descriptor_name} descriptor",
        source_ids=("search",),
        post_ids=(post_id,),
        limitations=("Synthetic authorized niche fixture; not representative.",),
        published_at=NOW - timedelta(days=3),
        observed_at=NOW - timedelta(days=2),
        descriptor_name=descriptor_name,
        descriptor_value=descriptor_value,
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
        niche_evidence=(_evidence("niche", "search", ids=("other-post",), niche_days=niche_days),)
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
    assert report.niche_findings[0].kind == "unknown"
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
    assert report.niche_findings[0].kind == "unknown"
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


def test_incompatible_metric_definition_outside_baseline_does_not_poison_it() -> None:
    original = _bundle()
    additional = replace(
        _observations()[0],
        post_id="post-other-definition",
        metric_definition="replies per thousand impressions",
        value=4.0,
    )
    extra_evidence = replace(
        original.personal_evidence[0],
        evidence_id="other-definition-claim",
        post_ids=(additional.post_id,),
        metric_definition=additional.metric_definition,
    )
    report = assemble_creator_report(
        replace(
            original,
            personal_evidence=original.personal_evidence + (extra_evidence,),
        ),
        personal_baselines=(_baseline(),),
        personal_outcomes=_observations() + (additional,),
    )
    assert report.personal_cohorts
    assert report.personal_cohorts[0].eligible_post_ids == tuple(
        sorted(item.post_id for item in _observations())
    )
    original_claim = next(
        finding
        for finding in report.personal_findings
        if finding.evidence_ids == (original.personal_evidence[0].evidence_id,)
    )
    assert original_claim.evidence_strength == "Moderate"


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


@pytest.mark.parametrize(
    ("exclusion", "reason"),
    (("future", "observed_after_as_of"), ("cross_creator", "incompatible_creator")),
)
def test_verified_outcome_exclusion_survives_baseline_replay(exclusion: str, reason: str) -> None:
    observations = _observations()
    if exclusion == "future":
        excluded = replace(
            observations[0], post_id="future-snapshot", observed_at=NOW + timedelta(hours=1)
        )
    else:
        excluded = replace(observations[0], post_id="cross-owner", creator_key="another-creator")
    all_observations = observations + (excluded,)
    request = BaselineRequest(
        creator_key="creator",
        metric="replies",
        metric_definition="observed reply count",
        window="age:24h",
        as_of=NOW,
    )
    source_baseline = build_creator_baseline(all_observations, request)
    evidence = replace(
        _bundle().personal_evidence[0],
        post_ids=tuple(f"post-{index}" for index in range(10)) + (excluded.post_id,),
    )

    report = assemble_creator_report(
        replace(_bundle(), personal_evidence=(evidence,)),
        personal_baselines=(source_baseline,),
        personal_outcomes=all_observations,
    )

    assert len(report.personal_cohorts) == 1
    cohort = report.personal_cohorts[0]
    assert cohort.eligible_post_ids == tuple(f"post-{index}" for index in range(10))
    assert cohort.exclusion_counts == ((reason, 1),)
    assert any(reason in limitation for limitation in cohort.limitations)


def test_missing_metric_is_reported_as_an_exclusion_not_a_zero() -> None:
    original = _bundle()
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{index}" for index in range(20)),
    )
    observations = list(_twenty_observations())
    observations[0] = replace(observations[0], value=None)
    request = BaselineRequest(
        creator_key="creator",
        metric="replies",
        metric_definition="observed reply count",
        window="age:24h",
        as_of=NOW,
    )
    baseline = build_creator_baseline(tuple(observations), request)
    report = assemble_creator_report(
        replace(original, personal_evidence=(evidence,)),
        personal_baselines=(baseline,),
        personal_outcomes=tuple(observations),
        personal_profiles=_twenty_profiles(),
    )
    cohort = report.personal_cohorts[0]
    assert baseline.eligible_post_count == 19
    assert "post-0" not in cohort.eligible_post_ids
    assert cohort.statistics is not None
    assert cohort.statistics.p50 == 11.0
    assert cohort.exclusion_counts == baseline.exclusion_counts
    assert any("missing" in reason for reason, _ in cohort.exclusion_counts)
    assert any("excluded" in limitation for limitation in cohort.limitations)


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
    assert report.experiments[0].opportunity_kind == "personal_pattern"
    assert report.experiments[0].evidence_strength == "High"
    assert report.experiments[0].personal_source_ids == ("owned",)
    assert report.experiments[0].niche_evidence_ids == ()
    assert "causal" in " ".join(report.experiments[0].limitations)
    assert report.opportunities[0].kind == "personal_pattern"


def test_personal_opportunities_respect_creator_goal_preferences() -> None:
    original = _bundle()
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{index}" for index in range(20)),
    )
    goals = replace(original.goals, priority_outcomes=("reach",))
    report = assemble_creator_report(
        replace(original, personal_evidence=(evidence,), goals=goals),
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
        personal_profiles=_twenty_profiles(),
    )
    assert report.content_patterns
    assert report.experiments == ()
    assert report.opportunities == ()
    assert any(
        finding.kind == "observation"
        and finding.eligible_observation_count == 20
        and finding.baseline_statistics is not None
        and "above P75" in finding.summary
        for finding in report.personal_findings
    )
    assert any(
        finding.kind == "inference" and "declared_topic=build" in finding.summary
        for finding in report.personal_findings
    )
    assert report.synthesis_mode == "deterministic_fallback"
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
    assert report.opportunities == ()
    assert any(finding.kind == "unknown" for finding in report.personal_findings)


def test_outlier_is_exposed_with_creator_sample_and_not_treated_as_a_pattern() -> None:
    outcomes = tuple(
        replace(
            item,
            post_id=f"outlier-post-{index}",
            value=10_000.0 if index == 9 else float(index + 1),
        )
        for index, item in enumerate(_observations())
    )
    baseline = build_creator_baseline(
        outcomes,
        BaselineRequest(
            creator_key="creator",
            metric="replies",
            metric_definition="observed reply count",
            window="age:24h",
            as_of=NOW,
        ),
    )
    evidence = replace(
        _bundle().personal_evidence[0],
        post_ids=tuple(f"outlier-post-{index}" for index in range(10)),
    )
    report = assemble_creator_report(
        replace(_bundle(), personal_evidence=(evidence,)),
        personal_baselines=(baseline,),
        personal_outcomes=outcomes,
    )
    assert len(report.personal_cohorts) == 1
    cohort = report.personal_cohorts[0]
    assert cohort.eligible_post_ids == tuple(f"outlier-post-{index}" for index in range(10))
    assert cohort.outlier_post_ids == ("outlier-post-9",)
    assert cohort.statistics is not None and cohort.statistics.outlier_count == 1
    assert cohort.effective_sample_size == pytest.approx(10)
    assert report.experiments == ()


def test_unverified_personal_and_niche_sources_fail_closed() -> None:
    original = _bundle(niche_days=1)
    personal_source = replace(
        original.personal_sources[0],
        authorization_verified=False,
        authorization_verified_at=None,
    )
    niche_source = replace(
        original.niche_sources[0],
        authorization_verified=False,
        authorization_verified_at=None,
    )
    unverified_personal = replace(original, personal_sources=(personal_source,))
    report = assemble_creator_report(
        unverified_personal,
        personal_baselines=(_baseline(),),
        personal_outcomes=_observations(),
    )
    assert report.state == "insufficient_evidence"
    assert report.personal_cohorts == ()
    assert report.niche_findings[0].kind == "observation"
    assert report.personal_findings[0].kind == "unknown"

    unverified_niche = replace(original, niche_sources=(niche_source,))
    partial = assemble_creator_report(unverified_niche)
    assert partial.state == "personal_only_partial"
    assert partial.niche_findings[0].kind == "unknown"
    assert any("authorization was not verified" in item for item in partial.limitations)


def test_niche_intersection_keeps_source_pools_and_metric_math_separate() -> None:
    original = _bundle(niche_days=1)
    niche = (
        _niche_descriptor_evidence("niche-build-a", "niche-post-a", "build"),
        _niche_descriptor_evidence("niche-build-b", "niche-post-b", "build"),
    )
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{index}" for index in range(20)),
    )
    full = replace(
        original,
        personal_evidence=(evidence,),
        niche_evidence=niche,
    )
    report = assemble_creator_report(
        full,
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
        personal_profiles=_twenty_profiles(),
    )
    intersection = next(item for item in report.opportunities if item.kind == "niche_intersection")
    assert report.state == "personal_and_niche"
    assert intersection.personal_evidence_ids == (evidence.evidence_id,)
    assert intersection.personal_source_ids == ("owned",)
    assert intersection.personal_post_ids
    assert intersection.niche_evidence_ids == ("niche-build-a", "niche-build-b")
    assert intersection.niche_source_ids == ("search",)
    assert intersection.niche_post_ids == ("niche-post-a", "niche-post-b")
    hypothesis = next(
        item for item in report.experiments if item.opportunity_kind == "niche_intersection"
    )
    assert hypothesis.evidence_strength == "High"
    assert hypothesis.personal_supporting_post_ids == intersection.personal_post_ids
    assert hypothesis.niche_supporting_post_ids == intersection.niche_post_ids
    assert not set(hypothesis.personal_supporting_post_ids).intersection(
        hypothesis.niche_supporting_post_ids
    )
    assert report.personal_cohorts[0].source_ids == ("owned",)
    assert report.personal_cohorts[0].eligible_post_ids == tuple(
        sorted(f"post-{index}" for index in range(20))
    )
    assert all(item.freshness == "current" for item in report.niche_findings)


def test_fully_known_personal_history_reports_niche_gap_as_low_strength_test() -> None:
    original = _bundle(niche_days=1)
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{index}" for index in range(20)),
    )
    profiles = tuple(
        replace(record, profile=replace(record.profile, declared_topic="engineering"))
        for record in _twenty_profiles()
    )
    report = assemble_creator_report(
        replace(
            original,
            personal_evidence=(evidence,),
            niche_evidence=(
                _niche_descriptor_evidence("niche-build-a", "niche-post-a", "build"),
                _niche_descriptor_evidence("niche-build-b", "niche-post-b", "build"),
            ),
        ),
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
        personal_profiles=profiles,
    )
    gap = next(item for item in report.opportunities if item.kind == "niche_gap")
    assert "absent from 20 eligible creator posts with known topic metadata" in gap.summary
    experiment = next(item for item in report.experiments if item.opportunity_kind == "niche_gap")
    assert experiment.evidence_strength == "Low"
    assert "exploratory test" in experiment.hypothesis
    assert any("not evidence" in item for item in gap.limitations)


def test_unsupported_profile_version_cannot_establish_a_niche_gap() -> None:
    original = _bundle(niche_days=1)
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{index}" for index in range(20)),
    )
    profiles = tuple(
        replace(record, profile=replace(record.profile, version="unsupported-profile-v99"))
        for record in _twenty_profiles()
    )
    report = assemble_creator_report(
        replace(
            original,
            personal_evidence=(evidence,),
            niche_evidence=(
                _niche_descriptor_evidence("niche-topic-a", "niche-topic-a", "engineering"),
                _niche_descriptor_evidence("niche-topic-b", "niche-topic-b", "engineering"),
            ),
        ),
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
        personal_profiles=profiles,
    )
    assert not any(item.kind == "niche_gap" for item in report.opportunities)
    assert not any(item.opportunity_kind == "niche_gap" for item in report.experiments)


def test_niche_experiment_cannot_reinstate_an_unsupported_personal_claim() -> None:
    original = _bundle(niche_days=1)
    rejected = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{index}" for index in range(20)) + ("not-owned",),
    )
    report = assemble_creator_report(
        replace(
            original,
            personal_evidence=(rejected,),
            niche_evidence=(
                _niche_descriptor_evidence("niche-build-a", "niche-a", "build"),
                _niche_descriptor_evidence("niche-build-b", "niche-b", "build"),
            ),
        ),
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
        personal_profiles=_twenty_profiles(),
    )
    assert report.personal_findings[0].evidence_strength == "Insufficient"
    assert not any(item.opportunity_kind == "niche_intersection" for item in report.experiments)


def test_niche_matching_checks_all_goal_cohorts_before_falling_back() -> None:
    original = _bundle(niche_days=1)
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{index}" for index in range(20)),
    )
    hour_evidence = replace(
        evidence,
        evidence_id="personal-hour-claim",
        metric_window="age:1h",
    )
    hour_observations = tuple(
        replace(item, window="age:1h", value=float(20 - index))
        for index, item in enumerate(_twenty_observations())
    )
    hour_baseline = build_creator_baseline(
        hour_observations,
        BaselineRequest(
            creator_key="creator",
            metric="replies",
            metric_definition="observed reply count",
            window="age:1h",
            as_of=NOW,
        ),
    )
    report = assemble_creator_report(
        replace(
            original,
            personal_evidence=(evidence, hour_evidence),
            niche_evidence=(
                _niche_descriptor_evidence("niche-build-a", "niche-a", "build"),
                _niche_descriptor_evidence("niche-build-b", "niche-b", "build"),
            ),
        ),
        personal_baselines=(_twenty_baseline(), hour_baseline),
        personal_outcomes=_twenty_observations() + hour_observations,
        personal_profiles=_twenty_profiles(),
    )
    intersection = next(item for item in report.opportunities if item.kind == "niche_intersection")
    assert intersection.metric_window == "age:24h"
    hypothesis = next(
        item for item in report.experiments if item.opportunity_kind == "niche_intersection"
    )
    assert hypothesis.metric_window == "age:24h"


def test_missing_personal_metadata_is_not_reported_as_niche_absence() -> None:
    original = _bundle(niche_days=1)
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{index}" for index in range(20)),
    )
    profiles = tuple(
        replace(record, profile=replace(record.profile, declared_topic=None))
        for record in _twenty_profiles()
    )
    report = assemble_creator_report(
        replace(
            original,
            personal_evidence=(evidence,),
            niche_evidence=(
                _niche_descriptor_evidence("niche-build-a", "niche-post-a", "build"),
                _niche_descriptor_evidence("niche-build-b", "niche-post-b", "build"),
            ),
        ),
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
        personal_profiles=profiles,
    )
    assert not any(item.kind == "niche_gap" for item in report.opportunities)
    assert not any(item.opportunity_kind == "niche_gap" for item in report.experiments)


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


def test_codex_exact_two_fifths_prevalence_cutoff() -> None:
    profiles = []
    for index, record in enumerate(_twenty_profiles()[:10]):
        topic = "build" if index in (0, 1, 2, 5) else "misc"
        profiles.append(replace(record, profile=replace(record.profile, declared_topic=topic)))
    cohort = PersonalMetricCohort(
        metric="replies",
        metric_definition="observed reply count",
        window="age:24h",
        evidence_strength="Moderate",
        strong_post_ids=tuple(f"post-{idx}" for idx in range(5)),
        typical_post_ids=(),
        weak_post_ids=tuple(f"post-{idx}" for idx in range(5, 10)),
        excluded_count=0,
        limitations=(),
    )
    patterns = compare_personal_content_patterns("creator", NOW, (cohort,), tuple(profiles))
    assert any(
        pattern.feature == "declared_topic"
        and pattern.feature_value == "build"
        and pattern.strong_count == 3
        and pattern.strong_total == 5
        and pattern.weak_count == 1
        and pattern.weak_total == 5
        for pattern in patterns
    )


def test_codex_experiment_requires_feature_negative_comparisons() -> None:
    original = _bundle()
    # Six feature-positive posts and two unrelated posts give eight supporting
    # measurements, but omit four weak posts from the actual contrast denominator.
    subset = tuple(f"post-{idx}" for idx in (0, 5, 6, 15, 16, 17, 18, 19))
    evidence = replace(original.personal_evidence[0], post_ids=subset)
    remainder = replace(
        evidence,
        evidence_id="personal-remainder",
        post_ids=tuple(f"post-{idx}" for idx in range(20) if f"post-{idx}" not in subset),
    )
    report = assemble_creator_report(
        replace(original, personal_evidence=(evidence, remainder)),
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
        personal_profiles=_twenty_profiles(),
    )
    assert report.personal_findings[0].evidence_strength == "Moderate"
    assert report.content_patterns
    assert report.experiments == ()


def test_codex_weak_associated_feature_not_recommended() -> None:
    original = _bundle()
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{idx}" for idx in range(20)),
    )
    changed = []
    for index, record in enumerate(_twenty_profiles()):
        topic = "build" if index in (0, 1, 2, 3, 4, 15, 16, 17) else "misc"
        changed.append(replace(record, profile=replace(record.profile, declared_topic=topic)))
    report = assemble_creator_report(
        replace(original, personal_evidence=(evidence,)),
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
        personal_profiles=tuple(changed),
    )
    assert any(
        pattern.feature == "declared_topic"
        and pattern.feature_value == "build"
        and pattern.strong_count * pattern.weak_total < pattern.weak_count * pattern.strong_total
        for pattern in report.content_patterns
    )
    assert report.experiments == ()


@pytest.mark.parametrize("exclusion", ("duplicate", "future", "cross_creator"))
def test_profile_exclusions_are_independent_and_keep_pattern_evidence_nonvacuous(
    exclusion: str,
) -> None:
    original = _bundle()
    evidence = replace(
        original.personal_evidence[0],
        post_ids=tuple(f"post-{idx}" for idx in range(20)),
    )
    profiles = list(_twenty_profiles())
    if exclusion == "duplicate":
        profiles.append(profiles[17])
    elif exclusion == "future":
        profiles[17] = replace(
            profiles[17],
            profile=replace(profiles[17].profile, features_as_of=NOW + timedelta(days=1)),
        )
    else:
        profiles[17] = replace(
            profiles[17],
            profile=replace(profiles[17].profile, creator_key="another-creator"),
        )
    report = assemble_creator_report(
        replace(original, personal_evidence=(evidence,)),
        personal_baselines=(_twenty_baseline(),),
        personal_outcomes=_twenty_observations(),
        personal_profiles=tuple(profiles),
    )
    build_patterns = [
        pattern
        for pattern in report.content_patterns
        if pattern.feature == "declared_topic" and pattern.feature_value == "build"
    ]
    assert build_patterns, f"{exclusion} exclusion must leave a measurable build contrast"
    pattern = build_patterns[0]
    assert (pattern.strong_count, pattern.strong_total) == (4, 4)
    assert (pattern.weak_count, pattern.weak_total) == (1, 4)
    assert pattern.strong_total + pattern.weak_total == 8
    assert "post-17" not in pattern.strong_post_ids
    assert "post-17" not in pattern.weak_post_ids
    assert "post-17" not in pattern.strong_group_post_ids
    assert "post-17" not in pattern.weak_group_post_ids

    build_experiments = [
        experiment
        for experiment in report.experiments
        if experiment.metric == pattern.metric
        and experiment.metric_definition == pattern.metric_definition
        and experiment.metric_window == pattern.window
    ]
    assert build_experiments, f"{exclusion} exclusion must retain source-backed experiment evidence"
    experiment = build_experiments[0]
    assert experiment.evidence_ids == (evidence.evidence_id,)
    assert "post-17" not in experiment.supporting_post_ids
    assert set(experiment.supporting_post_ids) == set(
        pattern.strong_group_post_ids + pattern.weak_group_post_ids
    )
    assert set(experiment.supporting_post_ids).issubset(set(evidence.post_ids))
