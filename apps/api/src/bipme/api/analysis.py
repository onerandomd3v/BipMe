"""Authorized creator-baseline and draft-assessment HTTP routes."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from bipme.api.dependencies import (
    AuthenticatedCreator,
    get_authenticated_creator,
    get_current_time,
    get_db_session,
    get_embedder,
)
from bipme.api.errors import ApiError
from bipme.api.schemas import (
    AcceptedHypothesis,
    AlgorithmVersions,
    BaselineStatisticsResponse,
    CreatorBaselineResponse,
    DraftAnalysisRequest,
    DraftAnalysisResponse,
    ErrorResponse,
    MetricIdentity,
)
from bipme.intelligence.baselines import (
    BaselineRequest,
    CreatorBaseline,
    build_creator_baseline,
)
from bipme.intelligence.embeddings import TextEmbedder
from bipme.intelligence.outlooks import (
    OUTLOOK_ALGORITHM_VERSION,
    OutlookRequest,
    build_distribution_outlook,
)
from bipme.intelligence.post_profiles import PROFILE_VERSION, PostProfileInput, extract_post_profile
from bipme.intelligence.retrieval import (
    DraftAssessment as RetrievalDraftAssessment,
)
from bipme.intelligence.retrieval import (
    RetrievalConfig,
    VectorCandidateQuery,
    rank_comparable_candidates,
)
from bipme.persistence.contracts import outcome_observations_from_records
from bipme.persistence.models import DraftAssessment as PersistedDraftAssessment
from bipme.persistence.models import OutcomeObservationRecord
from bipme.persistence.vector_candidates import PostgresVectorCandidateSource

router = APIRouter(prefix="/api/v1/creators/me", tags=["creator analysis"])


def _metric_definition(metric: MetricIdentity) -> str:
    return f"{metric.definition}|unit={metric.unit}"


def _metric_window(metric: MetricIdentity) -> str:
    return f"{metric.window_kind}:{metric.window_key}"


def _validate_as_of(as_of: datetime, now: datetime) -> None:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ApiError(422, "invalid_assessment_timestamp", "as_of must include a timezone.")
    if as_of > now:
        raise ApiError(422, "future_assessment_timestamp", "as_of cannot be in the future.")


def _validate_series_support(
    session: Session,
    creator_id: UUID,
    metric: MetricIdentity,
    as_of: datetime,
    known_records: list[OutcomeObservationRecord] | None = None,
) -> list[OutcomeObservationRecord]:
    """Reject incompatible series known by the cutoff while preserving no-history results."""
    records = known_records
    if records is None:
        records = list(
            session.scalars(
                select(OutcomeObservationRecord).where(
                    OutcomeObservationRecord.creator_id == creator_id,
                    OutcomeObservationRecord.metric_name == metric.metric,
                )
            ).all()
        )
    visible = [record for record in records if record.observed_at <= as_of]
    exact_visible = [record for record in visible if _same_metric_series(record, metric)]
    exact_all = [record for record in records if _same_metric_series(record, metric)]
    if exact_visible:
        # Retain future rows from this series so COD-353 can report their exclusion.
        return exact_all
    if not visible:
        return exact_all
    if any(
        record.metric_definition == metric.definition and record.metric_unit == metric.unit
        for record in visible
    ):
        raise ApiError(
            422,
            "unsupported_observation_window",
            "The requested observation window does not match this creator's recorded metric series.",
        )
    if any(record.metric_definition == metric.definition for record in visible):
        raise ApiError(
            422,
            "unsupported_metric_unit",
            "The requested metric unit does not match this creator's recorded metric definition.",
        )
    raise ApiError(
        422,
        "unsupported_metric_definition",
        "The requested metric definition is not recorded for this creator.",
    )


def _same_metric_series(record: OutcomeObservationRecord, metric: MetricIdentity) -> bool:
    return (
        record.metric_definition == metric.definition
        and record.metric_unit == metric.unit
        and record.window_kind == metric.window_kind
        and record.window_key == metric.window_key
    )


def _latest_observation_records(
    records: list[OutcomeObservationRecord], as_of: datetime
) -> list[OutcomeObservationRecord]:
    """Select one latest available snapshot per exact post and metric series."""
    latest: dict[tuple[str, str, str, str, str, str], OutcomeObservationRecord] = {}
    future: list[OutcomeObservationRecord] = []
    for record in records:
        if record.observed_at > as_of:
            future.append(record)
            continue
        key = (
            str(record.post_id),
            record.metric_name,
            record.metric_definition,
            record.metric_unit,
            record.window_kind,
            record.window_key,
        )
        prior = latest.get(key)
        if prior is None or (record.observed_at, str(record.id)) > (
            prior.observed_at,
            str(prior.id),
        ):
            latest[key] = record
    return [latest[key] for key in sorted(latest)] + sorted(
        future,
        key=lambda record: (
            str(record.post_id),
            record.metric_name,
            record.metric_definition,
            record.metric_unit,
            record.window_kind,
            record.window_key,
            record.observed_at,
            str(record.id),
        ),
    )


def _baseline_response(
    baseline: CreatorBaseline,
    metric: MetricIdentity,
    extra_exclusions: Counter[str] | None = None,
) -> CreatorBaselineResponse:
    stats = baseline.statistics
    exclusions = Counter(dict(baseline.exclusion_counts))
    if extra_exclusions:
        exclusions.update(extra_exclusions)
    return CreatorBaselineResponse(
        calculation_version=baseline.version,
        metric=metric,
        as_of=baseline.as_of,
        eligible_post_count=baseline.eligible_post_count,
        effective_sample_size=baseline.effective_sample_size,
        supporting_post_ids=tuple(UUID(value) for value in baseline.supporting_post_ids),
        evidence_strength=baseline.evidence_strength,
        repeatability_ratio=stats.consistency_ratio if stats else None,
        outlier_count=stats.outlier_count if stats else None,
        upper_outlier_count=stats.upper_outlier_count if stats else None,
        statistics=BaselineStatisticsResponse(**asdict(stats)) if stats else None,
        exclusions=dict(sorted(exclusions.items())),
        limitations=baseline.reasons,
    )


@router.get(
    "/baseline",
    summary="Get the authenticated creator's historical baseline",
    description=(
        "Returns an exact metric-definition-unit-window baseline at an authorized cutoff. "
        "Requires COD-346's active server-verified creator session."
    ),
    response_model=CreatorBaselineResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def get_creator_baseline(
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    session: Annotated[Session, Depends(get_db_session)],
    metric: Annotated[str, Query(min_length=1, max_length=100)],
    definition: Annotated[str, Query(min_length=1, max_length=255)],
    unit: Annotated[str, Query(min_length=1, max_length=64)],
    window_kind: Annotated[Literal["mature_cumulative", "age_aligned"], Query()],
    window_key: Annotated[str, Query(min_length=1, max_length=100)],
    now: Annotated[datetime, Depends(get_current_time)],
    as_of: datetime | None = None,
) -> CreatorBaselineResponse:
    """Return an exact metric/window baseline with no cross-creator records."""
    cutoff = as_of or now
    _validate_as_of(cutoff, now)
    identity = MetricIdentity(
        metric=metric,
        definition=definition,
        unit=unit,
        window_kind=window_kind,
        window_key=window_key,
    )
    try:
        records = _latest_observation_records(
            _validate_series_support(session, creator.creator_id, identity, cutoff), cutoff
        )
        observations = outcome_observations_from_records(
            records,
            weights_by_post_id={str(record.post_id): 1.0 for record in records},
        )
        baseline = build_creator_baseline(
            observations,
            BaselineRequest(
                creator_key=str(creator.creator_id),
                metric=metric,
                metric_definition=_metric_definition(identity),
                window=_metric_window(identity),
                as_of=cutoff,
            ),
        )
        invalid_count = sum(record.state == "invalid" for record in records)
        extra = Counter({"invalid_observation_state": invalid_count}) if invalid_count else None
        return _baseline_response(baseline, identity, extra)
    except ApiError:
        raise
    except SQLAlchemyError as exc:
        raise ApiError(
            503, "analysis_store_unavailable", "Historical evidence is temporarily unavailable."
        ) from exc


def _canonical_input(request: DraftAnalysisRequest) -> bytes:
    """Canonicalize assessed text/metadata while preserving meaningful whitespace.

    Text uses Unicode NFC and LF line endings; leading/trailing whitespace is retained.
    The stable sorted JSON also binds topology, media, declared labels and exact metric
    preferences so an idempotency key cannot silently return a different analysis.
    The optional accepted hypothesis is excluded because it does not alter analysis.
    """
    content = request.model_dump(mode="json", exclude={"text", "accepted_hypothesis"})
    content["text"] = _canonical_text(request.text)
    return json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _content_fingerprint(request: DraftAnalysisRequest) -> str:
    digest = hashlib.sha256(b"bipme-draft-assessment-v1\0" + _canonical_input(request)).hexdigest()
    return f"sha256:{digest}"


def _canonical_text(value: str) -> str:
    """Normalize equivalent Unicode and newline encodings without trimming content."""
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def _response_from_snapshot(snapshot: dict[str, object]) -> DraftAnalysisResponse:
    try:
        return DraftAnalysisResponse.model_validate(snapshot)
    except Exception as exc:
        raise ApiError(
            503, "assessment_snapshot_invalid", "The saved assessment is unavailable."
        ) from exc


def _versions(outlook: object) -> AlgorithmVersions:
    payload = cast(dict[str, object], outlook)
    return AlgorithmVersions(
        decision=str(payload["decision_algorithm_version"]),
        decision_config=str(payload["decision_config_version"]),
        retrieval=str(payload["retrieval_version"]),
        ranking_config=str(payload["ranking_config_version"]),
        baseline=str(payload["baseline_version"]),
        profile=PROFILE_VERSION,
        embedding_identity=str(payload["embedding_identity"]),
    )


def _build_api_response(
    outlook: object,
    *,
    assessed_at: datetime,
    accepted_hypothesis: AcceptedHypothesis | None,
) -> DraftAnalysisResponse:
    from bipme.intelligence.outlooks import DistributionOutlook

    if not isinstance(outlook, DistributionOutlook):
        raise TypeError("outlook must be a DistributionOutlook")
    raw = json.loads(outlook.to_json())
    api_payload: dict[str, object] = {
        "assessment_id": outlook.assessment_id,
        "input_fingerprint": outlook.content_fingerprint,
        "assessed_at": assessed_at.isoformat(),
        "versions": _versions(raw).model_dump(mode="json"),
        "decision_state": outlook.decision_state,
        "retrieval_state": outlook.retrieval_state,
        "retrieval_candidate_count": outlook.retrieval_candidate_count,
        "retrieval_vector_candidate_count": outlook.retrieval_vector_candidate_count,
        "retrieval_eligible_count": outlook.retrieval_eligible_count,
        "retrieval_excluded_count": outlook.retrieval_excluded_count,
        "retrieval_truncated": outlook.retrieval_truncated,
        "retrieval_exclusions": raw["retrieval_exclusions"],
        "retrieval_coverage_limitations": raw["retrieval_coverage_limitations"],
        "comparable_evidence": raw["comparable_evidence"],
        "metrics": raw["metrics"],
        "observations": raw["observations"],
        "suggested_hypothesis": raw["suggestion"],
        "accepted_hypothesis": (
            accepted_hypothesis.model_dump(mode="json") if accepted_hypothesis else None
        ),
        "assumptions": raw["assumptions"],
        "limitations": raw["limitations"],
        "exclusions": raw["exclusions"],
    }
    return DraftAnalysisResponse.model_validate(api_payload)


def _existing_assessment(
    session: Session,
    creator_id: UUID,
    idempotency_key: str,
    fingerprint: str,
    accepted_hypothesis: AcceptedHypothesis | None,
) -> DraftAnalysisResponse | None:
    existing = session.scalar(
        select(PersistedDraftAssessment).where(
            PersistedDraftAssessment.creator_id == creator_id,
            PersistedDraftAssessment.assessment_key == idempotency_key,
        )
    )
    if existing is None:
        return None
    if existing.content_fingerprint != fingerprint:
        raise ApiError(
            409,
            "idempotency_key_reused",
            "This idempotency key was already used for a different draft analysis.",
        )
    expected_hypothesis = (
        accepted_hypothesis.model_dump(mode="json") if accepted_hypothesis else None
    )
    if existing.accepted_hypothesis != expected_hypothesis:
        raise ApiError(
            409,
            "idempotency_key_reused",
            "This idempotency key was already used with a different accepted hypothesis.",
        )
    return _response_from_snapshot(existing.decision_snapshot)


def _metric_matches(record: OutcomeObservationRecord, request: DraftAnalysisRequest) -> bool:
    if not request.metric_preferences:
        return True
    return any(
        record.metric_name == item.metric
        and record.metric_definition == item.definition
        and record.metric_unit == item.unit
        and record.window_kind == item.window_kind
        and record.window_key == item.window_key
        for item in request.metric_preferences
    )


def analyze_draft(
    *,
    creator_id: UUID,
    session: Session,
    embedder: TextEmbedder,
    request: DraftAnalysisRequest,
    assessed_at: datetime,
    idempotency_key: str,
) -> DraftAnalysisResponse:
    """Run the deterministic draft-to-Outlook pipeline and persist its immutable result."""
    if assessed_at.tzinfo is None or assessed_at.utcoffset() is None:
        raise ApiError(500, "clock_invalid", "The assessment clock is unavailable.")
    if not idempotency_key.strip() or idempotency_key != idempotency_key.strip():
        raise ApiError(
            422, "invalid_idempotency_key", "Idempotency-Key must be non-blank and trimmed."
        )
    fingerprint = _content_fingerprint(request)
    try:
        prior = _existing_assessment(
            session,
            creator_id,
            idempotency_key,
            fingerprint,
            request.accepted_hypothesis,
        )
    except SQLAlchemyError as exc:
        raise ApiError(
            503, "analysis_store_unavailable", "Draft analysis is temporarily unavailable."
        ) from exc
    if prior is not None:
        return prior
    try:
        for preference in request.metric_preferences:
            _validate_series_support(session, creator_id, preference, assessed_at)
    except ApiError:
        raise
    except SQLAlchemyError as exc:
        raise ApiError(
            503, "analysis_store_unavailable", "Draft analysis is temporarily unavailable."
        ) from exc

    profile_input = PostProfileInput(
        text=_canonical_text(request.text),
        observed_at=assessed_at,
        features_as_of=assessed_at,
        creator_key=str(creator_id),
        topology=request.topology,
        thread_role=request.thread_role,
        media_types=request.media_types,
        declared_topic=request.declared_topic,
        declared_intent=request.declared_intent,
    )
    profile = extract_post_profile(profile_input)
    try:
        encoded = embedder.encode([_canonical_text(request.text)], role="query")
    except Exception as exc:
        raise ApiError(
            503, "embedding_unavailable", "Draft analysis is temporarily unavailable."
        ) from exc
    if len(encoded) != 1:
        raise ApiError(503, "embedding_unavailable", "Draft analysis is temporarily unavailable.")
    embedding = tuple(float(value) for value in encoded[0])
    assessment_id = str(uuid4())
    try:
        assessment = RetrievalDraftAssessment(
            assessment_id=assessment_id,
            creator_key=str(creator_id),
            as_of=assessed_at,
            profile=profile,
            embedding_identity=embedder.identity,
            embedding=embedding,
            embedding_observed_at=assessed_at,
        )
        retrieval_config = RetrievalConfig()
        candidate_batch = PostgresVectorCandidateSource(session).search(
            _vector_query(assessment, retrieval_config)
        )
        comparables = rank_comparable_candidates(
            assessment,
            candidate_batch.candidates,
            retrieval_config,
            prefiltered_exclusions=candidate_batch.prefiltered_exclusions,
            total_candidate_count=candidate_batch.total_candidate_count,
            vector_candidate_count=candidate_batch.vector_candidate_count,
            truncated=candidate_batch.truncated,
        )
        profiles_by_id = {
            candidate.post_id: candidate.profile
            for candidate in candidate_batch.candidates
            if candidate.profile is not None
        }
        match_ids = {match.post_id for match in comparables.matches}
        weights = {match.post_id: match.relevance for match in comparables.matches}
        records = (
            list(
                session.scalars(
                    select(OutcomeObservationRecord).where(
                        OutcomeObservationRecord.creator_id == creator_id,
                        OutcomeObservationRecord.post_id.in_([UUID(value) for value in match_ids]),
                    )
                ).all()
            )
            if match_ids
            else []
        )
        records = _latest_observation_records(
            [record for record in records if _metric_matches(record, request)], assessed_at
        )
        outcomes = outcome_observations_from_records(records, weights_by_post_id=weights)
        comparable_profiles = tuple(
            (post_id, profiles_by_id[post_id])
            for post_id in sorted(match_ids)
            if post_id in profiles_by_id
        )
        outlook = build_distribution_outlook(
            OutlookRequest(
                assessment=assessment,
                content_fingerprint=fingerprint,
                comparable_set=comparables,
                outcomes=outcomes,
                comparable_profiles=comparable_profiles,
            )
        )
        response = _build_api_response(
            outlook,
            assessed_at=assessed_at,
            accepted_hypothesis=request.accepted_hypothesis,
        )
        record = PersistedDraftAssessment(
            id=UUID(assessment_id),
            creator_id=creator_id,
            assessment_key=idempotency_key,
            assessed_at=assessed_at,
            content_fingerprint=fingerprint,
            outlook_version=OUTLOOK_ALGORITHM_VERSION,
            decision_snapshot=response.model_dump(mode="json"),
            accepted_hypothesis=(
                request.accepted_hypothesis.model_dump(mode="json")
                if request.accepted_hypothesis
                else None
            ),
        )
        session.add(record)
        session.commit()
        return response
    except ApiError:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        try:
            raced = _existing_assessment(
                session,
                creator_id,
                idempotency_key,
                fingerprint,
                request.accepted_hypothesis,
            )
        except ApiError:
            raise
        if raced is not None:
            return raced
        raise ApiError(
            409, "assessment_conflict", "The draft assessment could not be saved."
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise ApiError(
            503, "analysis_store_unavailable", "Draft analysis is temporarily unavailable."
        ) from exc
    except Exception as exc:
        session.rollback()
        raise ApiError(
            503, "analysis_unavailable", "Draft analysis is temporarily unavailable."
        ) from exc


def _vector_query(
    assessment: RetrievalDraftAssessment, config: RetrievalConfig
) -> VectorCandidateQuery:
    return VectorCandidateQuery(
        creator_key=assessment.creator_key,
        as_of=assessment.as_of,
        embedding_identity=assessment.embedding_identity,
        query_embedding=assessment.embedding,
        limit=config.candidate_limit,
    )


@router.post(
    "/draft-assessments",
    summary="Assess a draft against the creator's history",
    description=(
        "Runs profile extraction, local embedding, same-creator comparable retrieval, "
        "historical outcome analysis and immutable Outlook persistence. Requires an "
        "Idempotency-Key and COD-346's active server-verified creator session."
    ),
    response_model=DraftAnalysisResponse,
    status_code=201,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def create_draft_assessment(
    payload: DraftAnalysisRequest,
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    session: Annotated[Session, Depends(get_db_session)],
    embedder: Annotated[TextEmbedder, Depends(get_embedder)],
    assessed_at: Annotated[datetime, Depends(get_current_time)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> DraftAnalysisResponse:
    """Create or replay one same-creator idempotent, immutable draft Outlook."""
    result = analyze_draft(
        creator_id=creator.creator_id,
        session=session,
        embedder=embedder,
        request=payload,
        assessed_at=assessed_at,
        idempotency_key=idempotency_key,
    )
    return result


@router.get(
    "/draft-assessments/{assessment_id}",
    summary="Read one of the authenticated creator's immutable assessments",
    description=(
        "Returns only a saved assessment owned by the server-verified creator; "
        "foreign and absent IDs are indistinguishable."
    ),
    response_model=DraftAnalysisResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def get_draft_assessment(
    assessment_id: UUID,
    creator: Annotated[AuthenticatedCreator, Depends(get_authenticated_creator)],
    session: Annotated[Session, Depends(get_db_session)],
) -> DraftAnalysisResponse:
    """Read an assessment only through the server-verified creator ownership key."""
    try:
        record = session.scalar(
            select(PersistedDraftAssessment).where(
                PersistedDraftAssessment.id == assessment_id,
                PersistedDraftAssessment.creator_id == creator.creator_id,
            )
        )
    except SQLAlchemyError as exc:
        raise ApiError(
            503, "analysis_store_unavailable", "Saved assessment is temporarily unavailable."
        ) from exc
    if record is None:
        raise ApiError(404, "assessment_not_found", "The requested assessment was not found.")
    return _response_from_snapshot(record.decision_snapshot)
