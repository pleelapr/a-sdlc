"""
SQLite database operations for a-sdlc MCP server.

Provides:
- Platform-aware data directory (macOS, Linux, Windows)
- SQLite connection management
- Schema migrations
- CRUD operations for projects, PRDs, tasks, sprints
"""

import json
import os
import platform
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

# Schema version for migrations
SCHEMA_VERSION = 3


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


class Database:
    """SQLite database manager for a-sdlc."""

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
        """Initialize database with schema if needed."""
        with self.connection() as conn:
            # Check if schema exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            if cursor.fetchone() is None:
                self._create_schema(conn)
            else:
                self._migrate_if_needed(conn)

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        """Create initial database schema."""
        conn.executescript(f"""
            -- Schema version tracking
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT INTO schema_version (version) VALUES ({SCHEMA_VERSION});

            -- Projects table
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX idx_projects_path ON projects(path);

            -- PRDs table (PRDs can optionally belong to a sprint)
            CREATE TABLE prds (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                sprint_id TEXT,
                title TEXT NOT NULL,
                content TEXT,
                status TEXT DEFAULT 'draft',
                source TEXT,
                version TEXT DEFAULT '1.0.0',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_prds_project ON prds(project_id);
            CREATE INDEX idx_prds_status ON prds(status);
            CREATE INDEX idx_prds_sprint ON prds(sprint_id);

            -- Tasks table (tasks belong to PRDs, sprint is derived from PRD)
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                prd_id TEXT,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'medium',
                component TEXT,
                data JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
        """)

    def _migrate_if_needed(self, conn: sqlite3.Connection) -> None:
        """Check schema version and run migrations if needed.

        Note: Historical migrations (v1→v2, v2→v3) have been removed.
        New databases are created with the current schema directly.
        Existing databases at version 3 require no migration.
        """
        cursor = conn.execute("SELECT version FROM schema_version")
        current_version = cursor.fetchone()[0]

        if current_version < SCHEMA_VERSION:
            # No automatic migrations - manual intervention required
            raise RuntimeError(
                f"Database schema version {current_version} is outdated. "
                f"Expected version {SCHEMA_VERSION}. "
                "Please backup your data and recreate the database."
            )

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
    # Project Operations
    # =========================================================================

    def create_project(self, project_id: str, name: str, path: str) -> dict[str, Any]:
        """Create a new project.

        Args:
            project_id: Unique project identifier (slug)
            name: Display name
            path: Filesystem path to project root

        Returns:
            Created project dict
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO projects (id, name, path, created_at, last_accessed)
                   VALUES (?, ?, ?, ?, ?)""",
                (project_id, name, path, now, now),
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

    def list_projects(self) -> list[dict[str, Any]]:
        """List all projects ordered by last accessed."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM projects ORDER BY last_accessed DESC"
            )
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
        content: str = "",
        status: str = "draft",
        source: str | None = None,
        sprint_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new PRD.

        Args:
            prd_id: Unique PRD identifier
            project_id: Parent project ID
            title: PRD title
            content: PRD markdown content
            status: PRD status (draft, ready, split)
            source: Optional source reference
            sprint_id: Optional sprint assignment
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO prds (id, project_id, sprint_id, title, content, status, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (prd_id, project_id, sprint_id, title, content, status, source, now, now),
            )
        return self.get_prd(prd_id)

    def get_prd(self, prd_id: str) -> dict[str, Any] | None:
        """Get PRD by ID."""
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
        """Update PRD fields."""
        if not kwargs:
            return self.get_prd(prd_id)

        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()
        fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
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
        description: str = "",
        status: str = "pending",
        priority: str = "medium",
        prd_id: str | None = None,
        component: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new task.

        Args:
            task_id: Unique task identifier
            project_id: Parent project ID
            title: Task title
            description: Task description
            status: Task status (pending, in_progress, blocked, completed)
            priority: Task priority (low, medium, high, critical)
            prd_id: Optional parent PRD (task inherits sprint from PRD)
            component: Optional component/module name
            data: Optional additional structured data

        Note:
            Tasks no longer have direct sprint_id. Sprint is derived
            from the parent PRD's sprint_id.
        """
        now = datetime.now(timezone.utc).isoformat()
        data_json = json.dumps(data) if data else None

        with self.connection() as conn:
            conn.execute(
                """INSERT INTO tasks
                   (id, project_id, prd_id, title, description,
                    status, priority, component, data, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id, project_id, prd_id, title, description,
                    status, priority, component, data_json, now, now,
                ),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get task by ID."""
        with self.connection() as conn:
            cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                result = dict(row)
                if result.get("data"):
                    result["data"] = json.loads(result["data"])
                return result
            return None

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
            results = []
            for row in cursor.fetchall():
                result = dict(row)
                if result.get("data"):
                    result["data"] = json.loads(result["data"])
                results.append(result)
            return results

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
            results = []
            for row in cursor.fetchall():
                result = dict(row)
                if result.get("data"):
                    result["data"] = json.loads(result["data"])
                results.append(result)
            return results

    def update_task(self, task_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update task fields."""
        if not kwargs:
            return self.get_task(task_id)

        # Handle special fields
        if "data" in kwargs and kwargs["data"] is not None:
            kwargs["data"] = json.dumps(kwargs["data"])

        kwargs["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Handle completed_at for status changes
        if kwargs.get("status") == "completed" and "completed_at" not in kwargs:
            kwargs["completed_at"] = kwargs["updated_at"]

        fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
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
        """Generate next task ID for a project."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE project_id = ?", (project_id,)
            )
            count = cursor.fetchone()[0]
        return f"TASK-{count + 1:03d}"

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
        if kwargs.get("status") == "active" and "started_at" not in kwargs:
            kwargs["started_at"] = datetime.now(timezone.utc).isoformat()
        elif kwargs.get("status") == "completed" and "completed_at" not in kwargs:
            kwargs["completed_at"] = datetime.now(timezone.utc).isoformat()

        fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
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
        """Generate next sprint ID for a project."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM sprints WHERE project_id = ?", (project_id,)
            )
            count = cursor.fetchone()[0]
        return f"SPRINT-{count + 1:02d}"

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
        fields = ", ".join(f"{k} = ?" for k in kwargs.keys())
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
