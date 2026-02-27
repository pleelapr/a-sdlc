"""Tests for file-based storage."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from a_sdlc.core.database import SCHEMA_VERSION, Database
from a_sdlc.storage import FileStorage, ensure_templates, get_template_path


@pytest.fixture
def temp_storage():
    """Create a temporary storage instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileStorage(base_path=Path(tmpdir))
        yield storage


class TestFileStorageBasics:
    """Test basic FileStorage functionality."""

    def test_creates_required_directories(self, temp_storage):
        """Test that storage creates required directories."""
        # In the hybrid architecture, content directories are managed by ContentManager
        assert temp_storage.base_path.exists()
        assert temp_storage.templates_dir.exists()


class TestProjectOperations:
    """Test project CRUD operations."""

    def test_create_project(self, temp_storage, tmp_path):
        """Test creating a new project."""
        project_path = str(tmp_path / "test")
        project = temp_storage.create_project(
            project_id="test-project",
            name="Test Project",
            path=project_path
        )
        assert project["id"] == "test-project"
        assert project["name"] == "Test Project"
        assert project["path"] == project_path

    def test_get_project(self, temp_storage, tmp_path):
        """Test retrieving a project."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        project = temp_storage.get_project("test-project")
        assert project is not None
        assert project["id"] == "test-project"

    def test_get_project_by_path(self, temp_storage, tmp_path):
        """Test retrieving a project by path."""
        project_path = str(tmp_path / "test")
        temp_storage.create_project("test-project", "Test Project", project_path)
        project = temp_storage.get_project_by_path(project_path)
        assert project is not None
        assert project["id"] == "test-project"

    def test_list_projects(self, temp_storage, tmp_path):
        """Test listing projects."""
        temp_storage.create_project("project-1", "Project 1", str(tmp_path / "p1"))
        temp_storage.create_project("project-2", "Project 2", str(tmp_path / "p2"))
        projects = temp_storage.list_projects()
        assert len(projects) == 2

    def test_delete_project(self, temp_storage, tmp_path):
        """Test deleting a project."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        result = temp_storage.delete_project("test-project")
        assert result is True
        assert temp_storage.get_project("test-project") is None


class TestPRDOperations:
    """Test PRD CRUD operations."""

    def test_create_prd(self, temp_storage, tmp_path):
        """Test creating a PRD."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        prd = temp_storage.create_prd(
            prd_id="feature-auth",
            project_id="test-project",
            title="Authentication Feature",
            status="draft"
        )
        assert prd["id"] == "feature-auth"
        assert prd["title"] == "Authentication Feature"
        assert prd["status"] == "draft"

    def test_create_prd_with_sprint(self, temp_storage, tmp_path):
        """Test creating a PRD with sprint assignment."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        prd = temp_storage.create_prd(
            prd_id="feature-auth",
            project_id="test-project",
            title="Auth Feature",
            sprint_id="SPRINT-01"
        )
        assert prd["sprint_id"] == "SPRINT-01"

    def test_get_prd(self, temp_storage, tmp_path):
        """Test retrieving a PRD."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_prd("feature-auth", "test-project", "Auth Feature")
        prd = temp_storage.get_prd("feature-auth")
        assert prd is not None
        assert prd["id"] == "feature-auth"

    def test_list_prds(self, temp_storage, tmp_path):
        """Test listing PRDs."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_prd("prd-1", "test-project", "PRD 1")
        temp_storage.create_prd("prd-2", "test-project", "PRD 2")
        prds = temp_storage.list_prds("test-project")
        assert len(prds) == 2

    def test_list_prds_by_sprint(self, temp_storage, tmp_path):
        """Test filtering PRDs by sprint."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        temp_storage.create_prd("prd-1", "test-project", "PRD 1", sprint_id="SPRINT-01")
        temp_storage.create_prd("prd-2", "test-project", "PRD 2")  # No sprint
        prds = temp_storage.list_prds("test-project", sprint_id="SPRINT-01")
        assert len(prds) == 1
        assert prds[0]["id"] == "prd-1"

    def test_update_prd(self, temp_storage, tmp_path):
        """Test updating a PRD."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_prd("feature-auth", "test-project", "Auth Feature")
        updated = temp_storage.update_prd("feature-auth", status="ready")
        assert updated is not None
        assert updated["status"] == "ready"

    def test_delete_prd(self, temp_storage, tmp_path):
        """Test deleting a PRD."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_prd("feature-auth", "test-project", "Auth Feature")
        result = temp_storage.delete_prd("feature-auth")
        assert result is True
        assert temp_storage.get_prd("feature-auth") is None


class TestTaskOperations:
    """Test task CRUD operations."""

    def test_create_task(self, temp_storage, tmp_path):
        """Test creating a task."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        task = temp_storage.create_task(
            task_id="TASK-001",
            project_id="test-project",
            title="Setup auth config",
            priority="high"
        )
        assert task["id"] == "TASK-001"
        assert task["title"] == "Setup auth config"
        assert task["priority"] == "high"
        assert task["status"] == "pending"

    def test_get_task(self, temp_storage, tmp_path):
        """Test retrieving a task."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_task("TASK-001", "test-project", "Test Task")
        task = temp_storage.get_task("TASK-001")
        assert task is not None
        assert task["id"] == "TASK-001"

    def test_list_tasks(self, temp_storage, tmp_path):
        """Test listing tasks."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_task("TASK-001", "test-project", "Task 1")
        temp_storage.create_task("TASK-002", "test-project", "Task 2")
        tasks = temp_storage.list_tasks("test-project")
        assert len(tasks) == 2

    def test_list_tasks_by_status(self, temp_storage, tmp_path):
        """Test filtering tasks by status."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_task("TASK-001", "test-project", "Task 1", status="pending")
        temp_storage.create_task("TASK-002", "test-project", "Task 2", status="completed")
        tasks = temp_storage.list_tasks("test-project", status="pending")
        assert len(tasks) == 1
        assert tasks[0]["id"] == "TASK-001"

    def test_update_task(self, temp_storage, tmp_path):
        """Test updating a task."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_task("TASK-001", "test-project", "Test Task")
        updated = temp_storage.update_task("TASK-001", status="in_progress")
        assert updated is not None
        assert updated["status"] == "in_progress"

    def test_update_task_to_completed_sets_completed_at(self, temp_storage, tmp_path):
        """Test that completing a task sets completed_at."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_task("TASK-001", "test-project", "Test Task")
        updated = temp_storage.update_task("TASK-001", status="completed")
        assert updated["completed_at"] is not None

    def test_delete_task(self, temp_storage, tmp_path):
        """Test deleting a task."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_task("TASK-001", "test-project", "Test Task")
        result = temp_storage.delete_task("TASK-001")
        assert result is True
        assert temp_storage.get_task("TASK-001") is None

    def test_get_next_task_id(self, temp_storage, tmp_path):
        """Test task ID generation uses shortname format."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"), shortname="TEST")
        next_id = temp_storage.get_next_task_id("test-project")
        assert next_id == "TEST-T00001"


class TestSprintOperations:
    """Test sprint CRUD operations."""

    def test_create_sprint(self, temp_storage, tmp_path):
        """Test creating a sprint."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        sprint = temp_storage.create_sprint(
            sprint_id="SPRINT-01",
            project_id="test-project",
            title="Sprint 1",
            goal="Complete auth feature"
        )
        assert sprint["id"] == "SPRINT-01"
        assert sprint["title"] == "Sprint 1"
        assert sprint["goal"] == "Complete auth feature"
        assert sprint["status"] == "planned"

    def test_get_sprint(self, temp_storage, tmp_path):
        """Test retrieving a sprint."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        sprint = temp_storage.get_sprint("SPRINT-01")
        assert sprint is not None
        assert sprint["id"] == "SPRINT-01"

    def test_get_sprint_with_prd_count(self, temp_storage, tmp_path):
        """Test that get_sprint includes PRD count."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        temp_storage.create_prd("prd-1", "test-project", "PRD 1", sprint_id="SPRINT-01")
        sprint = temp_storage.get_sprint("SPRINT-01")
        assert sprint["prd_count"] == 1

    def test_list_sprints(self, temp_storage, tmp_path):
        """Test listing sprints."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        temp_storage.create_sprint("SPRINT-02", "test-project", "Sprint 2")
        sprints = temp_storage.list_sprints("test-project")
        assert len(sprints) == 2

    def test_update_sprint_to_active(self, temp_storage, tmp_path):
        """Test that activating a sprint sets started_at."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        updated = temp_storage.update_sprint("SPRINT-01", status="active")
        assert updated["status"] == "active"
        assert updated["started_at"] is not None

    def test_update_sprint_to_completed(self, temp_storage, tmp_path):
        """Test that completing a sprint sets completed_at."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        updated = temp_storage.update_sprint("SPRINT-01", status="completed")
        assert updated["status"] == "completed"
        assert updated["completed_at"] is not None

    def test_delete_sprint_unlinks_prds(self, temp_storage, tmp_path):
        """Test that deleting a sprint unlinks its PRDs."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        temp_storage.create_prd("prd-1", "test-project", "PRD 1", sprint_id="SPRINT-01")
        temp_storage.delete_sprint("SPRINT-01")
        prd = temp_storage.get_prd("prd-1")
        assert prd["sprint_id"] is None

    def test_get_sprint_prds(self, temp_storage, tmp_path):
        """Test getting PRDs for a sprint."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        temp_storage.create_prd("prd-1", "test-project", "PRD 1", sprint_id="SPRINT-01")
        temp_storage.create_prd("prd-2", "test-project", "PRD 2", sprint_id="SPRINT-01")
        prds = temp_storage.get_sprint_prds("SPRINT-01")
        assert len(prds) == 2

    def test_assign_prd_to_sprint(self, temp_storage, tmp_path):
        """Test assigning a PRD to a sprint."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        temp_storage.create_prd("prd-1", "test-project", "PRD 1")
        updated = temp_storage.assign_prd_to_sprint("prd-1", "SPRINT-01")
        assert updated["sprint_id"] == "SPRINT-01"

    def test_get_next_sprint_id(self, temp_storage, tmp_path):
        """Test sprint ID generation uses shortname format."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"), shortname="TEST")
        next_id = temp_storage.get_next_sprint_id("test-project")
        assert next_id == "TEST-S0001"


class TestSyncMappingOperations:
    """Test sync mapping operations."""

    def test_create_sync_mapping(self, temp_storage):
        """Test creating a sync mapping."""
        mapping = temp_storage.create_sync_mapping(
            entity_type="sprint",
            local_id="SPRINT-01",
            external_system="linear",
            external_id="abc123"
        )
        assert mapping["entity_type"] == "sprint"
        assert mapping["local_id"] == "SPRINT-01"
        assert mapping["external_system"] == "linear"
        assert mapping["external_id"] == "abc123"
        assert mapping["sync_status"] == "synced"

    def test_get_sync_mapping(self, temp_storage):
        """Test retrieving a sync mapping."""
        temp_storage.create_sync_mapping("sprint", "SPRINT-01", "linear", "abc123")
        mapping = temp_storage.get_sync_mapping("sprint", "SPRINT-01", "linear")
        assert mapping is not None
        assert mapping["external_id"] == "abc123"

    def test_get_sync_mapping_by_external(self, temp_storage):
        """Test retrieving a sync mapping by external ID."""
        temp_storage.create_sync_mapping("sprint", "SPRINT-01", "linear", "abc123")
        mapping = temp_storage.get_sync_mapping_by_external("sprint", "linear", "abc123")
        assert mapping is not None
        assert mapping["local_id"] == "SPRINT-01"

    def test_list_sync_mappings(self, temp_storage):
        """Test listing sync mappings."""
        temp_storage.create_sync_mapping("sprint", "SPRINT-01", "linear", "abc123")
        temp_storage.create_sync_mapping("prd", "prd-1", "linear", "def456")
        mappings = temp_storage.list_sync_mappings()
        assert len(mappings) == 2

    def test_list_sync_mappings_by_type(self, temp_storage):
        """Test filtering sync mappings by type."""
        temp_storage.create_sync_mapping("sprint", "SPRINT-01", "linear", "abc123")
        temp_storage.create_sync_mapping("prd", "prd-1", "linear", "def456")
        mappings = temp_storage.list_sync_mappings(entity_type="sprint")
        assert len(mappings) == 1
        assert mappings[0]["entity_type"] == "sprint"

    def test_delete_sync_mapping(self, temp_storage):
        """Test deleting a sync mapping."""
        temp_storage.create_sync_mapping("sprint", "SPRINT-01", "linear", "abc123")
        result = temp_storage.delete_sync_mapping("sprint", "SPRINT-01", "linear")
        assert result is True
        assert temp_storage.get_sync_mapping("sprint", "SPRINT-01", "linear") is None


class TestExternalConfigOperations:
    """Test external configuration operations."""

    def test_set_external_config(self, temp_storage, tmp_path):
        """Test setting external configuration."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        config = temp_storage.set_external_config(
            project_id="test-project",
            system="linear",
            config={"api_key": "test-key", "team_id": "test-team"}
        )
        assert config["system"] == "linear"
        assert config["config"]["api_key"] == "test-key"

    def test_get_external_config(self, temp_storage, tmp_path):
        """Test retrieving external configuration."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.set_external_config("test-project", "linear", {"api_key": "test-key"})
        config = temp_storage.get_external_config("test-project", "linear")
        assert config is not None
        assert config["config"]["api_key"] == "test-key"

    def test_list_external_configs(self, temp_storage, tmp_path):
        """Test listing external configurations."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.set_external_config("test-project", "linear", {"api_key": "linear-key"})
        temp_storage.set_external_config("test-project", "jira", {"api_key": "jira-key"})
        configs = temp_storage.list_external_configs("test-project")
        assert len(configs) == 2

    def test_delete_external_config(self, temp_storage, tmp_path):
        """Test deleting external configuration."""
        temp_storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        temp_storage.set_external_config("test-project", "linear", {"api_key": "test-key"})
        result = temp_storage.delete_external_config("test-project", "linear")
        assert result is True
        assert temp_storage.get_external_config("test-project", "linear") is None


class TestTemplateOperations:
    """Test template operations."""

    def test_get_template_path_package(self):
        """Test finding template in package."""
        path = get_template_path("task.template.md")
        assert path is not None
        assert path.exists()
        assert path.name == "task.template.md"

    def test_get_template_path_not_found(self):
        """Test template not found returns None."""
        path = get_template_path("nonexistent.template.md")
        assert path is None


class TestMigrationV3ToV4:
    """Test v3->v4 migration: PRD phase timestamp backfill."""

    def test_migration_backfills_prd_timestamps(self, tmp_path):
        """Migrating a v3 database backfills ready_at, split_at, completed_at."""
        from a_sdlc.core.database import Database
        import sqlite3

        db_path = tmp_path / "test_migrate.db"
        project_path = str(tmp_path / "proj")

        # Create a v3 database manually
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(f"""
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
            INSERT INTO schema_version (version) VALUES (3);

            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                shortname TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX idx_projects_shortname ON projects(shortname);

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
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
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
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE SET NULL
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

            INSERT INTO projects (id, shortname, name, path, created_at, last_accessed)
            VALUES ('proj', 'PROJ', 'Project', '{project_path}', '2025-01-01T00:00:00', '2025-01-10T00:00:00');

            INSERT INTO prds (id, project_id, title, status, created_at, updated_at)
            VALUES ('P-READY', 'proj', 'Ready PRD', 'ready', '2025-01-01T00:00:00', '2025-01-05T00:00:00');

            INSERT INTO prds (id, project_id, title, status, created_at, updated_at)
            VALUES ('P-SPLIT', 'proj', 'Split PRD', 'split', '2025-01-01T00:00:00', '2025-01-08T00:00:00');

            INSERT INTO prds (id, project_id, title, status, created_at, updated_at)
            VALUES ('P-DONE', 'proj', 'Done PRD', 'completed', '2025-01-01T00:00:00', '2025-01-10T00:00:00');
        """)
        conn.commit()
        conn.close()

        # Initialize Database, which triggers migration
        db = Database(db_path=db_path)

        # Verify migration ran
        with db.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            assert cursor.fetchone()[0] == SCHEMA_VERSION

        # Verify backfill: ready PRD
        prd_ready = db.get_prd("P-READY")
        assert prd_ready["ready_at"] == "2025-01-05T00:00:00"
        assert prd_ready["split_at"] is None
        assert prd_ready["completed_at"] is None

        # Verify backfill: split PRD
        prd_split = db.get_prd("P-SPLIT")
        assert prd_split["ready_at"] == "2025-01-01T00:00:00"
        assert prd_split["split_at"] == "2025-01-08T00:00:00"
        assert prd_split["completed_at"] is None

        # Verify backfill: completed PRD
        prd_done = db.get_prd("P-DONE")
        assert prd_done["ready_at"] == "2025-01-01T00:00:00"
        assert prd_done["split_at"] == "2025-01-01T00:00:00"
        assert prd_done["completed_at"] == "2025-01-10T00:00:00"


class TestProjectShortname:
    """Test project shortname functionality."""

    def test_create_project_with_auto_shortname(self, temp_storage, tmp_path):
        """Test creating project with auto-generated shortname."""
        project = temp_storage.create_project(
            project_id="my-project",
            name="My Awesome Project",
            path=str(tmp_path / "my-project")
        )
        assert project["shortname"] is not None
        assert len(project["shortname"]) == 4
        assert project["shortname"].isupper()
        assert project["shortname"].isalpha()

    def test_create_project_with_explicit_shortname(self, temp_storage, tmp_path):
        """Test creating project with explicit shortname."""
        project = temp_storage.create_project(
            project_id="my-project",
            name="My Project",
            path=str(tmp_path / "my-project"),
            shortname="MYPR"
        )
        assert project["shortname"] == "MYPR"

    def test_shortname_uniqueness(self, temp_storage, tmp_path):
        """Test that shortnames must be unique."""
        temp_storage.create_project(
            project_id="project-1",
            name="Project 1",
            path=str(tmp_path / "p1"),
            shortname="PROJ"
        )
        # Second project with same shortname should fail
        with pytest.raises(ValueError, match="already in use"):
            temp_storage.create_project(
                project_id="project-2",
                name="Project 2",
                path=str(tmp_path / "p2"),
                shortname="PROJ"
            )

    def test_shortname_validation_length(self, temp_storage, tmp_path):
        """Test that shortname must be exactly 4 characters."""
        test_path = str(tmp_path / "test")
        # Too short
        with pytest.raises(ValueError, match="exactly 4 characters"):
            temp_storage.create_project(
                project_id="test",
                name="Test",
                path=test_path,
                shortname="ABC"
            )
        # Too long
        with pytest.raises(ValueError, match="exactly 4 characters"):
            temp_storage.create_project(
                project_id="test",
                name="Test",
                path=test_path,
                shortname="ABCDE"
            )

    def test_shortname_validation_characters(self, temp_storage, tmp_path):
        """Test that shortname must be uppercase letters only."""
        test_path = str(tmp_path / "test")
        # Lowercase
        with pytest.raises(ValueError, match="uppercase letters"):
            temp_storage.create_project(
                project_id="test",
                name="Test",
                path=test_path,
                shortname="abcd"
            )
        # Numbers
        with pytest.raises(ValueError, match="uppercase letters"):
            temp_storage.create_project(
                project_id="test",
                name="Test",
                path=test_path,
                shortname="AB12"
            )
        # Special characters
        with pytest.raises(ValueError, match="uppercase letters"):
            temp_storage.create_project(
                project_id="test",
                name="Test",
                path=test_path,
                shortname="AB-C"
            )

    def test_task_id_uses_shortname(self, temp_storage, tmp_path):
        """Test that task IDs use shortname format."""
        temp_storage.create_project(
            project_id="test-project",
            name="Test Project",
            path=str(tmp_path / "test"),
            shortname="TEST"
        )
        task_id = temp_storage.get_next_task_id("test-project")
        assert task_id == "TEST-T00001"

    def test_sprint_id_uses_shortname(self, temp_storage, tmp_path):
        """Test that sprint IDs use shortname format."""
        temp_storage.create_project(
            project_id="test-project",
            name="Test Project",
            path=str(tmp_path / "test"),
            shortname="TEST"
        )
        sprint_id = temp_storage.get_next_sprint_id("test-project")
        assert sprint_id == "TEST-S0001"

    def test_prd_id_uses_shortname(self, temp_storage, tmp_path):
        """Test that PRD IDs use shortname format."""
        temp_storage.create_project(
            project_id="test-project",
            name="Test Project",
            path=str(tmp_path / "test"),
            shortname="TEST"
        )
        prd_id = temp_storage.get_next_prd_id("test-project")
        assert prd_id == "TEST-P0001"

    def test_get_project_by_shortname(self, temp_storage, tmp_path):
        """Test retrieving project by shortname."""
        temp_storage.create_project(
            project_id="test-project",
            name="Test Project",
            path=str(tmp_path / "test"),
            shortname="TEST"
        )
        project = temp_storage.get_project_by_shortname("TEST")
        assert project is not None
        assert project["id"] == "test-project"
        assert project["shortname"] == "TEST"

    def test_relocate_project(self, temp_storage, tmp_path):
        """Test updating project path (relocate)."""
        old_path = str(tmp_path / "old-path")
        new_path = str(tmp_path / "new-path")
        temp_storage.create_project(
            project_id="test-project",
            name="Test Project",
            path=old_path,
            shortname="TEST"
        )
        updated = temp_storage.update_project_path("test-project", new_path)
        assert updated is not None
        assert updated["path"] == new_path

        # Verify the change persisted
        project = temp_storage.get_project("test-project")
        assert project["path"] == new_path

    def test_shortname_auto_generation_consonants(self, temp_storage, tmp_path):
        """Test that auto-generated shortname prefers consonants."""
        project = temp_storage.create_project(
            project_id="frontend",
            name="Frontend Application",
            path=str(tmp_path / "frontend")
        )
        # "Frontend Application" -> consonants "FRNTNDPPLCTN" -> "FRNT"
        # The exact result depends on the algorithm, but it should be valid
        assert len(project["shortname"]) == 4
        assert project["shortname"].isupper()

    def test_multiple_projects_unique_shortnames(self, temp_storage, tmp_path):
        """Test that multiple projects get unique auto-generated shortnames."""
        projects = []
        for i in range(5):
            project = temp_storage.create_project(
                project_id=f"project-{i}",
                name="Project",  # Same name to test uniqueness
                path=str(tmp_path / f"p{i}")
            )
            projects.append(project)

        shortnames = [p["shortname"] for p in projects]
        # All shortnames should be unique
        assert len(shortnames) == len(set(shortnames))


class TestMigrationBackupAndRollback:
    """Test pre-migration backup creation and rollback on failure."""

    def _create_v5_database(self, db_path: Path, project_path: str = "") -> None:
        """Helper: create a v5 database with sample data for migration tests."""
        if not project_path:
            project_path = str(db_path.parent / "proj")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(f"""
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
            INSERT INTO schema_version (version) VALUES (5);

            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                shortname TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX idx_projects_shortname ON projects(shortname);

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

            INSERT INTO projects (id, shortname, name, path, created_at, last_accessed)
            VALUES ('proj', 'PROJ', 'Project', '{project_path}', '2025-01-01T00:00:00', '2025-01-10T00:00:00');

            INSERT INTO prds (id, project_id, title, status, created_at, updated_at)
            VALUES ('P-001', 'proj', 'Test PRD', 'draft', '2025-01-01T00:00:00', '2025-01-05T00:00:00');
        """)
        conn.commit()
        conn.close()

    def test_backup_created_before_migration(self, tmp_path):
        """Test that a backup file is created with correct name before migration runs."""
        db_path = tmp_path / "data.db"
        self._create_v5_database(db_path)

        # Initialize Database, which triggers migration from v5 to v7
        Database(db_path=db_path)

        backup_path = db_path.with_suffix(".db.bak.v5")
        assert backup_path.exists(), "Backup file should be created before migration"

    def test_backup_naming_convention(self, tmp_path):
        """Test backup naming follows data.db.bak.v{version} convention."""
        db_path = tmp_path / "data.db"
        self._create_v5_database(db_path)

        Database(db_path=db_path)

        expected_name = "data.db.bak.v5"
        backup_path = db_path.parent / expected_name
        assert backup_path.exists(), f"Backup should be named {expected_name}"

    def test_successful_migration_preserves_backup(self, tmp_path):
        """Test that backup is preserved after successful migration (safety net)."""
        db_path = tmp_path / "data.db"
        self._create_v5_database(db_path)

        Database(db_path=db_path)

        backup_path = db_path.with_suffix(".db.bak.v5")
        assert backup_path.exists(), "Backup should be preserved after successful migration"

        # Verify the migrated database has the correct version
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT version FROM schema_version")
        assert cursor.fetchone()[0] == SCHEMA_VERSION
        conn.close()

    def test_failed_migration_restores_from_backup(self, tmp_path):
        """Test that a failed migration restores the database from backup."""
        db_path = tmp_path / "data.db"
        self._create_v5_database(db_path)

        # Record original file size for comparison
        original_size = db_path.stat().st_size

        # Make _migrate_v5_to_v6 fail to simulate a migration error
        with patch.object(
            Database, "_migrate_v5_to_v6", side_effect=Exception("Simulated migration failure")
        ):
            with pytest.raises(RuntimeError, match="Migration from v5 failed"):
                Database(db_path=db_path)

        # Verify database was restored from backup (should still be v5)
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT version FROM schema_version")
        version = cursor.fetchone()[0]
        conn.close()
        assert version == 5, "Database should be restored to original v5 after failed migration"

    def test_failed_migration_error_includes_backup_path(self, tmp_path):
        """Test that RuntimeError message includes the backup path."""
        db_path = tmp_path / "data.db"
        self._create_v5_database(db_path)

        backup_path = db_path.with_suffix(".db.bak.v5")

        with patch.object(
            Database, "_migrate_v5_to_v6", side_effect=Exception("column already exists")
        ):
            with pytest.raises(RuntimeError, match=str(backup_path)):
                Database(db_path=db_path)

    def test_failed_migration_error_includes_original_error(self, tmp_path):
        """Test that RuntimeError includes the original exception message."""
        db_path = tmp_path / "data.db"
        self._create_v5_database(db_path)

        with patch.object(
            Database, "_migrate_v5_to_v6", side_effect=Exception("duplicate column name")
        ):
            with pytest.raises(RuntimeError, match="duplicate column name"):
                Database(db_path=db_path)

    def test_no_backup_when_version_matches(self, tmp_path):
        """Test that no backup is created when schema version already matches."""
        db_path = tmp_path / "data.db"

        # Create a database at the current schema version (no migration needed)
        Database(db_path=db_path)

        # No backup should exist since no migration was needed
        backup_path = db_path.with_suffix(f".db.bak.v{SCHEMA_VERSION}")
        assert not backup_path.exists(), "No backup should be created when version matches"

    def test_backup_preserves_original_data(self, tmp_path):
        """Test that the backup contains the original data before migration."""
        db_path = tmp_path / "data.db"
        self._create_v5_database(db_path)

        Database(db_path=db_path)

        # Read backup and verify it has original v5 schema
        backup_path = db_path.with_suffix(".db.bak.v5")
        conn = sqlite3.connect(backup_path)
        cursor = conn.execute("SELECT version FROM schema_version")
        assert cursor.fetchone()[0] == 5, "Backup should contain original v5 schema"

        # Verify original project data is in backup
        cursor = conn.execute("SELECT id, shortname FROM projects WHERE id = 'proj'")
        row = cursor.fetchone()
        assert row is not None
        assert row[1] == "PROJ"
        conn.close()


class TestHybridStorageDesign:
    """Test HybridStorage design document operations."""

    @pytest.fixture
    def hybrid_storage(self, tmp_path):
        """Create a HybridStorage instance for testing."""
        from a_sdlc.storage import HybridStorage

        storage = HybridStorage(base_path=tmp_path)
        # Create project and PRD for testing
        storage.create_project("test-project", "Test Project", str(tmp_path / "test"))
        storage.create_prd(
            prd_id="TEST-P0001",
            project_id="test-project",
            title="Test PRD",
        )
        yield storage

    def test_create_design_writes_file_and_db(self, hybrid_storage):
        """Test that create_design writes empty file and DB record."""
        design = hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
        )
        assert design is not None
        assert design["prd_id"] == "TEST-P0001"
        assert "file_path" in design

    def test_get_design_by_prd_with_content(self, hybrid_storage):
        """Test that get_design_by_prd returns content from file."""
        design = hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
        )
        # Write content directly to file (file-first pattern)
        file_path = Path(design["file_path"])
        file_path.write_text("# Architecture Design", encoding="utf-8")

        fetched = hybrid_storage.get_design_by_prd("TEST-P0001")
        assert fetched is not None
        assert fetched["content"] == "# Architecture Design"

    def test_get_design_by_prd_not_found(self, hybrid_storage):
        """Test get_design_by_prd returns None for nonexistent."""
        design = hybrid_storage.get_design_by_prd("NONEXISTENT")
        assert design is None

    def test_list_designs_metadata_only(self, hybrid_storage):
        """Test that list_designs returns metadata without content."""
        hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
        )
        designs = hybrid_storage.list_designs("test-project")
        assert len(designs) == 1
        assert designs[0]["prd_id"] == "TEST-P0001"
        # list_designs returns metadata only, no content key expected
        assert "content" not in designs[0]

    def test_delete_design_removes_both(self, hybrid_storage):
        """Test that delete_design removes file and DB record."""
        hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
        )
        result = hybrid_storage.delete_design("TEST-P0001")
        assert result is True
        assert hybrid_storage.get_design_by_prd("TEST-P0001") is None

    def test_delete_design_not_found(self, hybrid_storage):
        """Test delete_design returns False for nonexistent."""
        result = hybrid_storage.delete_design("NONEXISTENT")
        assert result is False

    def test_create_and_verify_file_exists(self, hybrid_storage):
        """Test that creating a design writes an empty file to disk."""
        design = hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
        )
        file_path = Path(design["file_path"])
        assert file_path.exists()

    def test_delete_design_removes_file(self, hybrid_storage):
        """Test that deleting a design removes the content file from disk."""
        design = hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
        )
        file_path = Path(design["file_path"])
        assert file_path.exists()

        hybrid_storage.delete_design("TEST-P0001")
        assert not file_path.exists()
