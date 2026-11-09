"""Conservative within-creator descriptive contrasts; no claims of causal reach.

Only versioned, cutoff-safe personal post profiles are eligible. Cohort groups
must come from already measured same-creator, exact-window outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from bipme.intelligence.attention_features import describe_attention_features
from bipme.intelligence.post_profiles import PostProfile

PATTERN_VERSION = "personal-content-contrasts-v1"
MIN_GROUP_POSTS = 2
MIN_TOTAL_POSTS = 8
MIN_PREVALENCE_GAP = 0.40

if TYPE_CHECKING:
    from bipme.intelligence.creator_report import PersonalMetricCohort


@dataclass(frozen=True)
class PersonalPostProfile:
    post_id: str
    profile: PostProfile


@dataclass(frozen=True)
class ContentPatternContrast:
    version: str
    metric: str
    metric_definition: str
    window: str
    feature: str
    feature_value: str
    strong_count: int
    strong_total: int
    weak_count: int
    weak_total: int
    strong_post_ids: tuple[str, ...]
    weak_post_ids: tuple[str, ...]
    limitations: tuple[str, ...]


def compare_personal_content_patterns(
    creator_key: str,
    as_of: datetime,
    cohorts: tuple[PersonalMetricCohort, ...],
    profiles: tuple[PersonalPostProfile, ...],
) -> tuple[ContentPatternContrast, ...]:
    """List explainable cohort associations without speculating about exposure.

    Profiles with duplicate IDs or invalid ownership/timestamps are excluded.
    A contrast is reported only for sufficiently populated strong/weak groups,
    from profiles present in both a single cohort and the creator's own archive.
    """
    if not creator_key.strip() or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("creator key and timezone-aware cutoff required")
    lookup: dict[str, PostProfile] = {}
    duplicates: set[str] = set()
    for record in profiles:
        if not record.post_id.strip():
            raise ValueError("post_id required")
        profile = record.profile
        if (
            profile.creator_key != creator_key
            or profile.features_as_of > as_of
            or profile.input_observed_at > as_of
        ):
            continue
        if record.post_id in lookup:
            duplicates.add(record.post_id)
        else:
            lookup[record.post_id] = profile
    for post_id in duplicates:
        lookup.pop(post_id, None)

    features: dict[str, set[tuple[str, str]]] = {}
    for post_id, profile in lookup.items():
        try:
            signals = describe_attention_features(profile, as_of=as_of).signals
        except ValueError:
            continue
        approved: set[tuple[str, str]] = set()
        for signal in signals:
            if signal.name in (
                "content_format",
                "topology",
                "thread_role",
                "declared_topic",
                "declared_intent",
                "question_marker",
                "reply_invitation",
            ):
                approved.add((signal.name, signal.value.casefold()))
        features[post_id] = approved

    results: list[ContentPatternContrast] = []
    for cohort in cohorts:
        if cohort.evidence_strength not in ("High", "Moderate"):
            continue
        strong = tuple(sorted(pid for pid in cohort.strong_post_ids if pid in features))
        weak = tuple(sorted(pid for pid in cohort.weak_post_ids if pid in features))
        if (
            len(strong) < MIN_GROUP_POSTS
            or len(weak) < MIN_GROUP_POSTS
            or len(strong) + len(weak) < MIN_TOTAL_POSTS
        ):
            continue
        candidates = sorted(set().union(*(features[pid] for pid in (*strong, *weak))))
        for name, value in candidates:
            stronger = tuple(pid for pid in strong if (name, value) in features[pid])
            weaker = tuple(pid for pid in weak if (name, value) in features[pid])
            gap = len(stronger) / len(strong) - len(weaker) / len(weak)
            if abs(gap) < MIN_PREVALENCE_GAP or min(len(stronger), len(weaker)) == 0:
                continue
            results.append(
                ContentPatternContrast(
                    version=PATTERN_VERSION,
                    metric=cohort.metric,
                    metric_definition=cohort.metric_definition,
                    window=cohort.window,
                    feature=name,
                    feature_value=value,
                    strong_count=len(stronger),
                    strong_total=len(strong),
                    weak_count=len(weaker),
                    weak_total=len(weak),
                    strong_post_ids=stronger,
                    weak_post_ids=weaker,
                    limitations=(
                        "Historical association only, not causal or predictive.",
                        "Strong/weak selection depends on measured outcomes and can be biased.",
                        "Declared topics and intents are creator labels, not verified audience behavior.",
                    ),
                )
            )
    return tuple(
        sorted(
            results,
            key=lambda item: (
                item.metric,
                item.window,
                item.feature,
                item.feature_value,
            ),
        )
    )
