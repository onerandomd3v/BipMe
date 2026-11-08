"""Versioned, provider-neutral HTTP schemas for creator analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MediaKind = Literal["image", "video", "gif", "audio", "other"]
Topology = Literal["original", "reply", "quote"]
ThreadRole = Literal["single", "root", "continuation"]
DeclaredIntent = Literal["inform", "ask", "promote", "entertain", "other"]
EvidenceStrength = Literal["High", "Moderate", "Low", "Insufficient"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricIdentity(StrictModel):
    metric: str = Field(min_length=1, max_length=100)
    definition: str = Field(min_length=1, max_length=255)
    unit: str = Field(min_length=1, max_length=64)
    window_kind: Literal["mature_cumulative", "age_aligned"]
    window_key: str = Field(min_length=1, max_length=100)


class MetricPreference(MetricIdentity):
    """Exact outcome series requested for a draft analysis."""


class AcceptedHypothesis(StrictModel):
    """One optional creator-selected question saved at assessment creation."""

    question: str = Field(min_length=1, max_length=500)
    metric: str = Field(min_length=1, max_length=100)
    metric_definition: str = Field(min_length=1, max_length=255)
    unit: str = Field(min_length=1, max_length=64)
    window_kind: Literal["mature_cumulative", "age_aligned"]
    window_key: str = Field(min_length=1, max_length=100)
    expected_direction: Literal["higher", "lower", "no_direction"] = "no_direction"


class DraftAnalysisRequest(StrictModel):
    """Draft and descriptive metadata; no client-supplied creator or timestamp."""

    text: str = Field(min_length=1, max_length=10_000)
    topology: Topology = "original"
    thread_role: ThreadRole | None = None
    media_types: tuple[MediaKind, ...] | None = None
    declared_topic: str | None = Field(default=None, max_length=120)
    declared_intent: DeclaredIntent | None = None
    metric_preferences: tuple[MetricPreference, ...] = Field(default=(), max_length=8)
    accepted_hypothesis: AcceptedHypothesis | None = None

    @field_validator("text")
    @classmethod
    def non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("draft text cannot be blank")
        return value

    @field_validator("declared_topic")
    @classmethod
    def non_blank_topic(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("declared_topic cannot be blank")
        return value.strip() if value is not None else None

    @field_validator("metric_preferences")
    @classmethod
    def unique_metric_preferences(
        cls, value: tuple[MetricPreference, ...]
    ) -> tuple[MetricPreference, ...]:
        identities = [item.model_dump(mode="json") for item in value]
        if len(identities) != len({tuple(sorted(item.items())) for item in identities}):
            raise ValueError("metric preferences must be unique")
        return value


class ErrorDetail(StrictModel):
    code: str
    message: str
    fields: list[dict[str, str]] | None = None


class ErrorResponse(StrictModel):
    error: ErrorDetail


class BaselineStatisticsResponse(StrictModel):
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    minimum: float
    maximum: float
    iqr: float
    dispersion_ratio: float | None
    consistency_ratio: float
    outlier_count: int
    upper_outlier_count: int
    outlier_adjusted_p50: float
    median_shift_in_iqr: float
    maximum_weight_share: float
    target_percentile_rank: float | None


class CreatorBaselineResponse(StrictModel):
    calculation_version: str
    metric: MetricIdentity
    as_of: datetime
    eligible_post_count: int
    effective_sample_size: float
    supporting_post_ids: tuple[UUID, ...]
    evidence_strength: EvidenceStrength
    repeatability_ratio: float | None
    outlier_count: int | None
    upper_outlier_count: int | None
    statistics: BaselineStatisticsResponse | None
    exclusions: dict[str, int]
    limitations: tuple[str, ...]


class AlgorithmVersions(StrictModel):
    decision: str
    decision_config: str
    retrieval: str
    ranking_config: str
    baseline: str
    profile: str
    embedding_identity: str


class RelevanceComponentsResponse(StrictModel):
    semantic: float
    topic: float | None
    intent: float | None
    format: float | None
    structure: float | None


class ComparableEvidenceResponse(StrictModel):
    post_id: UUID
    relevance: float
    components: RelevanceComponentsResponse
    retrieval_position: int
    inclusion_reasons: tuple[str, ...]


class CandidateExclusionResponse(StrictModel):
    post_id: UUID
    reasons: tuple[str, ...]


class HistoricalRangeResponse(StrictModel):
    kind: str
    lower_p25: float
    median_p50: float
    upper_p75: float
    comparable_post_ids: tuple[UUID, ...]
    effective_sample_size: float


class MetricEvidenceResponse(StrictModel):
    metric: str
    metric_definition: str
    window: str
    evidence_strength: EvidenceStrength
    coverage: float
    eligible_post_count: int
    effective_sample_size: float
    supporting_post_ids: tuple[UUID, ...]
    statistics: BaselineStatisticsResponse | None
    exclusion_counts: tuple[tuple[str, int], ...]
    limitations: tuple[str, ...]
    outlook: HistoricalRangeResponse | None


class DecisionObservationResponse(StrictModel):
    kind: Literal["repeatability", "outlier", "coverage_limitation"]
    explanation: str
    supporting_post_ids: tuple[UUID, ...]
    metric: str | None
    metric_definition: str | None
    window: str | None
    evidence_strength: EvidenceStrength
    evidence_statistics: BaselineStatisticsResponse | None
    limitations: tuple[str, ...]


class SuggestedHypothesisResponse(StrictModel):
    kind: Literal["experiment_hypothesis"]
    label: str
    variable: str
    value: str
    rationale: str
    supporting_post_ids: tuple[UUID, ...]
    comparison_post_ids: tuple[UUID, ...]
    metric: str
    metric_definition: str
    window: str
    is_optional: bool


class DraftAnalysisResponse(StrictModel):
    assessment_id: UUID
    input_fingerprint: str
    assessed_at: datetime
    versions: AlgorithmVersions
    decision_state: Literal["supported", "insufficient_evidence"]
    retrieval_state: Literal["matched", "insufficient_evidence", "no_match"]
    retrieval_candidate_count: int
    retrieval_vector_candidate_count: int
    retrieval_eligible_count: int
    retrieval_excluded_count: int
    retrieval_truncated: bool
    retrieval_exclusions: tuple[CandidateExclusionResponse, ...]
    retrieval_coverage_limitations: tuple[str, ...]
    comparable_evidence: tuple[ComparableEvidenceResponse, ...]
    metrics: tuple[MetricEvidenceResponse, ...]
    observations: tuple[DecisionObservationResponse, ...] = Field(max_length=2)
    suggested_hypothesis: SuggestedHypothesisResponse | None
    accepted_hypothesis: AcceptedHypothesis | None
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    exclusions: tuple[tuple[str, int], ...]
