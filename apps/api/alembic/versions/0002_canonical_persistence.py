"""Create canonical creator/post persistence records after pgvector foundation.

Revision ID: 0002_canonical_persistence
Revises: 0001_enable_vector
"""

from alembic import op

revision = "0002_canonical_persistence"
down_revision = "0001_enable_vector"
branch_labels = None
depends_on = None

TABLE_SQL = (
    """CREATE TABLE creators (
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_creators PRIMARY KEY (id)
)""",
    """CREATE TABLE api_usage_ledger (
	id UUID NOT NULL, 
	creator_id UUID, 
	provider VARCHAR(64) NOT NULL, 
	operation VARCHAR(128) NOT NULL, 
	idempotency_key VARCHAR(255) NOT NULL, 
	request_metadata JSONB NOT NULL, 
	requested_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	usage_units INTEGER, 
	currency VARCHAR(3), 
	estimated_cost NUMERIC(20, 8), 
	actual_cost NUMERIC(20, 8), 
	reconciliation_state VARCHAR(24) DEFAULT 'pending' NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_api_usage_ledger PRIMARY KEY (id), 
	CONSTRAINT usage_provider_idempotency UNIQUE (provider, idempotency_key), 
	CONSTRAINT ck_api_usage_ledger_provider_not_blank CHECK (length(trim(provider)) > 0), 
	CONSTRAINT ck_api_usage_ledger_operation_not_blank CHECK (length(trim(operation)) > 0), 
	CONSTRAINT ck_api_usage_ledger_idempotency_key_not_blank CHECK (length(trim(idempotency_key)) > 0), 
	CONSTRAINT ck_api_usage_ledger_usage_units_non_negative CHECK (usage_units IS NULL OR usage_units >= 0), 
	CONSTRAINT ck_api_usage_ledger_estimated_cost_non_negative CHECK (estimated_cost IS NULL OR estimated_cost >= 0), 
	CONSTRAINT ck_api_usage_ledger_actual_cost_non_negative CHECK (actual_cost IS NULL OR actual_cost >= 0), 
	CONSTRAINT ck_api_usage_ledger_completion_after_request CHECK (completed_at IS NULL OR completed_at >= requested_at), 
	CONSTRAINT fk_api_usage_ledger_creator_id_creators FOREIGN KEY(creator_id) REFERENCES creators (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE creator_platform_identities (
	id UUID NOT NULL, 
	creator_id UUID NOT NULL, 
	platform VARCHAR(32) NOT NULL, 
	external_creator_id VARCHAR(255) NOT NULL, 
	handle VARCHAR(255), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_creator_platform_identities PRIMARY KEY (id), 
	CONSTRAINT identity_platform_external UNIQUE (platform, external_creator_id), 
	CONSTRAINT identity_id_creator UNIQUE (id, creator_id), 
	CONSTRAINT identity_id_creator_platform UNIQUE (id, creator_id, platform), 
	CONSTRAINT ck_creator_platform_identities_platform_not_blank CHECK (length(trim(platform)) > 0), 
	CONSTRAINT ck_creator_platform_identities_external_id_not_blank CHECK (length(trim(external_creator_id)) > 0), 
	CONSTRAINT fk_creator_platform_identities_creator_id_creators FOREIGN KEY(creator_id) REFERENCES creators (id) ON DELETE RESTRICT
)""",
    """CREATE TABLE draft_assessments (
	id UUID NOT NULL, 
	creator_id UUID NOT NULL, 
	assessment_key VARCHAR(255) NOT NULL, 
	assessed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	content_fingerprint VARCHAR(71) NOT NULL, 
	outlook_version VARCHAR(100) NOT NULL, 
	decision_snapshot JSONB NOT NULL, 
	accepted_hypothesis JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_draft_assessments PRIMARY KEY (id), 
	CONSTRAINT fk_assessment_creator FOREIGN KEY(creator_id) REFERENCES creators (id) ON DELETE RESTRICT, 
	CONSTRAINT assessment_id_creator UNIQUE (id, creator_id), 
	CONSTRAINT assessment_creator_key UNIQUE (creator_id, assessment_key), 
	CONSTRAINT ck_draft_assessments_assessment_key_not_blank CHECK (length(trim(assessment_key)) > 0), 
	CONSTRAINT ck_draft_assessments_fingerprint_length CHECK (length(trim(content_fingerprint)) = 71), 
	CONSTRAINT ck_draft_assessments_fingerprint_prefix CHECK (left(content_fingerprint, 7) = 'sha256:'), 
	CONSTRAINT ck_draft_assessments_outlook_version_not_blank CHECK (length(trim(outlook_version)) > 0), 
	CONSTRAINT ck_draft_assessments_snapshot_is_object CHECK (jsonb_typeof(decision_snapshot) = 'object'), 
	CONSTRAINT ck_draft_assessments_hypothesis_is_object CHECK (accepted_hypothesis IS NULL OR jsonb_typeof(accepted_hypothesis) = 'object')
)""",
    """CREATE TABLE canonical_posts (
	id UUID NOT NULL, 
	creator_id UUID NOT NULL, 
	platform VARCHAR(32) NOT NULL, 
	external_post_id VARCHAR(255) NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	availability VARCHAR(24) NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	topology VARCHAR(16) NOT NULL, 
	reply_to_post_id UUID, 
	reply_to_external_post_id VARCHAR(255), 
	quoted_external_post_id VARCHAR(255), 
	thread_id VARCHAR(255), 
	thread_role VARCHAR(24), 
	thread_metadata JSONB, 
	ingestion_key VARCHAR(255), 
	source_assessment_id UUID, 
	version_match_state VARCHAR(16), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_canonical_posts PRIMARY KEY (id), 
	CONSTRAINT fk_post_creator FOREIGN KEY(creator_id) REFERENCES creators (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_post_reply_same_creator FOREIGN KEY(reply_to_post_id, creator_id) REFERENCES canonical_posts (id, creator_id) ON DELETE RESTRICT, 
	CONSTRAINT fk_post_source_assessment_same_creator FOREIGN KEY(source_assessment_id, creator_id) REFERENCES draft_assessments (id, creator_id) ON DELETE RESTRICT, 
	CONSTRAINT post_platform_external UNIQUE (platform, external_post_id), 
	CONSTRAINT post_creator_ingestion_key UNIQUE (creator_id, ingestion_key), 
	CONSTRAINT post_id_creator UNIQUE (id, creator_id), 
	CONSTRAINT post_id_creator_published UNIQUE (id, creator_id, published_at), 
	CONSTRAINT post_assessment_single_attachment UNIQUE (source_assessment_id), 
	CONSTRAINT ck_canonical_posts_platform_not_blank CHECK (length(trim(platform)) > 0), 
	CONSTRAINT ck_canonical_posts_external_id_not_blank CHECK (length(trim(external_post_id)) > 0), 
	CONSTRAINT ck_canonical_posts_availability_valid CHECK (availability IN ('available', 'unavailable', 'deleted')), 
	CONSTRAINT ck_canonical_posts_topology_valid CHECK (topology IN ('original', 'reply', 'quote')), 
	CONSTRAINT ck_canonical_posts_deletion_timestamp_consistent CHECK ((availability = 'deleted' AND deleted_at IS NOT NULL) OR (availability <> 'deleted' AND deleted_at IS NULL)), 
	CONSTRAINT ck_canonical_posts_version_match_state_valid CHECK (version_match_state IS NULL OR version_match_state IN ('match', 'mismatch', 'unknown')), 
	CONSTRAINT ck_canonical_posts_version_match_requires_assessment CHECK (source_assessment_id IS NOT NULL OR version_match_state IS NULL), 
	CONSTRAINT ck_canonical_posts_reply_has_parent_reference CHECK (topology <> 'reply' OR reply_to_external_post_id IS NOT NULL OR reply_to_post_id IS NOT NULL), 
	CONSTRAINT ck_canonical_posts_quote_has_reference CHECK (topology <> 'quote' OR quoted_external_post_id IS NOT NULL)
)""",
    """CREATE TABLE x_account_connections (
	id UUID NOT NULL, 
	creator_id UUID NOT NULL, 
	creator_identity_id UUID NOT NULL, 
	platform VARCHAR(32) DEFAULT 'x' NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	scopes JSONB NOT NULL, 
	encrypted_access_token BYTEA, 
	encrypted_refresh_token BYTEA, 
	key_version VARCHAR(100) NOT NULL, 
	access_token_expires_at TIMESTAMP WITH TIME ZONE, 
	token_rotated_at TIMESTAMP WITH TIME ZONE, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	CONSTRAINT pk_x_account_connections PRIMARY KEY (id), 
	CONSTRAINT fk_x_connection_identity_owner FOREIGN KEY(creator_identity_id, creator_id, platform) REFERENCES creator_platform_identities (id, creator_id, platform) ON DELETE RESTRICT, 
	CONSTRAINT x_connection_identity_unique UNIQUE (creator_identity_id), 
	CONSTRAINT ck_x_account_connections_provider_is_x CHECK (platform = 'x'), 
	CONSTRAINT ck_x_account_connections_state_valid CHECK (state IN ('pending', 'connected', 'revoked', 'reauth_required')), 
	CONSTRAINT ck_x_account_connections_key_version_not_blank CHECK (length(trim(key_version)) > 0), 
	CONSTRAINT ck_x_account_connections_revocation_timestamp_consistent CHECK ((state = 'revoked' AND revoked_at IS NOT NULL) OR (state <> 'revoked' AND revoked_at IS NULL)), 
	CONSTRAINT ck_x_account_connections_connected_has_encrypted_access_token CHECK (state <> 'connected' OR encrypted_access_token IS NOT NULL), 
	CONSTRAINT ck_x_account_connections_revocation_clears_encrypted_tokens CHECK (state <> 'revoked' OR (encrypted_access_token IS NULL AND encrypted_refresh_token IS NULL)), 
	CONSTRAINT ck_x_account_connections_access_token_envelope_marker CHECK (encrypted_access_token IS NULL OR substring(encrypted_access_token from 1 for 10) = decode('4249504d452d454e4301', 'hex')), 
	CONSTRAINT ck_x_account_connections_refresh_token_envelope_marker CHECK (encrypted_refresh_token IS NULL OR substring(encrypted_refresh_token from 1 for 10) = decode('4249504d452d454e4301', 'hex'))
)""",
    """CREATE TABLE outcome_observations (
	id UUID NOT NULL, 
	post_id UUID NOT NULL, 
	creator_id UUID NOT NULL, 
	published_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	metric_name VARCHAR(100) NOT NULL, 
	metric_definition VARCHAR(255) NOT NULL, 
	metric_unit VARCHAR(64) NOT NULL, 
	metric_value NUMERIC(30, 10), 
	state VARCHAR(16) NOT NULL, 
	window_kind VARCHAR(24) NOT NULL, 
	window_key VARCHAR(100) NOT NULL, 
	observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	idempotency_key VARCHAR(255) NOT NULL, 
	provenance JSONB NOT NULL, 
	CONSTRAINT pk_outcome_observations PRIMARY KEY (id), 
	CONSTRAINT fk_outcome_post_creator_publication FOREIGN KEY(post_id, creator_id, published_at) REFERENCES canonical_posts (id, creator_id, published_at) ON DELETE RESTRICT, 
	CONSTRAINT outcome_post_metric_window_observed UNIQUE (post_id, metric_name, metric_definition, metric_unit, window_kind, window_key, observed_at), 
	CONSTRAINT outcome_creator_idempotency UNIQUE (creator_id, idempotency_key), 
	CONSTRAINT ck_outcome_observations_metric_name_not_blank CHECK (length(trim(metric_name)) > 0), 
	CONSTRAINT ck_outcome_observations_metric_definition_not_blank CHECK (length(trim(metric_definition)) > 0), 
	CONSTRAINT ck_outcome_observations_metric_unit_not_blank CHECK (length(trim(metric_unit)) > 0), 
	CONSTRAINT ck_outcome_observations_window_kind_valid CHECK (window_kind IN ('mature_cumulative', 'age_aligned')), 
	CONSTRAINT ck_outcome_observations_window_key_not_blank CHECK (length(trim(window_key)) > 0), 
	CONSTRAINT ck_outcome_observations_idempotency_key_not_blank CHECK (length(trim(idempotency_key)) > 0), 
	CONSTRAINT ck_outcome_observations_state_valid CHECK (state IN ('observed', 'missing', 'invalid')), 
	CONSTRAINT ck_outcome_observations_value_state_consistent CHECK ((state = 'observed' AND metric_value IS NOT NULL) OR (state IN ('missing', 'invalid') AND metric_value IS NULL)), 
	CONSTRAINT ck_outcome_observations_metric_non_negative CHECK (metric_value IS NULL OR metric_value >= 0), 
	CONSTRAINT ck_outcome_observations_outcome_not_before_publication CHECK (observed_at >= published_at)
)""",
    """CREATE TABLE post_embeddings (
	id UUID NOT NULL, 
	post_id UUID NOT NULL, 
	creator_id UUID NOT NULL, 
	model_id VARCHAR(255) NOT NULL, 
	model_revision VARCHAR(40) NOT NULL, 
	dimensions INTEGER NOT NULL, 
	preprocessing_version VARCHAR(100) NOT NULL, 
	normalized BOOLEAN NOT NULL, 
	embedding_version VARCHAR(100) NOT NULL, 
	embedding VECTOR(384) NOT NULL, 
	generated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	CONSTRAINT pk_post_embeddings PRIMARY KEY (id), 
	CONSTRAINT fk_embedding_post_same_creator FOREIGN KEY(post_id, creator_id) REFERENCES canonical_posts (id, creator_id) ON DELETE RESTRICT, 
	CONSTRAINT embedding_post_full_identity UNIQUE (post_id, model_id, model_revision, dimensions, preprocessing_version, normalized, embedding_version), 
	CONSTRAINT ck_post_embeddings_initial_embedding_dimension CHECK (dimensions = 384), 
	CONSTRAINT ck_post_embeddings_normalization_boolean CHECK (normalized IN (true, false)), 
	CONSTRAINT ck_post_embeddings_model_id_not_blank CHECK (length(trim(model_id)) > 0), 
	CONSTRAINT ck_post_embeddings_model_revision_immutable_sha CHECK (model_revision ~ '^[0-9a-f]{40}$'), 
	CONSTRAINT ck_post_embeddings_preprocessing_not_blank CHECK (length(trim(preprocessing_version)) > 0), 
	CONSTRAINT ck_post_embeddings_embedding_version_not_blank CHECK (length(trim(embedding_version)) > 0)
)""",
    """CREATE TABLE post_profiles (
	id UUID NOT NULL, 
	post_id UUID NOT NULL, 
	creator_id UUID NOT NULL, 
	profile_version VARCHAR(100) NOT NULL, 
	features_as_of TIMESTAMP WITH TIME ZONE NOT NULL, 
	input_observed_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	creator_context_observed_at TIMESTAMP WITH TIME ZONE, 
	features JSONB NOT NULL, 
	CONSTRAINT pk_post_profiles PRIMARY KEY (id), 
	CONSTRAINT fk_profile_post_same_creator FOREIGN KEY(post_id, creator_id) REFERENCES canonical_posts (id, creator_id) ON DELETE RESTRICT, 
	CONSTRAINT profile_post_version_cutoff UNIQUE (post_id, profile_version, features_as_of), 
	CONSTRAINT ck_post_profiles_profile_version_not_blank CHECK (length(trim(profile_version)) > 0), 
	CONSTRAINT ck_post_profiles_profile_features_is_object CHECK (jsonb_typeof(features) = 'object'), 
	CONSTRAINT ck_post_profiles_profile_context_not_after_features_cutoff CHECK (creator_context_observed_at IS NULL OR creator_context_observed_at <= features_as_of)
)""",
)

INDEX_SQL = (
    """CREATE INDEX ix_api_usage_provider_requested ON api_usage_ledger (provider, requested_at)""",
    """CREATE INDEX ix_posts_creator_availability_published ON canonical_posts (creator_id, availability, published_at)""",
    """CREATE INDEX ix_posts_creator_published ON canonical_posts (creator_id, published_at)""",
    """CREATE INDEX ix_outcomes_creator_metric_window ON outcome_observations (creator_id, metric_name, window_kind, window_key)""",
    """CREATE INDEX ix_outcomes_post_observed ON outcome_observations (post_id, observed_at)""",
    """CREATE INDEX ix_embeddings_creator_post ON post_embeddings (creator_id, post_id)""",
    """CREATE INDEX ix_embeddings_e5_v1_cosine ON post_embeddings USING hnsw (embedding vector_cosine_ops) WHERE model_id = 'intfloat/multilingual-e5-small' AND model_revision = 'fd1525a9fd15316a2d503bf26ab031a61d056e98' AND dimensions = 384 AND preprocessing_version = 'e5-prefix-strip-v1' AND normalized = true AND embedding_version = '1'""",
    """CREATE INDEX ix_profiles_creator_version_cutoff ON post_profiles (creator_id, profile_version, features_as_of)""",
)


def upgrade() -> None:
    """Create the initial versioned persistence schema and its indexes."""
    for statement in TABLE_SQL:
        op.execute(statement)
    for statement in INDEX_SQL:
        op.execute(statement)
    op.execute(
        """CREATE FUNCTION prevent_draft_assessment_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'draft assessment snapshots are immutable';
        END;
        $$ LANGUAGE plpgsql"""
    )
    op.execute(
        """CREATE TRIGGER trg_draft_assessments_immutable
        BEFORE UPDATE ON draft_assessments
        FOR EACH ROW EXECUTE FUNCTION prevent_draft_assessment_update()"""
    )


def downgrade() -> None:
    """Drop COD-345 tables without removing the pgvector extension."""
    op.execute("DROP TRIGGER trg_draft_assessments_immutable ON draft_assessments")
    op.execute("DROP FUNCTION prevent_draft_assessment_update()")
    for table_name in (
        "api_usage_ledger",
        "outcome_observations",
        "post_embeddings",
        "post_profiles",
        "canonical_posts",
        "x_account_connections",
        "draft_assessments",
        "creator_platform_identities",
        "creators",
    ):
        op.drop_table(table_name)
