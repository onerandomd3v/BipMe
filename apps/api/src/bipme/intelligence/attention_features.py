"""Small, inspectable attention-descriptor taxonomy (COD-371).

These are *descriptions of eligible content*, never estimates of actual
attention, impressions, viewer dwell time, ranking probability or causation.
They only use versioned PostProfile data collected by the report cutoff.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from bipme.intelligence.post_profiles import PROFILE_VERSION, PostProfile

ATTENTION_FEATURES_VERSION = "attention-descriptors-v2"
SignalOrigin = Literal["observed_structure", "lexical_heuristic", "creator_declared"]

_SPECIFICITY_MARKER = re.compile(r"(?:\b\d+(?:[.,]\d+)?%?\b|`[^`\n]+`)")
_STORY_CUE = re.compile(
    r"\b(?:i|we|my|our|when|before|after|then|eventually|started|built|learned|realized)\b",
    re.IGNORECASE,
)
_OPINION_MARKER = re.compile(
    r"\b(?:i think|i believe|in my opinion|i would argue|should|must|is overrated|is underrated)\b",
    re.IGNORECASE,
)
_CONTRAST_OPENING = re.compile(r"\b(?:but|however|instead|although|yet)\b", re.IGNORECASE)
_IMPERATIVE_OPENING = re.compile(
    r"^(?:stop|start|try|build|learn|use|remember|imagine|consider|never|don't|do not)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AttentionSignal:
    name: str
    origin: SignalOrigin
    # These are categorization *features*, not engagement outcomes.
    value: str


@dataclass(frozen=True)
class AttentionDescriptor:
    version: str
    post_profile_version: str
    features_as_of: datetime
    signals: tuple[AttentionSignal, ...]
    unknowns: tuple[str, ...]


def describe_attention_features(
    profile: PostProfile, *, as_of: datetime, text: str | None = None
) -> AttentionDescriptor:
    """Describe inspectable content signals without exposure or performance claims.

    ``text`` is optional because a persisted PostProfile intentionally does not
    retain raw text. Text-derived heuristics are emitted only when the caller has
    the authorized content at evaluation time; they are not reconstructed from
    outcome metrics or inferred audience behavior.
    """
    if profile.version != PROFILE_VERSION:
        raise ValueError("Unsupported Post Profile version")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if profile.features_as_of > as_of or profile.input_observed_at > as_of:
        raise ValueError("Post Profile contains information from after the report cutoff")
    if (
        profile.creator_context_observed_at is not None
        and profile.creator_context_observed_at > as_of
    ):
        raise ValueError("Creator context is after the report cutoff")

    signals: list[AttentionSignal] = []
    unknowns: list[str] = []
    if profile.content_format == "unknown":
        unknowns.append("content_format")
    else:
        signals.append(
            AttentionSignal("content_format", "observed_structure", profile.content_format)
        )
    if profile.topology is None:
        unknowns.append("topology")
    else:
        signals.append(AttentionSignal("topology", "observed_structure", profile.topology))
    if profile.thread_role is None:
        unknowns.append("thread_role")
    else:
        signals.append(AttentionSignal("thread_role", "observed_structure", profile.thread_role))

    if profile.word_count is None:
        unknowns.append("word_count")
    else:
        signals.append(AttentionSignal("word_count", "observed_structure", str(profile.word_count)))

    if profile.intent_signals is None:
        unknowns.append("text_intent_signals")
    else:
        for name in profile.intent_signals:
            # A '?' indicates a question marker, not evidence that viewers responded.
            signals.append(AttentionSignal(name, "lexical_heuristic", "present"))

    if text is None:
        unknowns.extend(
            (
                "specificity_markers",
                "storytelling_cues",
                "opinion_marker",
                "opening_structure",
            )
        )
    else:
        specificity_count = len(_SPECIFICITY_MARKER.findall(text))
        signals.append(
            AttentionSignal("specificity_markers", "lexical_heuristic", str(specificity_count))
        )
        story_count = len(_STORY_CUE.findall(text))
        signals.append(AttentionSignal("storytelling_cues", "lexical_heuristic", str(story_count)))
        opinion_present = _OPINION_MARKER.search(text) is not None
        if opinion_present:
            signals.append(AttentionSignal("opinion_marker", "lexical_heuristic", "present"))

        opening = text.strip().splitlines()[0].strip() if text.strip() else ""
        if not opening:
            opening_value = "empty"
        elif "?" in opening:
            opening_value = "question"
        elif _CONTRAST_OPENING.search(opening):
            opening_value = "contrast"
        elif re.match(r"^\d+[.)]", opening):
            opening_value = "numbered"
        elif _IMPERATIVE_OPENING.search(opening):
            opening_value = "imperative"
        else:
            opening_value = "other"
        signals.append(AttentionSignal("opening_structure", "lexical_heuristic", opening_value))

    if profile.declared_intent is not None:
        signals.append(
            AttentionSignal("declared_intent", "creator_declared", profile.declared_intent)
        )
    if profile.declared_topic is not None:
        signals.append(
            AttentionSignal("declared_topic", "creator_declared", profile.declared_topic)
        )

    return AttentionDescriptor(
        version=ATTENTION_FEATURES_VERSION,
        post_profile_version=profile.version,
        features_as_of=profile.features_as_of,
        signals=tuple(signals),
        unknowns=tuple(unknowns),
    )
