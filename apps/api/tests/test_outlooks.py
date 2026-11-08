"""Synthetic behavior tests for deterministic creator decision outlooks."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from bipme.intelligence.baselines import OutcomeObservation
from bipme.intelligence.embeddings import EmbeddingIdentity
from bipme.intelligence.outlooks import (
    OutlookConfig,
    OutlookRequest,
    build_distribution_outlook,
)
from bipme.intelligence.post_profiles import PostProfile, PostProfileInput, extract_post_profile
from bipme.intelligence.retrieval import (
    CandidateExclusion,
    ComparableMatch,
    ComparableSet,
    DraftAssessment,
    RelevanceComponents,
)

AS_OF = datetime(2026, 1, 20, 12, tzinfo=UTC)
CREATOR = "creator-1"
IDENTITY = EmbeddingIdentity("test/model", "a" * 40, 3, "test-v1")
FINGERPRINT = "sha256:" + "b" * 64


def profile(topic: str | None = "python") -> PostProfile:
    return extract_post_profile(
        PostProfileInput(
            text="A short synthetic historical post.",
            observed_at=AS_OF - timedelta(days=3),
            features_as_of=AS_OF - timedelta(days=3),
            creator_key=CREATOR,
            declared_topic=topic,
            declared_intent="inform",
            topology="original",
            thread_role="single",
            media_types=(),
        )
    )


def observation(
    post_id: str,
    value: float | None,
    *,
    metric: str = "impressions",
    definition: str = "impressions-v1",
    window: str = "age:24h",
    observed_at: datetime | None = None,
    published_at: datetime | None = None,
) -> OutcomeObservation:
    published = published_at or AS_OF - timedelta(days=2)
    return OutcomeObservation(
        creator_key=CREATOR,
        post_id=post_id,
        metric=metric,
        metric_definition=definition,
        value=value,
        published_at=published,
        observed_at=observed_at or published + timedelta(days=1),
        window=window,
    )


def request(
    values: tuple[float | None, ...] = tuple(float(n * 10) for n in range(1, 11)),
    *,
    topics: tuple[str | None, ...] | None = None,
    matches: tuple[str, ...] | None = None,
    outcomes: tuple[OutcomeObservation, ...] | None = None,
) -> OutlookRequest:
    ids = matches or tuple(f"post-{index:02}" for index in range(len(values)))
    relevance = {post_id: 0.9 - index * 0.01 for index, post_id in enumerate(ids)}
    comparable_set = ComparableSet(
        assessment_id="draft-1",
        algorithm_version="comparable-retrieval-v1",
        config_version="comparable-ranking-config-v1",
        embedding_identity=IDENTITY,
        as_of=AS_OF,
        state="matched" if ids else "no_match",
        matches=tuple(
            ComparableMatch(
                post_id=post_id,
                relevance=relevance[post_id],
                components=RelevanceComponents(0.9, None, None, None, None),
                inclusion_reasons=("eligible",),
            )
            for post_id in ids
        ),
        exclusions=(),
        candidate_count=len(ids),
        vector_candidate_count=len(ids),
        eligible_count=len(ids),
        excluded_count=0,
        truncated=False,
        coverage_limitations=(),
    )
    assessment = DraftAssessment(
        assessment_id="draft-1",
        creator_key=CREATOR,
        as_of=AS_OF,
        profile=profile(),
        embedding_identity=IDENTITY,
        embedding=(1.0, 0.0, 0.0),
        embedding_observed_at=AS_OF,
    )
    actual_outcomes = outcomes or tuple(
        observation(post_id, values[index]) for index, post_id in enumerate(ids)
    )
    actual_topics = topics or tuple("python" for _ in ids)
    return OutlookRequest(
        assessment=assessment,
        content_fingerprint=FINGERPRINT,
        comparable_set=comparable_set,
        outcomes=actual_outcomes,
        comparable_profiles=tuple(
            (post_id, profile(actual_topics[index])) for index, post_id in enumerate(ids)
        ),
    )


def test_supported_metric_returns_ordered_traceable_evidence_and_historical_range() -> None:
    result = build_distribution_outlook(request())

    assert result.decision_state == "supported"
    assert result.assessment_id == "draft-1"
    assert result.content_fingerprint == FINGERPRINT
    assert [item.post_id for item in result.comparable_evidence] == [
        f"post-{index:02}" for index in range(10)
    ]
    assert result.comparable_evidence[0].components.semantic == 0.9
    assert result.comparable_evidence[0].retrieval_position == 1
    metric = result.metrics[0]
    assert (metric.metric, metric.metric_definition, metric.window) == (
        "impressions",
        "impressions-v1",
        "age:24h",
    )
    assert metric.evidence_strength == "Moderate"
    assert metric.coverage == 1.0
    expected_weights = tuple(0.9 - index * 0.01 for index in range(10))
    assert metric.effective_sample_size == pytest.approx(
        sum(expected_weights) ** 2 / sum(weight * weight for weight in expected_weights)
    )
    assert metric.outlook is not None
    assert (metric.outlook.lower_p25, metric.outlook.median_p50, metric.outlook.upper_p75) == (
        30.0,
        50.0,
        80.0,
    )
    assert "historical" in metric.outlook.kind


def test_repeatability_observation_explains_supported_history_without_causal_claims() -> None:
    result = build_distribution_outlook(request())

    assert result.observations
    repeatability = next(item for item in result.observations if item.kind == "repeatability")
    assert repeatability.supporting_post_ids == tuple(f"post-{i:02}" for i in range(10))
    assert repeatability.metric == "impressions"
    assert repeatability.window == "age:24h"
    assert repeatability.evidence_strength == "Moderate"
    assert repeatability.evidence_statistics is not None
    assert repeatability.evidence_statistics.consistency_ratio == 1.0
    forbidden_claims = ("will increase", "causes", "guarantees", "algorithm favors")
    assert not any(claim in repeatability.explanation.casefold() for claim in forbidden_claims)


def test_repeated_topic_association_can_offer_one_measurable_optional_experiment() -> None:
    topics = tuple("python" if index < 5 else "finance" for index in range(10))
    result = build_distribution_outlook(request(topics=topics))

    assert result.suggestion is not None
    assert result.suggestion.kind == "experiment_hypothesis"
    assert result.suggestion.variable == "declared_topic"
    assert result.suggestion.value == "python"
    assert set(result.suggestion.supporting_post_ids) == {f"post-{i:02}" for i in range(5)}
    assert result.suggestion.metric == "impressions"
    assert result.suggestion.window == "age:24h"
    assert result.suggestion.is_optional is True
    assert "experiment" in result.suggestion.label.casefold()
    assert "guarantee" not in result.suggestion.rationale.casefold()
    assert "does not show that the feature caused" in result.suggestion.rationale


def test_suggestion_is_absent_without_a_repeated_comparable_pattern() -> None:
    topics = tuple(f"topic-{index}" for index in range(10))
    assert build_distribution_outlook(request(topics=topics)).suggestion is None


def test_suggestion_is_withheld_when_either_association_group_is_sparse() -> None:
    topics = tuple("python" if index < 2 else "finance" for index in range(10))
    result = build_distribution_outlook(request(topics=topics))

    assert result.metrics[0].outlook is not None
    assert result.suggestion is None


def test_single_viral_outlier_is_identified_and_does_not_move_robust_range() -> None:
    values = (10.0,) * 9 + (1_000_000.0,)
    result = build_distribution_outlook(request(values))

    metric = result.metrics[0]
    assert metric.outlook is not None
    assert metric.outlook.median_p50 == 10.0
    outlier = next(item for item in result.observations if item.kind == "outlier")
    assert outlier.supporting_post_ids == ("post-09",)
    assert outlier.evidence_statistics is not None
    assert outlier.evidence_statistics.outlier_count == 1
    assert any("outlier" in item.casefold() for item in outlier.limitations)


def test_low_sample_is_described_but_has_no_numeric_outlook_or_suggestion() -> None:
    result = build_distribution_outlook(request((10.0, 20.0, 30.0, 40.0)))

    assert result.decision_state == "insufficient_evidence"
    assert result.metrics[0].evidence_strength == "Low"
    assert result.metrics[0].outlook is None
    assert result.suggestion is None
    assert any(item.kind == "coverage_limitation" for item in result.observations)


def test_missing_outcomes_reduce_coverage_and_prevent_unsupported_range() -> None:
    matches = tuple(f"post-{index:02}" for index in range(10))
    outcomes = tuple(
        observation(post_id, float(index * 10)) for index, post_id in enumerate(matches[:5])
    )
    result = build_distribution_outlook(request(matches=matches, outcomes=outcomes))

    assert result.metrics[0].coverage == 0.5
    assert result.metrics[0].outlook is None
    assert any("coverage" in reason.casefold() for reason in result.metrics[0].limitations)


def test_explicit_missing_metric_is_not_imputed_or_counted_as_zero() -> None:
    matches = tuple(f"post-{index:02}" for index in range(10))
    outcomes = tuple(
        observation(post_id, None if index == 0 else float((index + 1) * 10))
        for index, post_id in enumerate(matches)
    )
    result = build_distribution_outlook(request(matches=matches, outcomes=outcomes))

    metric = result.metrics[0]
    assert metric.coverage == 0.9
    assert metric.eligible_post_count == 9
    assert "post-00" not in metric.supporting_post_ids
    assert dict(metric.exclusion_counts)["missing_metric_or_window"] == 1
    assert metric.outlook is not None
    assert metric.outlook.lower_p25 == 40.0


def test_metric_definitions_and_windows_are_never_combined() -> None:
    outcomes = tuple(
        observation(f"post-{i:02}", float(i + 1), definition="impressions-v1", window="age:1h")
        for i in range(10)
    ) + tuple(
        observation(
            f"post-{i:02}", float((i + 1) * 100), definition="impressions-v2", window="age:24h"
        )
        for i in range(10)
    )
    result = build_distribution_outlook(request(outcomes=outcomes))

    assert [(item.metric_definition, item.window) for item in result.metrics] == [
        ("impressions-v1", "age:1h"),
        ("impressions-v2", "age:24h"),
    ]
    assert [item.outlook.lower_p25 for item in result.metrics if item.outlook] == [3.0, 300.0]


def test_future_observations_do_not_leak_into_ranges_or_evidence_ids() -> None:
    matches = tuple(f"post-{index:02}" for index in range(10))
    outcomes = tuple(
        observation(
            post_id,
            float((index + 1) * 10),
            observed_at=AS_OF + timedelta(minutes=1) if index >= 2 else None,
        )
        for index, post_id in enumerate(matches)
    )
    result = build_distribution_outlook(request(matches=matches, outcomes=outcomes))

    metric = result.metrics[0]
    assert metric.eligible_post_count == 2
    assert metric.outlook is None
    assert set(metric.supporting_post_ids) == {"post-00", "post-01"}
    assert dict(metric.exclusion_counts)["observed_after_as_of"] == 8


def test_future_publications_do_not_enter_the_assessment_baseline() -> None:
    matches = tuple(f"post-{index:02}" for index in range(10))
    outcomes = tuple(
        observation(
            post_id,
            float((index + 1) * 10),
            published_at=AS_OF + timedelta(minutes=1) if index >= 2 else None,
        )
        for index, post_id in enumerate(matches)
    )
    result = build_distribution_outlook(request(matches=matches, outcomes=outcomes))

    metric = result.metrics[0]
    assert metric.eligible_post_count == 2
    assert metric.outlook is None
    assert dict(metric.exclusion_counts)["published_after_as_of"] == 8


def test_duplicate_observations_are_excluded_instead_of_double_counted() -> None:
    base = tuple(observation(f"post-{i:02}", float((i + 1) * 10)) for i in range(10))
    duplicate = observation("post-00", 999.0)
    result = build_distribution_outlook(request(outcomes=base + (duplicate,)))

    metric = result.metrics[0]
    assert metric.eligible_post_count == 9
    assert dict(metric.exclusion_counts)["duplicate_post_metric_window"] == 2
    assert "post-00" not in metric.supporting_post_ids


def test_zero_relevance_outcome_is_excluded_and_reported() -> None:
    base = request()
    changed_matches = (
        replace(base.comparable_set.matches[0], relevance=0.0),
        *base.comparable_set.matches[1:],
    )
    result = build_distribution_outlook(
        OutlookRequest(
            assessment=base.assessment,
            content_fingerprint=base.content_fingerprint,
            comparable_set=replace(base.comparable_set, matches=changed_matches),
            outcomes=base.outcomes,
            comparable_profiles=base.comparable_profiles,
        )
    )

    assert result.metrics[0].outlook is not None
    assert "post-00" not in result.metrics[0].supporting_post_ids
    assert dict(result.metrics[0].exclusion_counts)["zero_relevance_outcomes"] == 1
    assert dict(result.exclusions)["zero_relevance_comparables"] == 1


def test_outcomes_for_non_comparables_cannot_change_comparable_order_or_relevance() -> None:
    base = request()
    extra = observation("not-selected", 1_000_000.0)
    result = build_distribution_outlook(
        OutlookRequest(
            assessment=base.assessment,
            content_fingerprint=base.content_fingerprint,
            comparable_set=base.comparable_set,
            outcomes=base.outcomes + (extra,),
            comparable_profiles=base.comparable_profiles,
        )
    )

    assert [(item.post_id, item.relevance) for item in result.comparable_evidence] == [
        (item.post_id, item.relevance)
        for item in build_distribution_outlook(base).comparable_evidence
    ]
    assert result.metrics[0].outlook == build_distribution_outlook(base).metrics[0].outlook


def test_retrieval_exclusion_reasons_and_coverage_metadata_are_preserved() -> None:
    base = request()
    excluded = CandidateExclusion("excluded-post", ("below_minimum_relevance",))
    comparable_set = replace(
        base.comparable_set,
        exclusions=(excluded,),
        candidate_count=11,
        vector_candidate_count=11,
        excluded_count=1,
    )
    result = build_distribution_outlook(
        OutlookRequest(
            assessment=base.assessment,
            content_fingerprint=base.content_fingerprint,
            comparable_set=comparable_set,
            outcomes=base.outcomes,
            comparable_profiles=base.comparable_profiles,
        )
    )

    assert result.retrieval_exclusions == (excluded,)
    assert result.retrieval_candidate_count == 11
    assert result.retrieval_vector_candidate_count == 11
    assert result.retrieval_excluded_count == 1


def test_incomplete_retrieval_coverage_withholds_range_and_suggestion() -> None:
    base = request()
    comparable_set = replace(
        base.comparable_set,
        truncated=True,
        coverage_limitations=("candidate page truncated",),
    )
    result = build_distribution_outlook(
        OutlookRequest(
            assessment=base.assessment,
            content_fingerprint=base.content_fingerprint,
            comparable_set=comparable_set,
            outcomes=base.outcomes,
            comparable_profiles=base.comparable_profiles,
        )
    )

    assert result.decision_state == "insufficient_evidence"
    assert result.metrics[0].outlook is None
    assert result.suggestion is None
    assert result.retrieval_truncated is True
    assert result.retrieval_coverage_limitations == ("candidate page truncated",)


def test_no_comparables_returns_explicit_insufficient_state_and_no_advice() -> None:
    result = build_distribution_outlook(request(values=(), matches=(), outcomes=()))

    assert result.decision_state == "insufficient_evidence"
    assert result.comparable_evidence == ()
    assert result.metrics == ()
    assert result.suggestion is None
    assert result.observations == ()
    assert result.limitations


def test_invalid_or_mismatched_assessment_and_fingerprint_are_rejected() -> None:
    base = request()
    with pytest.raises(ValueError, match="SHA-256"):
        OutlookRequest(
            assessment=base.assessment,
            content_fingerprint="not-a-hash",
            comparable_set=base.comparable_set,
            outcomes=base.outcomes,
        )


def test_unknown_retrieval_version_abstains_from_draft_specific_interpretations() -> None:
    base = request()
    unknown_set = replace(base.comparable_set, algorithm_version="unknown-retrieval-v99")
    result = build_distribution_outlook(
        OutlookRequest(
            assessment=base.assessment,
            content_fingerprint=base.content_fingerprint,
            comparable_set=unknown_set,
            outcomes=base.outcomes,
            comparable_profiles=base.comparable_profiles,
        )
    )

    assert result.decision_state == "insufficient_evidence"
    assert result.comparable_evidence
    assert all(metric.outlook is None for metric in result.metrics)
    assert result.observations == ()
    assert result.suggestion is None
    assert any("version is unknown" in item for item in result.limitations)


def test_profile_features_after_cutoff_are_rejected_at_the_service_boundary() -> None:
    base = request()
    invalid_profile = replace(profile(), features_as_of=AS_OF + timedelta(seconds=1))
    with pytest.raises(ValueError, match="after the assessment cutoff"):
        OutlookRequest(
            assessment=base.assessment,
            content_fingerprint=base.content_fingerprint,
            comparable_set=base.comparable_set,
            outcomes=base.outcomes,
            comparable_profiles=(("post-00", invalid_profile),),
        )


def test_missing_all_outcomes_returns_specific_insufficient_reason() -> None:
    base = request()
    result = build_distribution_outlook(
        OutlookRequest(
            assessment=base.assessment,
            content_fingerprint=base.content_fingerprint,
            comparable_set=base.comparable_set,
            outcomes=(),
            comparable_profiles=base.comparable_profiles,
        )
    )

    assert result.decision_state == "insufficient_evidence"
    assert result.metrics == ()
    assert result.suggestion is None
    assert any("No outcome observations" in item for item in result.limitations)
    mismatch = DraftAssessment(
        assessment_id="other-draft",
        creator_key=CREATOR,
        as_of=AS_OF,
        profile=profile(),
        embedding_identity=IDENTITY,
        embedding=(1.0, 0.0, 0.0),
        embedding_observed_at=AS_OF,
    )
    with pytest.raises(ValueError, match="assessment"):
        OutlookRequest(
            assessment=mismatch,
            content_fingerprint=FINGERPRINT,
            comparable_set=base.comparable_set,
            outcomes=base.outcomes,
        )


def test_response_serialization_is_stable_and_original_input_is_immutable() -> None:
    source = request()
    result = build_distribution_outlook(source)

    assert result.to_json() == build_distribution_outlook(source).to_json()
    encoded = json.loads(result.to_json())
    assert encoded["content_fingerprint"] == FINGERPRINT
    assert encoded["assessment_cutoff"] == AS_OF.isoformat()
    assert "text" not in result.to_json()
    assert result.decision_algorithm_version == "distribution-outlook-v1"
    assert result.decision_config_version.startswith("distribution-outlook-config-v1:")
    assert (
        OutlookConfig(minimum_metric_coverage=0.5).config_version != OutlookConfig().config_version
    )
    with pytest.raises(FrozenInstanceError):
        source.assessment.assessment_id = "changed"  # type: ignore[misc]
