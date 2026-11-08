"""Synthetic deterministic tests for comparable retrieval; no database or X data."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from bipme.intelligence.embeddings import EmbeddingIdentity
from bipme.intelligence.post_profiles import PostProfileInput, extract_post_profile
from bipme.intelligence.retrieval import (
    ComparableCandidate,
    DraftAssessment,
    InMemoryVectorCandidateSource,
    MetricEligibilityEvidence,
    MetricRequirement,
    RankingWeights,
    RetrievalConfig,
    VectorCandidateQuery,
    rank_comparable_candidates,
    retrieve_comparables,
)

AS_OF = datetime(2026, 1, 20, 12, tzinfo=UTC)
REV = "a" * 40
IDENTITY = EmbeddingIdentity("test/model", REV, 3, "test-preprocess-v1")


def vector(angle_degrees: float) -> tuple[float, float, float]:
    import math

    radians = math.radians(angle_degrees)
    return (math.cos(radians), math.sin(radians), 0.0)


def profile(
    *,
    creator: str = "creator-1",
    as_of: datetime = AS_OF,
    text: str = "A short synthetic post about Python #python?",
    topic: str | None = "python",
    intent: str | None = "ask",
    topology: str | None = "original",
    thread_role: str | None = "single",
    media_types: tuple[str, ...] | None = (),
):
    return extract_post_profile(
        PostProfileInput(
            text=text,
            observed_at=as_of,
            features_as_of=as_of,
            creator_key=creator,
            declared_topic=topic,
            declared_intent=intent,  # type: ignore[arg-type]
            topology=topology,  # type: ignore[arg-type]
            thread_role=thread_role,  # type: ignore[arg-type]
            media_types=media_types,  # type: ignore[arg-type]
        )
    )


def assessment(
    *,
    query_vector: tuple[float, float, float] = (1.0, 0.0, 0.0),
    creator: str = "creator-1",
    draft_profile=None,
    identity: EmbeddingIdentity = IDENTITY,
) -> DraftAssessment:
    return DraftAssessment(
        assessment_id="draft-2026-01-20-v1",
        creator_key=creator,
        as_of=AS_OF,
        profile=draft_profile or profile(creator=creator),
        embedding_identity=identity,
        embedding=query_vector,
        embedding_observed_at=AS_OF,
    )


def candidate(
    post_id: str,
    *,
    candidate_profile=None,
    candidate_vector: tuple[float, float, float] | None = (1.0, 0.0, 0.0),
    creator: str = "creator-1",
    published_at: datetime = AS_OF - timedelta(days=2),
    available: bool = True,
    identity: EmbeddingIdentity | None = IDENTITY,
    embedding_observed_at: datetime | None = AS_OF - timedelta(days=1),
    metric_evidence: tuple[MetricEligibilityEvidence, ...] = (),
) -> ComparableCandidate:
    return ComparableCandidate(
        post_id=post_id,
        creator_key=creator,
        published_at=published_at,
        available=available,
        profile=candidate_profile or profile(creator=creator, as_of=AS_OF - timedelta(days=2)),
        embedding_identity=identity,
        embedding=candidate_vector,
        embedding_observed_at=embedding_observed_at,
        metric_evidence=metric_evidence,
    )


def config(**kwargs) -> RetrievalConfig:
    return RetrievalConfig(
        minimum_comparables=1,
        minimum_relevance=0.0,
        **kwargs,
    )


def by_id(result):
    return {item.post_id: item for item in result.exclusions}


def test_semantic_similarity_orders_candidates_and_result_is_versioned() -> None:
    result = retrieve_comparables(
        assessment(),
        InMemoryVectorCandidateSource(
            (
                candidate("similar", candidate_vector=vector(10)),
                candidate("less-similar", candidate_vector=vector(60)),
            )
        ),
        config(),
    )
    assert [item.post_id for item in result.matches] == ["similar", "less-similar"]
    assert result.matches[0].components.semantic > result.matches[1].components.semantic
    assert result.algorithm_version == "comparable-retrieval-v1"
    assert result.config_version == "comparable-ranking-config-v1"
    assert result.embedding_identity == IDENTITY
    assert result.assessment_id == "draft-2026-01-20-v1"
    assert result.as_of == AS_OF


def test_topic_intent_and_format_features_can_rerank_semantically_close_posts() -> None:
    draft = profile(text="A concise Python question? #python", topic="python", intent="ask")
    wrong_features = profile(
        text="A concise gardening announcement.", topic="gardening", intent="inform"
    )
    right_features = profile(
        text="A concise Python question? #python", topic="python", intent="ask"
    )
    result = rank_comparable_candidates(
        assessment(draft_profile=draft),
        (
            candidate(
                "semantic-only", candidate_profile=wrong_features, candidate_vector=vector(0)
            ),
            candidate(
                "feature-match", candidate_profile=right_features, candidate_vector=vector(15)
            ),
        ),
        config(),
    )
    assert [item.post_id for item in result.matches] == ["feature-match", "semantic-only"]
    assert result.matches[0].components.topic == 1.0
    assert result.matches[0].components.intent is not None


def test_tied_scores_use_stable_post_id_tiebreaker() -> None:
    rows = (candidate("post-b"), candidate("post-a"), candidate("post-c"))
    first = rank_comparable_candidates(assessment(), rows, config())
    second = rank_comparable_candidates(assessment(), tuple(reversed(rows)), config())
    assert [item.post_id for item in first.matches] == ["post-a", "post-b", "post-c"]
    assert first.matches == second.matches


def test_same_creator_isolation_and_profile_identity_are_enforced() -> None:
    foreign = candidate("foreign", creator="creator-2")
    profile_mismatch = candidate(
        "wrong-profile-creator",
        candidate_profile=profile(creator="creator-2", as_of=AS_OF - timedelta(days=1)),
    )
    result = rank_comparable_candidates(assessment(), (foreign, profile_mismatch), config())
    assert not result.matches
    assert "different_creator" in by_id(result)["foreign"].reasons
    assert "profile_creator_mismatch" in by_id(result)["wrong-profile-creator"].reasons


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        (
            EmbeddingIdentity("test/other", REV, 3, "test-preprocess-v1"),
            "embedding_identity_mismatch",
        ),
        (
            EmbeddingIdentity("test/model", "b" * 40, 3, "test-preprocess-v1"),
            "embedding_identity_mismatch",
        ),
        (
            EmbeddingIdentity("test/model", REV, 4, "test-preprocess-v1"),
            "embedding_identity_mismatch",
        ),
        (
            EmbeddingIdentity("test/model", REV, 3, "other-preprocess-v1"),
            "embedding_identity_mismatch",
        ),
        (
            EmbeddingIdentity("test/model", REV, 3, "test-preprocess-v1", normalized=False),
            "embedding_identity_mismatch",
        ),
        (
            EmbeddingIdentity("test/model", REV, 3, "test-preprocess-v1", embedding_version="2"),
            "embedding_identity_mismatch",
        ),
    ],
)
def test_every_embedding_identity_field_must_match(identity, expected: str) -> None:
    result = rank_comparable_candidates(
        assessment(), (candidate("mismatch", identity=identity),), config()
    )
    assert expected in by_id(result)["mismatch"].reasons


def test_missing_embeddings_and_unknown_features_are_explained() -> None:
    missing_vector = candidate("no-vector", candidate_vector=None)
    unknown = candidate(
        "unknown", candidate_profile=profile(text=None, topic=None, intent=None, media_types=None)
    )
    result = rank_comparable_candidates(assessment(), (missing_vector, unknown), config())
    assert "missing_embedding" in by_id(result)["no-vector"].reasons
    assert [item.post_id for item in result.matches] == ["unknown"]
    assert result.matches[0].components.topic is None
    assert result.matches[0].components.semantic == 1.0
    assert result.matches[0].components.format is None
    assert "topic_similarity_unavailable" in result.matches[0].inclusion_reasons


def test_invalid_vector_values_and_dimensions_are_excluded() -> None:
    rows = (
        candidate("wrong-dimensions", candidate_vector=(1.0, 0.0)),
        candidate("non-finite", candidate_vector=(float("nan"), 0.0, 0.0)),
        candidate("not-normalized", candidate_vector=(2.0, 0.0, 0.0)),
    )
    result = rank_comparable_candidates(assessment(), rows, config())
    assert by_id(result)["wrong-dimensions"].reasons == ("embedding_dimensions_mismatch",)
    assert "embedding_contains_non_finite_values" in by_id(result)["non-finite"].reasons
    assert "embedding_not_normalized" in by_id(result)["not-normalized"].reasons


def test_topology_thread_role_and_known_format_mismatches_are_excluded() -> None:
    rows = (
        candidate("reply", candidate_profile=profile(topology="reply")),
        candidate("thread", candidate_profile=profile(thread_role="root")),
        candidate("media", candidate_profile=profile(media_types=("image",))),
    )
    result = rank_comparable_candidates(assessment(), rows, config())
    exclusions = by_id(result)
    assert "topology_mismatch" in exclusions["reply"].reasons
    assert "thread_role_mismatch" in exclusions["thread"].reasons
    assert "content_format_mismatch" in exclusions["media"].reasons


def test_unavailable_duplicates_and_missing_profiles_are_not_silently_dropped() -> None:
    unavailable = candidate("gone", available=False)
    duplicate_a = candidate("duplicate")
    duplicate_b = candidate("duplicate", candidate_vector=vector(20))
    missing_profile = replace(candidate("no-profile"), profile=None)
    result = rank_comparable_candidates(
        assessment(), (unavailable, duplicate_a, duplicate_b, missing_profile), config()
    )
    exclusions = by_id(result)
    assert "post_unavailable" in exclusions["gone"].reasons
    assert "duplicate_candidate_id" in exclusions["duplicate"].reasons
    assert "missing_post_profile" in exclusions["no-profile"].reasons
    assert result.candidate_count == 4
    assert result.excluded_count == 3


def test_future_publication_observations_and_profile_versions_are_excluded() -> None:
    future_profile = profile(as_of=AS_OF + timedelta(minutes=1))
    rows = (
        candidate("future-publication", published_at=AS_OF),
        candidate("future-embedding", embedding_observed_at=AS_OF + timedelta(seconds=1)),
        candidate("future-profile", candidate_profile=future_profile),
        candidate(
            "future-context",
            candidate_profile=replace(
                profile(as_of=AS_OF - timedelta(days=1)),
                creator_context_observed_at=AS_OF + timedelta(seconds=1),
            ),
        ),
        candidate(
            "old-profile-version",
            candidate_profile=replace(
                profile(as_of=AS_OF - timedelta(days=1)), version="post-profile-v0"
            ),
        ),
    )
    result = rank_comparable_candidates(assessment(), rows, config())
    exclusions = by_id(result)
    assert "not_published_before_assessment_cutoff" in exclusions["future-publication"].reasons
    assert "embedding_observed_after_assessment_cutoff" in exclusions["future-embedding"].reasons
    assert "profile_features_after_assessment_cutoff" in exclusions["future-profile"].reasons
    assert (
        "creator_context_observed_after_assessment_cutoff" in exclusions["future-context"].reasons
    )
    assert "profile_version_mismatch" in exclusions["old-profile-version"].reasons


def test_future_profile_input_observation_is_rechecked_even_when_features_as_of_is_old() -> None:
    profile_before = profile(as_of=AS_OF - timedelta(days=1))
    future_input = replace(profile_before, input_observed_at=AS_OF + timedelta(seconds=1))
    result = rank_comparable_candidates(
        assessment(), (candidate("future-input", candidate_profile=future_input),), config()
    )
    assert "profile_input_observed_after_assessment_cutoff" in by_id(result)["future-input"].reasons


def test_metric_definition_window_and_observation_cutoff_are_hard_filters_when_requested() -> None:
    requirement = MetricRequirement("impressions", "organic-total-v1", "mature-7d")
    good = MetricEligibilityEvidence(
        "impressions", "organic-total-v1", "mature-7d", AS_OF - timedelta(hours=2), True
    )
    rows = (
        candidate("valid", metric_evidence=(good,)),
        candidate("missing", metric_evidence=()),
        candidate("bad-definition", metric_evidence=(replace(good, definition="other"),)),
        candidate("bad-window", metric_evidence=(replace(good, window="age:1h"),)),
        candidate("invalid", metric_evidence=(replace(good, is_usable=False),)),
        candidate(
            "future-metric",
            metric_evidence=(replace(good, observed_at=AS_OF + timedelta(seconds=1)),),
        ),
        candidate(
            "naive-metric", metric_evidence=(replace(good, observed_at=AS_OF.replace(tzinfo=None)),)
        ),
    )
    result = rank_comparable_candidates(
        assessment(), rows, config(metric_requirements=(requirement,))
    )
    assert [item.post_id for item in result.matches] == ["valid"]
    assert "missing_metric_evidence:impressions" in by_id(result)["missing"].reasons
    assert "metric_definition_mismatch:impressions" in by_id(result)["bad-definition"].reasons
    assert "metric_window_mismatch:impressions" in by_id(result)["bad-window"].reasons
    assert "invalid_or_ineligible_metric_evidence:impressions" in by_id(result)["invalid"].reasons
    assert (
        "invalid_or_ineligible_metric_evidence:impressions"
        in by_id(result)["future-metric"].reasons
    )
    assert (
        "invalid_or_ineligible_metric_evidence:impressions" in by_id(result)["naive-metric"].reasons
    )


def test_metric_values_are_not_part_of_retrieval_or_ranking_contract() -> None:
    assert "value" not in {item.name for item in fields(MetricEligibilityEvidence)}
    first = candidate("post", metric_evidence=())
    second = replace(
        first,
        metric_evidence=(
            MetricEligibilityEvidence("different", "definition", "window", AS_OF, False),
        ),
    )
    a = rank_comparable_candidates(assessment(), (first,), config()).matches[0]
    b = rank_comparable_candidates(assessment(), (second,), config()).matches[0]
    assert a == b


def test_duplicate_records_are_reported_and_all_rejected_independent_of_input_order() -> None:
    first = candidate("same")
    duplicate = candidate("same", candidate_vector=vector(90))
    a = rank_comparable_candidates(assessment(), (first, duplicate), config())
    b = rank_comparable_candidates(assessment(), (duplicate, first), config())
    assert not a.matches and not b.matches
    assert a.exclusions == b.exclusions
    assert "duplicate_candidate_id" in a.exclusions[0].reasons


def test_vector_candidate_limit_and_coverage_are_explicit_and_stable() -> None:
    rows = tuple(candidate(f"post-{i:02d}", candidate_vector=vector(i)) for i in range(6))
    result = retrieve_comparables(
        assessment(),
        InMemoryVectorCandidateSource(rows),
        config(candidate_limit=3, result_limit=2),
    )
    assert result.truncated
    assert result.vector_candidate_count == 6
    assert len(result.matches) == 2
    assert (
        result.coverage_limitations[0] == "vector candidate limit truncated the searchable history"
    )


def test_tied_vector_scores_have_deterministic_candidate_selection_and_reranking() -> None:
    rows = (candidate("z"), candidate("a"), candidate("m"))
    source = InMemoryVectorCandidateSource(rows)
    query = VectorCandidateQuery("creator-1", AS_OF, IDENTITY, (1.0, 0.0, 0.0), 2)
    batch = source.search(query)
    assert [item.post_id for item in batch.candidates] == ["a", "m"]
    assert batch.truncated


def test_source_records_same_creator_future_and_identity_prefilter_exclusions() -> None:
    rows = (
        candidate("good"),
        candidate("foreign", creator="creator-2"),
        candidate("future", published_at=AS_OF),
        candidate(
            "other-space", identity=EmbeddingIdentity("test/other", REV, 3, "test-preprocess-v1")
        ),
    )
    result = retrieve_comparables(assessment(), InMemoryVectorCandidateSource(rows), config())
    assert [item.post_id for item in result.matches] == ["good"]
    exclusions = by_id(result)
    assert "different_creator" in exclusions["foreign"].reasons
    assert "not_published_before_assessment_cutoff" in exclusions["future"].reasons
    assert "embedding_identity_mismatch" in exclusions["other-space"].reasons
    assert result.candidate_count == 4
    assert result.excluded_count == 3


def test_sparse_history_and_novel_topic_return_explicit_abstention_states() -> None:
    sparse = rank_comparable_candidates(
        assessment(),
        (candidate("only-one"),),
        RetrievalConfig(minimum_comparables=2, minimum_relevance=0.0),
    )
    assert sparse.state == "insufficient_evidence"
    assert sparse.coverage_limitations
    novel = rank_comparable_candidates(
        assessment(),
        (candidate("unrelated", candidate_vector=(-1.0, 0.0, 0.0)),),
        RetrievalConfig(minimum_comparables=1, minimum_relevance=0.8),
    )
    assert novel.state == "no_match"
    assert not novel.matches
    assert "below_minimum_relevance" in by_id(novel)["unrelated"].reasons


def test_repeated_runs_return_identical_sets_and_exclusions() -> None:
    rows = (
        candidate("valid-b", candidate_vector=vector(20)),
        candidate("foreign", creator="other"),
        candidate("valid-a", candidate_vector=vector(20)),
    )
    first = retrieve_comparables(assessment(), InMemoryVectorCandidateSource(rows), config())
    second = retrieve_comparables(assessment(), InMemoryVectorCandidateSource(rows), config())
    assert first == second


def test_draft_cannot_use_future_or_mismatched_profile_or_invalid_query_embedding() -> None:
    with pytest.raises(ValueError, match="after assessment cutoff"):
        assessment(draft_profile=profile(as_of=AS_OF + timedelta(seconds=1)))
    with pytest.raises(ValueError, match="differs from assessment creator"):
        assessment(draft_profile=profile(creator="different"))
    with pytest.raises(ValueError, match="invalid draft embedding"):
        assessment(query_vector=(2.0, 0.0, 0.0))


def test_malformed_configurations_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least one ranking weight"):
        RankingWeights(semantic=0, topic=0, intent=0, format=0, structure=0)
    with pytest.raises(ValueError, match="finite and non-negative"):
        RankingWeights(semantic=-1)
    with pytest.raises(ValueError, match="result_limit must be at least"):
        RetrievalConfig(result_limit=1, minimum_comparables=2)
