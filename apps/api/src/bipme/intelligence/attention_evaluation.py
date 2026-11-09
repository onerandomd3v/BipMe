"""Deterministic, synthetic-first evaluation for versioned attention descriptors.

This is a descriptive research harness, not a ranking model or evidence that a
feature predicts exposure. Feature descriptors and measured outcomes are kept in
separate input fields. Walk-forward checks use only earlier measured outcomes to
set group boundaries, and only features that existed by each post's publication.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from bipme.intelligence.attention_features import (
    ATTENTION_FEATURES_VERSION,
    AttentionDescriptor,
    describe_attention_features,
)
from bipme.intelligence.baselines import weighted_quantile
from bipme.intelligence.content_patterns import MIN_GROUP_POSTS, MIN_TOTAL_POSTS
from bipme.intelligence.creator_goals import CreatorGoalsSnapshot
from bipme.intelligence.post_profiles import PROFILE_VERSION, PostProfile

ATTENTION_EVALUATION_VERSION = "attention-feature-evaluation-v1"
SelectionBasis = Literal["complete_archive", "sampled", "unknown"]
OutcomeBand = Literal["strong", "typical", "weak"]
EvaluationState = Literal["descriptive_sample_adequate", "insufficient_evidence"]
_GROUPS: tuple[OutcomeBand, ...] = ("strong", "typical", "weak")


@dataclass(frozen=True)
class AttentionEvaluationPost:
    """One creator-owned profile, raw authorized text, and a separate outcome."""

    post_id: str
    creator_key: str
    published_at: datetime
    profile: PostProfile
    text: str | None
    metric: str
    metric_definition: str
    window: str
    outcome: float | None
    outcome_observed_at: datetime


@dataclass(frozen=True)
class AttentionEvaluationSpec:
    """Cutoff, metric and sampling declarations for one evaluation run."""

    goals: CreatorGoalsSnapshot
    as_of: datetime
    metric: str
    metric_definition: str
    window: str
    selection_basis: SelectionBasis
    minimum_history_posts: int = MIN_TOTAL_POSTS
    minimum_group_posts: int = MIN_GROUP_POSTS


@dataclass(frozen=True)
class GroupPrevalence:
    """Known-data denominator and prevalence for one category/outcome band."""

    group: OutcomeBand
    category: str
    present_count: int
    known_count: int
    prevalence: float | None


@dataclass(frozen=True)
class FeatureEvaluation:
    """Descriptive association and outlier sensitivity for one feature."""

    feature: str
    origin: str
    groups: tuple[GroupPrevalence, ...]
    discriminative_category: str | None
    strong_minus_weak_gap: float | None
    outlier_excluded_gap: float | None
    groups_adequate: bool
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class FeatureAblation:
    """Model-free drop-one-feature diagnostic; no combined score is fit."""

    feature_removed: str
    associations_before: int
    associations_after: int
    associations_removed: int
    feature_evidence_removed: bool


@dataclass(frozen=True)
class WalkForwardSummary:
    """Held-out feature summaries and exclusions from chronological replay."""

    target_count: int
    targets_without_enough_prior_history: int
    strong_targets: int
    typical_targets: int
    weak_targets: int
    features: tuple[FeatureEvaluation, ...]
    ablations: tuple[FeatureAblation, ...]
    leakage_exclusions: tuple[tuple[str, int], ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class AttentionEvaluation:
    """Versioned output, diagnostics and limitations for a synthetic-first run."""

    version: str
    attention_features_version: str
    post_profile_version: str
    creator_key: str
    creator_goals_version: str
    creator_goals_recorded_at: datetime
    creator_niche: str
    intended_audience: str
    priority_outcomes: tuple[str, ...]
    preferred_styles: tuple[str, ...]
    metric: str
    metric_definition: str
    window: str
    as_of: datetime
    selection_basis: SelectionBasis
    evidence_state: EvaluationState
    eligible_post_count: int
    missing_outcome_count: int
    missing_metadata_count: int
    duplicate_post_count: int
    sample_adequate: bool
    features: tuple[FeatureEvaluation, ...]
    ablations: tuple[FeatureAblation, ...]
    walk_forward: WalkForwardSummary
    limitations: tuple[str, ...]


def _aware(value: datetime, name: str) -> None:
    """Reject missing timezone information before chronological comparisons."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _validate(spec: AttentionEvaluationSpec) -> None:
    """Validate the evaluation cutoff, metric identity and creator-goal snapshot."""
    _aware(spec.as_of, "as_of")
    if not all(value.strip() for value in (spec.metric, spec.metric_definition, spec.window)):
        raise ValueError("metric, metric_definition and window are required")
    if spec.selection_basis not in ("complete_archive", "sampled", "unknown"):
        raise ValueError("unsupported selection_basis")
    if spec.minimum_history_posts < 3 or spec.minimum_group_posts < 1:
        raise ValueError("minimum history and group sizes are invalid")
    spec.goals.require_available_by(spec.as_of, spec.goals.creator_key)


def _descriptor(post: AttentionEvaluationPost, cutoff: datetime) -> AttentionDescriptor:
    """Extract a cutoff-safe versioned descriptor from one evaluation post."""
    return describe_attention_features(post.profile, as_of=cutoff, text=post.text)


def _feature_values(descriptor: AttentionDescriptor) -> tuple[tuple[str, str, str], ...]:
    """Return (name, origin, category), including known absence for marker features."""
    signals: dict[str, tuple[str, str]] = {
        signal.name: (signal.origin, signal.value) for signal in descriptor.signals
    }
    known = {name for name in signals if name not in descriptor.unknowns}
    if "text_intent_signals" not in descriptor.unknowns:
        known.update(("question_marker", "reply_invitation"))
    if "opinion_marker" not in descriptor.unknowns:
        known.add("opinion_marker")
    values: list[tuple[str, str, str]] = []
    for name in sorted(known):
        origin, value = signals.get(name, ("lexical_heuristic", "absent"))
        if name in (
            "specificity_markers",
            "storytelling_cues",
            "informative_framing_cues",
            "curiosity_gap_cues",
        ):
            value = "0" if value == "0" else "1+"
        values.append((name, origin, value))
    return tuple(values)


def _classify(value: float, p25: float, p75: float) -> OutcomeBand:
    """Assign one outcome to creator-relative strong, typical or weak bands."""
    if value > p75:
        return "strong"
    if value < p25:
        return "weak"
    return "typical"


def _prevalence(
    rows: list[tuple[OutcomeBand, tuple[tuple[str, str, str], ...]]],
    feature: str,
    category: str,
    group: OutcomeBand,
) -> tuple[int, int, float | None]:
    """Calculate a feature category's prevalence over known rows in one band."""
    known = [
        values for band, values in rows if band == group and any(x[0] == feature for x in values)
    ]
    present = sum(
        any(name == feature and value == category for name, _, value in values) for values in known
    )
    return present, len(known), (present / len(known) if known else None)


def _summaries(
    rows: list[tuple[OutcomeBand, tuple[tuple[str, str, str], ...]]],
    *,
    minimum_group_posts: int,
) -> tuple[FeatureEvaluation, ...]:
    """Summarize category prevalence and denominator adequacy for each feature."""
    names = sorted({name for _, values in rows for name, _, _ in values})
    output: list[FeatureEvaluation] = []
    for feature in names:
        origin = next(
            value_origin
            for _, values in rows
            for name, value_origin, _ in values
            if name == feature
        )
        categories = sorted(
            {value for _, values in rows for name, _, value in values if name == feature}
        )
        group_reports: list[GroupPrevalence] = []
        gaps: list[tuple[str, float]] = []
        for category in categories:
            values_by_group = {
                group: _prevalence(rows, feature, category, group) for group in _GROUPS
            }
            for group, (present, known, prevalence) in values_by_group.items():
                group_reports.append(GroupPrevalence(group, category, present, known, prevalence))
            strong_rate = values_by_group["strong"][2]
            weak_rate = values_by_group["weak"][2]
            if strong_rate is not None and weak_rate is not None:
                gaps.append((category, strong_rate - weak_rate))
        # Summaries are descriptive; outlier sensitivity is calculated by callers
        # through a second pass with extreme outcome rows removed.
        known_by_group = {
            group: sum(
                band == group and any(name == feature for name, _, _ in values)
                for band, values in rows
            )
            for group in _GROUPS
        }
        adequate = all(known_by_group[group] >= minimum_group_posts for group in _GROUPS)
        ordered_gaps = sorted(gaps, key=lambda item: (-abs(item[1]), item[0]))
        discriminative_category: str | None = None
        gap: float | None = None
        if ordered_gaps:
            discriminative_category, gap = ordered_gaps[0]
        output.append(
            FeatureEvaluation(
                feature=feature,
                origin=origin,
                groups=tuple(group_reports),
                discriminative_category=discriminative_category,
                strong_minus_weak_gap=gap,
                outlier_excluded_gap=None,
                groups_adequate=adequate,
                limitations=(
                    "Prevalence differences are descriptive associations, not causal effects or exposure predictions.",
                    "A missing feature is excluded from its own denominator, not treated as absence.",
                    "No significance test or predictive utility estimate is calculated.",
                ),
            )
        )
    return tuple(output)


def _ablations(features: tuple[FeatureEvaluation, ...]) -> tuple[FeatureAblation, ...]:
    """Count descriptive feature associations before and after each drop-one test."""
    associations = sum(
        1
        for item in features
        if item.groups_adequate
        and item.strong_minus_weak_gap is not None
        and item.strong_minus_weak_gap != 0
    )
    return tuple(
        FeatureAblation(
            feature_removed=item.feature,
            associations_before=associations,
            associations_after=associations
            - int(
                item.groups_adequate
                and item.strong_minus_weak_gap is not None
                and item.strong_minus_weak_gap != 0
            ),
            associations_removed=int(
                item.groups_adequate
                and item.strong_minus_weak_gap is not None
                and item.strong_minus_weak_gap != 0
            ),
            feature_evidence_removed=True,
        )
        for item in features
    )


def _eligible_records(
    posts: tuple[AttentionEvaluationPost, ...], spec: AttentionEvaluationSpec
) -> tuple[tuple[AttentionEvaluationPost, ...], int, int, tuple[tuple[str, int], ...]]:
    """Exclude malformed, duplicate, future, mismatched and missing-outcome rows."""
    reasons: Counter[str] = Counter()
    first_by_id: dict[str, AttentionEvaluationPost] = {}
    duplicates: set[str] = set()
    accepted: list[AttentionEvaluationPost] = []
    for post in posts:
        if not post.post_id.strip():
            reasons["missing_post_id"] += 1
            continue
        if post.post_id in first_by_id:
            duplicates.add(post.post_id)
            continue
        first_by_id[post.post_id] = post
        if (
            post.creator_key != spec.goals.creator_key
            or post.profile.creator_key != spec.goals.creator_key
        ):
            reasons["creator_mismatch"] += 1
            continue
        if post.profile.version != PROFILE_VERSION:
            reasons["unsupported_profile_version"] += 1
            continue
        _aware(post.published_at, "published_at")
        _aware(post.outcome_observed_at, "outcome_observed_at")
        if post.published_at > spec.as_of or post.outcome_observed_at > spec.as_of:
            reasons["future_record"] += 1
            continue
        if post.outcome_observed_at < post.published_at:
            reasons["outcome_before_publication"] += 1
            continue
        if (
            post.profile.features_as_of > post.published_at
            or post.profile.input_observed_at > post.published_at
        ):
            reasons["future_feature"] += 1
            continue
        if (post.metric, post.metric_definition, post.window) != (
            spec.metric,
            spec.metric_definition,
            spec.window,
        ):
            reasons["metric_mismatch"] += 1
            continue
        if post.outcome is None:
            reasons["missing_outcome"] += 1
            continue
        if not math.isfinite(post.outcome) or post.outcome < 0:
            reasons["invalid_outcome"] += 1
            continue
        accepted.append(post)
    for post_id in duplicates:
        accepted = [post for post in accepted if post.post_id != post_id]
    reasons["duplicate_post"] += len(duplicates)
    return (
        tuple(sorted(accepted, key=lambda item: (item.published_at, item.post_id))),
        reasons["missing_outcome"],
        len(duplicates),
        tuple(sorted(reasons.items())),
    )


def _walk_forward(
    posts: tuple[AttentionEvaluationPost, ...], spec: AttentionEvaluationSpec
) -> WalkForwardSummary:
    """Replay targets in publication order using only outcomes known at each cutoff."""
    test_rows: list[tuple[OutcomeBand, tuple[tuple[str, str, str], ...]]] = []
    insufficient = 0
    exclusions: Counter[str] = Counter()
    target_count = 0
    for target_index, target in enumerate(posts):
        target_count += 1
        if spec.goals.recorded_at > target.published_at:
            exclusions["goals_after_target_publication"] += 1
            continue
        prior = [
            post
            for post in posts[:target_index]
            if post.published_at < target.published_at
            and post.outcome_observed_at <= target.published_at
        ]
        not_yet_observed = sum(
            post.published_at < target.published_at
            and post.outcome_observed_at > target.published_at
            for post in posts[:target_index]
        )
        if not_yet_observed:
            exclusions["prior_outcome_not_observed_by_target_cutoff"] += not_yet_observed
        if len(prior) < spec.minimum_history_posts:
            insufficient += 1
            continue
        values = [float(item.outcome) for item in prior if item.outcome is not None]
        p25 = weighted_quantile(values, [1.0] * len(values), 0.25)
        p75 = weighted_quantile(values, [1.0] * len(values), 0.75)
        if target.outcome is None:
            exclusions["target_outcome_missing"] += 1
            continue
        band = _classify(target.outcome, p25, p75)
        descriptor = _descriptor(target, target.published_at)
        test_rows.append((band, _feature_values(descriptor)))

    features = _summaries(test_rows, minimum_group_posts=spec.minimum_group_posts)
    bands = Counter(band for band, _ in test_rows)
    limits = [
        "Walk-forward groups use only same-creator outcomes observed before each target publication.",
        "A target's eventual outcome is used only as the backtest label, never as a feature or threshold input.",
        "Synthetic or selected observations do not establish real-world predictive performance.",
    ]
    return WalkForwardSummary(
        target_count=target_count,
        targets_without_enough_prior_history=insufficient,
        strong_targets=bands["strong"],
        typical_targets=bands["typical"],
        weak_targets=bands["weak"],
        features=features,
        ablations=_ablations(features),
        leakage_exclusions=tuple(sorted(exclusions.items())),
        limitations=tuple(limits),
    )


def evaluate_attention_features(
    posts: tuple[AttentionEvaluationPost, ...], spec: AttentionEvaluationSpec
) -> AttentionEvaluation:
    """Evaluate inspectable features across outcome bands and by walk-forward replay."""
    _validate(spec)
    eligible, missing_outcomes, duplicate_count, exclusions = _eligible_records(posts, spec)
    if eligible:
        values = [float(post.outcome) for post in eligible if post.outcome is not None]
        p25 = weighted_quantile(values, [1.0] * len(values), 0.25)
        p75 = weighted_quantile(values, [1.0] * len(values), 0.75)
        rows = [
            (
                _classify(float(post.outcome), p25, p75),
                _feature_values(_descriptor(post, post.published_at)),
            )
            for post in eligible
            if post.outcome is not None
        ]
    else:
        rows = []
    features = _summaries(rows, minimum_group_posts=spec.minimum_group_posts)
    outlier_removed_count = 0
    if eligible and rows:
        iqr = p75 - p25
        lower_fence, upper_fence = p25 - 3 * iqr, p75 + 3 * iqr
        retained = tuple(
            (post, row)
            for post, row in zip(eligible, rows, strict=True)
            if post.outcome is not None and lower_fence <= post.outcome <= upper_fence
        )
        outlier_removed_count = len(eligible) - len(retained)
        retained_rows = [row for _, row in retained]
        sensitivity: dict[str, float | None] = {}
        for item in features:
            category = item.discriminative_category
            if category is None:
                sensitivity[item.feature] = None
                continue
            strong_rate = _prevalence(retained_rows, item.feature, category, "strong")[2]
            weak_rate = _prevalence(retained_rows, item.feature, category, "weak")[2]
            sensitivity[item.feature] = (
                strong_rate - weak_rate
                if strong_rate is not None and weak_rate is not None
                else None
            )
        features = tuple(
            replace(item, outlier_excluded_gap=sensitivity.get(item.feature)) for item in features
        )
    ablations = _ablations(features)
    missing_metadata_count = sum(
        len(_descriptor(post, post.published_at).unknowns) for post in eligible
    )
    group_counts = Counter(group for group, _ in rows)
    sample_adequate = len(eligible) >= MIN_TOTAL_POSTS and all(
        group_counts[group] >= spec.minimum_group_posts for group in _GROUPS
    )
    limitations = [
        "Outcome quartiles reuse creator-relative baseline grouping; feature prevalence does not imply causation.",
        "This harness does not estimate impressions, viewer-level attention, X ranking scores or causal amplification.",
        "Observed metrics, descriptive features and creator-declared goals remain separate inputs.",
        "Specificity, storytelling, opinion and opening-structure descriptors are lexical heuristics, not semantic judgments.",
        "Backtests are an evaluation diagnostic and do not constitute model training or a calibrated forecast.",
    ]
    if spec.selection_basis != "complete_archive":
        limitations.append(
            "Selection basis is incomplete or unknown; prevalence may reflect archive/search selection bias."
        )
    if not sample_adequate:
        limitations.append(
            "Sample or one or more outcome groups are too small for a stable comparison."
        )
    if missing_metadata_count:
        limitations.append(
            f"{missing_metadata_count} feature fields are unknown across eligible posts; each feature uses its own known-data denominator."
        )
    if outlier_removed_count:
        limitations.append(
            f"Outlier sensitivity excludes {outlier_removed_count} outcome(s) beyond 3×IQR fences; the reported contrast remains descriptive."
        )
    return AttentionEvaluation(
        version=ATTENTION_EVALUATION_VERSION,
        attention_features_version=ATTENTION_FEATURES_VERSION,
        post_profile_version=PROFILE_VERSION,
        creator_key=spec.goals.creator_key,
        creator_goals_version=spec.goals.version,
        creator_goals_recorded_at=spec.goals.recorded_at,
        creator_niche=spec.goals.niche,
        intended_audience=spec.goals.intended_audience,
        priority_outcomes=tuple(spec.goals.priority_outcomes),
        preferred_styles=tuple(spec.goals.preferred_styles),
        metric=spec.metric,
        metric_definition=spec.metric_definition,
        window=spec.window,
        as_of=spec.as_of,
        selection_basis=spec.selection_basis,
        evidence_state=(
            "descriptive_sample_adequate" if sample_adequate else "insufficient_evidence"
        ),
        eligible_post_count=len(eligible),
        missing_outcome_count=missing_outcomes,
        missing_metadata_count=missing_metadata_count,
        duplicate_post_count=duplicate_count,
        sample_adequate=sample_adequate,
        features=features,
        ablations=ablations,
        walk_forward=_walk_forward(eligible, spec),
        limitations=tuple(
            (
                *limitations,
                *(f"Excluded: {count} {reason}." for reason, count in exclusions if count),
            )
        ),
    )
