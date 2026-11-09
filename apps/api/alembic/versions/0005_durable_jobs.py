"""Install Procrastinate 3.10.0 and permanent BipMe job receipts.

Revision ID: 0005_durable_jobs
Revises: 0004_creator_report_api
"""

from pathlib import Path

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005_durable_jobs"
down_revision = "0004_creator_report_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the pinned runner snapshot and BipMe submission receipt table."""
    bind = op.get_bind()
    schema = Path(__file__).resolve().parents[1] / "procrastinate_3_10_0_schema.sql"
    snapshot = schema.read_text(encoding="utf-8")
    if context.is_offline_mode():
        op.execute(snapshot)
    else:
        raw_connection = bind.connection.driver_connection
        with raw_connection.cursor() as cursor:
            cursor.execute(snapshot)
    op.create_unique_constraint(
        "x_connection_id_creator", "x_account_connections", ["id", "creator_id"]
    )
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("creator_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("handler_name", sa.String(100), nullable=False),
        sa.Column("arguments", JSONB(), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("runner_job_id", sa.BigInteger(), nullable=True),
        sa.Column("required_x_connection_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(
            ["creator_id"],
            ["creators.id"],
            name="fk_scheduled_jobs_creator_id_creators",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["required_x_connection_id", "creator_id"],
            ["x_account_connections.id", "x_account_connections.creator_id"],
            name="scheduled_job_required_x_owner_fk",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scheduled_jobs"),
        sa.UniqueConstraint("creator_id", "idempotency_key", name="scheduled_job_creator_key"),
        sa.UniqueConstraint("runner_job_id", name="scheduled_job_runner_id"),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) BETWEEN 1 AND 255",
            name=op.f("ck_scheduled_jobs_key_valid"),
        ),
        sa.CheckConstraint(
            "length(trim(handler_name)) BETWEEN 1 AND 100",
            name=op.f("ck_scheduled_jobs_handler_valid"),
        ),
        sa.CheckConstraint(
            "length(input_digest) = 64", name=op.f("ck_scheduled_jobs_digest_length")
        ),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 10", name=op.f("ck_scheduled_jobs_max_attempts_valid")
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('succeeded', 'failed', 'cancelled', 'needs_reconciliation', 'revoked')",
            name=op.f("ck_scheduled_jobs_outcome_valid"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(arguments) = 'object'", name=op.f("ck_scheduled_jobs_arguments_object")
        ),
    )
    op.create_index("ix_scheduled_jobs_due", "scheduled_jobs", ["scheduled_at", "outcome"])


def downgrade() -> None:
    """Remove COD-362 objects while preserving the existing pgvector extension."""
    op.drop_index("ix_scheduled_jobs_due", table_name="scheduled_jobs")
    op.drop_table("scheduled_jobs")
    op.drop_constraint("x_connection_id_creator", "x_account_connections", type_="unique")
    for function in (
        "procrastinate_defer_periodic_job_v2(character varying, character varying, character varying, character varying, integer, character varying, bigint, jsonb)",
        "procrastinate_defer_jobs_v1(procrastinate_job_to_defer_v1[])",
        "procrastinate_fetch_job_v2(character varying[], bigint)",
        "procrastinate_finish_job_v1(bigint, procrastinate_job_status, boolean)",
        "procrastinate_cancel_job_v1(bigint, boolean, boolean)",
        "procrastinate_retry_job_v1(bigint, timestamp with time zone, integer, character varying, character varying)",
        "procrastinate_retry_job_v2(bigint, timestamp with time zone, integer, character varying, character varying)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.drop_table("procrastinate_events")
    op.drop_table("procrastinate_periodic_defers")
    op.drop_table("procrastinate_jobs")
    op.drop_table("procrastinate_workers")
    for function in (
        "procrastinate_notify_queue_job_inserted_v1()",
        "procrastinate_notify_queue_abort_job_v1()",
        "procrastinate_trigger_function_status_events_insert_v1()",
        "procrastinate_trigger_function_status_events_update_v1()",
        "procrastinate_trigger_function_scheduled_events_v1()",
        "procrastinate_trigger_abort_requested_events_procedure_v1()",
        "procrastinate_unlink_periodic_defers_v1()",
        "procrastinate_register_worker_v1()",
        "procrastinate_unregister_worker_v1(bigint)",
        "procrastinate_update_heartbeat_v1(bigint)",
        "procrastinate_prune_stalled_workers_v1(double precision)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.execute("DROP TYPE procrastinate_job_to_defer_v1")
    op.execute("DROP TYPE procrastinate_job_event_type")
    op.execute("DROP TYPE procrastinate_job_status")
