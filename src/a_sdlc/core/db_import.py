"""
Data import engine for migrating a-sdlc data between databases.

Transfers all data from a source SQLite database to a target database
(PostgreSQL or any SQLAlchemy-supported backend) with zero data loss.

Features:
- Foreign-key dependency ordering for correct insert sequence
- Row count verification per table
- Pre-flight checks (schema version, target emptiness)
- Transaction safety with rollback on failure
- Optional content file migration to a different ContentBackend
- Rich progress output via callback

Usage::

    from a_sdlc.core.db_import import DataImporter

    importer = DataImporter(
        source_db_path="/path/to/source/data.db",
        target_url="postgresql://user:pass@host/dbname",
    )
    result = importer.run()
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

from a_sdlc.core.engine import create_all_tables, get_engine
from a_sdlc.core.models import ALL_MODELS
from a_sdlc.core.storage_config import StorageConfig

# Fields that store datetime values in the database.  Used by
# ``_coerce_datetimes`` to convert ISO-8601 strings read from the
# source SQLite DB into Python ``datetime`` objects required by
# SQLAlchemy's DateTime type adapter.
_DATETIME_FIELDS: frozenset[str] = frozenset({
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
    "last_accessed",
    "last_synced",
    "ready_at",
    "split_at",
    "cleaned_at",
    "verified_at",
})

logger = logging.getLogger(__name__)

# Schema version required for import
REQUIRED_SCHEMA_VERSION = 15

# Foreign-key dependency order for table insertion.
# Tables are listed so that referenced tables come before referencing ones.
# This order is derived from the FK graph in database.py _create_schema().
IMPORT_ORDER: list[str] = [
    "schema_version",
    "projects",
    "sprints",
    "prds",
    "tasks",
    "designs",
    "sync_mappings",
    "external_config",
    "worktrees",
    "reviews",
    "audit_log",
    "requirements",
    "requirement_links",
    "ac_verifications",
    "challenge_records",
]


@dataclass
class ImportResult:
    """Result of a data import operation."""

    success: bool = False
    tables_imported: int = 0
    total_rows: int = 0
    row_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    content_files_migrated: int = 0
    duration_seconds: float = 0.0

    def summary(self) -> str:
        """Return a human-readable summary of the import result."""
        if self.success:
            lines = [
                f"Import completed successfully in {self.duration_seconds:.1f}s",
                f"Tables: {self.tables_imported}",
                f"Total rows: {self.total_rows}",
            ]
            if self.content_files_migrated:
                lines.append(f"Content files migrated: {self.content_files_migrated}")
            if self.warnings:
                lines.append(f"Warnings: {len(self.warnings)}")
            return " | ".join(lines)
        return f"Import FAILED: {'; '.join(self.errors)}"


# Type alias for progress callbacks.
# Called with (table_name, rows_inserted, total_rows_in_table).
ProgressCallback = Callable[[str, int, int], None]


class ImportError(Exception):
    """Raised when a data import operation fails."""


class PreflightError(ImportError):
    """Raised when pre-flight checks fail before import begins."""


def _get_source_schema_version(conn: sqlite3.Connection) -> int | None:
    """Read the schema_version from a source SQLite database.

    Returns:
        The schema version integer, or None if the table does not exist.
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    if cursor.fetchone() is None:
        return None
    cursor = conn.execute("SELECT version FROM schema_version")
    row = cursor.fetchone()
    return row[0] if row else None


def _get_source_tables(conn: sqlite3.Connection) -> set[str]:
    """Get the set of user table names in the source database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return {row[0] for row in cursor.fetchall()}


def _get_source_row_count(conn: sqlite3.Connection, table: str) -> int:
    """Get the row count for a table in the source database."""
    cursor = conn.execute(f"SELECT COUNT(*) FROM [{table}]")  # noqa: S608
    return cursor.fetchone()[0]


def _get_source_rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    """Read all rows from a source table as list of dicts."""
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(f"SELECT * FROM [{table}]")  # noqa: S608
    rows = cursor.fetchall()
    conn.row_factory = None
    return [dict(row) for row in rows]


def _get_target_row_count(engine: Engine, table: str) -> int:
    """Get the row count for a table in the target database."""
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
        return result.scalar() or 0


def _is_target_empty(engine: Engine) -> bool:
    """Check if the target database has zero data rows (excluding schema_version)."""
    tables_to_check = [t for t in IMPORT_ORDER if t != "schema_version"]
    with engine.connect() as conn:
        for table in tables_to_check:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
                count = result.scalar() or 0
                if count > 0:
                    return False
            except Exception:
                # Table may not exist yet, which is fine
                continue
    return True


def _parse_datetime(value: str) -> datetime:
    """Parse a datetime string from SQLite into a Python datetime.

    Handles multiple formats produced by SQLite/SessionDatabase:
    - ISO 8601 with timezone: ``2024-01-15T10:30:00+00:00``
    - ISO 8601 with Z suffix: ``2024-01-15T10:30:00Z``
    - SQLite CURRENT_TIMESTAMP: ``2024-01-15 10:30:00``
    """
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    # Last resort: fromisoformat (Python 3.11+ handles most ISO strings)
    return datetime.fromisoformat(value)


def _coerce_datetimes(row: dict[str, Any]) -> dict[str, Any]:
    """Convert datetime string values in a row to Python datetime objects.

    SQLite stores timestamps as text (ISO-8601 or ``YYYY-MM-DD HH:MM:SS``).
    SQLAlchemy's DateTime type adapter requires actual ``datetime`` objects
    when inserting via the ORM.

    Args:
        row: Mutable row dictionary. Modified in place **and** returned.

    Returns:
        The same dictionary with datetime fields coerced.
    """
    for key in _DATETIME_FIELDS:
        val = row.get(key)
        if isinstance(val, str) and val:
            with contextlib.suppress(ValueError, TypeError):
                row[key] = _parse_datetime(val)
    return row


def _row_to_model(table_name: str, row: dict[str, Any]) -> SQLModel:
    """Convert a raw row dict to a SQLModel instance.

    Coerces datetime strings to Python datetime objects.

    Args:
        table_name: The SQL table name.
        row: Dictionary of column name -> value.

    Returns:
        A SQLModel instance ready for session.add().
    """
    model_cls = ALL_MODELS[table_name]

    # Coerce datetime strings to datetime objects
    row = _coerce_datetimes(row)

    # Filter row to only include fields the model actually has
    model_fields = set(model_cls.model_fields.keys())
    filtered_row = {k: v for k, v in row.items() if k in model_fields}

    return model_cls(**filtered_row)


class DataImporter:
    """Engine for importing data from a source SQLite database to a target database.

    The importer reads all rows from each table in FK dependency order,
    constructs SQLModel instances, and bulk-inserts them into the target
    database within a single transaction. On any failure, the transaction
    is rolled back leaving the target unchanged.

    Args:
        source_db_path: Path to the source SQLite database file.
        target_url: SQLAlchemy connection URL for the target database.
            E.g. ``"postgresql://user:pass@localhost/mydb"`` or
            ``"sqlite:///path/to/new.db"``.
        force: If True, allow importing into a non-empty target database.
            Defaults to False.
        migrate_content: If True, copy content files from the source
            LocalContentBackend to the target ContentBackend.
        target_content_backend: Optional target ContentBackend for content
            migration. Required when ``migrate_content=True``.
        source_content_dir: Optional source content directory. Defaults to
            the standard ``~/.a-sdlc/content/`` location.
        progress_callback: Optional callback for progress reporting.
    """

    def __init__(
        self,
        source_db_path: str | Path,
        target_url: str,
        *,
        force: bool = False,
        migrate_content: bool = False,
        target_content_backend: Any | None = None,
        source_content_dir: Path | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.source_db_path = Path(source_db_path)
        self.target_url = target_url
        self.force = force
        self.migrate_content = migrate_content
        self.target_content_backend = target_content_backend
        self.source_content_dir = source_content_dir
        self.progress_callback = progress_callback

    def _notify(self, table: str, current: int, total: int) -> None:
        """Fire the progress callback if set."""
        if self.progress_callback:
            self.progress_callback(table, current, total)

    def preflight(self) -> list[str]:
        """Run pre-flight checks before import.

        Returns:
            List of error messages. Empty list means all checks passed.
        """
        errors: list[str] = []

        # 1. Source database exists
        if not self.source_db_path.exists():
            errors.append(f"Source database not found: {self.source_db_path}")
            return errors

        # 2. Source schema version is v15
        try:
            src_conn = sqlite3.connect(str(self.source_db_path))
            version = _get_source_schema_version(src_conn)
            if version is None:
                errors.append("Source database has no schema_version table")
            elif version != REQUIRED_SCHEMA_VERSION:
                errors.append(
                    f"Source schema version is {version}, "
                    f"expected {REQUIRED_SCHEMA_VERSION}"
                )
            src_conn.close()
        except sqlite3.Error as exc:
            errors.append(f"Cannot read source database: {exc}")
            return errors

        # 3. Target database is accessible and tables can be created
        try:
            target_config = StorageConfig(database_url=self.target_url)
            target_engine = get_engine(target_config)
            create_all_tables(target_engine)
        except Exception as exc:
            errors.append(f"Cannot connect to target database: {exc}")
            return errors

        # 4. Target is empty (unless --force)
        if not self.force and not _is_target_empty(target_engine):
            errors.append(
                "Target database is not empty. "
                "Use --force to import into a non-empty database."
            )

        # 5. Content migration prerequisites
        if self.migrate_content:
            if self.target_content_backend is None:
                errors.append(
                    "--migrate-content requires a target content backend"
                )
            if self.source_content_dir is None:
                # Use default location
                from a_sdlc.core.content import get_data_dir

                default_dir = get_data_dir() / "content"
                if not default_dir.exists():
                    errors.append(
                        f"Source content directory not found: {default_dir}"
                    )

        return errors

    def run(self) -> ImportResult:
        """Execute the data import.

        Returns:
            An ImportResult with details about what was imported.

        Raises:
            PreflightError: If pre-flight checks fail.
            ImportError: If the import fails during execution.
        """
        start_time = datetime.now(timezone.utc)
        result = ImportResult()

        # Pre-flight checks
        errors = self.preflight()
        if errors:
            result.errors = errors
            raise PreflightError("; ".join(errors))

        # Open source connection
        src_conn = sqlite3.connect(str(self.source_db_path))
        src_conn.execute("PRAGMA foreign_keys = OFF")  # Read-only, don't enforce

        # Set up target engine and ensure tables exist
        target_config = StorageConfig(database_url=self.target_url)
        target_engine = get_engine(target_config)
        create_all_tables(target_engine)

        # Get the set of tables that actually exist in the source
        source_tables = _get_source_tables(src_conn)

        # Build the ordered list of tables to import (only those present in source)
        tables_to_import = [t for t in IMPORT_ORDER if t in source_tables]

        # Skip schema_version since the target already has it from create_all_tables
        tables_to_import = [t for t in tables_to_import if t != "schema_version"]

        # Use a single session/transaction for the entire import
        session = Session(target_engine)
        try:
            # If force mode, we may need to clear existing data in reverse FK order
            if self.force and not _is_target_empty(target_engine):
                logger.info("Force mode: clearing existing data from target")
                for table in reversed(tables_to_import):
                    session.execute(text(f"DELETE FROM {table}"))  # noqa: S608
                session.flush()

            for table_name in tables_to_import:
                if table_name not in ALL_MODELS:
                    result.warnings.append(
                        f"Skipping table '{table_name}': no SQLModel class found"
                    )
                    continue

                # Read source rows
                source_count = _get_source_row_count(src_conn, table_name)
                rows = _get_source_rows(src_conn, table_name)

                self._notify(table_name, 0, source_count)

                # Transform and insert
                inserted = 0
                for row in rows:
                    model_instance = _row_to_model(table_name, row)
                    session.add(model_instance)
                    inserted += 1

                    # Periodic flush for memory management on large tables
                    if inserted % 1000 == 0:
                        session.flush()
                        self._notify(table_name, inserted, source_count)

                session.flush()
                self._notify(table_name, inserted, source_count)

                # Record counts for verification
                result.row_counts[table_name] = {
                    "source": source_count,
                    "imported": inserted,
                }
                result.total_rows += inserted
                result.tables_imported += 1

            # Commit the entire transaction
            session.commit()

            # Verify row counts
            verification_errors = self._verify_counts(target_engine, result.row_counts)
            if verification_errors:
                result.errors.extend(verification_errors)
                result.success = False
                raise ImportError(
                    "Row count verification failed: " + "; ".join(verification_errors)
                )

            # Content migration (if requested)
            if self.migrate_content:
                result.content_files_migrated = self._migrate_content_files()

            result.success = True

        except ImportError:
            # Already handled; re-raise after cleanup
            raise
        except Exception as exc:
            session.rollback()
            result.errors.append(f"Import failed: {exc}")
            raise ImportError(f"Import failed: {exc}") from exc
        finally:
            session.close()
            src_conn.close()
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            result.duration_seconds = elapsed

        return result

    def _verify_counts(
        self,
        target_engine: Engine,
        row_counts: dict[str, dict[str, int]],
    ) -> list[str]:
        """Verify that row counts match between source and target.

        Returns:
            List of error messages for mismatches. Empty means all good.
        """
        errors: list[str] = []
        for table_name, counts in row_counts.items():
            expected = counts["source"]
            try:
                actual = _get_target_row_count(target_engine, table_name)
            except Exception as exc:
                errors.append(f"Cannot verify {table_name}: {exc}")
                continue

            if actual != expected:
                errors.append(
                    f"Table '{table_name}': expected {expected} rows, "
                    f"found {actual}"
                )
        return errors

    def _migrate_content_files(self) -> int:
        """Copy content files from source local backend to target backend.

        Returns:
            Number of files migrated.
        """
        if self.source_content_dir is None:
            from a_sdlc.core.content import get_data_dir

            source_dir = get_data_dir() / "content"
        else:
            source_dir = self.source_content_dir

        if not source_dir.exists():
            logger.warning("Source content directory not found: %s", source_dir)
            return 0

        backend = self.target_content_backend
        migrated = 0

        # For local backends, resolve paths as absolute under the default
        # content directory to avoid writing relative to CWD.
        from a_sdlc.core.content import LocalContentBackend, get_data_dir

        target_base: Path | None = None
        if isinstance(backend, LocalContentBackend):
            target_base = get_data_dir() / "content"

        # Walk all .md files under source content dir
        for md_file in sorted(source_dir.rglob("*.md")):
            relative = md_file.relative_to(source_dir)
            content = md_file.read_text(encoding="utf-8")
            # For S3, the relative path works as-is (it's a key).
            # For local filesystem, resolve to an absolute path.
            if target_base is not None:
                target_path = str(target_base / relative)
            else:
                target_path = str(relative)
            try:
                backend.write_content(target_path, content)
                migrated += 1
            except Exception as exc:
                logger.warning(
                    "Failed to migrate content file %s: %s", relative, exc
                )

        return migrated
