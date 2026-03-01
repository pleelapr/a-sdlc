"""Tests for worktrees table -- database migration and CRUD operations."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from a_sdlc.core.database import SCHEMA_VERSION, Database


@pytest.fixture
def temp_db():
    """Create a temporary database instance (fresh, current schema)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=db_path)
        # Create a project and PRD for testing
        db.create_project("test-project", "Test Project", "/tmp/test")
        db.create_prd(
            prd_id="TEST-P0001",
            project_id="test-project",
            title="Test PRD",
            file_path="/tmp/test/prds/TEST-P0001.md",
        )
        db.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-project",
            title="Sprint 1",
            goal="Test sprint",
        )
        yield db


@pytest.fixture
def v5_db():
    """Create a database at schema version 5 (before worktrees table)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_v5.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        # Create v5 schema manually (without worktrees table)
        conn.executescript("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT INTO schema_version (version) VALUES (5);

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
        conn.commit()
        conn.close()

        yield db_path


@pytest.fixture
def v6_db():
    """Create a database at schema version 6 (worktrees without pr_url)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_v6.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        # Create v6 schema (worktrees table WITHOUT pr_url column)
        conn.executescript("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT INTO schema_version (version) VALUES (6);

            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                shortname TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

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
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

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
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

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

            CREATE TABLE worktrees (
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
            CREATE INDEX idx_worktrees_project ON worktrees(project_id);
            CREATE INDEX idx_worktrees_prd ON worktrees(prd_id);
            CREATE INDEX idx_worktrees_sprint ON worktrees(sprint_id);
            CREATE INDEX idx_worktrees_status ON worktrees(status);
        """)
        conn.commit()
        conn.close()

        yield db_path


# =============================================================================
# Schema Version Tests
# =============================================================================


class TestSchemaVersion:
    """Test that the schema version is correctly set to 8."""

    def test_schema_version_constant(self):
        """SCHEMA_VERSION constant should be 8."""
        assert SCHEMA_VERSION == 8

    def test_fresh_db_has_version_8(self, temp_db):
        """A fresh database should have schema version 8."""
        with temp_db.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == 8

    def test_fresh_db_has_worktrees_table(self, temp_db):
        """A fresh database should have the worktrees table."""
        with temp_db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='worktrees'"
            )
            assert cursor.fetchone() is not None


# =============================================================================
# Migration v5 → v6 Tests
# =============================================================================


class TestMigrationV5ToV6:
    """Test the v5 → v6 migration (add worktrees table)."""

    def test_migration_creates_worktrees_table(self, v5_db):
        """Migration from v5 should create the worktrees table."""
        # Opening the database triggers migration
        db = Database(db_path=v5_db)
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='worktrees'"
            )
            assert cursor.fetchone() is not None

    def test_migration_updates_version_to_8(self, v5_db):
        """Migration from v5 should update schema version to 8 (via chained migration)."""
        db = Database(db_path=v5_db)
        with db.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == 8

    def test_migration_creates_indexes(self, v5_db):
        """Migration should create all expected indexes on worktrees table."""
        db = Database(db_path=v5_db)
        expected_indexes = {
            "idx_worktrees_project",
            "idx_worktrees_prd",
            "idx_worktrees_sprint",
            "idx_worktrees_status",
        }
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='worktrees'"
            )
            actual_indexes = {row[0] for row in cursor.fetchall()}
        assert expected_indexes.issubset(actual_indexes)

    def test_migration_preserves_existing_data(self, v5_db):
        """Migration should preserve existing project data."""
        # Insert test data into v5 database before migration
        conn = sqlite3.connect(v5_db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO projects (id, shortname, name, path) VALUES (?, ?, ?, ?)",
            ("proj-1", "PROJ", "Project One", "/tmp/proj1"),
        )
        conn.commit()
        conn.close()

        # Open with Database class (triggers migration)
        db = Database(db_path=v5_db)
        project = db.get_project("proj-1")
        assert project is not None
        assert project["shortname"] == "PROJ"
        assert project["name"] == "Project One"

    def test_migration_worktrees_table_schema(self, v5_db):
        """Migration should create worktrees table with correct columns (including pr_url from v7)."""
        db = Database(db_path=v5_db)
        expected_columns = {
            "id", "project_id", "prd_id", "sprint_id",
            "branch_name", "path", "status", "pr_url", "created_at", "cleaned_at",
        }
        with db.connection() as conn:
            cursor = conn.execute("PRAGMA table_info(worktrees)")
            actual_columns = {row[1] for row in cursor.fetchall()}
        assert actual_columns == expected_columns

    def test_migration_idempotent(self, v5_db):
        """Opening database twice should not cause errors (IF NOT EXISTS)."""
        Database(db_path=v5_db)
        # Opening again on same file should not fail
        db2 = Database(db_path=v5_db)
        with db2.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == 8


# =============================================================================
# Migration v6 -> v7 Tests
# =============================================================================


class TestMigrationV6ToV7:
    """Test the v6 -> v7 migration (add pr_url column to worktrees)."""

    def test_migration_adds_pr_url_column(self, v6_db):
        """Migration from v6 should add pr_url column to worktrees table."""
        db = Database(db_path=v6_db)
        with db.connection() as conn:
            cursor = conn.execute("PRAGMA table_info(worktrees)")
            columns = {row[1] for row in cursor.fetchall()}
        assert "pr_url" in columns

    def test_migration_updates_version_to_8(self, v6_db):
        """Migration from v6 should update schema version to 8 (via chained migration)."""
        db = Database(db_path=v6_db)
        with db.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == 8

    def test_migration_preserves_existing_worktrees(self, v6_db):
        """Migration should preserve existing worktree data."""
        # Insert test data into v6 database before migration
        conn = sqlite3.connect(v6_db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO projects (id, shortname, name, path) VALUES (?, ?, ?, ?)",
            ("proj-1", "PROJ", "Project One", "/tmp/proj1"),
        )
        conn.execute(
            "INSERT INTO prds (id, project_id, title) VALUES (?, ?, ?)",
            ("PROJ-P0001", "proj-1", "Test PRD"),
        )
        conn.execute(
            "INSERT INTO worktrees (id, project_id, prd_id, branch_name, path, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("wt-1", "proj-1", "PROJ-P0001", "feature/test", "/tmp/.worktrees/test", "active"),
        )
        conn.commit()
        conn.close()

        # Open with Database class (triggers migration)
        db = Database(db_path=v6_db)
        wt = db.get_worktree("wt-1")
        assert wt is not None
        assert wt["branch_name"] == "feature/test"
        assert wt["status"] == "active"
        assert wt["pr_url"] is None  # New column should default to NULL

    def test_migration_idempotent(self, v6_db):
        """Opening database twice should not cause errors."""
        Database(db_path=v6_db)
        db2 = Database(db_path=v6_db)
        with db2.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == 8


# =============================================================================
# Worktree CRUD Tests
# =============================================================================


class TestWorktreeCRUD:
    """Test worktree database CRUD operations."""

    def test_create_worktree(self, temp_db):
        """Test creating a worktree record."""
        wt = temp_db.create_worktree(
            worktree_id="wt-001",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="sprint/TEST-S0001/TEST-P0001",
            path="/tmp/test/.worktrees/TEST-P0001",
            sprint_id="TEST-S0001",
        )
        assert wt is not None
        assert wt["id"] == "wt-001"
        assert wt["project_id"] == "test-project"
        assert wt["prd_id"] == "TEST-P0001"
        assert wt["sprint_id"] == "TEST-S0001"
        assert wt["branch_name"] == "sprint/TEST-S0001/TEST-P0001"
        assert wt["path"] == "/tmp/test/.worktrees/TEST-P0001"
        assert wt["status"] == "active"
        assert wt["created_at"] is not None
        assert wt["cleaned_at"] is None

    def test_create_worktree_without_sprint(self, temp_db):
        """Test creating a worktree without a sprint ID."""
        wt = temp_db.create_worktree(
            worktree_id="wt-002",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/test/.worktrees/TEST-P0001",
        )
        assert wt is not None
        assert wt["sprint_id"] is None

    def test_create_worktree_custom_status(self, temp_db):
        """Test creating a worktree with a custom initial status."""
        wt = temp_db.create_worktree(
            worktree_id="wt-003",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/test/.worktrees/TEST-P0001",
            status="completed",
        )
        assert wt["status"] == "completed"

    def test_create_worktree_duplicate_id_raises(self, temp_db):
        """Test that creating a worktree with duplicate ID raises an error."""
        temp_db.create_worktree(
            worktree_id="wt-dup",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/test/.worktrees/TEST-P0001",
        )
        with pytest.raises(sqlite3.IntegrityError):
            temp_db.create_worktree(
                worktree_id="wt-dup",
                project_id="test-project",
                prd_id="TEST-P0001",
                branch_name="feature/TEST-P0001-dup",
                path="/tmp/test/.worktrees/TEST-P0001-dup",
            )

    def test_get_worktree(self, temp_db):
        """Test retrieving a worktree by ID."""
        temp_db.create_worktree(
            worktree_id="wt-get",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/test/.worktrees/TEST-P0001",
            sprint_id="TEST-S0001",
        )
        wt = temp_db.get_worktree("wt-get")
        assert wt is not None
        assert wt["id"] == "wt-get"
        assert wt["prd_id"] == "TEST-P0001"

    def test_get_worktree_not_found(self, temp_db):
        """Test retrieving a nonexistent worktree returns None."""
        wt = temp_db.get_worktree("nonexistent")
        assert wt is None

    def test_get_worktree_by_prd(self, temp_db):
        """Test retrieving the active worktree for a PRD."""
        temp_db.create_worktree(
            worktree_id="wt-prd",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/test/.worktrees/TEST-P0001",
        )
        wt = temp_db.get_worktree_by_prd("TEST-P0001")
        assert wt is not None
        assert wt["prd_id"] == "TEST-P0001"
        assert wt["status"] == "active"

    def test_get_worktree_by_prd_only_active(self, temp_db):
        """Test that get_worktree_by_prd returns only active worktrees."""
        # Create a completed worktree
        temp_db.create_worktree(
            worktree_id="wt-old",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001-old",
            path="/tmp/test/.worktrees/TEST-P0001-old",
            status="completed",
        )
        # Create an active worktree
        temp_db.create_worktree(
            worktree_id="wt-new",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/test/.worktrees/TEST-P0001",
            status="active",
        )
        wt = temp_db.get_worktree_by_prd("TEST-P0001")
        assert wt is not None
        assert wt["id"] == "wt-new"
        assert wt["status"] == "active"

    def test_get_worktree_by_prd_not_found(self, temp_db):
        """Test that get_worktree_by_prd returns None when no active worktree exists."""
        wt = temp_db.get_worktree_by_prd("NONEXISTENT")
        assert wt is None

    def test_get_worktree_by_prd_no_active(self, temp_db):
        """Test that get_worktree_by_prd returns None when only completed worktrees exist."""
        temp_db.create_worktree(
            worktree_id="wt-done",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/test/.worktrees/TEST-P0001",
            status="completed",
        )
        wt = temp_db.get_worktree_by_prd("TEST-P0001")
        assert wt is None


class TestWorktreeList:
    """Test worktree listing and filtering."""

    def _create_test_worktrees(self, db):
        """Helper to create multiple worktrees for listing tests."""
        # Create a second PRD
        db.create_prd(
            prd_id="TEST-P0002",
            project_id="test-project",
            title="Test PRD 2",
            file_path="/tmp/test/prds/TEST-P0002.md",
        )
        # Create worktrees with different statuses and sprints
        db.create_worktree(
            worktree_id="wt-1",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="sprint/TEST-S0001/TEST-P0001",
            path="/tmp/.worktrees/TEST-P0001",
            sprint_id="TEST-S0001",
            status="active",
        )
        db.create_worktree(
            worktree_id="wt-2",
            project_id="test-project",
            prd_id="TEST-P0002",
            branch_name="sprint/TEST-S0001/TEST-P0002",
            path="/tmp/.worktrees/TEST-P0002",
            sprint_id="TEST-S0001",
            status="completed",
        )
        db.create_worktree(
            worktree_id="wt-3",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001-v2",
            path="/tmp/.worktrees/TEST-P0001-v2",
            status="abandoned",
        )

    def test_list_all_worktrees(self, temp_db):
        """Test listing all worktrees for a project."""
        self._create_test_worktrees(temp_db)
        worktrees = temp_db.list_worktrees("test-project")
        assert len(worktrees) == 3

    def test_list_worktrees_empty(self, temp_db):
        """Test listing worktrees when none exist."""
        worktrees = temp_db.list_worktrees("test-project")
        assert worktrees == []

    def test_list_worktrees_filter_by_status(self, temp_db):
        """Test listing worktrees filtered by status."""
        self._create_test_worktrees(temp_db)
        active = temp_db.list_worktrees("test-project", status="active")
        assert len(active) == 1
        assert active[0]["status"] == "active"

        completed = temp_db.list_worktrees("test-project", status="completed")
        assert len(completed) == 1
        assert completed[0]["status"] == "completed"

    def test_list_worktrees_filter_by_sprint(self, temp_db):
        """Test listing worktrees filtered by sprint ID."""
        self._create_test_worktrees(temp_db)
        sprint_wts = temp_db.list_worktrees("test-project", sprint_id="TEST-S0001")
        assert len(sprint_wts) == 2
        for wt in sprint_wts:
            assert wt["sprint_id"] == "TEST-S0001"

    def test_list_worktrees_filter_by_status_and_sprint(self, temp_db):
        """Test listing worktrees filtered by both status and sprint."""
        self._create_test_worktrees(temp_db)
        results = temp_db.list_worktrees(
            "test-project", status="active", sprint_id="TEST-S0001"
        )
        assert len(results) == 1
        assert results[0]["id"] == "wt-1"

    def test_list_worktrees_ordered_by_created_at_desc(self, temp_db):
        """Test that worktrees are ordered by created_at descending."""
        self._create_test_worktrees(temp_db)
        worktrees = temp_db.list_worktrees("test-project")
        assert len(worktrees) == 3
        # Most recently created should be first
        assert worktrees[0]["id"] == "wt-3"


class TestWorktreeUpdate:
    """Test worktree update operations."""

    def _create_worktree(self, db):
        """Helper to create a worktree."""
        return db.create_worktree(
            worktree_id="wt-upd",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/.worktrees/TEST-P0001",
            sprint_id="TEST-S0001",
        )

    def test_update_worktree_status(self, temp_db):
        """Test updating worktree status."""
        self._create_worktree(temp_db)
        updated = temp_db.update_worktree("wt-upd", status="completed")
        assert updated is not None
        assert updated["status"] == "completed"

    def test_update_worktree_status_sets_cleaned_at(self, temp_db):
        """Test that setting status to 'completed' auto-sets cleaned_at."""
        self._create_worktree(temp_db)
        updated = temp_db.update_worktree("wt-upd", status="completed")
        assert updated["cleaned_at"] is not None

    def test_update_worktree_abandoned_sets_cleaned_at(self, temp_db):
        """Test that setting status to 'abandoned' auto-sets cleaned_at."""
        self._create_worktree(temp_db)
        updated = temp_db.update_worktree("wt-upd", status="abandoned")
        assert updated["cleaned_at"] is not None

    def test_update_worktree_active_does_not_set_cleaned_at(self, temp_db):
        """Test that setting status to 'active' does NOT set cleaned_at."""
        self._create_worktree(temp_db)
        updated = temp_db.update_worktree("wt-upd", status="active")
        assert updated["status"] == "active"
        assert updated["cleaned_at"] is None

    def test_update_worktree_pr_url(self, temp_db):
        """Test updating worktree with pr_url field."""
        self._create_worktree(temp_db)
        updated = temp_db.update_worktree(
            "wt-upd",
            pr_url="https://github.com/org/repo/pull/42",
        )
        assert updated["status"] == "active"
        assert updated["pr_url"] == "https://github.com/org/repo/pull/42"

    def test_update_worktree_pr_url_persists(self, temp_db):
        """Test that pr_url is persisted and retrievable."""
        self._create_worktree(temp_db)
        temp_db.update_worktree(
            "wt-upd",
            pr_url="https://github.com/org/repo/pull/99",
        )
        wt = temp_db.get_worktree("wt-upd")
        assert wt["pr_url"] == "https://github.com/org/repo/pull/99"

    def test_create_worktree_pr_url_initially_none(self, temp_db):
        """Test that pr_url is None on creation."""
        wt = temp_db.create_worktree(
            worktree_id="wt-pr-none",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/.worktrees/TEST-P0001",
        )
        assert wt["pr_url"] is None

    def test_update_worktree_no_kwargs(self, temp_db):
        """Test update_worktree with no kwargs returns current worktree."""
        created = self._create_worktree(temp_db)
        result = temp_db.update_worktree("wt-upd")
        assert result is not None
        assert result["id"] == created["id"]

    def test_update_worktree_path(self, temp_db):
        """Test updating worktree path."""
        self._create_worktree(temp_db)
        updated = temp_db.update_worktree(
            "wt-upd", path="/tmp/.worktrees/TEST-P0001-moved"
        )
        assert updated["path"] == "/tmp/.worktrees/TEST-P0001-moved"

    def test_update_worktree_not_found(self, temp_db):
        """Test updating a nonexistent worktree returns None."""
        result = temp_db.update_worktree("nonexistent", status="completed")
        assert result is None

    def test_update_worktree_explicit_cleaned_at(self, temp_db):
        """Test that explicit cleaned_at overrides auto-set."""
        self._create_worktree(temp_db)
        updated = temp_db.update_worktree(
            "wt-upd", status="completed", cleaned_at="2026-01-01T00:00:00+00:00"
        )
        assert updated["cleaned_at"] == "2026-01-01T00:00:00+00:00"


class TestWorktreeDelete:
    """Test worktree deletion."""

    def test_delete_worktree(self, temp_db):
        """Test deleting a worktree record."""
        temp_db.create_worktree(
            worktree_id="wt-del",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/.worktrees/TEST-P0001",
        )
        result = temp_db.delete_worktree("wt-del")
        assert result is True
        assert temp_db.get_worktree("wt-del") is None

    def test_delete_worktree_not_found(self, temp_db):
        """Test deleting a nonexistent worktree returns False."""
        result = temp_db.delete_worktree("nonexistent")
        assert result is False

    def test_cascade_delete_with_prd(self, temp_db):
        """Test that deleting a PRD cascades to delete its worktrees."""
        temp_db.create_worktree(
            worktree_id="wt-cascade",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/.worktrees/TEST-P0001",
        )
        assert temp_db.get_worktree("wt-cascade") is not None
        temp_db.delete_prd("TEST-P0001")
        assert temp_db.get_worktree("wt-cascade") is None

    def test_cascade_delete_with_project(self, temp_db):
        """Test that deleting a project cascades to delete its worktrees."""
        temp_db.create_worktree(
            worktree_id="wt-proj-cascade",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/.worktrees/TEST-P0001",
        )
        assert temp_db.get_worktree("wt-proj-cascade") is not None
        temp_db.delete_project("test-project")
        assert temp_db.get_worktree("wt-proj-cascade") is None


class TestWorktreeSprintRelationship:
    """Test worktree-sprint relationship behavior."""

    def test_sprint_set_null_on_delete(self, temp_db):
        """Test that deleting a sprint sets worktree.sprint_id to NULL."""
        temp_db.create_worktree(
            worktree_id="wt-sprint",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="sprint/TEST-S0001/TEST-P0001",
            path="/tmp/.worktrees/TEST-P0001",
            sprint_id="TEST-S0001",
        )
        wt = temp_db.get_worktree("wt-sprint")
        assert wt["sprint_id"] == "TEST-S0001"

        temp_db.delete_sprint("TEST-S0001")
        wt = temp_db.get_worktree("wt-sprint")
        assert wt is not None
        assert wt["sprint_id"] is None


class TestWorktreeTimestamps:
    """Test worktree timestamp handling."""

    def test_created_at_set_on_create(self, temp_db):
        """Test that created_at is set when creating a worktree."""
        wt = temp_db.create_worktree(
            worktree_id="wt-ts",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/.worktrees/TEST-P0001",
        )
        assert wt["created_at"] is not None

    def test_cleaned_at_initially_null(self, temp_db):
        """Test that cleaned_at is NULL on creation."""
        wt = temp_db.create_worktree(
            worktree_id="wt-ts2",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="feature/TEST-P0001",
            path="/tmp/.worktrees/TEST-P0001",
        )
        assert wt["cleaned_at"] is None


# =============================================================================
# Chained Migration Tests
# =============================================================================


class TestChainedMigration:
    """Test that migration chains work correctly through multiple versions."""

    def test_v4_to_v8_migration(self):
        """Test migration from v4 (no designs, no worktrees, no reviews) to v8."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_v4.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row

            # Create v4 schema (no designs table, no worktrees table)
            conn.executescript("""
                CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
                INSERT INTO schema_version (version) VALUES (4);

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
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

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
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

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
            """)
            conn.commit()
            conn.close()

            # Open with Database class (triggers chained migration v4→v5→v6→v7→v8)
            db = Database(db_path=db_path)

            with db.connection() as conn:
                cursor = conn.execute("SELECT version FROM schema_version")
                assert cursor.fetchone()[0] == 8

                # Both designs and worktrees tables should exist
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='designs'"
                )
                assert cursor.fetchone() is not None

                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='worktrees'"
                )
                assert cursor.fetchone() is not None
