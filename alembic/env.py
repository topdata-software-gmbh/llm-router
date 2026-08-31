"""Alembic env.py for llm-router migrations.

Alembic owns the schema; this wires the migration runner to SQLModel's
metadata so ``--autogenerate`` can diff against the ORM models. The database
URL is taken from the application config so ``LLM_ROUTER_DB`` is respected.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from llm_router import config as app_config
from llm_router.models import SQLModel  # noqa: F401 — registers all tables

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

config.set_main_option("sqlalchemy.url", app_config.DATABASE_URL)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
