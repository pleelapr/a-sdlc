"""Tests for database schema version and migration integrity."""

import tempfile
from pathlib import Path

import pytest

from a_sdlc.core.database import SCHEMA_VERSION, Database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db():
    """Create a temporary database instance (fresh, current schema)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=db_path)
        db.create_project("test-project", "Test Project")
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
        db.create_task(
            task_id="TEST-T00001",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Test Task",
            file_path="/tmp/test/tasks/TEST-T00001.md",
        )
        yield db


# ---------------------------------------------------------------------------
# TestSchemaVersion
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    """Basic version checks for current schema."""

    def test_schema_version_constant(self):
        assert SCHEMA_VERSION >= 14

    def test_fresh_db_has_current_version(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            assert row["version"] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# TestCoreTables
# ---------------------------------------------------------------------------


class TestCoreTables:
    """Verify core tables exist in fresh database."""

    def test_projects_table_exists(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
            ).fetchone()
            assert row is not None

    def test_prds_table_exists(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='prds'"
            ).fetchone()
            assert row is not None

    def test_tasks_table_exists(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
            ).fetchone()
            assert row is not None

    def test_sprints_table_exists(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sprints'"
            ).fetchone()
            assert row is not None

    def test_sync_mappings_table_exists(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_mappings'"
            ).fetchone()
            assert row is not None

    def test_designs_table_exists(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='designs'"
            ).fetchone()
            assert row is not None

    def test_reviews_table_exists(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='reviews'"
            ).fetchone()
            assert row is not None

    def test_audit_log_table_exists(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
            ).fetchone()
            assert row is not None

    def test_requirements_table_exists(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='requirements'"
            ).fetchone()
            assert row is not None

    def test_challenge_records_table_exists(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='challenge_records'"
            ).fetchone()
            assert row is not None

    def test_worktrees_table_exists(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='worktrees'"
            ).fetchone()
            assert row is not None

    def test_external_config_table_exists(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='external_config'"
            ).fetchone()
            assert row is not None


# ---------------------------------------------------------------------------
# TestTasksColumns
# ---------------------------------------------------------------------------


class TestTasksColumns:
    """Verify tasks table has expected columns (no assigned_agent_id)."""

    def test_tasks_columns(self, temp_db):
        with temp_db.connection() as conn:
            info = conn.execute("PRAGMA table_info(tasks)").fetchall()
            col_names = [r["name"] for r in info]
            expected = [
                "id", "project_id", "prd_id", "title", "file_path",
                "status", "priority", "component",
                "created_at", "updated_at", "started_at", "completed_at",
            ]
            assert col_names == expected

    def test_tasks_no_assigned_agent_id(self, temp_db):
        with temp_db.connection() as conn:
            info = conn.execute("PRAGMA table_info(tasks)").fetchall()
            col_names = [r["name"] for r in info]
            assert "assigned_agent_id" not in col_names


# ---------------------------------------------------------------------------
# TestMigrationPreservesData
# ---------------------------------------------------------------------------


class TestMigrationPreservesData:
    """Verify migration preserves existing project data."""

    def test_project_data_preserved(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", ("test-project",)
            ).fetchone()
            assert row is not None
            assert row["name"] == "Test Project"

    def test_migration_idempotent(self, temp_db):
        """Opening the same DB twice should not raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            Database(db_path=db_path)
            # Opening a second time should not raise
            db2 = Database(db_path=db_path)
            with db2.connection() as conn:
                row = conn.execute("SELECT version FROM schema_version").fetchone()
                assert row["version"] == SCHEMA_VERSION
