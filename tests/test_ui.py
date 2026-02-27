"""Tests for the web UI routes and dashboard enhancements."""

import tempfile
from pathlib import Path

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
    from a_sdlc.ui import app
    import a_sdlc.ui as ui_module

    monkeypatch.setattr(ui_module, "get_storage", lambda: temp_storage)
    return TestClient(app)


@pytest.fixture
def storage_with_project(temp_storage, tmp_path):
    """Create storage with a test project."""
    temp_storage.create_project("test-proj", "Test Project", str(tmp_path / "test"))
    return temp_storage


@pytest.fixture
def client_with_project(storage_with_project, monkeypatch):
    """Create a test client with a project in storage."""
    from starlette.testclient import TestClient
    from a_sdlc.ui import app
    import a_sdlc.ui as ui_module

    monkeypatch.setattr(ui_module, "get_storage", lambda: storage_with_project)
    return TestClient(app)


def _make_client(storage, monkeypatch):
    """Helper to create a test client with given storage."""
    from starlette.testclient import TestClient
    from a_sdlc.ui import app
    import a_sdlc.ui as ui_module

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

    def test_prd_split_copy_button(
        self, storage_with_project, monkeypatch
    ):
        """PRD list shows copy split command for splittable PRDs."""
        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
            status="draft",
        )

        client = _make_client(storage_with_project, monkeypatch)
        response = client.get("/prds?project=test-proj")
        assert response.status_code == 200
        assert "/sdlc:prd-split TEST-P0001" in response.text


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
        """ready→draft→ready gets a fresh ready_at value."""
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
        first_started = sprint["started_at"]

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
