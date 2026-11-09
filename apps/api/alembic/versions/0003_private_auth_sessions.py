"""Add revocable private sessions and single-use encrypted PKCE transactions.

Revision ID: 0003_private_auth_sessions
Revises: 0002_canonical_persistence
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_private_auth_sessions"
down_revision = "0002_canonical_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create private session and OAuth transaction records."""
    op.create_table(
        "creator_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("creator_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("auth_method", sa.String(length=24), nullable=False),
        sa.Column("x_identity_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_creator_sessions_creator_id_creators",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["x_identity_id", "creator_id"],
            ["creator_platform_identities.id", "creator_platform_identities.creator_id"],
            name="fk_creator_session_x_identity_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_creator_sessions"),
        sa.UniqueConstraint("token_hash", name="creator_session_token_hash_unique"),
        sa.CheckConstraint(
            "length(token_hash) = 64", name="ck_creator_sessions_session_token_hash_length"
        ),
        sa.CheckConstraint(
            "auth_method IN ('private_secret', 'x_oauth')",
            name="ck_creator_sessions_session_auth_method_valid",
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name="ck_creator_sessions_session_expiry_after_creation"
        ),
        sa.CheckConstraint(
            "(auth_method = 'private_secret' AND x_identity_id IS NULL) OR "
            "(auth_method = 'x_oauth' AND x_identity_id IS NOT NULL)",
            name="ck_creator_sessions_session_auth_method_identity_consistent",
        ),
    )
    op.create_index(
        "ix_creator_sessions_creator_expiry",
        "creator_sessions",
        ["creator_id", "expires_at"],
    )

    op.create_table(
        "oauth_authorization_transactions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("creator_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("browser_nonce_hash", sa.String(length=64), nullable=False),
        sa.Column("encrypted_verifier", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_version", sa.String(length=100), nullable=False),
        sa.Column("return_path", sa.String(length=2048), nullable=False),
        sa.Column("redirect_uri", sa.String(length=2048), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["creators.id"], name="fk_oauth_tx_creator", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_oauth_authorization_transactions"),
        sa.UniqueConstraint("state_hash", name="oauth_transaction_state_hash_unique"),
        sa.CheckConstraint(
            "length(state_hash) = 64",
            name="ck_oauth_authorization_transactions_oauth_state_hash_length",
        ),
        sa.CheckConstraint(
            "length(browser_nonce_hash) = 64",
            name="ck_oauth_authorization_transactions_oauth_browser_nonce_hash_length",
        ),
        sa.CheckConstraint(
            "length(trim(encryption_key_version)) > 0",
            name="ck_oauth_authorization_transactions_oauth_key_version_not_blank",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_oauth_authorization_transactions_oauth_expiry_after_creation",
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="ck_oauth_authorization_transactions_oauth_consumed_after_creation",
        ),
        sa.CheckConstraint(
            "substring(encrypted_verifier from 1 for 10) = decode('4249504d452d454e4301', 'hex')",
            name="ck_oauth_authorization_transactions_oauth_verifier_envelope_marker",
        ),
    )
    op.create_index(
        "ix_oauth_transactions_expiry", "oauth_authorization_transactions", ["expires_at"]
    )


def downgrade() -> None:
    """Remove auth rows and indexes without touching canonical identity records."""
    op.drop_index("ix_oauth_transactions_expiry", table_name="oauth_authorization_transactions")
    op.drop_table("oauth_authorization_transactions")
    op.drop_index("ix_creator_sessions_creator_expiry", table_name="creator_sessions")
    op.drop_table("creator_sessions")
