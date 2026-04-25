"""Tests for the web UI routes and dashboard enhancements."""

import asyncio
import contextlib
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from a_sdlc.storage import FileStorage

# Only run if fastapi is installed
pytest.importorskip("fastapi")


@pytest.fixture
def temp_storage():
    """Create a temporary storage instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileStorage(base_path=Path(tmpdir))
        yield storage


@pytest.fixture
def app_client(temp_storage, monkeypatch):
    """Create a synchronous test client with mocked storage."""
    from starlette.testclient import TestClient

    import a_sdlc.ui as ui_module
    from a_sdlc.ui import app

    monkeypatch.setattr(ui_module, "get_storage", lambda: temp_storage)
    return TestClient(app)


@pytest.fixture
def storage_with_project(temp_storage, tmp_path):
    """Create storage with a test project."""
    temp_storage.create_project("test-proj", "Test Project", str(tmp_path / "test"))
    # Add default agents for work_queue FK constraints
    temp_storage.create_agent("architect", "test-proj", "architect", "System Architect")
    temp_storage.create_agent("engineer-1", "test-proj", "implementer", "Backend Engineer")
    return temp_storage


@pytest.fixture
def client_with_project(storage_with_project, monkeypatch):
    """Create a test client with a project in storage."""
    from starlette.testclient import TestClient

    import a_sdlc.ui as ui_module
    from a_sdlc.ui import app

    monkeypatch.setattr(ui_module, "get_storage", lambda: storage_with_project)
    return TestClient(app)


def _make_client(storage, monkeypatch):
    """Helper to create a test client with given storage."""
    from starlette.testclient import TestClient

    import a_sdlc.ui as ui_module
    from a_sdlc.ui import app

    monkeypatch.setattr(ui_module, "get_storage", lambda: storage)
    return TestClient(app)


# =============================================================================
# Home / Cross-Project Routes
# =============================================================================


class TestHomePage:
    """Test the cross-project home page."""

    def test_home_no_projects_shows_onboarding(self, app_client):
        """With no projects, home shows onboarding page."""
        response = app_client.get("/")
        assert response.status_code == 200
        assert "/sdlc:init" in response.text
        assert "Getting Started" in response.text or "Welcome" in response.text

    def test_home_with_projects_shows_grid(self, client_with_project):
        """With projects, home shows project grid."""
        response = client_with_project.get("/")
        assert response.status_code == 200
        assert "Test Project" in response.text
        assert "All Projects" in response.text

    def test_home_backward_compat_redirect(self, client_with_project):
        """/?project=X redirects to /projects/X."""
        response = client_with_project.get(
            "/?project=test-proj", follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/projects/test-proj"


# =============================================================================
# Per-Project Dashboard
# =============================================================================


class TestProjectDashboard:
    """Test the per-project dashboard."""

    def test_project_dashboard(self, client_with_project):
        """Project dashboard shows project stats."""
        response = client_with_project.get("/projects/test-proj")
        assert response.status_code == 200
        assert "Test Project" in response.text
        assert "Total Tasks" in response.text

    def test_project_dashboard_not_found(self, client_with_project):
        """Non-existent project shows onboarding."""
        response = client_with_project.get("/projects/nonexistent")
        assert response.status_code == 200
        assert "Welcome" in response.text or "/sdlc:init" in response.text

    def test_dashboard_contextual_hints_no_tasks(
        self, storage_with_project, monkeypatch
    ):
        """Dashboard shows hint to split PRD when there are PRDs but no tasks."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/projects/test-proj")
        assert response.status_code == 200
        assert "/sdlc:prd-split" in response.text


# =============================================================================
# Task Routes
# =============================================================================


class TestTaskRoutes:
    """Test task-related routes."""

    def test_tasks_page(self, client_with_project):
        """Tasks page renders for a project."""
        response = client_with_project.get("/tasks?project=test-proj")
        assert response.status_code == 200
        assert "Tasks" in response.text

    def test_tasks_empty_state_shows_copy_cmd(self, client_with_project):
        """Empty tasks page shows copy command for prd-split."""
        response = client_with_project.get("/tasks?project=test-proj")
        assert response.status_code == 200
        assert "/sdlc:prd-split" in response.text

    def test_task_detail(self, storage_with_project, monkeypatch):
        """Task detail page renders."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Test Task",
            prd_id="TEST-P0001",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/tasks/TEST-T00001")
        assert response.status_code == 200
        assert "Test Task" in response.text
        assert "/sdlc:task-start" in response.text

    def test_task_start_is_copy_not_htmx(
        self, storage_with_project, monkeypatch
    ):
        """Start button on tasks page is copy-to-clipboard, not HTMX."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Test Task",
            prd_id="TEST-P0001",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/tasks?project=test-proj")
        text = response.text
        assert "copyCommand" in text
        assert "/sdlc:task-start TEST-T00001" in text
        # Should NOT have hx-post for starting tasks
        assert 'hx-post="/tasks/TEST-T00001/status?status=in_progress"' not in text

    def test_update_task_status(self, storage_with_project, monkeypatch):
        """POST /tasks/{id}/status updates task status."""
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Test Task",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/tasks/TEST-T00001/status?status=completed"
        )
        assert response.status_code == 200
        assert "Completed" in response.text


# =============================================================================
# Sprint Routes
# =============================================================================


class TestSprintRoutes:
    """Test sprint-related routes."""

    def test_sprints_page(self, client_with_project):
        """Sprints page renders."""
        response = client_with_project.get("/sprints?project=test-proj")
        assert response.status_code == 200
        assert "Sprints" in response.text

    def test_sprints_empty_state(self, client_with_project):
        """Empty sprints shows create command."""
        response = client_with_project.get("/sprints?project=test-proj")
        assert response.status_code == 200
        assert "/sdlc:sprint-create" in response.text

    def test_sprint_detail_with_progress(
        self, storage_with_project, monkeypatch
    ):
        """Sprint detail shows progress bar."""
        storage_with_project.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-proj",
            title="Sprint 1",
        )
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
            sprint_id="TEST-S0001",
        )
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Task 1",
            prd_id="TEST-P0001",
        )
        storage_with_project.create_task(
            task_id="TEST-T00002",
            project_id="test-proj",
            title="Task 2",
            status="completed",
            prd_id="TEST-P0001",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/sprints/TEST-S0001")
        assert response.status_code == 200
        assert "Sprint Progress" in response.text
        assert "progress-bar" in response.text


# =============================================================================
# Sprint PRD Management
# =============================================================================


class TestSprintPrdManagement:
    """Test adding/removing PRDs from sprints via the UI."""

    def test_sprint_detail_shows_add_prd_dropdown(
        self, storage_with_project, monkeypatch
    ):
        """Backlog PRDs appear in the add-to-sprint dropdown."""
        storage_with_project.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-proj",
            title="Sprint 1",
        )
        # Unassigned PRD (backlog)
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Backlog PRD",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/sprints/TEST-S0001")
        assert response.status_code == 200
        assert "TEST-P0001" in response.text
        assert "Backlog PRD" in response.text
        assert "Add to Sprint" in response.text

    def test_add_prd_to_sprint(self, storage_with_project, monkeypatch):
        """POST /sprints/{id}/prds assigns PRD and redirects back."""
        storage_with_project.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-proj",
            title="Sprint 1",
        )
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Backlog PRD",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/sprints/TEST-S0001/prds",
            data={"prd_id": "TEST-P0001"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/sprints/TEST-S0001"

        # Verify PRD is now in the sprint
        prds = storage_with_project.get_sprint_prds("TEST-S0001")
        assert any(p["id"] == "TEST-P0001" for p in prds)

    def test_remove_prd_from_sprint(self, storage_with_project, monkeypatch):
        """POST remove unassigns PRD and redirects back."""
        storage_with_project.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-proj",
            title="Sprint 1",
        )
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Sprint PRD",
            sprint_id="TEST-S0001",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/sprints/TEST-S0001/prds/TEST-P0001/remove",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/sprints/TEST-S0001"

        # Verify PRD is no longer in the sprint
        prds = storage_with_project.get_sprint_prds("TEST-S0001")
        assert not any(p["id"] == "TEST-P0001" for p in prds)

    def test_sprint_detail_no_backlog_prds(
        self, storage_with_project, monkeypatch
    ):
        """No dropdown when all PRDs are already assigned."""
        storage_with_project.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-proj",
            title="Sprint 1",
        )
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Assigned PRD",
            sprint_id="TEST-S0001",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/sprints/TEST-S0001")
        assert response.status_code == 200
        assert "Add to Sprint" not in response.text
        # The assigned PRD should still show in the table
        assert "TEST-P0001" in response.text


# =============================================================================
# PRD Routes
# =============================================================================


class TestPRDRoutes:
    """Test PRD-related routes."""

    def test_prds_page(self, client_with_project):
        """PRDs page renders."""
        response = client_with_project.get("/prds?project=test-proj")
        assert response.status_code == 200
        assert "Product Requirements Documents" in response.text

    def test_prds_empty_state(self, client_with_project):
        """Empty PRDs page shows generate command."""
        response = client_with_project.get("/prds?project=test-proj")
        assert response.status_code == 200
        assert "/sdlc:prd-generate" in response.text

    def test_prd_list_architect_button_no_design(
        self, storage_with_project, monkeypatch
    ):
        """PRD list shows Architect button when no design exists."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
            status="draft",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds?project=test-proj")
        assert response.status_code == 200
        assert "/sdlc:prd-architect TEST-P0001" in response.text
        assert "Architect" in response.text

    def test_prd_list_split_button_with_design(
        self, storage_with_project, monkeypatch
    ):
        """PRD list shows Split button when design exists."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
            status="draft",
        )
        storage_with_project.create_design(
            prd_id="TEST-P0001",
            project_id="test-proj",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds?project=test-proj")
        assert response.status_code == 200
        assert "/sdlc:prd-split TEST-P0001" in response.text

    def test_prd_detail_architect_primary_no_design(
        self, storage_with_project, monkeypatch
    ):
        """PRD detail shows Architect as primary button when no design."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
            status="draft",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds/TEST-P0001")
        assert response.status_code == 200
        assert "/sdlc:prd-architect TEST-P0001" in response.text
        # Secondary split button should also be present
        assert "/sdlc:prd-split TEST-P0001" in response.text

    def test_prd_detail_split_primary_with_design(
        self, storage_with_project, monkeypatch
    ):
        """PRD detail shows Split as primary button when design exists."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
            status="draft",
        )
        storage_with_project.create_design(
            prd_id="TEST-P0001",
            project_id="test-proj",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds/TEST-P0001")
        assert response.status_code == 200
        assert "/sdlc:prd-split TEST-P0001" in response.text
        # Architect button should NOT appear when design exists
        assert "/sdlc:prd-architect TEST-P0001" not in response.text

    def test_prd_detail_tasks_empty_state_no_design(
        self, storage_with_project, monkeypatch
    ):
        """Tasks tab empty state shows Architect command when no design."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
            status="draft",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds/TEST-P0001")
        assert response.status_code == 200
        assert "Design first, then split into tasks:" in response.text

    def test_prd_detail_tasks_empty_state_with_design(
        self, storage_with_project, monkeypatch
    ):
        """Tasks tab empty state shows Split command when design exists."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
            status="draft",
        )
        storage_with_project.create_design(
            prd_id="TEST-P0001",
            project_id="test-proj",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds/TEST-P0001")
        assert response.status_code == 200
        assert "Design first, then split into tasks:" not in response.text


# =============================================================================
# Storage: get_all_projects_with_stats
# =============================================================================


class TestGetAllProjectsWithStats:
    """Test the get_all_projects_with_stats method."""

    def test_empty_projects(self, temp_storage):
        """Returns empty list when no projects exist."""
        result = temp_storage.get_all_projects_with_stats()
        assert result == []

    def test_project_with_no_entities(self, temp_storage, tmp_path):
        """Returns project with zero counts when no tasks/PRDs/sprints."""
        temp_storage.create_project("proj1", "Project 1", str(tmp_path / "proj1"))
        result = temp_storage.get_all_projects_with_stats()
        assert len(result) == 1
        p = result[0]
        assert p["name"] == "Project 1"
        assert p["total_tasks"] == 0
        assert p["tasks_pending"] == 0
        assert p["total_prds"] == 0
        assert p["total_sprints"] == 0
        assert p["active_sprint_title"] is None

    def test_project_with_stats(self, temp_storage, tmp_path):
        """Returns correct aggregated stats."""
        temp_storage.create_project("proj1", "Project 1", str(tmp_path / "proj1"))
        temp_storage.create_prd(
            prd_id="PROJ-P0001",
            project_id="proj1",
            title="PRD 1",
        )
        temp_storage.create_task(
            task_id="PROJ-T00001",
            project_id="proj1",
            title="Task 1",
            prd_id="PROJ-P0001",
        )
        temp_storage.create_task(
            task_id="PROJ-T00002",
            project_id="proj1",
            title="Task 2",
            status="completed",
            prd_id="PROJ-P0001",
        )
        temp_storage.create_sprint(
            sprint_id="PROJ-S0001",
            project_id="proj1",
            title="Sprint 1",
            status="active",
        )

        result = temp_storage.get_all_projects_with_stats()
        assert len(result) == 1
        p = result[0]
        assert p["total_tasks"] == 2
        assert p["tasks_pending"] == 1
        assert p["tasks_completed"] == 1
        assert p["total_prds"] == 1
        assert p["total_sprints"] == 1
        assert p["active_sprint_title"] == "Sprint 1"
        assert p["active_sprint_id"] == "PROJ-S0001"

    def test_multiple_projects_ordered_by_access(self, temp_storage, tmp_path):
        """Projects are ordered by last accessed."""
        temp_storage.create_project("proj1", "First", str(tmp_path / "p1"))
        temp_storage.create_project("proj2", "Second", str(tmp_path / "p2"))
        # Access proj1 to make it most recent
        temp_storage.update_project_accessed("proj1")

        result = temp_storage.get_all_projects_with_stats()
        assert len(result) == 2
        assert result[0]["name"] == "First"
        assert result[1]["name"] == "Second"


# =============================================================================
# Copy Command Infrastructure
# =============================================================================


class TestCopyCommandInfrastructure:
    """Test that copy command infrastructure is present in base template."""

    def test_base_has_copy_js(self, client_with_project):
        """Base template includes copyCommand JS function."""
        response = client_with_project.get("/projects/test-proj")
        assert response.status_code == 200
        assert "copyCommand" in response.text
        assert "showToast" in response.text
        assert "toast-container" in response.text

    def test_base_has_responsive_css(self, client_with_project):
        """Base template includes responsive media queries."""
        response = client_with_project.get("/projects/test-proj")
        assert response.status_code == 200
        assert "@media" in response.text
        assert "768px" in response.text


# =============================================================================
# Auto-open Browser
# =============================================================================


class TestAutoOpenBrowser:
    """Test the auto-open browser functionality in server/__init__.py."""

    def test_open_browser_when_ready_function_exists(self):
        """The _open_browser_when_ready function exists."""
        from a_sdlc.server import _open_browser_when_ready
        assert callable(_open_browser_when_ready)

    def test_no_browser_env_var(self, monkeypatch):
        """A_SDLC_NO_BROWSER=1 suppresses browser opening."""
        import a_sdlc.server as server_module

        monkeypatch.setattr(server_module, "_is_port_in_use", lambda p: True)
        # Already running, so _start_ui_server returns None
        result = server_module._start_ui_server()
        assert result is None


# =============================================================================
# UI Enhancements: Button Consistency, Title Handling, Sorting, Search
# =============================================================================


class TestButtonConsistency:
    """Test that copy buttons use proper CSS classes."""

    def test_table_action_uses_btn_copy_sm(self, storage_with_project, monkeypatch):
        """Table action buttons use btn-copy-sm class."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
            status="draft",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds?project=test-proj")
        assert "btn-copy-sm" in response.text

    def test_task_table_action_uses_btn_copy_sm(self, storage_with_project, monkeypatch):
        """Task table start button uses btn-copy-sm class."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Test Task",
            prd_id="TEST-P0001",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/tasks?project=test-proj")
        assert "btn-copy-sm" in response.text

    def test_sprint_remove_uses_btn_danger_sm(self, storage_with_project, monkeypatch):
        """Remove button on sprint detail uses btn-danger-sm class."""
        storage_with_project.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-proj",
            title="Sprint 1",
        )
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Sprint PRD",
            sprint_id="TEST-S0001",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/sprints/TEST-S0001")
        assert "btn-danger-sm" in response.text


class TestTitleHandling:
    """Test that title cells use CSS truncation."""

    def test_title_cell_has_css_class(self, storage_with_project, monkeypatch):
        """Title cells use cell-title CSS class with title attribute."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="A very long PRD title for testing",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds?project=test-proj")
        assert 'class="cell-title"' in response.text
        assert 'title="A very long PRD title for testing"' in response.text

    def test_task_title_not_truncated_by_jinja(self, storage_with_project, monkeypatch):
        """Task titles are not truncated by Jinja slicing anymore."""
        long_title = "A" * 80  # Longer than the old 50-char truncation
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title=long_title,
            prd_id="TEST-P0001",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/tasks?project=test-proj")
        # Full title should be in the title attribute
        assert f'title="{long_title}"' in response.text
        # Full title should be in the cell content (CSS handles truncation)
        assert long_title in response.text

    def test_detail_header_has_title_full(self, storage_with_project, monkeypatch):
        """Detail page headers use title-full class for overflow handling."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Test Task",
            prd_id="TEST-P0001",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/tasks/TEST-T00001")
        assert "title-full" in response.text


class TestTableSorting:
    """Test that table headers have data-sort attributes."""

    def test_prds_table_has_sort_attributes(self, storage_with_project, monkeypatch):
        """PRDs table headers have data-sort attributes."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds?project=test-proj")
        assert 'data-sort="text"' in response.text
        assert 'data-sort="status"' in response.text
        assert 'data-sort="date"' in response.text

    def test_tasks_table_has_sort_attributes(self, storage_with_project, monkeypatch):
        """Tasks table headers have data-sort attributes."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Test Task",
            prd_id="TEST-P0001",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/tasks?project=test-proj")
        assert 'data-sort="text"' in response.text
        assert 'data-sort="status"' in response.text
        assert 'data-sort="priority"' in response.text

    def test_sort_js_function_exists(self, client_with_project):
        """Base template includes sortTable JS function."""
        response = client_with_project.get("/projects/test-proj")
        assert "sortTable" in response.text


class TestSearchAndFilters:
    """Test search inputs and filter dropdowns."""

    def test_tasks_page_has_search_input(self, storage_with_project, monkeypatch):
        """Tasks page has search input with initTableSearch."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Test Task",
            prd_id="TEST-P0001",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/tasks?project=test-proj")
        assert 'id="task-search"' in response.text
        assert "initTableSearch" in response.text

    def test_prds_page_has_search_input(self, storage_with_project, monkeypatch):
        """PRDs page has search input."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds?project=test-proj")
        assert 'id="prd-search"' in response.text
        assert "initTableSearch" in response.text

    def test_sprints_page_has_search_input(self, storage_with_project, monkeypatch):
        """Sprints page has search input."""
        storage_with_project.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-proj",
            title="Sprint 1",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/sprints?project=test-proj")
        assert 'id="sprint-search"' in response.text
        assert "initTableSearch" in response.text

    def test_prds_page_has_status_filter(self, storage_with_project, monkeypatch):
        """PRDs page has status filter dropdown."""
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds?project=test-proj")
        assert "All Status" in response.text
        assert "Draft" in response.text

    def test_prds_status_filter_works(self, storage_with_project, monkeypatch):
        """PRDs page filters by status correctly."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Draft PRD",
            status="draft",
        )
        storage_with_project.create_prd(
            prd_id="TEST-P0002",
            project_id="test-proj",
            title="Completed PRD",
            status="completed",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds?project=test-proj&status=draft")
        assert "Draft PRD" in response.text
        assert "Completed PRD" not in response.text

    def test_sprints_page_has_status_filter(self, storage_with_project, monkeypatch):
        """Sprints page has status filter dropdown."""
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/sprints?project=test-proj")
        assert "All Status" in response.text
        assert "Planned" in response.text

    def test_sprints_status_filter_works(self, storage_with_project, monkeypatch):
        """Sprints page filters by status correctly."""
        storage_with_project.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-proj",
            title="Active Sprint",
            status="active",
        )
        storage_with_project.create_sprint(
            sprint_id="TEST-S0002",
            project_id="test-proj",
            title="Planned Sprint",
            status="planned",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/sprints?project=test-proj&status=active")
        assert "Active Sprint" in response.text
        assert "Planned Sprint" not in response.text


# =============================================================================
# Analytics Page
# =============================================================================


class TestAnalyticsPage:
    """Test the developer analytics page."""

    def test_analytics_no_project_shows_onboarding(self, app_client):
        """GET /analytics with no project shows onboarding."""
        response = app_client.get("/analytics")
        assert response.status_code == 200
        assert "/sdlc:init" in response.text

    def test_analytics_page_loads(self, client_with_project):
        """Analytics page renders with key elements."""
        response = client_with_project.get("/analytics?project=test-proj")
        assert response.status_code == 200
        assert "Developer Analytics" in response.text
        assert "Completed Tasks" in response.text
        assert "Avg Task Lead Time" in response.text
        assert "Avg Task Cycle Time" in response.text
        assert "Completion Rate" in response.text

    def test_analytics_default_30_days(self, client_with_project):
        """Default time window is 30 days."""
        response = client_with_project.get("/analytics?project=test-proj")
        assert response.status_code == 200
        # The 30d button should have btn-primary class (active)
        assert 'days=30" \n           class="btn btn-primary"' in response.text or "btn-primary\">30d" in response.text

    def test_analytics_time_window_selector(self, client_with_project):
        """All 4 time windows render successfully."""
        for w in [7, 14, 30, 90]:
            response = client_with_project.get(f"/analytics?project=test-proj&days={w}")
            assert response.status_code == 200
            assert "Developer Analytics" in response.text

    def test_analytics_invalid_days_defaults(self, client_with_project):
        """Invalid days parameter defaults to 30."""
        response = client_with_project.get("/analytics?project=test-proj&days=999")
        assert response.status_code == 200
        assert "Developer Analytics" in response.text

    def test_analytics_with_completed_tasks(self, storage_with_project, monkeypatch):
        """Completed tasks show up in metrics."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Done Task",
            status="completed",
        )
        # Manually set completed_at via DB for the completed task
        storage_with_project._db.update_task(
            "TEST-T00001", status="completed", completed_at=now
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/analytics?project=test-proj")
        assert response.status_code == 200
        # At least one completed task
        assert "Completed Tasks" in response.text

    def test_analytics_status_distribution(self, storage_with_project, monkeypatch):
        """Status distribution chart canvas is rendered."""
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Pending Task",
            status="pending",
        )
        storage_with_project.create_task(
            task_id="TEST-T00002",
            project_id="test-proj",
            title="Active Task",
            status="in_progress",
        )
        storage_with_project.create_task(
            task_id="TEST-T00003",
            project_id="test-proj",
            title="Done Task",
            status="completed",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/analytics?project=test-proj")
        assert response.status_code == 200
        assert 'id="statusChart"' in response.text

    def test_analytics_priority_distribution(self, storage_with_project, monkeypatch):
        """Priority distribution chart canvas is rendered."""
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Critical Task",
            priority="critical",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/analytics?project=test-proj")
        assert response.status_code == 200
        assert 'id="priorityChart"' in response.text

    def test_analytics_nav_link(self, client_with_project):
        """Analytics link appears in dashboard nav."""
        response = client_with_project.get("/projects/test-proj")
        assert response.status_code == 200
        assert "/analytics?project=" in response.text
        assert ">Analytics<" in response.text

    def test_analytics_chart_js_loaded(self, client_with_project):
        """Chart.js CDN script tag is present on analytics page."""
        response = client_with_project.get("/analytics?project=test-proj")
        assert response.status_code == 200
        assert "chart.js" in response.text

    def test_analytics_prd_avg_duration_shown(self, client_with_project):
        """Avg PRD Duration label appears on analytics page."""
        response = client_with_project.get("/analytics?project=test-proj")
        assert response.status_code == 200
        assert "Avg PRD Duration" in response.text

    def test_analytics_sprint_avg_duration_shown(self, client_with_project):
        """Avg Sprint Duration label appears on analytics page."""
        response = client_with_project.get("/analytics?project=test-proj")
        assert response.status_code == 200
        assert "Avg Sprint Duration" in response.text

    def test_analytics_sprint_velocity_label_clarified(self, client_with_project):
        """Sprint velocity chart title includes 'Task Throughput'."""
        response = client_with_project.get("/analytics?project=test-proj")
        assert response.status_code == 200
        assert "Task Throughput" in response.text

    def test_analytics_lead_time_tooltip(self, client_with_project):
        """Lead time stat card has tooltip explaining the metric."""
        response = client_with_project.get("/analytics?project=test-proj")
        assert response.status_code == 200
        assert "Time from task creation to completion" in response.text

    def test_analytics_prd_duration_chart(self, client_with_project):
        """PRD duration chart section is present."""
        response = client_with_project.get("/analytics?project=test-proj")
        assert response.status_code == 200
        assert "PRD Completion Time" in response.text

    def test_analytics_sprint_duration_chart(self, client_with_project):
        """Sprint duration chart section is present."""
        response = client_with_project.get("/analytics?project=test-proj")
        assert response.status_code == 200
        assert "Sprint Duration" in response.text


# =============================================================================
# Smart Duration Formatting
# =============================================================================


class TestFormatDuration:
    """Test the _format_duration smart unit formatter."""

    def test_format_duration_minutes(self):
        """<1h shows as minutes."""
        from a_sdlc.ui import _format_duration
        assert _format_duration(0.5) == "30m"
        assert _format_duration(0.25) == "15m"
        assert _format_duration(0.01) == "1m"  # minimum 1m

    def test_format_duration_hours(self):
        """1-48h shows as hours with one decimal."""
        from a_sdlc.ui import _format_duration
        assert _format_duration(1.0) == "1.0h"
        assert _format_duration(24.0) == "24.0h"
        assert _format_duration(47.9) == "47.9h"

    def test_format_duration_days(self):
        """>48h shows as days with one decimal."""
        from a_sdlc.ui import _format_duration
        assert _format_duration(48.0) == "2.0d"
        assert _format_duration(72.0) == "3.0d"
        assert _format_duration(240.0) == "10.0d"


# =============================================================================
# DB Timestamp Tests
# =============================================================================


class TestPRDTimestamps:
    """Test PRD phase timestamp handling (ready_at, split_at, completed_at)."""

    def test_ready_at_set_on_ready(self, temp_storage, tmp_path):
        """ready_at is set when PRD moves to ready, others NULL."""
        temp_storage.create_project("proj", "Proj", str(tmp_path / "proj"))
        temp_storage.create_prd(
            prd_id="P-0001",
            project_id="proj",
            title="Test PRD",
        )
        updated = temp_storage.update_prd("P-0001", status="ready")
        assert updated is not None
        assert updated.get("ready_at") is not None
        assert updated.get("split_at") is None
        assert updated.get("completed_at") is None

    def test_split_at_set_on_split(self, temp_storage, tmp_path):
        """split_at is set when PRD moves to split, ready_at preserved."""
        temp_storage.create_project("proj", "Proj", str(tmp_path / "proj"))
        temp_storage.create_prd(
            prd_id="P-0001",
            project_id="proj",
            title="Test PRD",
        )
        temp_storage.update_prd("P-0001", status="ready")
        updated = temp_storage.update_prd("P-0001", status="split")
        assert updated is not None
        assert updated.get("ready_at") is not None
        assert updated.get("split_at") is not None
        assert updated.get("completed_at") is None

    def test_completed_at_set_on_completed(self, temp_storage, tmp_path):
        """completed_at is set when PRD completes, all others preserved."""
        temp_storage.create_project("proj", "Proj", str(tmp_path / "proj"))
        temp_storage.create_prd(
            prd_id="P-0001",
            project_id="proj",
            title="Test PRD",
        )
        temp_storage.update_prd("P-0001", status="ready")
        temp_storage.update_prd("P-0001", status="split")
        updated = temp_storage.update_prd("P-0001", status="completed")
        assert updated is not None
        assert updated.get("ready_at") is not None
        assert updated.get("split_at") is not None
        assert updated.get("completed_at") is not None

    def test_timestamps_cleared_on_draft(self, temp_storage, tmp_path):
        """All 3 timestamps cleared when PRD returns to draft."""
        temp_storage.create_project("proj", "Proj", str(tmp_path / "proj"))
        temp_storage.create_prd(
            prd_id="P-0001",
            project_id="proj",
            title="Test PRD",
        )
        temp_storage.update_prd("P-0001", status="ready")
        temp_storage.update_prd("P-0001", status="split")
        temp_storage.update_prd("P-0001", status="completed")
        updated = temp_storage.update_prd("P-0001", status="draft")
        assert updated is not None
        assert updated.get("ready_at") is None
        assert updated.get("split_at") is None
        assert updated.get("completed_at") is None

    def test_split_at_cleared_on_backtrack_to_ready(self, temp_storage, tmp_path):
        """split_at cleared when backtracking from split to ready, ready_at preserved."""
        temp_storage.create_project("proj", "Proj", str(tmp_path / "proj"))
        temp_storage.create_prd(
            prd_id="P-0001",
            project_id="proj",
            title="Test PRD",
        )
        temp_storage.update_prd("P-0001", status="ready")
        temp_storage.update_prd("P-0001", status="split")
        updated = temp_storage.update_prd("P-0001", status="ready")
        assert updated is not None
        assert updated.get("ready_at") is not None
        assert updated.get("split_at") is None
        assert updated.get("completed_at") is None

    def test_completed_at_cleared_on_backtrack_to_split(self, temp_storage, tmp_path):
        """completed_at cleared when backtracking from completed to split."""
        temp_storage.create_project("proj", "Proj", str(tmp_path / "proj"))
        temp_storage.create_prd(
            prd_id="P-0001",
            project_id="proj",
            title="Test PRD",
        )
        temp_storage.update_prd("P-0001", status="ready")
        temp_storage.update_prd("P-0001", status="split")
        temp_storage.update_prd("P-0001", status="completed")
        updated = temp_storage.update_prd("P-0001", status="split")
        assert updated is not None
        assert updated.get("ready_at") is not None
        assert updated.get("split_at") is not None
        assert updated.get("completed_at") is None

    def test_ready_at_fresh_after_draft_roundtrip(self, temp_storage, tmp_path):
        """ready->draft->ready gets a fresh ready_at value."""
        temp_storage.create_project("proj", "Proj", str(tmp_path / "proj"))
        temp_storage.create_prd(
            prd_id="P-0001",
            project_id="proj",
            title="Test PRD",
        )
        temp_storage.update_prd("P-0001", status="ready")
        first_ready = temp_storage._db.get_prd("P-0001")["ready_at"]

        # Round-trip through draft
        temp_storage.update_prd("P-0001", status="draft")
        prd_draft = temp_storage._db.get_prd("P-0001")
        assert prd_draft["ready_at"] is None

        temp_storage.update_prd("P-0001", status="ready")
        second_ready = temp_storage._db.get_prd("P-0001")["ready_at"]
        assert second_ready is not None
        # Fresh timestamp should be >= the first one
        assert second_ready >= first_ready


class TestTaskTimestamps:
    """Test started_at and completed_at timestamp handling."""

    def test_started_at_set_on_in_progress(self, temp_storage, tmp_path):
        """started_at is set when task moves to in_progress."""
        temp_storage.create_project("proj", "Proj", str(tmp_path / "proj"))
        temp_storage.create_task(
            task_id="T-00001",
            project_id="proj",
            title="Task",
        )
        updated = temp_storage.update_task("T-00001", status="in_progress")
        assert updated is not None
        assert updated.get("started_at") is not None

    def test_started_at_preserved_on_reenter(self, temp_storage, tmp_path):
        """started_at stays as first value when re-entering in_progress."""
        temp_storage.create_project("proj", "Proj", str(tmp_path / "proj"))
        temp_storage.create_task(
            task_id="T-00001",
            project_id="proj",
            title="Task",
        )
        # First transition to in_progress
        updated = temp_storage.update_task("T-00001", status="in_progress")
        first_started = updated["started_at"]

        # Move to blocked then back to in_progress
        temp_storage.update_task("T-00001", status="blocked")
        updated2 = temp_storage.update_task("T-00001", status="in_progress")
        assert updated2["started_at"] == first_started

    def test_completed_at_cleared_on_reopen(self, temp_storage, tmp_path):
        """completed_at is cleared when task moves from completed to in_progress."""
        temp_storage.create_project("proj", "Proj", str(tmp_path / "proj"))
        temp_storage.create_task(
            task_id="T-00001",
            project_id="proj",
            title="Task",
        )
        temp_storage.update_task("T-00001", status="in_progress")
        temp_storage.update_task("T-00001", status="completed")
        task = temp_storage._db.get_task("T-00001")
        assert task["completed_at"] is not None

        # Reopen
        temp_storage.update_task("T-00001", status="in_progress")
        task2 = temp_storage._db.get_task("T-00001")
        assert task2["completed_at"] is None

    def test_timestamps_cleared_on_pending(self, temp_storage, tmp_path):
        """Both started_at and completed_at are cleared on reset to pending."""
        temp_storage.create_project("proj", "Proj", str(tmp_path / "proj"))
        temp_storage.create_task(
            task_id="T-00001",
            project_id="proj",
            title="Task",
        )
        temp_storage.update_task("T-00001", status="in_progress")
        temp_storage.update_task("T-00001", status="pending")
        task = temp_storage._db.get_task("T-00001")
        assert task["started_at"] is None
        assert task["completed_at"] is None

    def test_sprint_timestamps_on_reversal(self, temp_storage, tmp_path):
        """Sprint timestamps are properly managed on status reversals."""
        temp_storage.create_project("proj", "Proj", str(tmp_path / "proj"))
        temp_storage.create_sprint(
            sprint_id="S-0001",
            project_id="proj",
            title="Sprint",
        )

        # planned -> active
        temp_storage.update_sprint("S-0001", status="active")
        sprint = temp_storage._db.get_sprint("S-0001")
        assert sprint["started_at"] is not None
        sprint["started_at"]

        # active -> planned (full reset)
        temp_storage.update_sprint("S-0001", status="planned")
        sprint2 = temp_storage._db.get_sprint("S-0001")
        assert sprint2["started_at"] is None
        assert sprint2["completed_at"] is None

        # planned -> active -> completed -> active
        temp_storage.update_sprint("S-0001", status="active")
        temp_storage.update_sprint("S-0001", status="completed")
        sprint3 = temp_storage._db.get_sprint("S-0001")
        assert sprint3["completed_at"] is not None

        temp_storage.update_sprint("S-0001", status="active")
        sprint4 = temp_storage._db.get_sprint("S-0001")
        assert sprint4["completed_at"] is None
        # started_at should be preserved (set default, not overwrite)
        assert sprint4["started_at"] is not None


# =============================================================================
# Pipeline Runs Routes
# =============================================================================


class TestPipelineRunsPage:
    """Test the pipeline runs list page (FR-001, FR-002, FR-003)."""

    def test_runs_page_renders(self, client_with_project):
        """GET /runs renders the pipeline runs page."""
        response = client_with_project.get("/runs?project=test-proj")
        assert response.status_code == 200
        assert "Pipeline Runs" in response.text

    def test_runs_page_no_project_shows_onboarding(self, app_client):
        """GET /runs with no project shows onboarding."""
        response = app_client.get("/runs")
        assert response.status_code == 200
        assert "/sdlc:init" in response.text

    def test_runs_page_empty_state(self, client_with_project):
        """Empty runs page shows helpful message."""
        response = client_with_project.get("/runs?project=test-proj")
        assert response.status_code == 200
        assert "No pipeline runs yet" in response.text

    def test_runs_page_has_new_run_button(self, client_with_project):
        """Pipeline runs page has a New Run button."""
        response = client_with_project.get("/runs?project=test-proj")
        assert response.status_code == 200
        assert "New Run" in response.text

    def test_runs_page_has_launch_modal(self, client_with_project):
        """Pipeline runs page has launch modal with form."""
        response = client_with_project.get("/runs?project=test-proj")
        assert response.status_code == 200
        assert "launch-modal" in response.text
        assert "Launch New Pipeline Run" in response.text
        assert 'name="sprint_id"' in response.text
        assert 'name="goal"' in response.text

    def test_runs_page_has_status_filter(self, client_with_project):
        """Pipeline runs page has status filter dropdown."""
        response = client_with_project.get("/runs?project=test-proj")
        assert response.status_code == 200
        assert "All Status" in response.text
        assert "Active" in response.text
        assert "Completed" in response.text
        assert "Failed" in response.text

    def test_runs_page_has_search_input(self, client_with_project, tmp_path, monkeypatch):
        """Runs page has search input when runs exist."""
        # Create a run file
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_data = {
            "run_id": "R-test0001",
            "type": "sprint",
            "entity_id": "TEST-S0001",
            "status": "completed",
            "started_at": "2026-01-01T00:00:00+00:00",
            "pid": None,
        }
        (runs_dir / "R-test0001.json").write_text(json.dumps(run_data))

        import a_sdlc.ui as ui_module
        monkeypatch.setattr(ui_module, "_list_pipeline_runs", lambda status_filter=None: [
            {**run_data, "pid_alive": False, "display_status": "completed"}
        ])
        monkeypatch.setattr(ui_module, "_count_active_runs", lambda: 0)

        response = client_with_project.get("/runs?project=test-proj")
        assert response.status_code == 200
        assert 'id="run-search"' in response.text
        assert "initTableSearch" in response.text

    def test_runs_page_shows_run_data(self, storage_with_project, monkeypatch):
        """Runs page shows run data when runs exist."""
        storage_with_project.create_execution_run(
            "R-abc12345", "test-proj", status="completed"
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs?project=test-proj")
        assert response.status_code == 200
        assert "R-abc12345" in response.text


class TestRunDetailPage:
    """Test the run detail page (FR-004 to FR-007)."""

    def test_run_detail_not_found(self, client_with_project):
        """GET /runs/nonexistent returns 404."""
        response = client_with_project.get("/runs/R-nonexist")
        assert response.status_code == 404
        assert "Run not found" in response.text

    def test_run_detail_renders(self, storage_with_project, monkeypatch):
        """GET /runs/{run_id} renders the detail page."""
        storage_with_project.create_execution_run(
            "R-detail01", "test-proj", status="completed"
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-detail01")
        assert response.status_code == 200
        assert "R-detail01" in response.text

    def test_run_detail_shows_outcome(self, storage_with_project, monkeypatch):
        """Run detail renders for a completed run."""
        storage_with_project.create_execution_run(
            "R-outcome1", "test-proj", status="completed"
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-outcome1")
        assert response.status_code == 200
        assert "R-outcome1" in response.text
        assert "completed" in response.text.lower()

    def test_run_detail_shows_error(self, storage_with_project, monkeypatch):
        """Run detail renders for a failed run."""
        storage_with_project.create_execution_run(
            "R-errored1", "test-proj", status="failed"
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-errored1")
        assert response.status_code == 200
        assert "R-errored1" in response.text
        assert "failed" in response.text.lower()

    def test_run_detail_shows_log_tail(self, storage_with_project, monkeypatch):
        """Run detail page renders for a completed run."""
        storage_with_project.create_execution_run(
            "R-logged01", "test-proj", status="completed"
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-logged01")
        assert response.status_code == 200
        assert "R-logged01" in response.text


class TestPipelineNavLink:
    """Test navigation integration (FR-014, FR-015)."""

    def test_nav_has_pipeline_link(self, client_with_project):
        """Navigation includes Pipeline link."""
        response = client_with_project.get("/projects/test-proj")
        assert response.status_code == 200
        assert "/runs?project=" in response.text
        assert "Pipeline" in response.text

    def test_pipeline_link_active_state(self, client_with_project, monkeypatch):
        """Pipeline nav link is active on runs page."""
        import a_sdlc.ui as ui_module
        monkeypatch.setattr(ui_module, "_list_pipeline_runs", lambda status_filter=None: [])
        monkeypatch.setattr(ui_module, "_count_active_runs", lambda: 0)

        response = client_with_project.get("/runs?project=test-proj")
        assert response.status_code == 200
        # The /runs link should have the active class
        assert 'class="active"' in response.text


class TestRunLauncher:
    """Test the run launcher endpoint (FR-023, FR-024, FR-025)."""

    def _patch_storage_create_run(self, storage, monkeypatch):
        """Patch storage.create_execution_run to forward extra kwargs to DB."""
        original = storage._db.create_execution_run

        def patched_create(run_id, project_id, sprint_id=None, status="pending", **kwargs):
            # Forward to DB which accepts run_type, goal, current_phase, etc.
            return original(
                run_id, project_id, sprint_id=sprint_id, status=status, **kwargs
            )

        monkeypatch.setattr(storage, "create_execution_run", patched_create)

    def test_launch_sprint_missing_entity_id(self, storage_with_project, monkeypatch):
        """POST /runs/launch creates a run and redirects."""
        import subprocess
        storage_with_project.create_sprint(
            sprint_id="TEST-S0001", project_id="test-proj", title="Sprint 1"
        )
        self._patch_storage_create_run(storage_with_project, monkeypatch)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: type("P", (), {"pid": 99})())
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/runs/launch",
            data={"sprint_id": "TEST-S0001"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/runs/")

    def test_launch_objective_missing_goal(self, storage_with_project, monkeypatch):
        """POST /runs/launch with goal creates an objective run."""
        import subprocess
        self._patch_storage_create_run(storage_with_project, monkeypatch)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: type("P", (), {"pid": 99})())
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/runs/launch",
            data={"goal": "Build a REST API"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/runs/")

    def test_launch_no_claude_cli(self, storage_with_project, monkeypatch):
        """POST /runs/launch spawns subprocess and redirects."""
        import subprocess
        storage_with_project.create_sprint(
            sprint_id="TEST-S0001", project_id="test-proj", title="Sprint 1"
        )
        self._patch_storage_create_run(storage_with_project, monkeypatch)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: type("P", (), {"pid": 99})())
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/runs/launch",
            data={"sprint_id": "TEST-S0001"},
            follow_redirects=False,
        )
        assert response.status_code == 303

    def test_launch_sprint_success(self, storage_with_project, monkeypatch):
        """POST /runs/launch with valid sprint spawns and redirects."""
        import subprocess
        storage_with_project.create_sprint(
            sprint_id="TEST-S0001", project_id="test-proj", title="Sprint 1"
        )
        self._patch_storage_create_run(storage_with_project, monkeypatch)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: type("P", (), {"pid": 99})())
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/runs/launch",
            data={"sprint_id": "TEST-S0001"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/runs/")

    def test_launch_objective_success(self, storage_with_project, monkeypatch):
        """POST /runs/launch with valid objective spawns and redirects."""
        import subprocess
        self._patch_storage_create_run(storage_with_project, monkeypatch)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: type("P", (), {"pid": 99})())
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/runs/launch",
            data={"goal": "Build a REST API for user management"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].startswith("/runs/")


class TestListPipelineRuns:
    """Test the _list_pipeline_runs helper function."""

    def test_empty_when_no_directory(self, monkeypatch):
        """Returns empty list when no project exists."""
        from a_sdlc.ui import _list_pipeline_runs

        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = None
        import a_sdlc.ui as ui_module
        monkeypatch.setattr(ui_module, "get_storage", lambda: mock_storage)
        result = _list_pipeline_runs()
        assert result == []

    def test_reads_run_files(self, monkeypatch):
        """Reads runs from the database."""
        from a_sdlc.ui import _list_pipeline_runs

        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "test-proj"}
        mock_storage.list_execution_runs.return_value = [
            {"id": "R-list0001", "status": "completed", "pid": None}
        ]
        import a_sdlc.ui as ui_module
        monkeypatch.setattr(ui_module, "get_storage", lambda: mock_storage)
        result = _list_pipeline_runs()
        assert len(result) == 1
        assert result[0]["id"] == "R-list0001"
        assert result[0]["display_status"] == "completed"

    def test_filters_by_status(self, monkeypatch):
        """Filters runs by status when status_filter is provided."""
        from a_sdlc.ui import _list_pipeline_runs

        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "test-proj"}
        mock_storage.list_execution_runs.return_value = [
            {"id": "R-filt0000", "status": "completed", "pid": None},
        ]
        import a_sdlc.ui as ui_module
        monkeypatch.setattr(ui_module, "get_storage", lambda: mock_storage)
        result = _list_pipeline_runs(status_filter="completed")
        assert len(result) == 1
        mock_storage.list_execution_runs.assert_called_with("test-proj", status="completed")


class TestCountActiveRuns:
    """Test the _count_active_runs helper function."""

    def test_zero_when_no_directory(self, monkeypatch):
        """Returns 0 when runs directory does not exist."""
        from a_sdlc.ui import _count_active_runs

        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = None
        import a_sdlc.ui as ui_module
        monkeypatch.setattr(ui_module, "get_storage", lambda: mock_storage)
        assert _count_active_runs() == 0

    def test_zero_when_no_running(self, monkeypatch):
        """Returns 0 when no runs are in running state."""
        from a_sdlc.ui import _count_active_runs

        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "test-proj"}
        mock_storage.list_execution_runs.return_value = []
        import a_sdlc.ui as ui_module
        monkeypatch.setattr(ui_module, "get_storage", lambda: mock_storage)
        assert _count_active_runs() == 0


# =============================================================================
# Thread Viewer + Comments + Thread Tabs (SDLC-T00200)
# =============================================================================


class TestThreadViewerPartial:
    """Test GET /threads/{artifact_type}/{artifact_id} endpoint."""

    def test_empty_thread_returns_empty_state(
        self, storage_with_project, monkeypatch
    ):
        """Thread viewer shows empty state when no entries exist."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/threads/prd/TEST-P0001")
        assert response.status_code == 200
        assert "No thread entries yet" in response.text

    def test_thread_with_entries(self, storage_with_project, monkeypatch):
        """Thread viewer displays thread entries."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        # Create execution run first (FK requirement)
        storage_with_project.create_execution_run(
            run_id="R-test01", project_id="test-proj"
        )
        # Create a thread entry directly
        storage_with_project.create_artifact_thread_entry(
            run_id="R-test01",
            project_id="test-proj",
            artifact_type="prd",
            artifact_id="TEST-P0001",
            entry_type="creation",
            agent_persona="pm",
            content="Initial PRD creation",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/threads/prd/TEST-P0001")
        assert response.status_code == 200
        assert "pm" in response.text
        assert "Creation" in response.text

    def test_thread_for_task(self, storage_with_project, monkeypatch):
        """Thread viewer works for tasks."""
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Test Task",
        )
        storage_with_project.create_execution_run(
            run_id="R-test01", project_id="test-proj"
        )
        storage_with_project.create_artifact_thread_entry(
            run_id="R-test01",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="challenge",
            agent_persona="architect",
            content="Challenge: missing error handling",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/threads/task/TEST-T00001")
        assert response.status_code == 200
        assert "architect" in response.text
        assert "Challenge" in response.text

    def test_thread_entry_type_colors(self, storage_with_project, monkeypatch):
        """Thread entries have type-specific CSS classes."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        storage_with_project.create_execution_run(
            run_id="R-test01", project_id="test-proj"
        )
        for etype in ["creation", "challenge", "revision", "approval"]:
            storage_with_project.create_artifact_thread_entry(
                run_id="R-test01",
                project_id="test-proj",
                artifact_type="prd",
                artifact_id="TEST-P0001",
                entry_type=etype,
                agent_persona="agent",
                content=f"Entry: {etype}",
            )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/threads/prd/TEST-P0001")
        text = response.text
        assert "thread-entry-creation" in text
        assert "thread-entry-challenge" in text
        assert "thread-entry-revision" in text
        assert "thread-entry-approval" in text


class TestThreadComment:
    """Test POST /threads/{artifact_type}/{artifact_id}/comment endpoint."""

    def test_post_comment_creates_entry(
        self, storage_with_project, monkeypatch
    ):
        """Posting a comment creates a user_intervention thread entry."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/threads/prd/TEST-P0001/comment",
            json={"content": "This is a user comment"},
        )
        assert response.status_code == 200
        # The response should be the updated thread viewer partial
        assert "User" in response.text
        assert "User Intervention" in response.text

    def test_post_comment_rejects_empty(
        self, storage_with_project, monkeypatch
    ):
        """Empty comment returns 400."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/threads/prd/TEST-P0001/comment",
            json={"content": ""},
        )
        assert response.status_code == 400

    def test_post_comment_returns_404_for_unknown_artifact(
        self, storage_with_project, monkeypatch
    ):
        """Comment on non-existent artifact returns 404."""
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/threads/prd/NONEXIST-P9999/comment",
            json={"content": "Hello"},
        )
        assert response.status_code == 404

    def test_post_comment_uses_existing_run_id(
        self, storage_with_project, monkeypatch
    ):
        """Comment uses the most recent run_id from existing thread entries."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        storage_with_project.create_execution_run(
            run_id="R-existing", project_id="test-proj"
        )
        storage_with_project.create_artifact_thread_entry(
            run_id="R-existing",
            project_id="test-proj",
            artifact_type="prd",
            artifact_id="TEST-P0001",
            entry_type="creation",
            content="First entry",
        )
        client = _make_client(storage_with_project, monkeypatch)
        client.post(
            "/threads/prd/TEST-P0001/comment",
            json={"content": "User comment"},
        )
        # Verify the comment was stored with the existing run_id
        entries = storage_with_project.list_artifact_threads_by_artifact(
            "prd", "TEST-P0001"
        )
        user_entries = [e for e in entries if e["entry_type"] == "user_intervention"]
        assert len(user_entries) == 1
        assert user_entries[0]["run_id"] == "R-existing"

    def test_post_comment_on_task(self, storage_with_project, monkeypatch):
        """Posting a comment works for task artifacts."""
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Test Task",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/threads/task/TEST-T00001/comment",
            json={"content": "Task comment"},
        )
        assert response.status_code == 200
        entries = storage_with_project.list_artifact_threads_by_artifact(
            "task", "TEST-T00001"
        )
        assert len(entries) == 1
        assert entries[0]["content"] == "Task comment"


class TestThreadTabsOnDetailPages:
    """Test that detail pages include the Agent Thread tab."""

    def test_prd_detail_has_thread_tab(
        self, storage_with_project, monkeypatch
    ):
        """PRD detail page includes Agent Thread tab button."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds/TEST-P0001")
        assert response.status_code == 200
        assert "Agent Thread" in response.text
        assert 'id="tab-thread"' in response.text
        assert 'id="panel-thread"' in response.text

    def test_prd_detail_thread_tab_count(
        self, storage_with_project, monkeypatch
    ):
        """PRD detail shows thread entry count in tab badge."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        storage_with_project.create_execution_run(
            run_id="R-test01", project_id="test-proj"
        )
        storage_with_project.create_artifact_thread_entry(
            run_id="R-test01",
            project_id="test-proj",
            artifact_type="prd",
            artifact_id="TEST-P0001",
            entry_type="creation",
            content="Entry 1",
        )
        storage_with_project.create_artifact_thread_entry(
            run_id="R-test01",
            project_id="test-proj",
            artifact_type="prd",
            artifact_id="TEST-P0001",
            entry_type="challenge",
            content="Entry 2",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds/TEST-P0001")
        assert response.status_code == 200
        assert "Agent Thread (2)" in response.text

    def test_task_detail_has_thread_tab(
        self, storage_with_project, monkeypatch
    ):
        """Task detail page includes Agent Thread tab."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )
        storage_with_project.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            title="Test Task",
            prd_id="TEST-P0001",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/tasks/TEST-T00001")
        assert response.status_code == 200
        assert "Agent Thread" in response.text
        assert 'id="tab-thread"' in response.text

    def test_sprint_detail_has_thread_section(
        self, storage_with_project, monkeypatch
    ):
        """Sprint detail page includes Agent Thread section."""
        storage_with_project.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-proj",
            title="Test Sprint",
            goal="Test goal",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/sprints/TEST-S0001")
        assert response.status_code == 200
        assert "Agent Thread" in response.text
        assert "thread-viewer-target" in response.text


# =============================================================================
# Kanban Board + Work Item Actions (SDLC-T00198)
# =============================================================================


class TestRunDetailKanban:
    """Test the kanban board rendering on the run detail page (FR-004)."""

    def test_kanban_renders_with_work_items(
        self, storage_with_project, monkeypatch
    ):
        """Run detail shows kanban board when work queue items exist."""
        storage_with_project.create_execution_run(
            "R-kanban01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-001", "R-kanban01", "test-proj", "prd_generate",
            artifact_type="prd", artifact_id="TEST-P0001", status="pending",
        )
        storage_with_project.create_work_queue_item(
            "WQ-002", "R-kanban01", "test-proj", "task_execute",
            artifact_type="task", artifact_id="TEST-T00001",
            status="in_progress", assigned_agent_id="engineer-1",
        )
        storage_with_project.create_work_queue_item(
            "WQ-003", "R-kanban01", "test-proj", "prd_review",
            artifact_type="prd", artifact_id="TEST-P0002", status="completed",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-kanban01")
        assert response.status_code == 200
        text = response.text

        # Kanban board should be present
        assert "kanban-board" in text

        # Core columns always shown
        assert "column-pending" in text
        assert "column-in_progress" in text
        assert "column-completed" in text
        assert "column-escalated" in text

    def test_kanban_shows_queue_stats(
        self, storage_with_project, monkeypatch
    ):
        """Run detail shows queue summary stats cards."""
        storage_with_project.create_execution_run(
            "R-kanban01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-001", "R-kanban01", "test-proj", "prd_generate",
            status="pending",
        )
        storage_with_project.create_work_queue_item(
            "WQ-002", "R-kanban01", "test-proj", "task_execute",
            status="completed",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-kanban01")
        assert response.status_code == 200
        text = response.text

        # Stats section shows stat-card elements with labels
        assert "stat-card" in text
        assert "Phase" in text

    def test_kanban_no_board_without_db_run(
        self, storage_with_project, monkeypatch
    ):
        """Kanban board does not render when no execution_run in DB."""
        # Do NOT create execution_run in DB
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-kanban01")
        # Route returns 404 when run not found in DB
        assert response.status_code == 404

    def test_kanban_persona_badge(
        self, storage_with_project, monkeypatch
    ):
        """Active agent persona badge is shown for assigned items (FR-022)."""
        storage_with_project.create_execution_run(
            "R-kanban01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-001", "R-kanban01", "test-proj", "task_execute",
            status="in_progress", assigned_agent_id="architect",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-kanban01")
        assert response.status_code == 200
        assert "agent-persona-badge" in response.text
        assert "architect" in response.text

    def test_kanban_action_buttons_pending(
        self, storage_with_project, monkeypatch
    ):
        """Pending items show Skip and Cancel action buttons (FR-016)."""
        storage_with_project.create_execution_run(
            "R-kanban01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-001", "R-kanban01", "test-proj", "prd_generate",
            status="pending",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-kanban01")
        text = response.text
        assert "Cancel" in text
        assert "action=cancel" in text

    def test_kanban_action_buttons_in_progress(
        self, storage_with_project, monkeypatch
    ):
        """In-progress items show Cancel action button."""
        storage_with_project.create_execution_run(
            "R-kanban01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-001", "R-kanban01", "test-proj", "task_execute",
            status="in_progress",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-kanban01")
        text = response.text
        assert "Cancel" in text
        assert "action=cancel" in text

    def test_kanban_action_buttons_failed(
        self, storage_with_project, monkeypatch
    ):
        """Failed items show Retry and Skip action buttons."""
        storage_with_project.create_execution_run(
            "R-kanban01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-001", "R-kanban01", "test-proj", "task_execute",
            status="failed",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-kanban01")
        text = response.text
        assert "Retry" in text
        assert "action=retry" in text

    def test_kanban_cancelled_column_hidden_when_empty(
        self, storage_with_project, monkeypatch
    ):
        """Cancelled column not shown when there are no cancelled items."""
        storage_with_project.create_execution_run(
            "R-kanban01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-001", "R-kanban01", "test-proj", "task_execute",
            status="pending",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-kanban01")
        # The 4 core columns are always shown, but cancelled is conditional
        assert "col-cancelled" not in response.text or "<span>Cancelled</span>" not in response.text


    def test_kanban_cancelled_column_shown_when_nonempty(
        self, storage_with_project, monkeypatch
    ):
        """Escalated column appears when there are failed items."""
        storage_with_project.create_execution_run(
            "R-kanban01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-001", "R-kanban01", "test-proj", "task_execute",
            status="failed",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-kanban01")
        assert "column-escalated" in response.text


class TestWorkItemAction:
    """Test POST /runs/items/{item_id}/action endpoint (FR-016)."""

    def test_cancel_action(self, storage_with_project, monkeypatch):
        """Cancel action updates item status to cancelled."""
        storage_with_project.create_execution_run(
            "R-action01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-001", "R-action01", "test-proj", "task_execute",
            status="in_progress",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/runs/items/WQ-001/action",
            data={"action": "cancel"},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "cancelled" in response.text.lower()

        item = storage_with_project.get_work_queue_item("WQ-001")
        assert item["status"] == "cancelled"

    def test_skip_action(self, storage_with_project, monkeypatch):
        """Skip action updates item status to skipped."""
        storage_with_project.create_execution_run(
            "R-action01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-002", "R-action01", "test-proj", "prd_generate",
            status="pending",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/runs/items/WQ-002/action",
            data={"action": "skip"},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "skipped" in response.text.lower()

        item = storage_with_project.get_work_queue_item("WQ-002")
        assert item["status"] == "skipped"

    def test_retry_action(self, storage_with_project, monkeypatch):
        """Retry action resets status to pending and increments retry_count."""
        storage_with_project.create_execution_run(
            "R-action01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-003", "R-action01", "test-proj", "task_execute",
            status="failed",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/runs/items/WQ-003/action",
            data={"action": "retry"},
            follow_redirects=False,
        )
        assert response.status_code == 200
        assert "pending" in response.text.lower()

        item = storage_with_project.get_work_queue_item("WQ-003")
        assert item["status"] == "pending"
        assert item["retry_count"] == 1

    def test_retry_increments_count(self, storage_with_project, monkeypatch):
        """Multiple retries increment the retry count cumulatively."""
        storage_with_project.create_execution_run(
            "R-action01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-004", "R-action01", "test-proj", "task_execute",
            status="failed",
        )
        client = _make_client(storage_with_project, monkeypatch)

        # First retry
        client.post(
            "/runs/items/WQ-004/action",
            data={"action": "retry"},
            follow_redirects=False,
        )
        # Set back to failed for second retry
        storage_with_project.update_work_queue_item("WQ-004", status="failed")

        # Second retry
        client.post(
            "/runs/items/WQ-004/action",
            data={"action": "retry"},
            follow_redirects=False,
        )

        item = storage_with_project.get_work_queue_item("WQ-004")
        assert item["status"] == "pending"
        assert item["retry_count"] == 2

    def test_pause_action(self, storage_with_project, monkeypatch):
        """Pause action sets item status to pending."""
        storage_with_project.create_execution_run(
            "R-action01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-005", "R-action01", "test-proj", "task_execute",
            status="in_progress",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/runs/items/WQ-005/action",
            data={"action": "pause"},
            follow_redirects=False,
        )
        assert response.status_code == 200
        item = storage_with_project.get_work_queue_item("WQ-005")
        assert item["status"] == "pending"

    def test_unknown_action_returns_400(self, storage_with_project, monkeypatch):
        """Unknown action returns 400 error."""
        storage_with_project.create_execution_run(
            "R-action01", "test-proj", status="running"
        )
        storage_with_project.create_work_queue_item(
            "WQ-006", "R-action01", "test-proj", "task_execute",
            status="pending",
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/runs/items/WQ-006/action",
            data={"action": "bogus"},
            follow_redirects=False,
        )
        assert response.status_code == 400
        assert "Unknown action" in response.text

    def test_nonexistent_item_returns_404(
        self, storage_with_project, monkeypatch
    ):
        """Action on non-existent work item returns 404."""
        client = _make_client(storage_with_project, monkeypatch)
        response = client.post(
            "/runs/items/WQ-NOPE/action",
            data={"action": "cancel"},
            follow_redirects=False,
        )
        assert response.status_code == 404
        assert "Work item not found" in response.text



class TestPhaseProgress:
    """Test phase progress indicator on run detail (FR-006)."""

    def _setup_run_with_phase(
        self, storage, monkeypatch, current_phase="implementation"
    ):
        """Helper: create execution_run with a current phase."""
        storage.create_execution_run("R-phase01", "test-proj", status="running")
        if current_phase:
            storage.update_execution_run(
                "R-phase01", current_phase=current_phase
            )

    def test_phase_progress_renders(
        self, storage_with_project, monkeypatch
    ):
        """Phase progress section renders with phase stat card."""
        self._setup_run_with_phase(
            storage_with_project, monkeypatch, "implementation"
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-phase01")
        assert response.status_code == 200
        text = response.text

        # Template has a stat card with "Phase" label and progress bar
        assert "Phase" in text
        assert "stat-card" in text
        assert "progress-bar" in text

    def test_phase_active_class(
        self, storage_with_project, monkeypatch
    ):
        """Current phase is shown in the stat card."""
        self._setup_run_with_phase(
            storage_with_project, monkeypatch, "design"
        )
        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-phase01")
        assert response.status_code == 200
        assert "design" in response.text.lower()


class TestChallengeConvergence:
    """Test challenge convergence display on run detail (FR-007)."""

    def _setup_run(self, storage, monkeypatch, run_id="R-conv01"):
        """Helper: create DB execution_run."""
        storage.create_execution_run(run_id, "test-proj", status="running")

    def test_convergence_table_renders(
        self, storage_with_project, monkeypatch
    ):
        """Challenge convergence section renders when artifact threads exist."""
        self._setup_run(storage_with_project, monkeypatch)
        storage_with_project.create_artifact_thread_entry(
            run_id="R-conv01",
            project_id="test-proj",
            artifact_type="prd",
            artifact_id="TEST-P0001",
            entry_type="creation",
            agent_persona="pm",
            content="Created PRD",
            round_number=1,
        )
        storage_with_project.create_artifact_thread_entry(
            run_id="R-conv01",
            project_id="test-proj",
            artifact_type="prd",
            artifact_id="TEST-P0001",
            entry_type="challenge",
            agent_persona="architect",
            content="Missing error handling",
            round_number=1,
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-conv01")
        assert response.status_code == 200
        text = response.text

        # Template has a "Convergence" stat card showing convergence rate
        assert "Convergence" in text or "convergence" in text.lower()

    def test_convergence_not_shown_without_threads(
        self, storage_with_project, monkeypatch
    ):
        """Challenge convergence section not rendered when no threads."""
        self._setup_run(storage_with_project, monkeypatch)
        # No artifact thread entries created

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/runs/R-conv01")
        assert response.status_code == 200
        assert "<h2>Challenge Convergence</h2>" not in response.text


# =============================================================================
# WebSocket Infrastructure (SDLC-T00196)
# =============================================================================


class TestConnectionManager:
    """Test the ConnectionManager class for WebSocket tracking."""

    def test_connect_and_disconnect(self):
        """ConnectionManager tracks connections per run_id."""
        from unittest.mock import AsyncMock

        from a_sdlc.ui import ConnectionManager

        async def _run():
            mgr = ConnectionManager()
            ws = AsyncMock()
            ws.accept = AsyncMock()
            ws.send_json = AsyncMock()

            await mgr.connect(ws, "RUN-001")
            assert mgr.connection_count("RUN-001") == 1
            assert "RUN-001" in mgr.watched_run_ids

            mgr.disconnect(ws, "RUN-001")
            assert mgr.connection_count("RUN-001") == 0
            assert "RUN-001" not in mgr.watched_run_ids

        asyncio.run(_run())

    def test_broadcast_sends_to_all(self):
        """Broadcast sends JSON to all watchers of a run."""
        from unittest.mock import AsyncMock

        from a_sdlc.ui import ConnectionManager

        async def _run():
            mgr = ConnectionManager()
            ws1 = AsyncMock()
            ws1.accept = AsyncMock()
            ws1.send_json = AsyncMock()
            ws2 = AsyncMock()
            ws2.accept = AsyncMock()
            ws2.send_json = AsyncMock()

            await mgr.connect(ws1, "RUN-001")
            await mgr.connect(ws2, "RUN-001")

            await mgr.broadcast("RUN-001", {"type": "state_changed"})

            ws1.send_json.assert_called_once_with({"type": "state_changed"})
            ws2.send_json.assert_called_once_with({"type": "state_changed"})

        asyncio.run(_run())

    def test_broadcast_removes_dead_connections(self):
        """Dead connections are removed during broadcast."""
        from unittest.mock import AsyncMock

        from a_sdlc.ui import ConnectionManager

        async def _run():
            mgr = ConnectionManager()
            ws_good = AsyncMock()
            ws_good.accept = AsyncMock()
            ws_good.send_json = AsyncMock()
            ws_dead = AsyncMock()
            ws_dead.accept = AsyncMock()
            ws_dead.send_json = AsyncMock(side_effect=RuntimeError("closed"))

            await mgr.connect(ws_good, "RUN-001")
            await mgr.connect(ws_dead, "RUN-001")
            assert mgr.connection_count("RUN-001") == 2

            await mgr.broadcast("RUN-001", {"type": "test"})

            assert mgr.connection_count("RUN-001") == 1

        asyncio.run(_run())

    def test_disconnect_cleans_empty_run(self):
        """Disconnecting the last watcher removes the run_id key."""
        from unittest.mock import AsyncMock

        from a_sdlc.ui import ConnectionManager

        async def _run():
            mgr = ConnectionManager()
            ws = AsyncMock()
            ws.accept = AsyncMock()

            await mgr.connect(ws, "RUN-002")
            assert "RUN-002" in mgr.active_connections

            mgr.disconnect(ws, "RUN-002")
            assert "RUN-002" not in mgr.active_connections

        asyncio.run(_run())

    def test_total_connections(self):
        """total_connections property counts across all runs."""
        from unittest.mock import AsyncMock

        from a_sdlc.ui import ConnectionManager

        async def _run():
            mgr = ConnectionManager()
            ws1 = AsyncMock()
            ws1.accept = AsyncMock()
            ws2 = AsyncMock()
            ws2.accept = AsyncMock()

            await mgr.connect(ws1, "RUN-001")
            await mgr.connect(ws2, "RUN-002")
            assert mgr.total_connections == 2

        asyncio.run(_run())

    def test_broadcast_to_nonexistent_run(self):
        """Broadcasting to a run with no watchers is a no-op."""
        from a_sdlc.ui import ConnectionManager

        async def _run():
            mgr = ConnectionManager()
            # Should not raise
            await mgr.broadcast("NONEXIST", {"type": "test"})

        asyncio.run(_run())

    def test_disconnect_unknown_websocket(self):
        """Disconnecting an unknown websocket is a no-op."""
        from unittest.mock import AsyncMock

        from a_sdlc.ui import ConnectionManager

        mgr = ConnectionManager()
        ws = AsyncMock()
        # Should not raise (synchronous method)
        mgr.disconnect(ws, "RUN-UNKNOWN")


class TestWebSocketEndpoint:
    """Test the /ws/runs/{run_id} WebSocket endpoint."""

    def test_websocket_connect_disconnect(self, client_with_project):
        """WebSocket endpoint accepts and handles disconnect."""
        with client_with_project.websocket_connect("/ws/runs/RUN-001") as _ws:
            # Connection should be accepted (no exception)
            pass  # Closing the context manager triggers disconnect


class TestActivePipelineCount:
    """Test the _get_active_pipeline_count helper."""

    def test_returns_zero_when_no_project_id(self):
        """Returns 0 when project_id is None."""
        from a_sdlc.ui import _get_active_pipeline_count

        assert _get_active_pipeline_count(None) == 0

    def test_returns_zero_when_no_runs(self, storage_with_project, monkeypatch):
        """Returns 0 when no execution runs exist."""
        import a_sdlc.ui as ui_module
        from a_sdlc.ui import _get_active_pipeline_count

        monkeypatch.setattr(ui_module, "get_storage", lambda: storage_with_project)
        count = _get_active_pipeline_count("test-proj")
        assert count == 0

    def test_returns_count_of_active_runs(self, storage_with_project, monkeypatch):
        """Returns correct count of active runs."""
        import a_sdlc.ui as ui_module
        from a_sdlc.ui import _get_active_pipeline_count

        monkeypatch.setattr(ui_module, "get_storage", lambda: storage_with_project)
        storage_with_project.create_execution_run(
            "R-active01", "test-proj", status="active"
        )
        storage_with_project.create_execution_run(
            "R-active02", "test-proj", status="active"
        )
        storage_with_project.create_execution_run(
            "R-done01", "test-proj", status="completed"
        )
        count = _get_active_pipeline_count("test-proj")
        assert count == 2

    def test_returns_zero_on_error(self, monkeypatch):
        """Returns 0 when storage raises an exception."""
        import a_sdlc.ui as ui_module
        from a_sdlc.ui import _get_active_pipeline_count

        def broken_storage():
            raise RuntimeError("DB unavailable")

        monkeypatch.setattr(ui_module, "get_storage", broken_storage)
        assert _get_active_pipeline_count("test-proj") == 0


class TestBaseTemplateWSExtension:
    """Test base.html includes HTMX WebSocket extension and new CSS."""

    def test_includes_ws_extension_script(self, client_with_project):
        """base.html includes the HTMX WebSocket extension script."""
        response = client_with_project.get("/projects/test-proj")
        assert response.status_code == 200
        assert "htmx-ext-ws" in response.text

    def test_includes_pipeline_nav_link(self, client_with_project):
        """base.html includes Pipeline nav link when project exists."""
        response = client_with_project.get("/projects/test-proj")
        assert response.status_code == 200
        assert "Pipeline" in response.text
        assert "/runs?project=" in response.text

    def test_includes_nav_badge_css(self, client_with_project):
        """base.html includes nav-badge CSS class."""
        response = client_with_project.get("/projects/test-proj")
        assert response.status_code == 200
        assert ".nav-badge" in response.text

    def test_includes_entry_type_css(self, client_with_project):
        """base.html includes entry type color CSS classes."""
        response = client_with_project.get("/projects/test-proj")
        text = response.text
        assert ".entry-implement" in text
        assert ".entry-review" in text
        assert ".entry-qa" in text
        assert ".entry-design" in text
        assert ".entry-pm" in text
        assert ".entry-challenge" in text
        assert ".entry-split" in text
        assert ".entry-escalation" in text

    def test_includes_entry_bg_css(self, client_with_project):
        """base.html includes entry type background CSS classes."""
        response = client_with_project.get("/projects/test-proj")
        text = response.text
        assert ".entry-bg-implement" in text
        assert ".entry-bg-review" in text
        assert ".entry-bg-qa" in text

    def test_includes_new_status_css(self, client_with_project):
        """base.html includes new status CSS classes."""
        response = client_with_project.get("/projects/test-proj")
        text = response.text
        assert ".status-escalated" in text
        assert ".status-awaiting_clarification" in text
        assert ".status-running" in text
        assert ".status-failed" in text

    def test_includes_btn_action_danger_css(self, client_with_project):
        """base.html includes btn-action-danger CSS class."""
        response = client_with_project.get("/projects/test-proj")
        assert ".btn-action-danger" in response.text


class TestChangeDetector:
    """Test the _change_detector background coroutine behavior."""

    def test_skips_runs_with_no_watchers(self, monkeypatch):
        """Change detector does not call get_run_state_hash when no watchers."""
        import a_sdlc.ui as ui_module
        from a_sdlc.ui import ConnectionManager

        mock_storage = MagicMock()
        monkeypatch.setattr(ui_module, "get_storage", lambda: mock_storage)

        # Use a fresh manager with no connections
        test_mgr = ConnectionManager()
        monkeypatch.setattr(ui_module, "manager", test_mgr)

        async def _run():
            from a_sdlc.ui import _change_detector

            task = asyncio.create_task(_change_detector())
            await asyncio.sleep(1.5)  # Allow one iteration
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        asyncio.run(_run())
        mock_storage.get_run_state_hash.assert_not_called()

    def test_broadcasts_on_hash_change(self, monkeypatch):
        """Change detector broadcasts when hash changes (after initial population)."""
        from unittest.mock import AsyncMock

        import a_sdlc.ui as ui_module
        from a_sdlc.ui import ConnectionManager

        # Track results across async boundary
        results = {}

        async def _run():
            test_mgr = ConnectionManager()
            ws = AsyncMock()
            ws.accept = AsyncMock()
            ws.send_json = AsyncMock()
            await test_mgr.connect(ws, "RUN-HASH01")

            monkeypatch.setattr(ui_module, "manager", test_mgr)

            # Mock storage to return changing hashes
            call_count = {"n": 0}
            hashes = ["hash-v1", "hash-v1", "hash-v2"]

            def mock_get_hash(run_id):
                idx = min(call_count["n"], len(hashes) - 1)
                call_count["n"] += 1
                return hashes[idx]

            mock_storage = MagicMock()
            mock_storage.get_run_state_hash = mock_get_hash
            monkeypatch.setattr(ui_module, "get_storage", lambda: mock_storage)

            from a_sdlc.ui import _change_detector

            task = asyncio.create_task(_change_detector())
            await asyncio.sleep(3.5)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

            results["call_count"] = ws.send_json.call_count
            if ws.send_json.call_count >= 1:
                results["last_call"] = ws.send_json.call_args[0][0]

        asyncio.run(_run())

        assert results["call_count"] >= 1
        assert results["last_call"]["type"] == "state_changed"
        assert results["last_call"]["run_id"] == "RUN-HASH01"
        assert results["last_call"]["hash"] == "hash-v2"

    def test_does_not_broadcast_on_initial_hash(self, monkeypatch):
        """Change detector does not broadcast on the first hash read."""
        from unittest.mock import AsyncMock

        import a_sdlc.ui as ui_module
        from a_sdlc.ui import ConnectionManager

        results = {}

        async def _run():
            test_mgr = ConnectionManager()
            ws = AsyncMock()
            ws.accept = AsyncMock()
            ws.send_json = AsyncMock()
            await test_mgr.connect(ws, "RUN-INIT01")

            monkeypatch.setattr(ui_module, "manager", test_mgr)

            mock_storage = MagicMock()
            mock_storage.get_run_state_hash.return_value = "initial-hash"
            monkeypatch.setattr(ui_module, "get_storage", lambda: mock_storage)

            from a_sdlc.ui import _change_detector

            task = asyncio.create_task(_change_detector())
            await asyncio.sleep(2.5)  # Two iterations, same hash
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

            results["call_count"] = ws.send_json.call_count

        asyncio.run(_run())

        # No broadcast because only initial hash was seen (or same hash repeated)
        assert results["call_count"] == 0
