from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.core.config import get_settings
from backend.repositories.db import Base
from backend.repositories import models, advanced_models  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def include_object(object_, name, type_, reflected, compare_to):
    # Legacy SQLite tables cannot add every new foreign key without rebuilding
    # the original table. Fresh migrations still create all declared FKs.
    if type_ == "foreign_key_constraint":
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=get_settings().database_url,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
