"""Tests for Phase 4: External Sync functionality.

These tests have been updated to work with file-based storage instead of SQLite.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_storage():
    """Create a temporary file storage for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestFileStorageMigration:
    """Test hybrid storage setup."""

    def test_storage_creates_directories(self, temp_storage):
        """Test that storage creates required directories."""
        from a_sdlc.storage import HybridStorage

        storage = HybridStorage(base_path=temp_storage)

        # Hybrid architecture creates base_path and templates
        assert storage.base_path.exists()
        assert storage.templates_dir.exists()


class TestPRDSprintRelationship:
    """Test PRD-Sprint relationship."""

    def test_create_prd_with_sprint_id(self, temp_storage):
        """Test creating a PRD with sprint assignment."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)
        project_id = "test-project"
        storage.create_project(project_id, "Test Project", "/tmp/test")

        # Create a sprint
        sprint_id = storage.get_next_sprint_id(project_id)
        storage.create_sprint(sprint_id, project_id, "Test Sprint")

        # Create PRD with sprint_id
        prd = storage.create_prd(
            prd_id="feature-auth",
            project_id=project_id,
            title="Authentication Feature",
            status="draft",
            sprint_id=sprint_id,
        )

        assert prd["sprint_id"] == sprint_id

    def test_list_prds_by_sprint(self, temp_storage):
        """Test listing PRDs filtered by sprint."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)
        project_id = "test-project"
        storage.create_project(project_id, "Test Project", "/tmp/test")

        # Create sprint
        sprint_id = storage.get_next_sprint_id(project_id)
        storage.create_sprint(sprint_id, project_id, "Test Sprint")

        # Create PRDs - one with sprint, one without
        storage.create_prd("prd-in-sprint", project_id, "In Sprint", sprint_id=sprint_id)
        storage.create_prd("prd-backlog", project_id, "Backlog")

        # List by sprint
        sprint_prds = storage.list_prds(project_id, sprint_id=sprint_id)
        assert len(sprint_prds) == 1
        assert sprint_prds[0]["id"] == "prd-in-sprint"

        # List backlog (empty sprint_id)
        backlog_prds = storage.list_prds(project_id, sprint_id="")
        assert len(backlog_prds) == 1
        assert backlog_prds[0]["id"] == "prd-backlog"

    def test_assign_prd_to_sprint(self, temp_storage):
        """Test assigning a PRD to a sprint."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)
        project_id = "test-project"
        storage.create_project(project_id, "Test Project", "/tmp/test")

        # Create sprint and PRD
        sprint_id = storage.get_next_sprint_id(project_id)
        storage.create_sprint(sprint_id, project_id, "Test Sprint")
        storage.create_prd("prd-1", project_id, "Test PRD")

        # Assign to sprint
        updated = storage.assign_prd_to_sprint("prd-1", sprint_id)
        assert updated["sprint_id"] == sprint_id

    def test_get_sprint_prds(self, temp_storage):
        """Test getting all PRDs for a sprint."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)
        project_id = "test-project"
        storage.create_project(project_id, "Test Project", "/tmp/test")

        sprint_id = storage.get_next_sprint_id(project_id)
        storage.create_sprint(sprint_id, project_id, "Test Sprint")

        storage.create_prd("prd-1", project_id, "PRD 1", sprint_id=sprint_id)
        storage.create_prd("prd-2", project_id, "PRD 2", sprint_id=sprint_id)
        storage.create_prd("prd-3", project_id, "PRD 3")  # No sprint

        prds = storage.get_sprint_prds(sprint_id)
        assert len(prds) == 2


class TestTaskPRDRelationship:
    """Test Task-PRD relationship (derived sprint via PRD)."""

    def test_list_tasks_by_sprint(self, temp_storage):
        """Test listing tasks filtered by sprint (via PRD)."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)
        project_id = "test-project"
        storage.create_project(project_id, "Test Project", "/tmp/test")

        # Create sprint and PRD
        sprint_id = storage.get_next_sprint_id(project_id)
        storage.create_sprint(sprint_id, project_id, "Test Sprint")
        storage.create_prd("prd-auth", project_id, "Auth", sprint_id=sprint_id)

        # Create task linked to PRD
        storage.create_task("TASK-001", project_id, "Auth Task", prd_id="prd-auth")

        # List tasks by sprint
        tasks = storage.list_tasks_by_sprint(project_id, sprint_id)
        assert len(tasks) == 1
        assert tasks[0]["id"] == "TASK-001"


class TestExternalConfig:
    """Test external system configuration."""

    def test_set_and_get_config(self, temp_storage):
        """Test setting and getting external config."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)
        project_id = "test-project"
        storage.create_project(project_id, "Test Project", "/tmp/test")

        # Set config
        config_data = {"api_key": "test-key", "team_id": "test-team"}
        storage.set_external_config(project_id, "linear", config_data)

        # Get config
        config = storage.get_external_config(project_id, "linear")
        assert config is not None
        assert config["config"]["api_key"] == "test-key"

    def test_list_configs(self, temp_storage):
        """Test listing all external configs."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)
        project_id = "test-project"
        storage.create_project(project_id, "Test Project", "/tmp/test")

        storage.set_external_config(project_id, "linear", {"key": "linear"})
        storage.set_external_config(project_id, "jira", {"key": "jira"})

        configs = storage.list_external_configs(project_id)
        assert len(configs) == 2

    def test_delete_config(self, temp_storage):
        """Test deleting external config."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)
        project_id = "test-project"
        storage.create_project(project_id, "Test Project", "/tmp/test")

        storage.set_external_config(project_id, "linear", {"key": "test"})
        result = storage.delete_external_config(project_id, "linear")
        assert result is True
        assert storage.get_external_config(project_id, "linear") is None


class TestSyncMappings:
    """Test sync mapping operations."""

    def test_create_and_get_mapping(self, temp_storage):
        """Test creating and getting a sync mapping."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)

        mapping = storage.create_sync_mapping(
            entity_type="sprint",
            local_id="SPRINT-01",
            external_system="linear",
            external_id="cycle-abc123",
        )

        assert mapping["entity_type"] == "sprint"
        assert mapping["sync_status"] == "synced"

        # Get mapping
        result = storage.get_sync_mapping("sprint", "SPRINT-01", "linear")
        assert result is not None
        assert result["external_id"] == "cycle-abc123"

    def test_get_mapping_by_external_id(self, temp_storage):
        """Test getting mapping by external ID."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)

        storage.create_sync_mapping("sprint", "SPRINT-01", "linear", "cycle-abc123")

        result = storage.get_sync_mapping_by_external("sprint", "linear", "cycle-abc123")
        assert result is not None
        assert result["local_id"] == "SPRINT-01"

    def test_update_mapping(self, temp_storage):
        """Test updating a sync mapping."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)

        storage.create_sync_mapping("sprint", "SPRINT-01", "linear", "cycle-abc123")

        updated = storage.update_sync_mapping(
            "sprint", "SPRINT-01", "linear", sync_status="out_of_sync"
        )
        assert updated["sync_status"] == "out_of_sync"

    def test_delete_mapping(self, temp_storage):
        """Test deleting a sync mapping."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)

        storage.create_sync_mapping("sprint", "SPRINT-01", "linear", "cycle-abc123")

        result = storage.delete_sync_mapping("sprint", "SPRINT-01", "linear")
        assert result is True
        assert storage.get_sync_mapping("sprint", "SPRINT-01", "linear") is None

    def test_list_mappings(self, temp_storage):
        """Test listing sync mappings."""
        from a_sdlc.storage import FileStorage

        storage = FileStorage(base_path=temp_storage)

        storage.create_sync_mapping("sprint", "SPRINT-01", "linear", "cycle-1")
        storage.create_sync_mapping("sprint", "SPRINT-02", "jira", "sprint-2")
        storage.create_sync_mapping("prd", "prd-1", "linear", "issue-1")

        # List all
        all_mappings = storage.list_sync_mappings()
        assert len(all_mappings) == 3

        # Filter by type
        sprint_mappings = storage.list_sync_mappings(entity_type="sprint")
        assert len(sprint_mappings) == 2

        # Filter by system
        linear_mappings = storage.list_sync_mappings(external_system="linear")
        assert len(linear_mappings) == 2


class TestExternalSyncService:
    """Test the ExternalSyncService class."""

    def test_sync_service_initialization(self, temp_storage):
        """Test sync service can be initialized."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database
        from a_sdlc.server.sync import ExternalSyncService

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")
        service = ExternalSyncService(db, content_mgr)
        assert service.db is db
        assert service.content_mgr is content_mgr

    def test_link_sprint(self, temp_storage):
        """Test linking a sprint to an external system."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database
        from a_sdlc.server.sync import ExternalSyncService

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")
        db.create_sprint("SPRINT-01", project_id, "Sprint 1")
        db.set_external_config(project_id, "linear", {"api_key": "test", "team_id": "test"})

        service = ExternalSyncService(db, content_mgr)
        mapping = service.link_sprint(project_id, "SPRINT-01", "linear", "cycle-abc")

        assert mapping["external_id"] == "cycle-abc"

        # Sprint should have external_id
        sprint = db.get_sprint("SPRINT-01")
        assert sprint["external_id"] == "cycle-abc"

    def test_unlink_sprint(self, temp_storage):
        """Test unlinking a sprint from external system."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database
        from a_sdlc.server.sync import ExternalSyncService

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")
        db.create_sprint("SPRINT-01", project_id, "Sprint 1")
        db.set_external_config(project_id, "linear", {"api_key": "test", "team_id": "test"})

        service = ExternalSyncService(db, content_mgr)
        service.link_sprint(project_id, "SPRINT-01", "linear", "cycle-abc")

        result = service.unlink_sprint("SPRINT-01")
        assert result is True

        # Mapping should be gone
        mapping = db.get_sync_mapping("sprint", "SPRINT-01", "linear")
        assert mapping is None

        # Sprint should have external_id cleared
        sprint = db.get_sprint("SPRINT-01")
        assert sprint["external_id"] is None


class TestDuplicateSprintDetection:
    """Test duplicate sprint detection during import."""

    def test_check_existing_sprint_mapping_finds_duplicate(self, temp_storage):
        """Test that _check_existing_sprint_mapping detects existing mappings."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database
        from a_sdlc.server.sync import ExternalSyncService

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")
        db.create_sprint("SPRINT-01", project_id, "Sprint 1")
        db.set_external_config(project_id, "linear", {"api_key": "test", "team_id": "test"})

        # Create a sync mapping
        db.create_sync_mapping("sprint", "SPRINT-01", "linear", "cycle-abc123")

        service = ExternalSyncService(db, content_mgr)
        result = service._check_existing_sprint_mapping(project_id, "linear", "cycle-abc123")

        assert result is not None
        assert result["existing_sprint"]["id"] == "SPRINT-01"
        assert result["mapping"]["external_id"] == "cycle-abc123"
        assert result["external_system"] == "linear"

    def test_check_existing_sprint_mapping_returns_none_when_no_mapping(self, temp_storage):
        """Test that _check_existing_sprint_mapping returns None when no mapping exists."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database
        from a_sdlc.server.sync import ExternalSyncService

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        service = ExternalSyncService(db, content_mgr)
        result = service._check_existing_sprint_mapping(project_id, "linear", "cycle-new")

        assert result is None

    def test_orphaned_mapping_is_cleaned_up(self, temp_storage):
        """Test that orphaned mappings (sprint deleted but mapping remains) are cleaned up."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database
        from a_sdlc.server.sync import ExternalSyncService

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create a mapping without a corresponding sprint (orphaned)
        db.create_sync_mapping("sprint", "SPRINT-DELETED", "linear", "cycle-orphan")

        service = ExternalSyncService(db, content_mgr)
        result = service._check_existing_sprint_mapping(project_id, "linear", "cycle-orphan")

        # Should return None (orphaned mapping cleaned up)
        assert result is None

        # Mapping should have been deleted
        mapping = db.get_sync_mapping("sprint", "SPRINT-DELETED", "linear")
        assert mapping is None

    def test_linear_import_returns_already_exists(self, temp_storage):
        """Test that import_linear_cycle returns already_exists status for duplicates."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database
        from a_sdlc.server.sync import ExternalSyncService

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")
        db.create_sprint("SPRINT-01", project_id, "Existing Sprint")
        db.set_external_config(project_id, "linear", {"api_key": "test", "team_id": "test"})

        # Create a sync mapping for the cycle
        db.create_sync_mapping("sprint", "SPRINT-01", "linear", "cycle-abc123")

        service = ExternalSyncService(db, content_mgr)
        result = service.import_linear_cycle(project_id, "cycle-abc123")

        assert result["status"] == "already_exists"
        assert result["existing_sprint"]["id"] == "SPRINT-01"
        assert result["external_id"] == "cycle-abc123"
        assert result["external_system"] == "linear"

    def test_jira_import_returns_already_exists(self, temp_storage):
        """Test that import_jira_sprint returns already_exists status for duplicates."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database
        from a_sdlc.server.sync import ExternalSyncService

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")
        db.create_sprint("SPRINT-02", project_id, "Existing Jira Sprint")
        db.set_external_config(project_id, "jira", {
            "base_url": "https://test.atlassian.net",
            "email": "test@test.com",
            "api_token": "test-token",
            "project_key": "TEST",
        })

        # Create a sync mapping for the Jira sprint
        db.create_sync_mapping("sprint", "SPRINT-02", "jira", "456")

        service = ExternalSyncService(db, content_mgr)
        result = service.import_jira_sprint(project_id, "456")

        assert result["status"] == "already_exists"
        assert result["existing_sprint"]["id"] == "SPRINT-02"
        assert result["external_id"] == "456"
        assert result["external_system"] == "jira"

    def test_different_external_id_allows_new_import(self, temp_storage):
        """Test that a different external_id allows a new import."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database
        from a_sdlc.server.sync import ExternalSyncService

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")
        db.create_sprint("SPRINT-01", project_id, "Existing Sprint")
        db.set_external_config(project_id, "linear", {"api_key": "test", "team_id": "test"})

        # Create a sync mapping for a different cycle
        db.create_sync_mapping("sprint", "SPRINT-01", "linear", "cycle-old")

        service = ExternalSyncService(db, content_mgr)

        # Checking for a different external_id should return None (no duplicate)
        result = service._check_existing_sprint_mapping(project_id, "linear", "cycle-new")
        assert result is None


class TestDeleteSyncMappingCleanup:
    """Test sync mapping cleanup on entity deletion."""

    def test_delete_prd_cleans_up_sync_mappings(self, temp_storage):
        """Test that deleting a PRD removes its sync mappings."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create a PRD
        prd_id = db.get_next_prd_id(project_id)
        content_mgr.write_prd(project_id, prd_id, "Test PRD", "Test content")
        db.create_prd(
            prd_id=prd_id,
            project_id=project_id,
            title="Test PRD",
            file_path=str(content_mgr.get_prd_path(project_id, prd_id)),
        )

        # Create sync mappings for Linear and Jira
        db.create_sync_mapping("prd", prd_id, "linear", "linear-issue-123")
        db.create_sync_mapping("prd", prd_id, "jira", "JIRA-456")

        # Verify mappings exist
        assert db.get_sync_mapping("prd", prd_id, "linear") is not None
        assert db.get_sync_mapping("prd", prd_id, "jira") is not None

        # Delete PRD using the server function
        from a_sdlc.server import delete_prd

        with patch("a_sdlc.server.get_db", return_value=db), \
             patch("a_sdlc.server.get_content_manager", return_value=content_mgr):
            result = delete_prd(prd_id)

        assert result["status"] == "deleted"

        # Verify sync mappings are cleaned up
        assert db.get_sync_mapping("prd", prd_id, "linear") is None
        assert db.get_sync_mapping("prd", prd_id, "jira") is None

    def test_delete_task_cleans_up_sync_mappings(self, temp_storage):
        """Test that deleting a task removes its sync mappings."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create a task
        task_id = db.get_next_task_id(project_id)
        content_mgr.write_task(project_id, task_id, "Test Task", "Test description")
        db.create_task(
            task_id=task_id,
            project_id=project_id,
            title="Test Task",
            file_path=str(content_mgr.get_task_path(project_id, task_id)),
        )

        # Create sync mappings for Linear and Jira
        db.create_sync_mapping("task", task_id, "linear", "linear-task-789")
        db.create_sync_mapping("task", task_id, "jira", "JIRA-101")

        # Verify mappings exist
        assert db.get_sync_mapping("task", task_id, "linear") is not None
        assert db.get_sync_mapping("task", task_id, "jira") is not None

        # Delete task using the server function
        from a_sdlc.server import delete_task

        with patch("a_sdlc.server.get_db", return_value=db), \
             patch("a_sdlc.server.get_content_manager", return_value=content_mgr):
            result = delete_task(task_id)

        assert result["status"] == "deleted"

        # Verify sync mappings are cleaned up
        assert db.get_sync_mapping("task", task_id, "linear") is None
        assert db.get_sync_mapping("task", task_id, "jira") is None

    def test_delete_sprint_cleans_up_sync_mappings(self, temp_storage):
        """Test that deleting a sprint removes its sync mappings (existing behavior)."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create a sprint
        sprint_id = db.get_next_sprint_id(project_id)
        db.create_sprint(sprint_id, project_id, "Test Sprint", "Test goal")

        # Create sync mappings for Linear and Jira
        db.create_sync_mapping("sprint", sprint_id, "linear", "cycle-abc")
        db.create_sync_mapping("sprint", sprint_id, "jira", "sprint-123")

        # Verify mappings exist
        assert db.get_sync_mapping("sprint", sprint_id, "linear") is not None
        assert db.get_sync_mapping("sprint", sprint_id, "jira") is not None

        # Delete sprint using the server function
        from a_sdlc.server import delete_sprint

        with patch("a_sdlc.server.get_db", return_value=db), \
             patch("a_sdlc.server.get_content_manager", return_value=content_mgr):
            result = delete_sprint(sprint_id)

        assert result["status"] == "deleted"

        # Verify sync mappings are cleaned up
        assert db.get_sync_mapping("sprint", sprint_id, "linear") is None
        assert db.get_sync_mapping("sprint", sprint_id, "jira") is None

    def test_delete_prd_without_sync_mappings_succeeds(self, temp_storage):
        """Test that deleting a PRD without sync mappings still works."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create a PRD without sync mappings
        prd_id = db.get_next_prd_id(project_id)
        content_mgr.write_prd(project_id, prd_id, "Test PRD", "Test content")
        db.create_prd(
            prd_id=prd_id,
            project_id=project_id,
            title="Test PRD",
            file_path=str(content_mgr.get_prd_path(project_id, prd_id)),
        )

        # Delete PRD (should not error even without mappings)
        from a_sdlc.server import delete_prd

        with patch("a_sdlc.server.get_db", return_value=db), \
             patch("a_sdlc.server.get_content_manager", return_value=content_mgr):
            result = delete_prd(prd_id)

        assert result["status"] == "deleted"

    def test_delete_task_without_sync_mappings_succeeds(self, temp_storage):
        """Test that deleting a task without sync mappings still works."""
        from a_sdlc.core.content import ContentManager
        from a_sdlc.core.database import Database

        db = Database(db_path=temp_storage / "data.db")
        content_mgr = ContentManager(base_path=temp_storage / "content")

        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create a task without sync mappings
        task_id = db.get_next_task_id(project_id)
        content_mgr.write_task(project_id, task_id, "Test Task", "Test description")
        db.create_task(
            task_id=task_id,
            project_id=project_id,
            title="Test Task",
            file_path=str(content_mgr.get_task_path(project_id, task_id)),
        )

        # Delete task (should not error even without mappings)
        from a_sdlc.server import delete_task

        with patch("a_sdlc.server.get_db", return_value=db), \
             patch("a_sdlc.server.get_content_manager", return_value=content_mgr):
            result = delete_task(task_id)

        assert result["status"] == "deleted"
