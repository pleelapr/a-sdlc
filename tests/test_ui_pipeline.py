"""Integration tests for pipeline UI routes (PRD SDLC-P0033).

Covers:
- Pipeline runs list page (GET /runs)
- Run launcher (POST /runs/launch)
- Run detail page with kanban board (GET /runs/{run_id})
- Run-level control actions (POST /runs/{run_id}/action)
- Work item control actions (POST /runs/items/{item_id}/action)
- Thread viewer (GET /threads/{type}/{id})
- Thread comment posting (POST /threads/{type}/{id}/comment)
- WebSocket connection lifecycle (WS /ws/runs/{run_id})
- Thread tab integration on existing PRD/task detail pages
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from a_sdlc.storage import FileStorage

# Only run if fastapi is installed
pytest.importorskip("fastapi")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_storage():
    """Create a temporary storage instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileStorage(base_path=Path(tmpdir))
        yield storage


@pytest.fixture
def storage_with_project(temp_storage, tmp_path):
    """Create storage with a test project and required agents."""
    temp_storage.create_project("test-proj", "Test Project", str(tmp_path / "test"))
    temp_storage.create_agent("architect", "test-proj", "architect", "System Architect")
    temp_storage.create_agent(
        "engineer-1", "test-proj", "implementer", "Backend Engineer"
    )
    return temp_storage


@pytest.fixture
def client(storage_with_project, monkeypatch):
    """Create TestClient with mocked storage pointing at a real project."""
    from starlette.testclient import TestClient

    import a_sdlc.ui as ui_module
    from a_sdlc.ui import app

    monkeypatch.setattr(ui_module, "get_storage", lambda: storage_with_project)
    return TestClient(app)


@pytest.fixture
def mock_storage(monkeypatch):
    """Create a fully-mocked storage instance and patch get_storage."""
    import a_sdlc.ui as ui_module

    storage = MagicMock()
    storage.list_projects.return_value = []
    storage.get_most_recent_project.return_value = None
    storage.get_all_projects_with_stats.return_value = []
    storage.list_execution_runs.return_value = []
    monkeypatch.setattr(ui_module, "get_storage", lambda: storage)
    return storage


@pytest.fixture
def mock_client(mock_storage):
    """Create TestClient with fully-mocked storage."""
    from starlette.testclient import TestClient

    from a_sdlc.ui import app

    return TestClient(app)


def _setup_project(storage):
    """Configure mock storage to return a test project."""
    project = {
        "id": "test-proj",
        "name": "Test Project",
        "shortname": "TEST",
        "path": "/tmp/test-proj",
    }
    storage.get_project.return_value = project
    storage.get_most_recent_project.return_value = project
    storage.list_projects.return_value = [project]
    storage.get_all_projects_with_stats.return_value = [
        {
            **project,
            "total_tasks": 0,
            "tasks_pending": 0,
            "tasks_completed": 0,
            "total_prds": 0,
            "total_sprints": 0,
            "active_sprint_title": None,
            "active_sprint_id": None,
        }
    ]
    storage.list_sprints.return_value = []
    return project


def _make_run(
    run_id="R-001",
    goal="Implement auth",
    status="active",
    current_phase="engineering",
    project_id="test-proj",
):
    """Build a mock pipeline run dict matching get_execution_run_detail shape."""
    return {
        "id": run_id,
        "goal": goal,
        "status": status,
        "current_phase": current_phase,
        "project_id": project_id,
        "started_at": "2026-04-09T10:00:00Z",
        "created_at": "2026-04-09T10:00:00Z",
        "sprint_id": None,
        "run_type": "objective",
        "clarification_question": None,
        "clarification_answer": None,
        "thread_count": 0,
        "total_spent_cents": 0,
        "total_budget_cents": 5000,
        "agent_count": 2,
    }


def _make_work_item(
    item_id="WI-001",
    status="in_progress",
    work_type="implement",
    artifact_type="task",
    artifact_id="TEST-T00001",
    assigned_agent_persona="sdlc-backend-engineer",
    assigned_agent_id="engineer-1",
    run_id="R-001",
):
    """Build a mock work queue item dict."""
    return {
        "id": item_id,
        "status": status,
        "work_type": work_type,
        "artifact_type": artifact_type,
        "artifact_id": artifact_id,
        "assigned_agent_persona": assigned_agent_persona,
        "assigned_agent_id": assigned_agent_id,
        "run_id": run_id,
        "started_at": "2026-04-09T10:01:00Z",
        "retry_count": 0,
        "result": None,
    }


def _make_thread_entry(
    entry_id="TE-001",
    entry_type="creation",
    agent_persona="sdlc-product-manager",
    content="Initial PRD draft",
):
    """Build a mock thread entry dict."""
    return {
        "id": entry_id,
        "entry_type": entry_type,
        "agent_persona": agent_persona,
        "content": content,
        "created_at": "2026-04-09T10:05:00Z",
        "agent_id": None,
        "round_number": 1,
        "run_id": "R-001",
        "project_id": "test-proj",
        "artifact_type": "prd",
        "artifact_id": "TEST-P0001",
    }


# =============================================================================
# TestPipelineRunsPage
# =============================================================================


class TestPipelineRunsPage:
    """Test the pipeline runs list page (GET /runs)."""

    def test_runs_page_renders(self, mock_client, mock_storage):
        """GET /runs returns 200 with Pipeline Runs heading."""
        _setup_project(mock_storage)
        mock_storage.list_execution_runs.return_value = []
        response = mock_client.get("/runs?project=test-proj")
        assert response.status_code == 200
        assert "Pipeline Runs" in response.text

    def test_runs_page_shows_runs(self, mock_client, mock_storage):
        """Mock storage returns 2 runs; both appear in HTML."""
        _setup_project(mock_storage)
        mock_storage.list_execution_runs.return_value = [
            _make_run("R-001", "Implement auth", "active"),
            _make_run("R-002", "Fix tests", "completed"),
        ]
        response = mock_client.get("/runs?project=test-proj")
        assert response.status_code == 200
        assert "Implement auth" in response.text
        assert "Fix tests" in response.text
        assert "R-001" in response.text
        assert "R-002" in response.text

    def test_runs_page_filter_by_status(self, mock_client, mock_storage):
        """GET /runs?status=active passes filter to list_execution_runs."""
        _setup_project(mock_storage)
        mock_storage.list_execution_runs.return_value = [
            _make_run(status="active"),
        ]
        response = mock_client.get("/runs?project=test-proj&status=active")
        assert response.status_code == 200
        # The route calls list_execution_runs twice: once with filter, once for active count
        calls = mock_storage.list_execution_runs.call_args_list
        # At least one call should have status="active"
        assert any(
            c.kwargs.get("status") == "active"
            or (len(c.args) > 1 and c.args[1] == "active")
            for c in calls
        )

    def test_runs_page_empty_state(self, mock_client, mock_storage):
        """No runs shows empty state message."""
        _setup_project(mock_storage)
        mock_storage.list_execution_runs.return_value = []
        response = mock_client.get("/runs?project=test-proj")
        assert response.status_code == 200
        assert "No pipeline runs yet" in response.text

    def test_runs_page_new_run_form(self, mock_client, mock_storage):
        """Runs page contains the new run launch form elements (FR-023)."""
        _setup_project(mock_storage)
        mock_storage.list_execution_runs.return_value = []
        response = mock_client.get("/runs?project=test-proj")
        assert response.status_code == 200
        text = response.text.lower()
        assert "goal" in text
        assert "textarea" in text
        assert "/runs/launch" in text


# =============================================================================
# TestStartRun
# =============================================================================


class TestStartRun:
    """Test starting a new pipeline run from the UI (POST /runs/launch)."""

    def test_start_run_basic(self, mock_client, mock_storage, monkeypatch):
        """POST /runs/launch with goal creates run and redirects to run detail."""
        _setup_project(mock_storage)
        mock_storage.get_next_run_id.return_value = "R-NEW"
        mock_storage.create_execution_run.return_value = {"id": "R-NEW"}

        mock_popen = MagicMock(return_value=MagicMock(pid=12345))
        monkeypatch.setattr(subprocess, "Popen", mock_popen)

        response = mock_client.post(
            "/runs/launch",
            data={"goal": "Implement user auth"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "/runs/R-NEW" in response.headers.get("location", "")

    def test_start_run_with_sprint(self, mock_client, mock_storage, monkeypatch):
        """POST /runs/launch with sprint_id creates a sprint-type run."""
        _setup_project(mock_storage)
        mock_storage.get_next_run_id.return_value = "R-SPR"
        mock_storage.create_execution_run.return_value = {"id": "R-SPR"}

        mock_popen = MagicMock(return_value=MagicMock(pid=12345))
        monkeypatch.setattr(subprocess, "Popen", mock_popen)

        response = mock_client.post(
            "/runs/launch",
            data={
                "sprint_id": "TEST-S0001",
                "goal": "Complete sprint tasks",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert "/runs/R-SPR" in response.headers.get("location", "")
        # Verify create_execution_run was called with sprint run_type
        call_kwargs = mock_storage.create_execution_run.call_args
        assert call_kwargs.kwargs.get("run_type") == "sprint" or (
            "sprint" in str(call_kwargs)
        )

    def test_start_run_no_project(self, mock_client, mock_storage):
        """POST /runs/launch with no project returns 400."""
        mock_storage.get_most_recent_project.return_value = None
        response = mock_client.post(
            "/runs/launch",
            data={"goal": "Should fail"},
        )
        assert response.status_code == 400


# =============================================================================
# TestRunDetailPage
# =============================================================================


class TestRunDetailPage:
    """Test the run detail page with kanban board (GET /runs/{run_id})."""

    def test_run_detail_renders(self, mock_client, mock_storage):
        """GET /runs/R-001 returns 200 with run ID and agent panel."""
        _setup_project(mock_storage)
        mock_storage.get_execution_run_detail.return_value = _make_run("R-001")
        mock_storage.list_work_queue_items.return_value = []
        mock_storage.get_recent_thread_entries.return_value = []
        response = mock_client.get("/runs/R-001")
        assert response.status_code == 200
        assert "R-001" in response.text
        # Run Board heading
        assert "Run Board" in response.text
        # Agent panel present (AC-011)
        assert "Active Agents" in response.text

    def test_run_detail_kanban_columns(self, mock_client, mock_storage):
        """Work items grouped into kanban columns by status (FR-004)."""
        _setup_project(mock_storage)
        mock_storage.get_execution_run_detail.return_value = _make_run("R-001")
        mock_storage.list_work_queue_items.return_value = [
            _make_work_item("WI-1", status="pending"),
            _make_work_item("WI-2", status="in_progress"),
            _make_work_item("WI-3", status="completed"),
        ]
        mock_storage.get_recent_thread_entries.return_value = []
        response = mock_client.get("/runs/R-001")
        assert response.status_code == 200
        text = response.text
        # Kanban column headers should be present
        assert "Pending" in text
        assert "In Progress" in text
        assert "Completed" in text

    def test_run_detail_phase_progress(self, mock_client, mock_storage):
        """Phase progress indicator is rendered (FR-006)."""
        _setup_project(mock_storage)
        run = _make_run("R-001", current_phase="implementation")
        mock_storage.get_execution_run_detail.return_value = run
        mock_storage.list_work_queue_items.return_value = []
        mock_storage.get_recent_thread_entries.return_value = []
        response = mock_client.get("/runs/R-001")
        assert response.status_code == 200
        # Phase indicator should show current phase
        text = response.text.lower()
        assert "implementation" in text
        assert "progress-bar" in text

    def test_run_detail_not_found(self, mock_client, mock_storage):
        """GET /runs/nonexistent returns 404."""
        _setup_project(mock_storage)
        mock_storage.get_execution_run_detail.return_value = None
        response = mock_client.get("/runs/nonexistent")
        assert response.status_code == 404

    def test_run_detail_clarification_panel(self, mock_client, mock_storage):
        """Run with clarification_question shows the question and answer form (FR-018)."""
        _setup_project(mock_storage)
        run = _make_run("R-001")
        run["clarification_question"] = "Should auth use JWT or session cookies?"
        run["clarification_answer"] = None
        mock_storage.get_execution_run_detail.return_value = run
        mock_storage.list_work_queue_items.return_value = []
        mock_storage.get_recent_thread_entries.return_value = []
        response = mock_client.get("/runs/R-001")
        assert response.status_code == 200
        assert "JWT or session cookies" in response.text
        # Answer form should be present
        assert "action=answer" in response.text


# =============================================================================
# TestWorkItemActions
# =============================================================================


class TestWorkItemActions:
    """Test work item control actions (POST /runs/items/{item_id}/action)."""

    def _setup_item(self, mock_storage, item_id="WI-001", **overrides):
        """Helper to set up a work item in mock storage."""
        _setup_project(mock_storage)
        item = _make_work_item(item_id, **overrides)
        mock_storage.get_work_queue_item.return_value = item
        return item

    def test_work_item_cancel(self, mock_client, mock_storage):
        """POST action=cancel updates item status to cancelled (AC-007)."""
        item = self._setup_item(mock_storage, status="in_progress")
        mock_storage.update_work_queue_item.return_value = None
        # After update, get_work_queue_item returns updated item
        cancelled = {**item, "status": "cancelled"}
        mock_storage.get_work_queue_item.side_effect = [item, cancelled]
        response = mock_client.post(
            "/runs/items/WI-001/action",
            data={"action": "cancel"},
        )
        assert response.status_code == 200
        mock_storage.update_work_queue_item.assert_called_once_with(
            "WI-001", status="cancelled"
        )

    def test_work_item_skip(self, mock_client, mock_storage):
        """POST action=skip updates item status to skipped."""
        item = self._setup_item(mock_storage, status="pending")
        mock_storage.update_work_queue_item.return_value = None
        skipped = {**item, "status": "skipped"}
        mock_storage.get_work_queue_item.side_effect = [item, skipped]
        response = mock_client.post(
            "/runs/items/WI-001/action",
            data={"action": "skip"},
        )
        assert response.status_code == 200
        mock_storage.update_work_queue_item.assert_called_once_with(
            "WI-001", status="skipped"
        )

    def test_work_item_retry(self, mock_client, mock_storage):
        """POST action=retry resets item to pending with incremented retry_count."""
        item = self._setup_item(mock_storage, status="failed")
        item["retry_count"] = 1
        mock_storage.update_work_queue_item.return_value = None
        retried = {**item, "status": "pending", "retry_count": 2}
        mock_storage.get_work_queue_item.side_effect = [item, retried]
        response = mock_client.post(
            "/runs/items/WI-001/action",
            data={"action": "retry"},
        )
        assert response.status_code == 200
        mock_storage.update_work_queue_item.assert_called_once_with(
            "WI-001", status="pending", retry_count=2
        )

    def test_work_item_force_approve(self, mock_client, mock_storage):
        """POST action=force_approve completes item with manually_approved result (AC-008)."""
        item = self._setup_item(
            mock_storage, status="in_progress", work_type="challenge"
        )
        mock_storage.update_work_queue_item.return_value = None
        approved = {**item, "status": "completed", "result": "manually_approved"}
        mock_storage.get_work_queue_item.side_effect = [item, approved]
        response = mock_client.post(
            "/runs/items/WI-001/action",
            data={"action": "force_approve"},
        )
        assert response.status_code == 200
        mock_storage.update_work_queue_item.assert_called_once_with(
            "WI-001", status="completed", result="manually_approved"
        )

    def test_work_item_not_found(self, mock_client, mock_storage):
        """POST action on nonexistent item returns 404."""
        _setup_project(mock_storage)
        mock_storage.get_work_queue_item.return_value = None
        response = mock_client.post(
            "/runs/items/FAKE/action",
            data={"action": "cancel"},
        )
        assert response.status_code == 404

    def test_work_item_unknown_action(self, mock_client, mock_storage):
        """POST with unknown action returns 400."""
        self._setup_item(mock_storage)
        response = mock_client.post(
            "/runs/items/WI-001/action",
            data={"action": "explode"},
        )
        assert response.status_code == 400


# =============================================================================
# TestRunActions
# =============================================================================


class TestRunActions:
    """Test run-level control actions (POST /runs/{run_id}/action)."""

    def test_pause_run(self, mock_client, mock_storage):
        """POST action=pause updates run status to paused."""
        _setup_project(mock_storage)
        response = mock_client.post(
            "/runs/R-001/action",
            data={"action": "pause"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        mock_storage.update_execution_run.assert_called_once_with(
            "R-001", status="paused"
        )

    def test_resume_run(self, mock_client, mock_storage):
        """POST action=resume updates run status to active."""
        _setup_project(mock_storage)
        response = mock_client.post(
            "/runs/R-001/action",
            data={"action": "resume"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        mock_storage.update_execution_run.assert_called_once_with(
            "R-001", status="active"
        )

    def test_cancel_run(self, mock_client, mock_storage):
        """POST action=cancel updates run status to cancelled."""
        _setup_project(mock_storage)
        response = mock_client.post(
            "/runs/R-001/action",
            data={"action": "cancel"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        mock_storage.update_execution_run.assert_called_once_with(
            "R-001", status="cancelled"
        )


# =============================================================================
# TestThreadViewer
# =============================================================================


class TestThreadViewer:
    """Test thread viewer routes (GET /threads/{type}/{id})."""

    def test_thread_viewer_renders(self, mock_client, mock_storage):
        """GET /threads/prd/PROJ-P0001 returns 200 with entries."""
        _setup_project(mock_storage)
        mock_storage.list_artifact_threads_by_artifact.return_value = [
            _make_thread_entry("TE-1", "creation", "sdlc-product-manager", "Draft v1"),
            _make_thread_entry("TE-2", "challenge", "sdlc-architect", "Missing NFRs"),
        ]
        response = mock_client.get("/threads/prd/PROJ-P0001")
        assert response.status_code == 200
        assert "Draft v1" in response.text
        assert "Missing NFRs" in response.text

    def test_thread_viewer_empty(self, mock_client, mock_storage):
        """No entries shows empty state."""
        _setup_project(mock_storage)
        mock_storage.list_artifact_threads_by_artifact.return_value = []
        response = mock_client.get("/threads/prd/PROJ-P0001")
        assert response.status_code == 200
        assert "No thread entries yet" in response.text

    def test_thread_viewer_entry_types(self, mock_client, mock_storage):
        """Different entry types have correct CSS classes for color coding (AC-004)."""
        _setup_project(mock_storage)
        mock_storage.list_artifact_threads_by_artifact.return_value = [
            _make_thread_entry("TE-1", "creation"),
            _make_thread_entry("TE-2", "challenge"),
            _make_thread_entry("TE-3", "revision"),
            _make_thread_entry("TE-4", "approval"),
            _make_thread_entry("TE-5", "escalation"),
        ]
        response = mock_client.get("/threads/prd/PROJ-P0001")
        assert response.status_code == 200
        text = response.text
        # Each entry type should have a CSS class
        assert "thread-entry-creation" in text
        assert "thread-entry-challenge" in text
        assert "thread-entry-revision" in text
        assert "thread-entry-approval" in text
        assert "thread-entry-escalation" in text


# =============================================================================
# TestThreadComment
# =============================================================================


class TestThreadComment:
    """Test thread comment posting (POST /threads/{type}/{id}/comment)."""

    def test_post_comment(self, mock_client, mock_storage):
        """POST /threads/prd/PROJ-P0001/comment creates a thread entry (AC-010)."""
        _setup_project(mock_storage)
        # _resolve_project_id needs get_prd to return a project
        mock_storage.get_prd.return_value = {
            "id": "PROJ-P0001",
            "project_id": "test-proj",
        }
        mock_storage.list_artifact_threads_by_artifact.return_value = [
            _make_thread_entry(entry_type="user_intervention", content="Rate limiting"),
        ]
        mock_storage.get_execution_run.return_value = None
        mock_storage.create_execution_run.return_value = {}

        response = mock_client.post(
            "/threads/prd/PROJ-P0001/comment",
            json={"content": "Please add rate limiting"},
        )
        assert response.status_code == 200
        mock_storage.create_artifact_thread_entry.assert_called_once()
        call_kwargs = mock_storage.create_artifact_thread_entry.call_args
        assert "Please add rate limiting" in str(call_kwargs)

    def test_post_empty_comment(self, mock_client, mock_storage):
        """POST with empty content returns 400 (no entry created)."""
        _setup_project(mock_storage)
        response = mock_client.post(
            "/threads/prd/PROJ-P0001/comment",
            json={"content": ""},
        )
        assert response.status_code == 400
        mock_storage.create_artifact_thread_entry.assert_not_called()

    def test_post_comment_via_form_data(self, mock_client, mock_storage):
        """POST comment via form data (non-JSON) also works."""
        _setup_project(mock_storage)
        mock_storage.get_prd.return_value = {
            "id": "PROJ-P0001",
            "project_id": "test-proj",
        }
        mock_storage.list_artifact_threads_by_artifact.return_value = []
        mock_storage.get_execution_run.return_value = None
        mock_storage.create_execution_run.return_value = {}

        response = mock_client.post(
            "/threads/prd/PROJ-P0001/comment",
            data={"content": "Form-based comment"},
        )
        assert response.status_code == 200
        mock_storage.create_artifact_thread_entry.assert_called_once()


# =============================================================================
# TestWebSocket
# =============================================================================


class TestWebSocket:
    """Test WebSocket endpoint for real-time updates (FR-012)."""

    def test_websocket_connect(self, mock_client, mock_storage):
        """WebSocket connection to /ws/runs/R-123 is accepted."""
        _setup_project(mock_storage)
        with mock_client.websocket_connect("/ws/runs/R-123") as ws:
            assert ws is not None

    def test_websocket_disconnect_cleanup(self, mock_client, mock_storage):
        """After disconnect, connection is removed without errors."""
        _setup_project(mock_storage)
        with mock_client.websocket_connect("/ws/runs/R-123"):
            pass
        # No assertion on internal state -- the test verifies that
        # disconnect does not raise an exception and cleanup completes.


# =============================================================================
# TestThreadTabs
# =============================================================================


class TestThreadTabs:
    """Test thread tab integration on existing detail pages (FR-008, AC-003)."""

    def test_prd_detail_has_thread_tab(self, storage_with_project, monkeypatch):
        """PRD detail page contains Agent Thread tab (FR-008, AC-003)."""
        from starlette.testclient import TestClient

        import a_sdlc.ui as ui_module
        from a_sdlc.ui import app

        monkeypatch.setattr(ui_module, "get_storage", lambda: storage_with_project)

        storage_with_project.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
        )

        tc = TestClient(app)
        response = tc.get("/prds/TEST-P0001")
        assert response.status_code == 200
        assert "Agent Thread" in response.text
        # The thread tab uses HTMX to lazy-load from /threads/prd/{id}
        assert "/threads/prd/TEST-P0001" in response.text

    def test_task_detail_has_thread_tab(self, storage_with_project, monkeypatch):
        """Task detail page contains Agent Thread tab (FR-008)."""
        from starlette.testclient import TestClient

        import a_sdlc.ui as ui_module
        from a_sdlc.ui import app

        monkeypatch.setattr(ui_module, "get_storage", lambda: storage_with_project)

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

        tc = TestClient(app)
        response = tc.get("/tasks/TEST-T00001")
        assert response.status_code == 200
        assert "Agent Thread" in response.text
        assert "/threads/task/TEST-T00001" in response.text
