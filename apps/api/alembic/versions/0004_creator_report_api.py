"""Persist versioned creator declarations, processing choices and reports.

Revision ID: 0004_creator_report_api
Revises: 0003_private_auth_sessions
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_creator_report_api"
down_revision = "0003_private_auth_sessions"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    """Create append-only onboarding, source permission and report snapshot tables."""
    op.create_table(
        "creator_goal_revisions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("creator_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("goals_version", sa.String(length=100), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("niche", sa.String(length=255), nullable=False),
        sa.Column("intended_audience", sa.String(length=512), nullable=False),
        sa.Column("priority_outcomes", JSON_DOCUMENT, nullable=False),
        sa.Column("preferred_styles", JSON_DOCUMENT, nullable=False),
        sa.Column("language", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["creators.id"], name="fk_goal_revision_creator", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_creator_goal_revisions"),
        sa.UniqueConstraint("creator_id", "revision", name="creator_goal_revision_number"),
        sa.UniqueConstraint("id", "creator_id", name="creator_goal_revision_owner"),
        sa.CheckConstraint("revision > 0", name="ck_goal_revision_positive"),
        sa.CheckConstraint("length(trim(goals_version)) > 0", name="ck_goal_version_not_blank"),
    )
    op.create_index(
        "ix_creator_goal_revision_latest",
        "creator_goal_revisions",
        ["creator_id", "recorded_at", "revision"],
    )

    op.create_table(
        "creator_processing_permissions",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("creator_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_processing_permission_creator",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_creator_processing_permissions"),
        sa.UniqueConstraint("creator_id", "revision", name="processing_permission_revision"),
        sa.CheckConstraint("revision > 0", name="ck_permission_revision_positive"),
        sa.CheckConstraint(
            "source_kind = 'personal_history'", name="ck_permission_source_supported"
        ),
        sa.CheckConstraint(
            "length(trim(policy_version)) > 0", name="ck_permission_policy_not_blank"
        ),
    )
    op.create_index(
        "ix_creator_processing_permission_latest",
        "creator_processing_permissions",
        ["creator_id", "source_kind", "revision"],
    )

    op.create_table(
        "creator_report_snapshots",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("creator_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("goals_revision_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("goals_revision", sa.Integer(), nullable=False),
        sa.Column("goals_version", sa.String(length=100), nullable=False),
        sa.Column("evidence_version", sa.String(length=100), nullable=False),
        sa.Column("report_version", sa.String(length=100), nullable=False),
        sa.Column("baseline_version", sa.String(length=100), nullable=False),
        sa.Column("report_state", sa.String(length=32), nullable=False),
        sa.Column("report_snapshot", JSON_DOCUMENT, nullable=False),
        sa.Column("evidence_snapshot", JSON_DOCUMENT, nullable=False),
        sa.Column("permission_snapshot", JSON_DOCUMENT, nullable=False),
        sa.Column("freshness_snapshot", JSON_DOCUMENT, nullable=False),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["creators.id"], name="fk_report_snapshot_creator", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["goals_revision_id", "creator_id"],
            ["creator_goal_revisions.id", "creator_goal_revisions.creator_id"],
            name="fk_report_snapshot_goals_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_creator_report_snapshots"),
        sa.UniqueConstraint("creator_id", "idempotency_key", name="creator_report_idempotency"),
        sa.UniqueConstraint("id", "creator_id", name="creator_report_snapshot_owner"),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) > 0", name="ck_report_idempotency_not_blank"
        ),
        sa.CheckConstraint("length(request_fingerprint) = 64", name="ck_report_fingerprint_sha256"),
        sa.CheckConstraint(
            "report_state IN ('personal_and_niche', 'personal_only_partial', 'insufficient_evidence')",
            name="ck_report_state_valid",
        ),
    )
    op.create_index(
        "ix_creator_report_latest",
        "creator_report_snapshots",
        ["creator_id", "generated_at", "id"],
    )


def downgrade() -> None:
    """Remove report-first API persistence without touching imported creator history."""
    op.drop_index("ix_creator_report_latest", table_name="creator_report_snapshots")
    op.drop_table("creator_report_snapshots")
    op.drop_index(
        "ix_creator_processing_permission_latest", table_name="creator_processing_permissions"
    )
    op.drop_table("creator_processing_permissions")
    op.drop_index("ix_creator_goal_revision_latest", table_name="creator_goal_revisions")
    op.drop_table("creator_goal_revisions")
