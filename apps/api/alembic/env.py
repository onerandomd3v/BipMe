"""Alembic migration environment."""

import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from bipme.persistence.base import Base

config = context.config
target_metadata = Base.metadata

database_url = os.getenv("BIPME_DATABASE_URL")
if not database_url:
    raise RuntimeError("BIPME_DATABASE_URL is required for migrations")

config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    """Apply migrations without a DB connection."""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live DB connection."""
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
