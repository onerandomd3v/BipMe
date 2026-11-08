"""PostgreSQL integration coverage for COD-345 models and real Alembic migrations."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, StatementError
from sqlalchemy.orm import Session

from bipme.intelligence.embeddings import EmbeddingIdentity
from bipme.intelligence.post_profiles import (
    CreatorContextSnapshot,
    PostProfileInput,
    extract_post_profile,
)
from bipme.intelligence.retrieval import VectorCandidateQuery
from bipme.persistence.contracts import (
    comparable_candidate_from_records,
    pgvector_candidate_statement,
    post_profile_payload,
)
from bipme.persistence.models import (
    APIUsageLedger,
    CanonicalPost,
    Creator,
    CreatorPlatformIdentity,
    DraftAssessment,
    OutcomeObservationRecord,
    PostEmbedding,
    PostProfileRecord,
    XAccountConnection,
)

API_DIR = Path(__file__).parents[1]
NOW = datetime(2026, 11, 8, 14, tzinfo=UTC)
REVISION = "fd1525a9fd15316a2d503bf26ab031a61d056e98"
IDENTITY = EmbeddingIdentity("intfloat/multilingual-e5-small", REVISION, 384, "e5-prefix-strip-v1")


@pytest.fixture(scope="module")
def migrated_postgres() -> Iterator[tuple[Engine, str]]:
    database_url = os.getenv("BIPME_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("BIPME_TEST_DATABASE_URL is required for PostgreSQL migration tests")

    engine = create_engine(database_url)
    schema = f"cod345_{uuid4().hex}"
    connection = engine.connect()
    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    connection.execute(text(f'SET search_path TO "{schema}", public'))
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    config.attributes["connection"] = connection
    try:
        # Exercise a clean forward migration, downgrade to the original pgvector base,
        # and a repeat forward migration in this isolated schema.
        command.upgrade(config, "head")
        connection.commit()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0002_canonical_persistence"
        )
        command.downgrade(config, "0001_enable_vector")
        connection.commit()
        assert "canonical_posts" not in inspect(connection).get_table_names()
        assert connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
        command.upgrade(config, "head")
        connection.commit()
        tables = set(inspect(connection).get_table_names())
        expected = {
            "creators",
            "creator_platform_identities",
            "x_account_connections",
            "draft_assessments",
            "canonical_posts",
            "post_profiles",
            "post_embeddings",
            "outcome_observations",
            "api_usage_ledger",
        }
        assert expected <= tables
        indexes = {index["name"] for index in inspect(connection).get_indexes("post_embeddings")}
        assert "ix_embeddings_e5_v1_cosine" in indexes
        assert "ix_posts_creator_published" in {
            index["name"] for index in inspect(connection).get_indexes("canonical_posts")
        }
        yield engine, schema
    finally:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        connection.commit()
        connection.close()
        engine.dispose()


@pytest.fixture
def session(migrated_postgres: tuple[Engine, str]) -> Iterator[Session]:
    engine, schema = migrated_postgres
    connection = engine.connect()
    connection.execute(text(f'SET search_path TO "{schema}", public'))
    connection.commit()
    transaction = connection.begin()
    db_session = Session(bind=connection)
    try:
        yield db_session
    finally:
        db_session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _creator(session: Session) -> Creator:
    creator = Creator(id=uuid4())
    session.add(creator)
    session.flush()
    return creator


def _post(
    session: Session,
    creator_id: UUID,
    *,
    external_id: str | None = None,
    published_at: datetime = NOW - timedelta(hours=1),
    source_assessment_id: UUID | None = None,
) -> CanonicalPost:
    post = CanonicalPost(
        id=uuid4(),
        creator_id=creator_id,
        platform="x",
        external_post_id=external_id or str(uuid4()),
        published_at=published_at,
        availability="available",
        topology="original",
        source_assessment_id=source_assessment_id,
    )
    session.add(post)
    session.flush()
    return post


def _profile(
    session: Session,
    post: CanonicalPost,
    *,
    features_as_of: datetime,
    text_value: str | None = "A synthetic post",
    version: str = "post-profile-v1",
) -> PostProfileRecord:
    profile = extract_post_profile(
        PostProfileInput(
            text=text_value,
            observed_at=features_as_of,
            features_as_of=features_as_of,
            creator_key=str(post.creator_id),
            topology="original",
            media_types=(),
            creator_context=CreatorContextSnapshot(features_as_of, follower_count=12),
        ),
        version=version,
    )
    record = PostProfileRecord(
        id=uuid4(),
        post_id=post.id,
        creator_id=post.creator_id,
        profile_version=profile.version,
        features_as_of=profile.features_as_of,
        input_observed_at=profile.input_observed_at,
        creator_context_observed_at=profile.creator_context_observed_at,
        features=post_profile_payload(profile),
    )
    session.add(record)
    session.flush()
    return record


def _embedding(
    session: Session,
    post: CanonicalPost,
    *,
    generated_at: datetime,
    identity: EmbeddingIdentity = IDENTITY,
) -> PostEmbedding:
    row = PostEmbedding(
        id=uuid4(),
        post_id=post.id,
        creator_id=post.creator_id,
        model_id=identity.model_id,
        model_revision=identity.revision,
        dimensions=identity.dimensions,
        preprocessing_version=identity.preprocessing_version,
        normalized=identity.normalized,
        embedding_version=identity.embedding_version,
        embedding=[1.0, *([0.0] * 383)],
        generated_at=generated_at,
    )
    session.add(row)
    session.flush()
    return row


def test_migration_survives_clean_upgrade_downgrade_and_repeat_upgrade(
    migrated_postgres: tuple[Engine, str],
) -> None:
    engine, schema = migrated_postgres
    with engine.connect() as connection:
        connection.execute(text(f'SET search_path TO "{schema}", public'))
        connection.commit()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0002_canonical_persistence"
        )


def test_creator_scoped_ownership_and_post_ingestion_are_enforced(session: Session) -> None:
    creator_a, creator_b = _creator(session), _creator(session)
    post = _post(session, creator_a.id, external_id="x-post-001")

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                CanonicalPost(
                    id=uuid4(),
                    creator_id=creator_b.id,
                    platform="x",
                    external_post_id="x-post-001",
                    published_at=NOW,
                    availability="available",
                    topology="original",
                )
            )
            session.flush()

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                OutcomeObservationRecord(
                    id=uuid4(),
                    post_id=post.id,
                    creator_id=creator_b.id,
                    published_at=post.published_at,
                    metric_name="impressions",
                    metric_definition="public_impressions_v1",
                    metric_unit="impressions",
                    metric_value=Decimal("1"),
                    state="observed",
                    window_kind="mature_cumulative",
                    window_key="mature",
                    observed_at=NOW,
                    idempotency_key="owner-mismatch",
                    provenance={},
                )
            )
            session.flush()


def test_outcome_snapshots_are_idempotent_and_preserve_zero_missing_and_time(
    session: Session,
) -> None:
    creator = _creator(session)
    post = _post(session, creator.id)
    common = dict(
        id=uuid4(),
        post_id=post.id,
        creator_id=creator.id,
        published_at=post.published_at,
        metric_name="replies",
        metric_definition="public_reply_count_v1",
        metric_unit="replies",
        window_kind="age_aligned",
        window_key="age:1h",
        provenance={},
    )
    zero = OutcomeObservationRecord(
        **common,
        metric_value=Decimal("0"),
        state="observed",
        observed_at=post.published_at + timedelta(hours=1),
        idempotency_key="snapshot-1",
    )
    later = OutcomeObservationRecord(
        **{**common, "id": uuid4()},
        metric_value=Decimal("3"),
        state="observed",
        observed_at=post.published_at + timedelta(hours=2),
        idempotency_key="snapshot-2",
    )
    missing = OutcomeObservationRecord(
        **{**common, "id": uuid4()},
        metric_value=None,
        state="missing",
        observed_at=post.published_at + timedelta(hours=3),
        idempotency_key="snapshot-missing",
    )
    session.add_all([zero, later, missing])
    session.flush()

    rows = session.scalars(
        select(OutcomeObservationRecord).where(OutcomeObservationRecord.post_id == post.id)
    ).all()
    assert len(rows) == 3
    assert next(row for row in rows if row.state == "observed").metric_value == Decimal("0E-10")
    assert next(row for row in rows if row.state == "missing").metric_value is None
    assert {row.observed_at for row in rows} == {
        post.published_at + timedelta(hours=1),
        post.published_at + timedelta(hours=2),
        post.published_at + timedelta(hours=3),
    }

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                OutcomeObservationRecord(
                    **{**common, "id": uuid4()},
                    metric_value=Decimal("0"),
                    state="observed",
                    observed_at=zero.observed_at,
                    idempotency_key="duplicate-observation-time",
                )
            )
            session.flush()


def test_profile_and_embedding_versions_are_unique_and_creator_scoped(session: Session) -> None:
    creator_a, creator_b = _creator(session), _creator(session)
    post = _post(session, creator_a.id)
    profile = _profile(session, post, features_as_of=post.published_at + timedelta(minutes=1))

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                PostProfileRecord(
                    id=uuid4(),
                    post_id=post.id,
                    creator_id=creator_a.id,
                    profile_version=profile.profile_version,
                    features_as_of=profile.features_as_of,
                    input_observed_at=profile.input_observed_at,
                    creator_context_observed_at=profile.creator_context_observed_at,
                    features=profile.features,
                )
            )
            session.flush()

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                PostProfileRecord(
                    id=uuid4(),
                    post_id=post.id,
                    creator_id=creator_b.id,
                    profile_version="post-profile-v2",
                    features_as_of=NOW,
                    input_observed_at=NOW,
                    features={},
                )
            )
            session.flush()

    embedding = _embedding(session, post, generated_at=post.published_at + timedelta(minutes=2))
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                PostEmbedding(
                    id=uuid4(),
                    post_id=post.id,
                    creator_id=creator_a.id,
                    model_id=embedding.model_id,
                    model_revision=embedding.model_revision,
                    dimensions=embedding.dimensions,
                    preprocessing_version=embedding.preprocessing_version,
                    normalized=embedding.normalized,
                    embedding_version=embedding.embedding_version,
                    embedding=embedding.embedding,
                    generated_at=NOW,
                )
            )
            session.flush()

    replacement = _embedding(
        session,
        post,
        generated_at=NOW,
        identity=EmbeddingIdentity(
            IDENTITY.model_id,
            IDENTITY.revision,
            IDENTITY.dimensions,
            IDENTITY.preprocessing_version,
            IDENTITY.normalized,
            embedding_version="2",
        ),
    )
    assert replacement.embedding_version == "2"


def test_x_connection_ownership_revocation_and_ciphertext_boundary(session: Session) -> None:
    creator = _creator(session)
    identity = CreatorPlatformIdentity(
        id=uuid4(),
        creator_id=creator.id,
        platform="x",
        external_creator_id="x-user-001",
        handle="creator",
    )
    session.add(identity)
    session.flush()
    connection = XAccountConnection(
        id=uuid4(),
        creator_id=creator.id,
        creator_identity_id=identity.id,
        platform="x",
        state="connected",
        scopes=["tweet.read", "users.read"],
        encrypted_access_token=b"BIPME-ENC\x01synthetic-ciphertext-access",
        encrypted_refresh_token=b"BIPME-ENC\x01synthetic-ciphertext-refresh",
        key_version="kms-key-v1",
        access_token_expires_at=NOW + timedelta(hours=1),
        token_rotated_at=NOW,
    )
    session.add(connection)
    session.flush()
    assert connection.encrypted_access_token.startswith(b"BIPME-ENC\x01")
    assert connection.scopes == ["tweet.read", "users.read"]

    connection.state = "revoked"
    connection.revoked_at = NOW
    connection.encrypted_access_token = None
    connection.encrypted_refresh_token = None
    session.flush()
    assert session.get(XAccountConnection, connection.id).revoked_at == NOW

    with pytest.raises(StatementError, match="encrypted BIPME-ENC v1 envelopes"):
        with session.begin_nested():
            session.add(
                XAccountConnection(
                    id=uuid4(),
                    creator_id=creator.id,
                    creator_identity_id=identity.id,
                    platform="x",
                    state="connected",
                    scopes=[],
                    encrypted_access_token=b"plaintext-token-is-rejected",
                    key_version="kms-key-v1",
                )
            )
            session.flush()

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                XAccountConnection(
                    id=uuid4(),
                    creator_id=creator.id,
                    creator_identity_id=identity.id,
                    platform="x",
                    state="connected",
                    scopes=[],
                    encrypted_access_token=None,
                    key_version="kms-key-v1",
                )
            )
            session.flush()


def test_api_usage_ledger_enforces_idempotency_and_usage_bounds(session: Session) -> None:
    creator = _creator(session)
    row = APIUsageLedger(
        id=uuid4(),
        creator_id=creator.id,
        provider="x",
        operation="users.posts.read",
        idempotency_key="x-request-001",
        request_metadata={"endpoint": "users.posts", "limit": 10},
        requested_at=NOW,
        completed_at=NOW + timedelta(seconds=3),
        usage_units=7,
        currency="USD",
        estimated_cost=Decimal("0.01000000"),
        actual_cost=Decimal("0.00700000"),
        reconciliation_state="reconciled",
    )
    session.add(row)
    session.flush()
    assert session.get(APIUsageLedger, row.id).actual_cost == Decimal("0.00700000")

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                APIUsageLedger(
                    id=uuid4(),
                    creator_id=creator.id,
                    provider="x",
                    operation="users.posts.read",
                    idempotency_key="x-request-001",
                    request_metadata={},
                    requested_at=NOW,
                )
            )
            session.flush()


def test_assessment_snapshot_is_immutable_and_publication_link_is_single_creator_scoped(
    session: Session,
) -> None:
    creator_a, creator_b = _creator(session), _creator(session)
    assessment = DraftAssessment(
        id=uuid4(),
        creator_id=creator_a.id,
        assessment_key="assessment-001",
        assessed_at=NOW,
        content_fingerprint="sha256:" + "a" * 64,
        outlook_version="distribution-outlook-v1+distribution-outlook-config-v1",
        decision_snapshot={"decision_state": "insufficient_evidence", "suggestion": None},
        accepted_hypothesis=None,
    )
    session.add(assessment)
    session.flush()

    with pytest.raises(DBAPIError, match="draft assessment snapshots are immutable"):
        with session.begin_nested():
            assessment.decision_snapshot = {"decision_state": "supported"}
            session.flush()

    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                CanonicalPost(
                    id=uuid4(),
                    creator_id=creator_b.id,
                    platform="x",
                    external_post_id="wrong-owner-publication",
                    published_at=NOW,
                    availability="available",
                    topology="original",
                    source_assessment_id=assessment.id,
                )
            )
            session.flush()

    linked = _post(session, creator_a.id, source_assessment_id=assessment.id)
    assert linked.source_assessment_id == assessment.id
    assert linked.version_match_state is None


def test_postgresql_candidate_source_returns_only_as_of_creator_and_exact_space_rows(
    session: Session,
) -> None:
    creator, other_creator = _creator(session), _creator(session)
    published_at = NOW - timedelta(hours=5)
    good_post = _post(session, creator.id, published_at=published_at)
    eligible_profile = _profile(
        session,
        good_post,
        features_as_of=published_at + timedelta(minutes=5),
    )
    # The latest profile is beyond the assessment cutoff; persistence must select the
    # earlier version visible at assessment time.
    _profile(session, good_post, features_as_of=NOW + timedelta(minutes=1))
    good_embedding = _embedding(
        session, good_post, generated_at=published_at + timedelta(minutes=6)
    )
    wrong_identity = EmbeddingIdentity(
        IDENTITY.model_id,
        "a" * 40,
        IDENTITY.dimensions,
        IDENTITY.preprocessing_version,
        IDENTITY.normalized,
        embedding_version="1",
    )
    _embedding(session, good_post, generated_at=NOW, identity=wrong_identity)

    _post(
        session,
        creator.id,
        published_at=NOW + timedelta(minutes=1),
    )
    other_post = _post(session, other_creator.id, published_at=published_at)
    _profile(
        session,
        other_post,
        features_as_of=published_at + timedelta(minutes=5),
    )
    _embedding(session, other_post, generated_at=published_at + timedelta(minutes=6))

    query = VectorCandidateQuery(
        creator_key=str(creator.id),
        as_of=NOW,
        embedding_identity=IDENTITY,
        query_embedding=(1.0, *([0.0] * 383)),
        limit=10,
    )
    row = session.execute(pgvector_candidate_statement(query)).one()
    post, profile, embedding = row
    candidate = comparable_candidate_from_records(post, profile, embedding)

    assert post.id == good_post.id
    assert profile.id == eligible_profile.id
    assert embedding.id == good_embedding.id
    assert candidate.creator_key == str(creator.id)
    assert candidate.available is True
    assert candidate.embedding_identity == IDENTITY
    assert candidate.embedding_observed_at == good_embedding.generated_at
