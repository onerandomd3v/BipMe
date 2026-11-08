"""Typed adapters from canonical database rows to existing intelligence contracts."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select

from bipme.intelligence.baselines import OutcomeObservation
from bipme.intelligence.embeddings import EmbeddingIdentity
from bipme.intelligence.post_profiles import PROFILE_VERSION, PostProfile
from bipme.intelligence.retrieval import ComparableCandidate, VectorCandidateQuery
from bipme.persistence.models import (
    CanonicalPost,
    OutcomeObservationRecord,
    PostEmbedding,
    PostProfileRecord,
)


def _utc_datetime(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value)
    else:
        raise ValueError(f"profile field {field} must be an ISO timestamp")
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"profile field {field} must be timezone-aware")
    return result


def post_profile_payload(profile: PostProfile) -> dict[str, Any]:
    """Serialize COD-350 output as JSON-compatible descriptive data only."""
    payload = asdict(profile)
    for key in ("features_as_of", "input_observed_at", "creator_context_observed_at"):
        value = payload[key]
        payload[key] = value.isoformat() if value is not None else None
    return payload


def post_profile_from_record(record: PostProfileRecord) -> PostProfile:
    """Restore COD-350's frozen profile, preserving null versus known-empty values."""
    payload = dict(record.features)
    payload["version"] = record.profile_version
    payload["features_as_of"] = record.features_as_of
    payload["input_observed_at"] = record.input_observed_at
    payload["creator_context_observed_at"] = record.creator_context_observed_at
    payload["creator_key"] = str(record.creator_id)
    for key in (
        "hashtags",
        "mentions",
        "format_tags",
        "media_types",
        "topic_signals",
        "intent_signals",
    ):
        if payload.get(key) is not None:
            payload[key] = tuple(payload[key])
    payload["features_as_of"] = _utc_datetime(payload["features_as_of"], "features_as_of")
    payload["input_observed_at"] = _utc_datetime(payload["input_observed_at"], "input_observed_at")
    if payload.get("creator_context_observed_at") is not None:
        payload["creator_context_observed_at"] = _utc_datetime(
            payload["creator_context_observed_at"], "creator_context_observed_at"
        )
    if payload["version"] != PROFILE_VERSION:
        raise ValueError(f"unsupported persisted Post Profile version: {payload['version']}")
    return PostProfile(**payload)


def comparable_candidate_from_records(
    post: CanonicalPost,
    profile: PostProfileRecord,
    embedding: PostEmbedding,
) -> ComparableCandidate:
    """Map a same-owner canonical post and compatible records to COD-352's row."""
    if post.id != profile.post_id or post.creator_id != profile.creator_id:
        raise ValueError("Post Profile is not owned by the canonical post creator")
    if post.id != embedding.post_id or post.creator_id != embedding.creator_id:
        raise ValueError("embedding is not owned by the canonical post creator")
    return ComparableCandidate(
        post_id=str(post.id),
        creator_key=str(post.creator_id),
        published_at=post.published_at,
        available=post.availability == "available",
        profile=post_profile_from_record(profile),
        embedding_identity=embedding_identity_from_record(embedding),
        embedding=tuple(embedding.embedding),
        embedding_observed_at=embedding.generated_at,
    )


def embedding_identity_from_record(record: PostEmbedding) -> EmbeddingIdentity:
    """Rebuild the complete COD-351 vector-space identity stored with a vector."""
    return EmbeddingIdentity(
        model_id=record.model_id,
        revision=record.model_revision,
        dimensions=record.dimensions,
        preprocessing_version=record.preprocessing_version,
        normalized=record.normalized,
        embedding_version=record.embedding_version,
    )


def _creator_uuid(creator_key: str) -> UUID:
    try:
        return UUID(creator_key)
    except ValueError as exc:
        raise ValueError("creator_key must be the canonical creator UUID string") from exc


def pgvector_candidate_statement(
    query: VectorCandidateQuery,
) -> Select[CanonicalPost, PostProfileRecord, PostEmbedding]:
    """Build the COD-352 bounded pgvector query without adding a ranking service.

    Filters are applied before cosine ordering: same creator, available earlier post,
    latest eligible COD-350 profile and exact COD-351 identity. HNSW is partial to the
    currently pinned E5 space; future identities require a deliberate index migration.
    """
    from sqlalchemy import select

    if query.limit < 1:
        raise ValueError("candidate query limit must be positive")
    creator_id = _creator_uuid(query.creator_key)
    if len(query.query_embedding) != query.embedding_identity.dimensions:
        raise ValueError("query vector dimensions differ from EmbeddingIdentity")
    latest_profile_id = (
        select(PostProfileRecord.id)
        .where(
            PostProfileRecord.post_id == CanonicalPost.id,
            PostProfileRecord.creator_id == CanonicalPost.creator_id,
            PostProfileRecord.profile_version == PROFILE_VERSION,
            PostProfileRecord.features_as_of <= query.as_of,
            PostProfileRecord.input_observed_at <= query.as_of,
            PostProfileRecord.features_as_of >= CanonicalPost.published_at,
            PostProfileRecord.input_observed_at >= CanonicalPost.published_at,
            (PostProfileRecord.creator_context_observed_at.is_(None))
            | (PostProfileRecord.creator_context_observed_at <= query.as_of),
        )
        .order_by(
            PostProfileRecord.features_as_of.desc(),
            PostProfileRecord.input_observed_at.desc(),
            PostProfileRecord.id,
        )
        .limit(1)
        .correlate(CanonicalPost)
        .scalar_subquery()
    )
    identity = query.embedding_identity
    return (
        select(CanonicalPost, PostProfileRecord, PostEmbedding)
        .join(
            PostProfileRecord,
            PostProfileRecord.id == latest_profile_id,
        )
        .join(
            PostEmbedding,
            (PostEmbedding.post_id == CanonicalPost.id)
            & (PostEmbedding.creator_id == CanonicalPost.creator_id),
        )
        .where(
            CanonicalPost.creator_id == creator_id,
            CanonicalPost.availability == "available",
            CanonicalPost.published_at < query.as_of,
            PostEmbedding.model_id == identity.model_id,
            PostEmbedding.model_revision == identity.revision,
            PostEmbedding.dimensions == identity.dimensions,
            PostEmbedding.preprocessing_version == identity.preprocessing_version,
            PostEmbedding.normalized == identity.normalized,
            PostEmbedding.embedding_version == identity.embedding_version,
            PostEmbedding.generated_at <= query.as_of,
            PostEmbedding.generated_at >= CanonicalPost.published_at,
        )
        .order_by(
            PostEmbedding.embedding.cosine_distance(list(query.query_embedding)),
            CanonicalPost.id,
        )
        .limit(query.limit)
    )


def outcome_observations_from_records(
    records: tuple[OutcomeObservationRecord, ...] | list[OutcomeObservationRecord],
    *,
    weights_by_post_id: dict[str, float],
    segment_paths_by_post_id: dict[str, tuple[str, ...]] | None = None,
) -> tuple[OutcomeObservation, ...]:
    """Map usable/missing snapshots to COD-353 without mixing definitions or windows.

    The baseline contract has no separate unit or window-kind fields. The adapter folds
    both into its exact identity keys as ``definition|unit=<unit>`` and
    ``<window_kind>:<window_key>``. Invalid-state rows are excluded rather than presented
    as known missing values. Callers supply non-outcome-derived relevance weights.
    """
    segments = segment_paths_by_post_id or {}
    observations: list[OutcomeObservation] = []
    for record in records:
        if record.state == "invalid":
            continue
        post_id = str(record.post_id)
        if post_id not in weights_by_post_id:
            raise ValueError(f"missing caller weight for post {post_id}")
        if record.state == "observed":
            if record.metric_value is None:
                raise ValueError("observed outcome row has no metric value")
            value = float(record.metric_value)
        else:
            value = None
        observations.append(
            OutcomeObservation(
                creator_key=str(record.creator_id),
                post_id=post_id,
                metric=record.metric_name,
                metric_definition=f"{record.metric_definition}|unit={record.metric_unit}",
                value=value,
                published_at=record.published_at,
                observed_at=record.observed_at,
                window=f"{record.window_kind}:{record.window_key}",
                weight=weights_by_post_id[post_id],
                segment_path=segments.get(post_id, ()),
            )
        )
    return tuple(observations)
