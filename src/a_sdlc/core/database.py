"""
SQLite database operations for a-sdlc MCP server.

Provides:
- Platform-aware data directory (macOS, Linux, Windows)
- SQLite connection management
- CRUD operations for projects, PRDs, tasks, sprints
- Hybrid storage: SQLite indexes metadata, file_path references markdown files
"""

import contextlib
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
SCHEMA_VERSION = 14


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
                assigned_agent_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE SET NULL,
                FOREIGN KEY (assigned_agent_id) REFERENCES agents(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_tasks_project ON tasks(project_id);
            CREATE INDEX idx_tasks_status ON tasks(status);
            CREATE INDEX idx_tasks_prd ON tasks(prd_id);
            CREATE INDEX idx_tasks_assigned_agent ON tasks(assigned_agent_id);

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

            -- Agent registry
            CREATE TABLE agents (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                persona_type TEXT NOT NULL,
                display_name TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                permissions_profile TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_by TEXT,
                team_id TEXT,
                reports_to_agent_id TEXT,
                hired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                suspended_at TIMESTAMP,
                retired_at TIMESTAMP,
                performance_score REAL DEFAULT 50.0,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_agents_project ON agents(project_id);
            CREATE INDEX idx_agents_status ON agents(status);
            CREATE INDEX idx_agents_persona ON agents(persona_type);

            -- Permission scopes per agent
            CREATE TABLE agent_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                permission_type TEXT NOT NULL,
                permission_value TEXT NOT NULL,
                allowed INTEGER DEFAULT 1,
                UNIQUE(agent_id, permission_type, permission_value),
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_agent_perms_agent ON agent_permissions(agent_id);

            -- Budget tracking per agent per run
            CREATE TABLE agent_budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                run_id TEXT,
                token_limit INTEGER,
                token_used INTEGER DEFAULT 0,
                cost_limit_cents INTEGER,
                cost_used_cents INTEGER DEFAULT 0,
                alert_threshold_pct INTEGER DEFAULT 90,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_agent_budgets_agent ON agent_budgets(agent_id);
            CREATE INDEX idx_agent_budgets_run ON agent_budgets(run_id);

            -- Execution runs (sprint-level tracking)
            CREATE TABLE execution_runs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                sprint_id TEXT,
                status TEXT DEFAULT 'pending',
                governance_config TEXT,
                total_budget_cents INTEGER,
                total_spent_cents INTEGER DEFAULT 0,
                agent_count INTEGER DEFAULT 0,
                run_type TEXT DEFAULT 'sprint',
                goal TEXT,
                current_phase TEXT,
                config TEXT,
                clarification_question TEXT,
                clarification_answer TEXT,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_execution_runs_project ON execution_runs(project_id);
            CREATE INDEX idx_execution_runs_sprint ON execution_runs(sprint_id);
            CREATE INDEX idx_execution_runs_status ON execution_runs(status);

            -- Append-only audit log
            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                agent_id TEXT,
                run_id TEXT,
                action_type TEXT NOT NULL,
                target_entity TEXT,
                outcome TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX idx_audit_log_project ON audit_log(project_id);
            CREATE INDEX idx_audit_log_agent ON audit_log(agent_id);
            CREATE INDEX idx_audit_log_run ON audit_log(run_id);
            CREATE INDEX idx_audit_log_action ON audit_log(action_type);

            -- Task claims (work-pickup: one active claim per task)
            CREATE TABLE task_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                released_at TIMESTAMP,
                status TEXT DEFAULT 'active',
                release_reason TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_task_claims_task ON task_claims(task_id);
            CREATE INDEX idx_task_claims_agent ON task_claims(agent_id);
            CREATE INDEX idx_task_claims_status ON task_claims(status);
            CREATE UNIQUE INDEX idx_task_claims_active ON task_claims(task_id) WHERE status = 'active';

            -- Agent messages (inter-agent communication)
            CREATE TABLE agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_agent_id TEXT NOT NULL,
                to_agent_id TEXT NOT NULL,
                message_type TEXT NOT NULL,
                content TEXT NOT NULL,
                related_task_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                read_at TIMESTAMP,
                FOREIGN KEY (from_agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                FOREIGN KEY (to_agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                FOREIGN KEY (related_task_id) REFERENCES tasks(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_agent_messages_to ON agent_messages(to_agent_id);
            CREATE INDEX idx_agent_messages_from ON agent_messages(from_agent_id);
            CREATE INDEX idx_agent_messages_task ON agent_messages(related_task_id);

            -- Agent performance tracking per sprint
            CREATE TABLE agent_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                sprint_id TEXT,
                tasks_completed INTEGER DEFAULT 0,
                tasks_failed INTEGER DEFAULT 0,
                avg_quality_score REAL,
                avg_completion_time_min REAL,
                corrections_count INTEGER DEFAULT 0,
                review_pass_rate REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agent_id, sprint_id),
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_agent_perf_agent ON agent_performance(agent_id);
            CREATE INDEX idx_agent_perf_sprint ON agent_performance(sprint_id);

            -- Agent teams
            CREATE TABLE agent_teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                project_id TEXT NOT NULL,
                lead_agent_id TEXT,
                sprint_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (lead_agent_id) REFERENCES agents(id) ON DELETE SET NULL,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_agent_teams_project ON agent_teams(project_id);
            CREATE INDEX idx_agent_teams_lead ON agent_teams(lead_agent_id);
            CREATE INDEX idx_agent_teams_sprint ON agent_teams(sprint_id);

            -- Requirements traceability
            CREATE TABLE requirements (
                id TEXT PRIMARY KEY,
                prd_id TEXT NOT NULL,
                req_type TEXT NOT NULL,
                req_number TEXT NOT NULL,
                summary TEXT NOT NULL,
                depth TEXT DEFAULT 'structural',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(prd_id, req_number),
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_requirements_prd ON requirements(prd_id);
            CREATE INDEX idx_requirements_type ON requirements(req_type);

            -- Requirement-to-task links
            CREATE TABLE requirement_links (
                requirement_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (requirement_id, task_id),
                FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            -- Acceptance-criteria verification evidence
            CREATE TABLE ac_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                verified_by TEXT,
                evidence_type TEXT,
                evidence TEXT,
                verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(requirement_id, task_id),
                FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_ac_verifications_task ON ac_verifications(task_id);

            -- Challenge records (adversarial review rounds)
            CREATE TABLE challenge_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artifact_type TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                objections TEXT,
                responses TEXT,
                verdict TEXT,
                challenger_context TEXT,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(artifact_type, artifact_id, round_number)
            );
            CREATE INDEX idx_challenge_artifact ON challenge_records(artifact_type, artifact_id);

            -- Work queue (agent work items per execution run)
            CREATE TABLE work_queue (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                work_type TEXT NOT NULL,
                artifact_type TEXT,
                artifact_id TEXT,
                status TEXT DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                depends_on TEXT,
                assigned_agent_id TEXT,
                config TEXT,
                result TEXT,
                retry_count INTEGER DEFAULT 0,
                pid INTEGER,
                log_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES execution_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (assigned_agent_id) REFERENCES agents(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_work_queue_run ON work_queue(run_id);
            CREATE INDEX idx_work_queue_status ON work_queue(status);
            CREATE INDEX idx_work_queue_run_status ON work_queue(run_id, status);
            CREATE INDEX idx_work_queue_project ON work_queue(project_id);

            -- Artifact threads (convergence discussion per artifact)
            CREATE TABLE artifact_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                agent_id TEXT,
                agent_persona TEXT,
                round_number INTEGER DEFAULT 1,
                entry_type TEXT NOT NULL,
                content TEXT,
                parent_thread_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES execution_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL,
                FOREIGN KEY (parent_thread_id) REFERENCES artifact_threads(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_artifact_threads_run ON artifact_threads(run_id);
            CREATE INDEX idx_artifact_threads_artifact ON artifact_threads(artifact_type, artifact_id);
            CREATE INDEX idx_artifact_threads_run_artifact ON artifact_threads(run_id, artifact_type, artifact_id);
            CREATE INDEX idx_artifact_threads_entry_type ON artifact_threads(entry_type);
            CREATE INDEX idx_artifact_threads_parent ON artifact_threads(parent_thread_id);
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

            if current_version == 8:
                self._migrate_v8_to_v9(conn)
                current_version = 9

            if current_version == 9:
                self._migrate_v9_to_v10(conn)
                current_version = 10

            if current_version == 10:
                self._migrate_v10_to_v11(conn)
                current_version = 11

            if current_version == 11:
                self._migrate_v11_to_v12(conn)
                current_version = 12

            if current_version == 12:
                self._migrate_v12_to_v13(conn)
                current_version = 13

            if current_version == 13:
                self._migrate_v13_to_v14(conn)
                current_version = 14
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

    def _migrate_v8_to_v9(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 8 to version 9 (add agent governance tables).

        Creates 5 tables for agent governance:
        - agents: Agent registry
        - agent_permissions: Permission scopes per agent
        - agent_budgets: Budget tracking per agent per run
        - execution_runs: Sprint-level execution tracking
        - audit_log: Append-only audit trail
        """
        conn.executescript("""
            -- Agent registry
            CREATE TABLE IF NOT EXISTS agents (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                persona_type TEXT NOT NULL,
                display_name TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                permissions_profile TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_by TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_agents_project ON agents(project_id);
            CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
            CREATE INDEX IF NOT EXISTS idx_agents_persona ON agents(persona_type);

            -- Permission scopes per agent
            CREATE TABLE IF NOT EXISTS agent_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                permission_type TEXT NOT NULL,
                permission_value TEXT NOT NULL,
                allowed INTEGER DEFAULT 1,
                UNIQUE(agent_id, permission_type, permission_value),
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_agent_perms_agent ON agent_permissions(agent_id);

            -- Budget tracking per agent per run
            CREATE TABLE IF NOT EXISTS agent_budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                run_id TEXT,
                token_limit INTEGER,
                token_used INTEGER DEFAULT 0,
                cost_limit_cents INTEGER,
                cost_used_cents INTEGER DEFAULT 0,
                alert_threshold_pct INTEGER DEFAULT 90,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_agent_budgets_agent ON agent_budgets(agent_id);
            CREATE INDEX IF NOT EXISTS idx_agent_budgets_run ON agent_budgets(run_id);

            -- Execution runs (sprint-level tracking)
            CREATE TABLE IF NOT EXISTS execution_runs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                sprint_id TEXT,
                status TEXT DEFAULT 'pending',
                governance_config TEXT,
                total_budget_cents INTEGER,
                total_spent_cents INTEGER DEFAULT 0,
                agent_count INTEGER DEFAULT 0,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_execution_runs_project ON execution_runs(project_id);
            CREATE INDEX IF NOT EXISTS idx_execution_runs_sprint ON execution_runs(sprint_id);
            CREATE INDEX IF NOT EXISTS idx_execution_runs_status ON execution_runs(status);

            -- Append-only audit log
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                agent_id TEXT,
                run_id TEXT,
                action_type TEXT NOT NULL,
                target_entity TEXT,
                outcome TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_audit_log_project ON audit_log(project_id);
            CREATE INDEX IF NOT EXISTS idx_audit_log_agent ON audit_log(agent_id);
            CREATE INDEX IF NOT EXISTS idx_audit_log_run ON audit_log(run_id);
            CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action_type);
        """)
        conn.execute("UPDATE schema_version SET version = 9")

    def _migrate_v9_to_v10(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 9 to version 10 (add task claims and agent messaging).

        Changes:
        - ALTER tasks: add assigned_agent_id column
        - CREATE task_claims: work-pickup with one active claim per task
        - CREATE agent_messages: inter-agent communication
        """
        # Add assigned_agent_id to tasks (SQLite ALTER TABLE doesn't support REFERENCES)
        conn.execute("ALTER TABLE tasks ADD COLUMN assigned_agent_id TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_assigned_agent ON tasks(assigned_agent_id)"
        )

        conn.executescript("""
            -- Task claims (work-pickup: one active claim per task)
            CREATE TABLE IF NOT EXISTS task_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                released_at TIMESTAMP,
                status TEXT DEFAULT 'active',
                release_reason TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_task_claims_task ON task_claims(task_id);
            CREATE INDEX IF NOT EXISTS idx_task_claims_agent ON task_claims(agent_id);
            CREATE INDEX IF NOT EXISTS idx_task_claims_status ON task_claims(status);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_task_claims_active ON task_claims(task_id) WHERE status = 'active';

            -- Agent messages (inter-agent communication)
            CREATE TABLE IF NOT EXISTS agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_agent_id TEXT NOT NULL,
                to_agent_id TEXT NOT NULL,
                message_type TEXT NOT NULL,
                content TEXT NOT NULL,
                related_task_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                read_at TIMESTAMP,
                FOREIGN KEY (from_agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                FOREIGN KEY (to_agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                FOREIGN KEY (related_task_id) REFERENCES tasks(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agent_messages_to ON agent_messages(to_agent_id);
            CREATE INDEX IF NOT EXISTS idx_agent_messages_from ON agent_messages(from_agent_id);
            CREATE INDEX IF NOT EXISTS idx_agent_messages_task ON agent_messages(related_task_id);
        """)
        conn.execute("UPDATE schema_version SET version = 10")

    def _migrate_v10_to_v11(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 10 to version 11 (add agent org structure).

        Changes:
        - ALTER agents: add team_id, reports_to_agent_id, hired_at,
          suspended_at, retired_at, performance_score columns
        - CREATE agent_performance: per-sprint performance metrics
        - CREATE agent_teams: team groupings per project
        """
        # Add 6 new columns to agents table
        conn.execute("ALTER TABLE agents ADD COLUMN team_id TEXT")
        conn.execute("ALTER TABLE agents ADD COLUMN reports_to_agent_id TEXT")
        conn.execute(
            "ALTER TABLE agents ADD COLUMN hired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        )
        conn.execute("ALTER TABLE agents ADD COLUMN suspended_at TIMESTAMP")
        conn.execute("ALTER TABLE agents ADD COLUMN retired_at TIMESTAMP")
        conn.execute(
            "ALTER TABLE agents ADD COLUMN performance_score REAL DEFAULT 50.0"
        )

        conn.executescript("""
            -- Agent performance tracking per sprint
            CREATE TABLE IF NOT EXISTS agent_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                sprint_id TEXT,
                tasks_completed INTEGER DEFAULT 0,
                tasks_failed INTEGER DEFAULT 0,
                avg_quality_score REAL,
                avg_completion_time_min REAL,
                corrections_count INTEGER DEFAULT 0,
                review_pass_rate REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agent_id, sprint_id),
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agent_perf_agent ON agent_performance(agent_id);
            CREATE INDEX IF NOT EXISTS idx_agent_perf_sprint ON agent_performance(sprint_id);

            -- Agent teams (sprint_id added in v13 migration for existing DBs)
            CREATE TABLE IF NOT EXISTS agent_teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                project_id TEXT NOT NULL,
                lead_agent_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (lead_agent_id) REFERENCES agents(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agent_teams_project ON agent_teams(project_id);
            CREATE INDEX IF NOT EXISTS idx_agent_teams_lead ON agent_teams(lead_agent_id);
        """)
        conn.execute("UPDATE schema_version SET version = 11")

    def _migrate_v11_to_v12(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 11 to version 12 (quality & traceability).

        Changes:
        - CREATE requirements: requirement traceability per PRD
        - CREATE requirement_links: many-to-many requirement <-> task
        - CREATE ac_verifications: acceptance-criteria verification evidence
        - CREATE challenge_records: adversarial review rounds
        """
        conn.executescript("""
            -- Requirements traceability
            CREATE TABLE IF NOT EXISTS requirements (
                id TEXT PRIMARY KEY,
                prd_id TEXT NOT NULL,
                req_type TEXT NOT NULL,
                req_number TEXT NOT NULL,
                summary TEXT NOT NULL,
                depth TEXT DEFAULT 'structural',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(prd_id, req_number),
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_requirements_prd ON requirements(prd_id);
            CREATE INDEX IF NOT EXISTS idx_requirements_type ON requirements(req_type);

            -- Requirement-to-task links
            CREATE TABLE IF NOT EXISTS requirement_links (
                requirement_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (requirement_id, task_id),
                FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            -- Acceptance-criteria verification evidence
            CREATE TABLE IF NOT EXISTS ac_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                verified_by TEXT,
                evidence_type TEXT,
                evidence TEXT,
                verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(requirement_id, task_id),
                FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_ac_verifications_task ON ac_verifications(task_id);

            -- Challenge records (adversarial review rounds)
            CREATE TABLE IF NOT EXISTS challenge_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artifact_type TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                objections TEXT,
                responses TEXT,
                verdict TEXT,
                challenger_context TEXT,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(artifact_type, artifact_id, round_number)
            );
            CREATE INDEX IF NOT EXISTS idx_challenge_artifact ON challenge_records(artifact_type, artifact_id);
        """)
        conn.execute("UPDATE schema_version SET version = 12")

    def _migrate_v12_to_v13(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 12 to version 13 (sprint-scoped teams).

        Changes:
        - ADD sprint_id nullable FK to agent_teams table
        - ADD index on agent_teams(sprint_id)
        """
        conn.execute(
            "ALTER TABLE agent_teams ADD COLUMN sprint_id TEXT "
            "REFERENCES sprints(id) ON DELETE SET NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_teams_sprint "
            "ON agent_teams(sprint_id)"
        )
        conn.execute("UPDATE schema_version SET version = 13")

    def _migrate_v13_to_v14(self, conn: sqlite3.Connection) -> None:
        """Migrate database from version 13 to version 14 (work queue & artifact threads).

        Changes:
        - CREATE work_queue: Agent work items per execution run
        - CREATE artifact_threads: Convergence discussion per artifact
        - ALTER execution_runs: Add run_type, goal, current_phase, config,
          clarification_question, clarification_answer columns
        """
        # Create work_queue table
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS work_queue (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                work_type TEXT NOT NULL,
                artifact_type TEXT,
                artifact_id TEXT,
                status TEXT DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                depends_on TEXT,
                assigned_agent_id TEXT,
                config TEXT,
                result TEXT,
                retry_count INTEGER DEFAULT 0,
                pid INTEGER,
                log_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES execution_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (assigned_agent_id) REFERENCES agents(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_work_queue_run ON work_queue(run_id);
            CREATE INDEX IF NOT EXISTS idx_work_queue_status ON work_queue(status);
            CREATE INDEX IF NOT EXISTS idx_work_queue_run_status ON work_queue(run_id, status);
            CREATE INDEX IF NOT EXISTS idx_work_queue_project ON work_queue(project_id);

            CREATE TABLE IF NOT EXISTS artifact_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                agent_id TEXT,
                agent_persona TEXT,
                round_number INTEGER DEFAULT 1,
                entry_type TEXT NOT NULL,
                content TEXT,
                parent_thread_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES execution_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL,
                FOREIGN KEY (parent_thread_id) REFERENCES artifact_threads(id) ON DELETE SET NULL
            );
            CREATE INDEX IF NOT EXISTS idx_artifact_threads_run ON artifact_threads(run_id);
            CREATE INDEX IF NOT EXISTS idx_artifact_threads_artifact ON artifact_threads(artifact_type, artifact_id);
            CREATE INDEX IF NOT EXISTS idx_artifact_threads_run_artifact ON artifact_threads(run_id, artifact_type, artifact_id);
            CREATE INDEX IF NOT EXISTS idx_artifact_threads_entry_type ON artifact_threads(entry_type);
            CREATE INDEX IF NOT EXISTS idx_artifact_threads_parent ON artifact_threads(parent_thread_id);
        """)

        # Extend execution_runs with pipeline columns
        conn.execute(
            "ALTER TABLE execution_runs ADD COLUMN run_type TEXT DEFAULT 'sprint'"
        )
        conn.execute(
            "ALTER TABLE execution_runs ADD COLUMN goal TEXT"
        )
        conn.execute(
            "ALTER TABLE execution_runs ADD COLUMN current_phase TEXT"
        )
        conn.execute(
            "ALTER TABLE execution_runs ADD COLUMN config TEXT"
        )
        conn.execute(
            "ALTER TABLE execution_runs ADD COLUMN clarification_question TEXT"
        )
        conn.execute(
            "ALTER TABLE execution_runs ADD COLUMN clarification_answer TEXT"
        )

        conn.execute("UPDATE schema_version SET version = 14")

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections.

        Yields:
            sqlite3.Connection with row factory set to sqlite3.Row
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
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

    def get_next_agent_id(self, project_id: str) -> str:
        """Generate next agent ID for a project.

        Format: {shortname}-A{number:03d} (e.g., PCRA-A001)
        Uses project shortname for compact, Jira-style IDs.
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        shortname = project["shortname"]

        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM agents WHERE project_id = ?", (project_id,)
            )
            count = cursor.fetchone()[0]
        return f"{shortname}-A{count + 1:03d}"

    def get_next_run_id(self, project_id: str) -> str:
        """Generate next execution run ID for a project.

        Format: {shortname}-R{number:03d} (e.g., PCRA-R001)
        Uses project shortname for compact, Jira-style IDs.
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        shortname = project["shortname"]

        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM execution_runs WHERE project_id = ?", (project_id,)
            )
            count = cursor.fetchone()[0]
        return f"{shortname}-R{count + 1:03d}"

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

    # =========================================================================
    # Agent & Governance Operations
    # =========================================================================

    # --- Agent methods ---

    def create_agent(
        self,
        agent_id: str,
        project_id: str,
        persona_type: str,
        display_name: str,
        status: str = "active",
        permissions_profile: str | None = None,
        approved_by: str | None = None,
    ) -> dict[str, Any]:
        """Create a new agent record.

        Args:
            agent_id: Unique agent identifier (e.g., PCRA-A001).
            project_id: Parent project ID.
            persona_type: Agent persona type (e.g., 'backend-engineer').
            display_name: Human-readable name for the agent.
            status: Initial status ('active', 'suspended', 'retired').
            permissions_profile: Optional permissions profile name.
            approved_by: Optional ID of the approving entity.

        Returns:
            Created agent dict.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO agents
                   (id, project_id, persona_type, display_name, status,
                    permissions_profile, created_at, approved_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (agent_id, project_id, persona_type, display_name,
                 status, permissions_profile, now, approved_by),
            )
        return self.get_agent(agent_id)

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Get an agent by ID.

        Args:
            agent_id: Agent identifier.

        Returns:
            Agent dict if found, None otherwise.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM agents WHERE id = ?", (agent_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_agents(
        self, project_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List agents for a project, optionally filtered by status.

        Args:
            project_id: Project identifier.
            status: Optional status filter ('active', 'suspended', 'retired').

        Returns:
            List of agent dicts ordered by created_at descending.
        """
        query = "SELECT * FROM agents WHERE project_id = ?"
        params: list[Any] = [project_id]

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC"

        with self.connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def update_agent_status(
        self, agent_id: str, status: str, reason: str | None = None
    ) -> dict[str, Any] | None:
        """Update agent status (active/suspended/retired).

        Args:
            agent_id: Agent identifier.
            status: New status value.
            reason: Optional reason for the status change (logged but not stored
                    in the agents table; callers should persist via audit log).

        Returns:
            Updated agent dict, or None if not found.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE agents SET status = ? WHERE id = ?",
                (status, agent_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_agent(agent_id)

    def update_agent(self, agent_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update agent fields dynamically.

        Only updates columns that exist in the agents table:
        persona_type, display_name, status, permissions_profile, approved_by.

        Note: The agents table does NOT have an updated_at column.

        Args:
            agent_id: Agent identifier.
            **kwargs: Fields to update.

        Returns:
            Updated agent dict, or None if not found.
        """
        if not kwargs:
            return self.get_agent(agent_id)

        # Only allow columns that exist in the agents table
        allowed_columns = {
            "persona_type", "display_name", "status",
            "permissions_profile", "approved_by",
        }
        filtered = {k: v for k, v in kwargs.items() if k in allowed_columns}
        if not filtered:
            return self.get_agent(agent_id)

        fields = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [agent_id]

        with self.connection() as conn:
            conn.execute(f"UPDATE agents SET {fields} WHERE id = ?", values)
        return self.get_agent(agent_id)

    def delete_agent(self, agent_id: str) -> bool:
        """Soft-delete an agent by setting status to 'retired'.

        This is a soft delete: the agent record remains in the database
        with status='retired' so that audit log references stay valid.

        Args:
            agent_id: Agent identifier.

        Returns:
            True if retired, False if not found.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE agents SET status = 'retired' WHERE id = ?",
                (agent_id,),
            )
            return cursor.rowcount > 0

    # --- Permission methods ---

    def set_agent_permission(
        self,
        agent_id: str,
        permission_type: str,
        permission_value: str,
        allowed: int = 1,
    ) -> dict[str, Any]:
        """Set or update a permission for an agent.

        Uses INSERT OR REPLACE to upsert based on the unique constraint
        (agent_id, permission_type, permission_value).

        Args:
            agent_id: Agent identifier.
            permission_type: Permission category (e.g., 'tool', 'file_path').
            permission_value: Specific permission value (e.g., 'git_push', '/src/').
            allowed: 1 for allowed, 0 for denied.

        Returns:
            The permission record dict.
        """
        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO agent_permissions
                   (agent_id, permission_type, permission_value, allowed)
                   VALUES (?, ?, ?, ?)""",
                (agent_id, permission_type, permission_value, allowed),
            )
            cursor = conn.execute(
                """SELECT * FROM agent_permissions
                   WHERE agent_id = ? AND permission_type = ? AND permission_value = ?""",
                (agent_id, permission_type, permission_value),
            )
            return dict(cursor.fetchone())

    def check_agent_permission(
        self, agent_id: str, permission_type: str, permission_value: str
    ) -> bool:
        """Check if agent has a specific permission.

        Default-deny: if no explicit row exists, returns False.

        Args:
            agent_id: Agent identifier.
            permission_type: Permission category.
            permission_value: Specific permission value.

        Returns:
            True if allowed=1, False if allowed=0 or not found.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                """SELECT allowed FROM agent_permissions
                   WHERE agent_id = ? AND permission_type = ? AND permission_value = ?""",
                (agent_id, permission_type, permission_value),
            )
            row = cursor.fetchone()
            if row is None:
                return False  # default-deny
            return bool(row["allowed"])

    def get_agent_permissions(self, agent_id: str) -> list[dict[str, Any]]:
        """Get all permissions for an agent.

        Args:
            agent_id: Agent identifier.

        Returns:
            List of permission dicts.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM agent_permissions WHERE agent_id = ?",
                (agent_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # --- Budget methods ---

    def create_agent_budget(
        self,
        agent_id: str,
        run_id: str | None = None,
        token_limit: int | None = None,
        cost_limit_cents: int | None = None,
        alert_threshold_pct: int = 90,
    ) -> dict[str, Any]:
        """Create a budget record for an agent.

        Args:
            agent_id: Agent identifier.
            run_id: Optional execution run to scope the budget to.
            token_limit: Optional maximum token usage.
            cost_limit_cents: Optional maximum cost in cents.
            alert_threshold_pct: Percentage threshold for budget alerts (default 90).

        Returns:
            Created budget dict.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO agent_budgets
                   (agent_id, run_id, token_limit, token_used, cost_limit_cents,
                    cost_used_cents, alert_threshold_pct, created_at, updated_at)
                   VALUES (?, ?, ?, 0, ?, 0, ?, ?, ?)""",
                (agent_id, run_id, token_limit, cost_limit_cents,
                 alert_threshold_pct, now, now),
            )
            budget_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM agent_budgets WHERE id = ?", (budget_id,)
            ).fetchone()
            return dict(row)

    def get_agent_budget(
        self, agent_id: str, run_id: str | None = None
    ) -> dict[str, Any] | None:
        """Get budget for an agent, optionally filtered by run.

        When run_id is provided, returns the budget for that specific run.
        When run_id is None, returns the most recent budget for the agent.

        Args:
            agent_id: Agent identifier.
            run_id: Optional execution run filter. If None, returns most recent.

        Returns:
            Budget dict if found, None otherwise.
        """
        if run_id is not None:
            query = "SELECT * FROM agent_budgets WHERE agent_id = ? AND run_id = ?"
            params: list[Any] = [agent_id, run_id]
        else:
            query = "SELECT * FROM agent_budgets WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1"
            params = [agent_id]

        with self.connection() as conn:
            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_agent_budget(
        self,
        budget_id: int,
        token_used_delta: int = 0,
        cost_used_delta: int = 0,
    ) -> dict[str, Any] | None:
        """Update budget usage with delta values.

        Args:
            budget_id: Budget record ID.
            token_used_delta: Tokens to add to token_used.
            cost_used_delta: Cents to add to cost_used_cents.

        Returns:
            Updated budget dict, or None if not found.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """UPDATE agent_budgets SET
                   token_used = token_used + ?,
                   cost_used_cents = cost_used_cents + ?,
                   updated_at = ?
                   WHERE id = ?""",
                (token_used_delta, cost_used_delta, now, budget_id),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM agent_budgets WHERE id = ?", (budget_id,)
            ).fetchone()
            return dict(row)

    def increment_agent_budget(
        self,
        agent_id: str,
        tokens_delta: int = 0,
        cost_delta_cents: int = 0,
        run_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Atomically increment an agent's budget usage counters (REM-004).

        Finds the agent's budget record (optionally scoped to *run_id*) and
        atomically adds the deltas.  This is the preferred method for agents
        to report consumption because it handles the lookup-and-update in a
        single transaction.

        Args:
            agent_id: Agent identifier.
            tokens_delta: Tokens to add to ``token_used``.
            cost_delta_cents: Cents to add to ``cost_used_cents``.
            run_id: Optional run scope.  When ``None``, updates the most
                recent budget record for the agent.

        Returns:
            Updated budget dict, or ``None`` if no budget record exists.
        """
        budget = self.get_agent_budget(agent_id, run_id=run_id)
        if not budget:
            return None
        return self.update_agent_budget(
            budget["id"],
            token_used_delta=tokens_delta,
            cost_used_delta=cost_delta_cents,
        )

    # --- Execution run methods ---

    def create_execution_run(
        self,
        run_id: str,
        project_id: str,
        sprint_id: str | None = None,
        status: str = "pending",
        run_type: str = "sprint",
        goal: str | None = None,
        current_phase: str | None = None,
        config: str | None = None,
        governance_config: str | None = None,
        total_budget_cents: int | None = None,
        agent_count: int = 0,
    ) -> dict[str, Any]:
        """Create an execution run record.

        Args:
            run_id: Unique run identifier (e.g., PCRA-R001).
            project_id: Parent project ID.
            sprint_id: Optional sprint this run belongs to.
            status: Initial status ('pending', 'running', 'completed', 'failed').
            run_type: Type of run ('sprint', 'task', 'objective').
            goal: Optional objective/goal description.
            current_phase: Optional current phase.
            config: Optional JSON configuration.
            governance_config: Optional JSON string of governance settings.
            total_budget_cents: Optional total budget in cents.
            agent_count: Number of agents in this run.

        Returns:
            Created execution run dict.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO execution_runs
                   (id, project_id, sprint_id, status, run_type, goal,
                    current_phase, config, governance_config,
                    total_budget_cents, total_spent_cents, agent_count, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (run_id, project_id, sprint_id, status, run_type, goal,
                 current_phase, config, governance_config,
                 total_budget_cents, agent_count, now),
            )
        return self.get_execution_run(run_id)

    def get_execution_run(self, run_id: str) -> dict[str, Any] | None:
        """Get an execution run by ID.

        Args:
            run_id: Run identifier.

        Returns:
            Execution run dict if found, None otherwise.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM execution_runs WHERE id = ?", (run_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_execution_run(self, run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update execution run fields dynamically.

        Supported fields: status, total_spent_cents, agent_count,
        started_at, completed_at, governance_config, total_budget_cents.

        Args:
            run_id: Run identifier.
            **kwargs: Fields to update.

        Returns:
            Updated execution run dict, or None if not found.
        """
        if not kwargs:
            return self.get_execution_run(run_id)

        allowed_columns = {
            "status", "total_spent_cents", "agent_count",
            "started_at", "completed_at", "governance_config",
            "total_budget_cents", "run_type", "goal",
            "current_phase", "config", "clarification_question",
            "clarification_answer",
        }
        filtered = {k: v for k, v in kwargs.items() if k in allowed_columns}
        if not filtered:
            return self.get_execution_run(run_id)

        fields = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [run_id]

        with self.connection() as conn:
            cursor = conn.execute(
                f"UPDATE execution_runs SET {fields} WHERE id = ?", values
            )
            if cursor.rowcount == 0:
                return None
        return self.get_execution_run(run_id)

    def list_execution_runs(
        self,
        project_id: str,
        run_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List execution runs for a project with optional filters.

        Args:
            project_id: Project identifier.
            run_type: Optional run type filter.
            status: Optional status filter.

        Returns:
            List of execution run dicts ordered by created_at descending.
        """
        query = "SELECT * FROM execution_runs WHERE project_id = ?"
        params: list[Any] = [project_id]

        if run_type is not None:
            query += " AND run_type = ?"
            params.append(run_type)

        if status is not None:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC"

        with self.connection() as conn:
            rows = conn.execute(query, params)
            return [dict(row) for row in rows.fetchall()]

    def get_execution_run_detail(self, run_id: str) -> dict[str, Any] | None:
        """Get an execution run by ID with summary stats."""
        run = self.get_execution_run(run_id)
        if not run:
            return None

        run_dict = dict(run)
        run_dict["queue_summary"] = self.count_work_items_by_status(run_id)
        run_dict["thread_count"] = self.count_thread_entries(run_id)
        return run_dict

    def count_work_items_by_status(self, run_id: str) -> dict[str, int]:
        """Count work items by status for a run."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT status, COUNT(*) as count FROM work_queue WHERE run_id = ? GROUP BY status",
                (run_id,),
            )
            return {row["status"]: row["count"] for row in cursor.fetchall()}

    def count_thread_entries(self, run_id: str) -> int:
        """Count total thread entries for a run."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM artifact_threads WHERE run_id = ?",
                (run_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def get_recent_thread_entries(self, run_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent thread entries across all artifacts for a run."""
        with self.connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM artifact_threads
                   WHERE run_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (run_id, limit),
            )
            return [dict(row) for row in cursor.fetchall()]

    def list_work_queue_items(
        self,
        run_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List work queue items for a run, optionally filtered by status.

        Args:
            run_id: Execution run identifier.
            status: Optional status filter.

        Returns:
            List of work queue item dicts ordered by priority, created_at.
        """
        query = "SELECT * FROM work_queue WHERE run_id = ?"
        params: list[Any] = [run_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY priority DESC, created_at"
        with self.connection() as conn:
            rows = conn.execute(query, params)
            return [dict(row) for row in rows.fetchall()]

    def get_work_queue_item(self, item_id: str) -> dict[str, Any] | None:
        """Get a single work queue item by ID.

        Args:
            item_id: Work queue item identifier.

        Returns:
            Work queue item dict, or None if not found.
        """
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM work_queue WHERE id = ?", (item_id,)
            ).fetchone()
            return dict(row) if row else None

    def update_work_queue_item(
        self, item_id: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        """Update work queue item fields dynamically.

        Supported fields: status, assigned_agent_id, result, retry_count,
        pid, log_path, started_at, completed_at, config.

        Args:
            item_id: Work queue item identifier.
            **kwargs: Fields to update.

        Returns:
            Updated work queue item dict, or None if not found.
        """
        if not kwargs:
            return self.get_work_queue_item(item_id)

        allowed_columns = {
            "status", "assigned_agent_id", "result", "retry_count",
            "pid", "log_path", "started_at", "completed_at", "config",
        }
        filtered = {k: v for k, v in kwargs.items() if k in allowed_columns}
        if not filtered:
            return self.get_work_queue_item(item_id)

        fields = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [item_id]

        with self.connection() as conn:
            cursor = conn.execute(
                f"UPDATE work_queue SET {fields} WHERE id = ?", values
            )
            if cursor.rowcount == 0:
                return None
        return self.get_work_queue_item(item_id)

    def create_work_queue_item(
        self,
        item_id: str,
        run_id: str,
        project_id: str,
        work_type: str,
        artifact_type: str | None = None,
        artifact_id: str | None = None,
        status: str = "pending",
        priority: int = 0,
        depends_on: str | None = None,
        assigned_agent_id: str | None = None,
        config: str | None = None,
    ) -> dict[str, Any]:
        """Create a work queue item.

        Args:
            item_id: Unique work item identifier.
            run_id: Parent execution run ID.
            project_id: Parent project ID.
            work_type: Type of work (e.g., 'prd_generate', 'task_implement').
            artifact_type: Optional artifact type being worked on.
            artifact_id: Optional artifact ID being worked on.
            status: Initial status (default 'pending').
            priority: Priority ordering (higher = more important).
            depends_on: Optional comma-separated list of item IDs this depends on.
            assigned_agent_id: Optional agent assigned to this item.
            config: Optional JSON config string.

        Returns:
            Created work queue item dict.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO work_queue
                   (id, run_id, project_id, work_type, artifact_type,
                    artifact_id, status, priority, depends_on,
                    assigned_agent_id, config, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item_id, run_id, project_id, work_type, artifact_type,
                 artifact_id, status, priority, depends_on,
                 assigned_agent_id, config, now),
            )
        return self.get_work_queue_item(item_id)

    # =========================================================================
    # Work Queue Advanced Operations
    # =========================================================================

    @staticmethod
    def _parse_work_item_row(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a work_queue row to a dict, deserializing JSON fields."""
        d = dict(row)
        for field in ("depends_on", "config"):
            if d.get(field):
                with contextlib.suppress(json.JSONDecodeError, TypeError):
                    d[field] = json.loads(d[field])
        return d

    @staticmethod
    def _parse_thread_entry_row(row: sqlite3.Row) -> dict[str, Any]:
        """Convert an artifact_threads row to a dict, deserializing JSON fields."""
        d = dict(row)
        if d.get("content"):
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                d["content"] = json.loads(d["content"])
        return d

    def get_next_work_item_id(self, project_id: str) -> str:
        """Generate next work item ID for a project.

        Format: {shortname}-W{number:05d} (e.g., PCRA-W00001)
        Uses project shortname for compact, Jira-style IDs.
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        shortname = project["shortname"]

        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM work_queue WHERE project_id = ?", (project_id,)
            )
            count = cursor.fetchone()[0]
        return f"{shortname}-W{count + 1:05d}"

    def create_work_item(
        self,
        run_id: str,
        project_id: str,
        work_type: str,
        artifact_type: str | None = None,
        artifact_id: str | None = None,
        status: str = "pending",
        priority: int = 0,
        depends_on: list[str] | str | None = None,
        config: dict[str, Any] | str | None = None,
        retry_count: int = 0,
    ) -> dict[str, Any]:
        """Create a work queue item with auto-generated ID.

        Args:
            run_id: Parent execution run ID.
            project_id: Parent project ID.
            work_type: Type of work (e.g., 'prd_generate', 'task_implement').
            artifact_type: Optional artifact type being worked on.
            artifact_id: Optional artifact ID being worked on.
            status: Initial status (default 'pending').
            priority: Priority ordering (higher = more important).
            depends_on: Optional list of item IDs this depends on.
            config: Optional configuration dict.
            retry_count: Initial retry count (default 0).

        Returns:
            Created work queue item dict with JSON fields deserialized.
        """
        item_id = self.get_next_work_item_id(project_id)

        # Serialize depends_on if it's a list
        depends_on_str: str | None = None
        if depends_on is not None:
            depends_on_str = (
                json.dumps(depends_on) if isinstance(depends_on, list) else depends_on
            )

        # Serialize config if it's a dict
        config_str: str | None = None
        if config is not None:
            config_str = json.dumps(config) if isinstance(config, dict) else config

        self.create_work_queue_item(
            item_id=item_id,
            run_id=run_id,
            project_id=project_id,
            work_type=work_type,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            status=status,
            priority=priority,
            depends_on=depends_on_str,
            config=config_str,
        )

        # Set retry_count if non-zero
        if retry_count:
            with self.connection() as conn:
                conn.execute(
                    "UPDATE work_queue SET retry_count = ? WHERE id = ?",
                    (retry_count, item_id),
                )

        return self.get_work_item(item_id)

    def get_work_item(self, item_id: str) -> dict[str, Any] | None:
        """Get a single work queue item by ID with JSON fields deserialized.

        Args:
            item_id: Work queue item identifier.

        Returns:
            Work queue item dict with deserialized JSON fields, or None if not found.
        """
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM work_queue WHERE id = ?", (item_id,)
            ).fetchone()
            if not row:
                return None
            return self._parse_work_item_row(row)

    def get_work_items(
        self,
        run_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List work queue items for a run with JSON fields deserialized.

        Args:
            run_id: Execution run identifier.
            status: Optional status filter.

        Returns:
            List of work queue item dicts ordered by priority DESC, created_at ASC.
        """
        query = "SELECT * FROM work_queue WHERE run_id = ?"
        params: list[Any] = [run_id]
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY priority DESC, created_at ASC"
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._parse_work_item_row(row) for row in rows]

    def update_work_item(
        self, item_id: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        """Update work queue item fields with JSON serialization and auto-timestamps.

        Extends the base update_work_queue_item with:
        - JSON serialization for depends_on (list) and config (dict)
        - Auto-sets started_at when status transitions to 'in_progress'
        - Auto-sets completed_at when status transitions to terminal states
        - Supports error_message (stored in result column) and result columns

        Args:
            item_id: Work queue item identifier.
            **kwargs: Fields to update.

        Returns:
            Updated work queue item dict with deserialized JSON, or None if not found.
        """
        if not kwargs:
            return self.get_work_item(item_id)

        now = datetime.now(timezone.utc).isoformat()

        # Map error_message to result column
        if "error_message" in kwargs:
            kwargs["result"] = kwargs.pop("error_message")

        # Serialize JSON fields
        if "depends_on" in kwargs and isinstance(kwargs["depends_on"], list):
            kwargs["depends_on"] = json.dumps(kwargs["depends_on"])
        if "config" in kwargs and isinstance(kwargs["config"], dict):
            kwargs["config"] = json.dumps(kwargs["config"])

        # Auto-set timestamps based on status transitions
        status = kwargs.get("status")
        if status == "in_progress" and "started_at" not in kwargs:
            kwargs["started_at"] = now
        terminal_states = {"completed", "failed", "cancelled", "skipped"}
        if status in terminal_states and "completed_at" not in kwargs:
            kwargs["completed_at"] = now

        allowed_columns = {
            "status", "assigned_agent_id", "result", "retry_count",
            "pid", "log_path", "started_at", "completed_at", "config",
            "depends_on", "priority",
        }
        filtered = {k: v for k, v in kwargs.items() if k in allowed_columns}
        if not filtered:
            return self.get_work_item(item_id)

        fields = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [item_id]

        with self.connection() as conn:
            cursor = conn.execute(
                f"UPDATE work_queue SET {fields} WHERE id = ?", values
            )
            if cursor.rowcount == 0:
                return None
        return self.get_work_item(item_id)

    def get_dispatchable_items(
        self, run_id: str, max_concurrent: int = 3
    ) -> list[dict[str, Any]]:
        """Get work items that are ready to be dispatched.

        An item is dispatchable if:
        1. Its status is 'pending'
        2. Its dependencies (depends_on) are all completed
        3. The number of currently in_progress items is below max_concurrent

        Args:
            run_id: Execution run identifier.
            max_concurrent: Maximum number of concurrent in_progress items.

        Returns:
            List of dispatchable work item dicts, up to available capacity.
        """
        with self.connection() as conn:
            # Count current in_progress items
            cursor = conn.execute(
                "SELECT COUNT(*) FROM work_queue WHERE run_id = ? AND status = 'in_progress'",
                (run_id,),
            )
            in_progress_count = cursor.fetchone()[0]

            if in_progress_count >= max_concurrent:
                return []

            available_slots = max_concurrent - in_progress_count

            # Fetch all pending items ordered by priority DESC, created_at ASC
            pending_rows = conn.execute(
                """SELECT * FROM work_queue
                   WHERE run_id = ? AND status = 'pending'
                   ORDER BY priority DESC, created_at ASC""",
                (run_id,),
            ).fetchall()

            # Fetch all completed item IDs into a set
            completed_rows = conn.execute(
                "SELECT id FROM work_queue WHERE run_id = ? AND status = 'completed'",
                (run_id,),
            ).fetchall()
            completed_ids = {row["id"] for row in completed_rows}

            # Filter: item is dispatchable if depends_on is empty or all deps completed
            dispatchable = []
            for row in pending_rows:
                if len(dispatchable) >= available_slots:
                    break

                parsed = self._parse_work_item_row(row)
                deps = parsed.get("depends_on")

                if deps is None or deps == [] or deps == "":
                    dispatchable.append(parsed)
                elif isinstance(deps, list):
                    if all(dep_id in completed_ids for dep_id in deps):
                        dispatchable.append(parsed)
                elif isinstance(deps, str):
                    # Might be a comma-separated string
                    dep_ids = [d.strip() for d in deps.split(",") if d.strip()]
                    if all(dep_id in completed_ids for dep_id in dep_ids):
                        dispatchable.append(parsed)

            return dispatchable

    def increment_retry_count(self, item_id: str) -> dict[str, Any] | None:
        """Atomically increment the retry count for a work item.

        Args:
            item_id: Work queue item identifier.

        Returns:
            Updated work queue item dict, or None if not found.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE work_queue SET retry_count = retry_count + 1 WHERE id = ?",
                (item_id,),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_work_item(item_id)

    # =========================================================================
    # Work Queue Per-Item Control
    # =========================================================================

    def pause_work_item(self, item_id: str) -> dict[str, Any]:
        """Pause a work item (pending/in_progress -> paused).

        Args:
            item_id: Work queue item identifier.

        Returns:
            Updated work queue item dict.

        Raises:
            ValueError: If item not found or transition is invalid.
        """
        item = self.get_work_item(item_id)
        if not item:
            raise ValueError(f"Work item not found: {item_id}")
        if item["status"] not in ("pending", "in_progress"):
            raise ValueError(
                f"Cannot pause item in '{item['status']}' state; "
                f"must be 'pending' or 'in_progress'"
            )
        return self.update_work_item(item_id, status="paused")

    def cancel_work_item(self, item_id: str) -> dict[str, Any]:
        """Cancel a work item (non-terminal -> cancelled).

        Args:
            item_id: Work queue item identifier.

        Returns:
            Updated work queue item dict.

        Raises:
            ValueError: If item not found or already in a terminal state.
        """
        item = self.get_work_item(item_id)
        if not item:
            raise ValueError(f"Work item not found: {item_id}")
        terminal_states = {"completed", "cancelled", "skipped"}
        if item["status"] in terminal_states:
            raise ValueError(
                f"Cannot cancel item in '{item['status']}' state; "
                f"already in a terminal state"
            )
        return self.update_work_item(item_id, status="cancelled")

    def skip_work_item(
        self, item_id: str, reason: str | None = None
    ) -> dict[str, Any]:
        """Skip a work item (pending/blocked -> skipped).

        Args:
            item_id: Work queue item identifier.
            reason: Optional reason for skipping.

        Returns:
            Updated work queue item dict.

        Raises:
            ValueError: If item not found or transition is invalid.
        """
        item = self.get_work_item(item_id)
        if not item:
            raise ValueError(f"Work item not found: {item_id}")
        if item["status"] not in ("pending", "blocked"):
            raise ValueError(
                f"Cannot skip item in '{item['status']}' state; "
                f"must be 'pending' or 'blocked'"
            )
        kwargs: dict[str, Any] = {"status": "skipped"}
        if reason:
            kwargs["result"] = reason
        return self.update_work_item(item_id, **kwargs)

    def force_approve_work_item(self, item_id: str) -> dict[str, Any]:
        """Force-approve a work item (any state -> completed with result='force_approved').

        Args:
            item_id: Work queue item identifier.

        Returns:
            Updated work queue item dict.

        Raises:
            ValueError: If item not found.
        """
        item = self.get_work_item(item_id)
        if not item:
            raise ValueError(f"Work item not found: {item_id}")
        return self.update_work_item(
            item_id, status="completed", result="force_approved"
        )

    def retry_work_item(self, item_id: str) -> dict[str, Any]:
        """Retry a work item (failed/blocked -> pending, increment retry, clear error).

        Args:
            item_id: Work queue item identifier.

        Returns:
            Updated work queue item dict.

        Raises:
            ValueError: If item not found or transition is invalid.
        """
        item = self.get_work_item(item_id)
        if not item:
            raise ValueError(f"Work item not found: {item_id}")
        if item["status"] not in ("failed", "blocked"):
            raise ValueError(
                f"Cannot retry item in '{item['status']}' state; "
                f"must be 'failed' or 'blocked'"
            )
        self.increment_retry_count(item_id)
        return self.update_work_item(
            item_id,
            status="pending",
            result=None,
            started_at=None,
            completed_at=None,
        )

    def answer_work_item(self, item_id: str, answer: str) -> dict[str, Any]:
        """Answer a question work item (question items only -> completed with result=answer).

        Args:
            item_id: Work queue item identifier.
            answer: The answer to store.

        Returns:
            Updated work queue item dict.

        Raises:
            ValueError: If item not found or not a question item.
        """
        item = self.get_work_item(item_id)
        if not item:
            raise ValueError(f"Work item not found: {item_id}")
        if item["work_type"] != "question":
            raise ValueError(
                f"Cannot answer item of type '{item['work_type']}'; "
                f"must be 'question'"
            )
        return self.update_work_item(
            item_id, status="completed", result=answer
        )

    # =========================================================================
    # Hierarchical Thread Operations
    # =========================================================================

    def get_hierarchical_thread(
        self,
        artifact_type: str,
        artifact_id: str,
        run_id: str,
    ) -> list[dict[str, Any]]:
        """Get thread entries across the sprint/PRD/task hierarchy.

        For a task, returns thread entries at sprint, PRD, and task levels.
        For a PRD, returns thread entries at sprint and PRD levels.
        For a sprint, returns only sprint-level entries.

        Each entry gets a 'hierarchy_level' key: 'sprint', 'prd', or 'task'.

        Args:
            artifact_type: Type of artifact ('sprint', 'prd', 'task').
            artifact_id: Artifact identifier.
            run_id: Execution run identifier.

        Returns:
            List of thread entry dicts ordered: sprint first, then prd, then task.
        """
        entries: list[dict[str, Any]] = []

        sprint_id: str | None = None
        prd_id: str | None = None

        if artifact_type == "task":
            # Look up task to get prd_id
            task = self.get_task(artifact_id)
            if task and task.get("prd_id"):
                prd_id = task["prd_id"]
                # Look up PRD to get sprint_id
                prd = self.get_prd(prd_id)
                if prd and prd.get("sprint_id"):
                    sprint_id = prd["sprint_id"]
        elif artifact_type == "prd":
            prd = self.get_prd(artifact_id)
            if prd and prd.get("sprint_id"):
                sprint_id = prd["sprint_id"]

        # Fetch sprint-level entries
        if sprint_id:
            sprint_entries = self.list_artifact_threads(
                run_id, artifact_type="sprint", artifact_id=sprint_id
            )
            for entry in sprint_entries:
                entry["hierarchy_level"] = "sprint"
                entries.append(entry)

        # Fetch PRD-level entries
        if prd_id:
            prd_entries = self.list_artifact_threads(
                run_id, artifact_type="prd", artifact_id=prd_id
            )
            for entry in prd_entries:
                entry["hierarchy_level"] = "prd"
                entries.append(entry)

        # Fetch artifact-level entries
        artifact_entries = self.list_artifact_threads(
            run_id, artifact_type=artifact_type, artifact_id=artifact_id
        )
        for entry in artifact_entries:
            entry["hierarchy_level"] = artifact_type
            entries.append(entry)

        return entries

    def create_artifact_thread_entry(
        self,
        run_id: str,
        project_id: str,
        artifact_type: str,
        artifact_id: str,
        entry_type: str,
        agent_id: str | None = None,
        agent_persona: str | None = None,
        round_number: int = 1,
        content: str | None = None,
        parent_thread_id: int | None = None,
    ) -> dict[str, Any]:
        """Create an artifact thread entry.

        Args:
            run_id: Parent execution run ID.
            project_id: Parent project ID.
            artifact_type: Type of artifact (e.g., 'prd', 'task', 'design').
            artifact_id: Artifact identifier.
            entry_type: Type of entry (e.g., 'creation', 'challenge', 'revision',
                        'approval', 'escalation', 'user_intervention').
            agent_id: Optional agent who created the entry.
            agent_persona: Optional persona label (e.g., 'pm', 'architect').
            round_number: Challenge round number (default 1).
            content: Optional markdown content.
            parent_thread_id: Optional parent thread entry for threading.

        Returns:
            Created thread entry dict.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO artifact_threads
                   (run_id, project_id, artifact_type, artifact_id,
                    agent_id, agent_persona, round_number, entry_type,
                    content, parent_thread_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, project_id, artifact_type, artifact_id,
                 agent_id, agent_persona, round_number, entry_type,
                 content, parent_thread_id, now),
            )
            entry_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM artifact_threads WHERE id = ?", (entry_id,)
            ).fetchone()
            return dict(row)

    def list_artifact_threads(
        self,
        run_id: str,
        artifact_type: str | None = None,
        artifact_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List artifact thread entries for a run.

        Args:
            run_id: Execution run identifier.
            artifact_type: Optional filter by artifact type.
            artifact_id: Optional filter by artifact ID.

        Returns:
            List of thread entry dicts ordered by created_at ascending.
        """
        query = "SELECT * FROM artifact_threads WHERE run_id = ?"
        params: list[Any] = [run_id]
        if artifact_type is not None:
            query += " AND artifact_type = ?"
            params.append(artifact_type)
        if artifact_id is not None:
            query += " AND artifact_id = ?"
            params.append(artifact_id)
        query += " ORDER BY created_at"
        with self.connection() as conn:
            rows = conn.execute(query, params)
            return [dict(row) for row in rows.fetchall()]

    def list_artifact_threads_by_artifact(
        self,
        artifact_type: str,
        artifact_id: str,
    ) -> list[dict[str, Any]]:
        """List artifact thread entries for a specific artifact across all runs.

        Args:
            artifact_type: Artifact type (e.g. 'prd', 'task', 'sprint').
            artifact_id: Artifact identifier.

        Returns:
            List of thread entry dicts ordered by created_at ascending.
        """
        query = (
            "SELECT * FROM artifact_threads "
            "WHERE artifact_type = ? AND artifact_id = ? "
            "ORDER BY created_at"
        )
        with self.connection() as conn:
            rows = conn.execute(query, (artifact_type, artifact_id))
            return [dict(row) for row in rows.fetchall()]

    def get_run_state_hash(self, run_id: str) -> str:
        """Get a hash representing the current state of a run.

        Includes run status, work items status/count, and thread entry count.
        Used by the UI for fast change detection (WebSockets/polling).

        Args:
            run_id: Execution run identifier.

        Returns:
            A hash string (SHA1 hexdigest).
        """
        import hashlib

        with self.connection() as conn:
            # 1. Get run status and metadata
            run = conn.execute(
                "SELECT status, current_phase, total_spent_cents FROM execution_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if not run:
                return ""

            # 2. Get work queue summary
            work = conn.execute(
                """SELECT status, COUNT(*), MAX(completed_at)
                   FROM work_queue WHERE run_id = ?
                   GROUP BY status ORDER BY status""",
                (run_id,),
            ).fetchall()

            # 3. Get thread count and latest entry
            thread = conn.execute(
                "SELECT COUNT(*), MAX(created_at) FROM artifact_threads WHERE run_id = ?",
                (run_id,),
            ).fetchone()

            # Concatenate all state identifiers
            state = f"{run['status']}|{run['current_phase']}|{run['total_spent_cents']}|"
            state += "|".join(f"{r[0]}:{r[1]}:{r[2]}" for r in work)
            state += f"|threads:{thread[0]}:{thread[1]}"

            return hashlib.sha1(state.encode()).hexdigest()

    # --- Audit log methods ---

    def append_audit_log(
        self,
        project_id: str,
        action_type: str,
        outcome: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        target_entity: str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """Append an entry to the audit log.

        This is append-only: no update or delete methods exist for audit entries.

        Args:
            project_id: Project identifier.
            action_type: Type of action (e.g., 'task_completed', 'permission_denied').
            outcome: Outcome description (e.g., 'success', 'denied', 'error').
            agent_id: Optional agent who performed the action.
            run_id: Optional execution run context.
            target_entity: Optional entity that was acted upon (e.g., 'PCRA-T00001').
            details: Optional additional details (dict will be JSON-serialized).

        Returns:
            Created audit log entry dict.
        """
        details_str: str | None = None
        if details is not None:
            details_str = json.dumps(details) if isinstance(details, dict) else str(details)

        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO audit_log
                   (project_id, agent_id, run_id, action_type,
                    target_entity, outcome, details, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (project_id, agent_id, run_id, action_type,
                 target_entity, outcome, details_str, now),
            )
            log_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM audit_log WHERE id = ?", (log_id,)
            ).fetchone()
            return dict(row)

    def get_audit_log(
        self,
        project_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        action_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get audit log entries with optional filters.

        Args:
            project_id: Project identifier.
            agent_id: Optional agent filter.
            run_id: Optional execution run filter.
            action_type: Optional action type filter.
            limit: Maximum number of entries to return (default 50).

        Returns:
            List of audit log entry dicts ordered by created_at descending.
        """
        query = "SELECT * FROM audit_log WHERE project_id = ?"
        params: list[Any] = [project_id]

        if agent_id is not None:
            query += " AND agent_id = ?"
            params.append(agent_id)
        if run_id is not None:
            query += " AND run_id = ?"
            params.append(run_id)
        if action_type is not None:
            query += " AND action_type = ?"
            params.append(action_type)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with self.connection() as conn:
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    # =========================================================================
    # Task Claim Operations
    # =========================================================================

    def claim_task(self, task_id: str, agent_id: str) -> dict[str, Any]:
        """Atomically claim a task for an agent.

        Uses the partial unique index idx_task_claims_active to prevent
        concurrent claims on the same task.

        Args:
            task_id: Task identifier to claim.
            agent_id: Agent identifier claiming the task.

        Returns:
            The created claim dict.

        Raises:
            ValueError: If task not found, not pending, or already has an active claim.
        """
        with self.connection() as conn:
            # Check task exists and is pending
            task = conn.execute(
                "SELECT id, status FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if not task:
                raise ValueError(f"Task not found: {task_id}")
            if task["status"] != "pending":
                raise ValueError(
                    f"Task {task_id} is not pending (status: {task['status']})"
                )

            # Insert claim (partial unique index enforces one active claim per task)
            try:
                conn.execute(
                    "INSERT INTO task_claims (task_id, agent_id, status) VALUES (?, ?, 'active')",
                    (task_id, agent_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"Task {task_id} already has an active claim"
                ) from exc

            # Update task assignment
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE tasks SET assigned_agent_id = ?, status = 'in_progress', "
                "started_at = ?, updated_at = ? WHERE id = ?",
                (agent_id, now, now, task_id),
            )

            # Return the claim
            claim = conn.execute(
                "SELECT * FROM task_claims WHERE task_id = ? AND status = 'active'",
                (task_id,),
            ).fetchone()
            return dict(claim)

    def release_task(
        self, task_id: str, agent_id: str, reason: str = "manual"
    ) -> dict[str, Any] | None:
        """Release a task claim, resetting the task to pending.

        Args:
            task_id: Task identifier.
            agent_id: Agent identifier releasing the task.
            reason: Reason for releasing (e.g., 'manual', 'timeout', 'reassign').

        Returns:
            The released claim dict, or None if no matching active claim found.
        """
        with self.connection() as conn:
            now = datetime.now(timezone.utc).isoformat()
            # Release the active claim
            conn.execute(
                "UPDATE task_claims SET status = 'released', released_at = ?, "
                "release_reason = ? "
                "WHERE task_id = ? AND agent_id = ? AND status = 'active'",
                (now, reason, task_id, agent_id),
            )
            # Reset task assignment
            conn.execute(
                "UPDATE tasks SET assigned_agent_id = NULL, status = 'pending', "
                "updated_at = ? WHERE id = ?",
                (now, task_id),
            )
            claim = conn.execute(
                "SELECT * FROM task_claims WHERE task_id = ? AND agent_id = ? "
                "ORDER BY released_at DESC LIMIT 1",
                (task_id, agent_id),
            ).fetchone()
            return dict(claim) if claim else None

    def get_active_claim(self, task_id: str) -> dict[str, Any] | None:
        """Get the active claim for a task.

        Args:
            task_id: Task identifier.

        Returns:
            Active claim dict if one exists, None otherwise.
        """
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM task_claims WHERE task_id = ? AND status = 'active'",
                (task_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_claims_by_agent(self, agent_id: str) -> list[dict[str, Any]]:
        """List all claims (active and released) for an agent.

        Args:
            agent_id: Agent identifier.

        Returns:
            List of claim dicts ordered by claimed_at descending.
        """
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_claims WHERE agent_id = ? ORDER BY claimed_at DESC",
                (agent_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def detect_stale_claims(self, timeout_minutes: int = 30) -> list[dict[str, Any]]:
        """Detect active claims that have exceeded the timeout threshold.

        Args:
            timeout_minutes: Number of minutes after which an active claim is
                considered stale. Default 30.

        Returns:
            List of stale claim dicts.
        """
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_claims WHERE status = 'active' "
                "AND claimed_at < datetime('now', ? || ' minutes')",
                (f"-{timeout_minutes}",),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_available_work(
        self,
        project_id: str,
        agent_id: str,
        sprint_id: str | None = None,
        component_map: dict[str, list[str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Get available (unclaimed, pending) tasks for an agent using three-tier routing.

        Three-tier priority routing (REM-006/REM-007/REM-015):
        - Tier 1: Tasks whose component matches the agent's persona type via component_map
        - Tier 2: Remaining tasks sorted by priority (critical > high > medium > low)
        - Tier 3: Fallback -- any remaining available task

        Within each tier, tasks are further sorted by priority and then by
        performance_score of the requesting agent (higher score = earlier assignment).

        Args:
            project_id: Project identifier.
            agent_id: Agent identifier (validated to exist).
            sprint_id: Optional sprint filter (derived via PRD relationship).
            component_map: Optional mapping of component labels to persona types.
                When provided, enables Tier-1 component-based routing.

        Returns:
            List of available task dicts with a ``routing_tier`` field (1, 2, or 3).

        Raises:
            ValueError: If agent not found.
        """
        with self.connection() as conn:
            # Validate agent exists and get persona info
            agent = conn.execute(
                "SELECT id, persona_type, performance_score FROM agents WHERE id = ?",
                (agent_id,),
            ).fetchone()
            if not agent:
                raise ValueError(f"Agent not found: {agent_id}")

            persona_type = agent["persona_type"]
            perf_score = agent["performance_score"] or 50.0

            query = """
                SELECT t.* FROM tasks t
                WHERE t.project_id = ? AND t.status = 'pending'
                AND t.assigned_agent_id IS NULL
                AND NOT EXISTS (
                    SELECT 1 FROM task_claims tc
                    WHERE tc.task_id = t.id AND tc.status = 'active'
                )
            """
            params: list[Any] = [project_id]

            if sprint_id:
                query += " AND t.prd_id IN (SELECT id FROM prds WHERE sprint_id = ?)"
                params.append(sprint_id)

            query += """
                ORDER BY
                    CASE t.priority
                        WHEN 'critical' THEN 0
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        ELSE 3
                    END,
                    t.created_at
            """
            rows = conn.execute(query, tuple(params)).fetchall()
            all_tasks = [dict(row) for row in rows]

            # Build set of components this agent's persona matches
            matched_components: set[str] = set()
            if component_map:
                for component, personas in component_map.items():
                    if persona_type in personas:
                        matched_components.add(component)

            # Three-tier classification
            tier1: list[dict[str, Any]] = []
            tier2: list[dict[str, Any]] = []

            for task in all_tasks:
                task_component = (task.get("component") or "").lower()
                if matched_components and task_component in matched_components:
                    task["routing_tier"] = 1
                    tier1.append(task)
                else:
                    task["routing_tier"] = 2
                    tier2.append(task)

            # If no component map or no matches, everything is tier 2 (priority-sorted)
            # Tier 3 is implicit: tasks at the end of the list with no special matching
            # Reclassify the last portion of tier2 as tier 3 (fallback)
            if tier1:
                # Only mark tier 3 when there is a meaningful tier 1
                for task in tier2:
                    task["routing_tier"] = 3
            # else all stay as tier 2 (priority-only sorting)

            # Performance-score weighting: within each tier, use perf_score
            # to slightly adjust ordering (agent's score stored for context)
            result = tier1 + tier2
            for task in result:
                task["agent_performance_score"] = perf_score

            return result

    # =========================================================================
    # Agent Message Operations
    # =========================================================================

    def send_agent_message(
        self,
        from_agent_id: str,
        to_agent_id: str,
        message_type: str,
        content: str,
        related_task_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a message from one agent to another.

        Args:
            from_agent_id: Sender agent identifier.
            to_agent_id: Recipient agent identifier.
            message_type: Message type (e.g., 'handoff', 'question', 'blocker').
            content: Message content text.
            related_task_id: Optional task this message relates to.

        Returns:
            Created message dict with id.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO agent_messages "
                "(from_agent_id, to_agent_id, message_type, content, related_task_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (from_agent_id, to_agent_id, message_type, content, related_task_id),
            )
            row = conn.execute(
                "SELECT * FROM agent_messages WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(row)

    def get_agent_messages(
        self,
        agent_id: str,
        unread_only: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get messages sent to an agent.

        Args:
            agent_id: Recipient agent identifier.
            unread_only: If True, return only unread messages (read_at IS NULL).
            limit: Maximum number of messages to return (default 50).

        Returns:
            List of message dicts ordered by created_at descending.
        """
        with self.connection() as conn:
            query = "SELECT * FROM agent_messages WHERE to_agent_id = ?"
            params: list[Any] = [agent_id]

            if unread_only:
                query += " AND read_at IS NULL"

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    def mark_message_read(self, message_id: int) -> dict[str, Any] | None:
        """Mark a message as read by setting read_at timestamp.

        Args:
            message_id: Message identifier (integer primary key).

        Returns:
            Updated message dict, or None if not found.
        """
        with self.connection() as conn:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE agent_messages SET read_at = ? WHERE id = ?",
                (now, message_id),
            )
            row = conn.execute(
                "SELECT * FROM agent_messages WHERE id = ?", (message_id,)
            ).fetchone()
            return dict(row) if row else None

    # =========================================================================
    # Agent Performance Operations
    # =========================================================================

    def record_agent_performance(
        self,
        agent_id: str,
        sprint_id: str | None = None,
        tasks_completed: int = 0,
        tasks_failed: int = 0,
        avg_quality_score: float | None = None,
        avg_completion_time_min: float | None = None,
        corrections_count: int = 0,
        review_pass_rate: float | None = None,
    ) -> dict[str, Any]:
        """Upsert agent performance record (UNIQUE(agent_id, sprint_id)).

        Inserts a new performance row or updates the existing one when the
        (agent_id, sprint_id) pair already exists.

        Args:
            agent_id: Agent identifier.
            sprint_id: Sprint identifier (None for overall/aggregate records).
            tasks_completed: Number of tasks completed.
            tasks_failed: Number of tasks failed.
            avg_quality_score: Average quality score (0-100).
            avg_completion_time_min: Average completion time in minutes.
            corrections_count: Number of corrections applied.
            review_pass_rate: Review pass rate (0.0-1.0).

        Returns:
            The upserted performance record dict.
        """
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO agent_performance
                (agent_id, sprint_id, tasks_completed, tasks_failed,
                 avg_quality_score, avg_completion_time_min,
                 corrections_count, review_pass_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id, sprint_id) DO UPDATE SET
                    tasks_completed = excluded.tasks_completed,
                    tasks_failed = excluded.tasks_failed,
                    avg_quality_score = excluded.avg_quality_score,
                    avg_completion_time_min = excluded.avg_completion_time_min,
                    corrections_count = excluded.corrections_count,
                    review_pass_rate = excluded.review_pass_rate
                """,
                (
                    agent_id,
                    sprint_id,
                    tasks_completed,
                    tasks_failed,
                    avg_quality_score,
                    avg_completion_time_min,
                    corrections_count,
                    review_pass_rate,
                ),
            )
            row = conn.execute(
                "SELECT * FROM agent_performance "
                "WHERE agent_id = ? AND (sprint_id = ? OR (? IS NULL AND sprint_id IS NULL))",
                (agent_id, sprint_id, sprint_id),
            ).fetchone()
            return dict(row)

    def get_agent_performance(
        self, agent_id: str, sprint_id: str | None = None
    ) -> dict[str, Any] | None:
        """Get performance record for an agent, optionally for a specific sprint.

        Args:
            agent_id: Agent identifier.
            sprint_id: If provided, returns the record for that sprint.
                       If None, returns the most recent record.

        Returns:
            Performance record dict, or None if not found.
        """
        with self.connection() as conn:
            if sprint_id:
                row = conn.execute(
                    "SELECT * FROM agent_performance "
                    "WHERE agent_id = ? AND sprint_id = ?",
                    (agent_id, sprint_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM agent_performance "
                    "WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1",
                    (agent_id,),
                ).fetchone()
            return dict(row) if row else None

    def compute_agent_performance(self, agent_id: str) -> dict[str, Any]:
        """Compute aggregated performance metrics across all sprints.

        Sums task counts and corrections, averages quality and time metrics.

        Args:
            agent_id: Agent identifier.

        Returns:
            Aggregated metrics dict. If no records exist, returns zeroed defaults.
        """
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT
                    agent_id,
                    SUM(tasks_completed) as total_completed,
                    SUM(tasks_failed) as total_failed,
                    AVG(avg_quality_score) as overall_quality,
                    AVG(avg_completion_time_min) as overall_completion_time,
                    SUM(corrections_count) as total_corrections,
                    AVG(review_pass_rate) as overall_pass_rate,
                    COUNT(*) as sprint_count
                FROM agent_performance WHERE agent_id = ?
                GROUP BY agent_id
                """,
                (agent_id,),
            ).fetchone()
            if row:
                return dict(row)
            return {
                "agent_id": agent_id,
                "total_completed": 0,
                "total_failed": 0,
                "overall_quality": None,
                "overall_completion_time": None,
                "total_corrections": 0,
                "overall_pass_rate": None,
                "sprint_count": 0,
            }

    def update_agent_performance_score(
        self, agent_id: str, new_score: float
    ) -> dict[str, Any] | None:
        """Update the rolling performance_score on the agents table.

        Args:
            agent_id: Agent identifier.
            new_score: New performance score (0.0-100.0).

        Returns:
            Updated agent dict, or None if agent not found.
        """
        with self.connection() as conn:
            conn.execute(
                "UPDATE agents SET performance_score = ? WHERE id = ?",
                (new_score, agent_id),
            )
            row = conn.execute(
                "SELECT * FROM agents WHERE id = ?", (agent_id,)
            ).fetchone()
            return dict(row) if row else None

    # =========================================================================
    # Agent Team Operations
    # =========================================================================

    def create_agent_team(
        self,
        name: str,
        project_id: str,
        lead_agent_id: str | None = None,
        sprint_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new agent team.

        Args:
            name: Team name.
            project_id: Project identifier.
            lead_agent_id: Optional lead agent identifier.
            sprint_id: Optional sprint to scope this team to.

        Returns:
            Created team dict.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO agent_teams (name, project_id, lead_agent_id, sprint_id) "
                "VALUES (?, ?, ?, ?)",
                (name, project_id, lead_agent_id, sprint_id),
            )
            row = conn.execute(
                "SELECT * FROM agent_teams WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(row)

    def assign_agent_to_team(
        self, agent_id: str, team_id: int
    ) -> dict[str, Any] | None:
        """Assign an agent to a team by setting their team_id.

        Args:
            agent_id: Agent identifier.
            team_id: Team identifier (integer primary key).

        Returns:
            Updated agent dict, or None if agent not found.
        """
        with self.connection() as conn:
            conn.execute(
                "UPDATE agents SET team_id = ? WHERE id = ?",
                (str(team_id), agent_id),
            )
            row = conn.execute(
                "SELECT * FROM agents WHERE id = ?", (agent_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_team_composition(
        self, team_id: int, sprint_id: str | None = None
    ) -> dict[str, Any]:
        """Get team details with all member agents.

        Args:
            team_id: Team identifier (integer primary key).
            sprint_id: Optional sprint filter. When provided, only returns
                the team if it is scoped to that sprint (or unscoped).

        Returns:
            Team dict with a ``members`` list of agent dicts.

        Raises:
            ValueError: If team not found.
        """
        with self.connection() as conn:
            if sprint_id:
                team = conn.execute(
                    "SELECT * FROM agent_teams WHERE id = ? "
                    "AND (sprint_id = ? OR sprint_id IS NULL)",
                    (team_id, sprint_id),
                ).fetchone()
            else:
                team = conn.execute(
                    "SELECT * FROM agent_teams WHERE id = ?", (team_id,)
                ).fetchone()
            if not team:
                raise ValueError(f"Team not found: {team_id}")
            members = conn.execute(
                "SELECT * FROM agents WHERE team_id = ? ORDER BY persona_type",
                (str(team_id),),
            ).fetchall()
            result = dict(team)
            result["members"] = [dict(m) for m in members]
            return result

    def list_agent_teams(
        self, project_id: str, sprint_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List all teams in a project, optionally filtered by sprint.

        Args:
            project_id: Project identifier.
            sprint_id: Optional sprint filter. When provided, returns only
                teams scoped to that sprint (or unscoped teams).

        Returns:
            List of team dicts ordered by name.
        """
        with self.connection() as conn:
            if sprint_id:
                rows = conn.execute(
                    "SELECT * FROM agent_teams WHERE project_id = ? "
                    "AND (sprint_id = ? OR sprint_id IS NULL) ORDER BY name",
                    (project_id, sprint_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_teams WHERE project_id = ? ORDER BY name",
                    (project_id,),
                ).fetchall()
            return [dict(row) for row in rows]

    # =========================================================================
    # Agent Health Operations
    # =========================================================================

    def detect_health_issues(
        self,
        project_id: str,
        stalled_timeout_min: int = 30,
        error_rate_threshold_pct: int = 30,
        quality_threshold: int = 40,
    ) -> list[dict[str, Any]]:
        """Detect agents with health issues: low quality or high error rate.

        Checks active agents for:
        - Performance score below ``quality_threshold``.
        - Error rate (tasks_failed / total_tasks) above ``error_rate_threshold_pct``.

        Args:
            project_id: Project identifier.
            stalled_timeout_min: Unused (reserved for future stalled-agent detection).
            error_rate_threshold_pct: Error-rate percentage threshold (0-100).
            quality_threshold: Minimum acceptable performance_score.

        Returns:
            List of issue dicts, each containing agent_id, issue type,
            observed value, and threshold.
        """
        issues: list[dict[str, Any]] = []
        with self.connection() as conn:
            # Find active agents with low performance scores
            low_quality = conn.execute(
                """
                SELECT * FROM agents
                WHERE project_id = ? AND status = 'active'
                AND performance_score < ?
                """,
                (project_id, quality_threshold),
            ).fetchall()
            for agent in low_quality:
                issues.append(
                    {
                        "agent_id": agent["id"],
                        "issue": "low_quality",
                        "value": agent["performance_score"],
                        "threshold": quality_threshold,
                    }
                )

            # Find agents with high error rates from recent performance
            high_error = conn.execute(
                """
                SELECT ap.agent_id,
                       CASE WHEN (ap.tasks_completed + ap.tasks_failed) > 0
                            THEN (ap.tasks_failed * 100.0
                                  / (ap.tasks_completed + ap.tasks_failed))
                            ELSE 0 END as error_rate
                FROM agent_performance ap
                JOIN agents a ON a.id = ap.agent_id
                WHERE a.project_id = ? AND a.status = 'active'
                ORDER BY ap.created_at DESC
                """,
                (project_id,),
            ).fetchall()
            for row in high_error:
                if row["error_rate"] > error_rate_threshold_pct:
                    issues.append(
                        {
                            "agent_id": row["agent_id"],
                            "issue": "high_error_rate",
                            "value": row["error_rate"],
                            "threshold": error_rate_threshold_pct,
                        }
                    )

        return issues

    def suspend_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Suspend an agent (sets status='suspended' and records suspended_at).

        Args:
            agent_id: Agent identifier.

        Returns:
            Updated agent dict, or None if agent not found.
        """
        with self.connection() as conn:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE agents SET status = 'suspended', suspended_at = ? WHERE id = ?",
                (now, agent_id),
            )
            row = conn.execute(
                "SELECT * FROM agents WHERE id = ?", (agent_id,)
            ).fetchone()
            return dict(row) if row else None

    def retire_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Retire an agent (preserves all data per NFR-003).

        Args:
            agent_id: Agent identifier.

        Returns:
            Updated agent dict, or None if agent not found.
        """
        with self.connection() as conn:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE agents SET status = 'retired', retired_at = ? WHERE id = ?",
                (now, agent_id),
            )
            row = conn.execute(
                "SELECT * FROM agents WHERE id = ?", (agent_id,)
            ).fetchone()
            return dict(row) if row else None

    # =========================================================================
    # Requirements CRUD
    # =========================================================================

    def upsert_requirement(
        self,
        id: str,
        prd_id: str,
        req_type: str,
        req_number: str,
        summary: str,
        depth: str = "structural",
    ) -> dict[str, Any]:
        """Insert or replace a requirement record.

        Args:
            id: Unique requirement identifier.
            prd_id: Parent PRD identifier.
            req_type: Requirement type (e.g. 'functional', 'non-functional', 'ac').
            req_number: Requirement number within the PRD (e.g. 'FR-001').
            summary: Short description of the requirement.
            depth: Depth level (default 'structural').

        Returns:
            The upserted requirement as a dict.
        """
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO requirements
                    (id, prd_id, req_type, req_number, summary, depth)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (id, prd_id, req_type, req_number, summary, depth),
            )
            row = conn.execute(
                "SELECT * FROM requirements WHERE id = ?", (id,)
            ).fetchone()
            return dict(row)

    def get_requirement(self, requirement_id: str) -> dict[str, Any] | None:
        """Get a single requirement by ID.

        Args:
            requirement_id: Requirement identifier.

        Returns:
            Requirement dict, or None if not found.
        """
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM requirements WHERE id = ?", (requirement_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_requirements(
        self, prd_id: str, req_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all requirements for a PRD, optionally filtered by type.

        Args:
            prd_id: PRD identifier.
            req_type: Optional type filter.

        Returns:
            List of requirement dicts.
        """
        query = "SELECT * FROM requirements WHERE prd_id = ?"
        params: list[Any] = [prd_id]
        if req_type is not None:
            query += " AND req_type = ?"
            params.append(req_type)
        query += " ORDER BY req_number"
        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def delete_requirements(self, prd_id: str) -> int:
        """Delete all requirements for a PRD.

        Args:
            prd_id: PRD identifier.

        Returns:
            Number of rows deleted.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM requirements WHERE prd_id = ?", (prd_id,)
            )
            return cursor.rowcount

    # =========================================================================
    # Requirement Links CRUD
    # =========================================================================

    def link_task_requirement(self, requirement_id: str, task_id: str) -> dict[str, Any]:
        """Link a task to a requirement.

        Uses INSERT OR IGNORE so duplicate links are silently skipped.

        Args:
            requirement_id: Requirement identifier.
            task_id: Task identifier.

        Returns:
            Dict with requirement_id, task_id, and created_at.
        """
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO requirement_links (requirement_id, task_id)
                VALUES (?, ?)
                """,
                (requirement_id, task_id),
            )
            row = conn.execute(
                "SELECT * FROM requirement_links WHERE requirement_id = ? AND task_id = ?",
                (requirement_id, task_id),
            ).fetchone()
            return dict(row)

    def get_task_requirements(self, task_id: str) -> list[dict[str, Any]]:
        """Get all requirements linked to a task, with verification status.

        Performs a JOIN on requirements and LEFT JOIN on ac_verifications
        to include verification status per requirement.

        Args:
            task_id: Task identifier.

        Returns:
            List of requirement dicts with an additional 'verified' boolean field.
        """
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT r.*, rl.created_at as linked_at,
                       CASE WHEN av.id IS NOT NULL THEN 1 ELSE 0 END as verified,
                       av.verified_by, av.evidence_type, av.evidence, av.verified_at
                FROM requirement_links rl
                INNER JOIN requirements r ON rl.requirement_id = r.id
                LEFT JOIN ac_verifications av
                    ON av.requirement_id = r.id AND av.task_id = rl.task_id
                WHERE rl.task_id = ?
                ORDER BY r.req_number
                """,
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_requirement_tasks(self, requirement_id: str) -> list[dict[str, Any]]:
        """Get all tasks linked to a requirement.

        Args:
            requirement_id: Requirement identifier.

        Returns:
            List of task dicts.
        """
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT t.* FROM requirement_links rl
                INNER JOIN tasks t ON rl.task_id = t.id
                WHERE rl.requirement_id = ?
                ORDER BY t.id
                """,
                (requirement_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_orphaned_requirements(self, prd_id: str) -> list[dict[str, Any]]:
        """Get requirements with zero linked tasks.

        Args:
            prd_id: PRD identifier.

        Returns:
            List of requirement dicts that have no linked tasks.
        """
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT r.* FROM requirements r
                LEFT JOIN requirement_links rl ON r.id = rl.requirement_id
                WHERE r.prd_id = ? AND rl.requirement_id IS NULL
                ORDER BY r.req_number
                """,
                (prd_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_coverage_stats(self, prd_id: str) -> dict[str, Any]:
        """Compute requirement coverage statistics for a PRD.

        Args:
            prd_id: PRD identifier.

        Returns:
            Dict with keys: total, linked, orphaned, by_type.
            by_type is a dict mapping req_type to {total, linked}.
        """
        with self.connection() as conn:
            # Total requirements
            total = conn.execute(
                "SELECT COUNT(*) as cnt FROM requirements WHERE prd_id = ?",
                (prd_id,),
            ).fetchone()["cnt"]

            # Linked requirements (at least one task)
            linked = conn.execute(
                """
                SELECT COUNT(DISTINCT r.id) as cnt
                FROM requirements r
                INNER JOIN requirement_links rl ON r.id = rl.requirement_id
                WHERE r.prd_id = ?
                """,
                (prd_id,),
            ).fetchone()["cnt"]

            orphaned = total - linked

            # Breakdown by type
            type_rows = conn.execute(
                """
                SELECT r.req_type,
                       COUNT(*) as total,
                       COUNT(rl.requirement_id) as linked
                FROM requirements r
                LEFT JOIN (
                    SELECT DISTINCT requirement_id FROM requirement_links
                ) rl ON r.id = rl.requirement_id
                WHERE r.prd_id = ?
                GROUP BY r.req_type
                """,
                (prd_id,),
            ).fetchall()

            by_type = {
                row["req_type"]: {"total": row["total"], "linked": row["linked"]}
                for row in type_rows
            }

            return {
                "total": total,
                "linked": linked,
                "orphaned": orphaned,
                "by_type": by_type,
            }

    # =========================================================================
    # AC Verifications CRUD
    # =========================================================================

    def record_ac_verification(
        self,
        requirement_id: str,
        task_id: str,
        verified_by: str,
        evidence_type: str,
        evidence: str,
    ) -> dict[str, Any]:
        """Record acceptance-criteria verification evidence.

        Uses INSERT OR REPLACE so re-verification overwrites the previous record.

        Args:
            requirement_id: Requirement identifier.
            task_id: Task identifier.
            verified_by: Agent or user who verified.
            evidence_type: Type of evidence (e.g. 'test', 'manual', 'review').
            evidence: Evidence details / description.

        Returns:
            The verification record as a dict.
        """
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ac_verifications
                    (requirement_id, task_id, verified_by, evidence_type, evidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (requirement_id, task_id, verified_by, evidence_type, evidence),
            )
            row = conn.execute(
                """
                SELECT * FROM ac_verifications
                WHERE requirement_id = ? AND task_id = ?
                """,
                (requirement_id, task_id),
            ).fetchone()
            return dict(row)

    def get_ac_verifications(self, task_id: str) -> list[dict[str, Any]]:
        """Get all AC verifications for a task.

        Args:
            task_id: Task identifier.

        Returns:
            List of verification dicts.
        """
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ac_verifications WHERE task_id = ? ORDER BY verified_at",
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_unverified_acs(self, task_id: str) -> list[dict[str, Any]]:
        """Get AC requirements linked to a task but not yet verified.

        Args:
            task_id: Task identifier.

        Returns:
            List of requirement dicts that are linked but lack verification.
        """
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT r.* FROM requirement_links rl
                INNER JOIN requirements r ON rl.requirement_id = r.id
                LEFT JOIN ac_verifications av
                    ON av.requirement_id = r.id AND av.task_id = rl.task_id
                WHERE rl.task_id = ? AND av.id IS NULL
                ORDER BY r.req_number
                """,
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # =========================================================================
    # Challenge Records CRUD
    # =========================================================================

    def create_challenge_round(
        self,
        artifact_type: str,
        artifact_id: str,
        round_number: int,
        objections: str,
        challenger_context: str | None = None,
    ) -> dict[str, Any]:
        """Create a new challenge round for an artifact.

        Args:
            artifact_type: Type of artifact (e.g. 'prd', 'design', 'task').
            artifact_id: Artifact identifier.
            round_number: Round number (1-based).
            objections: JSON string of objections raised.
            challenger_context: Optional context about the challenger.

        Returns:
            The created challenge record as a dict.
        """
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO challenge_records
                    (artifact_type, artifact_id, round_number, objections, challenger_context)
                VALUES (?, ?, ?, ?, ?)
                """,
                (artifact_type, artifact_id, round_number, objections, challenger_context),
            )
            row = conn.execute(
                """
                SELECT * FROM challenge_records
                WHERE artifact_type = ? AND artifact_id = ? AND round_number = ?
                """,
                (artifact_type, artifact_id, round_number),
            ).fetchone()
            return dict(row)

    def update_challenge_round(
        self,
        artifact_type: str,
        artifact_id: str,
        round_number: int,
        responses: str | None = None,
        verdict: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        """Update specific fields of a challenge round.

        Args:
            artifact_type: Type of artifact.
            artifact_id: Artifact identifier.
            round_number: Round number.
            responses: Optional JSON string of responses.
            verdict: Optional verdict (e.g. 'accepted', 'rejected', 'revised').
            status: Optional status update (e.g. 'open', 'closed').

        Returns:
            Updated challenge record, or None if not found.
        """
        updates: dict[str, Any] = {}
        if responses is not None:
            updates["responses"] = responses
        if verdict is not None:
            updates["verdict"] = verdict
        if status is not None:
            updates["status"] = status

        if not updates:
            return self._get_challenge_round(artifact_type, artifact_id, round_number)

        fields = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [artifact_type, artifact_id, round_number]

        with self.connection() as conn:
            conn.execute(
                f"""
                UPDATE challenge_records SET {fields}
                WHERE artifact_type = ? AND artifact_id = ? AND round_number = ?
                """,
                values,
            )
            row = conn.execute(
                """
                SELECT * FROM challenge_records
                WHERE artifact_type = ? AND artifact_id = ? AND round_number = ?
                """,
                (artifact_type, artifact_id, round_number),
            ).fetchone()
            return dict(row) if row else None

    def _get_challenge_round(
        self, artifact_type: str, artifact_id: str, round_number: int
    ) -> dict[str, Any] | None:
        """Get a single challenge round (internal helper)."""
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM challenge_records
                WHERE artifact_type = ? AND artifact_id = ? AND round_number = ?
                """,
                (artifact_type, artifact_id, round_number),
            ).fetchone()
            return dict(row) if row else None

    def get_challenge_rounds(
        self, artifact_type: str, artifact_id: str
    ) -> list[dict[str, Any]]:
        """Get all challenge rounds for an artifact, ordered by round number.

        JSON fields (objections, responses) are parsed back into Python objects.

        Args:
            artifact_type: Type of artifact.
            artifact_id: Artifact identifier.

        Returns:
            List of challenge record dicts with parsed JSON fields.
        """
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM challenge_records
                WHERE artifact_type = ? AND artifact_id = ?
                ORDER BY round_number
                """,
                (artifact_type, artifact_id),
            ).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            # Parse JSON fields
            for field in ("objections", "responses"):
                if d.get(field):
                    with contextlib.suppress(json.JSONDecodeError, TypeError):
                        d[field] = json.loads(d[field])
            results.append(d)
        return results

    def get_challenge_status(
        self, artifact_type: str, artifact_id: str
    ) -> dict[str, Any]:
        """Get summary status of challenge rounds for an artifact.

        Args:
            artifact_type: Type of artifact.
            artifact_id: Artifact identifier.

        Returns:
            Dict with keys: total_rounds, latest_status, open_count, closed_count.
        """
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) as cnt FROM challenge_records
                WHERE artifact_type = ? AND artifact_id = ?
                GROUP BY status
                """,
                (artifact_type, artifact_id),
            ).fetchall()

            total = sum(r["cnt"] for r in rows)
            counts = {r["status"]: r["cnt"] for r in rows}

            # Get latest round status
            latest = conn.execute(
                """
                SELECT status FROM challenge_records
                WHERE artifact_type = ? AND artifact_id = ?
                ORDER BY round_number DESC LIMIT 1
                """,
                (artifact_type, artifact_id),
            ).fetchone()

            return {
                "total_rounds": total,
                "latest_status": latest["status"] if latest else None,
                "open_count": counts.get("open", 0),
                "closed_count": counts.get("closed", 0),
            }

    # =========================================================================
    # Artifact Thread Methods
    # =========================================================================

    def add_thread_entry(
        self,
        run_id: str,
        project_id: str,
        artifact_type: str,
        artifact_id: str,
        entry_type: str,
        content: str | None = None,
        agent_id: str | None = None,
        agent_persona: str | None = None,
        round_number: int = 1,
        parent_thread_id: int | None = None,
    ) -> dict[str, Any]:
        """Add an entry to an artifact's discussion thread.

        Thread entries track the convergence discussion around an artifact
        (PRD, design, task) across multiple agents and rounds.

        Args:
            run_id: Parent execution run ID.
            project_id: Parent project ID.
            artifact_type: Type of artifact ('prd', 'design', 'task', 'sprint').
            artifact_id: Artifact identifier (e.g., 'PROJ-P0001').
            entry_type: Type of entry ('draft', 'review', 'revision',
                'challenge', 'response', 'verdict', 'user_intervention',
                'handoff', 'signal').
            content: Optional text content of the entry.
            agent_id: Optional agent who created this entry.
            agent_persona: Optional persona type (e.g., 'sdlc-architect').
            round_number: Round number in the convergence cycle (default 1).
            parent_thread_id: Optional parent entry ID for threading.

        Returns:
            Created thread entry dict.
        """
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO artifact_threads
                   (run_id, project_id, artifact_type, artifact_id,
                    entry_type, content, agent_id, agent_persona,
                    round_number, parent_thread_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, project_id, artifact_type, artifact_id,
                 entry_type, content, agent_id, agent_persona,
                 round_number, parent_thread_id),
            )
            entry_id = cursor.lastrowid
            row = conn.execute(
                "SELECT * FROM artifact_threads WHERE id = ?", (entry_id,)
            ).fetchone()
            return dict(row)

    def get_thread_entries(
        self,
        artifact_type: str,
        artifact_id: str,
        run_id: str | None = None,
        entry_type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get thread entries for an artifact, ordered by creation time.

        Args:
            artifact_type: Type of artifact ('prd', 'design', 'task', 'sprint').
            artifact_id: Artifact identifier.
            run_id: Optional filter by execution run.
            entry_type: Optional filter by entry type.
            limit: Optional maximum number of entries to return
                (most recent first when limited, but returned in chronological order).

        Returns:
            List of thread entry dicts in chronological order.
        """
        conditions = ["artifact_type = ?", "artifact_id = ?"]
        params: list[Any] = [artifact_type, artifact_id]

        if run_id is not None:
            conditions.append("run_id = ?")
            params.append(run_id)
        if entry_type is not None:
            conditions.append("entry_type = ?")
            params.append(entry_type)

        where_clause = " AND ".join(conditions)

        if limit is not None:
            # Get the most recent N entries, then return in chronological order
            query = f"""
                SELECT * FROM (
                    SELECT * FROM artifact_threads
                    WHERE {where_clause}
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                ) sub ORDER BY created_at ASC, id ASC
            """
            params.append(limit)
        else:
            query = f"""
                SELECT * FROM artifact_threads
                WHERE {where_clause}
                ORDER BY created_at ASC, id ASC
            """

        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_thread_entry(self, entry_id: int) -> dict[str, Any] | None:
        """Get a single thread entry by ID.

        Args:
            entry_id: Thread entry ID.

        Returns:
            Thread entry dict if found, None otherwise.
        """
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM artifact_threads WHERE id = ?", (entry_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_thread_entries_for_run(
        self,
        run_id: str,
        artifact_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Get all thread entries for an execution run, optionally filtered by type.

        Args:
            run_id: Execution run ID.
            artifact_types: Optional list of artifact types to include.

        Returns:
            List of thread entry dicts in chronological order.
        """
        if artifact_types:
            placeholders = ", ".join("?" for _ in artifact_types)
            query = f"""
                SELECT * FROM artifact_threads
                WHERE run_id = ? AND artifact_type IN ({placeholders})
                ORDER BY created_at ASC, id ASC
            """
            params: list[Any] = [run_id, *artifact_types]
        else:
            query = """
                SELECT * FROM artifact_threads
                WHERE run_id = ?
                ORDER BY created_at ASC, id ASC
            """
            params = [run_id]

        with self.connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # =========================================================================
    # Org Overview
    # =========================================================================

    def get_org_overview(self, project_id: str) -> dict[str, Any]:
        """Get organizational overview with agent stats, teams, and recent performance.

        Args:
            project_id: Project identifier.

        Returns:
            Overview dict containing agent_counts by status, team_count,
            and a list of all agents with key fields.
        """
        with self.connection() as conn:
            # Agent counts by status
            status_counts = conn.execute(
                """
                SELECT status, COUNT(*) as count FROM agents
                WHERE project_id = ? GROUP BY status
                """,
                (project_id,),
            ).fetchall()

            # Team count
            team_count = conn.execute(
                "SELECT COUNT(*) as count FROM agent_teams WHERE project_id = ?",
                (project_id,),
            ).fetchone()["count"]

            # Active agents with performance
            agents = conn.execute(
                """
                SELECT a.id, a.display_name, a.persona_type, a.status,
                       a.team_id, a.performance_score, a.hired_at
                FROM agents a WHERE a.project_id = ?
                ORDER BY a.status, a.display_name
                """,
                (project_id,),
            ).fetchall()

            return {
                "project_id": project_id,
                "agent_counts": {
                    row["status"]: row["count"] for row in status_counts
                },
                "team_count": team_count,
                "agents": [dict(a) for a in agents],
            }


# Global database instance
_db: Database | None = None


def get_db() -> Database:
    """Get or create the global database instance."""
    global _db
    if _db is None:
        _db = Database()
    return _db
