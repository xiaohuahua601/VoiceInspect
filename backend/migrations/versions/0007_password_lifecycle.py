from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_password_lifecycle"
down_revision = "0006_knowledge_source_content"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    return column in {item["name"] for item in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    if not _has_column("users", "must_change_password"):
        op.add_column("users", sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    if _has_column("users", "must_change_password"):
        op.drop_column("users", "must_change_password")
