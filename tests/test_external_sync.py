"""Tests for Phase 4: External Sync functionality."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from a_sdlc.cli import main


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield db_path


class TestDatabaseMigration:
    """Test database schema migrations."""

    def test_schema_version_2_creates_external_config(self, temp_db):
        """Test that v2 migration creates external_config table."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)

        # Check external_config table exists
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='external_config'"
            )
            assert cursor.fetchone() is not None

    def test_schema_creates_sync_mappings_table(self, temp_db):
        """Test that schema creates sync_mappings table."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)

        # Check sync_mappings table exists
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sync_mappings'"
            )
            assert cursor.fetchone() is not None

    def test_schema_version_3_prds_have_sprint_id(self, temp_db):
        """Test that v3 schema adds sprint_id to PRDs table."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)

        # Check prds table has sprint_id column
        with db.connection() as conn:
            cursor = conn.execute("PRAGMA table_info(prds)")
            columns = [row[1] for row in cursor.fetchall()]
            assert "sprint_id" in columns

    def test_schema_version_3_tasks_no_sprint_id(self, temp_db):
        """Test that v3 schema removes sprint_id from tasks table."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)

        # Check tasks table does NOT have sprint_id column
        with db.connection() as conn:
            cursor = conn.execute("PRAGMA table_info(tasks)")
            columns = [row[1] for row in cursor.fetchall()]
            assert "sprint_id" not in columns


class TestPRDSprintRelationship:
    """Test PRD-Sprint relationship (v3 hierarchy)."""

    def test_create_prd_with_sprint_id(self, temp_db):
        """Test creating a PRD with sprint assignment."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create a sprint
        sprint_id = db.get_next_sprint_id(project_id)
        db.create_sprint(sprint_id, project_id, "Test Sprint")

        # Create PRD with sprint_id (returns dict)
        prd = db.create_prd(
            prd_id="feature-auth",
            project_id=project_id,
            title="Authentication Feature",
            content="# Auth PRD",
            sprint_id=sprint_id,
        )

        # Verify PRD has sprint_id
        assert prd is not None
        assert prd["sprint_id"] == sprint_id
        assert prd["id"] == "feature-auth"

    def test_list_prds_by_sprint(self, temp_db):
        """Test listing PRDs filtered by sprint."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create two sprints
        sprint1_id = db.get_next_sprint_id(project_id)
        db.create_sprint(sprint1_id, project_id, "Sprint 1")
        sprint2_id = db.get_next_sprint_id(project_id)
        db.create_sprint(sprint2_id, project_id, "Sprint 2")

        # Create PRDs in different sprints (use keyword args)
        db.create_prd(prd_id="prd-1", project_id=project_id, title="PRD 1", content="content", sprint_id=sprint1_id)
        db.create_prd(prd_id="prd-2", project_id=project_id, title="PRD 2", content="content", sprint_id=sprint1_id)
        db.create_prd(prd_id="prd-3", project_id=project_id, title="PRD 3", content="content", sprint_id=sprint2_id)
        db.create_prd(prd_id="prd-backlog", project_id=project_id, title="Backlog PRD", content="content")  # No sprint

        # List PRDs in sprint 1
        sprint1_prds = db.list_prds(project_id, sprint_id=sprint1_id)
        assert len(sprint1_prds) == 2

        # List PRDs in sprint 2
        sprint2_prds = db.list_prds(project_id, sprint_id=sprint2_id)
        assert len(sprint2_prds) == 1

        # List backlog PRDs (empty string for sprint_id)
        backlog_prds = db.list_prds(project_id, sprint_id="")
        assert len(backlog_prds) == 1
        assert backlog_prds[0]["id"] == "prd-backlog"

    def test_get_sprint_prds(self, temp_db):
        """Test getting all PRDs assigned to a sprint."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create sprint
        sprint_id = db.get_next_sprint_id(project_id)
        db.create_sprint(sprint_id, project_id, "Test Sprint")

        # Create PRDs
        db.create_prd(prd_id="prd-1", project_id=project_id, title="PRD 1", content="content", sprint_id=sprint_id)
        db.create_prd(prd_id="prd-2", project_id=project_id, title="PRD 2", content="content", sprint_id=sprint_id)

        # Get sprint PRDs
        prds = db.get_sprint_prds(sprint_id)
        assert len(prds) == 2
        prd_ids = [p["id"] for p in prds]
        assert "prd-1" in prd_ids
        assert "prd-2" in prd_ids

    def test_assign_prd_to_sprint(self, temp_db):
        """Test assigning a backlog PRD to a sprint."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create sprint and backlog PRD
        sprint_id = db.get_next_sprint_id(project_id)
        db.create_sprint(sprint_id, project_id, "Test Sprint")
        db.create_prd(prd_id="prd-backlog", project_id=project_id, title="Backlog PRD", content="content")

        # Verify PRD has no sprint
        prd = db.get_prd("prd-backlog")
        assert prd["sprint_id"] is None

        # Assign to sprint
        db.assign_prd_to_sprint("prd-backlog", sprint_id)

        # Verify PRD now has sprint
        prd = db.get_prd("prd-backlog")
        assert prd["sprint_id"] == sprint_id

    def test_remove_prd_from_sprint(self, temp_db):
        """Test removing a PRD from sprint (move to backlog)."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create sprint and PRD with sprint
        sprint_id = db.get_next_sprint_id(project_id)
        db.create_sprint(sprint_id, project_id, "Test Sprint")
        db.create_prd(prd_id="prd-1", project_id=project_id, title="PRD 1", content="content", sprint_id=sprint_id)

        # Remove from sprint
        db.assign_prd_to_sprint("prd-1", None)

        # Verify PRD has no sprint
        prd = db.get_prd("prd-1")
        assert prd["sprint_id"] is None

    def test_get_sprint_tasks_via_prd(self, temp_db):
        """Test getting tasks derived from sprint's PRDs."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create sprint and PRD
        sprint_id = db.get_next_sprint_id(project_id)
        db.create_sprint(sprint_id, project_id, "Test Sprint")
        db.create_prd(prd_id="prd-1", project_id=project_id, title="PRD 1", content="content", sprint_id=sprint_id)

        # Create tasks under the PRD
        db.create_task(task_id="TASK-001", project_id=project_id, title="Task 1", prd_id="prd-1")
        db.create_task(task_id="TASK-002", project_id=project_id, title="Task 2", prd_id="prd-1")

        # Create task without PRD (should not be in sprint)
        db.create_task(task_id="TASK-003", project_id=project_id, title="Orphan Task")

        # Get sprint tasks (derived via PRD)
        tasks = db.list_tasks_by_sprint(project_id, sprint_id)
        assert len(tasks) == 2

    def test_task_no_direct_sprint_id(self, temp_db):
        """Test that tasks cannot be created with direct sprint_id."""
        from a_sdlc.server.database import Database
        import inspect

        db = Database(temp_db)

        # Verify create_task doesn't accept sprint_id parameter
        sig = inspect.signature(db.create_task)
        params = list(sig.parameters.keys())
        assert "sprint_id" not in params


class TestExternalConfigMethods:
    """Test database methods for external config."""

    def test_set_and_get_external_config(self, temp_db):
        """Test setting and getting external config."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)

        # Create a project first
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Set config
        config = {"api_key": "test-key", "team_id": "ENG"}
        result = db.set_external_config(project_id, "linear", config)

        assert result["system"] == "linear"
        assert result["config"]["api_key"] == "test-key"

        # Get config
        retrieved = db.get_external_config(project_id, "linear")
        assert retrieved is not None
        assert retrieved["config"]["api_key"] == "test-key"

    def test_get_nonexistent_config_returns_none(self, temp_db):
        """Test getting non-existent config returns None."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        result = db.get_external_config(project_id, "linear")
        assert result is None

    def test_delete_external_config(self, temp_db):
        """Test deleting external config."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Set then delete
        db.set_external_config(project_id, "linear", {"api_key": "test"})
        result = db.delete_external_config(project_id, "linear")
        assert result is True

        # Verify deleted
        retrieved = db.get_external_config(project_id, "linear")
        assert retrieved is None

    def test_list_external_configs(self, temp_db):
        """Test listing all external configs for a project."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Set multiple configs
        db.set_external_config(project_id, "linear", {"api_key": "linear-key"})
        db.set_external_config(project_id, "jira", {"api_key": "jira-key"})

        # List all
        configs = db.list_external_configs(project_id)
        assert len(configs) == 2
        systems = [c["system"] for c in configs]
        assert "linear" in systems
        assert "jira" in systems

    def test_update_external_config(self, temp_db):
        """Test updating existing external config."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Set initial config
        db.set_external_config(project_id, "linear", {"api_key": "old-key"})

        # Update config
        db.set_external_config(project_id, "linear", {"api_key": "new-key"})

        # Verify updated
        retrieved = db.get_external_config(project_id, "linear")
        assert retrieved["config"]["api_key"] == "new-key"


class TestSyncMappingMethods:
    """Test database methods for sync mappings."""

    def test_create_and_update_sprint_with_external(self, temp_db):
        """Test creating sprint and updating with external fields."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)

        # Create a project
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create sprint
        sprint_id = db.get_next_sprint_id(project_id)
        db.create_sprint(sprint_id, project_id, "Test Sprint")

        # Update with external_id and external_url
        db.update_sprint(
            sprint_id,
            external_id="ENG-Q1",
            external_url="https://linear.app/team/ENG/cycle/25",
        )

        # Create sync mapping for external_system tracking
        db.create_sync_mapping(
            entity_type="sprint",
            local_id=sprint_id,
            external_system="linear",
            external_id="ENG-Q1",
        )

        # Verify sprint has external fields
        sprint = db.get_sprint(sprint_id)
        assert sprint["external_id"] == "ENG-Q1"

        # Verify sync mapping
        mapping = db.get_sync_mapping("sprint", sprint_id, "linear")
        assert mapping is not None
        assert mapping["external_id"] == "ENG-Q1"

    def test_list_sync_mappings(self, temp_db):
        """Test listing sync mappings."""
        from a_sdlc.server.database import Database

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create a sync mapping
        db.create_sync_mapping(
            entity_type="sprint",
            local_id="SPRINT-001",
            external_system="linear",
            external_id="ENG-Q1",
        )

        # List mappings
        mappings = db.list_sync_mappings()
        assert len(mappings) == 1
        assert mappings[0]["local_id"] == "SPRINT-001"
        assert mappings[0]["external_system"] == "linear"


class TestCLICommands:
    """Test CLI commands for external integrations."""

    def test_integrations_command_no_project(self, runner: CliRunner):
        """Test integrations command without active project."""
        result = runner.invoke(main, ["integrations"])
        # Should handle gracefully
        assert result.exit_code in (0, 1)

    def test_connect_linear_prompts_for_input(self, runner: CliRunner):
        """Test connect linear prompts for API key."""
        result = runner.invoke(main, ["connect", "linear"], input="\n")
        # Exit code 1 because user aborted
        assert result.exit_code == 1
        assert "API Key" in result.output or "Aborted" in result.output

    def test_connect_jira_prompts_for_input(self, runner: CliRunner):
        """Test connect jira prompts for URL."""
        result = runner.invoke(main, ["connect", "jira"], input="\n")
        assert result.exit_code == 1

    def test_disconnect_requires_system(self, runner: CliRunner):
        """Test disconnect requires system argument."""
        result = runner.invoke(main, ["disconnect"])
        # Should fail without system arg
        assert result.exit_code != 0


class TestSyncService:
    """Test the ExternalSyncService class."""

    def test_linear_client_initialization(self):
        """Test LinearClient can be initialized."""
        from a_sdlc.server.sync import LinearClient

        client = LinearClient("test-api-key", "test-team-id")
        assert client.api_key == "test-api-key"
        assert client.team_id == "test-team-id"

    def test_jira_client_initialization(self):
        """Test JiraClient can be initialized."""
        from a_sdlc.server.sync import JiraClient

        client = JiraClient(
            base_url="https://test.atlassian.net",
            email="test@example.com",
            api_token="test-token",
            project_key="TEST",
        )
        assert client.base_url == "https://test.atlassian.net"
        assert client.project_key == "TEST"

    def test_sync_service_initialization(self, temp_db):
        """Test ExternalSyncService can be initialized."""
        from a_sdlc.server.database import Database
        from a_sdlc.server.sync import ExternalSyncService

        db = Database(temp_db)
        service = ExternalSyncService(db)
        assert service.db is db

    def test_linear_status_mapping_to_local(self):
        """Test Linear status mapping to local status."""
        from a_sdlc.server.sync import LinearClient

        # Test various Linear statuses
        assert LinearClient.LINEAR_TO_STATUS["Todo"] == "pending"
        assert LinearClient.LINEAR_TO_STATUS["In Progress"] == "in_progress"
        assert LinearClient.LINEAR_TO_STATUS["Done"] == "completed"
        assert LinearClient.LINEAR_TO_STATUS["Blocked"] == "blocked"

    def test_linear_status_mapping_from_local(self):
        """Test local status mapping to Linear status."""
        from a_sdlc.server.sync import LinearClient

        assert LinearClient.STATUS_TO_LINEAR["pending"] == "Backlog"
        assert LinearClient.STATUS_TO_LINEAR["in_progress"] == "In Progress"
        assert LinearClient.STATUS_TO_LINEAR["completed"] == "Done"

    def test_linear_priority_mapping(self):
        """Test priority mapping for Linear."""
        from a_sdlc.server.sync import LinearClient

        assert LinearClient.PRIORITY_TO_LINEAR["critical"] == 1
        assert LinearClient.PRIORITY_TO_LINEAR["high"] == 2
        assert LinearClient.PRIORITY_TO_LINEAR["medium"] == 3
        assert LinearClient.PRIORITY_TO_LINEAR["low"] == 4


class TestLinearClientMocked:
    """Test LinearClient with mocked HTTP responses."""

    @patch("httpx.Client.post")
    def test_list_cycles(self, mock_post):
        """Test listing Linear cycles."""
        from a_sdlc.server.sync import LinearClient

        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "team": {
                    "cycles": {
                        "nodes": [
                            {
                                "id": "cycle-1",
                                "name": "Sprint 1",
                                "number": 1,
                                "startsAt": "2025-01-01",
                                "endsAt": "2025-01-14",
                            }
                        ]
                    }
                }
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client = LinearClient("test-key", "test-team")
        cycles = client.list_cycles()

        assert len(cycles) == 1
        assert cycles[0]["name"] == "Sprint 1"

    @patch("httpx.Client.post")
    def test_get_cycle(self, mock_post):
        """Test getting a specific Linear cycle."""
        from a_sdlc.server.sync import LinearClient

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "cycle": {
                    "id": "cycle-1",
                    "name": "Sprint 1",
                    "issues": {"nodes": []},
                }
            }
        }
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        client = LinearClient("test-key", "test-team")
        cycle = client.get_cycle("cycle-1")

        assert cycle is not None
        assert cycle["name"] == "Sprint 1"


class TestJiraClientMocked:
    """Test JiraClient with mocked HTTP responses."""

    @patch("httpx.Client.get")
    def test_list_sprints(self, mock_get):
        """Test listing Jira sprints."""
        from a_sdlc.server.sync import JiraClient

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "values": [
                {
                    "id": 1,
                    "name": "Sprint 1",
                    "state": "active",
                    "startDate": "2025-01-01",
                    "endDate": "2025-01-14",
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = JiraClient(
            base_url="https://test.atlassian.net",
            email="test@example.com",
            api_token="test-token",
            project_key="TEST",
        )
        sprints = client.list_sprints("10")

        assert len(sprints) == 1
        assert sprints[0]["name"] == "Sprint 1"


class TestExternalSyncServiceMocked:
    """Test ExternalSyncService with mocked dependencies."""

    def test_link_sprint_via_sync_mapping(self, temp_db):
        """Test that link_sprint creates proper sync mappings."""
        from a_sdlc.server.database import Database
        from a_sdlc.server.sync import ExternalSyncService

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create a sprint
        sprint_id = db.get_next_sprint_id(project_id)
        db.create_sprint(sprint_id, project_id, "Test Sprint")

        # Set up external config
        db.set_external_config(
            project_id, "linear", {"api_key": "test-key", "team_id": "test-team"}
        )

        service = ExternalSyncService(db)

        # Mock the Linear client
        with patch.object(service, "_get_linear_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.get_cycle.return_value = {
                "id": "ENG-Q1",
                "name": "Q1 Sprint",
            }
            mock_get_client.return_value = mock_client

            result = service.link_sprint(project_id, sprint_id, "linear", "ENG-Q1")

            # Result should be a sync mapping dict
            assert "external_id" in result
            assert result["external_id"] == "ENG-Q1"
            assert result["external_system"] == "linear"

            # Verify sync mapping was created in database
            mapping = db.get_sync_mapping("sprint", sprint_id, "linear")
            assert mapping is not None

    def test_unlink_sprint(self, temp_db):
        """Test unlinking a sprint from external system."""
        from a_sdlc.server.database import Database
        from a_sdlc.server.sync import ExternalSyncService

        db = Database(temp_db)
        project_id = "test-project"
        db.create_project(project_id, "Test Project", "/tmp/test")

        # Create a sprint and set up external link
        sprint_id = db.get_next_sprint_id(project_id)
        db.create_sprint(sprint_id, project_id, "Test Sprint")
        db.update_sprint(sprint_id, external_id="ENG-Q1")
        db.create_sync_mapping(
            entity_type="sprint",
            local_id=sprint_id,
            external_system="linear",
            external_id="ENG-Q1",
        )

        service = ExternalSyncService(db)
        result = service.unlink_sprint(sprint_id)

        assert result is True

        # Verify unlinked
        sprint = db.get_sprint(sprint_id)
        assert sprint["external_id"] is None


# Integration test (requires actual API keys - skip by default)
@pytest.mark.skip(reason="Requires actual Linear API key")
class TestLinearIntegration:
    """Integration tests for Linear API."""

    def test_list_real_cycles(self):
        """Test listing real Linear cycles."""
        import os

        from a_sdlc.server.sync import LinearClient

        api_key = os.environ.get("LINEAR_API_KEY")
        team_id = os.environ.get("LINEAR_TEAM_ID")

        if not api_key or not team_id:
            pytest.skip("LINEAR_API_KEY and LINEAR_TEAM_ID not set")

        client = LinearClient(api_key, team_id)
        cycles = client.list_cycles(status="active")

        # Just verify it doesn't crash
        assert isinstance(cycles, list)
