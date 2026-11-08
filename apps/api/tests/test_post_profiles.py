"""Synthetic Post Profile contracts; no X data or model inference."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from bipme.intelligence.post_profiles import (
    PROFILE_VERSION,
    CreatorContextSnapshot,
    PostProfileInput,
    extract_post_profile,
)

AS_OF = datetime(2026, 1, 2, 12, tzinfo=UTC)


def post_input(**overrides: Any) -> PostProfileInput:
    values: dict[str, Any] = {
        "text": "A synthetic draft.",
        "observed_at": AS_OF,
        "features_as_of": AS_OF,
        "creator_key": "creator-1",
        "topology": "original",
        "thread_role": "single",
        "media_types": (),
    }
    values.update(overrides)
    return PostProfileInput(**values)


def test_identical_input_produces_identical_versioned_profile() -> None:
    data = post_input(
        text="Learning Python? Reply with your questions. #Python #python",
        declared_topic="  Programming  ",
        declared_intent="ask",
        creator_context=CreatorContextSnapshot(AS_OF, follower_count=120),
    )
    first = extract_post_profile(data)
    assert first == extract_post_profile(data)
    assert first.version == PROFILE_VERSION
    assert first.input_observed_at == AS_OF
    assert first.topic_signals == ("python",)
    assert first.hashtags == ("python", "python")
    assert first.intent_signals == ("question_marker", "reply_invitation")
    assert first.declared_topic == "Programming"
    assert first.declared_intent == "ask"
    assert first.creator_follower_count == 120
    assert first.creator_context_observed_at == AS_OF


def test_empty_short_and_unknown_text_are_distinct() -> None:
    empty = extract_post_profile(post_input(text="", media_types=()))
    short = extract_post_profile(post_input(text="Hi", media_types=()))
    missing = extract_post_profile(post_input(text=None, media_types=None))

    assert (empty.character_count, empty.word_count, empty.sentence_count) == (0, 0, 0)
    assert empty.content_format == "empty"
    assert empty.hashtags == ()
    assert short.character_count == 2
    assert short.word_count == 1
    assert short.sentence_count == 1
    assert short.content_format == "text_only"
    assert missing.character_count is None
    assert missing.word_count is None
    assert missing.hashtags is None
    assert missing.topic_signals is None
    assert missing.intent_signals is None
    assert missing.content_format == "unknown"


def test_hashtags_mentions_links_and_structure() -> None:
    text = "Hello @Ada! Read https://example.test/a#Hidden. #Build #build?"
    profile = extract_post_profile(post_input(text=text))
    assert profile.character_count == len(text)
    assert profile.word_count == 5
    assert profile.sentence_count == 3
    assert profile.hashtags == ("build", "build")
    assert profile.mentions == ("ada",)
    assert profile.url_count == 1
    assert profile.topic_signals == ("build",)
    assert profile.intent_signals == ("question_marker",)


@pytest.mark.parametrize(
    "url",
    [
        "https://en.wikipedia.org/wiki/Function_(mathematics)",
        "https://en.wikipedia.org/wiki/Function_(mathematics)#@NotAMention",
    ],
)
def test_parenthesized_url_content_is_excluded_from_text_signals(url: str) -> None:
    profile = extract_post_profile(
        post_input(text=f"Read this {url} #RealTopic? Reply with your thoughts.")
    )
    assert profile.url_count == 1
    assert profile.word_count == 7
    assert profile.hashtags == ("realtopic",)
    assert profile.mentions == ()
    assert profile.topic_signals == ("realtopic",)
    assert profile.intent_signals == ("question_marker", "reply_invitation")


def test_parenthesized_url_keeps_only_unmatched_wrapper_punctuation() -> None:
    profile = extract_post_profile(
        post_input(text="See (https://en.wikipedia.org/wiki/Function_(mathematics)).")
    )
    assert profile.url_count == 1
    assert profile.word_count == 1
    assert profile.hashtags == ()
    assert profile.mentions == ()
    assert profile.sentence_count == 1


@pytest.mark.parametrize(
    ("topology", "thread_role", "media_types", "expected_tags"),
    [
        ("reply", "continuation", (), ("text_only", "reply", "thread_continuation")),
        ("quote", "single", ("image",), ("media", "quote")),
        ("original", "root", ("video", "image"), ("media", "thread_root")),
    ],
)
def test_known_topology_thread_and_media(
    topology: str, thread_role: str, media_types: tuple[str, ...], expected_tags: tuple[str, ...]
) -> None:
    data = post_input(topology=topology, thread_role=thread_role, media_types=media_types)
    profile = extract_post_profile(data)
    assert profile.topology == topology
    assert profile.thread_role == thread_role
    assert profile.media_types == media_types
    assert profile.format_tags == expected_tags
    assert profile.content_format == ("media" if media_types else "text_only")


def test_missing_metadata_stays_unknown_and_not_inferred_from_text() -> None:
    profile = extract_post_profile(
        post_input(
            text="This looks like a reply? #topic",
            topology=None,
            thread_role=None,
            media_types=None,
            declared_intent=None,
            creator_context=None,
        )
    )
    assert profile.topology is None
    assert profile.thread_role is None
    assert profile.media_types is None
    assert profile.content_format == "unknown"
    assert profile.declared_intent is None
    assert profile.creator_follower_count is None
    assert profile.topic_signals == ("topic",)
    assert profile.intent_signals == ("question_marker",)


def test_feature_version_change_requires_new_extractor() -> None:
    assert extract_post_profile(post_input()).version == PROFILE_VERSION
    with pytest.raises(ValueError, match="Unsupported Post Profile version"):
        extract_post_profile(post_input(), version="post-profile-v2")


def test_future_input_or_creator_context_is_rejected() -> None:
    with pytest.raises(ValueError, match="Input was observed after"):
        post_input(observed_at=AS_OF + timedelta(seconds=1))
    with pytest.raises(ValueError, match="Creator context was observed after"):
        post_input(creator_context=CreatorContextSnapshot(AS_OF + timedelta(seconds=1), 999))
    with pytest.raises(ValueError, match="timezone-aware"):
        post_input(features_as_of=AS_OF.replace(tzinfo=None))
    earlier = CreatorContextSnapshot(AS_OF - timedelta(days=1), 100)
    profile = extract_post_profile(post_input(creator_context=earlier))
    assert profile.creator_follower_count == 100
    assert profile.creator_context_observed_at == earlier.observed_at


def test_outcomes_cannot_enter_input_or_profile() -> None:
    with pytest.raises(TypeError, match="impressions"):
        post_input(impressions=5000)
    profile = extract_post_profile(post_input())
    serialized = asdict(profile)
    assert not {"impressions", "views", "likes", "replies", "reposts", "engagement_rate"} & set(
        serialized
    )
    assert "embedding" not in serialized


def test_invalid_supplied_signals_are_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported topology"):
        post_input(topology="reshare")
    with pytest.raises(ValueError, match="media_types"):
        post_input(media_types=("unsupported",))
    with pytest.raises(ValueError, match="declared_topic"):
        post_input(declared_topic=" ")
    with pytest.raises(ValueError, match="negative"):
        CreatorContextSnapshot(AS_OF, -1)
