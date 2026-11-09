"""Synthetic tests for deterministic version-aware postmortem comparisons."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from bipme.intelligence.baselines import OutcomeObservation
from bipme.intelligence.embeddings import EmbeddingIdentity
from bipme.intelligence.outlooks import OutlookRequest, build_distribution_outlook
from bipme.intelligence.post_profiles import PostProfileInput, extract_post_profile
from bipme.intelligence.postmortems import (
    AcceptedHypothesis,
    OriginalAssessment,
    PostmortemRequest,
    PublishedPost,
    build_postmortem,
)
from bipme.intelligence.retrieval import (
    ComparableMatch,
    ComparableSet,
    DraftAssessment,
    RelevanceComponents,
)

CREATOR = "creator-1"
AS_OF = datetime(2026, 1, 20, 12, tzinfo=UTC)
PUBLISHED_AT = AS_OF + timedelta(hours=1)
AGE = timedelta(hours=24)
FINGERPRINT = "sha256:" + "b" * 64
METRIC = "impressions"
DEFINITION = "impressions-v1|unit=impressions"
WINDOW = "age_aligned:age:24h"
IDENTITY = EmbeddingIdentity("synthetic/model", "a" * 40, 3, "synthetic-v1")


def _profile(at: datetime):
    return extract_post_profile(
        PostProfileInput(
            text="Synthetic assessed and historical post.",
            observed_at=at,
            features_as_of=at,
            creator_key=CREATOR,
            declared_topic="engineering",
            declared_intent="inform",
            topology="original",
            thread_role="single",
            media_types=(),
        )
    )


def _outcome(
    post_id: str,
    value: float | None,
    published_at: datetime,
    *,
    creator_key: str = CREATOR,
    metric: str = METRIC,
    definition: str = DEFINITION,
    window: str = WINDOW,
    age: timedelta = AGE,
) -> OutcomeObservation:
    return OutcomeObservation(
        creator_key=creator_key,
        post_id=post_id,
        metric=metric,
        metric_definition=definition,
        value=value,
        published_at=published_at,
        observed_at=published_at + age,
        window=window,
    )


def _request(
    *,
    history_count: int = 10,
    target_value: float | None = 95.0,
    hypothesis_direction: str = "higher",
    target_age: timedelta = AGE,
    target_window: str = WINDOW,
    target_definition: str = DEFINITION,
    published_creator: str = CREATOR,
    source_assessment_id: str = "assessment-row-1",
    version_match_state: str = "match",
    published_fingerprint: str | None = FINGERPRINT,
    future_target: bool = False,
    duplicate_target: bool = False,
    extra_historical: tuple[OutcomeObservation, ...] = (),
) -> PostmortemRequest:
    comparable_ids = tuple(f"history-{i}" for i in range(history_count))
    comparable_set = ComparableSet(
        assessment_id="assessment-1",
        algorithm_version="comparable-retrieval-v1",
        config_version="comparable-ranking-config-v1",
        embedding_identity=IDENTITY,
        as_of=AS_OF,
        state="matched" if comparable_ids else "no_match",
        matches=tuple(
            ComparableMatch(
                post_id,
                0.9 - index * 0.01,
                RelevanceComponents(0.9, None, None, None, None),
                ("eligible",),
            )
            for index, post_id in enumerate(comparable_ids)
        ),
        exclusions=(),
        candidate_count=history_count,
        vector_candidate_count=history_count,
        eligible_count=history_count,
        excluded_count=0,
        truncated=False,
        coverage_limitations=(),
    )
    draft = DraftAssessment(
        assessment_id="assessment-1",
        creator_key=CREATOR,
        as_of=AS_OF,
        profile=_profile(AS_OF - timedelta(minutes=5)),
        embedding_identity=IDENTITY,
        embedding=(1.0, 0.0, 0.0),
        embedding_observed_at=AS_OF,
    )
    historical = (
        tuple(
            _outcome(
                post_id,
                float((index + 1) * 10),
                AS_OF - timedelta(days=history_count - index + 2),
            )
            for index, post_id in enumerate(comparable_ids)
        )
        + extra_historical
    )
    outlook = build_distribution_outlook(
        OutlookRequest(draft, FINGERPRINT, comparable_set, historical[:history_count])
    )
    hypothesis = (
        AcceptedHypothesis(
            question="Does the chosen format increase impressions?",
            metric=METRIC,
            metric_definition="impressions-v1",
            unit="impressions",
            window_kind="age_aligned",
            window_key="age:24h",
            expected_direction=hypothesis_direction,  # type: ignore[arg-type]
        )
        if hypothesis_direction
        else None
    )
    assessment = OriginalAssessment(
        assessment_id="assessment-1",
        assessment_record_id="assessment-row-1",
        creator_key=CREATOR,
        assessed_at=AS_OF,
        content_fingerprint=FINGERPRINT,
        outlook=outlook,
        accepted_hypothesis=hypothesis,
    )
    published = PublishedPost(
        creator_key=published_creator,
        post_id="published-1",
        published_at=PUBLISHED_AT,
        source_assessment_id=source_assessment_id,
        version_match_state=version_match_state,  # type: ignore[arg-type]
        content_fingerprint=published_fingerprint,
    )
    observed_at = PUBLISHED_AT + target_age
    if future_target:
        observed_at += timedelta(days=3)
    target_observation = OutcomeObservation(
        creator_key=published_creator,
        post_id="published-1",
        metric=METRIC,
        metric_definition=target_definition,
        value=target_value,
        published_at=PUBLISHED_AT,
        observed_at=observed_at,
        window=target_window,
    )
    if duplicate_target:
        observed = (target_observation, target_observation)
    else:
        observed = (target_observation,)
    evaluation_as_of = (
        PUBLISHED_AT + target_age - timedelta(minutes=1)
        if future_target
        else PUBLISHED_AT + target_age + timedelta(days=1)
    )
    return PostmortemRequest(
        assessment=assessment,
        published_post=published,
        historical_outcomes=historical,
        published_outcomes=observed,
        evaluated_at=evaluation_as_of,
    )


def test_matching_version_and_equal_age_observations_score_forecast_and_hypothesis() -> None:
    result = build_postmortem(_request())

    assert result.version_state == "verified"
    comparison = result.metric_comparisons[0]
    assert comparison.status == "scored"
    assert comparison.observed_value == 95.0
    assert comparison.deviation_from_median == 45.0
    assert comparison.within_reference_range is False
    assert comparison.relative_percentile is not None
    assert comparison.matched_sample_count == 10
    assert set(comparison.comparison_post_ids) == {f"history-{i}" for i in range(10)}
    assert {item.post_id for item in comparison.comparison_observations} == set(
        comparison.comparison_post_ids
    )
    assert all(
        item.observed_at - item.published_at == AGE for item in comparison.comparison_observations
    )
    assert result.hypothesis_evaluation is not None
    assert result.hypothesis_evaluation.status == "supported"
    assert "caus" in " ".join(result.limitations).casefold()


@pytest.mark.parametrize(
    ("value", "expected"),
    [(5.0, "contradicted"), (50.0, "inconclusive")],
)
def test_hypothesis_direction_uses_equal_age_history_without_causal_claims(
    value: float, expected: str
) -> None:
    result = build_postmortem(_request(target_value=value))

    assert result.hypothesis_evaluation is not None
    assert result.hypothesis_evaluation.status == expected


def test_directionless_accepted_hypothesis_is_inconclusive() -> None:
    result = build_postmortem(_request(hypothesis_direction="no_direction"))

    assert result.hypothesis_evaluation is not None
    assert result.hypothesis_evaluation.status == "inconclusive"


def test_malformed_hypothesis_direction_is_rejected_at_the_input_boundary() -> None:
    with pytest.raises(ValueError, match="expected_direction"):
        AcceptedHypothesis(
            question="Does the chosen format increase impressions?",
            metric=METRIC,
            metric_definition="impressions-v1",
            unit="impressions",
            window_kind="age_aligned",
            window_key="age:24h",
            expected_direction="sideways",  # type: ignore[arg-type]
        )


def test_changed_or_unverified_publication_keeps_observation_but_withholds_scoring() -> None:
    request = _request(version_match_state="mismatch", published_fingerprint="sha256:" + "c" * 64)

    result = build_postmortem(request)

    assert result.observed_outcomes == request.published_outcomes
    assert result.metric_comparisons[0].observed_value == 95.0
    assert result.metric_comparisons[0].status == "version_unverified"
    assert result.metric_comparisons[0].deviation_from_median is None
    assert result.hypothesis_evaluation is not None
    assert result.hypothesis_evaluation.status == "inconclusive"


def test_different_content_fingerprint_cannot_score_even_if_link_state_claims_match() -> None:
    result = build_postmortem(_request(published_fingerprint="sha256:" + "c" * 64))

    assert result.version_state == "unverified"
    assert result.metric_comparisons[0].status == "version_unverified"
    assert result.metric_comparisons[0].observed_value == 95.0


@pytest.mark.parametrize(
    "postmortem_request",
    [
        _request(target_age=timedelta(hours=23)),
        _request(target_window="age_aligned:age:1h"),
        _request(target_definition="impressions-v2|unit=impressions"),
        _request(target_value=None),
        _request(future_target=True),
        _request(duplicate_target=True),
    ],
    ids=[
        "age-mismatch",
        "window-mismatch",
        "definition-mismatch",
        "missing",
        "future",
        "duplicate",
    ],
)
def test_unsupported_observation_comparisons_are_unavailable(
    postmortem_request: PostmortemRequest,
) -> None:
    result = build_postmortem(postmortem_request)

    assert result.metric_comparisons[0].status == "unavailable"
    assert result.metric_comparisons[0].deviation_from_median is None
    assert result.hypothesis_evaluation is not None
    assert result.hypothesis_evaluation.status == "inconclusive"
    if any(
        item.observed_at > postmortem_request.evaluated_at
        for item in postmortem_request.published_outcomes
    ):
        assert result.observed_outcomes == ()
        assert any("after the postmortem cutoff" in item for item in result.limitations)


def test_sparse_historical_reference_data_does_not_invent_comparison() -> None:
    result = build_postmortem(_request(history_count=2))

    assert result.metric_comparisons[0].status == "unavailable"
    assert result.metric_comparisons[0].relative_percentile is None
    assert result.hypothesis_evaluation is not None
    assert result.hypothesis_evaluation.status == "inconclusive"
    assert result.metric_comparisons[0].matched_sample_count == 2


def test_absent_published_metric_is_unavailable_without_substituting_other_series() -> None:
    request = _request()
    request = replace(request, published_outcomes=())

    result = build_postmortem(request)

    assert result.metric_comparisons[0].status == "unavailable"
    assert result.metric_comparisons[0].observed_value is None
    assert result.metric_comparisons[0].comparison_observations == ()
    assert result.hypothesis_evaluation is not None
    assert result.hypothesis_evaluation.status == "inconclusive"


def test_cross_creator_publication_and_history_cannot_be_scored() -> None:
    foreign = _outcome(
        "foreign-history",
        100_000.0,
        AS_OF - timedelta(days=20),
        creator_key="creator-2",
    )
    request = _request(published_creator="creator-2", extra_historical=(foreign,))

    result = build_postmortem(request)

    assert result.version_state == "unverified"
    assert result.metric_comparisons[0].status == "version_unverified"
    assert "creator" in " ".join(result.metric_comparisons[0].limitations).casefold()
    assert "foreign-history" not in result.metric_comparisons[0].comparison_post_ids


def test_cross_creator_historical_observation_is_excluded_from_same_creator_comparison() -> None:
    foreign = _outcome(
        "foreign-history",
        100_000.0,
        AS_OF - timedelta(days=20),
        creator_key="creator-2",
    )

    result = build_postmortem(_request(extra_historical=(foreign,)))

    comparison = result.metric_comparisons[0]
    assert result.version_state == "verified"
    assert comparison.status == "scored"
    assert len(comparison.comparison_post_ids) == 10
    assert "foreign-history" not in comparison.comparison_post_ids
    assert any("cross-creator" in item.casefold() for item in comparison.limitations)


def test_source_assessment_identity_mismatch_is_inconclusive() -> None:
    result = build_postmortem(_request(source_assessment_id="different-assessment"))

    assert result.version_state == "unverified"
    assert result.metric_comparisons[0].status == "version_unverified"
    assert result.hypothesis_evaluation is not None
    assert result.hypothesis_evaluation.status == "inconclusive"


def test_outlook_assessment_identity_must_match_at_input_construction() -> None:
    request = _request()
    with pytest.raises(ValueError, match="outlook assessment identity"):
        replace(request.assessment, assessment_id="different-assessment")


def test_duplicate_historical_observations_are_excluded_and_reported() -> None:
    request = _request()
    duplicated = replace(
        request,
        historical_outcomes=request.historical_outcomes + (request.historical_outcomes[0],),
    )

    result = build_postmortem(duplicated)

    assert result.metric_comparisons[0].matched_sample_count == 9
    assert any(
        "duplicate" in reason.casefold() for reason in result.metric_comparisons[0].limitations
    )


def test_result_is_deterministic_and_retains_original_outlook_and_observations() -> None:
    request = _request()
    first = build_postmortem(request)
    second = build_postmortem(request)

    assert first == second
    assert first.original_outlook is request.assessment.outlook
    assert first.observed_outcomes == request.published_outcomes


def test_unrelated_published_records_do_not_leak_into_the_postmortem_result() -> None:
    request = _request()
    unrelated = _outcome("other-post", 5.0, PUBLISHED_AT)
    request = replace(request, published_outcomes=request.published_outcomes + (unrelated,))

    result = build_postmortem(request)

    assert result.observed_outcomes == request.published_outcomes[:1]
    assert any("unrelated" in item for item in result.limitations)
    assert not any("after the postmortem cutoff" in item for item in result.limitations)
