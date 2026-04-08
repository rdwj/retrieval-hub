"""Alembic environment for retrieval-hub-auth.

The auth service has its own model metadata and its own migration
history, separate from the core library's. We pull the database URL from
``RETRIEVAL_HUB_AUTH_DB_URL`` so the same configuration works in dev, CI,
and OpenShift.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing the db package registers every auth ORM model on Base.metadata
# as a side-effect. Do not remove even if it looks unused: Alembic's
# autogenerate compares against the populated MetaData object.
from retrieval_hub_auth.db import models  # noqa: F401
from retrieval_hub_auth.db.base import metadata as target_metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Always override the URL from the environment.
_db_url = os.environ.get(
    "RETRIEVAL_HUB_AUTH_DB_URL",
    "sqlite+pysqlite:///:memory:",
)
config.set_main_option("sqlalchemy.url", _db_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
