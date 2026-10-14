"""Add fault location and observed evidence fields."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_fault_context"
down_revision = "0009_diagnosis_performance"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if not _has_column("fault_records", "fault_location"):
        op.add_column("fault_records", sa.Column("fault_location", sa.String(length=255), nullable=True))
    if not _has_column("fault_records", "observed_evidence"):
        op.add_column("fault_records", sa.Column("observed_evidence", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("fault_records", "observed_evidence"):
        op.drop_column("fault_records", "observed_evidence")
    if _has_column("fault_records", "fault_location"):
        op.drop_column("fault_records", "fault_location")
