"""Align legacy SQLite columns and indexes with the enterprise metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0004_enterprise_indexes"
down_revision = "0003_enterprise_columns"
branch_labels = None
depends_on = None


def _index_names(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _add_index(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    if name not in _index_names(table):
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE devices SET updated_at = created_at WHERE updated_at IS NULL"))
    conn.execute(sa.text("UPDATE fault_records SET updated_at = created_at WHERE updated_at IS NULL"))
    with op.batch_alter_table("devices") as batch:
        batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    with op.batch_alter_table("fault_records") as batch:
        batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)

    _add_index("ix_devices_organization_id", "devices", ["organization_id"])
    _add_index("ix_devices_site_id", "devices", ["site_id"])
    _add_index("ix_devices_line_id", "devices", ["line_id"])
    _add_index("ix_sessions_organization_id", "sessions", ["organization_id"])
    _add_index("ix_knowledge_docs_organization_id", "knowledge_docs", ["organization_id"])
    _add_index("ix_fault_records_session_id", "fault_records", ["session_id"])
    _add_index("ix_fault_records_assigned_to", "fault_records", ["assigned_to"])
    _add_index("ix_users_organization_id", "users", ["organization_id"])

    # These indexes are declared unique by the ORM model.
    for name, table, columns in [
        ("ix_organizations_code", "organizations", ["code"]),
        ("ix_provider_configs_name", "provider_configs", ["name"]),
    ]:
        if name in _index_names(table):
            op.drop_index(name, table_name=table)
        op.create_index(name, table, columns, unique=True)


def downgrade() -> None:
    for name, table in [
        ("ix_users_organization_id", "users"),
        ("ix_fault_records_assigned_to", "fault_records"),
        ("ix_fault_records_session_id", "fault_records"),
        ("ix_knowledge_docs_organization_id", "knowledge_docs"),
        ("ix_sessions_organization_id", "sessions"),
        ("ix_devices_line_id", "devices"),
        ("ix_devices_site_id", "devices"),
        ("ix_devices_organization_id", "devices"),
    ]:
        if name in _index_names(table):
            op.drop_index(name, table_name=table)
