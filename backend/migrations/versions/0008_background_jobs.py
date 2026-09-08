"""Add durable jobs, job events, login attempt tracking and report links."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008_background_jobs"
down_revision = "0007_password_lifecycle"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    return column in {item["name"] for item in sa.inspect(bind).get_columns(table)}


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _has_table("background_jobs"):
        op.create_table(
            "background_jobs",
            sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=120), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "ix_background_jobs_status_available" not in {x["name"] for x in sa.inspect(op.get_bind()).get_indexes("background_jobs")}:
        op.create_index("ix_background_jobs_status_available", "background_jobs", ["status", "available_at"])
    if "ix_background_jobs_owner_created" not in {x["name"] for x in sa.inspect(op.get_bind()).get_indexes("background_jobs")}:
        op.create_index("ix_background_jobs_owner_created", "background_jobs", ["owner_id", "created_at"])
    if not _has_table("job_events"):
        op.create_table(
            "job_events",
            sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_id", sa.String(length=36), sa.ForeignKey("background_jobs.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "sequence", name="uq_job_events_job_sequence"),
        )
    if "ix_job_events_job_id" not in {x["name"] for x in sa.inspect(op.get_bind()).get_indexes("job_events")}:
        op.create_index("ix_job_events_job_id", "job_events", ["job_id"])
    if not _has_table("login_attempts"):
        op.create_table(
            "login_attempts",
            sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("username_key", sa.String(length=160), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username_key", "ip_address", name="uq_login_attempts_username_ip"),
        )
    if "ix_login_attempts_username" not in {x["name"] for x in sa.inspect(op.get_bind()).get_indexes("login_attempts")}:
        op.create_index("ix_login_attempts_username", "login_attempts", ["username_key"])
    if not _has_column("capability_tasks", "job_id"):
        op.add_column("capability_tasks", sa.Column("job_id", sa.String(length=36), nullable=True))
        op.create_index("ix_capability_tasks_job_id", "capability_tasks", ["job_id"])
    with op.batch_alter_table("capability_tasks", recreate="always") as batch:
        if _has_column("capability_tasks", "job_id"):
            batch.create_foreign_key("fk_capability_tasks_job_id", "background_jobs", ["job_id"], ["id"])
    if not _has_column("report_exports", "job_id"):
        op.add_column("report_exports", sa.Column("job_id", sa.String(length=36), nullable=True))
        op.add_column("report_exports", sa.Column("error_code", sa.String(length=80), nullable=True))
        op.add_column("report_exports", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index("ix_report_exports_job_id", "report_exports", ["job_id"])
    with op.batch_alter_table("report_exports", recreate="always") as batch:
        if _has_column("report_exports", "job_id"):
            batch.create_foreign_key("fk_report_exports_job_id", "background_jobs", ["job_id"], ["id"])


def downgrade() -> None:
    if _has_column("report_exports", "job_id"):
        op.drop_constraint("fk_report_exports_job_id", "report_exports", type_="foreignkey")
        op.drop_index("ix_report_exports_job_id", table_name="report_exports")
        op.drop_column("report_exports", "completed_at")
        op.drop_column("report_exports", "error_code")
        op.drop_column("report_exports", "job_id")
    if _has_column("capability_tasks", "job_id"):
        op.drop_constraint("fk_capability_tasks_job_id", "capability_tasks", type_="foreignkey")
        op.drop_index("ix_capability_tasks_job_id", table_name="capability_tasks")
        op.drop_column("capability_tasks", "job_id")
    op.drop_index("ix_login_attempts_username", table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_index("ix_job_events_job_id", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_background_jobs_owner_created", table_name="background_jobs")
    op.drop_index("ix_background_jobs_status_available", table_name="background_jobs")
    op.drop_table("background_jobs")
