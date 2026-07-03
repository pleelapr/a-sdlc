"""Alembic environment configuration for a-sdlc.

Resolves the database URL at runtime via ``StorageConfig`` / ``get_engine()``
so that environment variables, project config, and global config are all
respected.  Supports both *offline* (SQL script generation) and *online*
(live connection) migration modes.
"""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlmodel import SQLModel, create_engine

import a_sdlc.core.models  # noqa: F401  -- populate SQLModel.metadata
from a_sdlc.core.storage_config import load_storage_config

# Alembic Config object -- provides access to alembic.ini values
config = context.config

# Set up loggers from the config file (if present)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

# Target metadata for autogenerate support
target_metadata = SQLModel.metadata


def _resolve_url() -> str:
    """Resolve the database URL.

    Priority order:
    1. ``sqlalchemy.url`` set on the Alembic Config object at runtime
       (e.g. via ``cfg.set_main_option("sqlalchemy.url", ...)`` in tests).
    2. ``StorageConfig`` (environment variables, project/global config).
    3. ``sqlalchemy.url`` from ``alembic.ini`` (static fallback).
    """
    # Check if a URL was explicitly set on the Config object at runtime.
    # When tests call ``cfg.set_main_option("sqlalchemy.url", url)``,
    # the value is stored in the config's ``cmd_opts`` or internal dict
    # and takes precedence.  The config file itself provides a generic
    # fallback.  We detect an explicitly-set value by checking whether
    # it differs from a placeholder pattern.
    ini_url = config.get_main_option("sqlalchemy.url") or ""

    # If the URL was explicitly overridden (not the alembic.ini default
    # that contains ``%(here)s``), honour it.
    if ini_url and "%(here)s" not in ini_url and ini_url != "sqlite:///data.db":
        return ini_url

    # Otherwise fall back to StorageConfig (env vars + config files).
    try:
        storage_config = load_storage_config(validate=False)
        url = storage_config.database_url
        if url:
            return url
    except Exception:
        logger.debug("Could not load StorageConfig; falling back to alembic.ini URL")

    return ini_url or "sqlite:///data.db"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts instead of executing against a live database.
    This is useful for producing migration SQL for review or for
    environments where a direct DB connection is not available.
    """
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # Required for SQLite ALTER TABLE support
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an engine, connects to the database, and runs migrations
    within a transaction.
    """
    url = _resolve_url()

    # Determine engine kwargs based on dialect
    connect_args: dict = {}
    poolclass = None

    if url.startswith("sqlite:///"):
        connect_args = {"check_same_thread": False}
        poolclass = pool.StaticPool

    engine_kwargs: dict = {
        "connect_args": connect_args,
    }
    if poolclass is not None:
        engine_kwargs["poolclass"] = poolclass

    connectable = create_engine(url, **engine_kwargs)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # Required for SQLite ALTER TABLE support
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
