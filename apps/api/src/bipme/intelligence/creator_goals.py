"""Versioned, creator-declared goals for report-first intelligence.

The fields below express what a creator *wants* to reach, not what BipMe
knows about their actual followers or X's ranking decisions. No database,
network service, text model or platform data is needed to construct a snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

CREATOR_GOALS_VERSION = "creator-goals-v1"

CreatorOutcome = Literal["reach", "conversation", "qualified_interest", "authority"]
ContentStyle = Literal[
    "technical_explainer",
    "personal_story",
    "opinion",
    "question",
    "tutorial",
    "other",
]

_OUTCOMES = frozenset({"reach", "conversation", "qualified_interest", "authority"})
_STYLES = frozenset(
    {"technical_explainer", "personal_story", "opinion", "question", "tutorial", "other"}
)


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class CreatorGoalsSnapshot:
    """An immutable snapshot supplied by the creator, valid from recorded_at.

    The database and API layers must authorize creator_key and store each new
    revision independently rather than retroactively rewriting older reports.
    """

    creator_key: str
    recorded_at: datetime
    niche: str
    intended_audience: str
    priority_outcomes: tuple[CreatorOutcome, ...]
    preferred_styles: tuple[ContentStyle, ...] = ()
    language: str | None = None
    version: str = CREATOR_GOALS_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "creator_key", _required(self.creator_key, "creator_key"))
        object.__setattr__(self, "niche", _required(self.niche, "niche"))
        object.__setattr__(
            self, "intended_audience", _required(self.intended_audience, "intended_audience")
        )
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        if self.version != CREATOR_GOALS_VERSION:
            raise ValueError("Unsupported creator goals version")
        if (
            not isinstance(self.priority_outcomes, tuple)
            or not self.priority_outcomes
            or any(item not in _OUTCOMES for item in self.priority_outcomes)
            or len(set(self.priority_outcomes)) != len(self.priority_outcomes)
        ):
            raise ValueError("priority_outcomes must be a non-empty unique tuple of supported goals")
        if (
            not isinstance(self.preferred_styles, tuple)
            or any(item not in _STYLES for item in self.preferred_styles)
            or len(set(self.preferred_styles)) != len(self.preferred_styles)
        ):
            raise ValueError("preferred_styles must be a unique tuple of supported styles")
        if self.language is not None:
            object.__setattr__(self, "language", _required(self.language, "language"))

    def require_available_by(self, as_of: datetime, creator_key: str) -> None:
        """Disallow other-creator and future onboarding data in a report."""
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if self.creator_key != creator_key:
            raise ValueError("Creator goals belong to another creator")
        if self.recorded_at > as_of:
            raise ValueError("Creator goals were recorded after the report cutoff")
