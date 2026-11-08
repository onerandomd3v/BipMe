"""Deterministic, prediction-time descriptions of posts and drafts.

Outcome measurements deliberately have no place in this input or output contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

PROFILE_VERSION = "post-profile-v1"

Topology = Literal["original", "reply", "quote"]
ThreadRole = Literal["single", "root", "continuation"]
MediaKind = Literal["image", "video", "gif", "audio", "other"]
DeclaredIntent = Literal["inform", "ask", "promote", "entertain", "other"]
ContentFormat = Literal["text_only", "media", "empty", "unknown"]

# Accept balanced parenthesized URL path segments (common in Wikipedia links).
_URL = re.compile(r"https?://[^\s<>]*(?:\([^()\s<>]*\)[^\s<>]*)*", re.IGNORECASE)
_HASHTAG = re.compile(r"(?<!\w)#(\w+)", re.UNICODE)
_MENTION = re.compile(r"(?<!\w)@(\w+)", re.UNICODE)
_WORD = re.compile(r"\b\w+\b", re.UNICODE)
_SENTENCE = re.compile(r"[^.!?]+[.!?]*")
_REPLY_INVITATION = re.compile(
    r"\b(?:reply\s+(?:with|below)|comment\s+(?:with|below)|tell\s+me)\b", re.IGNORECASE
)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _redact_url(match: re.Match[str]) -> str:
    """Remove URL content while keeping any sentence-ending punctuation."""
    value = match.group()
    content = value.rstrip(".,;!?")
    while content.endswith(")") and content.count(")") > content.count("("):
        content = content[:-1]
    return " " + value[len(content) :]


@dataclass(frozen=True)
class CreatorContextSnapshot:
    """Creator state observed by a known time, never a later audience state."""

    observed_at: datetime
    follower_count: int | None = None

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "creator context observed_at")
        if self.follower_count is not None and self.follower_count < 0:
            raise ValueError("follower_count cannot be negative")


@dataclass(frozen=True)
class PostProfileInput:
    """Known content/metadata as observed no later than features_as_of.

    None means unknown. Empty text or media tuples mean known absence.
    Topic and intent labels are creator-declared, not inferred from performance.
    """

    text: str | None
    observed_at: datetime
    features_as_of: datetime
    creator_key: str | None = None
    topology: Topology | None = None
    thread_role: ThreadRole | None = None
    media_types: tuple[MediaKind, ...] | None = None
    declared_topic: str | None = None
    declared_intent: DeclaredIntent | None = None
    creator_context: CreatorContextSnapshot | None = None

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "input observed_at")
        _require_aware(self.features_as_of, "features_as_of")
        if self.observed_at > self.features_as_of:
            raise ValueError("Input was observed after features_as_of")
        if self.creator_context and self.creator_context.observed_at > self.features_as_of:
            raise ValueError("Creator context was observed after features_as_of")
        if self.text is not None and not isinstance(self.text, str):
            raise TypeError("text must be a string or None")
        if self.creator_key is not None and not self.creator_key.strip():
            raise ValueError("creator_key cannot be blank")
        if self.declared_topic is not None and not self.declared_topic.strip():
            raise ValueError("declared_topic cannot be blank")
        if self.topology not in (None, "original", "reply", "quote"):
            raise ValueError("Unsupported topology")
        if self.thread_role not in (None, "single", "root", "continuation"):
            raise ValueError("Unsupported thread role")
        if self.declared_intent not in (None, "inform", "ask", "promote", "entertain", "other"):
            raise ValueError("Unsupported declared intent")
        if self.media_types is not None:
            if not isinstance(self.media_types, tuple) or any(
                kind not in ("image", "video", "gif", "audio", "other") for kind in self.media_types
            ):
                raise ValueError("media_types must be a tuple of supported kinds")


@dataclass(frozen=True)
class PostProfile:
    """Versioned descriptive features for COD-352; no outcomes or embeddings."""

    version: str
    features_as_of: datetime
    input_observed_at: datetime
    creator_key: str | None
    character_count: int | None
    word_count: int | None
    sentence_count: int | None
    hashtags: tuple[str, ...] | None
    mentions: tuple[str, ...] | None
    url_count: int | None
    content_format: ContentFormat
    format_tags: tuple[str, ...]
    topology: Topology | None
    thread_role: ThreadRole | None
    media_types: tuple[MediaKind, ...] | None
    topic_signals: tuple[str, ...] | None
    declared_topic: str | None
    intent_signals: tuple[str, ...] | None
    declared_intent: DeclaredIntent | None
    creator_follower_count: int | None
    creator_context_observed_at: datetime | None


def extract_post_profile(data: PostProfileInput, *, version: str = PROFILE_VERSION) -> PostProfile:
    """Extract stable lexical and supplied metadata signals for the supported version."""
    if version != PROFILE_VERSION:
        raise ValueError(f"Unsupported Post Profile version: {version}")

    if data.text is None:
        character_count = word_count = sentence_count = url_count = None
        hashtags = mentions = topic_signals = intent_signals = None
    else:
        text_without_urls = _URL.sub(_redact_url, data.text)
        hashtags = tuple(match.casefold() for match in _HASHTAG.findall(text_without_urls))
        mentions = tuple(match.casefold() for match in _MENTION.findall(text_without_urls))
        topic_signals = tuple(dict.fromkeys(hashtags))
        signals: list[str] = []
        if "?" in text_without_urls:
            signals.append("question_marker")
        if _REPLY_INVITATION.search(text_without_urls):
            signals.append("reply_invitation")
        intent_signals = tuple(signals)
        character_count = len(data.text)
        word_count = len(_WORD.findall(text_without_urls))
        sentence_count = sum(bool(part.strip()) for part in _SENTENCE.findall(text_without_urls))
        url_count = len(_URL.findall(data.text))

    if data.media_types is None:
        content_format: ContentFormat = "unknown"
    elif data.media_types:
        content_format = "media"
    elif data.text is not None and data.text.strip():
        content_format = "text_only"
    elif data.text is None:
        content_format = "unknown"
    else:
        content_format = "empty"

    format_tags: list[str] = []
    if content_format in ("text_only", "media"):
        format_tags.append(content_format)
    if data.topology in ("reply", "quote"):
        format_tags.append(data.topology)
    if data.thread_role in ("root", "continuation"):
        format_tags.append(f"thread_{data.thread_role}")

    context = data.creator_context
    return PostProfile(
        version=version,
        features_as_of=data.features_as_of,
        input_observed_at=data.observed_at,
        creator_key=data.creator_key.strip() if data.creator_key is not None else None,
        character_count=character_count,
        word_count=word_count,
        sentence_count=sentence_count,
        hashtags=hashtags,
        mentions=mentions,
        url_count=url_count,
        content_format=content_format,
        format_tags=tuple(format_tags),
        topology=data.topology,
        thread_role=data.thread_role,
        media_types=data.media_types,
        topic_signals=topic_signals,
        declared_topic=data.declared_topic.strip() if data.declared_topic is not None else None,
        intent_signals=intent_signals,
        declared_intent=data.declared_intent,
        creator_follower_count=context.follower_count if context else None,
        creator_context_observed_at=context.observed_at if context else None,
    )
