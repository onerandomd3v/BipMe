"""Deterministic, as-of comparable-post retrieval with no outcome-based ranking.

This module depends on the COD-351 embedding identity and COD-350 Post Profile only.
A persistence adapter may implement VectorCandidateSource with pgvector later; it must
return a bounded semantic candidate page and preserve pre-filter exclusion/count metadata.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from bipme.intelligence.embeddings import EmbeddingIdentity
from bipme.intelligence.post_profiles import PostProfile

RETRIEVAL_ALGORITHM_VERSION = "comparable-retrieval-v1"
RANKING_CONFIG_VERSION = "comparable-ranking-config-v1"

RetrievalState = Literal["matched", "insufficient_evidence", "no_match"]


def _aware(value: datetime, name: str) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _vector_error(values: tuple[float, ...], identity: EmbeddingIdentity) -> str | None:
    if len(values) != identity.dimensions:
        return "embedding_dimensions_mismatch"
    if not all(math.isfinite(value) for value in values):
        return "embedding_contains_non_finite_values"
    norm = math.sqrt(math.fsum(value * value for value in values))
    if norm == 0:
        return "embedding_vector_is_zero"
    if identity.normalized and not math.isclose(norm, 1.0, rel_tol=1e-3, abs_tol=1e-3):
        return "embedding_not_normalized"
    return None


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    dot = math.fsum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


@dataclass(frozen=True)
class MetricRequirement:
    """An exact metric definition/window required for a downstream baseline."""

    metric: str
    definition: str
    window: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.metric, self.definition, self.window)):
            raise ValueError("metric, definition and window are required")


@dataclass(frozen=True)
class MetricEligibilityEvidence:
    """Eligibility metadata only; metric values never enter retrieval or ranking."""

    metric: str
    definition: str
    window: str
    observed_at: datetime
    is_usable: bool


@dataclass(frozen=True)
class ComparableCandidate:
    """One canonical historical post and its versioned descriptive retrieval inputs."""

    post_id: str
    creator_key: str
    published_at: datetime
    available: bool
    profile: PostProfile | None
    embedding_identity: EmbeddingIdentity | None
    embedding: tuple[float, ...] | None
    embedding_observed_at: datetime | None
    metric_evidence: tuple[MetricEligibilityEvidence, ...] = ()


@dataclass(frozen=True)
class DraftAssessment:
    """Pre-publication retrieval inputs, fixed at one assessment cutoff."""

    assessment_id: str
    creator_key: str
    as_of: datetime
    profile: PostProfile
    embedding_identity: EmbeddingIdentity
    embedding: tuple[float, ...]
    embedding_observed_at: datetime

    def __post_init__(self) -> None:
        if not self.assessment_id.strip() or not self.creator_key.strip():
            raise ValueError("assessment_id and creator_key are required")
        if not _aware(self.as_of, "as_of") or not _aware(
            self.embedding_observed_at, "embedding_observed_at"
        ):
            raise ValueError("assessment timestamps must be timezone-aware")
        if self.embedding_observed_at > self.as_of:
            raise ValueError("draft embedding was generated after assessment cutoff")
        if self.profile.features_as_of > self.as_of:
            raise ValueError("draft profile features are after assessment cutoff")
        if self.profile.input_observed_at > self.as_of:
            raise ValueError("draft profile input was observed after assessment cutoff")
        if self.profile.creator_context_observed_at is not None and (
            self.profile.creator_context_observed_at > self.as_of
        ):
            raise ValueError("draft creator context is after assessment cutoff")
        if self.profile.creator_key not in (None, self.creator_key):
            raise ValueError("draft profile creator differs from assessment creator")
        error = _vector_error(self.embedding, self.embedding_identity)
        if error:
            raise ValueError(f"invalid draft embedding: {error}")


@dataclass(frozen=True)
class RankingWeights:
    """Illustrative, caller-configurable starting weights from the research design."""

    semantic: float = 0.30
    topic: float = 0.18
    intent: float = 0.15
    format: float = 0.12
    structure: float = 0.0

    def __post_init__(self) -> None:
        values = (self.semantic, self.topic, self.intent, self.format, self.structure)
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("ranking weights must be finite and non-negative")
        if not any(value > 0 for value in values):
            raise ValueError("at least one ranking weight must be positive")


@dataclass(frozen=True)
class RetrievalConfig:
    """Versioned ranking and candidate limits; thresholds are uncalibrated heuristics."""

    candidate_limit: int = 100
    result_limit: int = 20
    minimum_comparables: int = 3
    minimum_relevance: float = 0.55
    weights: RankingWeights = RankingWeights()
    algorithm_version: str = RETRIEVAL_ALGORITHM_VERSION
    config_version: str = RANKING_CONFIG_VERSION
    metric_requirements: tuple[MetricRequirement, ...] = ()

    def __post_init__(self) -> None:
        if self.candidate_limit < 1 or self.result_limit < 1 or self.minimum_comparables < 1:
            raise ValueError("candidate, result and minimum comparable limits must be positive")
        if self.result_limit < self.minimum_comparables:
            raise ValueError("result_limit must be at least minimum_comparables")
        if not math.isfinite(self.minimum_relevance) or not 0 <= self.minimum_relevance <= 1:
            raise ValueError("minimum_relevance must be in [0, 1]")
        if not self.algorithm_version.strip() or not self.config_version.strip():
            raise ValueError("algorithm and config versions are required")
        keys = [(item.metric, item.definition, item.window) for item in self.metric_requirements]
        if len(keys) != len(set(keys)):
            raise ValueError("metric requirements must be unique")


@dataclass(frozen=True)
class VectorCandidateQuery:
    """Minimal persistence query contract for a future pgvector read adapter.

    The adapter should constrain creator, publication cutoff and exact index identity
    before ordering by cosine distance. It must return deterministic rows, total matching
    count, truncation state and any rows rejected by those storage-side filters.
    Intelligence rechecks all eligibility rules after the query.
    """

    creator_key: str
    as_of: datetime
    embedding_identity: EmbeddingIdentity
    query_embedding: tuple[float, ...]
    limit: int


@dataclass(frozen=True)
class VectorCandidateBatch:
    candidates: tuple[ComparableCandidate, ...]
    total_candidate_count: int
    vector_candidate_count: int
    truncated: bool
    prefiltered_exclusions: tuple[CandidateExclusion, ...] = ()


class VectorCandidateSource(Protocol):
    """Narrow contract implemented by an in-memory test or future pgvector adapter."""

    def search(self, query: VectorCandidateQuery) -> VectorCandidateBatch: ...


@dataclass(frozen=True)
class InMemoryVectorCandidateSource:
    """Deterministic exact-cosine adapter for synthetic tests and local experiments."""

    candidates: tuple[ComparableCandidate, ...]

    def search(self, query: VectorCandidateQuery) -> VectorCandidateBatch:
        counts = Counter(item.post_id for item in self.candidates)
        duplicates = {post_id for post_id, count in counts.items() if count > 1}
        exclusions: list[CandidateExclusion] = []
        rankable: list[tuple[float, ComparableCandidate]] = []

        for candidate in self.candidates:
            reasons: list[str] = []
            if candidate.post_id in duplicates:
                reasons.append("duplicate_candidate_id")
            if not candidate.post_id.strip():
                reasons.append("missing_post_id")
            if not candidate.available:
                reasons.append("post_unavailable")
            if candidate.creator_key != query.creator_key:
                reasons.append("different_creator")
            if not _aware(candidate.published_at, "published_at"):
                reasons.append("publication_timestamp_not_timezone_aware")
            elif candidate.published_at >= query.as_of:
                reasons.append("not_published_before_assessment_cutoff")
            if candidate.embedding is None:
                reasons.append("missing_embedding")
            if candidate.embedding_identity is None:
                reasons.append("missing_embedding_identity")
            elif candidate.embedding_identity != query.embedding_identity:
                reasons.append("embedding_identity_mismatch")
            if candidate.embedding_observed_at is None:
                reasons.append("missing_embedding_timestamp")
            elif not _aware(candidate.embedding_observed_at, "embedding_observed_at"):
                reasons.append("embedding_timestamp_not_timezone_aware")
            elif candidate.embedding_observed_at > query.as_of:
                reasons.append("embedding_observed_after_assessment_cutoff")
            if (
                candidate.embedding is not None
                and candidate.embedding_identity == query.embedding_identity
            ):
                vector_error = _vector_error(candidate.embedding, query.embedding_identity)
                if vector_error:
                    reasons.append(vector_error)
            if reasons:
                exclusions.append(
                    CandidateExclusion(candidate.post_id, tuple(sorted(set(reasons))))
                )
                continue
            assert candidate.embedding is not None
            rankable.append((_cosine(query.query_embedding, candidate.embedding), candidate))

        rankable.sort(key=lambda pair: (-pair[0], pair[1].post_id))
        selected = tuple(candidate for _, candidate in rankable[: query.limit])
        return VectorCandidateBatch(
            candidates=selected,
            total_candidate_count=len(self.candidates),
            vector_candidate_count=len(rankable),
            truncated=len(rankable) > len(selected),
            prefiltered_exclusions=tuple(
                sorted(exclusions, key=lambda item: (item.post_id, item.reasons))
            ),
        )


@dataclass(frozen=True)
class RelevanceComponents:
    semantic: float
    topic: float | None
    intent: float | None
    format: float | None
    structure: float | None


@dataclass(frozen=True)
class ComparableMatch:
    post_id: str
    relevance: float
    components: RelevanceComponents
    inclusion_reasons: tuple[str, ...]


@dataclass(frozen=True)
class CandidateExclusion:
    post_id: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ComparableSet:
    assessment_id: str
    algorithm_version: str
    config_version: str
    embedding_identity: EmbeddingIdentity
    as_of: datetime
    state: RetrievalState
    matches: tuple[ComparableMatch, ...]
    exclusions: tuple[CandidateExclusion, ...]
    candidate_count: int
    vector_candidate_count: int
    eligible_count: int
    excluded_count: int
    truncated: bool
    coverage_limitations: tuple[str, ...]


def _token_set(profile: PostProfile) -> set[str] | None:
    if profile.topic_signals is None and profile.declared_topic is None:
        return None
    tokens = {value.casefold() for value in (profile.topic_signals or ()) if value.strip()}
    if profile.declared_topic is not None:
        tokens.add(profile.declared_topic.casefold().strip())
    return tokens


def _jaccard(left: set[str] | None, right: set[str] | None) -> float | None:
    if left is None or right is None:
        return None
    union = left | right
    return 1.0 if not union else len(left & right) / len(union)


def _topic_similarity(draft: PostProfile, candidate: PostProfile) -> float | None:
    return _jaccard(_token_set(draft), _token_set(candidate))


def _intent_similarity(draft: PostProfile, candidate: PostProfile) -> float | None:
    components: list[float] = []
    if draft.declared_intent is not None and candidate.declared_intent is not None:
        components.append(float(draft.declared_intent == candidate.declared_intent))
    signal_similarity = _jaccard(
        set(draft.intent_signals) if draft.intent_signals is not None else None,
        set(candidate.intent_signals) if candidate.intent_signals is not None else None,
    )
    if signal_similarity is not None:
        components.append(signal_similarity)
    return math.fsum(components) / len(components) if components else None


def _format_similarity(draft: PostProfile, candidate: PostProfile) -> float | None:
    components: list[float] = []
    if draft.content_format != "unknown" and candidate.content_format != "unknown":
        components.append(float(draft.content_format == candidate.content_format))
    if draft.media_types is not None and candidate.media_types is not None:
        media = _jaccard(set(draft.media_types), set(candidate.media_types))
        if media is not None:
            components.append(media)
    return math.fsum(components) / len(components) if components else None


def _length_similarity(left: int | None, right: int | None) -> float | None:
    if left is None or right is None:
        return None
    high = max(left, right)
    return 1.0 if high == 0 else min(left, right) / high


def _structure_similarity(draft: PostProfile, candidate: PostProfile) -> float | None:
    values = (
        _length_similarity(draft.character_count, candidate.character_count),
        _length_similarity(draft.word_count, candidate.word_count),
        _length_similarity(draft.sentence_count, candidate.sentence_count),
    )
    known = [value for value in values if value is not None]
    return math.fsum(known) / len(known) if known else None


def _components(assessment: DraftAssessment, candidate: ComparableCandidate) -> RelevanceComponents:
    assert candidate.profile is not None and candidate.embedding is not None
    cosine = _cosine(assessment.embedding, candidate.embedding)
    return RelevanceComponents(
        semantic=(cosine + 1.0) / 2.0,
        topic=_topic_similarity(assessment.profile, candidate.profile),
        intent=_intent_similarity(assessment.profile, candidate.profile),
        format=_format_similarity(assessment.profile, candidate.profile),
        structure=_structure_similarity(assessment.profile, candidate.profile),
    )


def _relevance(components: RelevanceComponents, weights: RankingWeights) -> float:
    pairs = (
        (components.semantic, weights.semantic),
        (components.topic, weights.topic),
        (components.intent, weights.intent),
        (components.format, weights.format),
        (components.structure, weights.structure),
    )
    active = [(score, weight) for score, weight in pairs if score is not None and weight > 0]
    total_weight = math.fsum(weight for _, weight in active)
    if total_weight == 0:
        raise ValueError("ranking config has no weight for available relevance components")
    return math.fsum(score * weight for score, weight in active) / total_weight


def _metric_reasons(
    candidate: ComparableCandidate, requirements: tuple[MetricRequirement, ...], as_of: datetime
) -> list[str]:
    reasons: list[str] = []
    for requirement in requirements:
        matching = [item for item in candidate.metric_evidence if item.metric == requirement.metric]
        if not matching:
            reasons.append(f"missing_metric_evidence:{requirement.metric}")
            continue
        defined = [item for item in matching if item.definition == requirement.definition]
        if not defined:
            reasons.append(f"metric_definition_mismatch:{requirement.metric}")
            continue
        windowed = [item for item in defined if item.window == requirement.window]
        if not windowed:
            reasons.append(f"metric_window_mismatch:{requirement.metric}")
            continue
        usable = False
        for item in windowed:
            if not _aware(item.observed_at, "metric observed_at"):
                continue
            if item.observed_at > as_of or item.observed_at < candidate.published_at:
                continue
            if item.is_usable:
                usable = True
        if not usable:
            reasons.append(f"invalid_or_ineligible_metric_evidence:{requirement.metric}")
    return reasons


def _eligibility_reasons(
    assessment: DraftAssessment,
    candidate: ComparableCandidate,
    config: RetrievalConfig,
) -> list[str]:
    reasons: list[str] = []
    if not candidate.post_id.strip():
        reasons.append("missing_post_id")
    if not candidate.available:
        reasons.append("post_unavailable")
    if candidate.creator_key != assessment.creator_key:
        reasons.append("different_creator")
    if not _aware(candidate.published_at, "published_at"):
        reasons.append("publication_timestamp_not_timezone_aware")
    elif candidate.published_at >= assessment.as_of:
        reasons.append("not_published_before_assessment_cutoff")
    if candidate.profile is None:
        reasons.append("missing_post_profile")
    else:
        profile = candidate.profile
        if profile.creator_key not in (None, candidate.creator_key):
            reasons.append("profile_creator_mismatch")
        if profile.version != assessment.profile.version:
            reasons.append("profile_version_mismatch")
        if profile.features_as_of > assessment.as_of:
            reasons.append("profile_features_after_assessment_cutoff")
        if profile.input_observed_at > assessment.as_of:
            reasons.append("profile_input_observed_after_assessment_cutoff")
        if profile.creator_context_observed_at is not None and (
            profile.creator_context_observed_at > assessment.as_of
        ):
            reasons.append("creator_context_observed_after_assessment_cutoff")
        if (
            profile.topology is not None
            and assessment.profile.topology is not None
            and profile.topology != assessment.profile.topology
        ):
            reasons.append("topology_mismatch")
        if (
            profile.thread_role is not None
            and assessment.profile.thread_role is not None
            and profile.thread_role != assessment.profile.thread_role
        ):
            reasons.append("thread_role_mismatch")
        if (
            profile.content_format != "unknown"
            and assessment.profile.content_format != "unknown"
            and profile.content_format != assessment.profile.content_format
        ):
            reasons.append("content_format_mismatch")
    if candidate.embedding is None:
        reasons.append("missing_embedding")
    if candidate.embedding_identity is None:
        reasons.append("missing_embedding_identity")
    elif candidate.embedding_identity != assessment.embedding_identity:
        reasons.append("embedding_identity_mismatch")
    if candidate.embedding_observed_at is None:
        reasons.append("missing_embedding_timestamp")
    elif not _aware(candidate.embedding_observed_at, "embedding_observed_at"):
        reasons.append("embedding_timestamp_not_timezone_aware")
    elif candidate.embedding_observed_at > assessment.as_of:
        reasons.append("embedding_observed_after_assessment_cutoff")
    if (
        candidate.embedding is not None
        and candidate.embedding_identity == assessment.embedding_identity
    ):
        vector_error = _vector_error(candidate.embedding, assessment.embedding_identity)
        if vector_error:
            reasons.append(vector_error)
    if config.metric_requirements and _aware(candidate.published_at, "published_at"):
        reasons.extend(_metric_reasons(candidate, config.metric_requirements, assessment.as_of))
    return reasons


def rank_comparable_candidates(
    assessment: DraftAssessment,
    candidates: tuple[ComparableCandidate, ...],
    config: RetrievalConfig | None = None,
    *,
    prefiltered_exclusions: tuple[CandidateExclusion, ...] = (),
    total_candidate_count: int | None = None,
    vector_candidate_count: int | None = None,
    truncated: bool = False,
) -> ComparableSet:
    """Recheck eligibility, score descriptive features, abstain and return stable evidence."""
    config = config or RetrievalConfig()
    reasons_by_id: dict[str, set[str]] = {}
    counts = Counter(candidate.post_id for candidate in candidates)
    for exclusion in prefiltered_exclusions:
        reasons_by_id.setdefault(exclusion.post_id, set()).update(exclusion.reasons)
    duplicate_ids = {post_id for post_id, count in counts.items() if count > 1}
    for candidate in candidates:
        reasons = reasons_by_id.setdefault(candidate.post_id, set())
        if candidate.post_id in duplicate_ids:
            reasons.add("duplicate_candidate_id")
            continue
        reasons.update(_eligibility_reasons(assessment, candidate, config))

    eligible: list[ComparableMatch] = []
    for candidate in candidates:
        if reasons_by_id.get(candidate.post_id):
            continue
        component_values = _components(assessment, candidate)
        relevance = _relevance(component_values, config.weights)
        if relevance < config.minimum_relevance:
            reasons_by_id.setdefault(candidate.post_id, set()).add("below_minimum_relevance")
            continue
        inclusion_reasons = ["same_creator", "published_before_assessment_cutoff"]
        inclusion_reasons.extend(
            name if value is not None else f"{name}_unavailable"
            for name, value in (
                ("semantic_similarity", component_values.semantic),
                ("topic_similarity", component_values.topic),
                ("intent_similarity", component_values.intent),
                ("format_similarity", component_values.format),
                ("structural_similarity", component_values.structure),
            )
        )
        if config.metric_requirements:
            inclusion_reasons.append("required_metric_evidence_eligible")
        eligible.append(
            ComparableMatch(
                post_id=candidate.post_id,
                relevance=relevance,
                components=component_values,
                inclusion_reasons=tuple(inclusion_reasons),
            )
        )

    eligible.sort(key=lambda item: (-item.relevance, item.post_id))
    matches = tuple(eligible[: config.result_limit])
    exclusions = tuple(
        CandidateExclusion(post_id, tuple(sorted(reasons)))
        for post_id, reasons in sorted(reasons_by_id.items())
        if reasons
    )
    if not matches:
        state: RetrievalState = "no_match"
    elif len(matches) < config.minimum_comparables:
        state = "insufficient_evidence"
    else:
        state = "matched"
    coverage: list[str] = []
    if truncated:
        coverage.append("vector candidate limit truncated the searchable history")
    if state == "insufficient_evidence":
        coverage.append(
            f"only {len(matches)} comparable(s) met the configured relevance threshold; "
            f"{config.minimum_comparables} are required for sufficient evidence"
        )
    elif state == "no_match":
        coverage.append("no candidate met all eligibility and minimum relevance requirements")
    return ComparableSet(
        assessment_id=assessment.assessment_id,
        algorithm_version=config.algorithm_version,
        config_version=config.config_version,
        embedding_identity=assessment.embedding_identity,
        as_of=assessment.as_of,
        state=state,
        matches=matches,
        exclusions=exclusions,
        candidate_count=(
            total_candidate_count
            if total_candidate_count is not None
            else len(candidates) + len(prefiltered_exclusions)
        ),
        vector_candidate_count=(
            vector_candidate_count if vector_candidate_count is not None else len(candidates)
        ),
        eligible_count=len(eligible),
        excluded_count=len(exclusions),
        truncated=truncated,
        coverage_limitations=tuple(coverage),
    )


def retrieve_comparables(
    assessment: DraftAssessment,
    source: VectorCandidateSource,
    config: RetrievalConfig | None = None,
) -> ComparableSet:
    """Run bounded vector candidate retrieval followed by deterministic eligibility/reranking."""
    config = config or RetrievalConfig()
    query = VectorCandidateQuery(
        creator_key=assessment.creator_key,
        as_of=assessment.as_of,
        embedding_identity=assessment.embedding_identity,
        query_embedding=assessment.embedding,
        limit=config.candidate_limit,
    )
    batch = source.search(query)
    return rank_comparable_candidates(
        assessment,
        batch.candidates,
        config,
        prefiltered_exclusions=batch.prefiltered_exclusions,
        total_candidate_count=batch.total_candidate_count,
        vector_candidate_count=batch.vector_candidate_count,
        truncated=batch.truncated,
    )
