"""
SQLite database operations for a-sdlc MCP server.

Provides:
- Platform-aware data directory (macOS, Linux, Windows)
- SQLite connection management
- CRUD operations for projects, PRDs, tasks, sprints
- Hybrid storage: SQLite indexes metadata, file_path references markdown files
"""

import json
import os
import platform
import re
import shutil
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Schema version for fresh start (hybrid storage with file_path design)
# Version 2: Added shortname column to projects table
SCHEMA_VERSION = 8


def get_data_dir() -> Path:
    """Get platform-specific data directory.

    Returns:
        Path: ~/.a-sdlc/ on macOS/Linux, %LOCALAPPDATA%/a-sdlc/ on Windows
    """
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "a-sdlc"
    else:
        return Path.home() / ".a-sdlc"


def get_db_path() -> Path:
    """Get path to SQLite database file."""
    return get_data_dir() / "data.db"


def ensure_data_dir() -> Path:
    """Create data directory if it doesn't exist."""
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


class _MigrationError(Exception):
    """Internal exception for migration failures that need backup restore."""

    def __init__(self, original_version: int, backup_path: Path, original_error: Exception):
        self.original_version = original_version
        self.backup_path = backup_path
        self.original_error = original_error
        super().__init__(str(original_error))


class Database:
    """SQLite database manager for a-sdlc.

    This class manages metadata and file path references.
    Actual content is stored in markdown files (managed by ContentManager).
    """

    def __init__(self, db_path: Path | None = None):
        """Initialize database connection.

        Args:
            db_path: Optional custom path to database file.
                    If None, uses platform-specific default.
        """
        self.db_path = db_path or get_db_path()
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database with schema if needed.

        Wraps migration in a backup/restore cycle: if migration fails,
        the database file is restored from the pre-migration backup.
        """
        try:
            with self.connection() as conn:
                # Check if schema exists
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
                )
                if cursor.fetchone() is None:
                    self._create_schema(conn)
                else:
                    self._check_schema_version(conn)
        except _MigrationError as e:
            # Connection is now closed by context manager.
            # Restore from backup and re-raise as RuntimeError.
            if e.backup_path and e.backup_path.exists():
                shutil.copy2(e.backup_path, self.db_path)
            raise RuntimeError(
                f"Migration from v{e.original_version} failed. "
                f"Database restored from backup at {e.backup_path}. "
                f"Error: {e.original_error}"
            ) from e.original_error

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        """Create initial database schema (version 2 - with shortname)."""
        conn.executescript(f"""
            -- Schema version tracking
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT INTO schema_version (version) VALUES ({SCHEMA_VERSION});

            -- Projects table
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                shortname TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX idx_projects_path ON projects(path);
            CREATE UNIQUE INDEX idx_projects_shortname ON projects(shortname);

            -- PRDs table (metadata + file path reference)
            CREATE TABLE prds (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                sprint_id TEXT,
                title TEXT NOT NULL,
                file_path TEXT,
                status TEXT DEFAULT 'draft',
                source TEXT,
                version TEXT DEFAULT '1.0.0',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ready_at TIMESTAMP,
                split_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_prds_project ON prds(project_id);
            CREATE INDEX idx_prds_status ON prds(status);
            CREATE INDEX idx_prds_sprint ON prds(sprint_id);

            -- Tasks table (metadata + file path reference)
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                prd_id TEXT,
                title TEXT NOT NULL,
                file_path TEXT,
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'medium',
                component TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_tasks_project ON tasks(project_id);
            CREATE INDEX idx_tasks_status ON tasks(status);
            CREATE INDEX idx_tasks_prd ON tasks(prd_id);

            -- Sprints table
            CREATE TABLE sprints (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                goal TEXT,
                status TEXT DEFAULT 'planned',
                external_id TEXT,
                external_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_sprints_project ON sprints(project_id);
            CREATE INDEX idx_sprints_status ON sprints(status);

            -- Sync mappings for external systems
            CREATE TABLE sync_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                local_id TEXT NOT NULL,
                external_system TEXT NOT NULL,
                external_id TEXT NOT NULL,
                sync_status TEXT DEFAULT 'synced',
                last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(entity_type, local_id, external_system)
            );
            CREATE INDEX idx_sync_entity ON sync_mappings(entity_type, local_id);
            CREATE INDEX idx_sync_external ON sync_mappings(external_system, external_id);

            -- Designs table (1:1 with PRD, metadata + file path reference)
            CREATE TABLE designs (
                id TEXT PRIMARY KEY,
                prd_id TEXT UNIQUE NOT NULL,
                project_id TEXT NOT NULL,
                file_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_designs_prd ON designs(prd_id);
            CREATE INDEX idx_designs_project ON designs(project_id);

            -- External configuration for integrations (Linear, Jira)
            CREATE TABLE external_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                system TEXT NOT NULL,
                config JSON NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, system),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_external_config_project ON external_config(project_id);

            -- Worktrees table (DB-tracked worktree lifecycle per PRD)
            CREATE TABLE worktrees (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                prd_id TEXT NOT NULL,
                sprint_id TEXT,
                branch_name TEXT NOT NULL,
                path TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                pr_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cleaned_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_worktrees_project ON worktrees(project_id);
            CREATE INDEX idx_worktrees_prd ON worktrees(prd_id);
            CREATE INDEX idx_worktrees_sprint ON worktrees(sprint_id);
            CREATE INDEX idx_worktrees_status ON worktrees(status);

            -- Reviews table (review evidence per task per round)
            CREATE TABLE reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                round INTEGER NOT NULL DEFAULT 1,
                reviewer_type TEXT NOT NULL,
                verdict TEXT NOT NULL,
                findings TEXT,
                test_output TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_reviews_task ON reviews(task_id);
            CREATE INDEX idx_reviews_project ON reviews(project_id);
        """)

    def _check_schema_version(self, conn: sqlite3.Connection) -> None:
        """Check schema version matches expected and run migrations if needed.

        Creates a backup of the database before running migrations.
        If any migration fails, the database is restored from the backup
        and a RuntimeError is raised with details.
        """
        cursor = conn.execute("SELECT version FROM schema_version")
        current_version = cursor.fetchone()[0]

        if current_version == SCHEMA_VERSION:
            return

        if current_version > SCHEMA_VERSION:
            # Unknown/future version - can't migrate
            raise RuntimeError(
                f"Database schema version {current_version} is newer than expected "
                f"version {SCHEMA_VERSION}. Please upgrade a-sdlc or restore from "
                f"a backup at {self.db_path.with_suffix('.db.bak.v' + str(current_version))} "
                "if available."
            )

        # Create backup before migrating
        original_version = current_version
        backup_path = self.db_path.with_suffix(f".db.bak.v{original_version}")
        if self.db_path.exists():
            shutil.copy2(self.db_path, backup_path)

        # Run chained migrations with rollback on failure
        try:
            if current_version == 1:
                self._migrate_v1_to_v2(conn)
                current_version = 2

            if current_version == 2:
                self._migrate_v2_to_v3(conn)
                current_version = 3

            if current_version == 3:
                self._migrate_v3_to_v4(conn)
                current_version = 4

            if current_version == 4:
                self._migrate_v4_to_v5(conn)
                current_version = 5

            if current_version == 5:
                self._migrate_v5_to_v6(conn)
                current_version = 6

            if current_version == 6:
                self._migrate_v6_to_v7(conn)
                current_version = 7

            if current_version == 7:
                self._migrate_v7_to_v8(conn)
                current_version = 8
        except _MigrationError:
            raise
        except Exception as e:
            # Raise _MigrationError to signal _init_db to restore from backup
            # after the connection context manager has closed the connection.
            raise _MigrationError(original_version, backup_path, e) from e

        if current_version != SCHEMA_VERSION:
            # Reached end of migration chain but version still doesn't match
            raise RuntimeError(
                f"Database schema version {current_version} is incompatible. "
                f"Expected version {SCHEMA_VERSION}. "
                f"A backup is available at {backup_path}."
            )

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 1 to version 2 (add shortname column)."""
        # Add shortname column
        conn.execute("ALTER TABLE projects ADD COLUMN shortname TEXT")

        # Generate shortnames for existing projects
        cursor = conn.execute("SELECT id, name FROM projects")
        projects = cursor.fetchall()

        existing_shortnames: set[str] = set()
        for project in projects:
            project_id = project["id"]
            project_name = project["name"]
            shortname = self._generate_unique_shortname_internal(
                project_name, existing_shortnames, conn
            )
            existing_shortnames.add(shortname)
            conn.execute(
                "UPDATE projects SET shortname = ? WHERE id = ?",
                (shortname, project_id)
            )

        # Add unique constraint
        conn.execute("CREATE UNIQUE INDEX idx_projects_shortname ON projects(shortname)")

        # Update schema version
        conn.execute("UPDATE schema_version SET version = 2")

    def _migrate_v2_to_v3(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 2 to version 3 (add started_at to tasks)."""
        conn.execute("ALTER TABLE tasks ADD COLUMN started_at TIMESTAMP")
        # Backfill: approximate started_at from created_at for active/completed tasks
        conn.execute("""
            UPDATE tasks SET started_at = created_at
            WHERE status IN ('in_progress', 'completed') AND started_at IS NULL
        """)
        conn.execute("UPDATE schema_version SET version = 3")

    def _migrate_v3_to_v4(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 3 to version 4 (add PRD phase timestamps)."""
        conn.execute("ALTER TABLE prds ADD COLUMN ready_at TIMESTAMP")
        conn.execute("ALTER TABLE prds ADD COLUMN split_at TIMESTAMP")
        conn.execute("ALTER TABLE prds ADD COLUMN completed_at TIMESTAMP")

        # Backfill: approximate from available data
        # ready → ready_at = updated_at
        conn.execute("""
            UPDATE prds SET ready_at = updated_at
            WHERE status = 'ready' AND ready_at IS NULL
        """)
        # split → ready_at = created_at, split_at = updated_at
        conn.execute("""
            UPDATE prds SET ready_at = created_at, split_at = updated_at
            WHERE status = 'split' AND split_at IS NULL
        """)
        # completed → all three approximated
        conn.execute("""
            UPDATE prds SET ready_at = created_at, split_at = created_at, completed_at = updated_at
            WHERE status = 'completed' AND completed_at IS NULL
        """)
        conn.execute("UPDATE schema_version SET version = 4")

    def _migrate_v4_to_v5(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 4 to version 5 (add designs table)."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS designs (
                id TEXT PRIMARY KEY,
                prd_id TEXT UNIQUE NOT NULL,
                project_id TEXT NOT NULL,
                file_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_designs_prd ON designs(prd_id);
            CREATE INDEX IF NOT EXISTS idx_designs_project ON designs(project_id);
        """)
        conn.execute("UPDATE schema_version SET version = 5")

    def _migrate_v5_to_v6(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 5 to version 6 (add worktrees table)."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS worktrees (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                prd_id TEXT NOT NULL,
                sprint_id TEXT,
                branch_name TEXT NOT NULL,
                path TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cleaned_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_worktrees_project ON worktrees(project_id);
            CREATE INDEX IF NOT EXISTS idx_worktrees_prd ON worktrees(prd_id);
            CREATE INDEX IF NOT EXISTS idx_worktrees_sprint ON worktrees(sprint_id);
            CREATE INDEX IF NOT EXISTS idx_worktrees_status ON worktrees(status);
        """)
        conn.execute("UPDATE schema_version SET version = 6")

    def _migrate_v6_to_v7(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 6 to version 7 (add pr_url to worktrees)."""
        conn.execute("ALTER TABLE worktrees ADD COLUMN pr_url TEXT")
        conn.execute("UPDATE schema_version SET version = 7")

    def _migrate_v7_to_v8(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 7 to version 8 (add reviews table)."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                round INTEGER NOT NULL DEFAULT 1,
                reviewer_type TEXT NOT NULL,
                verdict TEXT NOT NULL,
                findings TEXT,
                test_output TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_reviews_task ON reviews(task_id);
            CREATE INDEX IF NOT EXISTS idx_reviews_project ON reviews(project_id);
        """)
        conn.execute("UPDATE schema_version SET version = 8")

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections.

        Yields:
            sqlite3.Connection with row factory set to sqlite3.Row
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # =========================================================================
    # Shortname Utilities
    # =========================================================================

    @staticmethod
    def validate_shortname(shortname: str) -> tuple[bool, str]:
        """Validate a project shortname.

        Args:
            shortname: The shortname to validate.

        Returns:
            Tuple of (is_valid, error_message). Error message is empty if valid.
        """
        if not shortname:
            return False, "Shortname cannot be empty"
        if len(shortname) != 4:
            return False, "Shortname must be exactly 4 characters"
        if not re.match(r'^[A-Z]{4}$', shortname):
            return False, "Shortname must contain only uppercase letters (A-Z)"
        return True, ""

    @staticmethod
    def _generate_shortname_candidate(name: str) -> str:
        """Generate a 4-char shortname candidate from project name.

        Args:
            name: Project name to generate shortname from.

        Returns:
            4-character uppercase shortname candidate.
        """
        # Remove non-alpha, uppercase
        clean = re.sub(r'[^a-zA-Z]', '', name).upper()

        # Try consonants first (more memorable)
        consonants = re.sub(r'[AEIOU]', '', clean)
        if len(consonants) >= 4:
            return consonants[:4]

        # Fall back to first 4 letters
        if len(clean) >= 4:
            return clean[:4]

        # Pad with X if too short
        return (clean + 'XXXX')[:4]

    def _generate_unique_shortname_internal(
        self,
        name: str,
        existing: set[str],
        conn: sqlite3.Connection,
    ) -> str:
        """Generate a unique shortname (internal helper for migration).

        Args:
            name: Project name.
            existing: Set of already-used shortnames in this batch.
            conn: Database connection.

        Returns:
            Unique shortname.
        """
        base = self._generate_shortname_candidate(name)

        # Try the base candidate first
        if base not in existing:
            cursor = conn.execute(
                "SELECT 1 FROM projects WHERE shortname = ?", (base,)
            )
            if not cursor.fetchone():
                return base

        # Try adding numeric suffix (A, B, C... then 1, 2, 3...)
        for suffix in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789':
            candidate = base[:3] + suffix
            if candidate not in existing:
                cursor = conn.execute(
                    "SELECT 1 FROM projects WHERE shortname = ?", (candidate,)
                )
                if not cursor.fetchone():
                    return candidate

        # Fallback: random-ish suffix
        import random
        while True:
            suffix = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ', k=1))
            candidate = base[:3] + suffix
            if candidate not in existing:
                cursor = conn.execute(
                    "SELECT 1 FROM projects WHERE shortname = ?", (candidate,)
                )
                if not cursor.fetchone():
                    return candidate

    def generate_unique_shortname(self, name: str) -> str:
        """Generate a unique shortname for a new project.

        Args:
            name: Project name to generate shortname from.

        Returns:
            Unique 4-character uppercase shortname.
        """
        with self.connection() as conn:
            return self._generate_unique_shortname_internal(name, set(), conn)

    def is_shortname_available(self, shortname: str) -> bool:
        """Check if a shortname is available.

        Args:
            shortname: Shortname to check.

        Returns:
            True if available, False if already in use.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM projects WHERE shortname = ?", (shortname,)
            )
            return cursor.fetchone() is None

    # =========================================================================
    # Project Operations
    # =========================================================================

    def create_project(
        self,
        project_id: str,
        name: str,
        path: str,
        shortname: str | None = None,
    ) -> dict[str, Any]:
        """Create a new project.

        Args:
            project_id: Unique project identifier (slug)
            name: Display name
            path: Filesystem path to project root
            shortname: 4-character uppercase project key (auto-generated if not provided)

        Returns:
            Created project dict

        Raises:
            ValueError: If shortname is invalid or already in use.
        """
        # Generate shortname if not provided
        if shortname is None:
            shortname = self.generate_unique_shortname(name)
        else:
            # Validate provided shortname
            is_valid, error_msg = self.validate_shortname(shortname)
            if not is_valid:
                raise ValueError(error_msg)
            if not self.is_shortname_available(shortname):
                raise ValueError(f"Shortname '{shortname}' is already in use")

        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO projects (id, shortname, name, path, created_at, last_accessed)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (project_id, shortname, name, path, now, now),
            )
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Get project by ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_project_by_path(self, path: str) -> dict[str, Any] | None:
        """Get project by filesystem path."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM projects WHERE path = ?", (path,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_project_by_shortname(self, shortname: str) -> dict[str, Any] | None:
        """Get project by shortname.

        Args:
            shortname: 4-character project shortname.

        Returns:
            Project dict if found, None otherwise.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM projects WHERE shortname = ?", (shortname,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_project_path(self, project_id: str, new_path: str) -> dict[str, Any] | None:
        """Update project filesystem path (for relocating projects).

        Args:
            project_id: Project identifier.
            new_path: New filesystem path.

        Returns:
            Updated project dict or None if not found.

        Raises:
            ValueError: If new_path is already used by another project.
        """
        # Check if path is already in use by another project
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT id FROM projects WHERE path = ? AND id != ?",
                (new_path, project_id)
            )
            if cursor.fetchone():
                raise ValueError(f"Path '{new_path}' is already used by another project")

            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                "UPDATE projects SET path = ?, last_accessed = ? WHERE id = ?",
                (new_path, now, project_id)
            )
            if cursor.rowcount == 0:
                return None

        return self.get_project(project_id)

    def list_projects(self) -> list[dict[str, Any]]:
        """List all projects ordered by last accessed."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM projects ORDER BY last_accessed DESC"
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_all_projects_with_stats(self) -> list[dict[str, Any]]:
        """Get all projects with aggregated task/PRD/sprint counts.

        Returns projects ordered by last accessed, each with:
        - task counts by status (pending, in_progress, completed, blocked)
        - total PRDs, total sprints
        - active sprint title (if any)
        """
        with self.connection() as conn:
            cursor = conn.execute("""
                SELECT
                    p.*,
                    COALESCE(t_counts.total_tasks, 0) AS total_tasks,
                    COALESCE(t_counts.pending, 0) AS tasks_pending,
                    COALESCE(t_counts.in_progress, 0) AS tasks_in_progress,
                    COALESCE(t_counts.completed, 0) AS tasks_completed,
                    COALESCE(t_counts.blocked, 0) AS tasks_blocked,
                    COALESCE(prd_counts.total_prds, 0) AS total_prds,
                    COALESCE(sprint_counts.total_sprints, 0) AS total_sprints,
                    active_sprint.title AS active_sprint_title,
                    active_sprint.id AS active_sprint_id
                FROM projects p
                LEFT JOIN (
                    SELECT project_id,
                           COUNT(*) AS total_tasks,
                           SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                           SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) AS in_progress,
                           SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                           SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked
                    FROM tasks GROUP BY project_id
                ) t_counts ON p.id = t_counts.project_id
                LEFT JOIN (
                    SELECT project_id, COUNT(*) AS total_prds
                    FROM prds GROUP BY project_id
                ) prd_counts ON p.id = prd_counts.project_id
                LEFT JOIN (
                    SELECT project_id, COUNT(*) AS total_sprints
                    FROM sprints GROUP BY project_id
                ) sprint_counts ON p.id = sprint_counts.project_id
                LEFT JOIN (
                    SELECT project_id, id, title
                    FROM sprints
                    WHERE status = 'active'
                    GROUP BY project_id
                    HAVING id = MAX(id)
                ) active_sprint ON p.id = active_sprint.project_id
                ORDER BY p.last_accessed DESC
            """)
            return [dict(row) for row in cursor.fetchall()]

    def get_most_recent_project(self) -> dict[str, Any] | None:
        """Get the most recently accessed project."""
        with self.connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM projects
                   ORDER BY last_accessed DESC
                   LIMIT 1"""
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_project_accessed(self, project_id: str) -> None:
        """Update project's last_accessed timestamp."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                "UPDATE projects SET last_accessed = ? WHERE id = ?",
                (now, project_id),
            )

    def delete_project(self, project_id: str) -> bool:
        """Delete a project and all associated data."""
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM projects WHERE id = ?", (project_id,)
            )
            return cursor.rowcount > 0

    # =========================================================================
    # PRD Operations
    # =========================================================================

    def create_prd(
        self,
        prd_id: str,
        project_id: str,
        title: str,
        file_path: str | None = None,
        status: str = "draft",
        source: str | None = None,
        sprint_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new PRD.

        Args:
            prd_id: Unique PRD identifier
            project_id: Parent project ID
            title: PRD title
            file_path: Path to markdown file (source of truth for content)
            status: PRD status (draft, ready, split)
            source: Optional source reference
            sprint_id: Optional sprint assignment
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO prds (id, project_id, sprint_id, title, file_path, status, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (prd_id, project_id, sprint_id, title, file_path, status, source, now, now),
            )
        return self.get_prd(prd_id)

    def get_prd(self, prd_id: str) -> dict[str, Any] | None:
        """Get PRD by ID (metadata only, content in file)."""
        with self.connection() as conn:
            cursor = conn.execute("SELECT * FROM prds WHERE id = ?", (prd_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_prds(
        self,
        project_id: str,
        sprint_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List PRDs for a project with optional filters.

        Args:
            project_id: Project identifier
            sprint_id: Filter by sprint (None for all, empty string for backlog/unassigned)
            status: Filter by status
        """
        query = "SELECT * FROM prds WHERE project_id = ?"
        params: list[Any] = [project_id]

        if sprint_id is not None:
            if sprint_id == "":
                # Empty string means backlog (no sprint)
                query += " AND sprint_id IS NULL"
            else:
                query += " AND sprint_id = ?"
                params.append(sprint_id)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY updated_at DESC"

        with self.connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def update_prd(self, prd_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update PRD fields with status transition timestamp tracking."""
        if not kwargs:
            return self.get_prd(prd_id)

        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()

        new_status = kwargs.get("status")
        if new_status:
            now = kwargs["updated_at"]
            current = self.get_prd(prd_id)

            if new_status == "draft":
                # Full reset: clear all phase timestamps
                kwargs.setdefault("ready_at", None)
                kwargs.setdefault("split_at", None)
                kwargs.setdefault("completed_at", None)
            elif new_status == "ready":
                # Set ready_at on first transition (NULL = not yet set)
                if current and not current.get("ready_at"):
                    kwargs["ready_at"] = now
                # Clear downstream timestamps
                kwargs.setdefault("split_at", None)
                kwargs.setdefault("completed_at", None)
            elif new_status == "split":
                # Preserve ready_at, set split_at on first transition
                if current and not current.get("split_at"):
                    kwargs["split_at"] = now
                # Clear completed_at
                kwargs.setdefault("completed_at", None)
            elif new_status == "completed":
                # Preserve all prior, set completed_at
                kwargs.setdefault("completed_at", now)

        fields = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [prd_id]

        with self.connection() as conn:
            conn.execute(f"UPDATE prds SET {fields} WHERE id = ?", values)
        return self.get_prd(prd_id)

    def delete_prd(self, prd_id: str) -> bool:
        """Delete a PRD."""
        with self.connection() as conn:
            cursor = conn.execute("DELETE FROM prds WHERE id = ?", (prd_id,))
            return cursor.rowcount > 0

    # =========================================================================
    # Task Operations
    # =========================================================================

    def create_task(
        self,
        task_id: str,
        project_id: str,
        title: str,
        file_path: str | None = None,
        status: str = "pending",
        priority: str = "medium",
        prd_id: str | None = None,
        component: str | None = None,
    ) -> dict[str, Any]:
        """Create a new task.

        Args:
            task_id: Unique task identifier
            project_id: Parent project ID
            title: Task title
            file_path: Path to markdown file (source of truth for content)
            status: Task status (pending, in_progress, blocked, completed)
            priority: Task priority (low, medium, high, critical)
            prd_id: Optional parent PRD (task inherits sprint from PRD)
            component: Optional component/module name

        Note:
            Tasks no longer have direct sprint_id. Sprint is derived
            from the parent PRD's sprint_id.
        """
        now = datetime.now(timezone.utc).isoformat()

        with self.connection() as conn:
            conn.execute(
                """INSERT INTO tasks
                   (id, project_id, prd_id, title, file_path,
                    status, priority, component, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id, project_id, prd_id, title, file_path,
                    status, priority, component, now, now,
                ),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get task by ID (metadata only, content in file)."""
        with self.connection() as conn:
            cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_tasks(
        self,
        project_id: str,
        status: str | None = None,
        prd_id: str | None = None,
        sprint_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List tasks with optional filters.

        Args:
            project_id: Project identifier
            status: Filter by task status
            prd_id: Filter by parent PRD
            sprint_id: Filter by sprint (derived from PRD's sprint_id)

        Note:
            sprint_id filter works by joining with PRDs table to find
            tasks whose parent PRD belongs to the specified sprint.
        """
        if sprint_id:
            # Join with PRDs to filter by sprint
            query = """
                SELECT t.* FROM tasks t
                LEFT JOIN prds p ON t.prd_id = p.id
                WHERE t.project_id = ?
                AND (p.sprint_id = ? OR (t.prd_id IS NULL AND ? = ''))
            """
            params: list[Any] = [project_id, sprint_id, sprint_id]
        else:
            query = "SELECT * FROM tasks WHERE project_id = ?"
            params = [project_id]

        if status:
            query += " AND status = ?"
            params.append(status)
        if prd_id:
            query += " AND prd_id = ?"
            params.append(prd_id)

        query += " ORDER BY created_at DESC"

        with self.connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def list_tasks_by_sprint(
        self,
        project_id: str,
        sprint_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List tasks for a sprint (derived via PRD relationship).

        This is a convenience method that finds all tasks whose parent
        PRD belongs to the specified sprint.

        Args:
            project_id: Project identifier
            sprint_id: Sprint to get tasks for
            status: Optional status filter
        """
        query = """
            SELECT t.*, p.sprint_id as derived_sprint_id
            FROM tasks t
            INNER JOIN prds p ON t.prd_id = p.id
            WHERE t.project_id = ? AND p.sprint_id = ?
        """
        params: list[Any] = [project_id, sprint_id]

        if status:
            query += " AND t.status = ?"
            params.append(status)

        query += " ORDER BY t.created_at DESC"

        with self.connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def update_task(self, task_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update task fields."""
        if not kwargs:
            return self.get_task(task_id)

        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Handle timestamps for status transitions
        new_status = kwargs.get("status")
        if new_status:
            now = kwargs["updated_at"]
            if new_status == "in_progress":
                # Set started_at only on first start
                current = self.get_task(task_id)
                if current and not current.get("started_at"):
                    kwargs["started_at"] = now
                # Clear completed_at if reopening
                kwargs.setdefault("completed_at", None)
            elif new_status == "completed":
                kwargs.setdefault("completed_at", now)
            elif new_status == "pending":
                # Full reset: clear both timestamps
                kwargs.setdefault("started_at", None)
                kwargs.setdefault("completed_at", None)
            elif new_status == "blocked":
                # Keep started_at but clear completed_at
                kwargs.setdefault("completed_at", None)

        fields = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]

        with self.connection() as conn:
            conn.execute(f"UPDATE tasks SET {fields} WHERE id = ?", values)
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        with self.connection() as conn:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cursor.rowcount > 0

    def get_next_task_id(self, project_id: str) -> str:
        """Generate next task ID for a project.

        Format: {shortname}-T{number:05d} (e.g., PCRA-T00001)
        Uses project shortname for compact, Jira-style IDs.
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        shortname = project["shortname"]

        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE project_id = ?", (project_id,)
            )
            count = cursor.fetchone()[0]
        return f"{shortname}-T{count + 1:05d}"

    # =========================================================================
    # Sprint Operations
    # =========================================================================

    def create_sprint(
        self,
        sprint_id: str,
        project_id: str,
        title: str,
        goal: str = "",
        status: str = "planned",
    ) -> dict[str, Any]:
        """Create a new sprint."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO sprints (id, project_id, title, goal, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (sprint_id, project_id, title, goal, status, now),
            )
        return self.get_sprint(sprint_id)

    def get_sprint(self, sprint_id: str) -> dict[str, Any] | None:
        """Get sprint by ID with PRD and task summary.

        Returns sprint with:
        - prd_count: Number of PRDs in this sprint
        - task_counts: Status breakdown of all tasks (derived via PRDs)
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM sprints WHERE id = ?", (sprint_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None

            sprint = dict(row)

            # Count PRDs in this sprint
            cursor = conn.execute(
                "SELECT COUNT(*) FROM prds WHERE sprint_id = ?",
                (sprint_id,),
            )
            sprint["prd_count"] = cursor.fetchone()[0]

            # Add task counts (derived via PRD relationship)
            cursor = conn.execute(
                """SELECT t.status, COUNT(*) as count
                   FROM tasks t
                   INNER JOIN prds p ON t.prd_id = p.id
                   WHERE p.sprint_id = ?
                   GROUP BY t.status""",
                (sprint_id,),
            )
            sprint["task_counts"] = {r["status"]: r["count"] for r in cursor.fetchall()}
            return sprint

    def list_sprints(self, project_id: str) -> list[dict[str, Any]]:
        """List all sprints for a project."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM sprints WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_sprint(self, sprint_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update sprint fields."""
        if not kwargs:
            return self.get_sprint(sprint_id)

        # Handle status changes with timestamps
        new_status = kwargs.get("status")
        if new_status:
            now = datetime.now(timezone.utc).isoformat()
            if new_status == "active":
                kwargs.setdefault("started_at", now)
                kwargs.setdefault("completed_at", None)
            elif new_status == "completed":
                kwargs.setdefault("completed_at", now)
            elif new_status == "planned":
                kwargs.setdefault("started_at", None)
                kwargs.setdefault("completed_at", None)

        fields = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [sprint_id]

        with self.connection() as conn:
            conn.execute(f"UPDATE sprints SET {fields} WHERE id = ?", values)
        return self.get_sprint(sprint_id)

    def delete_sprint(self, sprint_id: str) -> bool:
        """Delete a sprint (PRDs are unlinked, not deleted)."""
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM sprints WHERE id = ?", (sprint_id,)
            )
            return cursor.rowcount > 0

    def get_sprint_prds(self, sprint_id: str) -> list[dict[str, Any]]:
        """Get all PRDs assigned to a sprint."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM prds WHERE sprint_id = ? ORDER BY updated_at DESC",
                (sprint_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def assign_prd_to_sprint(self, prd_id: str, sprint_id: str | None) -> dict[str, Any] | None:
        """Assign a PRD to a sprint (or unassign by passing None).

        Args:
            prd_id: PRD identifier
            sprint_id: Sprint ID to assign to, or None to unassign

        Returns:
            Updated PRD or None if not found
        """
        return self.update_prd(prd_id, sprint_id=sprint_id)

    def get_next_sprint_id(self, project_id: str) -> str:
        """Generate next sprint ID for a project.

        Format: {shortname}-S{number:04d} (e.g., PCRA-S0001)
        Uses project shortname for compact, Jira-style IDs.
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        shortname = project["shortname"]

        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM sprints WHERE project_id = ?", (project_id,)
            )
            count = cursor.fetchone()[0]
        return f"{shortname}-S{count + 1:04d}"

    def get_next_prd_id(self, project_id: str) -> str:
        """Generate next PRD ID for a project.

        Format: {shortname}-P{number:04d} (e.g., PCRA-P0001)
        Uses project shortname for compact, Jira-style IDs.
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        shortname = project["shortname"]

        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM prds WHERE project_id = ?", (project_id,)
            )
            count = cursor.fetchone()[0]
        return f"{shortname}-P{count + 1:04d}"

    # =========================================================================
    # Design Operations
    # =========================================================================

    def create_design(
        self,
        design_id: str,
        prd_id: str,
        project_id: str,
        file_path: str | None = None,
    ) -> dict[str, Any]:
        """Create a new design document.

        Args:
            design_id: Unique design identifier (same as prd_id)
            prd_id: Parent PRD ID (1:1 relationship)
            project_id: Parent project ID
            file_path: Path to markdown file (source of truth for content)

        Returns:
            Created design dict
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO designs (id, prd_id, project_id, file_path, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (design_id, prd_id, project_id, file_path, now, now),
            )
        return self.get_design(design_id)

    def get_design(self, design_id: str) -> dict[str, Any] | None:
        """Get design by ID (metadata only, content in file).

        Args:
            design_id: Design identifier

        Returns:
            Design dict if found, None otherwise.
        """
        with self.connection() as conn:
            cursor = conn.execute("SELECT * FROM designs WHERE id = ?", (design_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_design_by_prd(self, prd_id: str) -> dict[str, Any] | None:
        """Get design by parent PRD ID.

        Args:
            prd_id: PRD identifier

        Returns:
            Design dict if found, None otherwise.
        """
        with self.connection() as conn:
            cursor = conn.execute("SELECT * FROM designs WHERE prd_id = ?", (prd_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_designs(self, project_id: str) -> list[dict[str, Any]]:
        """List all designs for a project.

        Args:
            project_id: Project identifier

        Returns:
            List of design dicts ordered by most recently updated.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM designs WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_design(self, design_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update design fields.

        Args:
            design_id: Design identifier
            **kwargs: Fields to update (file_path, etc.)

        Returns:
            Updated design dict or None if not found.
        """
        if not kwargs:
            return self.get_design(design_id)

        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()

        fields = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [design_id]

        with self.connection() as conn:
            conn.execute(f"UPDATE designs SET {fields} WHERE id = ?", values)
        return self.get_design(design_id)

    def delete_design(self, design_id: str) -> bool:
        """Delete a design.

        Args:
            design_id: Design identifier

        Returns:
            True if deleted, False if not found.
        """
        with self.connection() as conn:
            cursor = conn.execute("DELETE FROM designs WHERE id = ?", (design_id,))
            return cursor.rowcount > 0

    # =========================================================================
    # Worktree Operations
    # =========================================================================

    def get_next_worktree_id(self, project_id: str) -> str:
        """Generate next worktree ID for a project.

        Format: {shortname}-W{number:04d} (e.g., PCRA-W0001)
        Uses project shortname for compact, Jira-style IDs.
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        shortname = project["shortname"]

        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM worktrees WHERE project_id = ?", (project_id,)
            )
            count = cursor.fetchone()[0]
        return f"{shortname}-W{count + 1:04d}"

    def create_worktree(
        self,
        worktree_id: str,
        project_id: str,
        prd_id: str,
        branch_name: str,
        path: str,
        sprint_id: str | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        """Create a new worktree record.

        Args:
            worktree_id: Unique worktree identifier.
            project_id: Parent project ID.
            prd_id: Associated PRD ID.
            branch_name: Git branch name for the worktree.
            path: Filesystem path to the worktree directory.
            sprint_id: Optional sprint ID.
            status: Worktree status (active, completed, abandoned). Default: active.

        Returns:
            Created worktree dict.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO worktrees
                   (id, project_id, prd_id, sprint_id, branch_name, path, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (worktree_id, project_id, prd_id, sprint_id, branch_name, path, status, now),
            )
        return self.get_worktree(worktree_id)

    def get_worktree(self, worktree_id: str) -> dict[str, Any] | None:
        """Get worktree by ID.

        Args:
            worktree_id: Worktree identifier.

        Returns:
            Worktree dict if found, None otherwise.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM worktrees WHERE id = ?", (worktree_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_worktree_by_prd(self, prd_id: str) -> dict[str, Any] | None:
        """Get the active worktree for a PRD.

        Args:
            prd_id: PRD identifier.

        Returns:
            Active worktree dict if found, None otherwise.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM worktrees WHERE prd_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                (prd_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_worktrees(
        self,
        project_id: str,
        status: str | None = None,
        sprint_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List worktrees for a project with optional filters.

        Args:
            project_id: Project identifier.
            status: Filter by status (active, completed, abandoned).
            sprint_id: Filter by sprint ID.

        Returns:
            List of worktree dicts ordered by most recently created.
        """
        query = "SELECT * FROM worktrees WHERE project_id = ?"
        params: list[Any] = [project_id]

        if status:
            query += " AND status = ?"
            params.append(status)

        if sprint_id:
            query += " AND sprint_id = ?"
            params.append(sprint_id)

        query += " ORDER BY created_at DESC"

        with self.connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def update_worktree(self, worktree_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update worktree fields.

        Args:
            worktree_id: Worktree identifier.
            **kwargs: Fields to update (status, cleaned_at, etc.).

        Returns:
            Updated worktree dict or None if not found.
        """
        if not kwargs:
            return self.get_worktree(worktree_id)

        # Whitelist allowed field names to prevent SQL injection via kwargs keys
        allowed_fields = {"status", "cleaned_at", "pr_url", "path", "branch_name", "sprint_id"}
        invalid_keys = set(kwargs.keys()) - allowed_fields
        if invalid_keys:
            raise ValueError(f"Invalid worktree fields: {invalid_keys}. Allowed: {allowed_fields}")

        # Handle status transitions with timestamps
        new_status = kwargs.get("status")
        if new_status and new_status in ("completed", "abandoned"):
            now = datetime.now(timezone.utc).isoformat()
            kwargs.setdefault("cleaned_at", now)

        fields = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [worktree_id]

        with self.connection() as conn:
            conn.execute(f"UPDATE worktrees SET {fields} WHERE id = ?", values)
        return self.get_worktree(worktree_id)

    def delete_worktree(self, worktree_id: str) -> bool:
        """Delete a worktree record.

        Args:
            worktree_id: Worktree identifier.

        Returns:
            True if deleted, False if not found.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM worktrees WHERE id = ?", (worktree_id,)
            )
            return cursor.rowcount > 0

    # =========================================================================
    # Review Operations
    # =========================================================================

    VALID_REVIEWER_TYPES = ("self", "subagent")
    VALID_VERDICTS = ("pass", "fail", "approve", "request_changes", "escalate")

    def create_review(
        self,
        task_id: str,
        project_id: str,
        round_num: int,
        reviewer_type: str,
        verdict: str,
        findings: str | None = None,
        test_output: str | None = None,
    ) -> dict[str, Any]:
        """Create a new review record.

        Args:
            task_id: Task being reviewed.
            project_id: Parent project ID.
            round_num: Review round number (1-based).
            reviewer_type: Type of reviewer ('self' or 'subagent').
            verdict: Review verdict ('pass', 'fail', 'approve', 'request_changes', 'escalate').
            findings: Optional JSON array of finding objects.
            test_output: Optional raw test command output.

        Returns:
            Created review dict with id.

        Raises:
            ValueError: If reviewer_type or verdict is invalid.
        """
        if reviewer_type not in self.VALID_REVIEWER_TYPES:
            raise ValueError(
                f"Invalid reviewer_type: {reviewer_type!r}. "
                f"Must be one of {self.VALID_REVIEWER_TYPES}"
            )
        if verdict not in self.VALID_VERDICTS:
            raise ValueError(
                f"Invalid verdict: {verdict!r}. "
                f"Must be one of {self.VALID_VERDICTS}"
            )

        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO reviews
                   (task_id, project_id, round, reviewer_type, verdict,
                    findings, test_output, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_id, project_id, round_num, reviewer_type, verdict,
                 findings, test_output, now),
            )
            review_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM reviews WHERE id = ?", (review_id,)
            ).fetchone()
            return dict(row)

    def get_reviews_for_task(self, task_id: str) -> list[dict[str, Any]]:
        """Get all reviews for a task, ordered by round and creation time.

        Args:
            task_id: Task identifier.

        Returns:
            List of review dicts ordered by round ASC, created_at ASC.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM reviews WHERE task_id = ? ORDER BY round ASC, created_at ASC",
                (task_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_latest_approved_review(self, task_id: str) -> dict[str, Any] | None:
        """Get the most recent approved/passed review for a task.

        Args:
            task_id: Task identifier.

        Returns:
            Most recent review with verdict 'pass' or 'approve', or None if not found.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM reviews
                   WHERE task_id = ? AND verdict IN ('pass', 'approve')
                   ORDER BY created_at DESC
                   LIMIT 1""",
                (task_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    # =========================================================================
    # Sync Mapping Operations
    # =========================================================================

    def create_sync_mapping(
        self,
        entity_type: str,
        local_id: str,
        external_system: str,
        external_id: str,
    ) -> dict[str, Any]:
        """Create a sync mapping for external system integration."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO sync_mappings
                   (entity_type, local_id, external_system, external_id, last_synced)
                   VALUES (?, ?, ?, ?, ?)""",
                (entity_type, local_id, external_system, external_id, now),
            )
            cursor = conn.execute(
                """SELECT * FROM sync_mappings
                   WHERE entity_type = ? AND local_id = ? AND external_system = ?""",
                (entity_type, local_id, external_system),
            )
            return dict(cursor.fetchone())

    def get_sync_mapping(
        self, entity_type: str, local_id: str, external_system: str
    ) -> dict[str, Any] | None:
        """Get sync mapping for an entity."""
        with self.connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM sync_mappings
                   WHERE entity_type = ? AND local_id = ? AND external_system = ?""",
                (entity_type, local_id, external_system),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_sync_mapping_by_external(
        self, entity_type: str, external_system: str, external_id: str
    ) -> dict[str, Any] | None:
        """Get sync mapping by external ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM sync_mappings
                   WHERE entity_type = ? AND external_system = ? AND external_id = ?""",
                (entity_type, external_system, external_id),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_sync_mappings(
        self, entity_type: str | None = None, external_system: str | None = None
    ) -> list[dict[str, Any]]:
        """List all sync mappings, optionally filtered."""
        query = "SELECT * FROM sync_mappings WHERE 1=1"
        params: list[Any] = []

        if entity_type:
            query += " AND entity_type = ?"
            params.append(entity_type)
        if external_system:
            query += " AND external_system = ?"
            params.append(external_system)

        query += " ORDER BY last_synced DESC"

        with self.connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def update_sync_mapping(
        self,
        entity_type: str,
        local_id: str,
        external_system: str,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Update sync mapping fields."""
        if not kwargs:
            return self.get_sync_mapping(entity_type, local_id, external_system)

        kwargs["last_synced"] = datetime.now(timezone.utc).isoformat()
        fields = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [entity_type, local_id, external_system]

        with self.connection() as conn:
            conn.execute(
                f"""UPDATE sync_mappings SET {fields}
                   WHERE entity_type = ? AND local_id = ? AND external_system = ?""",
                values,
            )
        return self.get_sync_mapping(entity_type, local_id, external_system)

    def delete_sync_mapping(
        self, entity_type: str, local_id: str, external_system: str
    ) -> bool:
        """Delete a sync mapping."""
        with self.connection() as conn:
            cursor = conn.execute(
                """DELETE FROM sync_mappings
                   WHERE entity_type = ? AND local_id = ? AND external_system = ?""",
                (entity_type, local_id, external_system),
            )
            return cursor.rowcount > 0

    # =========================================================================
    # External Config Operations
    # =========================================================================

    def get_external_config(self, project_id: str, system: str) -> dict[str, Any] | None:
        """Get external system configuration for a project.

        Args:
            project_id: Project identifier
            system: External system name ('linear' or 'jira')

        Returns:
            Config dict if found, None otherwise.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM external_config WHERE project_id = ? AND system = ?",
                (project_id, system),
            )
            row = cursor.fetchone()
            if row:
                result = dict(row)
                if result.get("config"):
                    result["config"] = json.loads(result["config"])
                return result
            return None

    def set_external_config(
        self, project_id: str, system: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Set external system configuration for a project.

        Args:
            project_id: Project identifier
            system: External system name ('linear' or 'jira')
            config: Configuration dict (API keys, team IDs, etc.)

        Returns:
            Saved config record.
        """
        now = datetime.now(timezone.utc).isoformat()
        config_json = json.dumps(config)

        with self.connection() as conn:
            conn.execute(
                """INSERT INTO external_config (project_id, system, config, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(project_id, system) DO UPDATE SET
                       config = excluded.config,
                       updated_at = excluded.updated_at""",
                (project_id, system, config_json, now, now),
            )
        return self.get_external_config(project_id, system)

    def delete_external_config(self, project_id: str, system: str) -> bool:
        """Delete external system configuration.

        Args:
            project_id: Project identifier
            system: External system name

        Returns:
            True if deleted, False if not found.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM external_config WHERE project_id = ? AND system = ?",
                (project_id, system),
            )
            return cursor.rowcount > 0

    def list_external_configs(self, project_id: str) -> list[dict[str, Any]]:
        """List all external configurations for a project.

        Args:
            project_id: Project identifier

        Returns:
            List of config records.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM external_config WHERE project_id = ? ORDER BY system",
                (project_id,),
            )
            results = []
            for row in cursor.fetchall():
                result = dict(row)
                if result.get("config"):
                    result["config"] = json.loads(result["config"])
                results.append(result)
            return results


# Global database instance
_db: Database | None = None


def get_db() -> Database:
    """Get or create the global database instance."""
    global _db
    if _db is None:
        _db = Database()
    return _db
