"""Tests for MCP server tools."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_project_dir():
    """Create a temporary project directory with optional artifacts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def _make_project(path: str) -> dict:
    """Create a minimal project dict."""
    return {
        "id": "test-project",
        "shortname": "TEST",
        "name": "Test Project",
        "path": path,
    }


def _setup_mocks(mock_db, project_path: str):
    """Configure common mock returns for get_context()."""
    project = _make_project(project_path)
    mock_db.get_project.return_value = project
    mock_db.list_tasks.return_value = []
    mock_db.list_sprints.return_value = []
    mock_db.list_prds.return_value = []
    mock_db.get_project_by_path.return_value = project
    mock_db.update_project_accessed.return_value = None


class TestGetContextArtifacts:
    """Test artifact detection in get_context()."""

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_no_artifacts_directory(self, mock_getcwd, mock_get_db, mock_project_dir):
        """When .sdlc/artifacts/ doesn't exist, scan_status is 'not_scanned'."""
        from a_sdlc.server import get_context

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_mocks(mock_db, str(mock_project_dir))

        result = get_context()

        assert result["status"] == "ok"
        assert result["artifacts"]["scan_status"] == "not_scanned"
        assert result["artifacts"]["available"] == []

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_partial_artifacts(self, mock_getcwd, mock_get_db, mock_project_dir):
        """When some artifacts exist, scan_status is 'partial'."""
        from a_sdlc.server import get_context

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_mocks(mock_db, str(mock_project_dir))

        # Create artifacts directory with 2 of 5 artifacts
        artifacts_dir = mock_project_dir / ".sdlc" / "artifacts"
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "architecture.md").write_text("# Architecture")
        (artifacts_dir / "data-model.md").write_text("# Data Model")

        result = get_context()

        assert result["status"] == "ok"
        assert result["artifacts"]["scan_status"] == "partial"
        assert sorted(result["artifacts"]["available"]) == ["architecture", "data-model"]

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_complete_artifacts(self, mock_getcwd, mock_get_db, mock_project_dir):
        """When all 5 artifacts exist, scan_status is 'complete'."""
        from a_sdlc.server import get_context

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_mocks(mock_db, str(mock_project_dir))

        # Create artifacts directory with all 5 artifacts
        artifacts_dir = mock_project_dir / ".sdlc" / "artifacts"
        artifacts_dir.mkdir(parents=True)
        for name in [
            "architecture",
            "codebase-summary",
            "data-model",
            "directory-structure",
            "key-workflows",
        ]:
            (artifacts_dir / f"{name}.md").write_text(f"# {name}")

        result = get_context()

        assert result["status"] == "ok"
        assert result["artifacts"]["scan_status"] == "complete"
        assert len(result["artifacts"]["available"]) == 5
        assert "architecture" in result["artifacts"]["available"]
        assert "codebase-summary" in result["artifacts"]["available"]
        assert "data-model" in result["artifacts"]["available"]
        assert "directory-structure" in result["artifacts"]["available"]
        assert "key-workflows" in result["artifacts"]["available"]


# =============================================================================
# get_sprint_tasks — group_by_prd parameter
# =============================================================================


class TestGetSprintTasksGroupByPrd:
    """Test get_sprint_tasks with group_by_prd parameter."""

    def _make_sprint(self):
        return {
            "id": "TEST-S0001",
            "project_id": "test-project",
            "title": "Sprint 1",
            "status": "active",
        }

    def _make_tasks(self):
        return [
            {"id": "TEST-T00001", "title": "Task 1", "status": "pending", "priority": "high", "prd_id": "TEST-P0001", "updated_at": "2026-01-01"},
            {"id": "TEST-T00002", "title": "Task 2", "status": "pending", "priority": "medium", "prd_id": "TEST-P0001", "updated_at": "2026-01-01"},
            {"id": "TEST-T00003", "title": "Task 3", "status": "pending", "priority": "high", "prd_id": "TEST-P0002", "updated_at": "2026-01-01"},
        ]

    def _make_prds(self):
        return [
            {"id": "TEST-P0001", "title": "Auth Feature", "status": "split", "version": "1"},
            {"id": "TEST-P0002", "title": "User Profile", "status": "split", "version": "1"},
        ]

    @patch("a_sdlc.server.get_db")
    def test_flat_list_by_default(self, mock_get_db):
        """Without group_by_prd, returns flat task list."""
        from a_sdlc.server import get_sprint_tasks

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_sprint.return_value = self._make_sprint()
        mock_db.list_tasks_by_sprint.return_value = self._make_tasks()

        result = get_sprint_tasks("TEST-S0001")

        assert result["status"] == "ok"
        assert "tasks" in result
        assert "prd_groups" not in result
        assert result["count"] == 3

    @patch("a_sdlc.server.get_db")
    def test_group_by_prd_true(self, mock_get_db):
        """With group_by_prd=True, returns tasks grouped by PRD."""
        from a_sdlc.server import get_sprint_tasks

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_sprint.return_value = self._make_sprint()
        mock_db.list_tasks_by_sprint.return_value = self._make_tasks()
        mock_db.get_sprint_prds.return_value = self._make_prds()

        result = get_sprint_tasks("TEST-S0001", group_by_prd=True)

        assert result["status"] == "ok"
        assert "prd_groups" in result
        assert "tasks" not in result
        assert result["count"] == 3

        # Verify grouping
        groups = {g["prd_id"]: g for g in result["prd_groups"]}
        assert "TEST-P0001" in groups
        assert "TEST-P0002" in groups
        assert len(groups["TEST-P0001"]["tasks"]) == 2
        assert len(groups["TEST-P0002"]["tasks"]) == 1
        assert groups["TEST-P0001"]["prd_title"] == "Auth Feature"
        assert groups["TEST-P0002"]["prd_title"] == "User Profile"

    @patch("a_sdlc.server.get_db")
    def test_group_by_prd_sprint_not_found(self, mock_get_db):
        """Returns not_found when sprint doesn't exist."""
        from a_sdlc.server import get_sprint_tasks

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_sprint.return_value = None

        result = get_sprint_tasks("NONEXISTENT", group_by_prd=True)

        assert result["status"] == "not_found"

    @patch("a_sdlc.server.get_db")
    def test_group_by_prd_empty_sprint(self, mock_get_db):
        """Returns empty groups for sprint with no tasks."""
        from a_sdlc.server import get_sprint_tasks

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_sprint.return_value = self._make_sprint()
        mock_db.list_tasks_by_sprint.return_value = []
        mock_db.get_sprint_prds.return_value = []

        result = get_sprint_tasks("TEST-S0001", group_by_prd=True)

        assert result["status"] == "ok"
        assert result["prd_groups"] == []
        assert result["count"] == 0


# =============================================================================
# setup_prd_worktree
# =============================================================================


class TestSetupPrdWorktree:
    """Test setup_prd_worktree MCP tool."""

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_creates_worktree_successfully(
        self, mock_getcwd, mock_get_db, mock_get_pid, mock_run, tmp_path
    ):
        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_get_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project.return_value = {"shortname": "TEST"}

        # Create .gitignore so _ensure_gitignore_entry can work
        (tmp_path / ".gitignore").write_text("")

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = setup_prd_worktree(
            prd_id="TEST-P0001",
            sprint_id="TEST-S0001",
            port_offset=0,
        )

        assert result["status"] == "created"
        assert result["worktree"]["prd_id"] == "TEST-P0001"
        assert result["worktree"]["branch"] == "sprint/TEST-S0001/TEST-P0001"
        assert result["worktree"]["port_offset"] == 0
        assert result["worktree"]["compose_name"] == "test-test-p0001"

        # Verify git commands were called
        assert mock_run.call_count == 2  # git branch + git worktree add

        # Verify state file was written (env file is in the worktree created by git)
        state_path = tmp_path / ".worktrees" / ".state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert "TEST-P0001" in state["worktrees"]
        assert state["worktrees"]["TEST-P0001"]["status"] == "active"
        assert state["sprint_id"] == "TEST-S0001"

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_returns_exists_if_already_setup(
        self, mock_getcwd, mock_get_db, mock_get_pid, mock_run, tmp_path
    ):
        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)

        # Pre-create worktree state and directory
        worktree_path = tmp_path / ".worktrees" / "TEST-P0001"
        worktree_path.mkdir(parents=True)
        state_path = tmp_path / ".worktrees" / ".state.json"
        state_path.write_text(json.dumps({
            "sprint_id": "TEST-S0001",
            "created_at": "2026-01-01T00:00:00+00:00",
            "worktrees": {
                "TEST-P0001": {
                    "branch": "sprint/TEST-S0001/TEST-P0001",
                    "path": str(worktree_path),
                    "port_offset": 0,
                    "compose_name": "test-test-p0001",
                    "status": "active",
                    "pr_url": None,
                },
            },
        }))

        result = setup_prd_worktree(
            prd_id="TEST-P0001",
            sprint_id="TEST-S0001",
        )

        assert result["status"] == "exists"
        # Should not call git at all
        mock_run.assert_not_called()

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_handles_branch_already_exists(
        self, mock_getcwd, mock_get_db, mock_get_pid, mock_run, tmp_path
    ):
        """If branch already exists (resume), should proceed to worktree add."""
        import subprocess as sp

        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_get_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project.return_value = {"shortname": "TEST"}
        (tmp_path / ".gitignore").write_text("")

        # First call (git branch) fails with "already exists"
        # Second call (git worktree add) succeeds
        branch_error = sp.CalledProcessError(128, "git", stderr="already exists")
        mock_run.side_effect = [branch_error, MagicMock(returncode=0)]

        result = setup_prd_worktree(
            prd_id="TEST-P0001",
            sprint_id="TEST-S0001",
        )

        assert result["status"] == "created"
        assert mock_run.call_count == 2

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_gitignore_entry_added(
        self, mock_getcwd, mock_get_db, mock_get_pid, mock_run, tmp_path
    ):
        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_get_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project.return_value = {"shortname": "TEST"}
        (tmp_path / ".gitignore").write_text("node_modules/\n")
        mock_run.return_value = MagicMock(returncode=0)

        setup_prd_worktree(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        gitignore_content = (tmp_path / ".gitignore").read_text()
        assert ".worktrees/" in gitignore_content
        assert "node_modules/" in gitignore_content


# =============================================================================
# cleanup_prd_worktree
# =============================================================================


class TestCleanupPrdWorktree:
    """Test cleanup_prd_worktree MCP tool."""

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_removes_worktree(self, mock_getcwd, mock_run, tmp_path):
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)

        # Create state file
        worktree_path = tmp_path / ".worktrees" / "TEST-P0001"
        worktree_path.mkdir(parents=True)
        state = {
            "sprint_id": "TEST-S0001",
            "created_at": "2026-01-01T00:00:00+00:00",
            "worktrees": {
                "TEST-P0001": {
                    "branch": "sprint/TEST-S0001/TEST-P0001",
                    "path": str(worktree_path),
                    "port_offset": 0,
                    "compose_name": "test-test-p0001",
                    "status": "active",
                    "pr_url": None,
                },
            },
        }
        state_path = tmp_path / ".worktrees" / ".state.json"
        state_path.write_text(json.dumps(state))

        mock_run.return_value = MagicMock(returncode=0)

        result = cleanup_prd_worktree(prd_id="TEST-P0001", docker_cleanup=False)

        assert result["status"] == "cleaned"
        assert result["branch_removed"] is False

        # Verify git worktree remove was called
        git_calls = [c for c in mock_run.call_args_list if "worktree" in str(c)]
        assert len(git_calls) == 1

        # State should be updated
        updated_state = json.loads(state_path.read_text())
        assert updated_state["worktrees"]["TEST-P0001"]["status"] == "removed"

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_with_branch_removal(self, mock_getcwd, mock_run, tmp_path):
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)

        worktree_path = tmp_path / ".worktrees" / "TEST-P0001"
        worktree_path.mkdir(parents=True)
        state_path = tmp_path / ".worktrees" / ".state.json"
        state_path.write_text(json.dumps({
            "sprint_id": "TEST-S0001",
            "created_at": "2026-01-01",
            "worktrees": {
                "TEST-P0001": {
                    "branch": "sprint/TEST-S0001/TEST-P0001",
                    "path": str(worktree_path),
                    "port_offset": 0,
                    "compose_name": "test-test-p0001",
                    "status": "active",
                    "pr_url": None,
                },
            },
        }))

        mock_run.return_value = MagicMock(returncode=0)

        result = cleanup_prd_worktree(
            prd_id="TEST-P0001",
            remove_branch=True,
            docker_cleanup=False,
        )

        assert result["status"] == "cleaned"
        assert result["branch_removed"] is True

        # Verify git branch -D was called
        branch_calls = [c for c in mock_run.call_args_list if "branch" in str(c)]
        assert len(branch_calls) >= 1

    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_not_found(self, mock_getcwd, tmp_path):
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)

        result = cleanup_prd_worktree(prd_id="NONEXISTENT")

        assert result["status"] == "not_found"

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_with_docker(self, mock_getcwd, mock_run, tmp_path):
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)

        worktree_path = tmp_path / ".worktrees" / "TEST-P0001"
        worktree_path.mkdir(parents=True)
        state_path = tmp_path / ".worktrees" / ".state.json"
        state_path.write_text(json.dumps({
            "sprint_id": "TEST-S0001",
            "created_at": "2026-01-01",
            "worktrees": {
                "TEST-P0001": {
                    "branch": "sprint/TEST-S0001/TEST-P0001",
                    "path": str(worktree_path),
                    "port_offset": 0,
                    "compose_name": "test-test-p0001",
                    "status": "active",
                    "pr_url": None,
                },
            },
        }))

        mock_run.return_value = MagicMock(returncode=0)

        result = cleanup_prd_worktree(prd_id="TEST-P0001", docker_cleanup=True)

        assert result["status"] == "cleaned"
        assert result["docker_cleaned"] is True

        # Docker compose down should have been called
        docker_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "docker"]
        assert len(docker_calls) == 1


# =============================================================================
# create_prd_pr
# =============================================================================


class TestCreatePrdPr:
    """Test create_prd_pr MCP tool."""

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_creates_pr_successfully(self, mock_getcwd, mock_get_db, mock_run, tmp_path):
        from a_sdlc.server import create_prd_pr

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_prd.return_value = {"title": "Auth Feature"}

        # Setup state file
        state_path = tmp_path / ".worktrees" / ".state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            "sprint_id": "TEST-S0001",
            "created_at": "2026-01-01",
            "worktrees": {
                "TEST-P0001": {
                    "branch": "sprint/TEST-S0001/TEST-P0001",
                    "path": str(tmp_path / ".worktrees" / "TEST-P0001"),
                    "port_offset": 0,
                    "compose_name": "test-test-p0001",
                    "status": "active",
                    "pr_url": None,
                },
            },
        }))

        # git push succeeds, gh pr create returns URL
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="", stderr=""),  # git push
            MagicMock(returncode=0, stdout="https://github.com/org/repo/pull/42\n", stderr=""),  # gh pr create
        ]

        result = create_prd_pr(
            prd_id="TEST-P0001",
            sprint_id="TEST-S0001",
        )

        assert result["status"] == "created"
        assert result["pr_url"] == "https://github.com/org/repo/pull/42"
        assert result["branch"] == "sprint/TEST-S0001/TEST-P0001"
        assert "Auth Feature" in result["title"]

        # Verify state updated with PR URL
        updated_state = json.loads(state_path.read_text())
        assert updated_state["worktrees"]["TEST-P0001"]["pr_url"] == "https://github.com/org/repo/pull/42"
        assert updated_state["worktrees"]["TEST-P0001"]["status"] == "pr_created"

    @patch("a_sdlc.server.os.getcwd")
    def test_pr_no_worktree(self, mock_getcwd, tmp_path):
        from a_sdlc.server import create_prd_pr

        mock_getcwd.return_value = str(tmp_path)

        result = create_prd_pr(prd_id="NONEXISTENT", sprint_id="TEST-S0001")

        assert result["status"] == "not_found"

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_push_failure(self, mock_getcwd, mock_get_db, mock_run, tmp_path):
        import subprocess as sp

        from a_sdlc.server import create_prd_pr

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_prd.return_value = {"title": "Auth Feature"}

        state_path = tmp_path / ".worktrees" / ".state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            "sprint_id": "TEST-S0001",
            "created_at": "2026-01-01",
            "worktrees": {
                "TEST-P0001": {
                    "branch": "sprint/TEST-S0001/TEST-P0001",
                    "path": str(tmp_path / ".worktrees" / "TEST-P0001"),
                    "port_offset": 0,
                    "compose_name": "test-test-p0001",
                    "status": "active",
                    "pr_url": None,
                },
            },
        }))

        mock_run.side_effect = sp.CalledProcessError(1, "git", stderr="remote rejected")

        result = create_prd_pr(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        assert result["status"] == "error"
        assert "push" in result["message"].lower()

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_custom_title_and_body(self, mock_getcwd, mock_get_db, mock_run, tmp_path):
        from a_sdlc.server import create_prd_pr

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_prd.return_value = {"title": "Auth Feature"}

        state_path = tmp_path / ".worktrees" / ".state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            "sprint_id": "TEST-S0001",
            "created_at": "2026-01-01",
            "worktrees": {
                "TEST-P0001": {
                    "branch": "sprint/TEST-S0001/TEST-P0001",
                    "path": str(tmp_path / ".worktrees" / "TEST-P0001"),
                    "port_offset": 0,
                    "compose_name": "test-test-p0001",
                    "status": "active",
                    "pr_url": None,
                },
            },
        }))

        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout="https://github.com/org/repo/pull/99\n"),
        ]

        result = create_prd_pr(
            prd_id="TEST-P0001",
            sprint_id="TEST-S0001",
            title="Custom PR Title",
            body="Custom body text",
        )

        assert result["status"] == "created"
        assert result["title"] == "Custom PR Title"


# =============================================================================
# Worktree state helpers
# =============================================================================


class TestWorktreeStateHelpers:
    """Test _load_worktree_state and _save_worktree_state."""

    @patch("a_sdlc.server.os.getcwd")
    def test_load_empty_state(self, mock_getcwd, tmp_path):
        from a_sdlc.server import _load_worktree_state

        mock_getcwd.return_value = str(tmp_path)

        state = _load_worktree_state()

        assert state["sprint_id"] is None
        assert state["worktrees"] == {}

    @patch("a_sdlc.server.os.getcwd")
    def test_load_existing_state(self, mock_getcwd, tmp_path):
        from a_sdlc.server import _load_worktree_state

        mock_getcwd.return_value = str(tmp_path)

        state_path = tmp_path / ".worktrees" / ".state.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(json.dumps({
            "sprint_id": "TEST-S0001",
            "created_at": "2026-01-01",
            "worktrees": {"TEST-P0001": {"status": "active"}},
        }))

        state = _load_worktree_state()

        assert state["sprint_id"] == "TEST-S0001"
        assert "TEST-P0001" in state["worktrees"]

    @patch("a_sdlc.server.os.getcwd")
    def test_save_creates_directory(self, mock_getcwd, tmp_path):
        from a_sdlc.server import _save_worktree_state

        mock_getcwd.return_value = str(tmp_path)

        state = {
            "sprint_id": "TEST-S0001",
            "created_at": "2026-01-01",
            "worktrees": {"TEST-P0001": {"status": "active"}},
        }
        _save_worktree_state(state)

        state_path = tmp_path / ".worktrees" / ".state.json"
        assert state_path.exists()
        loaded = json.loads(state_path.read_text())
        assert loaded["sprint_id"] == "TEST-S0001"

    @patch("a_sdlc.server.os.getcwd")
    def test_roundtrip(self, mock_getcwd, tmp_path):
        from a_sdlc.server import _load_worktree_state, _save_worktree_state

        mock_getcwd.return_value = str(tmp_path)

        state = {
            "sprint_id": "TEST-S0001",
            "created_at": "2026-02-06T12:00:00+00:00",
            "worktrees": {
                "TEST-P0001": {
                    "branch": "sprint/TEST-S0001/TEST-P0001",
                    "path": "/tmp/test/.worktrees/TEST-P0001",
                    "port_offset": 0,
                    "status": "active",
                    "pr_url": None,
                },
                "TEST-P0002": {
                    "branch": "sprint/TEST-S0001/TEST-P0002",
                    "path": "/tmp/test/.worktrees/TEST-P0002",
                    "port_offset": 100,
                    "status": "completed",
                    "pr_url": "https://github.com/org/repo/pull/42",
                },
            },
        }
        _save_worktree_state(state)
        loaded = _load_worktree_state()

        assert loaded == state


# =============================================================================
# _ensure_gitignore_entry
# =============================================================================


class TestEnsureGitignoreEntry:
    """Test _ensure_gitignore_entry helper."""

    def test_creates_gitignore_if_missing(self, tmp_path):
        from a_sdlc.server import _ensure_gitignore_entry

        _ensure_gitignore_entry(tmp_path, ".worktrees/")

        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert ".worktrees/" in gitignore.read_text()

    def test_appends_to_existing_gitignore(self, tmp_path):
        from a_sdlc.server import _ensure_gitignore_entry

        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/\n.env\n")

        _ensure_gitignore_entry(tmp_path, ".worktrees/")

        content = gitignore.read_text()
        assert "node_modules/" in content
        assert ".env" in content
        assert ".worktrees/" in content

    def test_does_not_duplicate_entry(self, tmp_path):
        from a_sdlc.server import _ensure_gitignore_entry

        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".worktrees/\n")

        _ensure_gitignore_entry(tmp_path, ".worktrees/")

        content = gitignore.read_text()
        assert content.count(".worktrees/") == 1

    def test_handles_no_trailing_newline(self, tmp_path):
        from a_sdlc.server import _ensure_gitignore_entry

        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/")  # no trailing newline

        _ensure_gitignore_entry(tmp_path, ".worktrees/")

        content = gitignore.read_text()
        assert content == "node_modules/\n.worktrees/\n"
