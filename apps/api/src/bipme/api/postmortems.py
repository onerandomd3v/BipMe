"""Read-only creator postmortems over persisted COD-354/361/363 evidence."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import Field, ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from bipme.api.creator_reports import _latest_permission, _x_history_policy_verified_at
from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
)
from bipme.api.errors import ApiError
from bipme.api.evidence import KNOWN_X_SOURCES
from bipme.api.schemas import AcceptedHypothesis as AcceptedHypothesisSchema
from bipme.api.schemas import DraftAnalysisResponse, ErrorResponse, StrictModel
from bipme.intelligence.baselines import BaselineStatistics, OutcomeObservation
from bipme.intelligence.outlooks import (
    ComparableEvidence,
    DecisionObservation,
    DistributionOutlook,
    MetricEvidence,
    OutlookRange,
    TestableSuggestion,
)
from bipme.intelligence.postmortems import (
    AcceptedHypothesis,
    HypothesisEvaluation,
    MetricComparison,
    OriginalAssessment,
    PostmortemRequest,
    PostmortemResult,
    PublishedPost,
    build_postmortem,
)
from bipme.intelligence.retrieval import CandidateExclusion, RelevanceComponents
from bipme.persistence.contracts import (
    latest_observation_records,
    outcome_observations_from_records,
)
from bipme.persistence.models import CanonicalPost, DraftAssessment, OutcomeObservationRecord
from bipme.posts.publications import postmortem_publication

router = APIRouter(prefix="/api/v1/creators/me", tags=["postmortems"])


class PostmortemObservationResponse(StrictModel):
    post_id: UUID
    metric: str
    metric_definition: str
    unit: str
    state: Literal["observed", "missing"]
    value: float | None
    published_at: datetime
    observed_at: datetime
    window_kind: Literal["mature_cumulative", "age_aligned"]
    window_key: str


class PostmortemHypothesisResponse(StrictModel):
    status: Literal["supported", "contradicted", "inconclusive"]
    hypothesis: AcceptedHypothesisSchema
    metric: str
    metric_definition: str
    unit: str
    window_kind: Literal["mature_cumulative", "age_aligned"]
    window_key: str
    observed_value: float | None
    historical_median: float | None
    matched_sample_count: int
    effective_sample_size: float
    comparison_post_ids: tuple[UUID, ...]
    limitations: tuple[str, ...]


class PostmortemRangeResponse(StrictModel):
    kind: str
    lower_p25: float
    median_p50: float
    upper_p75: float
    comparable_post_ids: tuple[UUID, ...]
    effective_sample_size: float


class PostmortemMetricResponse(StrictModel):
    metric: str
    metric_definition: str
    unit: str
    window_kind: Literal["mature_cumulative", "age_aligned"]
    window_key: str
    status: Literal["scored", "unavailable", "version_unverified"]
    observed_value: float | None
    observed_at: datetime | None
    observation_age_seconds: float | None
    reference_range: PostmortemRangeResponse | None
    deviation_from_median: float | None
    within_reference_range: bool | None
    relative_percentile: float | None
    matched_sample_count: int
    effective_sample_size: float
    comparison_post_ids: tuple[UUID, ...]
    limitations: tuple[str, ...]
    historical_median: float | None
    comparison_observations: tuple[PostmortemObservationResponse, ...]


class PostmortemEvaluationResponse(StrictModel):
    version: str
    version_state: Literal["verified", "unverified"]
    assessment_id: UUID
    published_post_id: UUID
    original_outlook: DraftAnalysisResponse
    observed_outcomes: tuple[PostmortemObservationResponse, ...]
    metric_comparisons: tuple[PostmortemMetricResponse, ...]
    hypothesis_evaluation: PostmortemHypothesisResponse | None
    limitations: tuple[str, ...]


class PostmortemPublicationResponse(StrictModel):
    canonical_post_id: UUID
    external_post_id: str
    published_at: datetime
    availability: Literal["available", "unavailable", "deleted"]
    version_match_state: Literal["match", "mismatch", "unknown"]


class PostmortemReadResponse(StrictModel):
    state: Literal[
        "publication_pending",
        "publication_unavailable",
        "evidence_unavailable",
        "monitoring_pending",
        "insufficient_evidence",
        "version_unverified",
        "evaluated",
    ]
    assessment_id: UUID
    assessed_at: datetime
    published_post: PostmortemPublicationResponse | None
    original_outlook: DraftAnalysisResponse
    postmortem: PostmortemEvaluationResponse | None
    limitations: tuple[str, ...] = Field(default=())


def _outlook(snapshot: DraftAnalysisResponse) -> DistributionOutlook:
    raw = snapshot.model_dump(mode="python")
    versions = raw["versions"]
    assert isinstance(versions, dict)
    exclusions = tuple(
        CandidateExclusion(str(item.post_id), tuple(item.reasons))
        for item in snapshot.retrieval_exclusions
    )
    evidence = tuple(
        ComparableEvidence(
            post_id=str(item.post_id),
            relevance=item.relevance,
            components=RelevanceComponents(**item.components.model_dump()),
            retrieval_position=item.retrieval_position,
            inclusion_reasons=item.inclusion_reasons,
        )
        for item in snapshot.comparable_evidence
    )
    metrics = tuple(
        MetricEvidence(
            metric=item.metric,
            metric_definition=item.metric_definition,
            window=item.window,
            evidence_strength=item.evidence_strength,
            coverage=item.coverage,
            eligible_post_count=item.eligible_post_count,
            effective_sample_size=item.effective_sample_size,
            supporting_post_ids=tuple(str(post_id) for post_id in item.supporting_post_ids),
            statistics=(
                BaselineStatistics(**item.statistics.model_dump()) if item.statistics else None
            ),
            exclusion_counts=item.exclusion_counts,
            limitations=item.limitations,
            outlook=(
                OutlookRange(
                    kind=item.outlook.kind,
                    lower_p25=item.outlook.lower_p25,
                    median_p50=item.outlook.median_p50,
                    upper_p75=item.outlook.upper_p75,
                    comparable_post_ids=tuple(
                        str(post_id) for post_id in item.outlook.comparable_post_ids
                    ),
                    effective_sample_size=item.outlook.effective_sample_size,
                )
                if item.outlook
                else None
            ),
        )
        for item in snapshot.metrics
    )
    observations = tuple(
        DecisionObservation(
            kind=item.kind,
            explanation=item.explanation,
            supporting_post_ids=tuple(str(post_id) for post_id in item.supporting_post_ids),
            metric=item.metric,
            metric_definition=item.metric_definition,
            window=item.window,
            evidence_strength=item.evidence_strength,
            evidence_statistics=(
                BaselineStatistics(**item.evidence_statistics.model_dump())
                if item.evidence_statistics
                else None
            ),
            limitations=item.limitations,
        )
        for item in snapshot.observations
    )
    suggestion = snapshot.suggested_hypothesis
    return DistributionOutlook(
        assessment_id=str(snapshot.assessment_id),
        content_fingerprint=snapshot.input_fingerprint,
        decision_algorithm_version=str(versions["decision"]),
        decision_config_version=str(versions["decision_config"]),
        retrieval_version=str(versions["retrieval"]),
        ranking_config_version=str(versions["ranking_config"]),
        retrieval_state=snapshot.retrieval_state,
        retrieval_candidate_count=snapshot.retrieval_candidate_count,
        retrieval_vector_candidate_count=snapshot.retrieval_vector_candidate_count,
        retrieval_eligible_count=snapshot.retrieval_eligible_count,
        retrieval_excluded_count=snapshot.retrieval_excluded_count,
        retrieval_truncated=snapshot.retrieval_truncated,
        retrieval_exclusions=exclusions,
        retrieval_coverage_limitations=snapshot.retrieval_coverage_limitations,
        baseline_version=str(versions["baseline"]),
        embedding_identity=str(versions["embedding_identity"]),
        assessment_cutoff=snapshot.assessed_at,
        decision_state=snapshot.decision_state,
        comparable_evidence=evidence,
        metrics=metrics,
        observations=observations,
        suggestion=(
            TestableSuggestion(
                kind=suggestion.kind,
                label=suggestion.label,
                variable=suggestion.variable,
                value=suggestion.value,
                rationale=suggestion.rationale,
                supporting_post_ids=tuple(str(i) for i in suggestion.supporting_post_ids),
                comparison_post_ids=tuple(str(i) for i in suggestion.comparison_post_ids),
                metric=suggestion.metric,
                metric_definition=suggestion.metric_definition,
                window=suggestion.window,
                is_optional=suggestion.is_optional,
            )
            if suggestion
            else None
        ),
        assumptions=snapshot.assumptions,
        limitations=snapshot.limitations,
        exclusions=snapshot.exclusions,
    )


def _identity(value: str) -> tuple[str, str]:
    metric_definition, marker, unit = value.partition("|unit=")
    if not marker or not unit:
        raise ValueError("stored metric definition is missing its unit")
    return metric_definition, unit


def _window_parts(value: str) -> tuple[Literal["mature_cumulative", "age_aligned"], str]:
    kind, marker, key = value.partition(":")
    if not marker or kind not in {"mature_cumulative", "age_aligned"} or not key:
        raise ValueError("stored outcome window is invalid")
    return kind, key  # type: ignore[return-value]


def _observation(item: OutcomeObservation) -> PostmortemObservationResponse:
    definition, unit = _identity(item.metric_definition)
    kind, key = _window_parts(item.window)
    return PostmortemObservationResponse(
        post_id=UUID(item.post_id),
        metric=item.metric,
        metric_definition=definition,
        unit=unit,
        state="observed" if item.value is not None else "missing",
        value=item.value,
        published_at=item.published_at,
        observed_at=item.observed_at,
        window_kind=kind,
        window_key=key,
    )


def _metric_comparison(item: MetricComparison) -> PostmortemMetricResponse:
    definition, unit = _identity(item.metric_definition)
    kind, key = _window_parts(item.window)
    return PostmortemMetricResponse(
        metric=item.metric,
        metric_definition=definition,
        unit=unit,
        window_kind=kind,
        window_key=key,
        status=item.status,
        observed_value=item.observed_value,
        observed_at=item.observed_at,
        observation_age_seconds=item.observation_age_seconds,
        reference_range=(
            PostmortemRangeResponse(
                kind=item.reference_range.kind,
                lower_p25=item.reference_range.lower_p25,
                median_p50=item.reference_range.median_p50,
                upper_p75=item.reference_range.upper_p75,
                comparable_post_ids=tuple(
                    UUID(value) for value in item.reference_range.comparable_post_ids
                ),
                effective_sample_size=item.reference_range.effective_sample_size,
            )
            if item.reference_range
            else None
        ),
        deviation_from_median=item.deviation_from_median,
        within_reference_range=item.within_reference_range,
        relative_percentile=item.relative_percentile,
        matched_sample_count=item.matched_sample_count,
        effective_sample_size=item.effective_sample_size,
        comparison_post_ids=tuple(UUID(value) for value in item.comparison_post_ids),
        limitations=item.limitations,
        historical_median=item.historical_median,
        comparison_observations=tuple(
            _observation(value) for value in item.comparison_observations
        ),
    )


def _hypothesis(item: HypothesisEvaluation | None) -> PostmortemHypothesisResponse | None:
    if item is None:
        return None
    definition, unit = _identity(item.metric_definition)
    kind, key = _window_parts(item.window)
    return PostmortemHypothesisResponse(
        status=item.status,
        hypothesis=AcceptedHypothesisSchema.model_validate(asdict(item.hypothesis)),
        metric=item.metric,
        metric_definition=definition,
        unit=unit,
        window_kind=kind,
        window_key=key,
        observed_value=item.observed_value,
        historical_median=item.historical_median,
        matched_sample_count=item.matched_sample_count,
        effective_sample_size=item.effective_sample_size,
        comparison_post_ids=tuple(UUID(value) for value in item.comparison_post_ids),
        limitations=item.limitations,
    )


def _evaluation(
    result: PostmortemResult, outlook: DraftAnalysisResponse
) -> PostmortemEvaluationResponse:
    return PostmortemEvaluationResponse(
        version=result.version,
        version_state=result.version_state,
        assessment_id=UUID(result.assessment_id),
        published_post_id=UUID(result.published_post_id),
        original_outlook=outlook,
        observed_outcomes=tuple(_observation(item) for item in result.observed_outcomes),
        metric_comparisons=tuple(_metric_comparison(item) for item in result.metric_comparisons),
        hypothesis_evaluation=_hypothesis(result.hypothesis_evaluation),
        limitations=result.limitations,
    )


def _publication_response(post: CanonicalPost) -> PostmortemPublicationResponse:
    return PostmortemPublicationResponse(
        canonical_post_id=post.id,
        external_post_id=post.external_post_id,
        published_at=post.published_at,
        availability=cast(Literal["available", "unavailable", "deleted"], post.availability),
        version_match_state=cast(
            Literal["match", "mismatch", "unknown"], post.version_match_state or "unknown"
        ),
    )


def _state(
    result: PostmortemResult, has_published_observation: bool
) -> Literal["monitoring_pending", "insufficient_evidence", "version_unverified", "evaluated"]:
    if result.version_state == "unverified":
        return "version_unverified"
    if not result.original_outlook.metrics:
        return "insufficient_evidence"
    if not has_published_observation:
        return "monitoring_pending"
    if any(item.status == "unavailable" for item in result.metric_comparisons):
        return "insufficient_evidence"
    return "evaluated"


@router.get(
    "/draft-assessments/{assessment_id}/postmortem",
    response_model=PostmortemReadResponse,
    summary="Read a creator-authenticated evidence-aware publication postmortem",
    description=(
        "Evaluates only the immutable saved Outlook, the creator's linked publication, and "
        "persisted eligible metric observations. This GET makes no provider calls, schedules "
        "no work and performs no writes. A missing publication is reported as publication_pending; "
        "missing observations and historical evidence are explicit states in the response."
    ),
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def read_postmortem(
    assessment_id: UUID,
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    db: Annotated[Session, Depends(get_db_session)],
    now: Annotated[datetime, Depends(get_current_time)],
) -> PostmortemReadResponse:
    """Return only data owned by the authenticated creator; never execute live work."""
    try:
        assessment = db.scalar(
            select(DraftAssessment).where(
                DraftAssessment.id == assessment_id,
                DraftAssessment.creator_id == creator.creator_id,
            )
        )
        if assessment is None:
            raise ApiError(404, "assessment_not_found", "The requested assessment was not found.")
        try:
            outlook = DraftAnalysisResponse.model_validate(
                {
                    key: value
                    for key, value in assessment.decision_snapshot.items()
                    if key != "_cod361_linking"
                }
            )
            original_outlook = _outlook(outlook)
            hypothesis = (
                AcceptedHypothesis(**assessment.accepted_hypothesis)
                if assessment.accepted_hypothesis is not None
                else None
            )
            original = OriginalAssessment(
                assessment_id=str(assessment.id),
                assessment_record_id=str(assessment.id),
                creator_key=str(assessment.creator_id),
                assessed_at=assessment.assessed_at,
                content_fingerprint=assessment.content_fingerprint,
                outlook=original_outlook,
                accepted_hypothesis=hypothesis,
            )
        except (ValidationError, TypeError, ValueError, KeyError) as exc:
            raise ApiError(
                503, "assessment_snapshot_invalid", "The saved assessment is unavailable."
            ) from exc

        post = db.scalar(
            select(CanonicalPost).where(
                CanonicalPost.source_assessment_id == assessment.id,
                CanonicalPost.creator_id == creator.creator_id,
                CanonicalPost.platform == "x",
            )
        )
        if post is None:
            return PostmortemReadResponse(
                state="publication_pending",
                assessment_id=assessment.id,
                assessed_at=assessment.assessed_at,
                published_post=None,
                original_outlook=outlook,
                postmortem=None,
                limitations=("No linked publication is available yet.",),
            )
        if post.availability != "available":
            return PostmortemReadResponse(
                state="publication_unavailable",
                assessment_id=assessment.id,
                assessed_at=assessment.assessed_at,
                published_post=_publication_response(post),
                original_outlook=outlook,
                postmortem=None,
                limitations=("The linked publication is unavailable.",),
            )
        permission = _latest_permission(db, creator.creator_id)
        processing_allowed = bool(
            permission
            and permission.allowed
            and permission.recorded_at <= now
            and _x_history_policy_verified_at(now) is not None
            and post.source in KNOWN_X_SOURCES
        )
        if not processing_allowed:
            return PostmortemReadResponse(
                state="evidence_unavailable",
                assessment_id=assessment.id,
                assessed_at=assessment.assessed_at,
                published_post=_publication_response(post),
                original_outlook=outlook,
                postmortem=None,
                limitations=(
                    "Personal-history processing is unavailable because current permission or source policy does not allow reading metric evidence.",
                ),
            )
        published: PublishedPost = postmortem_publication(post)

        history_ids = {item.post_id for item in outlook.comparable_evidence}
        rows = list(
            db.scalars(
                select(OutcomeObservationRecord)
                .join(CanonicalPost, CanonicalPost.id == OutcomeObservationRecord.post_id)
                .where(
                    OutcomeObservationRecord.creator_id == creator.creator_id,
                    CanonicalPost.creator_id == creator.creator_id,
                    CanonicalPost.platform == "x",
                    CanonicalPost.availability == "available",
                    CanonicalPost.source.in_(KNOWN_X_SOURCES),
                    or_(
                        and_(
                            OutcomeObservationRecord.post_id == post.id,
                            OutcomeObservationRecord.observed_at <= now,
                        ),
                        and_(
                            OutcomeObservationRecord.post_id.in_(history_ids),
                            OutcomeObservationRecord.observed_at <= assessment.assessed_at,
                        ),
                    ),
                )
                .order_by(
                    OutcomeObservationRecord.observed_at,
                    OutcomeObservationRecord.post_id,
                    OutcomeObservationRecord.metric_name,
                    OutcomeObservationRecord.metric_definition,
                    OutcomeObservationRecord.metric_unit,
                    OutcomeObservationRecord.window_kind,
                    OutcomeObservationRecord.window_key,
                )
            ).all()
        )
        weights = {str(item.post_id): item.relevance for item in outlook.comparable_evidence}
        weights[str(post.id)] = 1.0
        historical_rows = latest_observation_records(
            [row for row in rows if row.post_id in history_ids], assessment.assessed_at
        )
        published_rows = [row for row in rows if row.post_id == post.id]
        history = outcome_observations_from_records(historical_rows, weights_by_post_id=weights)
        published_outcomes = outcome_observations_from_records(
            published_rows, weights_by_post_id=weights
        )
        request = PostmortemRequest(
            assessment=original,
            published_post=published,
            historical_outcomes=history,
            published_outcomes=published_outcomes,
            evaluated_at=now,
        )
        result = build_postmortem(request)
        wanted_metrics = {
            (item.metric, item.metric_definition, item.window) for item in outlook.metrics
        }
        has_observation = any(
            (item.metric, item.metric_definition, item.window) in wanted_metrics
            for item in published_outcomes
        )
        state = _state(result, has_observation)
        try:
            return PostmortemReadResponse(
                state=state,
                assessment_id=assessment.id,
                assessed_at=assessment.assessed_at,
                published_post=_publication_response(post),
                original_outlook=outlook,
                postmortem=_evaluation(result, outlook),
                limitations=result.limitations,
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ApiError(
                503, "assessment_snapshot_invalid", "The saved assessment is unavailable."
            ) from exc
    except ApiError:
        raise
    except SQLAlchemyError as exc:
        raise ApiError(
            503, "postmortem_store_unavailable", "Postmortem evidence is temporarily unavailable."
        ) from exc
