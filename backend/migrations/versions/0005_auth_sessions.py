"""Add persisted, revocable authentication sessions."""

from alembic import op
import sqlalchemy as sa

revision = "0005_auth_sessions"
down_revision = "0004_enterprise_indexes"
branch_labels = None
depends_on = None

def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "content_text" not in {column["name"] for column in inspector.get_columns("knowledge_docs")}:
        op.add_column("knowledge_docs", sa.Column("content_text", sa.Text(), nullable=True))
    if "due_at" not in {column["name"] for column in inspector.get_columns("fault_records")}:
        op.add_column("fault_records", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    if "ix_fault_records_due_at" not in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("fault_records")}:
        op.create_index("ix_fault_records_due_at", "fault_records", ["due_at"])
    if "auth_sessions" not in inspector.get_table_names():
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("jti", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("user_agent", sa.String(length=500), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("auth_sessions")}
    if "ix_auth_sessions_user_id" not in indexes:
        op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    if "ix_auth_sessions_jti" not in indexes:
        op.create_index("ix_auth_sessions_jti", "auth_sessions", ["jti"], unique=True)
    if "ix_auth_sessions_expires_at" not in indexes:
        op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    if "notifications" not in inspector.get_table_names():
        op.create_table(
            "notifications",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("recipient_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("kind", sa.String(length=40), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("target_type", sa.String(length=40), nullable=True),
            sa.Column("target_id", sa.String(length=36), nullable=True),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_notifications_recipient_id", "notifications", ["recipient_id"])
        op.create_index("ix_notifications_target_id", "notifications", ["target_id"])
        op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

def downgrade() -> None:
    op.drop_index("ix_fault_records_due_at", table_name="fault_records")
    op.drop_column("fault_records", "due_at")
    op.drop_column("knowledge_docs", "content_text")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_jti", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
