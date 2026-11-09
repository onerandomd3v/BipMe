"""Canonical, provider-neutral persistence records for the private V1 workflow.

Raw provider payloads and plaintext credentials are deliberately not represented here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    and_,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bipme.persistence.base import Base, EncryptedTokenEnvelope, UTCDateTime

JsonObject = dict[str, Any]
JSON_DOCUMENT = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


class TimestampMixin:
    """UTC-aware creation and update timestamps for mutable records."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP"),
    )


class Creator(TimestampMixin, Base):
    """Internal provider-neutral owner of platform identities and posts."""

    __tablename__ = "creators"
    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)


class CreatorGoalRevision(Base):
    """Append-only versioned creator declarations used by report snapshots."""

    __tablename__ = "creator_goal_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["creator_id"], ["creators.id"], ondelete="CASCADE", name="fk_goal_revision_creator"
        ),
        UniqueConstraint("creator_id", "revision", name="creator_goal_revision_number"),
        UniqueConstraint("id", "creator_id", name="creator_goal_revision_owner"),
        CheckConstraint("revision > 0", name="goal_revision_positive"),
        CheckConstraint("length(trim(goals_version)) > 0", name="goal_version_not_blank"),
        Index("ix_creator_goal_revision_latest", "creator_id", "recorded_at", "revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    goals_version: Mapped[str] = mapped_column(String(100), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    niche: Mapped[str] = mapped_column(String(255), nullable=False)
    intended_audience: Mapped[str] = mapped_column(String(512), nullable=False)
    priority_outcomes: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    preferred_styles: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False)
    language: Mapped[str | None] = mapped_column(String(64))


class CreatorProcessingPermission(Base):
    """Append-only opt-in/revocation for local deterministic personal-history use."""

    __tablename__ = "creator_processing_permissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            ondelete="CASCADE",
            name="fk_processing_permission_creator",
        ),
        UniqueConstraint("creator_id", "revision", name="processing_permission_revision"),
        CheckConstraint("revision > 0", name="permission_revision_positive"),
        CheckConstraint("source_kind = 'personal_history'", name="permission_source_supported"),
        CheckConstraint("length(trim(policy_version)) > 0", name="permission_policy_not_blank"),
        Index("ix_creator_processing_permission_latest", "creator_id", "source_kind", "revision"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class CreatorReportSnapshot(Base):
    """Immutable deterministic report, evidence, source and permission snapshot."""

    __tablename__ = "creator_report_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["creator_id"], ["creators.id"], ondelete="CASCADE", name="fk_report_snapshot_creator"
        ),
        ForeignKeyConstraint(
            ["goals_revision_id", "creator_id"],
            ["creator_goal_revisions.id", "creator_goal_revisions.creator_id"],
            ondelete="RESTRICT",
            name="fk_report_snapshot_goals_owner",
        ),
        UniqueConstraint("creator_id", "idempotency_key", name="creator_report_idempotency"),
        UniqueConstraint("id", "creator_id", name="creator_report_snapshot_owner"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="report_idempotency_not_blank"),
        CheckConstraint("length(request_fingerprint) = 64", name="report_fingerprint_sha256"),
        CheckConstraint(
            "report_state IN ('personal_and_niche', 'personal_only_partial', 'insufficient_evidence')",
            name="report_state_valid",
        ),
        Index("ix_creator_report_latest", "creator_id", "generated_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    goals_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    as_of: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    goals_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    goals_version: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence_version: Mapped[str] = mapped_column(String(100), nullable=False)
    report_version: Mapped[str] = mapped_column(String(100), nullable=False)
    baseline_version: Mapped[str] = mapped_column(String(100), nullable=False)
    report_state: Mapped[str] = mapped_column(String(32), nullable=False)
    report_snapshot: Mapped[JsonObject] = mapped_column(JSON_DOCUMENT, nullable=False)
    evidence_snapshot: Mapped[JsonObject] = mapped_column(JSON_DOCUMENT, nullable=False)
    permission_snapshot: Mapped[JsonObject] = mapped_column(JSON_DOCUMENT, nullable=False)
    freshness_snapshot: Mapped[JsonObject] = mapped_column(JSON_DOCUMENT, nullable=False)


class CreatorPlatformIdentity(TimestampMixin, Base):
    """External provider identity mapped to exactly one canonical creator."""

    __tablename__ = "creator_platform_identities"
    __table_args__ = (
        UniqueConstraint("platform", "external_creator_id", name="identity_platform_external"),
        UniqueConstraint("id", "creator_id", name="identity_id_creator"),
        UniqueConstraint("id", "creator_id", "platform", name="identity_id_creator_platform"),
        CheckConstraint("length(trim(platform)) > 0", name="platform_not_blank"),
        CheckConstraint("length(trim(external_creator_id)) > 0", name="external_id_not_blank"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("creators.id", ondelete="RESTRICT"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    external_creator_id: Mapped[str] = mapped_column(String(255), nullable=False)
    handle: Mapped[str | None] = mapped_column(String(255))


class XAccountConnection(TimestampMixin, Base):
    """X authorization state; token bytes must be application-encrypted ciphertext."""

    __tablename__ = "x_account_connections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["creator_identity_id", "creator_id", "platform"],
            [
                "creator_platform_identities.id",
                "creator_platform_identities.creator_id",
                "creator_platform_identities.platform",
            ],
            ondelete="RESTRICT",
            name="fk_x_connection_identity_owner",
        ),
        UniqueConstraint("creator_identity_id", name="x_connection_identity_unique"),
        CheckConstraint("platform = 'x'", name="provider_is_x"),
        CheckConstraint(
            "state IN ('pending', 'connected', 'revoked', 'reauth_required')",
            name="state_valid",
        ),
        CheckConstraint("length(trim(key_version)) > 0", name="key_version_not_blank"),
        CheckConstraint(
            "(state = 'revoked' AND revoked_at IS NOT NULL) OR "
            "(state <> 'revoked' AND revoked_at IS NULL)",
            name="revocation_timestamp_consistent",
        ),
        CheckConstraint(
            "state <> 'connected' OR encrypted_access_token IS NOT NULL",
            name="connected_has_encrypted_access_token",
        ),
        CheckConstraint(
            "state <> 'revoked' OR "
            "(encrypted_access_token IS NULL AND encrypted_refresh_token IS NULL)",
            name="revocation_clears_encrypted_tokens",
        ),
        CheckConstraint(
            "encrypted_access_token IS NULL OR substring(encrypted_access_token from 1 for 10) "
            "= decode('4249504d452d454e4301', 'hex')",
            name="access_token_envelope_marker",
        ),
        CheckConstraint(
            "encrypted_refresh_token IS NULL OR substring(encrypted_refresh_token from 1 for 10) "
            "= decode('4249504d452d454e4301', 'hex')",
            name="refresh_token_envelope_marker",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    creator_identity_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    platform: Mapped[str] = mapped_column(
        String(32), nullable=False, default="x", server_default="x"
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    scopes: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, nullable=False, default=list)
    encrypted_access_token: Mapped[bytes | None] = mapped_column(EncryptedTokenEnvelope())
    encrypted_refresh_token: Mapped[bytes | None] = mapped_column(EncryptedTokenEnvelope())
    key_version: Mapped[str] = mapped_column(String(100), nullable=False)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    token_rotated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class CreatorSession(Base):
    """Opaque, revocable server-side session for the one configured BipMe creator."""

    __tablename__ = "creator_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["x_identity_id", "creator_id"],
            ["creator_platform_identities.id", "creator_platform_identities.creator_id"],
            ondelete="RESTRICT",
            name="fk_creator_session_x_identity_owner",
        ),
        UniqueConstraint("token_hash", name="creator_session_token_hash_unique"),
        CheckConstraint("length(token_hash) = 64", name="session_token_hash_length"),
        CheckConstraint(
            "auth_method IN ('private_secret', 'x_oauth')", name="session_auth_method_valid"
        ),
        CheckConstraint("expires_at > created_at", name="session_expiry_after_creation"),
        CheckConstraint(
            "(auth_method = 'private_secret' AND x_identity_id IS NULL) OR "
            "(auth_method = 'x_oauth' AND x_identity_id IS NOT NULL)",
            name="session_auth_method_identity_consistent",
        ),
        Index("ix_creator_sessions_creator_expiry", "creator_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("creators.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    auth_method: Mapped[str] = mapped_column(String(24), nullable=False)
    x_identity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class OAuthAuthorizationTransaction(Base):
    """Short-lived single-use PKCE transaction; secrets are stored encrypted or hashed."""

    __tablename__ = "oauth_authorization_transactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["creator_id"], ["creators.id"], ondelete="CASCADE", name="fk_oauth_tx_creator"
        ),
        UniqueConstraint("state_hash", name="oauth_transaction_state_hash_unique"),
        CheckConstraint("length(state_hash) = 64", name="oauth_state_hash_length"),
        CheckConstraint("length(browser_nonce_hash) = 64", name="oauth_browser_nonce_hash_length"),
        CheckConstraint(
            "length(trim(encryption_key_version)) > 0", name="oauth_key_version_not_blank"
        ),
        CheckConstraint("expires_at > created_at", name="oauth_expiry_after_creation"),
        CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at", name="oauth_consumed_after_creation"
        ),
        CheckConstraint(
            "substring(encrypted_verifier from 1 for 10) = decode('4249504d452d454e4301', 'hex')",
            name="oauth_verifier_envelope_marker",
        ),
        Index("ix_oauth_transactions_expiry", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    browser_nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_verifier: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(100), nullable=False)
    return_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class DraftAssessment(Base):
    """Immutable versioned Outlook snapshot, with an optional accepted hypothesis."""

    __tablename__ = "draft_assessments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["creator_id"], ["creators.id"], ondelete="RESTRICT", name="fk_assessment_creator"
        ),
        UniqueConstraint("id", "creator_id", name="assessment_id_creator"),
        UniqueConstraint("creator_id", "assessment_key", name="assessment_creator_key"),
        CheckConstraint("length(trim(assessment_key)) > 0", name="assessment_key_not_blank"),
        CheckConstraint("length(trim(content_fingerprint)) = 71", name="fingerprint_length"),
        CheckConstraint("left(content_fingerprint, 7) = 'sha256:'", name="fingerprint_prefix"),
        CheckConstraint("length(trim(outlook_version)) > 0", name="outlook_version_not_blank"),
        CheckConstraint("jsonb_typeof(decision_snapshot) = 'object'", name="snapshot_is_object"),
        CheckConstraint(
            "accepted_hypothesis IS NULL OR jsonb_typeof(accepted_hypothesis) = 'object'",
            name="hypothesis_is_object",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    assessment_key: Mapped[str] = mapped_column(String(255), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String(71), nullable=False)
    outlook_version: Mapped[str] = mapped_column(String(100), nullable=False)
    decision_snapshot: Mapped[JsonObject] = mapped_column(JSON_DOCUMENT, nullable=False)
    accepted_hypothesis: Mapped[JsonObject | None] = mapped_column(JSON_DOCUMENT)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class CanonicalPost(TimestampMixin, Base):
    """Minimal canonical platform post record, without copied provider payloads."""

    __tablename__ = "canonical_posts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["creator_id"], ["creators.id"], ondelete="RESTRICT", name="fk_post_creator"
        ),
        ForeignKeyConstraint(
            ["reply_to_post_id", "creator_id"],
            ["canonical_posts.id", "canonical_posts.creator_id"],
            ondelete="RESTRICT",
            name="fk_post_reply_same_creator",
        ),
        ForeignKeyConstraint(
            ["source_assessment_id", "creator_id"],
            ["draft_assessments.id", "draft_assessments.creator_id"],
            ondelete="RESTRICT",
            name="fk_post_source_assessment_same_creator",
        ),
        UniqueConstraint("platform", "external_post_id", name="post_platform_external"),
        UniqueConstraint("creator_id", "ingestion_key", name="post_creator_ingestion_key"),
        UniqueConstraint("id", "creator_id", name="post_id_creator"),
        UniqueConstraint("id", "creator_id", "published_at", name="post_id_creator_published"),
        UniqueConstraint("source_assessment_id", name="post_assessment_single_attachment"),
        CheckConstraint("length(trim(platform)) > 0", name="platform_not_blank"),
        CheckConstraint("length(trim(external_post_id)) > 0", name="external_id_not_blank"),
        CheckConstraint(
            "availability IN ('available', 'unavailable', 'deleted')", name="availability_valid"
        ),
        CheckConstraint("topology IN ('original', 'reply', 'quote')", name="topology_valid"),
        CheckConstraint(
            "(availability = 'deleted' AND deleted_at IS NOT NULL) OR "
            "(availability <> 'deleted' AND deleted_at IS NULL)",
            name="deletion_timestamp_consistent",
        ),
        CheckConstraint(
            "version_match_state IS NULL OR version_match_state IN ('match', 'mismatch', 'unknown')",
            name="version_match_state_valid",
        ),
        CheckConstraint(
            "source_assessment_id IS NOT NULL OR version_match_state IS NULL",
            name="version_match_requires_assessment",
        ),
        CheckConstraint(
            "topology <> 'reply' OR reply_to_external_post_id IS NOT NULL OR reply_to_post_id IS NOT NULL",
            name="reply_has_parent_reference",
        ),
        CheckConstraint(
            "topology <> 'quote' OR quoted_external_post_id IS NOT NULL",
            name="quote_has_reference",
        ),
        Index("ix_posts_creator_published", "creator_id", "published_at"),
        Index(
            "ix_posts_creator_availability_published", "creator_id", "availability", "published_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    external_post_id: Mapped[str] = mapped_column(String(255), nullable=False)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    availability: Mapped[str] = mapped_column(String(24), nullable=False, default="available")
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    topology: Mapped[str] = mapped_column(String(16), nullable=False, default="original")
    reply_to_post_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    reply_to_external_post_id: Mapped[str | None] = mapped_column(String(255))
    quoted_external_post_id: Mapped[str | None] = mapped_column(String(255))
    thread_id: Mapped[str | None] = mapped_column(String(255))
    thread_role: Mapped[str | None] = mapped_column(String(24))
    thread_metadata: Mapped[JsonObject | None] = mapped_column(JSON_DOCUMENT)
    ingestion_key: Mapped[str | None] = mapped_column(String(255))
    source_assessment_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    version_match_state: Mapped[str | None] = mapped_column(String(16))
    text: Mapped[str | None] = mapped_column(String(10000))
    media_present: Mapped[bool | None] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="unknown")
    source_endpoint: Mapped[str | None] = mapped_column(String(255))
    source_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    provenance: Mapped[JsonObject] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)


class CreatorHistoryImport(TimestampMixin, Base):
    """Creator-scoped state for a bounded, repeatable official-history import."""

    __tablename__ = "creator_history_imports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["creator_id"], ["creators.id"], ondelete="CASCADE", name="fk_history_import_creator"
        ),
        UniqueConstraint("creator_id", "import_id", name="history_import_creator_key"),
        CheckConstraint("length(trim(import_id)) > 0", name="history_import_id_not_blank"),
        CheckConstraint(
            "status IN ('running', 'complete', 'partial', 'unavailable')",
            name="history_import_status_valid",
        ),
        CheckConstraint("requested_posts > 0", name="history_import_requested_positive"),
        CheckConstraint(
            "pages_read >= 0 AND imported_posts >= 0", name="history_import_counts_valid"
        ),
        Index("ix_history_import_creator_started", "creator_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    import_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    requested_posts: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    pages_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_posts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_page_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(
        String(100), nullable=False, default="x_creator_authorized_history"
    )
    provenance: Mapped[JsonObject] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)


class PostProfileRecord(Base):
    """Versioned descriptive COD-350 feature snapshot; contains no outcome fields."""

    __tablename__ = "post_profiles"
    __table_args__ = (
        ForeignKeyConstraint(
            ["post_id", "creator_id"],
            ["canonical_posts.id", "canonical_posts.creator_id"],
            ondelete="RESTRICT",
            name="fk_profile_post_same_creator",
        ),
        UniqueConstraint(
            "post_id", "profile_version", "features_as_of", name="profile_post_version_cutoff"
        ),
        CheckConstraint("length(trim(profile_version)) > 0", name="profile_version_not_blank"),
        CheckConstraint("jsonb_typeof(features) = 'object'", name="profile_features_is_object"),
        CheckConstraint(
            "creator_context_observed_at IS NULL OR creator_context_observed_at <= features_as_of",
            name="profile_context_not_after_features_cutoff",
        ),
        Index(
            "ix_profiles_creator_version_cutoff", "creator_id", "profile_version", "features_as_of"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    post_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    creator_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(100), nullable=False)
    features_as_of: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    input_observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    creator_context_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    features: Mapped[JsonObject] = mapped_column(JSON_DOCUMENT, nullable=False)


class PostEmbedding(Base):
    """Immutable vector plus its complete COD-351 vector-space identity."""

    __tablename__ = "post_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["post_id", "creator_id"],
            ["canonical_posts.id", "canonical_posts.creator_id"],
            ondelete="RESTRICT",
            name="fk_embedding_post_same_creator",
        ),
        UniqueConstraint(
            "post_id",
            "model_id",
            "model_revision",
            "dimensions",
            "preprocessing_version",
            "normalized",
            "embedding_version",
            name="embedding_post_full_identity",
        ),
        CheckConstraint("dimensions = 384", name="initial_embedding_dimension"),
        CheckConstraint("normalized IN (true, false)", name="normalization_boolean"),
        CheckConstraint("length(trim(model_id)) > 0", name="model_id_not_blank"),
        CheckConstraint("model_revision ~ '^[0-9a-f]{40}$'", name="model_revision_immutable_sha"),
        CheckConstraint("length(trim(preprocessing_version)) > 0", name="preprocessing_not_blank"),
        CheckConstraint("length(trim(embedding_version)) > 0", name="embedding_version_not_blank"),
        Index("ix_embeddings_creator_post", "creator_id", "post_id"),
        Index(
            "ix_embeddings_e5_v1_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_where=and_(
                text("model_id = 'intfloat/multilingual-e5-small'"),
                text("model_revision = 'fd1525a9fd15316a2d503bf26ab031a61d056e98'"),
                text("dimensions = 384"),
                text("preprocessing_version = 'e5-prefix-strip-v1'"),
                text("normalized = true"),
                text("embedding_version = '1'"),
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    post_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    creator_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_revision: Mapped[str] = mapped_column(String(40), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    preprocessing_version: Mapped[str] = mapped_column(String(100), nullable=False)
    normalized: Mapped[bool] = mapped_column(Boolean, nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class OutcomeObservationRecord(Base):
    """Append-only metric observation with exact definition/window provenance."""

    __tablename__ = "outcome_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["post_id", "creator_id", "published_at"],
            ["canonical_posts.id", "canonical_posts.creator_id", "canonical_posts.published_at"],
            ondelete="RESTRICT",
            name="fk_outcome_post_creator_publication",
        ),
        UniqueConstraint(
            "post_id",
            "metric_name",
            "metric_definition",
            "metric_unit",
            "window_kind",
            "window_key",
            "observed_at",
            name="outcome_post_metric_window_observed",
        ),
        UniqueConstraint("creator_id", "idempotency_key", name="outcome_creator_idempotency"),
        CheckConstraint("length(trim(metric_name)) > 0", name="metric_name_not_blank"),
        CheckConstraint("length(trim(metric_definition)) > 0", name="metric_definition_not_blank"),
        CheckConstraint("length(trim(metric_unit)) > 0", name="metric_unit_not_blank"),
        CheckConstraint(
            "window_kind IN ('mature_cumulative', 'age_aligned')", name="window_kind_valid"
        ),
        CheckConstraint("length(trim(window_key)) > 0", name="window_key_not_blank"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key_not_blank"),
        CheckConstraint("state IN ('observed', 'missing', 'invalid')", name="state_valid"),
        CheckConstraint(
            "(state = 'observed' AND metric_value IS NOT NULL) OR "
            "(state IN ('missing', 'invalid') AND metric_value IS NULL)",
            name="value_state_consistent",
        ),
        CheckConstraint("metric_value IS NULL OR metric_value >= 0", name="metric_non_negative"),
        CheckConstraint("observed_at >= published_at", name="outcome_not_before_publication"),
        Index(
            "ix_outcomes_creator_metric_window",
            "creator_id",
            "metric_name",
            "window_kind",
            "window_key",
        ),
        Index("ix_outcomes_post_observed", "post_id", "observed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    post_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    creator_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_definition: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_unit: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_value: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    window_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    window_key: Mapped[str] = mapped_column(String(100), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    provenance: Mapped[JsonObject] = mapped_column(JSON_DOCUMENT, nullable=False, default=dict)


class APIUsageLedger(TimestampMixin, Base):
    """Idempotent provider-operation accounting with sanitized request metadata."""

    __tablename__ = "api_usage_ledger"
    __table_args__ = (
        UniqueConstraint("provider", "idempotency_key", name="usage_provider_idempotency"),
        CheckConstraint("length(trim(provider)) > 0", name="provider_not_blank"),
        CheckConstraint("length(trim(operation)) > 0", name="operation_not_blank"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key_not_blank"),
        CheckConstraint("usage_units IS NULL OR usage_units >= 0", name="usage_units_non_negative"),
        CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0", name="estimated_cost_non_negative"
        ),
        CheckConstraint("actual_cost IS NULL OR actual_cost >= 0", name="actual_cost_non_negative"),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= requested_at", name="completion_after_request"
        ),
        Index("ix_api_usage_provider_requested", "provider", "requested_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    creator_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("creators.id", ondelete="RESTRICT")
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_metadata: Mapped[JsonObject] = mapped_column(
        JSON_DOCUMENT, nullable=False, default=dict
    )
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    usage_units: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    reconciliation_state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending", server_default="pending"
    )
