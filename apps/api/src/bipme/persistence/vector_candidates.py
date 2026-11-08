"""PostgreSQL-backed COD-352 candidate source using the COD-345 schema."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from bipme.intelligence.embeddings import EmbeddingIdentity
from bipme.intelligence.post_profiles import PROFILE_VERSION
from bipme.intelligence.retrieval import (
    CandidateExclusion,
    VectorCandidateBatch,
    VectorCandidateQuery,
)
from bipme.persistence.contracts import (
    comparable_candidate_from_records,
    pgvector_candidate_statement,
)
from bipme.persistence.models import CanonicalPost, PostEmbedding, PostProfileRecord


@dataclass
class PostgresVectorCandidateSource:
    """Execute a bounded, creator-scoped pgvector query and report storage exclusions."""

    session: Session

    def search(self, query: VectorCandidateQuery) -> VectorCandidateBatch:
        """Return semantic top-K rows with counts, deterministic ordering and coverage."""
        statement = pgvector_candidate_statement(query)
        all_posts = self.session.execute(
            select(CanonicalPost.id, CanonicalPost.availability, CanonicalPost.published_at).where(
                CanonicalPost.creator_id == _creator_uuid(query.creator_key),
                CanonicalPost.published_at < query.as_of,
            )
        ).all()
        base_ids = {row.id for row in all_posts}

        unbounded = statement.order_by(None).limit(None)
        vector_candidate_count = int(
            self.session.scalar(select(func.count()).select_from(unbounded.subquery())) or 0
        )
        eligible_ids = set(
            self.session.scalars(
                unbounded.with_only_columns(CanonicalPost.id, maintain_column_froms=True).distinct()
            ).all()
        )
        rows = self.session.execute(statement).all()
        candidates = tuple(
            comparable_candidate_from_records(post, profile, embedding)
            for post, profile, embedding in rows
        )

        rejected_ids = base_ids - eligible_ids
        exclusions = self._exclusions(query, all_posts, rejected_ids)
        return VectorCandidateBatch(
            candidates=candidates,
            total_candidate_count=len(all_posts),
            vector_candidate_count=vector_candidate_count,
            truncated=vector_candidate_count > len(candidates),
            prefiltered_exclusions=exclusions,
        )

    def _exclusions(
        self,
        query: VectorCandidateQuery,
        all_posts: Sequence[Any],
        rejected_ids: set[UUID],
    ) -> tuple[CandidateExclusion, ...]:
        """Explain records omitted by SQL storage filters without exposing content."""
        if not rejected_ids:
            return ()
        identity = query.embedding_identity
        post_rows = [row for row in all_posts if row.id in rejected_ids]
        publication = {row.id: row.published_at for row in post_rows}
        availability = {row.id: row.availability for row in post_rows}
        ids = list(rejected_ids)
        profiles = self.session.scalars(
            select(PostProfileRecord).where(
                PostProfileRecord.creator_id == _creator_uuid(query.creator_key),
                PostProfileRecord.post_id.in_(ids),
            )
        ).all()
        embeddings = self.session.scalars(
            select(PostEmbedding).where(
                PostEmbedding.creator_id == _creator_uuid(query.creator_key),
                PostEmbedding.post_id.in_(ids),
            )
        ).all()
        profiles_by_post: dict[object, list[PostProfileRecord]] = defaultdict(list)
        embeddings_by_post: dict[object, list[PostEmbedding]] = defaultdict(list)
        for profile in profiles:
            profiles_by_post[profile.post_id].append(profile)
        for embedding in embeddings:
            embeddings_by_post[embedding.post_id].append(embedding)

        results: list[CandidateExclusion] = []
        for post_id in sorted(rejected_ids, key=str):
            reasons: set[str] = set()
            if availability[post_id] != "available":
                reasons.add("post_unavailable")
            post_profiles = profiles_by_post[post_id]
            supported_profiles = [
                profile for profile in post_profiles if profile.profile_version == PROFILE_VERSION
            ]
            if not post_profiles:
                reasons.add("missing_post_profile")
            elif not supported_profiles:
                reasons.add("unsupported_profile_version")
            elif not any(
                profile.features_as_of <= query.as_of
                and profile.input_observed_at <= query.as_of
                and profile.features_as_of >= publication[post_id]
                and profile.input_observed_at >= publication[post_id]
                and (
                    profile.creator_context_observed_at is None
                    or profile.creator_context_observed_at <= query.as_of
                )
                for profile in supported_profiles
            ):
                reasons.add(_profile_time_reason(supported_profiles, publication[post_id], query))

            post_embeddings = embeddings_by_post[post_id]
            if not post_embeddings:
                reasons.add("missing_embedding")
            else:
                exact = [item for item in post_embeddings if _same_identity(item, identity)]
                if not exact:
                    reasons.add("embedding_identity_mismatch")
                elif not any(
                    item.generated_at <= query.as_of and item.generated_at >= publication[post_id]
                    for item in exact
                ):
                    if all(item.generated_at > query.as_of for item in exact):
                        reasons.add("embedding_generated_after_assessment_cutoff")
                    else:
                        reasons.add("embedding_predates_publication")
            results.append(
                CandidateExclusion(str(post_id), tuple(sorted(reasons or {"storage_filter"})))
            )
        return tuple(results)


def _creator_uuid(value: str) -> UUID:
    """Parse the authenticated creator's canonical database identity."""
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError("creator_key must be a canonical UUID") from exc


def _same_identity(record: PostEmbedding, identity: EmbeddingIdentity) -> bool:
    return (
        record.model_id == identity.model_id
        and record.model_revision == identity.revision
        and record.dimensions == identity.dimensions
        and record.preprocessing_version == identity.preprocessing_version
        and record.normalized == identity.normalized
        and record.embedding_version == identity.embedding_version
    )


def _profile_time_reason(
    profiles: list[PostProfileRecord], published_at: datetime, query: VectorCandidateQuery
) -> str:
    if any(
        profile.features_as_of > query.as_of or profile.input_observed_at > query.as_of
        for profile in profiles
    ):
        return "profile_observed_after_assessment_cutoff"
    if any(
        profile.creator_context_observed_at is not None
        and profile.creator_context_observed_at > query.as_of
        for profile in profiles
    ):
        return "creator_context_after_assessment_cutoff"
    if any(
        profile.features_as_of < published_at or profile.input_observed_at < published_at
        for profile in profiles
    ):
        return "profile_predates_publication"
    return "profile_not_eligible_at_assessment_cutoff"
