"""Persist the relationship between user messages and uploaded assets."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_message_assets"
down_revision = "0010_fault_context"
branch_labels = None
depends_on = None


def _has_table(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table("message_assets"):
        return
    op.create_table(
        "message_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("message_id", sa.String(length=36), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("asset_id", sa.String(length=36), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("message_id", "asset_id", name="uq_message_assets_message_asset"),
    )
    op.create_index("ix_message_assets_message_id", "message_assets", ["message_id"])
    op.create_index("ix_message_assets_asset_id", "message_assets", ["asset_id"])
    op.create_index("ix_message_assets_message_created", "message_assets", ["message_id", "created_at"])


def downgrade() -> None:
    if not _has_table("message_assets"):
        return
    op.drop_index("ix_message_assets_message_created", table_name="message_assets")
    op.drop_index("ix_message_assets_asset_id", table_name="message_assets")
    op.drop_index("ix_message_assets_message_id", table_name="message_assets")
    op.drop_table("message_assets")
