from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from creative_hub.models import ORCHESTRATION_SCHEMA, OrchestrationBase
import creative_hub.db.models  # noqa: F401  # register atomic tables
import creative_hub.dag_models  # noqa: F401  # register DAG projections
import creative_hub.cutover_models  # noqa: F401  # register cutover authority


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = OrchestrationBase.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_schemas=True,
        version_table="alembic_version",
        version_table_schema=ORCHESTRATION_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.exec_driver_sql(
            f"CREATE SCHEMA IF NOT EXISTS {ORCHESTRATION_SCHEMA}"
        )
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_schemas=True,
            version_table="alembic_version",
            version_table_schema=ORCHESTRATION_SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
