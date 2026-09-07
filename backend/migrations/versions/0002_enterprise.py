"""Add enterprise organizations, permissions, lifecycle and reporting entities."""

from alembic import op
import sqlalchemy as sa


revision = "0002_enterprise"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def _add_column(table: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    if column.name not in {item["name"] for item in inspector.get_columns(table)}:
        with op.batch_alter_table(table) as batch:
            batch.add_column(column)


def _create_tables() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "organizations" not in tables:
        op.create_table(
            "organizations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("code", sa.String(80), nullable=False, unique=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_organizations_code", "organizations", ["code"], unique=False)

    if "sites" not in tables:
        op.create_table(
            "sites",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("code", sa.String(80), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("organization_id", "code", name="uq_sites_org_code"),
        )
        op.create_index("ix_sites_organization_id", "sites", ["organization_id"], unique=False)
        op.create_index("ix_sites_code", "sites", ["code"], unique=False)

    if "production_lines" not in tables:
        op.create_table(
            "production_lines",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("site_id", sa.String(36), sa.ForeignKey("sites.id"), nullable=False),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("code", sa.String(80), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("site_id", "code", name="uq_lines_site_code"),
        )
        op.create_index("ix_production_lines_site_id", "production_lines", ["site_id"], unique=False)
        op.create_index("ix_production_lines_organization_id", "production_lines", ["organization_id"], unique=False)
        op.create_index("ix_production_lines_code", "production_lines", ["code"], unique=False)

    if "user_scopes" not in tables:
        op.create_table(
            "user_scopes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False),
            sa.Column("site_id", sa.String(36), sa.ForeignKey("sites.id"), nullable=True),
            sa.Column("line_id", sa.String(36), sa.ForeignKey("production_lines.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("user_id", "organization_id", "site_id", "line_id", name="uq_user_scope"),
        )
        for name, table, cols in [
            ("ix_user_scopes_user_id", "user_scopes", ["user_id"]),
            ("ix_user_scopes_organization_id", "user_scopes", ["organization_id"]),
            ("ix_user_scopes_site_id", "user_scopes", ["site_id"]),
            ("ix_user_scopes_line_id", "user_scopes", ["line_id"]),
        ]:
            op.create_index(name, table, cols, unique=False)

    if "role_permissions" not in tables:
        op.create_table(
            "role_permissions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("role", sa.String(40), nullable=False),
            sa.Column("permission", sa.String(120), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("role", "permission", name="uq_role_permission"),
        )
        op.create_index("ix_role_permissions_role", "role_permissions", ["role"], unique=False)
        op.create_index("ix_role_permissions_permission", "role_permissions", ["permission"], unique=False)

    if "fault_events" not in tables:
        op.create_table(
            "fault_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("fault_id", sa.String(36), sa.ForeignKey("fault_records.id"), nullable=False),
            sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("from_status", sa.String(32), nullable=True),
            sa.Column("to_status", sa.String(32), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_fault_events_fault_id", "fault_events", ["fault_id"], unique=False)
        op.create_index("ix_fault_events_actor_id", "fault_events", ["actor_id"], unique=False)

    if "report_exports" not in tables:
        op.create_table(
            "report_exports",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("report_type", sa.String(40), nullable=False),
            sa.Column("format", sa.String(10), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="ready"),
            sa.Column("file_name", sa.String(255), nullable=False),
            sa.Column("file_path", sa.String(500), nullable=False),
            sa.Column("filters_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_report_exports_owner_id", "report_exports", ["owner_id"], unique=False)

    if "provider_configs" not in tables:
        op.create_table(
            "provider_configs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(40), nullable=False, unique=True),
            sa.Column("model", sa.String(255), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("settings_json", sa.JSON(), nullable=True),
            sa.Column("updated_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_provider_configs_name", "provider_configs", ["name"], unique=False)


def upgrade() -> None:
    _create_tables()
    _add_column("users", sa.Column("organization_id", sa.String(36), nullable=True))
    _add_column("devices", sa.Column("organization_id", sa.String(36), nullable=True))
    _add_column("devices", sa.Column("site_id", sa.String(36), nullable=True))
    _add_column("devices", sa.Column("line_id", sa.String(36), nullable=True))
    _add_column("sessions", sa.Column("organization_id", sa.String(36), nullable=True))
    _add_column("knowledge_docs", sa.Column("organization_id", sa.String(36), nullable=True))
    _add_column("knowledge_docs", sa.Column("failure_reason", sa.Text(), nullable=True))
    _add_column("fault_records", sa.Column("session_id", sa.String(36), nullable=True))
    _add_column("fault_records", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("fault_records", sa.Column("assigned_to", sa.String(36), nullable=True))
    _add_column("fault_records", sa.Column("confirmed_by", sa.String(36), nullable=True))
    _add_column("fault_records", sa.Column("verified_by", sa.String(36), nullable=True))
    _add_column("fault_records", sa.Column("closed_by", sa.String(36), nullable=True))
    _add_column("fault_records", sa.Column("resolution", sa.Text(), nullable=True))


def downgrade() -> None:
    for table in ("provider_configs", "report_exports", "fault_events", "role_permissions", "user_scopes", "production_lines", "sites", "organizations"):
        if table in sa.inspect(op.get_bind()).get_table_names():
            op.drop_table(table)
