"""Preserve source text for reliable knowledge re-indexing."""
from alembic import op
import sqlalchemy as sa

revision = "0006_knowledge_source_content"
down_revision = "0005_auth_sessions"
branch_labels = None
depends_on = None

def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("knowledge_docs")}
    if "content_text" not in columns:
        op.add_column("knowledge_docs", sa.Column("content_text", sa.Text(), nullable=True))

def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("knowledge_docs")}
    if "content_text" in columns:
        op.drop_column("knowledge_docs", "content_text")
