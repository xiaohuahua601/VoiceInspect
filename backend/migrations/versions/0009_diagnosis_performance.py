"""Add diagnosis request idempotency and performance metadata."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_diagnosis_performance"
down_revision = "0008_background_jobs"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table: str, name: str) -> bool:
    return name in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    if not _has_column("background_jobs", "request_id"):
        op.add_column("background_jobs", sa.Column("request_id", sa.String(length=120), nullable=True))
    if not _has_column("background_jobs", "metrics_json"):
        op.add_column("background_jobs", sa.Column("metrics_json", sa.JSON(), nullable=True))
    if not _has_column("background_jobs", "error_detail"):
        op.add_column("background_jobs", sa.Column("error_detail", sa.String(length=500), nullable=True))
    if not _has_index("background_jobs", "ix_background_jobs_request_id"):
        op.create_index("ix_background_jobs_request_id", "background_jobs", ["request_id"])
    if not _has_index("background_jobs", "uq_background_jobs_owner_request"):
        op.create_index("uq_background_jobs_owner_request", "background_jobs", ["owner_id", "request_id"], unique=True)
    if not _has_column("messages", "job_id"):
        op.add_column("messages", sa.Column("job_id", sa.String(length=36), nullable=True))
    if not _has_index("messages", "ix_messages_job_id"):
        op.create_index("ix_messages_job_id", "messages", ["job_id"])


def downgrade() -> None:
    if _has_index("messages", "ix_messages_job_id"):
        op.drop_index("ix_messages_job_id", table_name="messages")
    if _has_column("messages", "job_id"):
        op.drop_column("messages", "job_id")
    if _has_index("background_jobs", "uq_background_jobs_owner_request"):
        op.drop_index("uq_background_jobs_owner_request", table_name="background_jobs")
    if _has_index("background_jobs", "ix_background_jobs_request_id"):
        op.drop_index("ix_background_jobs_request_id", table_name="background_jobs")
    if _has_column("background_jobs", "error_detail"):
        op.drop_column("background_jobs", "error_detail")
    if _has_column("background_jobs", "metrics_json"):
        op.drop_column("background_jobs", "metrics_json")
    if _has_column("background_jobs", "request_id"):
        op.drop_column("background_jobs", "request_id")
