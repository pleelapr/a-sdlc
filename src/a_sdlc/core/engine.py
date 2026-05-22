"""
SQLAlchemy engine and session factory for a-sdlc.

Provides:
- ``get_engine()``: Create or reuse a cached SQLAlchemy engine from a
  ``StorageConfig.database_url``.
- ``get_session()``: Context manager yielding a short-lived ``Session``
  with automatic commit/rollback.

Connection pooling:
- PostgreSQL (production): SQLAlchemy's default ``QueuePool`` (configurable
  via ``pool_size`` / ``max_overflow``).
- SQLite (test isolation only): ``StaticPool`` with ``check_same_thread=False``.

Usage::

    from a_sdlc.core.engine import get_engine, get_session

    engine = get_engine()                     # uses default StorageConfig
    with get_session(engine) as session:
        project = session.get(Project, "id")
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from a_sdlc.core.storage_config import StorageConfig, get_storage_config

# ---------------------------------------------------------------------------
# Module-level engine cache (one engine per database URL)
# ---------------------------------------------------------------------------

_engine_lock = threading.Lock()
_engine_cache: dict[str, Engine] = {}


def get_engine(
    config: StorageConfig | None = None,
    *,
    echo: bool = False,
) -> Engine:
    """Create or return a cached SQLAlchemy ``Engine``.

    Args:
        config: Storage configuration. Defaults to the singleton from
            ``get_storage_config()``.
        echo: If ``True``, enable SQLAlchemy SQL logging. Defaults to ``False``.

    Returns:
        A SQLAlchemy ``Engine`` instance. Engines are cached by URL so that
        repeated calls with the same URL return the same engine.
    """
    if config is None:
        config = get_storage_config()

    url = config.database_url

    with _engine_lock:
        if url in _engine_cache:
            return _engine_cache[url]

        kwargs: dict = {"echo": echo}

        if config.is_sqlite:
            # SQLite-specific settings
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = StaticPool
        else:
            # PostgreSQL / other dialects: use default QueuePool
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 10
            kwargs["pool_pre_ping"] = True

        engine = create_engine(url, **kwargs)

        # Enable WAL journal mode and foreign keys for SQLite connections
        if config.is_sqlite:
            @event.listens_for(engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn, _connection_record):  # noqa: ANN001
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _engine_cache[url] = engine
        return engine


def create_all_tables(engine: Engine) -> None:
    """Create all tables defined by SQLModel metadata.

    This uses ``SQLModel.metadata.create_all()`` which is safe to call
    repeatedly -- it only creates tables that do not already exist.

    Args:
        engine: The SQLAlchemy engine to create tables on.
    """
    SQLModel.metadata.create_all(engine)


def reset_engine_cache() -> None:
    """Dispose all cached engines and clear the cache.

    Intended for test teardown to ensure a clean state.
    """
    with _engine_lock:
        for engine in _engine_cache.values():
            engine.dispose()
        _engine_cache.clear()


@contextmanager
def get_session(engine: Engine | None = None) -> Generator[Session, None, None]:
    """Context manager for short-lived database sessions.

    Opens a session, yields it for use, and handles commit/rollback:
    - On normal exit: commits the transaction.
    - On exception: rolls back the transaction and re-raises.
    - Always: closes the session.

    Args:
        engine: SQLAlchemy engine. If ``None``, uses ``get_engine()``
            with the default ``StorageConfig``.

    Yields:
        A SQLModel ``Session`` instance.
    """
    if engine is None:
        engine = get_engine()

    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
