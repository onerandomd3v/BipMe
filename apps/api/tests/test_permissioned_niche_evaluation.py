"""Synthetic-only checks for permissioned cross-creator evaluation."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from bipme.intelligence.permissioned_niche_evaluation import (
    NicheEvaluationPost,
    NicheEvaluationSpec,
    evaluate_permissioned_niche_comparisons,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
TARGET = "synthetic-target"


def make_posts(*, peer_permission: bool = True) -> tuple[NicheEvaluationPost, ...]:
    posts: list[NicheEvaluationPost] = []
    patterns = (
        ("weak", 100.0),
        ("typical", 200.0),
        ("typical", 200.0),
        ("typical", 200.0),
        ("typical", 200.0),
        ("strong", 300.0),
    )
    for creator_index, creator in enumerate(
        (TARGET, "synthetic-peer-a", "synthetic-peer-b", "synthetic-peer-c")
    ):
        for index in range(36):
            pattern, value = patterns[index % len(patterns)]
            if pattern == "weak":
                value += index % 5
            elif pattern == "typical":
                value += (index % 24) * 5
            else:
                value += (index % 4) * 10
            published = START + timedelta(days=index + creator_index * 0.01)
            posts.append(
                NicheEvaluationPost(
                    post_id=f"{creator}-{index:02d}",
                    creator_key=creator,
                    niche="synthetic niche",
                    audience_size_band="small",
                    language="en",
                    pattern=pattern,
                    metric="replies",
                    metric_definition="replies-v1",
                    window="age:24h",
                    value=value,
                    published_at=published,
                    observed_at=published + timedelta(hours=24),
                    owner_verified=True,
                    comparison_permission=creator == TARGET or peer_permission,
                    evidence_provenance=f"synthetic://{creator}/{index}",
                )
            )
    return tuple(posts)


def spec(**overrides: object) -> NicheEvaluationSpec:
    values: dict[str, object] = {
        "target_creator_key": TARGET,
        "niche": "synthetic niche",
        "audience_size_band": "small",
        "language": "en",
        "metric": "replies",
        "metric_definition": "replies-v1",
        "window": "age:24h",
        "expected_observation_age_hours": 24,
        "as_of": START + timedelta(days=45),
        "minimum_history_posts": 3,
        "minimum_niche_contributors": 2,
    }
    values.update(overrides)
    return NicheEvaluationSpec(**values)  # type: ignore[arg-type]


def test_permissioned_niche_comparison_is_repeatable_and_balanced() -> None:
    result = evaluate_permissioned_niche_comparisons(make_posts(), spec())

    assert result.version == "permissioned-niche-evaluation-v1"
    assert result.synthetic_only
    assert result.niche_contributor_count == 3
    assert result.personal.recommendation_coverage > 0
    assert result.permissioned_niche.recommendation_coverage > 0
    assert result.permissioned_niche.pattern == "strong"
    assert result.permissioned_niche.recommendation_stability >= 0.8
    assert all(count > 0 for _, count in result.permissioned_niche.sampled_band_counts)
    assert result.permissioned_niche.outlier_sensitivity_status == "measured"
    assert any("Synthetic outcomes only" in item for item in result.limitations)


def test_unpermissioned_or_unverified_peers_never_enter_niche_evidence() -> None:
    posts = tuple(
        replace(post, comparison_permission=False, owner_verified=False)
        if post.creator_key == "synthetic-peer-a"
        else post
        for post in make_posts()
    )

    result = evaluate_permissioned_niche_comparisons(posts, spec())

    assert result.niche_contributor_count == 2
    assert dict(result.exclusions)["peer_permission_missing"] > 0
    assert dict(result.exclusions)["owner_verification_missing"] > 0


def test_future_incompatible_missing_and_wrong_age_evidence_is_excluded() -> None:
    posts = list(make_posts())
    peer_index = next(i for i, post in enumerate(posts) if post.creator_key == "synthetic-peer-a")
    posts[peer_index] = replace(posts[peer_index], observed_at=spec().as_of + timedelta(days=3))
    posts.append(
        replace(
            posts[peer_index + 1],
            post_id="synthetic-missing-impressions",
            metric="impressions",
            value=None,
        )
    )
    posts.append(
        replace(
            posts[peer_index + 2],
            post_id="synthetic-different-window",
            window="mature",
        )
    )
    posts.append(
        replace(
            posts[peer_index + 3],
            post_id="synthetic-wrong-age",
            observed_at=posts[peer_index + 3].published_at + timedelta(hours=48),
        )
    )

    result = evaluate_permissioned_niche_comparisons(tuple(posts), spec())

    assert dict(result.exclusions)["future_observation"] >= 1
    assert dict(result.exclusions)["missing_outcome"] >= 1
    assert dict(result.exclusions)["metric_or_window_mismatch"] >= 1
    assert dict(result.exclusions)["observation_age_mismatch"] >= 1


def test_personal_recommendation_does_not_change_when_peer_future_is_changed() -> None:
    posts = make_posts()
    final_target_publication = max(
        post.published_at for post in posts if post.creator_key == TARGET
    )
    changed = tuple(
        replace(post, pattern="future-only", value=1_000_000)
        if post.creator_key == "synthetic-peer-c" and post.published_at > final_target_publication
        else replace(post, pattern="heldout-only", value=1_000_000)
        if post.creator_key == TARGET and post.published_at == final_target_publication
        else post
        for post in posts
    )

    before = evaluate_permissioned_niche_comparisons(posts, spec())
    after = evaluate_permissioned_niche_comparisons(changed, spec())

    assert before.personal.pattern == after.personal.pattern
    assert before.personal.recommendation_count == after.personal.recommendation_count
    assert before.permissioned_niche.pattern == after.permissioned_niche.pattern
    assert (
        before.permissioned_niche.recommendation_count
        == after.permissioned_niche.recommendation_count
    )


def test_sparse_history_returns_insufficient_recommendations() -> None:
    result = evaluate_permissioned_niche_comparisons(make_posts(), spec(minimum_history_posts=40))

    assert result.scored_target_count == 0
    assert result.personal.pattern is None
    assert result.permissioned_niche.pattern is None
    assert result.personal.recommendation_coverage == 0


def test_creator_size_mismatch_is_not_pooled_even_with_large_raw_counts() -> None:
    posts = make_posts()
    extra = replace(
        next(post for post in posts if post.creator_key == "synthetic-peer-a"),
        post_id="synthetic-larger-creator-outcome",
        audience_size_band="large",
        value=10_000_000.0,
    )

    result = evaluate_permissioned_niche_comparisons(posts + (extra,), spec())

    assert dict(result.exclusions)["context_mismatch"] >= 1
    assert result.permissioned_niche.pattern == "strong"
    assert result.permissioned_niche.mean_matched_outcome_score is not None


def test_extreme_creator_relative_outlier_is_reported_and_checked() -> None:
    posts = list(make_posts())
    outlier_index = next(
        i
        for i, post in enumerate(posts)
        if post.creator_key == "synthetic-peer-a" and post.post_id.endswith("-24")
    )
    posts[outlier_index] = replace(posts[outlier_index], value=1_000_000.0)

    result = evaluate_permissioned_niche_comparisons(tuple(posts), spec())

    assert result.permissioned_niche.outlier_excluded_post_count > 0
    assert result.permissioned_niche.outlier_recommendation_change_rate is not None


def test_zero_iqr_is_reported_as_unidentifiable_outlier_sensitivity() -> None:
    posts = tuple(replace(post, value=200.0) for post in make_posts())

    result = evaluate_permissioned_niche_comparisons(posts, spec())

    assert result.personal.outlier_sensitivity_status == "not_identifiable"
    assert result.personal.outlier_recommendation_change_rate is None


def test_evaluator_rejects_non_synthetic_identity_or_provenance() -> None:
    posts = list(make_posts())
    posts[0] = replace(posts[0], creator_key="real-creator")

    with pytest.raises(ValueError, match="synthetic identities and provenance only"):
        evaluate_permissioned_niche_comparisons(tuple(posts), spec())
