"""Persist bounded creator-history import state and normalized source fields."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_creator_history_import"
down_revision = "0005_durable_jobs"
branch_labels = None
depends_on = None

JSON_DOCUMENT = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    op.add_column("canonical_posts", sa.Column("text", sa.String(length=10000), nullable=True))
    op.add_column("canonical_posts", sa.Column("media_present", sa.Boolean(), nullable=True))
    op.add_column(
        "canonical_posts",
        sa.Column("source", sa.String(length=100), nullable=False, server_default="unknown"),
    )
    op.add_column(
        "canonical_posts", sa.Column("source_endpoint", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "canonical_posts",
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "canonical_posts",
        sa.Column("provenance", JSON_DOCUMENT, nullable=False, server_default="{}"),
    )
    op.create_table(
        "creator_history_imports",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("creator_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("import_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("requested_posts", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pages_read", sa.Integer(), nullable=False),
        sa.Column("imported_posts", sa.Integer(), nullable=False),
        sa.Column("next_page_available", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("provenance", JSON_DOCUMENT, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["creators.id"], ondelete="CASCADE", name="fk_history_import_creator"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("creator_id", "import_id", name="history_import_creator_key"),
        sa.CheckConstraint("length(trim(import_id)) > 0", name="history_import_id_not_blank"),
        sa.CheckConstraint(
            "status IN ('running', 'complete', 'partial', 'unavailable')",
            name="history_import_status_valid",
        ),
        sa.CheckConstraint("requested_posts > 0", name="history_import_requested_positive"),
        sa.CheckConstraint(
            "pages_read >= 0 AND imported_posts >= 0", name="history_import_counts_valid"
        ),
    )
    op.create_index(
        "ix_history_import_creator_started", "creator_history_imports", ["creator_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_history_import_creator_started", table_name="creator_history_imports")
    op.drop_table("creator_history_imports")
    for name in (
        "provenance",
        "source_observed_at",
        "source_endpoint",
        "source",
        "media_present",
        "text",
    ):
        op.drop_column("canonical_posts", name)
