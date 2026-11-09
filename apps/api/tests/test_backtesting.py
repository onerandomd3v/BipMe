"""Synthetic, non-vacuous leakage and calibration-quality tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from bipme.intelligence.backtesting import (
    BacktestSpec,
    OutlookBacktestCase,
    evaluate_distribution_outlooks,
)
from bipme.intelligence.baselines import OutcomeObservation
from bipme.intelligence.embeddings import EmbeddingIdentity
from bipme.intelligence.outlooks import OutlookRequest
from bipme.intelligence.post_profiles import PostProfileInput, extract_post_profile
from bipme.intelligence.retrieval import (
    CandidateExclusion,
    ComparableMatch,
    ComparableSet,
    DraftAssessment,
    RelevanceComponents,
)

CREATOR = "synthetic-creator"
METRIC = ("impressions", "impressions-v1", "age:24h")
IDENTITY = EmbeddingIdentity("synthetic/model", "a" * 40, 3, "synthetic-v1")
REPORT_CUTOFF = datetime(2026, 3, 1, tzinfo=UTC)


def _profile(at: datetime, creator: str = CREATOR):
    return extract_post_profile(
        PostProfileInput(
            text="Synthetic historical post with a measurable idea.",
            observed_at=at,
            features_as_of=at,
            creator_key=creator,
            declared_topic="engineering",
            declared_intent="inform",
            topology="original",
            thread_role="single",
            media_types=(),
        )
    )


def _observation(
    post_id: str,
    value: float | None,
    published_at: datetime,
    observed_at: datetime,
    *,
    creator: str = CREATOR,
    metric: tuple[str, str, str] = METRIC,
) -> OutcomeObservation:
    return OutcomeObservation(
        creator, post_id, *metric[:2], value, published_at, observed_at, metric[2]
    )


def _case(
    index: int,
    *,
    history_count: int = 10,
    value: float | None = 55.0,
    extra_outcomes: tuple[OutcomeObservation, ...] = (),
    target_observation_at: datetime | None = None,
    skew: int = 0,
) -> OutlookBacktestCase:
    cutoff = datetime(2026, 1, 20 + index, tzinfo=UTC)
    target_published = cutoff + timedelta(hours=1)
    matches = tuple(f"history-{index}-{i}" for i in range(history_count))
    comparable_set = ComparableSet(
        assessment_id=f"assessment-{index}",
        algorithm_version="comparable-retrieval-v1",
        config_version="comparable-ranking-config-v1",
        embedding_identity=IDENTITY,
        as_of=cutoff,
        state="matched",
        matches=tuple(
            ComparableMatch(
                post_id,
                0.9 - i * 0.001,
                RelevanceComponents(0.9, None, None, None, None),
                ("eligible",),
            )
            for i, post_id in enumerate(matches)
        ),
        exclusions=(CandidateExclusion("future", ("after_cutoff",)),),
        candidate_count=history_count,
        vector_candidate_count=history_count,
        eligible_count=history_count,
        excluded_count=0,
        truncated=False,
        coverage_limitations=(),
    )
    assessment = DraftAssessment(
        f"assessment-{index}",
        CREATOR,
        cutoff,
        _profile(cutoff - timedelta(minutes=5)),
        IDENTITY,
        (1.0, 0.0, 0.0),
        cutoff,
    )
    histories = tuple(
        _observation(
            post_id,
            float((i + 1) * 10 + skew),
            cutoff - timedelta(days=history_count - i + 2),
            cutoff - timedelta(days=history_count - i + 1),
        )
        for i, post_id in enumerate(matches)
    )
    request = OutlookRequest(
        assessment,
        "sha256:" + "b" * 64,
        comparable_set,
        histories + extra_outcomes,
    )
    target = _observation(
        f"target-{index}",
        value,
        target_published,
        target_observation_at or target_published + timedelta(days=1),
    )
    return OutlookBacktestCase(
        f"case-{index}",
        target.post_id,
        target_published,
        request,
        target,
        tuple(
            (post_id, outcome.published_at)
            for post_id, outcome in zip(matches, histories, strict=True)
        ),
    )


def _spec() -> BacktestSpec:
    return BacktestSpec(CREATOR, *METRIC, REPORT_CUTOFF, minimum_band_samples=1)


def test_walk_forward_reports_supported_reference_coverage_and_percentile_error() -> None:
    cases = (_case(0, value=55), _case(1, value=200, skew=100))
    result = evaluate_distribution_outlooks(cases, _spec())

    assert result.replay_count == 2
    assert result.scored_count == 2
    assert result.cases[0].reference_range_covered is True
    assert result.cases[1].reference_range_covered is False
    assert result.cases[0].absolute_percentile_error == pytest.approx(0.14, abs=0.02)
    assert result.cases[1].absolute_percentile_error > 40
    assert result.cases[0].direction_correct is False
    assert result.selection_basis == "unknown"
    assert any("selection bias" in note for note in result.limitations)
    assert result.evidence_bands[1].scored_count == 2
    assert result.evidence_bands[1].reference_range_coverage == pytest.approx(0.5)
    assert result.evidence_bands[1].direction_accuracy == 0.0


def test_future_observation_does_not_change_replayed_range_or_scores() -> None:
    base = _case(0)
    cutoff = base.outlook_request.assessment.as_of
    future = _observation(
        "history-0-9",
        100_000,
        cutoff - timedelta(days=2),
        cutoff + timedelta(hours=4),
    )
    with_future = replace(
        base,
        outlook_request=replace(
            base.outlook_request,
            outcomes=base.outlook_request.outcomes + (future,),
        ),
    )

    original = evaluate_distribution_outlooks((base,), _spec())
    replayed = evaluate_distribution_outlooks((with_future,), _spec())

    assert replayed.cases[0].reference_range_covered == original.cases[0].reference_range_covered
    assert (
        replayed.cases[0].absolute_percentile_error == original.cases[0].absolute_percentile_error
    )
    assert replayed.cases[0].prior_observation_count == original.cases[0].prior_observation_count
    assert (
        dict((item.name, item.count) for item in replayed.exclusions)[
            "future_or_unobserved_comparable_outcome"
        ]
        == 1
    )


def test_missing_and_incompatible_observations_are_excluded_not_imputed() -> None:
    base = _case(0)
    cutoff = base.outlook_request.assessment.as_of
    extras = (
        _observation(
            "history-0-missing", None, cutoff - timedelta(days=4), cutoff - timedelta(days=3)
        ),
        _observation(
            "history-0-other-definition",
            1_000_000,
            cutoff - timedelta(days=4),
            cutoff - timedelta(days=3),
            metric=("impressions", "impressions-v2", "age:24h"),
        ),
        _observation(
            "history-0-other-window",
            1_000_000,
            cutoff - timedelta(days=4),
            cutoff - timedelta(days=3),
            metric=("impressions", "impressions-v1", "mature"),
        ),
    )
    matches = base.outlook_request.comparable_set.matches + tuple(
        ComparableMatch(
            post_id, 0.8, RelevanceComponents(0.8, None, None, None, None), ("eligible",)
        )
        for post_id in ("history-0-missing", "history-0-other-definition", "history-0-other-window")
    )
    request = replace(
        base.outlook_request,
        comparable_set=replace(base.outlook_request.comparable_set, matches=matches),
        outcomes=base.outlook_request.outcomes + extras,
    )
    publication_times = base.comparable_publication_times + tuple(
        (item.post_id, item.published_at) for item in extras
    )

    report = evaluate_distribution_outlooks(
        (replace(base, outlook_request=request, comparable_publication_times=publication_times),),
        _spec(),
    )

    assert report.cases[0].reference_range_covered is True
    assert (
        dict((item.name, item.count) for item in report.exclusions)["incompatible_metric_or_window"]
        == 2
    )
    assert (
        dict((item.name, item.count) for item in report.exclusions)["missing_comparable_value"] == 1
    )
    assert report.cases[0].absolute_percentile_error is not None


def test_sparse_history_is_insufficient_and_does_not_emit_fake_scores() -> None:
    report = evaluate_distribution_outlooks((_case(0, history_count=2),), _spec())

    assert report.cases[0].evidence_strength == "Insufficient"
    assert report.cases[0].reference_range_covered is None
    assert report.cases[0].absolute_percentile_error is None
    assert report.evidence_bands[-1].scored_count == 0
    assert report.evidence_bands[-1].limitations


def test_outlier_sensitivity_reports_changed_coverage_without_relabeling_forecast() -> None:
    base = _case(0, history_count=10, value=55)
    outlier = _observation(
        "history-0-outlier",
        100_000,
        base.outlook_request.assessment.as_of - timedelta(days=2),
        base.outlook_request.assessment.as_of - timedelta(days=1),
    )
    matches = base.outlook_request.comparable_set.matches + (
        ComparableMatch(
            "history-0-outlier",
            0.89,
            RelevanceComponents(0.89, None, None, None, None),
            ("eligible",),
        ),
    )
    request = replace(
        base.outlook_request,
        comparable_set=replace(base.outlook_request.comparable_set, matches=matches),
        outcomes=base.outlook_request.outcomes + (outlier,),
    )
    report = evaluate_distribution_outlooks(
        (
            replace(
                base,
                outlook_request=request,
                comparable_publication_times=base.comparable_publication_times
                + ((outlier.post_id, outlier.published_at),),
            ),
        ),
        _spec(),
    )

    assert report.outlier_sensitivity.outliers_excluded == 1
    assert report.outlier_sensitivity.scored_count == 1
    assert report.outlier_sensitivity.reference_range_coverage == 1.0
    assert report.outlier_sensitivity.outlier_excluded_coverage == 1.0


def test_duplicate_records_and_cross_creator_observations_do_not_inflate_history() -> None:
    base = _case(0)
    existing = base.outlook_request.outcomes[0]
    duplicate = existing
    contaminant = replace(
        existing, creator_key="another-creator", post_id="history-0-foreign", value=999_999
    )
    matches = base.outlook_request.comparable_set.matches + (
        ComparableMatch(
            "history-0-foreign",
            0.9,
            RelevanceComponents(0.9, None, None, None, None),
            ("eligible",),
        ),
    )
    request = replace(
        base.outlook_request,
        comparable_set=replace(base.outlook_request.comparable_set, matches=matches),
        outcomes=base.outlook_request.outcomes + (duplicate, contaminant),
    )
    report = evaluate_distribution_outlooks(
        (
            replace(
                base,
                outlook_request=request,
                comparable_publication_times=base.comparable_publication_times
                + (("history-0-foreign", contaminant.published_at),),
            ),
        ),
        _spec(),
    )

    exclusions = dict((item.name, item.count) for item in report.exclusions)
    assert exclusions["duplicate_outcome_record"] == 2
    assert exclusions["cross_creator_outcome"] == 1
    assert report.cases[0].evidence_strength == "Moderate"
    assert report.cases[0].reference_range_covered is True


def test_missing_target_value_is_not_scored_as_zero() -> None:
    report = evaluate_distribution_outlooks((_case(0, value=None),), _spec())

    assert report.replay_count == 1
    assert report.scored_count == 0
    assert report.cases[0].target_value is None
    assert report.cases[0].reference_range_covered is None
    assert report.cases[0].absolute_percentile_error is None
    assert dict((item.name, item.count) for item in report.exclusions)["missing_target_value"] == 1


def test_percentile_error_has_its_own_denominator_and_adequacy() -> None:
    report = evaluate_distribution_outlooks(
        (_case(0, history_count=4, value=55), _case(1, history_count=4, value=None)),
        replace(_spec(), minimum_band_samples=2),
    )
    low = report.evidence_bands[2]

    assert low.replay_count == 2
    assert low.scored_count == 0
    assert low.percentile_scored_count == 1
    assert low.median_absolute_percentile_error is not None
    assert low.percentile_error_sample_adequate is False
    assert low.direction_scored_count == 0


def test_scoring_history_matches_baseline_timestamp_and_value_eligibility() -> None:
    base = _case(0)
    cutoff = base.outlook_request.assessment.as_of
    negative = _observation(
        "history-0-negative", -50, cutoff - timedelta(days=3), cutoff - timedelta(days=2)
    )
    impossible = _observation(
        "history-0-impossible",
        1_000_000,
        cutoff - timedelta(days=2),
        cutoff - timedelta(days=3),
    )
    additions = (negative, impossible)
    matches = base.outlook_request.comparable_set.matches + tuple(
        ComparableMatch(
            item.post_id,
            0.8,
            RelevanceComponents(0.8, None, None, None, None),
            ("eligible",),
        )
        for item in additions
    )
    request = replace(
        base.outlook_request,
        comparable_set=replace(base.outlook_request.comparable_set, matches=matches),
        outcomes=base.outlook_request.outcomes + additions,
    )
    report = evaluate_distribution_outlooks(
        (
            replace(
                base,
                outlook_request=request,
                comparable_publication_times=base.comparable_publication_times
                + tuple((item.post_id, item.published_at) for item in additions),
            ),
        ),
        _spec(),
    )

    assert report.cases[0].prior_observation_count == 10
    exclusions = dict((item.name, item.count) for item in report.exclusions)
    assert exclusions["negative_comparable_value"] == 1
    assert exclusions["observation_before_publication"] == 1


def test_target_observation_cannot_precede_publication() -> None:
    base = _case(0)
    impossible_target = replace(
        base,
        target_observation=replace(
            base.target_observation,
            observed_at=base.target_published_at - timedelta(minutes=1),
        ),
    )

    with pytest.raises(ValueError, match="cannot precede target publication"):
        evaluate_distribution_outlooks((impossible_target,), _spec())


def test_report_is_reproducible_chronological_and_groups_each_evidence_band() -> None:
    cases = (
        _case(2, history_count=21, value=55),
        _case(0, history_count=4, value=15),
        _case(1, history_count=10, value=55),
    )
    one = evaluate_distribution_outlooks(cases, _spec())
    two = evaluate_distribution_outlooks(tuple(reversed(cases)), _spec())
    shuffled_outcomes = tuple(
        replace(
            case,
            outlook_request=replace(
                case.outlook_request,
                outcomes=tuple(reversed(case.outlook_request.outcomes)),
            ),
        )
        for case in cases
    )
    three = evaluate_distribution_outlooks(shuffled_outcomes, _spec())

    assert one == two
    assert one == three
    assert [item.case_id for item in one.cases] == ["case-0", "case-1", "case-2"]
    assert [item.evidence_strength for item in one.cases] == ["Low", "Moderate", "High"]
    assert [item.evidence_strength for item in one.evidence_bands] == [
        "High",
        "Moderate",
        "Low",
        "Insufficient",
    ]


def test_future_creator_context_and_future_comparable_are_rejected() -> None:
    base = _case(0)
    future_context = extract_post_profile(
        PostProfileInput(
            text="Synthetic target post.",
            observed_at=base.outlook_request.assessment.as_of + timedelta(minutes=1),
            features_as_of=base.outlook_request.assessment.as_of + timedelta(minutes=1),
            creator_key=CREATOR,
        )
    )
    with pytest.raises(ValueError, match="after assessment cutoff"):
        replace(
            base.outlook_request,
            assessment=replace(base.outlook_request.assessment, profile=future_context),
        )

    future_published = replace(
        base,
        comparable_publication_times=(
            (
                base.comparable_publication_times[0][0],
                base.outlook_request.assessment.as_of + timedelta(minutes=1),
            ),
        )
        + base.comparable_publication_times[1:],
    )
    with pytest.raises(ValueError, match="published after"):
        evaluate_distribution_outlooks((future_published,), _spec())

    naive_publication_time = replace(
        base,
        comparable_publication_times=(
            (base.comparable_publication_times[0][0], datetime(2026, 1, 1)),
        )
        + base.comparable_publication_times[1:],
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_distribution_outlooks((naive_publication_time,), _spec())
