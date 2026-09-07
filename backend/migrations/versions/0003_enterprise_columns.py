"""Complete columns introduced by the enterprise model layer."""

from alembic import op
import sqlalchemy as sa


revision = "0003_enterprise_columns"
down_revision = "0002_enterprise"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "updated_at" not in {item["name"] for item in inspector.get_columns("devices")}:
        with op.batch_alter_table("devices") as batch:
            batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("devices") as batch:
        batch.drop_column("updated_at")
