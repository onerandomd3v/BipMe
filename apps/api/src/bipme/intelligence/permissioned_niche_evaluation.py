"""Synthetic-only, time-respecting comparison of personal and niche evidence.

This research harness evaluates format-pattern recommendations. Peer evidence is
eligible only with explicit ownership, permission, and provenance fields. It has
no persistence, X API, embedding, or production retrieval dependency.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from bipme.intelligence.baselines import weighted_quantile

NICHE_EVALUATION_VERSION = "permissioned-niche-evaluation-v1"
OutcomeBand = Literal["strong", "typical", "weak"]
_BANDS: tuple[OutcomeBand, ...] = ("strong", "typical", "weak")


@dataclass(frozen=True)
class NicheEvaluationPost:
    """One synthetic creator post and one observed, window-specific outcome."""

    post_id: str
    creator_key: str
    niche: str
    audience_size_band: str
    language: str
    pattern: str
    metric: str
    metric_definition: str
    window: str
    value: float | None
    published_at: datetime
    observed_at: datetime
    owner_verified: bool = False
    comparison_permission: bool = False
    evidence_provenance: str = ""

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.post_id,
                self.creator_key,
                self.niche,
                self.audience_size_band,
                self.language,
                self.pattern,
                self.metric,
                self.metric_definition,
                self.window,
            )
        ):
            raise ValueError("post identity and comparison dimensions are required")
        _aware(self.published_at, "published_at")
        _aware(self.observed_at, "observed_at")
        if self.observed_at < self.published_at:
            raise ValueError("observed_at cannot precede publication")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("value must be finite or None")


@dataclass(frozen=True)
class NicheEvaluationSpec:
    """A predeclared, exact-window synthetic walk-forward evaluation."""

    target_creator_key: str
    niche: str
    audience_size_band: str
    language: str
    metric: str
    metric_definition: str
    window: str
    expected_observation_age_hours: float
    as_of: datetime
    minimum_history_posts: int = 8
    minimum_niche_contributors: int = 3
    minimum_examples_per_band_per_creator: int = 1
    maximum_examples_per_band_per_creator: int = 2
    observation_age_tolerance_hours: float = 2.0
    selection_basis: Literal["complete_history", "voluntary", "api_ranked", "unknown"] = "unknown"

    def __post_init__(self) -> None:
        _aware(self.as_of, "as_of")
        if not all(
            value.strip()
            for value in (
                self.target_creator_key,
                self.niche,
                self.audience_size_band,
                self.language,
                self.metric,
                self.metric_definition,
                self.window,
            )
        ):
            raise ValueError("target and exact comparison dimensions are required")
        if self.minimum_history_posts < 3:
            raise ValueError("minimum_history_posts must be at least 3")
        if self.minimum_niche_contributors < 2:
            raise ValueError("minimum_niche_contributors must be at least 2")
        if self.minimum_examples_per_band_per_creator < 1:
            raise ValueError("minimum band sample must be positive")
        if self.maximum_examples_per_band_per_creator < self.minimum_examples_per_band_per_creator:
            raise ValueError("maximum band sample cannot be below the minimum")
        if not math.isfinite(self.expected_observation_age_hours) or (
            self.expected_observation_age_hours <= 0
        ):
            raise ValueError("expected observation age must be finite and positive")
        if not math.isfinite(self.observation_age_tolerance_hours) or (
            self.observation_age_tolerance_hours < 0
        ):
            raise ValueError("observation age tolerance must be finite and non-negative")
        if self.selection_basis not in ("complete_history", "voluntary", "api_ranked", "unknown"):
            raise ValueError("unsupported selection_basis")


@dataclass(frozen=True)
class RecommendationEvaluation:
    """Held-out diagnostics for one recommendation source."""

    pattern: str | None
    recommendation_coverage: float
    recommendation_count: int
    scored_target_count: int
    recommendation_stability: float | None
    matched_target_count: int
    mean_matched_outcome_score: float | None
    sampled_band_counts: tuple[tuple[str, int], ...]
    outlier_recommendation_change_rate: float | None
    outlier_excluded_post_count: int
    outlier_sensitivity_status: Literal["measured", "not_identifiable"]


@dataclass(frozen=True)
class PermissionedNicheEvaluation:
    """Versioned results, never a real-world effectiveness claim."""

    version: str
    synthetic_only: bool
    selection_basis: str
    niche_contributor_count: int
    eligible_niche_post_count: int
    scored_target_count: int
    personal: RecommendationEvaluation
    permissioned_niche: RecommendationEvaluation
    incremental_mean_matched_outcome_score: float | None
    exclusions: tuple[tuple[str, int], ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class _Classified:
    post: NicheEvaluationPost
    band: OutcomeBand


@dataclass(frozen=True)
class _FoldRecommendation:
    target: NicheEvaluationPost
    band: OutcomeBand
    personal_pattern: str | None
    niche_pattern: str | None
    personal_robust_pattern: str | None
    niche_robust_pattern: str | None
    personal_outliers_removed: int
    niche_outliers_removed: int
    personal_outlier_evaluable: bool
    niche_outlier_evaluable: bool


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _age_hours(post: NicheEvaluationPost) -> float:
    return (post.observed_at - post.published_at).total_seconds() / 3600


def _matches(post: NicheEvaluationPost, spec: NicheEvaluationSpec) -> bool:
    return (
        post.niche == spec.niche
        and post.audience_size_band == spec.audience_size_band
        and post.language == spec.language
        and (post.metric, post.metric_definition, post.window)
        == (spec.metric, spec.metric_definition, spec.window)
        and abs(_age_hours(post) - spec.expected_observation_age_hours)
        <= spec.observation_age_tolerance_hours
    )


def _mismatch_reason(post: NicheEvaluationPost, spec: NicheEvaluationSpec) -> str | None:
    if (post.metric, post.metric_definition, post.window) != (
        spec.metric,
        spec.metric_definition,
        spec.window,
    ):
        return "metric_or_window_mismatch"
    if (
        abs(_age_hours(post) - spec.expected_observation_age_hours)
        > spec.observation_age_tolerance_hours
    ):
        return "observation_age_mismatch"
    if (post.niche, post.audience_size_band, post.language) != (
        spec.niche,
        spec.audience_size_band,
        spec.language,
    ):
        return "context_mismatch"
    return None


def _classify_history(
    posts: tuple[NicheEvaluationPost, ...],
    spec: NicheEvaluationSpec,
    *,
    exclusions: Counter[str],
) -> tuple[_Classified, ...]:
    """Label each past post against that creator's strictly earlier outcomes."""
    by_creator: dict[str, list[NicheEvaluationPost]] = defaultdict(list)
    for post in posts:
        if post.value is not None:
            by_creator[post.creator_key].append(post)
    output: list[_Classified] = []
    for post in sorted(posts, key=lambda item: (item.published_at, item.post_id)):
        if post.value is None:
            exclusions["missing_outcome"] += 1
            continue
        previous = [
            item
            for item in by_creator[post.creator_key]
            if item.published_at < post.published_at and item.observed_at <= post.published_at
        ]
        if len(previous) < spec.minimum_history_posts:
            exclusions["source_history_too_sparse"] += 1
            continue
        values = [float(item.value) for item in previous if item.value is not None]
        p25 = weighted_quantile(values, [1.0] * len(values), 0.25)
        p75 = weighted_quantile(values, [1.0] * len(values), 0.75)
        band: OutcomeBand = (
            "strong" if post.value > p75 else "weak" if post.value < p25 else "typical"
        )
        output.append(_Classified(post, band))
    return tuple(output)


def _spaced(values: list[_Classified], maximum: int) -> list[_Classified]:
    """Choose deterministic evenly spaced rows rather than the first or largest posts."""
    if len(values) <= maximum:
        return values
    if maximum == 1:
        return [values[len(values) // 2]]
    return [values[round(i * (len(values) - 1) / (maximum - 1))] for i in range(maximum)]


def _sample_balanced(
    rows: tuple[_Classified, ...], spec: NicheEvaluationSpec
) -> tuple[tuple[_Classified, ...], tuple[tuple[str, int], ...]]:
    grouped: dict[tuple[str, OutcomeBand], list[_Classified]] = defaultdict(list)
    for row in rows:
        grouped[(row.post.creator_key, row.band)].append(row)
    selected: list[_Classified] = []
    counts: Counter[str] = Counter()
    for creator in sorted({key[0] for key in grouped}):
        creator_bands = {
            band: sorted(
                grouped[(creator, band)], key=lambda row: (row.post.published_at, row.post.post_id)
            )
            for band in _BANDS
        }
        if any(
            len(creator_bands[band]) < spec.minimum_examples_per_band_per_creator for band in _BANDS
        ):
            continue
        for band in _BANDS:
            sampled = _spaced(creator_bands[band], spec.maximum_examples_per_band_per_creator)
            selected.extend(sampled)
            counts[band] += len(sampled)
    return tuple(selected), tuple((band, counts[band]) for band in _BANDS)


def _recommend(
    rows: tuple[_Classified, ...], spec: NicheEvaluationSpec, *, niche: bool
) -> tuple[str | None, tuple[tuple[str, int], ...], int]:
    sampled, counts = _sample_balanced(rows, spec)
    by_creator_pattern_band: dict[tuple[str, str, OutcomeBand], int] = Counter()
    by_creator_band: dict[tuple[str, OutcomeBand], int] = Counter()
    for row in sampled:
        by_creator_pattern_band[(row.post.creator_key, row.post.pattern, row.band)] += 1
        by_creator_band[(row.post.creator_key, row.band)] += 1
    creators = sorted({row.post.creator_key for row in sampled})
    if niche and len(creators) < spec.minimum_niche_contributors:
        return None, counts, len(creators)
    candidates = sorted({row.post.pattern for row in sampled if row.band == "strong"})
    scores: list[tuple[float, str]] = []
    for pattern in candidates:
        contributor_scores: list[float] = []
        for creator in creators:
            strong_n = by_creator_band[(creator, "strong")]
            weak_n = by_creator_band[(creator, "weak")]
            if strong_n and weak_n:
                strong_rate = by_creator_pattern_band[(creator, pattern, "strong")] / strong_n
                weak_rate = by_creator_pattern_band[(creator, pattern, "weak")] / weak_n
                contributor_scores.append(strong_rate - weak_rate)
        if contributor_scores:
            scores.append((math.fsum(contributor_scores) / len(contributor_scores), pattern))
    positive = [item for item in scores if item[0] > 0]
    if not positive:
        return None, counts, len(creators)
    return sorted(positive, key=lambda item: (-item[0], item[1]))[0][1], counts, len(creators)


def _without_outliers(
    rows: tuple[_Classified, ...],
) -> tuple[tuple[_Classified, ...], int, bool]:
    """Remove source-relative 3x-IQR outliers for a sensitivity replay."""
    grouped: dict[str, list[_Classified]] = defaultdict(list)
    for row in rows:
        grouped[row.post.creator_key].append(row)
    retained: list[_Classified] = []
    excluded_count = 0
    identifiable = bool(grouped)
    for values in grouped.values():
        outcomes = [float(row.post.value) for row in values if row.post.value is not None]
        if len(outcomes) < 4:
            retained.extend(values)
            identifiable = False
            continue
        p25 = weighted_quantile(outcomes, [1.0] * len(outcomes), 0.25)
        p75 = weighted_quantile(outcomes, [1.0] * len(outcomes), 0.75)
        spread = p75 - p25
        if spread == 0:
            retained.extend(values)
            identifiable = False
            continue
        accepted = [
            row
            for row in values
            if row.post.value is not None and p25 - 3 * spread <= row.post.value <= p75 + 3 * spread
        ]
        excluded_count += len(values) - len(accepted)
        retained.extend(accepted)
    return tuple(retained), excluded_count, identifiable


def _macro_stability(patterns: list[str | None]) -> tuple[str | None, float | None]:
    eligible = [item for item in patterns if item is not None]
    if not eligible:
        return None, None
    counts = Counter(eligible)
    winner = sorted(counts, key=lambda item: (-counts[item], item))[0]
    return winner, counts[winner] / len(eligible)


def _result(
    *,
    patterns: list[str | None],
    robust_patterns: list[str | None],
    scores: list[float],
    target_count: int,
    sampled_counts: tuple[tuple[str, int], ...],
    outlier_removed: list[int],
    outlier_evaluable: list[bool],
) -> RecommendationEvaluation:
    winner, stability = _macro_stability(patterns)
    recommendations = sum(item is not None for item in patterns)
    return RecommendationEvaluation(
        pattern=winner,
        recommendation_coverage=recommendations / target_count if target_count else 0.0,
        recommendation_count=recommendations,
        scored_target_count=target_count,
        recommendation_stability=stability,
        matched_target_count=len(scores),
        mean_matched_outcome_score=math.fsum(scores) / len(scores) if scores else None,
        sampled_band_counts=sampled_counts,
        outlier_recommendation_change_rate=(
            sum(
                patterns[index] != robust_patterns[index]
                for index, identifiable in enumerate(outlier_evaluable)
                if identifiable
            )
            / sum(outlier_evaluable)
            if any(outlier_evaluable)
            else None
        ),
        outlier_excluded_post_count=sum(outlier_removed),
        outlier_sensitivity_status=("measured" if any(outlier_evaluable) else "not_identifiable"),
    )


def evaluate_permissioned_niche_comparisons(
    posts: tuple[NicheEvaluationPost, ...], spec: NicheEvaluationSpec
) -> PermissionedNicheEvaluation:
    """Compare personal-only and equally weighted, permissioned niche patterns.

    Exclusion totals count fold-level eligibility decisions, so the same row may
    be counted more than once across target folds. Held-out outcomes are read only
    after the cutoff and are used solely to score the already fixed recommendation.
    """
    if any(
        not post.creator_key.startswith("synthetic-")
        or not post.post_id.startswith("synthetic-")
        or not post.evidence_provenance.startswith("synthetic://")
        for post in posts
    ):
        raise ValueError("this evaluator accepts synthetic identities and provenance only")
    exclusions: Counter[str] = Counter()
    first_by_id: dict[str, NicheEvaluationPost] = {}
    duplicate_ids: set[str] = set()
    for post in posts:
        if post.post_id in first_by_id:
            duplicate_ids.add(post.post_id)
        else:
            first_by_id[post.post_id] = post
    if duplicate_ids:
        posts = tuple(post for post in posts if post.post_id not in duplicate_ids)
        exclusions["duplicate_post"] += len(duplicate_ids)

    target_posts = sorted(
        (post for post in posts if post.creator_key == spec.target_creator_key),
        key=lambda item: (item.published_at, item.post_id),
    )
    peer_posts = tuple(post for post in posts if post.creator_key != spec.target_creator_key)
    eligible_peers: list[NicheEvaluationPost] = []
    for post in peer_posts:
        has_required_permission = True
        if not post.owner_verified:
            exclusions["owner_verification_missing"] += 1
            has_required_permission = False
        if not post.comparison_permission:
            exclusions["peer_permission_missing"] += 1
            has_required_permission = False
        if not post.evidence_provenance.strip():
            exclusions["provenance_missing"] += 1
            has_required_permission = False
        if not has_required_permission:
            continue
        if post.observed_at > spec.as_of:
            exclusions["future_observation"] += 1
            continue
        missing = post.value is None
        if missing:
            exclusions["missing_outcome"] += 1
        mismatch = _mismatch_reason(post, spec)
        if mismatch:
            exclusions[mismatch] += 1
        if missing or mismatch:
            continue
        eligible_peers.append(post)

    peer_creators = len({post.creator_key for post in eligible_peers})
    folds: list[_FoldRecommendation] = []
    personal_counts: Counter[str] = Counter()
    niche_counts: Counter[str] = Counter()
    eligible_niche_post_count = 0
    for target in target_posts:
        if target.published_at > spec.as_of or target.observed_at > spec.as_of:
            exclusions["target_outside_evaluation_period"] += 1
            continue
        if target.observed_at <= target.published_at:
            exclusions["target_outcome_not_post_publication"] += 1
            continue
        if not _matches(target, spec):
            exclusions["target_metric_or_window_mismatch"] += 1
            continue
        if target.value is None:
            exclusions["target_outcome_missing"] += 1
            continue

        prior_personal = tuple(
            post
            for post in posts
            if post.creator_key == spec.target_creator_key
            and post.published_at < target.published_at
            and post.observed_at <= target.published_at
            and _matches(post, spec)
            and post.value is not None
        )
        prior_peers = tuple(
            post
            for post in eligible_peers
            if post.published_at < target.published_at and post.observed_at <= target.published_at
        )
        if len(prior_personal) < spec.minimum_history_posts:
            exclusions["target_history_too_sparse"] += 1
            continue
        values = [float(item.value) for item in prior_personal if item.value is not None]
        p25 = weighted_quantile(values, [1.0] * len(values), 0.25)
        p75 = weighted_quantile(values, [1.0] * len(values), 0.75)
        target_band: OutcomeBand = (
            "strong" if target.value > p75 else "weak" if target.value < p25 else "typical"
        )
        classified_personal = _classify_history(prior_personal, spec, exclusions=exclusions)
        classified_peers = _classify_history(prior_peers, spec, exclusions=exclusions)
        personal_pattern, p_counts, _ = _recommend(classified_personal, spec, niche=False)
        niche_rows = classified_personal + classified_peers
        niche_pattern, n_counts, _ = _recommend(niche_rows, spec, niche=True)
        personal_clean, personal_outliers, personal_outlier_evaluable = _without_outliers(
            classified_personal
        )
        niche_clean, niche_outliers, niche_outlier_evaluable = _without_outliers(niche_rows)
        robust_personal, _, _ = _recommend(personal_clean, spec, niche=False)
        robust_niche, _, _ = _recommend(niche_clean, spec, niche=True)
        for band, count in p_counts:
            personal_counts[band] += count
        for band, count in n_counts:
            niche_counts[band] += count
        eligible_niche_post_count = max(eligible_niche_post_count, len(prior_peers))
        folds.append(
            _FoldRecommendation(
                target,
                target_band,
                personal_pattern,
                niche_pattern,
                robust_personal,
                robust_niche,
                personal_outliers,
                niche_outliers,
                personal_outlier_evaluable,
                niche_outlier_evaluable,
            )
        )

    def summarize(niche: bool) -> RecommendationEvaluation:
        pattern_field = "niche_pattern" if niche else "personal_pattern"
        robust_field = "niche_robust_pattern" if niche else "personal_robust_pattern"
        patterns = [getattr(fold, pattern_field) for fold in folds]
        robust_patterns = [getattr(fold, robust_field) for fold in folds]
        matched = [
            1.0 if fold.band == "strong" else -1.0 if fold.band == "weak" else 0.0
            for fold in folds
            if getattr(fold, pattern_field) == fold.target.pattern
        ]
        counts = niche_counts if niche else personal_counts
        return _result(
            patterns=patterns,
            robust_patterns=robust_patterns,
            scores=matched,
            target_count=len(folds),
            sampled_counts=tuple((band, counts[band]) for band in _BANDS),
            outlier_removed=[
                fold.niche_outliers_removed if niche else fold.personal_outliers_removed
                for fold in folds
            ],
            outlier_evaluable=[
                fold.niche_outlier_evaluable if niche else fold.personal_outlier_evaluable
                for fold in folds
            ],
        )

    personal_result = summarize(False)
    niche_result = summarize(True)
    incremental = (
        niche_result.mean_matched_outcome_score - personal_result.mean_matched_outcome_score
        if niche_result.mean_matched_outcome_score is not None
        and personal_result.mean_matched_outcome_score is not None
        else None
    )
    limitations = (
        "Synthetic outcomes only; this does not establish real-world recommendation usefulness.",
        "A strong/typical/weak label is creator-relative and uses only that creator's earlier, observed outcomes.",
        "Niche recommendations average creator-level pattern rates so prolific contributors do not dominate.",
        "The balanced sample includes all three outcome bands; it is not a population-representative cohort.",
        "Audience-size band, language, exact metric definition, age window, niche and provenance must match; residual confounding remains.",
        "Voluntary, API-ranked, and convenience cohorts are selection-biased; no significance or causal effect is estimated.",
        "Missing impressions and incomparable metrics are excluded, not imputed or treated as zero.",
        "A real pilot requires documented rights, verified creator ownership, explicit opt-in, withdrawal/deletion, and an adequate cohort.",
    )
    return PermissionedNicheEvaluation(
        version=NICHE_EVALUATION_VERSION,
        synthetic_only=True,
        selection_basis=spec.selection_basis,
        niche_contributor_count=peer_creators,
        eligible_niche_post_count=eligible_niche_post_count,
        scored_target_count=len(folds),
        personal=personal_result,
        permissioned_niche=niche_result,
        incremental_mean_matched_outcome_score=incremental,
        exclusions=tuple(sorted(exclusions.items())),
        limitations=limitations,
    )
