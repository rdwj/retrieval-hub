"""Alembic environment for retrieval-hub.

We always pull the database URL from ``RETRIEVAL_HUB_DB_URL`` so the same
configuration works in dev, CI, and OpenShift. The metadata target is the
catalog data model defined under ``retrieval_hub.models``.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Importing the package registers every ORM model on Base.metadata as a
# side-effect. Do not remove these imports even if they look unused: alembic's
# autogenerate compares against the populated MetaData object.
from retrieval_hub import models  # noqa: F401
from retrieval_hub.db.base import metadata as target_metadata
from retrieval_hub.db.engine import get_default_db_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Always override the URL from the environment.
config.set_main_option("sqlalchemy.url", get_default_db_url())


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
