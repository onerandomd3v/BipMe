from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from bipme.intelligence.embeddings import EmbeddingIdentity
from bipme.intelligence.post_profiles import (
    CreatorContextSnapshot,
    PostProfileInput,
    extract_post_profile,
)
from bipme.intelligence.retrieval import VectorCandidateQuery
from bipme.persistence.contracts import (
    embedding_identity_from_record,
    outcome_observations_from_records,
    pgvector_candidate_statement,
    post_profile_from_record,
    post_profile_payload,
)
from bipme.persistence.models import OutcomeObservationRecord, PostEmbedding, PostProfileRecord

AS_OF = datetime(2026, 11, 8, 12, tzinfo=UTC)
REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"
IDENTITY = EmbeddingIdentity("intfloat/multilingual-e5-small", REVISION, 384, "e5-prefix-strip-v1")


def profile_input(*, text: str | None = "A post", media_types: tuple[str, ...] | None = ()):
    return PostProfileInput(
        text=text,
        observed_at=AS_OF,
        features_as_of=AS_OF,
        creator_key="creator-source",
        topology="original",
        media_types=media_types,  # type: ignore[arg-type]
        creator_context=CreatorContextSnapshot(AS_OF, follower_count=0),
    )


def profile_record(
    *, creator_id=None, feature_text: str | None = None, media_types: tuple[str, ...] | None = ()
) -> PostProfileRecord:
    creator_id = creator_id or uuid4()
    profile = extract_post_profile(profile_input(text=feature_text, media_types=media_types))
    return PostProfileRecord(
        id=uuid4(),
        post_id=uuid4(),
        creator_id=creator_id,
        profile_version=profile.version,
        features_as_of=profile.features_as_of,
        input_observed_at=profile.input_observed_at,
        creator_context_observed_at=profile.creator_context_observed_at,
        features=post_profile_payload(profile),
    )


def test_profile_payload_round_trip_preserves_unknown_and_known_absence() -> None:
    unknown = profile_record(feature_text=None, media_types=None)
    known_empty = profile_record(feature_text="", media_types=())

    restored_unknown = post_profile_from_record(unknown)
    restored_empty = post_profile_from_record(known_empty)

    assert restored_unknown.character_count is None
    assert restored_unknown.hashtags is None
    assert restored_unknown.media_types is None
    assert restored_empty.character_count == 0
    assert restored_empty.hashtags == ()
    assert restored_empty.media_types == ()
    assert restored_empty.creator_follower_count == 0
    assert restored_empty.creator_key == str(known_empty.creator_id)


def test_embedding_identity_round_trip_retains_every_index_dimension() -> None:
    record = PostEmbedding(
        id=uuid4(),
        post_id=uuid4(),
        creator_id=uuid4(),
        model_id=IDENTITY.model_id,
        model_revision=IDENTITY.revision,
        dimensions=IDENTITY.dimensions,
        preprocessing_version=IDENTITY.preprocessing_version,
        normalized=IDENTITY.normalized,
        embedding_version=IDENTITY.embedding_version,
        embedding=[1.0, *([0.0] * 383)],
        generated_at=AS_OF,
    )

    assert embedding_identity_from_record(record) == IDENTITY
    assert record.embedding[0] == 1.0


def outcome_record(
    *,
    creator_id,
    post_id,
    value: Decimal | None,
    state: str,
    window_kind: str = "age_aligned",
    window_key: str = "age:1h",
    observed_at: datetime = AS_OF,
) -> OutcomeObservationRecord:
    return OutcomeObservationRecord(
        id=uuid4(),
        creator_id=creator_id,
        post_id=post_id,
        published_at=datetime(2026, 11, 8, 10, tzinfo=UTC),
        metric_name="impressions",
        metric_definition="public_impressions_v1",
        metric_unit="impressions",
        metric_value=value,
        state=state,
        window_kind=window_kind,
        window_key=window_key,
        observed_at=observed_at,
        idempotency_key=str(uuid4()),
        provenance={},
    )


def test_outcome_mapping_preserves_zero_missing_window_and_real_timestamps() -> None:
    creator_id, zero_post, missing_post, invalid_post = uuid4(), uuid4(), uuid4(), uuid4()
    records = (
        outcome_record(
            creator_id=creator_id, post_id=zero_post, value=Decimal("0"), state="observed"
        ),
        outcome_record(creator_id=creator_id, post_id=missing_post, value=None, state="missing"),
        outcome_record(creator_id=creator_id, post_id=invalid_post, value=None, state="invalid"),
    )

    mapped = outcome_observations_from_records(
        records,
        weights_by_post_id={str(zero_post): 0.5, str(missing_post): 1.0},
    )

    assert len(mapped) == 2
    assert mapped[0].creator_key == str(creator_id)
    assert mapped[0].value == 0.0
    assert mapped[0].metric_definition == "public_impressions_v1|unit=impressions"
    assert mapped[0].window == "age_aligned:age:1h"
    assert mapped[0].observed_at == AS_OF
    assert mapped[0].weight == 0.5
    assert mapped[1].value is None


def test_mature_and_age_aligned_observations_get_distinct_baseline_windows() -> None:
    creator_id, post_id = uuid4(), uuid4()
    rows = (
        outcome_record(
            creator_id=creator_id,
            post_id=post_id,
            value=Decimal("120"),
            state="observed",
            window_kind="mature_cumulative",
            window_key="mature",
        ),
        outcome_record(
            creator_id=creator_id, post_id=post_id, value=Decimal("5"), state="observed"
        ),
    )

    mapped = outcome_observations_from_records(
        rows,
        weights_by_post_id={str(post_id): 1.0},
    )

    assert {observation.window for observation in mapped} == {
        "mature_cumulative:mature",
        "age_aligned:age:1h",
    }
    assert mapped[0].published_at < mapped[0].observed_at


def test_missing_relevance_weight_fails_closed() -> None:
    row = outcome_record(creator_id=uuid4(), post_id=uuid4(), value=Decimal("1"), state="observed")

    with pytest.raises(ValueError, match="missing caller weight"):
        outcome_observations_from_records((row,), weights_by_post_id={})


def test_pgvector_statement_applies_owner_identity_and_as_of_filters_before_ordering() -> None:
    query = VectorCandidateQuery(
        creator_key=str(uuid4()),
        as_of=AS_OF,
        embedding_identity=IDENTITY,
        query_embedding=(1.0, *([0.0] * 383)),
        limit=12,
    )
    sql = str(pgvector_candidate_statement(query).compile(dialect=postgresql.dialect()))

    assert "canonical_posts.creator_id =" in sql
    assert "canonical_posts.published_at <" in sql
    assert "post_embeddings.model_revision =" in sql
    assert "post_embeddings.generated_at <=" in sql
    assert "post_profiles.features_as_of <=" in sql
    assert "post_profiles.input_observed_at <=" in sql
    assert "ORDER BY post_embeddings.embedding <=>" in sql
    assert "LIMIT" in sql


def test_pgvector_statement_rejects_a_mismatched_query_vector() -> None:
    query = VectorCandidateQuery(
        creator_key=str(uuid4()),
        as_of=AS_OF,
        embedding_identity=IDENTITY,
        query_embedding=(1.0, 0.0),
        limit=12,
    )

    with pytest.raises(ValueError, match="query vector dimensions"):
        pgvector_candidate_statement(query)
