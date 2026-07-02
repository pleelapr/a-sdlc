"""Programmatic Alembic configuration pointing at the packaged migrations.

Single source of truth for both the server's startup auto-migration and the
``a-sdlc db`` CLI commands. Migrations live inside the installed package at
``a_sdlc/migrations`` (not the repo root), so this module resolves them via
the package location and works identically from a source checkout, an
editable install, a built wheel, and inside the Docker image.

The previous implementation probed for ``alembic.ini`` at a path that
resolved to ``site-packages/`` in Docker (and ``src/`` in a checkout), so it
was never found and auto-migration silently skipped. This module removes the
ini-file dependency entirely: Alembic ``env.py`` skips ``fileConfig`` when
``config_file_name`` is ``None`` and honours a runtime-set ``sqlalchemy.url``,
so a purely programmatic ``Config`` is sufficient.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from alembic.config import Config
    from sqlalchemy.engine import Connection

# a_sdlc/core/alembic_config.py -> a_sdlc/core -> a_sdlc -> a_sdlc/migrations
MIGRATIONS_DIR: Path = Path(__file__).resolve().parent.parent / "migrations"


class MigrationSetupError(RuntimeError):
    """Packaged migration scripts or the database URL are missing/broken.

    Raised instead of silently skipping so a broken install fails loudly.
    """


def _create_engine(database_url: str):
    """Create a short-lived engine with the project's Postgres fail-fast settings.

    Mirrors ``a_sdlc.core.engine.get_engine``: for PostgreSQL, apply
    ``connect_timeout=10`` and ``pool_pre_ping=True`` so status/migration calls
    (including ``a-sdlc doctor``) fail in seconds on an unreachable host instead
    of blocking for minutes on the OS TCP timeout.
    """
    from sqlalchemy import create_engine

    kwargs: dict[str, Any] = {}
    if database_url.startswith(("postgresql://", "postgresql+")):
        kwargs["pool_pre_ping"] = True
        kwargs["connect_args"] = {"connect_timeout": 10}
    return create_engine(database_url, **kwargs)


def build_alembic_config(database_url: str | None = None) -> Config:
    """Build an ini-less Alembic ``Config`` for the packaged migrations.

    ``env.py`` skips ``fileConfig`` when ``config_file_name`` is ``None`` and a
    runtime-set ``sqlalchemy.url`` takes precedence in its URL resolution, so
    no ``alembic.ini`` file is needed at runtime.

    Args:
        database_url: Explicit DB URL. When ``None``, resolved from
            ``StorageConfig`` (environment variables + config files).

    Raises:
        MigrationSetupError: if the packaged migration scripts are missing or
            no database URL can be resolved.
    """
    from alembic.config import Config

    if not (MIGRATIONS_DIR / "env.py").is_file():
        raise MigrationSetupError(
            f"Packaged Alembic migrations not found at {MIGRATIONS_DIR}; "
            "the a-sdlc installation is broken (wheel missing a_sdlc/migrations)."
        )

    if database_url is None:
        from a_sdlc.core.storage_config import load_storage_config

        database_url = load_storage_config(validate=False).database_url

    if not database_url:
        raise MigrationSetupError(
            "No database URL configured; set A_SDLC_DATABASE_URL or "
            "storage.database_url in a config file."
        )

    cfg = Config()  # no ini file -- env.py handles the None config_file_name
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Alembic's Config stores values in a ConfigParser with BasicInterpolation,
    # which treats "%" as an interpolation sigil. Managed Postgres providers
    # (Railway, etc.) hand out URLs with percent-encoded password characters
    # (e.g. p%40ss). Escape "%" -> "%%" so ConfigParser stores it literally;
    # env.py reads it back via get_main_option(), which un-escapes it, yielding
    # the original URL for SQLAlchemy to decode. Without this, a "%" in the URL
    # raises ValueError here and crash-loops startup (auto-migration is fatal).
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return cfg


def detect_stamp_revision(connection: Connection) -> str | None:
    """Infer the Alembic revision for a schema created outside Alembic.

    The production database was created by ``SQLModel.metadata.create_all``
    before Alembic auto-migration worked, so it has the tables but no
    ``alembic_version`` row. Stamping the correct baseline lets subsequent
    ``upgrade head`` runs apply only the genuinely-missing migrations.

    The ``projects.path`` column is the discriminator across the three known
    revisions:

    * no ``projects`` table            -> ``None``  (fresh DB: run all migrations)
    * ``projects`` has no ``path``      -> ``"0003"`` (current models)
    * ``projects.path`` is nullable     -> ``"0002"``
    * ``projects.path`` is NOT NULL     -> ``"0001"``
    """
    from sqlalchemy import inspect as sa_inspect

    insp = sa_inspect(connection)
    if not insp.has_table("projects"):
        return None
    cols = {c["name"]: c for c in insp.get_columns("projects")}
    if "path" not in cols:
        return "0003"
    return "0002" if cols["path"]["nullable"] else "0001"


def get_revision_info(database_url: str) -> dict[str, Any]:
    """Return ``{"current", "head", "pending"}`` for logging and diagnostics.

    ``current`` is the DB's stamped revision (``None`` if unstamped), ``head``
    is the latest packaged revision, ``pending`` is the count of migrations
    between them.
    """
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(build_alembic_config(database_url))
    heads = script.get_heads()
    head = heads[0] if heads else None

    engine = _create_engine(database_url)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()

    pending = 0
    if head is not None and current != head:
        # walk_revisions(base, head): base (older) first, head (newer) second.
        # current is the older bound (DB behind head) -> (current or "base", head).
        pending = sum(
            1 for r in script.walk_revisions(current or "base", head) if r.revision != current
        )
    return {"current": current, "head": head, "pending": pending}


def run_upgrade_head(database_url: str, *, logger: Any) -> None:
    """Stamp a pre-Alembic schema if needed, then ``alembic upgrade head``.

    Raises on any failure so callers (server startup) can refuse to serve
    traffic against an unmigrated or half-migrated schema.
    """
    from alembic import command as alembic_command
    from alembic.runtime.migration import MigrationContext

    cfg = build_alembic_config(database_url)
    engine = _create_engine(database_url)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
            stamp_rev = None if current is not None else detect_stamp_revision(conn)

        if stamp_rev is not None:
            logger.warning(
                "Existing schema has no alembic_version; stamping baseline %s "
                "before upgrading (schema was created by SQLModel create_all).",
                stamp_rev,
            )
            alembic_command.stamp(cfg, stamp_rev)

        logger.info(
            "Running database migrations (alembic upgrade head, scripts=%s, current=%s)",
            MIGRATIONS_DIR,
            current or stamp_rev or "<empty database>",
        )
        alembic_command.upgrade(cfg, "head")

        with engine.connect() as conn:
            final = MigrationContext.configure(conn).get_current_revision()
        logger.info("Database schema at revision %s", final)
    finally:
        engine.dispose()
