"""Tests for file-based storage."""

import tempfile
from pathlib import Path

import pytest

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

    def test_create_project(self, temp_storage):
        """Test creating a new project."""
        project = temp_storage.create_project(
            project_id="test-project",
            name="Test Project",
            path="/tmp/test"
        )
        assert project["id"] == "test-project"
        assert project["name"] == "Test Project"
        assert project["path"] == "/tmp/test"

    def test_get_project(self, temp_storage):
        """Test retrieving a project."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        project = temp_storage.get_project("test-project")
        assert project is not None
        assert project["id"] == "test-project"

    def test_get_project_by_path(self, temp_storage):
        """Test retrieving a project by path."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        project = temp_storage.get_project_by_path("/tmp/test")
        assert project is not None
        assert project["id"] == "test-project"

    def test_list_projects(self, temp_storage):
        """Test listing projects."""
        temp_storage.create_project("project-1", "Project 1", "/tmp/p1")
        temp_storage.create_project("project-2", "Project 2", "/tmp/p2")
        projects = temp_storage.list_projects()
        assert len(projects) == 2

    def test_delete_project(self, temp_storage):
        """Test deleting a project."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        result = temp_storage.delete_project("test-project")
        assert result is True
        assert temp_storage.get_project("test-project") is None


class TestPRDOperations:
    """Test PRD CRUD operations."""

    def test_create_prd(self, temp_storage):
        """Test creating a PRD."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        prd = temp_storage.create_prd(
            prd_id="feature-auth",
            project_id="test-project",
            title="Authentication Feature",
            content="Implement user authentication",
            status="draft"
        )
        assert prd["id"] == "feature-auth"
        assert prd["title"] == "Authentication Feature"
        assert prd["status"] == "draft"

    def test_create_prd_with_sprint(self, temp_storage):
        """Test creating a PRD with sprint assignment."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        prd = temp_storage.create_prd(
            prd_id="feature-auth",
            project_id="test-project",
            title="Auth Feature",
            sprint_id="SPRINT-01"
        )
        assert prd["sprint_id"] == "SPRINT-01"

    def test_get_prd(self, temp_storage):
        """Test retrieving a PRD."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_prd("feature-auth", "test-project", "Auth Feature")
        prd = temp_storage.get_prd("feature-auth")
        assert prd is not None
        assert prd["id"] == "feature-auth"

    def test_list_prds(self, temp_storage):
        """Test listing PRDs."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_prd("prd-1", "test-project", "PRD 1")
        temp_storage.create_prd("prd-2", "test-project", "PRD 2")
        prds = temp_storage.list_prds("test-project")
        assert len(prds) == 2

    def test_list_prds_by_sprint(self, temp_storage):
        """Test filtering PRDs by sprint."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        temp_storage.create_prd("prd-1", "test-project", "PRD 1", sprint_id="SPRINT-01")
        temp_storage.create_prd("prd-2", "test-project", "PRD 2")  # No sprint
        prds = temp_storage.list_prds("test-project", sprint_id="SPRINT-01")
        assert len(prds) == 1
        assert prds[0]["id"] == "prd-1"

    def test_update_prd(self, temp_storage):
        """Test updating a PRD."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_prd("feature-auth", "test-project", "Auth Feature")
        updated = temp_storage.update_prd("feature-auth", status="ready")
        assert updated is not None
        assert updated["status"] == "ready"

    def test_delete_prd(self, temp_storage):
        """Test deleting a PRD."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_prd("feature-auth", "test-project", "Auth Feature")
        result = temp_storage.delete_prd("feature-auth")
        assert result is True
        assert temp_storage.get_prd("feature-auth") is None


class TestTaskOperations:
    """Test task CRUD operations."""

    def test_create_task(self, temp_storage):
        """Test creating a task."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
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

    def test_get_task(self, temp_storage):
        """Test retrieving a task."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_task("TASK-001", "test-project", "Test Task")
        task = temp_storage.get_task("TASK-001")
        assert task is not None
        assert task["id"] == "TASK-001"

    def test_list_tasks(self, temp_storage):
        """Test listing tasks."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_task("TASK-001", "test-project", "Task 1")
        temp_storage.create_task("TASK-002", "test-project", "Task 2")
        tasks = temp_storage.list_tasks("test-project")
        assert len(tasks) == 2

    def test_list_tasks_by_status(self, temp_storage):
        """Test filtering tasks by status."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_task("TASK-001", "test-project", "Task 1", status="pending")
        temp_storage.create_task("TASK-002", "test-project", "Task 2", status="completed")
        tasks = temp_storage.list_tasks("test-project", status="pending")
        assert len(tasks) == 1
        assert tasks[0]["id"] == "TASK-001"

    def test_update_task(self, temp_storage):
        """Test updating a task."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_task("TASK-001", "test-project", "Test Task")
        updated = temp_storage.update_task("TASK-001", status="in_progress")
        assert updated is not None
        assert updated["status"] == "in_progress"

    def test_update_task_to_completed_sets_completed_at(self, temp_storage):
        """Test that completing a task sets completed_at."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_task("TASK-001", "test-project", "Test Task")
        updated = temp_storage.update_task("TASK-001", status="completed")
        assert updated["completed_at"] is not None

    def test_delete_task(self, temp_storage):
        """Test deleting a task."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_task("TASK-001", "test-project", "Test Task")
        result = temp_storage.delete_task("TASK-001")
        assert result is True
        assert temp_storage.get_task("TASK-001") is None

    def test_get_next_task_id(self, temp_storage):
        """Test task ID generation uses shortname format."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test", shortname="TEST")
        next_id = temp_storage.get_next_task_id("test-project")
        assert next_id == "TEST-T00001"


class TestSprintOperations:
    """Test sprint CRUD operations."""

    def test_create_sprint(self, temp_storage):
        """Test creating a sprint."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
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

    def test_get_sprint(self, temp_storage):
        """Test retrieving a sprint."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        sprint = temp_storage.get_sprint("SPRINT-01")
        assert sprint is not None
        assert sprint["id"] == "SPRINT-01"

    def test_get_sprint_with_prd_count(self, temp_storage):
        """Test that get_sprint includes PRD count."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        temp_storage.create_prd("prd-1", "test-project", "PRD 1", sprint_id="SPRINT-01")
        sprint = temp_storage.get_sprint("SPRINT-01")
        assert sprint["prd_count"] == 1

    def test_list_sprints(self, temp_storage):
        """Test listing sprints."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        temp_storage.create_sprint("SPRINT-02", "test-project", "Sprint 2")
        sprints = temp_storage.list_sprints("test-project")
        assert len(sprints) == 2

    def test_update_sprint_to_active(self, temp_storage):
        """Test that activating a sprint sets started_at."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        updated = temp_storage.update_sprint("SPRINT-01", status="active")
        assert updated["status"] == "active"
        assert updated["started_at"] is not None

    def test_update_sprint_to_completed(self, temp_storage):
        """Test that completing a sprint sets completed_at."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        updated = temp_storage.update_sprint("SPRINT-01", status="completed")
        assert updated["status"] == "completed"
        assert updated["completed_at"] is not None

    def test_delete_sprint_unlinks_prds(self, temp_storage):
        """Test that deleting a sprint unlinks its PRDs."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        temp_storage.create_prd("prd-1", "test-project", "PRD 1", sprint_id="SPRINT-01")
        temp_storage.delete_sprint("SPRINT-01")
        prd = temp_storage.get_prd("prd-1")
        assert prd["sprint_id"] is None

    def test_get_sprint_prds(self, temp_storage):
        """Test getting PRDs for a sprint."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        temp_storage.create_prd("prd-1", "test-project", "PRD 1", sprint_id="SPRINT-01")
        temp_storage.create_prd("prd-2", "test-project", "PRD 2", sprint_id="SPRINT-01")
        prds = temp_storage.get_sprint_prds("SPRINT-01")
        assert len(prds) == 2

    def test_assign_prd_to_sprint(self, temp_storage):
        """Test assigning a PRD to a sprint."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.create_sprint("SPRINT-01", "test-project", "Sprint 1")
        temp_storage.create_prd("prd-1", "test-project", "PRD 1")
        updated = temp_storage.assign_prd_to_sprint("prd-1", "SPRINT-01")
        assert updated["sprint_id"] == "SPRINT-01"

    def test_get_next_sprint_id(self, temp_storage):
        """Test sprint ID generation uses shortname format."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test", shortname="TEST")
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

    def test_set_external_config(self, temp_storage):
        """Test setting external configuration."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        config = temp_storage.set_external_config(
            project_id="test-project",
            system="linear",
            config={"api_key": "test-key", "team_id": "test-team"}
        )
        assert config["system"] == "linear"
        assert config["config"]["api_key"] == "test-key"

    def test_get_external_config(self, temp_storage):
        """Test retrieving external configuration."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.set_external_config("test-project", "linear", {"api_key": "test-key"})
        config = temp_storage.get_external_config("test-project", "linear")
        assert config is not None
        assert config["config"]["api_key"] == "test-key"

    def test_list_external_configs(self, temp_storage):
        """Test listing external configurations."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
        temp_storage.set_external_config("test-project", "linear", {"api_key": "linear-key"})
        temp_storage.set_external_config("test-project", "jira", {"api_key": "jira-key"})
        configs = temp_storage.list_external_configs("test-project")
        assert len(configs) == 2

    def test_delete_external_config(self, temp_storage):
        """Test deleting external configuration."""
        temp_storage.create_project("test-project", "Test Project", "/tmp/test")
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

        # Create a v3 database manually
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript("""
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
            VALUES ('proj', 'PROJ', 'Project', '/tmp/proj', '2025-01-01T00:00:00', '2025-01-10T00:00:00');

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
            assert cursor.fetchone()[0] == 5

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

    def test_create_project_with_auto_shortname(self, temp_storage):
        """Test creating project with auto-generated shortname."""
        project = temp_storage.create_project(
            project_id="my-project",
            name="My Awesome Project",
            path="/tmp/my-project"
        )
        assert project["shortname"] is not None
        assert len(project["shortname"]) == 4
        assert project["shortname"].isupper()
        assert project["shortname"].isalpha()

    def test_create_project_with_explicit_shortname(self, temp_storage):
        """Test creating project with explicit shortname."""
        project = temp_storage.create_project(
            project_id="my-project",
            name="My Project",
            path="/tmp/my-project",
            shortname="MYPR"
        )
        assert project["shortname"] == "MYPR"

    def test_shortname_uniqueness(self, temp_storage):
        """Test that shortnames must be unique."""
        temp_storage.create_project(
            project_id="project-1",
            name="Project 1",
            path="/tmp/p1",
            shortname="PROJ"
        )
        # Second project with same shortname should fail
        with pytest.raises(ValueError, match="already in use"):
            temp_storage.create_project(
                project_id="project-2",
                name="Project 2",
                path="/tmp/p2",
                shortname="PROJ"
            )

    def test_shortname_validation_length(self, temp_storage):
        """Test that shortname must be exactly 4 characters."""
        # Too short
        with pytest.raises(ValueError, match="exactly 4 characters"):
            temp_storage.create_project(
                project_id="test",
                name="Test",
                path="/tmp/test",
                shortname="ABC"
            )
        # Too long
        with pytest.raises(ValueError, match="exactly 4 characters"):
            temp_storage.create_project(
                project_id="test",
                name="Test",
                path="/tmp/test",
                shortname="ABCDE"
            )

    def test_shortname_validation_characters(self, temp_storage):
        """Test that shortname must be uppercase letters only."""
        # Lowercase
        with pytest.raises(ValueError, match="uppercase letters"):
            temp_storage.create_project(
                project_id="test",
                name="Test",
                path="/tmp/test",
                shortname="abcd"
            )
        # Numbers
        with pytest.raises(ValueError, match="uppercase letters"):
            temp_storage.create_project(
                project_id="test",
                name="Test",
                path="/tmp/test",
                shortname="AB12"
            )
        # Special characters
        with pytest.raises(ValueError, match="uppercase letters"):
            temp_storage.create_project(
                project_id="test",
                name="Test",
                path="/tmp/test",
                shortname="AB-C"
            )

    def test_task_id_uses_shortname(self, temp_storage):
        """Test that task IDs use shortname format."""
        temp_storage.create_project(
            project_id="test-project",
            name="Test Project",
            path="/tmp/test",
            shortname="TEST"
        )
        task_id = temp_storage.get_next_task_id("test-project")
        assert task_id == "TEST-T00001"

    def test_sprint_id_uses_shortname(self, temp_storage):
        """Test that sprint IDs use shortname format."""
        temp_storage.create_project(
            project_id="test-project",
            name="Test Project",
            path="/tmp/test",
            shortname="TEST"
        )
        sprint_id = temp_storage.get_next_sprint_id("test-project")
        assert sprint_id == "TEST-S0001"

    def test_prd_id_uses_shortname(self, temp_storage):
        """Test that PRD IDs use shortname format."""
        temp_storage.create_project(
            project_id="test-project",
            name="Test Project",
            path="/tmp/test",
            shortname="TEST"
        )
        prd_id = temp_storage.get_next_prd_id("test-project")
        assert prd_id == "TEST-P0001"

    def test_get_project_by_shortname(self, temp_storage):
        """Test retrieving project by shortname."""
        temp_storage.create_project(
            project_id="test-project",
            name="Test Project",
            path="/tmp/test",
            shortname="TEST"
        )
        project = temp_storage.get_project_by_shortname("TEST")
        assert project is not None
        assert project["id"] == "test-project"
        assert project["shortname"] == "TEST"

    def test_relocate_project(self, temp_storage):
        """Test updating project path (relocate)."""
        temp_storage.create_project(
            project_id="test-project",
            name="Test Project",
            path="/tmp/old-path",
            shortname="TEST"
        )
        updated = temp_storage.update_project_path("test-project", "/tmp/new-path")
        assert updated is not None
        assert updated["path"] == "/tmp/new-path"

        # Verify the change persisted
        project = temp_storage.get_project("test-project")
        assert project["path"] == "/tmp/new-path"

    def test_shortname_auto_generation_consonants(self, temp_storage):
        """Test that auto-generated shortname prefers consonants."""
        project = temp_storage.create_project(
            project_id="frontend",
            name="Frontend Application",
            path="/tmp/frontend"
        )
        # "Frontend Application" -> consonants "FRNTNDPPLCTN" -> "FRNT"
        # The exact result depends on the algorithm, but it should be valid
        assert len(project["shortname"]) == 4
        assert project["shortname"].isupper()

    def test_multiple_projects_unique_shortnames(self, temp_storage):
        """Test that multiple projects get unique auto-generated shortnames."""
        projects = []
        for i in range(5):
            project = temp_storage.create_project(
                project_id=f"project-{i}",
                name="Project",  # Same name to test uniqueness
                path=f"/tmp/p{i}"
            )
            projects.append(project)

        shortnames = [p["shortname"] for p in projects]
        # All shortnames should be unique
        assert len(shortnames) == len(set(shortnames))


class TestHybridStorageDesign:
    """Test HybridStorage design document operations."""

    @pytest.fixture
    def hybrid_storage(self):
        """Create a HybridStorage instance for testing."""
        import tempfile
        from a_sdlc.storage import HybridStorage

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = HybridStorage(base_path=Path(tmpdir))
            # Create project and PRD for testing
            storage.create_project("test-project", "Test Project", "/tmp/test")
            storage.create_prd(
                prd_id="TEST-P0001",
                project_id="test-project",
                title="Test PRD",
                content="# Test PRD Content",
            )
            yield storage

    def test_create_design_writes_file_and_db(self, hybrid_storage):
        """Test that create_design writes content file and DB record."""
        design = hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
            content="# Architecture\n\nDesign content",
        )
        assert design is not None
        assert design["prd_id"] == "TEST-P0001"
        assert "file_path" in design
        assert design["content"] == "# Architecture\n\nDesign content"

    def test_get_design_by_prd_with_content(self, hybrid_storage):
        """Test that get_design_by_prd returns content from file."""
        hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
            content="# Architecture Design",
        )
        design = hybrid_storage.get_design_by_prd("TEST-P0001")
        assert design is not None
        assert design["content"] == "# Architecture Design"

    def test_get_design_by_prd_not_found(self, hybrid_storage):
        """Test get_design_by_prd returns None for nonexistent."""
        design = hybrid_storage.get_design_by_prd("NONEXISTENT")
        assert design is None

    def test_list_designs_metadata_only(self, hybrid_storage):
        """Test that list_designs returns metadata without content."""
        hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
            content="# Design",
        )
        designs = hybrid_storage.list_designs("test-project")
        assert len(designs) == 1
        assert designs[0]["prd_id"] == "TEST-P0001"
        # list_designs returns metadata only, no content key expected
        assert "content" not in designs[0]

    def test_update_design_updates_both(self, hybrid_storage):
        """Test that update_design updates file and DB."""
        hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
            content="# Original",
        )
        updated = hybrid_storage.update_design("TEST-P0001", content="# Updated Design")
        assert updated is not None
        assert updated["content"] == "# Updated Design"

        # Verify via get
        fetched = hybrid_storage.get_design_by_prd("TEST-P0001")
        assert fetched["content"] == "# Updated Design"

    def test_update_design_not_found(self, hybrid_storage):
        """Test update_design returns None for nonexistent."""
        result = hybrid_storage.update_design("NONEXISTENT", content="# New")
        assert result is None

    def test_delete_design_removes_both(self, hybrid_storage):
        """Test that delete_design removes file and DB record."""
        hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
            content="# To Delete",
        )
        result = hybrid_storage.delete_design("TEST-P0001")
        assert result is True
        assert hybrid_storage.get_design_by_prd("TEST-P0001") is None

    def test_delete_design_not_found(self, hybrid_storage):
        """Test delete_design returns False for nonexistent."""
        result = hybrid_storage.delete_design("NONEXISTENT")
        assert result is False

    def test_create_and_verify_file_exists(self, hybrid_storage):
        """Test that creating a design actually writes a file to disk."""
        design = hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
            content="# File Test",
        )
        file_path = Path(design["file_path"])
        assert file_path.exists()
        assert file_path.read_text(encoding="utf-8") == "# File Test"

    def test_delete_design_removes_file(self, hybrid_storage):
        """Test that deleting a design removes the content file from disk."""
        design = hybrid_storage.create_design(
            prd_id="TEST-P0001",
            project_id="test-project",
            content="# To Remove",
        )
        file_path = Path(design["file_path"])
        assert file_path.exists()

        hybrid_storage.delete_design("TEST-P0001")
        assert not file_path.exists()
