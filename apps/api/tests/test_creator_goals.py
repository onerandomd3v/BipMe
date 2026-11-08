"""Synthetic creator goal and lexical signal tests. No real X content or inference."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import pytest

from bipme.intelligence.attention_features import (
    ATTENTION_FEATURES_VERSION,
    describe_attention_features,
)
from bipme.intelligence.creator_goals import CREATOR_GOALS_VERSION, CreatorGoalsSnapshot
from bipme.intelligence.post_profiles import PostProfileInput, extract_post_profile

AS_OF = datetime(2026, 11, 8, 12, tzinfo=UTC)


def snapshot(**overrides: object) -> CreatorGoalsSnapshot:
    values: dict[str, object] = {
        "creator_key": "creator-1",
        "recorded_at": AS_OF,
        "niche": "  Software Engineering  ",
        "intended_audience": "  Backend engineers ",
        "priority_outcomes": ("conversation", "reach"),
        "preferred_styles": ("technical_explainer", "personal_story"),
        "language": " en ",
    }
    values.update(overrides)
    return CreatorGoalsSnapshot(**values)  # type: ignore[arg-type]


def profile(text: str | None) -> PostProfileInput:
    return PostProfileInput(
        text=text,
        observed_at=AS_OF,
        features_as_of=AS_OF,
        creator_key="creator-1",
        media_types=() if text is not None else None,
        topology="original",
        thread_role="single",
    )


def test_goal_snapshot_normalizes_declared_values_and_serializes() -> None:
    goals = snapshot()
    assert goals.version == CREATOR_GOALS_VERSION
    assert goals.niche == "Software Engineering"
    assert goals.intended_audience == "Backend engineers"
    assert goals.language == "en"
    assert asdict(goals)["priority_outcomes"] == ("conversation", "reach")
    goals.require_available_by(AS_OF, "creator-1")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("creator_key", "  "),
        ("niche", ""),
        ("intended_audience", "\t"),
        ("priority_outcomes", ()),
        ("priority_outcomes", ("conversation", "conversation")),
        ("priority_outcomes", ("virality",)),
        ("priority_outcomes", ["reach"]),
        ("preferred_styles", ("tutorial", "tutorial")),
        ("preferred_styles", ("magic",)),
        ("preferred_styles", ["tutorial"]),
        ("language", " "),
        ("recorded_at", AS_OF.replace(tzinfo=None)),
        ("version", "creator-goals-v2"),
    ],
)
def test_invalid_goal_snapshots_fail_closed(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        snapshot(**{field: value})


def test_creators_and_time_cutoffs_are_isolated() -> None:
    goals = snapshot()
    with pytest.raises(ValueError, match="another creator"):
        goals.require_available_by(AS_OF, "creator-2")
    with pytest.raises(ValueError, match="after the report cutoff"):
        goals.require_available_by(AS_OF - timedelta(seconds=1), "creator-1")
    with pytest.raises(ValueError, match="timezone-aware"):
        goals.require_available_by(AS_OF.replace(tzinfo=None), "creator-1")


def test_attention_taxonomy_is_descriptive_and_deterministic() -> None:
    item = profile("A synthetic database lesson? Reply with your findings.")
    post = extract_post_profile(item)
    result = describe_attention_features(post, as_of=AS_OF)
    assert result == describe_attention_features(post, as_of=AS_OF)
    assert result.version == ATTENTION_FEATURES_VERSION
    assert ("question_marker", "lexical_heuristic", "present") in [
        (signal.name, signal.origin, signal.value) for signal in result.signals
    ]
    assert ("reply_invitation", "lexical_heuristic", "present") in [
        (signal.name, signal.origin, signal.value) for signal in result.signals
    ]
    assert not {"views", "impressions", "dwell_time", "ranking_score"} & {
        signal.name for signal in result.signals
    }


def test_unknown_text_does_not_turn_into_asserted_negative_signal() -> None:
    post = extract_post_profile(profile(None))
    result = describe_attention_features(post, as_of=AS_OF)
    assert "text_intent_signals" in result.unknowns
    assert "word_count" in result.unknowns
    assert "content_format" in result.unknowns
    assert all(signal.name != "question_marker" for signal in result.signals)


def test_future_post_features_rejected_even_with_known_goal() -> None:
    post = extract_post_profile(profile("A test post."))
    with pytest.raises(ValueError, match="after the report cutoff"):
        describe_attention_features(post, as_of=AS_OF - timedelta(seconds=1))
    with pytest.raises(ValueError, match="timezone-aware"):
        describe_attention_features(post, as_of=AS_OF.replace(tzinfo=None))


def test_optional_declared_intent_not_inferred_as_audience_demographic() -> None:
    item = PostProfileInput(
        text="Guide: build a small API",
        observed_at=AS_OF,
        features_as_of=AS_OF,
        declared_intent="inform",
        declared_topic="Developer tutorials",
    )
    result = describe_attention_features(extract_post_profile(item), as_of=AS_OF)
    assert ("declared_topic", "creator_declared", "Developer tutorials") in [
        (signal.name, signal.origin, signal.value) for signal in result.signals
    ]
    assert "actual_follower_demographics" not in asdict(result)
