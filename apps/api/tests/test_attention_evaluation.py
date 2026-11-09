"""Synthetic-only attention evaluation tests; no real X data or model inference."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from bipme.intelligence.attention_evaluation import (
    AttentionEvaluationPost,
    AttentionEvaluationSpec,
    evaluate_attention_features,
)
from bipme.intelligence.attention_features import describe_attention_features
from bipme.intelligence.creator_goals import CreatorGoalsSnapshot
from bipme.intelligence.post_profiles import PostProfileInput, extract_post_profile

START = datetime(2026, 10, 1, tzinfo=UTC)
CREATOR = "synthetic-creator"


def goals(**overrides: object) -> CreatorGoalsSnapshot:
    values: dict[str, object] = {
        "creator_key": CREATOR,
        "recorded_at": START - timedelta(days=1),
        "niche": "synthetic software engineering",
        "intended_audience": "synthetic backend engineers",
        "priority_outcomes": ("conversation", "qualified_interest"),
        "preferred_styles": ("technical_explainer", "personal_story"),
    }
    values.update(overrides)
    return CreatorGoalsSnapshot(**values)  # type: ignore[arg-type]


def make_posts(count: int = 24) -> tuple[AttentionEvaluationPost, ...]:
    rows: list[AttentionEvaluationPost] = []
    for index in range(count):
        published = START + timedelta(days=index)
        if index % 3 == 0:
            text = "A short reference guide."
            value = float(index + 1)
        elif index % 3 == 1:
            text = "What do you think?"
            value = float(index + 20)
        else:
            text = "When I built version 12, I learned a specific lesson."
            value = float(index + 40)
        if index == 18:
            text = "When I built version 12, I think the API should change."
        profile = extract_post_profile(
            PostProfileInput(
                text=text,
                observed_at=published,
                features_as_of=published,
                creator_key=CREATOR,
                topology="original",
                thread_role="single",
                media_types=(),
            )
        )
        rows.append(
            AttentionEvaluationPost(
                post_id=f"post-{index:02d}",
                creator_key=CREATOR,
                published_at=published,
                profile=profile,
                text=text,
                metric="replies",
                metric_definition="reply-count-v1",
                window="age:24h",
                outcome=value,
                outcome_observed_at=published + timedelta(hours=1),
            )
        )
    return tuple(rows)


def spec(*, as_of: datetime | None = None, **overrides: object) -> AttentionEvaluationSpec:
    values: dict[str, object] = {
        "goals": goals(),
        "as_of": as_of or START + timedelta(days=40),
        "metric": "replies",
        "metric_definition": "reply-count-v1",
        "window": "age:24h",
        "selection_basis": "complete_archive",
    }
    values.update(overrides)
    return AttentionEvaluationSpec(**values)  # type: ignore[arg-type]


def feature(result: object, name: str):
    return next(item for item in result.features if item.feature == name)  # type: ignore[attr-defined]


def test_text_heuristics_are_versioned_and_explicitly_lexical() -> None:
    item = make_posts(1)[0]
    descriptor = describe_attention_features(item.profile, as_of=item.published_at, text=item.text)
    assert descriptor.version == "attention-descriptors-v2"
    signals = {(signal.name, signal.origin, signal.value) for signal in descriptor.signals}
    assert ("specificity_markers", "lexical_heuristic", "0") in signals
    assert ("opening_structure", "lexical_heuristic", "other") in signals
    assert all("impression" not in name and "dwell" not in name for name, _, _ in signals)


def test_question_story_opinion_specificity_and_hook_are_visible_separately() -> None:
    published = START
    text = "But this changed things.\nWhen I built release 12, I learned something. I think this should change. Why?"
    profile = extract_post_profile(
        PostProfileInput(
            text=text,
            observed_at=published,
            features_as_of=published,
            creator_key=CREATOR,
            topology="original",
            thread_role="single",
            media_types=(),
        )
    )
    descriptor = describe_attention_features(profile, as_of=published, text=text)
    signals = {signal.name: signal.value for signal in descriptor.signals}
    assert signals["specificity_markers"] == "1"
    assert int(signals["storytelling_cues"]) > 0
    assert signals["opinion_marker"] == "present"
    assert signals["opening_structure"] == "contrast"
    assert ("question_marker", "lexical_heuristic", "present") in {
        (signal.name, signal.origin, signal.value) for signal in descriptor.signals
    }


def test_evaluation_reports_three_groups_prevalence_and_feature_ablation() -> None:
    result = evaluate_attention_features(make_posts(), spec())
    assert result.eligible_post_count == 24
    assert result.sample_adequate
    assert result.evidence_state == "descriptive_sample_adequate"
    assert result.creator_niche == "synthetic software engineering"
    assert result.intended_audience == "synthetic backend engineers"
    assert {item.group for item in feature(result, "storytelling_cues").groups} == {
        "strong",
        "typical",
        "weak",
    }
    storytelling = feature(result, "storytelling_cues")
    assert storytelling.strong_minus_weak_gap is not None
    assert storytelling.discriminative_category == "0"
    storytelling_present = {
        item.group: item.prevalence for item in storytelling.groups if item.category == "1+"
    }
    assert storytelling_present["strong"] > storytelling_present["weak"]
    format_feature = feature(result, "content_format")
    assert format_feature.strong_minus_weak_gap == 0
    format_ablation = next(
        item for item in result.ablations if item.feature_removed == "content_format"
    )
    assert format_ablation.associations_removed == 0
    ablation = next(
        item for item in result.ablations if item.feature_removed == "storytelling_cues"
    )
    assert ablation.feature_evidence_removed
    assert ablation.associations_after == ablation.associations_before - 1
    assert result.walk_forward.target_count == 24
    assert result.walk_forward.targets_without_enough_prior_history >= 8
    assert result.walk_forward.strong_targets > 0
    assert any("not causal" in item for item in storytelling.limitations)


def test_walk_forward_does_not_use_outcomes_unobserved_at_target_time() -> None:
    posts = list(make_posts())
    posts[10] = replace(posts[10], outcome_observed_at=posts[12].published_at + timedelta(hours=1))
    result = evaluate_attention_features(tuple(posts), spec())
    # At post 12's cutoff, post 10's later measurement is not in the prior reference set.
    target_cutoff = posts[12].published_at
    prior_available = [
        post
        for post in posts[:12]
        if post.published_at < target_cutoff and post.outcome_observed_at <= target_cutoff
    ]
    assert len(prior_available) == 11
    # The evaluated target remains a label, but its feature timestamp stays pre-publication.
    assert result.walk_forward.target_count == 24
    assert (
        dict(result.walk_forward.leakage_exclusions)["prior_outcome_not_observed_by_target_cutoff"]
        >= 1
    )
    assert all(post.profile.features_as_of <= post.published_at for post in posts)


def test_missing_data_duplicates_outliers_and_selection_bias_are_visible() -> None:
    posts = list(make_posts())
    posts[0] = replace(
        posts[0],
        text=None,
        profile=extract_post_profile(
            PostProfileInput(
                text=None,
                observed_at=posts[0].published_at,
                features_as_of=posts[0].published_at,
                creator_key=CREATOR,
                media_types=None,
            )
        ),
    )
    posts[5] = replace(posts[5], outcome=None)
    posts[23] = replace(posts[23], outcome=100_000.0)
    posts.append(posts[1])
    result = evaluate_attention_features(tuple(posts), spec(selection_basis="sampled"))
    assert result.duplicate_post_count == 1
    assert result.missing_outcome_count == 1
    assert result.missing_metadata_count > 0
    assert not result.sample_adequate or result.eligible_post_count >= 8
    assert any("selection bias" in item for item in result.limitations)
    assert any("Outlier sensitivity" in item for item in result.limitations)
    assert feature(result, "storytelling_cues").outlier_excluded_gap is not None
    assert any(
        item.known_count < 8
        for item in feature(result, "question_marker").groups
        if item.group == "weak"
    )


def test_small_and_non_discriminating_samples_abstain() -> None:
    result = evaluate_attention_features(make_posts(3), spec())
    assert result.eligible_post_count == 3
    assert not result.sample_adequate
    assert result.evidence_state == "insufficient_evidence"
    assert result.walk_forward.targets_without_enough_prior_history == 3
    assert any("too small" in item for item in result.limitations)


def test_future_profile_creator_and_naive_cutoffs_fail_closed() -> None:
    posts = list(make_posts())
    posts[0] = replace(
        posts[0],
        profile=replace(
            posts[0].profile, features_as_of=posts[0].published_at + timedelta(seconds=1)
        ),
    )
    result = evaluate_attention_features(tuple(posts), spec())
    assert result.eligible_post_count == 23
    assert any("future_feature" in item for item in result.limitations)
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_attention_features(tuple(make_posts()), spec(as_of=START.replace(tzinfo=None)))
    foreign = evaluate_attention_features(
        tuple(make_posts()), spec(goals=goals(creator_key="other"))
    )
    assert foreign.eligible_post_count == 0
    assert any("creator_mismatch" in item for item in foreign.limitations)
