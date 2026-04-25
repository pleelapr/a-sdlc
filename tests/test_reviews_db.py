"""Tests for reviews table -- database migration and CRUD operations."""

import json
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
        # Create a project, PRD, and task for testing
        db.create_project("test-project", "Test Project", "/tmp/test")
        db.create_prd(
            prd_id="TEST-P0001",
            project_id="test-project",
            title="Test PRD",
            file_path="/tmp/test/prds/TEST-P0001.md",
        )
        db.create_task(
            task_id="TEST-T00001",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Test Task",
            file_path="/tmp/test/tasks/TEST-T00001.md",
        )
        yield db


@pytest.fixture
def v7_db():
    """Create a database at schema version 7 (before reviews table)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_v7.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        # Create v7 schema manually (without reviews table)
        conn.executescript("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT INTO schema_version (version) VALUES (7);

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
        """)
        conn.commit()
        conn.close()

        yield db_path


# =============================================================================
# Schema Version Tests
# =============================================================================


class TestSchemaVersion:
    """Test that the schema version is at least 8 (reviews table)."""

    def test_schema_version_constant(self):
        """SCHEMA_VERSION constant should be at least 8 (reviews table)."""
        assert SCHEMA_VERSION >= 8

    def test_fresh_db_has_version_8(self, temp_db):
        """A fresh database should have schema version 8."""
        with temp_db.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_fresh_db_has_reviews_table(self, temp_db):
        """A fresh database should have the reviews table."""
        with temp_db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='reviews'"
            )
            assert cursor.fetchone() is not None


# =============================================================================
# Migration v7 → v8 Tests
# =============================================================================


class TestMigrationV7ToV8:
    """Test the v7 → v8 migration (add reviews table)."""

    def test_migration_creates_reviews_table(self, v7_db):
        """Migration from v7 should create the reviews table."""
        db = Database(db_path=v7_db)
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='reviews'"
            )
            assert cursor.fetchone() is not None

    def test_migration_updates_version_to_8(self, v7_db):
        """Migration from v7 should update schema version to 8."""
        db = Database(db_path=v7_db)
        with db.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_migration_creates_indexes(self, v7_db):
        """Migration should create all expected indexes on reviews table."""
        db = Database(db_path=v7_db)
        expected_indexes = {
            "idx_reviews_task",
            "idx_reviews_project",
        }
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='reviews'"
            )
            actual_indexes = {row[0] for row in cursor.fetchall()}
        assert expected_indexes.issubset(actual_indexes)

    def test_migration_reviews_table_schema(self, v7_db):
        """Migration should create reviews table with correct columns."""
        db = Database(db_path=v7_db)
        expected_columns = {
            "id", "task_id", "project_id", "round", "reviewer_type",
            "verdict", "findings", "test_output", "created_at",
        }
        with db.connection() as conn:
            cursor = conn.execute("PRAGMA table_info(reviews)")
            actual_columns = {row[1] for row in cursor.fetchall()}
        assert actual_columns == expected_columns

    def test_migration_preserves_existing_data(self, v7_db):
        """Migration should preserve existing project data."""
        conn = sqlite3.connect(v7_db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO projects (id, shortname, name, path) VALUES (?, ?, ?, ?)",
            ("proj-1", "PROJ", "Project One", "/tmp/proj1"),
        )
        conn.commit()
        conn.close()

        db = Database(db_path=v7_db)
        project = db.get_project("proj-1")
        assert project is not None
        assert project["shortname"] == "PROJ"
        assert project["name"] == "Project One"

    def test_migration_idempotent(self, v7_db):
        """Opening database twice should not cause errors (IF NOT EXISTS)."""
        Database(db_path=v7_db)
        db2 = Database(db_path=v7_db)
        with db2.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == SCHEMA_VERSION


# =============================================================================
# Review CRUD Tests
# =============================================================================


class TestCreateReview:
    """Test create_review() with valid and invalid inputs."""

    def test_create_review_basic(self, temp_db):
        """Test creating a review with required fields."""
        review = temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="pass",
        )
        assert review is not None
        assert review["id"] is not None
        assert review["task_id"] == "TEST-T00001"
        assert review["project_id"] == "test-project"
        assert review["round"] == 1
        assert review["reviewer_type"] == "self"
        assert review["verdict"] == "pass"
        assert review["findings"] is None
        assert review["test_output"] is None
        assert review["created_at"] is not None

    def test_create_review_with_findings(self, temp_db):
        """Test creating a review with findings JSON."""
        findings = json.dumps([
            {"type": "error", "message": "Missing null check", "file": "main.py", "line": 42},
            {"type": "warning", "message": "Unused import", "file": "utils.py", "line": 3},
        ])
        review = temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="subagent",
            verdict="request_changes",
            findings=findings,
        )
        assert review["findings"] == findings
        parsed = json.loads(review["findings"])
        assert len(parsed) == 2
        assert parsed[0]["type"] == "error"

    def test_create_review_with_test_output(self, temp_db):
        """Test creating a review with test output."""
        test_output = "PASSED tests/test_main.py::test_hello\n1 passed in 0.5s"
        review = temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="pass",
            test_output=test_output,
        )
        assert review["test_output"] == test_output

    def test_create_review_all_verdicts(self, temp_db):
        """Test creating reviews with each valid verdict."""
        for i, verdict in enumerate(("pass", "fail", "approve", "request_changes", "escalate"), 1):
            review = temp_db.create_review(
                task_id="TEST-T00001",
                project_id="test-project",
                round_num=i,
                reviewer_type="self",
                verdict=verdict,
            )
            assert review["verdict"] == verdict

    def test_create_review_both_reviewer_types(self, temp_db):
        """Test creating reviews with each valid reviewer type."""
        for reviewer_type in ("self", "subagent"):
            review = temp_db.create_review(
                task_id="TEST-T00001",
                project_id="test-project",
                round_num=1,
                reviewer_type=reviewer_type,
                verdict="pass",
            )
            assert review["reviewer_type"] == reviewer_type

    def test_create_review_invalid_reviewer_type(self, temp_db):
        """Test that invalid reviewer_type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid reviewer_type"):
            temp_db.create_review(
                task_id="TEST-T00001",
                project_id="test-project",
                round_num=1,
                reviewer_type="unknown",
                verdict="pass",
            )

    def test_create_review_invalid_verdict(self, temp_db):
        """Test that invalid verdict raises ValueError."""
        with pytest.raises(ValueError, match="Invalid verdict"):
            temp_db.create_review(
                task_id="TEST-T00001",
                project_id="test-project",
                round_num=1,
                reviewer_type="self",
                verdict="maybe",
            )

    def test_create_review_nonexistent_task_raises(self, temp_db):
        """Test that referencing a nonexistent task raises IntegrityError."""
        with pytest.raises(sqlite3.IntegrityError):
            temp_db.create_review(
                task_id="NONEXISTENT-T99999",
                project_id="test-project",
                round_num=1,
                reviewer_type="self",
                verdict="pass",
            )

    def test_create_review_nonexistent_project_raises(self, temp_db):
        """Test that referencing a nonexistent project raises IntegrityError."""
        with pytest.raises(sqlite3.IntegrityError):
            temp_db.create_review(
                task_id="TEST-T00001",
                project_id="nonexistent-project",
                round_num=1,
                reviewer_type="self",
                verdict="pass",
            )

    def test_create_review_autoincrement_id(self, temp_db):
        """Test that review IDs are auto-incremented."""
        r1 = temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="fail",
        )
        r2 = temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=2,
            reviewer_type="self",
            verdict="pass",
        )
        assert r2["id"] > r1["id"]


# =============================================================================
# get_reviews_for_task Tests
# =============================================================================


class TestGetReviewsForTask:
    """Test get_reviews_for_task() returns correct results in order."""

    def test_returns_empty_list_for_no_reviews(self, temp_db):
        """Test that an empty list is returned when no reviews exist."""
        reviews = temp_db.get_reviews_for_task("TEST-T00001")
        assert reviews == []

    def test_returns_all_reviews_for_task(self, temp_db):
        """Test that all reviews for a task are returned."""
        for i in range(1, 4):
            temp_db.create_review(
                task_id="TEST-T00001",
                project_id="test-project",
                round_num=i,
                reviewer_type="self",
                verdict="fail" if i < 3 else "pass",
            )
        reviews = temp_db.get_reviews_for_task("TEST-T00001")
        assert len(reviews) == 3

    def test_ordered_by_round_asc(self, temp_db):
        """Test that reviews are ordered by round ascending."""
        # Insert in reverse order to verify sorting
        for round_num in (3, 1, 2):
            temp_db.create_review(
                task_id="TEST-T00001",
                project_id="test-project",
                round_num=round_num,
                reviewer_type="self",
                verdict="fail",
            )
        reviews = temp_db.get_reviews_for_task("TEST-T00001")
        rounds = [r["round"] for r in reviews]
        assert rounds == [1, 2, 3]

    def test_does_not_return_reviews_for_other_tasks(self, temp_db):
        """Test that only reviews for the specified task are returned."""
        # Create a second task
        temp_db.create_task(
            task_id="TEST-T00002",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Other Task",
        )
        temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="pass",
        )
        temp_db.create_review(
            task_id="TEST-T00002",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="fail",
        )
        reviews = temp_db.get_reviews_for_task("TEST-T00001")
        assert len(reviews) == 1
        assert reviews[0]["task_id"] == "TEST-T00001"

    def test_returns_nonexistent_task_as_empty(self, temp_db):
        """Test that a nonexistent task returns an empty list."""
        reviews = temp_db.get_reviews_for_task("NONEXISTENT-T99999")
        assert reviews == []


# =============================================================================
# get_latest_approved_review Tests
# =============================================================================


class TestGetLatestApprovedReview:
    """Test get_latest_approved_review() behavior."""

    def test_returns_none_when_no_reviews(self, temp_db):
        """Test that None is returned when no reviews exist."""
        result = temp_db.get_latest_approved_review("TEST-T00001")
        assert result is None

    def test_returns_none_when_no_approved_reviews(self, temp_db):
        """Test that None is returned when no approved/passed reviews exist."""
        temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="fail",
        )
        temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=2,
            reviewer_type="subagent",
            verdict="request_changes",
        )
        result = temp_db.get_latest_approved_review("TEST-T00001")
        assert result is None

    def test_returns_pass_verdict(self, temp_db):
        """Test that a review with 'pass' verdict is returned."""
        temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="pass",
        )
        result = temp_db.get_latest_approved_review("TEST-T00001")
        assert result is not None
        assert result["verdict"] == "pass"

    def test_returns_approve_verdict(self, temp_db):
        """Test that a review with 'approve' verdict is returned."""
        temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="subagent",
            verdict="approve",
        )
        result = temp_db.get_latest_approved_review("TEST-T00001")
        assert result is not None
        assert result["verdict"] == "approve"

    def test_returns_most_recent_approved(self, temp_db):
        """Test that the most recent approved review is returned when multiple exist."""
        temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="pass",
        )
        temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=2,
            reviewer_type="self",
            verdict="fail",
        )
        temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=3,
            reviewer_type="subagent",
            verdict="approve",
        )
        result = temp_db.get_latest_approved_review("TEST-T00001")
        assert result is not None
        assert result["verdict"] == "approve"
        assert result["round"] == 3

    def test_ignores_non_approved_verdicts(self, temp_db):
        """Test that escalate verdict is not considered approved."""
        temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="escalate",
        )
        result = temp_db.get_latest_approved_review("TEST-T00001")
        assert result is None


# =============================================================================
# Cascade Deletion Tests
# =============================================================================


class TestReviewCascadeDeletion:
    """Test that reviews are deleted when parent entities are removed."""

    def test_cascade_delete_with_task(self, temp_db):
        """Test that deleting a task cascades to delete its reviews."""
        temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="pass",
        )
        reviews = temp_db.get_reviews_for_task("TEST-T00001")
        assert len(reviews) == 1

        temp_db.delete_task("TEST-T00001")
        reviews = temp_db.get_reviews_for_task("TEST-T00001")
        assert reviews == []

    def test_cascade_delete_with_project(self, temp_db):
        """Test that deleting a project cascades to delete its reviews."""
        temp_db.create_review(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="pass",
        )
        reviews = temp_db.get_reviews_for_task("TEST-T00001")
        assert len(reviews) == 1

        temp_db.delete_project("test-project")

        # Verify review is gone by querying the table directly
        with temp_db.connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM reviews")
            count = cursor.fetchone()[0]
        assert count == 0

    def test_multiple_reviews_cascade_with_task(self, temp_db):
        """Test that all reviews for a task are deleted on cascade."""
        for i in range(1, 4):
            temp_db.create_review(
                task_id="TEST-T00001",
                project_id="test-project",
                round_num=i,
                reviewer_type="self" if i % 2 else "subagent",
                verdict="fail" if i < 3 else "pass",
            )
        reviews = temp_db.get_reviews_for_task("TEST-T00001")
        assert len(reviews) == 3

        temp_db.delete_task("TEST-T00001")
        reviews = temp_db.get_reviews_for_task("TEST-T00001")
        assert reviews == []


# =============================================================================
# Chained Migration Tests
# =============================================================================


class TestChainedMigrationToV8:
    """Test that migration chains work correctly through to version 8."""

    def test_v7_to_v8_migration(self, v7_db):
        """Test migration from v7 to v8 via chained migration."""
        db = Database(db_path=v7_db)
        with db.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            assert cursor.fetchone()[0] == SCHEMA_VERSION

            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='reviews'"
            )
            assert cursor.fetchone() is not None
