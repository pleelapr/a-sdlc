"""Tests for MCP server tools."""

import subprocess
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
# get_context — config.yaml auto-creation
# =============================================================================


class TestGetContextConfigAutoCreate:
    """Test that get_context() auto-creates .sdlc/config.yaml when missing."""

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_creates_config_yaml_when_missing(self, mock_getcwd, mock_get_db, mock_project_dir):
        """When project exists but config.yaml is missing, get_context() creates it."""
        from a_sdlc.server import get_context

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_mocks(mock_db, str(mock_project_dir))

        # No config.yaml exists initially
        assert not (mock_project_dir / ".sdlc" / "config.yaml").exists()

        result = get_context()

        assert result["status"] == "ok"
        config_path = mock_project_dir / ".sdlc" / "config.yaml"
        assert config_path.exists()
        content = config_path.read_text()
        assert "testing:" in content
        assert "review:" in content
        assert "git:" in content

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_does_not_overwrite_existing_config(self, mock_getcwd, mock_get_db, mock_project_dir):
        """When config.yaml already exists, get_context() leaves it alone."""
        from a_sdlc.server import get_context

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_mocks(mock_db, str(mock_project_dir))

        # Create pre-existing config.yaml
        sdlc_dir = mock_project_dir / ".sdlc"
        sdlc_dir.mkdir(parents=True)
        config_path = sdlc_dir / "config.yaml"
        config_path.write_text("custom: true")

        result = get_context()

        assert result["status"] == "ok"
        assert config_path.read_text() == "custom: true"


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
# complete_sprint — auto-complete PRDs
# =============================================================================


class TestCompleteSprintPrdCascade:
    """Test that complete_sprint auto-completes PRDs with all tasks done."""

    @patch("a_sdlc.server.get_db")
    def test_completes_prds_with_all_tasks_done(self, mock_get_db):
        """PRDs in 'split' status are completed when all tasks are done."""
        from a_sdlc.server import complete_sprint

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_sprint.return_value = {
            "id": "TEST-S0001",
            "project_id": "test-project",
            "status": "active",
        }
        mock_db.list_tasks_by_sprint.return_value = [
            {"status": "completed"},
            {"status": "completed"},
        ]
        mock_db.get_sprint_prds.return_value = [
            {"id": "TEST-P0001", "project_id": "test-project", "status": "split"},
        ]
        mock_db.list_tasks.return_value = [
            {"status": "completed"},
            {"status": "completed"},
        ]
        mock_db.update_sprint.return_value = {"id": "TEST-S0001", "status": "completed"}

        result = complete_sprint("TEST-S0001")

        assert result["status"] == "completed"
        assert "TEST-P0001" in result["statistics"]["prds_completed"]
        mock_db.update_prd.assert_called_once_with("TEST-P0001", status="completed")

    @patch("a_sdlc.server.get_db")
    def test_skips_prds_with_incomplete_tasks(self, mock_get_db):
        """PRDs with incomplete tasks are not auto-completed."""
        from a_sdlc.server import complete_sprint

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_sprint.return_value = {
            "id": "TEST-S0001",
            "project_id": "test-project",
            "status": "active",
        }
        mock_db.list_tasks_by_sprint.return_value = [
            {"status": "completed"},
            {"status": "in_progress"},
        ]
        mock_db.get_sprint_prds.return_value = [
            {"id": "TEST-P0001", "project_id": "test-project", "status": "split"},
        ]
        mock_db.list_tasks.return_value = [
            {"status": "completed"},
            {"status": "in_progress"},
        ]
        mock_db.update_sprint.return_value = {"id": "TEST-S0001", "status": "completed"}

        result = complete_sprint("TEST-S0001")

        assert result["statistics"]["prds_completed"] == []
        mock_db.update_prd.assert_not_called()

    @patch("a_sdlc.server.get_db")
    def test_skips_prds_not_in_split_status(self, mock_get_db):
        """PRDs not in 'split' status are not touched."""
        from a_sdlc.server import complete_sprint

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_sprint.return_value = {
            "id": "TEST-S0001",
            "project_id": "test-project",
            "status": "active",
        }
        mock_db.list_tasks_by_sprint.return_value = []
        mock_db.get_sprint_prds.return_value = [
            {"id": "TEST-P0001", "project_id": "test-project", "status": "draft"},
        ]
        mock_db.update_sprint.return_value = {"id": "TEST-S0001", "status": "completed"}

        result = complete_sprint("TEST-S0001")

        assert result["statistics"]["prds_completed"] == []
        mock_db.update_prd.assert_not_called()

    @patch("a_sdlc.server.get_db")
    def test_skips_prds_with_no_tasks(self, mock_get_db):
        """PRDs with zero tasks are not auto-completed."""
        from a_sdlc.server import complete_sprint

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_sprint.return_value = {
            "id": "TEST-S0001",
            "project_id": "test-project",
            "status": "active",
        }
        mock_db.list_tasks_by_sprint.return_value = []
        mock_db.get_sprint_prds.return_value = [
            {"id": "TEST-P0001", "project_id": "test-project", "status": "split"},
        ]
        mock_db.list_tasks.return_value = []
        mock_db.update_sprint.return_value = {"id": "TEST-S0001", "status": "completed"}

        result = complete_sprint("TEST-S0001")

        assert result["statistics"]["prds_completed"] == []
        mock_db.update_prd.assert_not_called()


# =============================================================================
# setup_prd_worktree
# =============================================================================


class TestSetupPrdWorktree:
    """Test setup_prd_worktree MCP tool."""

    def _enabled_git_config(self):
        """Return a GitSafetyConfig with worktree_enabled=True."""
        from a_sdlc.core.git_config import GitSafetyConfig
        return GitSafetyConfig(worktree_enabled=True)

    def _make_worktree_record(self, tmp_path, prd_id="TEST-P0001"):
        """Return a DB-style worktree dict."""
        return {
            "id": "TEST-W0001",
            "project_id": "test-project",
            "prd_id": prd_id,
            "sprint_id": "TEST-S0001",
            "branch_name": f"sprint/TEST-S0001/{prd_id}",
            "path": str(tmp_path / ".worktrees" / prd_id),
            "status": "active",
            "created_at": "2026-01-01T00:00:00+00:00",
            "cleaned_at": None,
        }

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_creates_worktree_successfully(
        self, mock_getcwd, mock_get_db, mock_get_pid, mock_run, mock_git_config, tmp_path
    ):
        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_get_pid.return_value = "test-project"
        mock_git_config.return_value = self._enabled_git_config()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project.return_value = {"shortname": "TEST"}
        mock_db.get_worktree_by_prd.return_value = None
        mock_db.get_next_worktree_id.return_value = "TEST-W0001"

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
        assert result["worktree"]["id"] == "TEST-W0001"

        # Verify git commands were called
        assert mock_run.call_count == 2  # git branch + git worktree add

        # Verify worktree was recorded in database
        mock_db.create_worktree.assert_called_once_with(
            worktree_id="TEST-W0001",
            project_id="test-project",
            prd_id="TEST-P0001",
            branch_name="sprint/TEST-S0001/TEST-P0001",
            path=str(tmp_path / ".worktrees" / "TEST-P0001"),
            sprint_id="TEST-S0001",
            status="active",
        )

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_returns_exists_if_already_setup(
        self, mock_getcwd, mock_get_db, mock_get_pid, mock_run, mock_git_config, tmp_path
    ):
        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_get_pid.return_value = "test-project"
        mock_git_config.return_value = self._enabled_git_config()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project.return_value = {"shortname": "TEST"}

        # Pre-create worktree directory and DB record
        worktree_path = tmp_path / ".worktrees" / "TEST-P0001"
        worktree_path.mkdir(parents=True)
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        result = setup_prd_worktree(
            prd_id="TEST-P0001",
            sprint_id="TEST-S0001",
        )

        assert result["status"] == "exists"
        # Should not call git at all
        mock_run.assert_not_called()

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_handles_branch_already_exists(
        self, mock_getcwd, mock_get_db, mock_get_pid, mock_run, mock_git_config, tmp_path
    ):
        """If branch already exists (resume), should proceed to worktree add."""
        import subprocess as sp

        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_get_pid.return_value = "test-project"
        mock_git_config.return_value = self._enabled_git_config()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project.return_value = {"shortname": "TEST"}
        mock_db.get_worktree_by_prd.return_value = None
        mock_db.get_next_worktree_id.return_value = "TEST-W0001"
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

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_gitignore_entry_added(
        self, mock_getcwd, mock_get_db, mock_get_pid, mock_run, mock_git_config, tmp_path
    ):
        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_get_pid.return_value = "test-project"
        mock_git_config.return_value = self._enabled_git_config()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project.return_value = {"shortname": "TEST"}
        mock_db.get_worktree_by_prd.return_value = None
        mock_db.get_next_worktree_id.return_value = "TEST-W0001"
        (tmp_path / ".gitignore").write_text("node_modules/\n")
        mock_run.return_value = MagicMock(returncode=0)

        setup_prd_worktree(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        gitignore_content = (tmp_path / ".gitignore").read_text()
        assert ".worktrees/" in gitignore_content
        assert "node_modules/" in gitignore_content

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.os.getcwd")
    def test_blocked_when_worktree_disabled(self, mock_getcwd, mock_git_config, tmp_path):
        """Worktree creation is blocked when worktree_enabled is False (default)."""
        from a_sdlc.core.git_config import GitSafetyConfig
        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = GitSafetyConfig()  # all defaults = False

        result = setup_prd_worktree(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        assert result["status"] == "disabled"
        assert "worktree_enabled" in result["message"]


# =============================================================================
# cleanup_prd_worktree
# =============================================================================


class TestCleanupPrdWorktree:
    """Test cleanup_prd_worktree MCP tool."""

    def _make_worktree_record(self, tmp_path, prd_id="TEST-P0001"):
        """Return a DB-style worktree dict."""
        return {
            "id": "TEST-W0001",
            "project_id": "test-project",
            "prd_id": prd_id,
            "sprint_id": "TEST-S0001",
            "branch_name": f"sprint/TEST-S0001/{prd_id}",
            "path": str(tmp_path / ".worktrees" / prd_id),
            "status": "active",
            "created_at": "2026-01-01T00:00:00+00:00",
            "cleaned_at": None,
        }

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_removes_worktree(self, mock_getcwd, mock_get_db, mock_run, tmp_path):
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        # Create worktree directory and DB record
        worktree_path = tmp_path / ".worktrees" / "TEST-P0001"
        worktree_path.mkdir(parents=True)
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)
        mock_db.get_project.return_value = {"shortname": "TEST"}

        mock_run.return_value = MagicMock(returncode=0)

        result = cleanup_prd_worktree(prd_id="TEST-P0001", docker_cleanup=False)

        assert result["status"] == "cleaned"
        assert result["branch_removed"] is False

        # Verify git worktree remove was called
        remove_calls = [
            c for c in mock_run.call_args_list
            if c[0][0][:3] == ["git", "worktree", "remove"]
        ]
        assert len(remove_calls) == 1

        # Verify git worktree prune was called
        prune_calls = [
            c for c in mock_run.call_args_list
            if c[0][0] == ["git", "worktree", "prune"]
        ]
        assert len(prune_calls) == 1

        # Verify DB status was updated
        mock_db.update_worktree.assert_called_once_with("TEST-W0001", status="abandoned")

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_with_branch_removal_requires_confirmation(
        self, mock_getcwd, mock_get_db, mock_run, tmp_path
    ):
        """Branch deletion without confirm_branch_delete returns confirmation_required."""
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        worktree_path = tmp_path / ".worktrees" / "TEST-P0001"
        worktree_path.mkdir(parents=True)
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        result = cleanup_prd_worktree(
            prd_id="TEST-P0001",
            remove_branch=True,
            docker_cleanup=False,
        )

        assert result["status"] == "confirmation_required"
        assert "branch" in result
        # git should not have been called at all
        mock_run.assert_not_called()

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_with_branch_removal_confirmed(self, mock_getcwd, mock_get_db, mock_run, tmp_path):
        """Branch deletion proceeds when confirm_branch_delete=True."""
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        worktree_path = tmp_path / ".worktrees" / "TEST-P0001"
        worktree_path.mkdir(parents=True)
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)
        mock_db.get_project.return_value = {"shortname": "TEST"}

        mock_run.return_value = MagicMock(returncode=0)

        result = cleanup_prd_worktree(
            prd_id="TEST-P0001",
            remove_branch=True,
            confirm_branch_delete=True,
            docker_cleanup=False,
        )

        assert result["status"] == "cleaned"
        assert result["branch_removed"] is True

        # Verify git branch -D was called
        branch_calls = [c for c in mock_run.call_args_list if "branch" in str(c)]
        assert len(branch_calls) >= 1

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_not_found(self, mock_getcwd, mock_get_db, tmp_path):
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = None

        result = cleanup_prd_worktree(prd_id="NONEXISTENT")

        assert result["status"] == "not_found"

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_with_docker(self, mock_getcwd, mock_get_db, mock_run, tmp_path):
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        worktree_path = tmp_path / ".worktrees" / "TEST-P0001"
        worktree_path.mkdir(parents=True)
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)
        mock_db.get_project.return_value = {"shortname": "TEST"}

        mock_run.return_value = MagicMock(returncode=0)

        result = cleanup_prd_worktree(prd_id="TEST-P0001", docker_cleanup=True)

        assert result["status"] == "cleaned"
        assert result["docker_cleaned"] is True

        # Docker compose down should have been called
        docker_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "docker"]
        assert len(docker_calls) == 1

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_orphan_worktree_on_disk(self, mock_getcwd, mock_get_db, mock_run, tmp_path):
        """Orphaned worktree on disk (no DB record) is cleaned up."""
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = None

        # Create orphan worktree directory on disk
        orphan_path = tmp_path / ".worktrees" / "ORPHAN-P0001"
        orphan_path.mkdir(parents=True)

        mock_run.return_value = MagicMock(returncode=0)

        result = cleanup_prd_worktree(prd_id="ORPHAN-P0001")

        assert result["status"] == "cleaned"
        assert result["orphan"] is True
        assert "no DB record" in result["message"]
        assert result["branch_removed"] is False
        assert result["docker_cleaned"] is False

        # Verify git worktree remove and prune were called
        remove_calls = [c for c in mock_run.call_args_list if "remove" in str(c)]
        assert len(remove_calls) == 1
        prune_calls = [c for c in mock_run.call_args_list if "prune" in str(c)]
        assert len(prune_calls) == 1

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_orphan_fallback_to_rmtree(
        self, mock_getcwd, mock_get_db, mock_run, tmp_path
    ):
        """Orphan cleanup falls back to shutil.rmtree when git worktree remove fails."""
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = None

        orphan_path = tmp_path / ".worktrees" / "ORPHAN-P0001"
        orphan_path.mkdir(parents=True)

        # git worktree remove fails, git worktree prune succeeds
        def side_effect(*args, **kwargs):
            cmd = args[0]
            if "remove" in cmd:
                raise subprocess.CalledProcessError(1, cmd, stderr="not a valid worktree")
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect

        result = cleanup_prd_worktree(prd_id="ORPHAN-P0001")

        assert result["status"] == "cleaned"
        assert result["orphan"] is True
        # The orphan directory should be removed (via shutil.rmtree fallback)
        assert not orphan_path.exists()

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_db_record_but_no_directory(self, mock_getcwd, mock_get_db, mock_run, tmp_path):
        """Worktree in DB but directory missing on disk -- prune and update DB."""
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        # DB record exists but the directory does NOT exist on disk
        record = self._make_worktree_record(tmp_path)
        mock_db.get_worktree_by_prd.return_value = record
        mock_db.get_project.return_value = {"shortname": "TEST"}

        mock_run.return_value = MagicMock(returncode=0)

        result = cleanup_prd_worktree(prd_id="TEST-P0001", docker_cleanup=False)

        assert result["status"] == "cleaned"

        # git worktree remove should NOT be called (directory doesn't exist)
        remove_calls = [
            c for c in mock_run.call_args_list
            if len(c[0]) > 0 and "remove" in str(c[0][0])
        ]
        assert len(remove_calls) == 0

        # git worktree prune SHOULD be called
        prune_calls = [c for c in mock_run.call_args_list if "prune" in str(c)]
        assert len(prune_calls) == 1

        # DB status should still be updated
        mock_db.update_worktree.assert_called_once_with("TEST-W0001", status="abandoned")

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_cleanup_branch_removed_false_when_not_confirmed(
        self, mock_getcwd, mock_get_db, mock_run, tmp_path
    ):
        """branch_removed is False when remove_branch=True but confirm_branch_delete=False."""
        from a_sdlc.server import cleanup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        worktree_path = tmp_path / ".worktrees" / "TEST-P0001"
        worktree_path.mkdir(parents=True)
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        result = cleanup_prd_worktree(
            prd_id="TEST-P0001",
            remove_branch=True,
            confirm_branch_delete=False,
        )

        # Should get confirmation_required, not proceed
        assert result["status"] == "confirmation_required"


# =============================================================================
# create_prd_pr
# =============================================================================


class TestCreatePrdPr:
    """Test create_prd_pr MCP tool."""

    def _enabled_git_config(self):
        """Return a GitSafetyConfig with auto_pr=True."""
        from a_sdlc.core.git_config import GitSafetyConfig
        return GitSafetyConfig(auto_pr=True)

    def _make_worktree_record(self, tmp_path, prd_id="TEST-P0001"):
        """Return a DB-style worktree dict."""
        return {
            "id": "TEST-W0001",
            "project_id": "test-project",
            "prd_id": prd_id,
            "sprint_id": "TEST-S0001",
            "branch_name": f"sprint/TEST-S0001/{prd_id}",
            "path": str(tmp_path / ".worktrees" / prd_id),
            "status": "active",
            "created_at": "2026-01-01T00:00:00+00:00",
            "cleaned_at": None,
        }

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_creates_pr_successfully(self, mock_getcwd, mock_get_db, mock_run, mock_git_config, tmp_path):
        from a_sdlc.server import create_prd_pr

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_prd.return_value = {"title": "Auth Feature"}
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

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

        # Verify DB was updated with pr_url only (status stays active)
        mock_db.update_worktree.assert_called_once_with(
            "TEST-W0001", pr_url="https://github.com/org/repo/pull/42"
        )

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_no_worktree(self, mock_getcwd, mock_get_db, mock_git_config, tmp_path):
        from a_sdlc.server import create_prd_pr

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = None

        result = create_prd_pr(prd_id="NONEXISTENT", sprint_id="TEST-S0001")

        assert result["status"] == "not_found"

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_push_failure(self, mock_getcwd, mock_get_db, mock_run, mock_git_config, tmp_path):
        import subprocess as sp

        from a_sdlc.server import create_prd_pr

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_prd.return_value = {"title": "Auth Feature"}
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        mock_run.side_effect = sp.CalledProcessError(1, "git", stderr="remote rejected")

        result = create_prd_pr(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        assert result["status"] == "error"
        assert "push" in result["message"].lower()

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_custom_title_and_body(self, mock_getcwd, mock_get_db, mock_run, mock_git_config, tmp_path):
        from a_sdlc.server import create_prd_pr

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_prd.return_value = {"title": "Auth Feature"}
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

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

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_blocked_when_auto_pr_disabled(self, mock_getcwd, mock_git_config, tmp_path):
        """PR creation is blocked when auto_pr is False (default)."""
        from a_sdlc.core.git_config import GitSafetyConfig
        from a_sdlc.server import create_prd_pr

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = GitSafetyConfig()  # all defaults = False

        result = create_prd_pr(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        assert result["status"] == "disabled"
        assert "auto_pr" in result["message"]


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


# =============================================================================
# list_worktrees
# =============================================================================


class TestListWorktrees:
    """Test list_worktrees MCP tool."""

    def _make_worktree_record(self, prd_id="TEST-P0001", status="active", sprint_id="TEST-S0001"):
        """Return a DB-style worktree dict."""
        return {
            "id": f"TEST-W{prd_id[-4:]}",
            "project_id": "test-project",
            "prd_id": prd_id,
            "sprint_id": sprint_id,
            "branch_name": f"sprint/{sprint_id}/{prd_id}",
            "path": f"/tmp/.worktrees/{prd_id}",
            "status": status,
            "created_at": "2026-01-01T00:00:00+00:00",
            "cleaned_at": None,
        }

    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_lists_all_worktrees(self, mock_get_db, mock_get_pid):
        from a_sdlc.server import list_worktrees

        mock_get_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.list_worktrees.return_value = [
            self._make_worktree_record("TEST-P0001"),
            self._make_worktree_record("TEST-P0002", status="completed"),
        ]

        result = list_worktrees()

        assert result["status"] == "ok"
        assert result["project_id"] == "test-project"
        assert result["count"] == 2
        assert len(result["worktrees"]) == 2
        assert result["worktrees"][0]["prd_id"] == "TEST-P0001"
        assert result["worktrees"][0]["status"] == "active"
        assert result["worktrees"][1]["status"] == "completed"

    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_lists_worktrees_empty(self, mock_get_db, mock_get_pid):
        from a_sdlc.server import list_worktrees

        mock_get_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.list_worktrees.return_value = []

        result = list_worktrees()

        assert result["status"] == "ok"
        assert result["count"] == 0
        assert result["worktrees"] == []

    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_filters_by_status(self, mock_get_db, mock_get_pid):
        from a_sdlc.server import list_worktrees

        mock_get_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.list_worktrees.return_value = [
            self._make_worktree_record("TEST-P0001", status="active"),
        ]

        result = list_worktrees(status="active")

        assert result["status"] == "ok"
        assert result["filters"]["status"] == "active"
        mock_db.list_worktrees.assert_called_once_with(
            "test-project", status="active", sprint_id=None,
        )

    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_filters_by_sprint_id(self, mock_get_db, mock_get_pid):
        from a_sdlc.server import list_worktrees

        mock_get_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.list_worktrees.return_value = []

        result = list_worktrees(sprint_id="TEST-S0002")

        assert result["filters"]["sprint_id"] == "TEST-S0002"
        mock_db.list_worktrees.assert_called_once_with(
            "test-project", status=None, sprint_id="TEST-S0002",
        )

    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_no_project_returns_error(self, mock_get_db, mock_get_pid):
        from a_sdlc.server import list_worktrees

        mock_get_pid.return_value = None
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        result = list_worktrees()

        assert result["status"] == "error"
        assert "No project context" in result["message"]

    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_explicit_project_id(self, mock_get_db, mock_get_pid):
        from a_sdlc.server import list_worktrees

        mock_get_pid.return_value = "auto-detected"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.list_worktrees.return_value = []

        result = list_worktrees(project_id="explicit-project")

        assert result["project_id"] == "explicit-project"
        mock_db.list_worktrees.assert_called_once_with(
            "explicit-project", status=None, sprint_id=None,
        )

    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_worktree_fields_in_response(self, mock_get_db, mock_get_pid):
        """Verify all expected fields are present in each worktree entry."""
        from a_sdlc.server import list_worktrees

        mock_get_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.list_worktrees.return_value = [self._make_worktree_record()]

        result = list_worktrees()

        w = result["worktrees"][0]
        expected_keys = {"id", "prd_id", "sprint_id", "branch_name", "path", "status", "created_at", "cleaned_at"}
        assert set(w.keys()) == expected_keys


# =============================================================================
# complete_prd_worktree
# =============================================================================


class TestCompletePrdWorktree:
    """Test complete_prd_worktree MCP tool."""

    def _make_worktree_record(self, tmp_path, prd_id="TEST-P0001"):
        """Return a DB-style worktree dict."""
        return {
            "id": "TEST-W0001",
            "project_id": "test-project",
            "prd_id": prd_id,
            "sprint_id": "TEST-S0001",
            "branch_name": f"sprint/TEST-S0001/{prd_id}",
            "path": str(tmp_path / ".worktrees" / prd_id),
            "status": "active",
            "created_at": "2026-01-01T00:00:00+00:00",
            "cleaned_at": None,
        }

    def _enabled_git_config(self, auto_pr=False, auto_merge=False):
        """Return a GitSafetyConfig with specified settings."""
        from a_sdlc.core.git_config import GitSafetyConfig
        return GitSafetyConfig(auto_pr=auto_pr, auto_merge=auto_merge, worktree_enabled=True)

    def test_invalid_action_returns_error(self):
        from a_sdlc.server import complete_prd_worktree

        result = complete_prd_worktree(prd_id="TEST-P0001", action="invalid")

        assert result["status"] == "error"
        assert "Invalid action" in result["message"]
        assert "merge" in result["message"]

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_no_worktree_returns_not_found(self, mock_getcwd, mock_get_db, tmp_path):
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = None

        result = complete_prd_worktree(prd_id="NONEXISTENT", action="keep")

        assert result["status"] == "not_found"

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_keep_action(self, mock_getcwd, mock_get_db, mock_git_config, tmp_path):
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        result = complete_prd_worktree(prd_id="TEST-P0001", action="keep")

        assert result["status"] == "kept"
        assert result["branch"] == "sprint/TEST-S0001/TEST-P0001"
        assert result["worktree_id"] == "TEST-W0001"
        # No cleanup should happen
        mock_db.update_worktree.assert_not_called()

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_discard_requires_confirmation(self, mock_getcwd, mock_get_db, mock_git_config, tmp_path):
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        result = complete_prd_worktree(prd_id="TEST-P0001", action="discard")

        assert result["status"] == "confirmation_required"
        assert "confirm_discard" in result["message"]
        assert result["branch"] == "sprint/TEST-S0001/TEST-P0001"

    @patch("a_sdlc.server.cleanup_prd_worktree")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_discard_confirmed_calls_cleanup(self, mock_getcwd, mock_get_db, mock_git_config, mock_cleanup, tmp_path):
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        mock_cleanup.return_value = {"status": "cleaned", "message": "done"}

        result = complete_prd_worktree(prd_id="TEST-P0001", action="discard", confirm_discard=True)

        mock_cleanup.assert_called_once_with(
            prd_id="TEST-P0001",
            remove_branch=True,
            confirm_branch_delete=True,
            docker_cleanup=True,
        )
        assert result["status"] == "cleaned"

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_blocked_when_disabled(self, mock_getcwd, mock_get_db, mock_git_config, tmp_path):
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config(auto_pr=False)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        result = complete_prd_worktree(prd_id="TEST-P0001", action="pr")

        assert result["status"] == "disabled"
        assert "auto_pr" in result["message"]

    @patch("a_sdlc.server.create_prd_pr")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_delegates_to_create_prd_pr(self, mock_getcwd, mock_get_db, mock_git_config, mock_create_pr, tmp_path):
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config(auto_pr=True)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        mock_create_pr.return_value = {
            "status": "created",
            "pr_url": "https://github.com/org/repo/pull/42",
            "branch": "sprint/TEST-S0001/TEST-P0001",
            "title": "[TEST-S0001] Test PRD",
        }

        result = complete_prd_worktree(prd_id="TEST-P0001", action="pr")

        mock_create_pr.assert_called_once_with(
            prd_id="TEST-P0001",
            sprint_id="TEST-S0001",
            base_branch=None,
            title=None,
            body=None,
        )
        assert result["status"] == "created"
        assert result["pr_url"] == "https://github.com/org/repo/pull/42"

    @patch("a_sdlc.server.create_prd_pr")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_passes_custom_title_and_body(self, mock_getcwd, mock_get_db, mock_git_config, mock_create_pr, tmp_path):
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config(auto_pr=True)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        mock_create_pr.return_value = {"status": "created", "pr_url": "https://example.com/pr/1"}

        complete_prd_worktree(
            prd_id="TEST-P0001",
            action="pr",
            base_branch="develop",
            pr_title="Custom Title",
            pr_body="Custom Body",
        )

        mock_create_pr.assert_called_once_with(
            prd_id="TEST-P0001",
            sprint_id="TEST-S0001",
            base_branch="develop",
            title="Custom Title",
            body="Custom Body",
        )

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_merge_blocked_when_disabled(self, mock_getcwd, mock_get_db, mock_git_config, tmp_path):
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config(auto_merge=False)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        result = complete_prd_worktree(prd_id="TEST-P0001", action="merge")

        assert result["status"] == "disabled"
        assert "auto_merge" in result["message"]

    @patch("a_sdlc.server.cleanup_prd_worktree")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_merge_success(self, mock_getcwd, mock_get_db, mock_git_config, mock_run, mock_cleanup, tmp_path):
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config(auto_merge=True)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        # git symbolic-ref succeeds (find default branch), then git merge succeeds
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),  # symbolic-ref
            MagicMock(returncode=0, stdout="", stderr=""),  # git merge
        ]
        mock_cleanup.return_value = {"status": "cleaned"}

        result = complete_prd_worktree(prd_id="TEST-P0001", action="merge")

        assert result["status"] == "merged"
        assert result["target_branch"] == "main"
        assert result["branch"] == "sprint/TEST-S0001/TEST-P0001"
        assert result["cleanup"]["status"] == "cleaned"

        mock_cleanup.assert_called_once_with(
            prd_id="TEST-P0001",
            remove_branch=False,
            docker_cleanup=True,
        )

    @patch("a_sdlc.server.cleanup_prd_worktree")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_merge_with_explicit_base_branch(self, mock_getcwd, mock_get_db, mock_git_config, mock_run, mock_cleanup, tmp_path):
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config(auto_merge=True)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_cleanup.return_value = {"status": "cleaned"}

        result = complete_prd_worktree(prd_id="TEST-P0001", action="merge", base_branch="develop")

        assert result["status"] == "merged"
        assert result["target_branch"] == "develop"
        # Should NOT call symbolic-ref since base_branch is provided
        assert mock_run.call_count == 1  # only git merge

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_merge_failure(self, mock_getcwd, mock_get_db, mock_git_config, mock_run, tmp_path):
        import subprocess as sp

        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config(auto_merge=True)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        # symbolic-ref succeeds, merge fails
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
            sp.CalledProcessError(1, "git", stderr="CONFLICT in file.txt"),
        ]

        result = complete_prd_worktree(prd_id="TEST-P0001", action="merge")

        assert result["status"] == "error"
        assert "Merge failed" in result["message"]

    @patch("a_sdlc.server.cleanup_prd_worktree")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_merge_defaults_to_main_when_symbolic_ref_fails(
        self, mock_getcwd, mock_get_db, mock_git_config, mock_run, mock_cleanup, tmp_path
    ):
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_git_config.return_value = self._enabled_git_config(auto_merge=True)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        # symbolic-ref fails (no remote), merge succeeds
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout=""),  # symbolic-ref fails
            MagicMock(returncode=0, stdout="", stderr=""),  # merge succeeds
        ]
        mock_cleanup.return_value = {"status": "cleaned"}

        result = complete_prd_worktree(prd_id="TEST-P0001", action="merge")

        assert result["status"] == "merged"
        assert result["target_branch"] == "main"


class TestLogCorrection:
    """Test log_correction() MCP tool."""

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_valid_input_creates_file(self, mock_getcwd, mock_get_db, tmp_path):
        """Valid input creates corrections.log with correct format."""
        from a_sdlc.server import log_correction

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        project = _make_project(str(tmp_path))
        mock_db.get_project_by_path.return_value = project
        mock_db.get_project.return_value = project
        mock_db.update_project_accessed.return_value = None

        result = log_correction(
            context_type="task",
            context_id="PROJ-T00001",
            category="testing",
            description="Added missing edge case tests",
        )

        assert result["status"] == "logged"
        assert result["entry"]["context"] == "task:PROJ-T00001"
        assert result["entry"]["category"] == "testing"
        assert result["entry"]["description"] == "Added missing edge case tests"

        log_file = tmp_path / ".sdlc" / "corrections.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "task:PROJ-T00001" in content
        assert "testing" in content
        assert "Added missing edge case tests" in content

    def test_invalid_category_returns_error(self):
        """Invalid category returns error without writing."""
        from a_sdlc.server import log_correction

        result = log_correction(
            context_type="task",
            context_id="PROJ-T00001",
            category="invalid-cat",
            description="Some fix",
        )

        assert result["status"] == "error"
        assert "invalid-cat" in result["message"].lower() or "invalid" in result["message"].lower()

    def test_invalid_context_type_returns_error(self):
        """Invalid context_type returns error without writing."""
        from a_sdlc.server import log_correction

        result = log_correction(
            context_type="unknown",
            context_id="X",
            category="testing",
            description="Some fix",
        )

        assert result["status"] == "error"
        assert "unknown" in result["message"].lower() or "context_type" in result["message"].lower()

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_creates_file_if_missing(self, mock_getcwd, mock_get_db, tmp_path):
        """Creates .sdlc/corrections.log if it does not exist."""
        from a_sdlc.server import log_correction

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        project = _make_project(str(tmp_path))
        mock_db.get_project_by_path.return_value = project
        mock_db.get_project.return_value = project
        mock_db.update_project_accessed.return_value = None

        log_file = tmp_path / ".sdlc" / "corrections.log"
        assert not log_file.exists()

        result = log_correction(
            context_type="prd",
            context_id="PROJ-P0001",
            category="documentation",
            description="Fixed missing section",
        )

        assert result["status"] == "logged"
        assert log_file.exists()

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_appends_to_existing_file(self, mock_getcwd, mock_get_db, tmp_path):
        """Appends to existing corrections.log, preserving previous entries."""
        from a_sdlc.server import log_correction

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        project = _make_project(str(tmp_path))
        mock_db.get_project_by_path.return_value = project
        mock_db.get_project.return_value = project
        mock_db.update_project_accessed.return_value = None

        sdlc_dir = tmp_path / ".sdlc"
        sdlc_dir.mkdir()
        log_file = sdlc_dir / "corrections.log"
        log_file.write_text("2026-01-01T00:00:00Z | task:OLD-001 | testing | Old entry\n")

        log_correction(
            context_type="sprint",
            context_id="PROJ-S0001",
            category="process",
            description="New entry",
        )

        content = log_file.read_text()
        lines = content.strip().split("\n")
        assert len(lines) == 2
        assert "OLD-001" in lines[0]
        assert "PROJ-S0001" in lines[1]

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_no_project_falls_back_to_cwd(self, mock_getcwd, mock_get_db, tmp_path):
        """When no project context exists, falls back to os.getcwd()."""
        from a_sdlc.server import log_correction

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project_by_path.return_value = None

        result = log_correction(
            context_type="ad-hoc",
            context_id="none",
            category="code-quality",
            description="Fixed linting issues",
        )

        assert result["status"] == "logged"
        log_file = tmp_path / ".sdlc" / "corrections.log"
        assert log_file.exists()
        assert "ad-hoc:none" in log_file.read_text()

    def test_empty_description_returns_error(self):
        """Empty description returns error."""
        from a_sdlc.server import log_correction

        result = log_correction(
            context_type="task",
            context_id="PROJ-T00001",
            category="testing",
            description="",
        )

        assert result["status"] == "error"
        assert "empty" in result["message"].lower() or "description" in result["message"].lower()


# =============================================================================
# init_project -- init_files context for existing projects
# =============================================================================


class TestInitProjectExistingContext:
    """Test that init_project() returns init_files for existing projects."""

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_returns_init_files_all_present(self, mock_getcwd, mock_get_db, mock_project_dir):
        """When project exists and all init files are present, init_files all True."""
        from a_sdlc.server import init_project

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project_by_path.return_value = _make_project(str(mock_project_dir))

        # Create all init files
        (mock_project_dir / "CLAUDE.md").write_text("# CLAUDE.md")
        sdlc_dir = mock_project_dir / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "lesson-learn.md").write_text("# Lessons")
        (sdlc_dir / "config.yaml").write_text("testing: {}")

        result = init_project()

        assert result["status"] == "exists"
        assert result["init_files"]["claude_md"] is True
        assert result["init_files"]["lesson_learn"] is True
        assert result["init_files"]["sdlc_dir"] is True
        assert result["init_files"]["config_yaml"] is True

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_returns_init_files_none_present(self, mock_getcwd, mock_get_db, mock_project_dir):
        """When project exists but no init files, init_files all False."""
        from a_sdlc.server import init_project

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project_by_path.return_value = _make_project(str(mock_project_dir))

        result = init_project()

        assert result["status"] == "exists"
        assert result["init_files"]["claude_md"] is False
        assert result["init_files"]["lesson_learn"] is False
        assert result["init_files"]["sdlc_dir"] is False
        assert result["init_files"]["config_yaml"] is False

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_returns_init_files_partial(self, mock_getcwd, mock_get_db, mock_project_dir):
        """When project exists with only CLAUDE.md, init_files reflects that."""
        from a_sdlc.server import init_project

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project_by_path.return_value = _make_project(str(mock_project_dir))

        # Only create CLAUDE.md
        (mock_project_dir / "CLAUDE.md").write_text("# CLAUDE.md")

        result = init_project()

        assert result["status"] == "exists"
        assert result["init_files"]["claude_md"] is True
        assert result["init_files"]["lesson_learn"] is False
        assert result["init_files"]["sdlc_dir"] is False
        assert result["init_files"]["config_yaml"] is False

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_still_returns_project_info(self, mock_getcwd, mock_get_db, mock_project_dir):
        """Existing project response still includes project dict."""
        from a_sdlc.server import init_project

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        project = _make_project(str(mock_project_dir))
        mock_db.get_project_by_path.return_value = project

        result = init_project()

        assert result["status"] == "exists"
        assert result["project"] == project
        assert "message" in result


# =============================================================================
# Design Document MCP Tools
# =============================================================================


class TestDesignMCPTools:
    """Test design document MCP tools."""

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server._get_current_project_id")
    def test_create_design_no_project(self, mock_get_pid, mock_get_storage):
        """Test create_design without project context."""
        from a_sdlc.server import create_design

        mock_get_pid.return_value = None

        result = create_design(prd_id="TEST-P0001")
        assert result["status"] == "error"
        assert "No project context" in result["message"]

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server._get_current_project_id")
    def test_create_design_prd_not_found(self, mock_get_pid, mock_get_storage):
        """Test create_design when PRD doesn't exist."""
        from a_sdlc.server import create_design

        mock_get_pid.return_value = "test-project"
        mock_storage = MagicMock()
        mock_get_storage.return_value = mock_storage
        mock_storage.get_prd.return_value = None

        result = create_design(prd_id="NONEXISTENT")
        assert result["status"] == "not_found"

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server._get_current_project_id")
    def test_create_design_success(self, mock_get_pid, mock_get_storage):
        """Test successful design creation returns file_path."""
        from a_sdlc.server import create_design

        mock_get_pid.return_value = "test-project"
        mock_storage = MagicMock()
        mock_get_storage.return_value = mock_storage
        mock_storage.get_prd.return_value = {"id": "TEST-P0001", "title": "Test PRD"}
        mock_storage.get_design_by_prd.return_value = None
        mock_storage.create_design.return_value = {
            "id": "TEST-P0001",
            "prd_id": "TEST-P0001",
            "project_id": "test-project",
            "file_path": "/tmp/design.md",
        }

        result = create_design(prd_id="TEST-P0001")
        assert result["status"] == "created"
        assert result["design"]["prd_id"] == "TEST-P0001"
        assert result["file_path"] == "/tmp/design.md"
        mock_storage.create_design.assert_called_once_with(
            prd_id="TEST-P0001", project_id="test-project"
        )

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server._get_current_project_id")
    def test_create_design_duplicate(self, mock_get_pid, mock_get_storage):
        """Test creating duplicate design returns error."""
        from a_sdlc.server import create_design

        mock_get_pid.return_value = "test-project"
        mock_storage = MagicMock()
        mock_get_storage.return_value = mock_storage
        mock_storage.get_prd.return_value = {"id": "TEST-P0001", "title": "Test PRD"}
        mock_storage.get_design_by_prd.return_value = {"id": "existing-design"}

        result = create_design(prd_id="TEST-P0001")
        assert result["status"] == "error"
        assert "already exists" in result["message"]

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server._get_current_project_id")
    def test_create_design_returns_file_path(self, mock_get_pid, mock_get_storage):
        """Test create_design returns file_path for content writing."""
        from a_sdlc.server import create_design

        mock_get_pid.return_value = "test-project"
        mock_storage = MagicMock()
        mock_get_storage.return_value = mock_storage
        mock_storage.get_prd.return_value = {"id": "TEST-P0001", "title": "Test PRD"}
        mock_storage.get_design_by_prd.return_value = None
        mock_storage.create_design.return_value = {
            "id": "TEST-P0001",
            "prd_id": "TEST-P0001",
            "project_id": "test-project",
            "file_path": "/tmp/designs/TEST-P0001.md",
        }

        result = create_design(prd_id="TEST-P0001")
        assert result["status"] == "created"
        assert result["file_path"] == "/tmp/designs/TEST-P0001.md"
        mock_storage.create_design.assert_called_once_with(
            prd_id="TEST-P0001", project_id="test-project"
        )

    @patch("a_sdlc.server.get_storage")
    def test_get_design_not_found(self, mock_get_storage):
        """Test get_design when design doesn't exist."""
        from a_sdlc.server import get_design

        mock_storage = MagicMock()
        mock_get_storage.return_value = mock_storage
        mock_storage.get_design_by_prd.return_value = None

        result = get_design(prd_id="NONEXISTENT")
        assert result["status"] == "not_found"

    @patch("a_sdlc.server.get_storage")
    def test_get_design_success(self, mock_get_storage):
        """Test successful design retrieval."""
        from a_sdlc.server import get_design

        mock_storage = MagicMock()
        mock_get_storage.return_value = mock_storage
        mock_storage.get_design_by_prd.return_value = {
            "id": "TEST-P0001",
            "prd_id": "TEST-P0001",
            "content": "# Design Content",
        }

        result = get_design(prd_id="TEST-P0001")
        assert result["status"] == "ok"
        assert result["design"]["content"] == "# Design Content"

    @patch("a_sdlc.server.get_storage")
    def test_delete_design_success(self, mock_get_storage):
        """Test successful design deletion."""
        from a_sdlc.server import delete_design

        mock_storage = MagicMock()
        mock_get_storage.return_value = mock_storage
        mock_storage.delete_design.return_value = True

        result = delete_design(prd_id="TEST-P0001")
        assert result["status"] == "deleted"
        mock_storage.delete_design.assert_called_once_with("TEST-P0001")

    @patch("a_sdlc.server.get_storage")
    def test_delete_design_not_found(self, mock_get_storage):
        """Test delete_design when design doesn't exist."""
        from a_sdlc.server import delete_design

        mock_storage = MagicMock()
        mock_get_storage.return_value = mock_storage
        mock_storage.delete_design.return_value = False

        result = delete_design(prd_id="NONEXISTENT")
        assert result["status"] == "not_found"

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server._get_current_project_id")
    def test_list_designs_success(self, mock_get_pid, mock_get_storage):
        """Test listing designs."""
        from a_sdlc.server import list_designs

        mock_get_pid.return_value = "test-project"
        mock_storage = MagicMock()
        mock_get_storage.return_value = mock_storage
        mock_storage.list_designs.return_value = [
            {"id": "d1", "prd_id": "TEST-P0001"},
        ]

        result = list_designs()
        assert result["status"] == "ok"
        assert result["count"] == 1
        assert result["project_id"] == "test-project"
        assert len(result["designs"]) == 1

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server._get_current_project_id")
    def test_list_designs_no_project(self, mock_get_pid, mock_get_storage):
        """Test list_designs without project context."""
        from a_sdlc.server import list_designs

        mock_get_pid.return_value = None

        result = list_designs()
        assert result["status"] == "error"
        assert "No project context" in result["message"]

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server._get_current_project_id")
    def test_list_designs_with_explicit_project_id(self, mock_get_pid, mock_get_storage):
        """Test list_designs with explicitly provided project_id."""
        from a_sdlc.server import list_designs

        mock_get_pid.return_value = None  # No auto-detected project
        mock_storage = MagicMock()
        mock_get_storage.return_value = mock_storage
        mock_storage.list_designs.return_value = []

        result = list_designs(project_id="explicit-project")
        assert result["status"] == "ok"
        assert result["project_id"] == "explicit-project"
        assert result["count"] == 0

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server._get_current_project_id")
    def test_list_designs_empty(self, mock_get_pid, mock_get_storage):
        """Test list_designs when no designs exist."""
        from a_sdlc.server import list_designs

        mock_get_pid.return_value = "test-project"
        mock_storage = MagicMock()
        mock_get_storage.return_value = mock_storage
        mock_storage.list_designs.return_value = []

        result = list_designs()
        assert result["status"] == "ok"
        assert result["count"] == 0
        assert result["designs"] == []


# =============================================================================
# Review Tools
# =============================================================================


class TestSubmitSelfReview:
    """Test submit_self_review MCP tool."""

    def _make_task(self):
        return {
            "id": "TEST-T00001",
            "project_id": "test-project",
            "prd_id": "TEST-P0001",
            "title": "Test Task",
            "status": "in_progress",
            "priority": "medium",
        }

    @patch("a_sdlc.server.get_db")
    def test_submit_self_review_pass(self, mock_get_db):
        """Self-review with 'pass' verdict creates review and returns ok."""
        from a_sdlc.server import submit_self_review

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_reviews_for_task.return_value = []
        mock_db.create_review.return_value = {
            "id": 1,
            "task_id": "TEST-T00001",
            "project_id": "test-project",
            "round": 1,
            "reviewer_type": "self",
            "verdict": "pass",
            "findings": None,
            "test_output": None,
        }

        result = submit_self_review("TEST-T00001", "pass")

        assert result["status"] == "ok"
        assert result["review_id"] == 1
        assert result["round"] == 1
        assert result["verdict"] == "pass"
        mock_db.create_review.assert_called_once_with(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="pass",
            findings=None,
            test_output=None,
        )

    @patch("a_sdlc.server.get_db")
    def test_submit_self_review_fail(self, mock_get_db):
        """Self-review with 'fail' verdict is accepted."""
        from a_sdlc.server import submit_self_review

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_reviews_for_task.return_value = []
        mock_db.create_review.return_value = {
            "id": 2,
            "task_id": "TEST-T00001",
            "project_id": "test-project",
            "round": 1,
            "reviewer_type": "self",
            "verdict": "fail",
            "findings": '[{"severity": "high", "description": "Test failure"}]',
            "test_output": "FAILED test_auth.py::test_login",
        }

        result = submit_self_review(
            "TEST-T00001",
            "fail",
            findings='[{"severity": "high", "description": "Test failure"}]',
            test_output="FAILED test_auth.py::test_login",
        )

        assert result["status"] == "ok"
        assert result["verdict"] == "fail"
        mock_db.create_review.assert_called_once_with(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="fail",
            findings='[{"severity": "high", "description": "Test failure"}]',
            test_output="FAILED test_auth.py::test_login",
        )

    @patch("a_sdlc.server.get_db")
    def test_submit_self_review_task_not_found(self, mock_get_db):
        """Self-review on non-existent task returns not_found."""
        from a_sdlc.server import submit_self_review

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = None

        result = submit_self_review("NONEXISTENT", "pass")

        assert result["status"] == "not_found"
        mock_db.create_review.assert_not_called()

    @patch("a_sdlc.server.get_db")
    def test_submit_self_review_invalid_verdict(self, mock_get_db):
        """Self-review with invalid verdict (e.g. 'approve') returns error."""
        from a_sdlc.server import submit_self_review

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()

        result = submit_self_review("TEST-T00001", "approve")

        assert result["status"] == "error"
        assert "Invalid verdict" in result["message"]
        mock_db.create_review.assert_not_called()

    @patch("a_sdlc.server.get_db")
    def test_submit_self_review_round_auto_increment(self, mock_get_db):
        """Submitting two self-reviews results in rounds 1 and 2."""
        from a_sdlc.server import submit_self_review

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()

        # First call: no existing reviews
        mock_db.get_reviews_for_task.return_value = []
        mock_db.create_review.return_value = {
            "id": 1, "round": 1, "reviewer_type": "self", "verdict": "fail",
        }

        result1 = submit_self_review("TEST-T00001", "fail")
        assert result1["round"] == 1

        # Second call: one existing self-review
        mock_db.get_reviews_for_task.return_value = [
            {"id": 1, "round": 1, "reviewer_type": "self", "verdict": "fail"},
        ]
        mock_db.create_review.return_value = {
            "id": 2, "round": 2, "reviewer_type": "self", "verdict": "pass",
        }

        result2 = submit_self_review("TEST-T00001", "pass")
        assert result2["round"] == 2

    @patch("a_sdlc.server.get_db")
    def test_submit_self_review_empty_strings_become_none(self, mock_get_db):
        """Empty findings and test_output are stored as None."""
        from a_sdlc.server import submit_self_review

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_reviews_for_task.return_value = []
        mock_db.create_review.return_value = {"id": 1, "round": 1}

        submit_self_review("TEST-T00001", "pass", findings="", test_output="")

        mock_db.create_review.assert_called_once_with(
            task_id="TEST-T00001",
            project_id="test-project",
            round_num=1,
            reviewer_type="self",
            verdict="pass",
            findings=None,
            test_output=None,
        )


class TestSubmitReviewVerdict:
    """Test submit_review_verdict MCP tool."""

    def _make_task(self):
        return {
            "id": "TEST-T00001",
            "project_id": "test-project",
            "prd_id": "TEST-P0001",
            "title": "Test Task",
            "status": "in_progress",
            "priority": "medium",
        }

    @patch("a_sdlc.server.get_db")
    def test_submit_review_verdict_approve(self, mock_get_db):
        """Subagent review with 'approve' verdict succeeds."""
        from a_sdlc.server import submit_review_verdict

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_reviews_for_task.return_value = []
        mock_db.create_review.return_value = {
            "id": 1,
            "task_id": "TEST-T00001",
            "project_id": "test-project",
            "round": 1,
            "reviewer_type": "subagent",
            "verdict": "approve",
            "findings": None,
        }

        result = submit_review_verdict("TEST-T00001", "approve")

        assert result["status"] == "ok"
        assert result["review_id"] == 1
        assert result["round"] == 1
        assert result["verdict"] == "approve"

    @patch("a_sdlc.server.get_db")
    def test_submit_review_verdict_request_changes(self, mock_get_db):
        """Subagent review with 'request_changes' verdict succeeds."""
        from a_sdlc.server import submit_review_verdict

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_reviews_for_task.return_value = []
        mock_db.create_review.return_value = {
            "id": 2,
            "round": 1,
            "reviewer_type": "subagent",
            "verdict": "request_changes",
        }

        result = submit_review_verdict(
            "TEST-T00001",
            "request_changes",
            findings='[{"description": "Missing error handling"}]',
        )

        assert result["status"] == "ok"
        assert result["verdict"] == "request_changes"

    @patch("a_sdlc.server.get_db")
    def test_submit_review_verdict_escalate(self, mock_get_db):
        """Subagent review with 'escalate' verdict succeeds."""
        from a_sdlc.server import submit_review_verdict

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_reviews_for_task.return_value = []
        mock_db.create_review.return_value = {
            "id": 3,
            "round": 1,
            "reviewer_type": "subagent",
            "verdict": "escalate",
        }

        result = submit_review_verdict("TEST-T00001", "escalate")

        assert result["status"] == "ok"
        assert result["verdict"] == "escalate"

    @patch("a_sdlc.server.get_db")
    def test_submit_review_verdict_invalid_verdict(self, mock_get_db):
        """Subagent review with invalid verdict (e.g. 'pass') returns error."""
        from a_sdlc.server import submit_review_verdict

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()

        result = submit_review_verdict("TEST-T00001", "pass")

        assert result["status"] == "error"
        assert "Invalid verdict" in result["message"]
        mock_db.create_review.assert_not_called()

    @patch("a_sdlc.server.get_db")
    def test_submit_review_verdict_task_not_found(self, mock_get_db):
        """Subagent review on non-existent task returns not_found."""
        from a_sdlc.server import submit_review_verdict

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = None

        result = submit_review_verdict("NONEXISTENT", "approve")

        assert result["status"] == "not_found"
        mock_db.create_review.assert_not_called()

    @patch("a_sdlc.server.get_db")
    def test_submit_review_verdict_round_auto_increment(self, mock_get_db):
        """Submitting two subagent reviews results in rounds 1 and 2."""
        from a_sdlc.server import submit_review_verdict

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()

        # First call: no existing reviews
        mock_db.get_reviews_for_task.return_value = []
        mock_db.create_review.return_value = {"id": 1, "round": 1}

        result1 = submit_review_verdict("TEST-T00001", "request_changes")
        assert result1["round"] == 1

        # Second call: one existing subagent review
        mock_db.get_reviews_for_task.return_value = [
            {"id": 1, "round": 1, "reviewer_type": "subagent", "verdict": "request_changes"},
        ]
        mock_db.create_review.return_value = {"id": 2, "round": 2}

        result2 = submit_review_verdict("TEST-T00001", "approve")
        assert result2["round"] == 2

    @patch("a_sdlc.server.get_db")
    def test_submit_review_verdict_ignores_self_reviews_in_round_count(self, mock_get_db):
        """Subagent round count is independent of self-review rounds."""
        from a_sdlc.server import submit_review_verdict

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()

        # Existing reviews: 2 self-reviews, 0 subagent reviews
        mock_db.get_reviews_for_task.return_value = [
            {"id": 1, "round": 1, "reviewer_type": "self", "verdict": "fail"},
            {"id": 2, "round": 2, "reviewer_type": "self", "verdict": "pass"},
        ]
        mock_db.create_review.return_value = {"id": 3, "round": 1}

        result = submit_review_verdict("TEST-T00001", "approve")

        # First subagent review should be round 1, not 3
        assert result["round"] == 1


class TestGetReviewEvidence:
    """Test get_review_evidence MCP tool."""

    def _make_task(self):
        return {
            "id": "TEST-T00001",
            "project_id": "test-project",
            "prd_id": "TEST-P0001",
            "title": "Test Task",
            "status": "in_progress",
        }

    @patch("a_sdlc.server.get_db")
    def test_get_review_evidence_with_reviews(self, mock_get_db):
        """Returns ordered list of reviews with summary."""
        from a_sdlc.server import get_review_evidence

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_reviews_for_task.return_value = [
            {
                "id": 1, "task_id": "TEST-T00001", "round": 1,
                "reviewer_type": "self", "verdict": "fail",
                "findings": None, "test_output": "FAILED",
            },
            {
                "id": 2, "task_id": "TEST-T00001", "round": 1,
                "reviewer_type": "subagent", "verdict": "request_changes",
                "findings": '[{"description": "Missing tests"}]', "test_output": None,
            },
            {
                "id": 3, "task_id": "TEST-T00001", "round": 2,
                "reviewer_type": "self", "verdict": "pass",
                "findings": None, "test_output": "ALL PASSED",
            },
            {
                "id": 4, "task_id": "TEST-T00001", "round": 2,
                "reviewer_type": "subagent", "verdict": "approve",
                "findings": None, "test_output": None,
            },
        ]

        result = get_review_evidence("TEST-T00001")

        assert result["status"] == "ok"
        assert result["task_id"] == "TEST-T00001"
        assert len(result["reviews"]) == 4
        assert result["summary"]["total_rounds"] == 2
        assert result["summary"]["latest_self_verdict"] == "pass"
        assert result["summary"]["latest_subagent_verdict"] == "approve"
        assert result["summary"]["has_approved"] is True

    @patch("a_sdlc.server.get_db")
    def test_get_review_evidence_no_reviews(self, mock_get_db):
        """Task with no reviews returns empty list and has_approved=False."""
        from a_sdlc.server import get_review_evidence

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_reviews_for_task.return_value = []

        result = get_review_evidence("TEST-T00001")

        assert result["status"] == "ok"
        assert result["task_id"] == "TEST-T00001"
        assert result["reviews"] == []
        assert result["summary"]["total_rounds"] == 0
        assert result["summary"]["latest_self_verdict"] is None
        assert result["summary"]["latest_subagent_verdict"] is None
        assert result["summary"]["has_approved"] is False

    @patch("a_sdlc.server.get_db")
    def test_get_review_evidence_task_not_found(self, mock_get_db):
        """Non-existent task returns not_found."""
        from a_sdlc.server import get_review_evidence

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = None

        result = get_review_evidence("NONEXISTENT")

        assert result["status"] == "not_found"

    @patch("a_sdlc.server.get_db")
    def test_get_review_evidence_only_self_reviews(self, mock_get_db):
        """Task with only self-reviews has no subagent verdict."""
        from a_sdlc.server import get_review_evidence

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_reviews_for_task.return_value = [
            {
                "id": 1, "task_id": "TEST-T00001", "round": 1,
                "reviewer_type": "self", "verdict": "pass",
                "findings": None, "test_output": None,
            },
        ]

        result = get_review_evidence("TEST-T00001")

        assert result["status"] == "ok"
        assert result["summary"]["latest_self_verdict"] == "pass"
        assert result["summary"]["latest_subagent_verdict"] is None
        assert result["summary"]["has_approved"] is True  # 'pass' counts as approved

    @patch("a_sdlc.server.get_db")
    def test_get_review_evidence_has_approved_false_when_all_fail(self, mock_get_db):
        """has_approved is False when all verdicts are fail/request_changes."""
        from a_sdlc.server import get_review_evidence

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_reviews_for_task.return_value = [
            {
                "id": 1, "task_id": "TEST-T00001", "round": 1,
                "reviewer_type": "self", "verdict": "fail",
                "findings": None, "test_output": None,
            },
            {
                "id": 2, "task_id": "TEST-T00001", "round": 1,
                "reviewer_type": "subagent", "verdict": "request_changes",
                "findings": None, "test_output": None,
            },
        ]

        result = get_review_evidence("TEST-T00001")

        assert result["summary"]["has_approved"] is False


class TestUpdateTaskReviewGate:
    """Test review enforcement hard gate in update_task() and complete_task()."""

    @staticmethod
    def _make_task():
        return {
            "id": "TEST-T00001",
            "project_id": "test-project",
            "prd_id": "TEST-P0001",
            "title": "Test Task",
            "file_path": "/tmp/tasks/TEST-T00001.md",
            "status": "in_progress",
            "priority": "medium",
            "component": None,
        }

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.get_db")
    def test_complete_with_review_disabled_succeeds(
        self, mock_get_db, mock_load_review_config
    ):
        """update_task(status='completed') with review DISABLED succeeds normally."""
        from a_sdlc.core.review_config import ReviewConfig
        from a_sdlc.server import update_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.update_task.return_value = {**self._make_task(), "status": "completed"}

        mock_load_review_config.return_value = ReviewConfig(enabled=False)

        result = update_task("TEST-T00001", status="completed")

        assert result["status"] == "updated"
        assert result["task"]["status"] == "completed"
        mock_db.update_task.assert_called_once()
        # Should NOT call get_latest_approved_review when disabled
        mock_db.get_latest_approved_review.assert_not_called()

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.get_db")
    def test_complete_with_review_enabled_no_evidence_returns_error(
        self, mock_get_db, mock_load_review_config
    ):
        """update_task(status='completed') with review ENABLED and no evidence returns error."""
        from a_sdlc.core.review_config import ReviewConfig
        from a_sdlc.server import update_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_latest_approved_review.return_value = None

        mock_load_review_config.return_value = ReviewConfig(enabled=True)

        result = update_task("TEST-T00001", status="completed")

        assert result["status"] == "error"
        assert "Cannot complete TEST-T00001" in result["message"]
        assert "no approved review evidence" in result["message"]
        assert "submit_self_review()" in result["message"]
        assert "submit_review_verdict()" in result["message"]
        # Should NOT call update_task on db when gate blocks
        mock_db.update_task.assert_not_called()

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.get_db")
    def test_complete_with_review_enabled_approved_review_succeeds(
        self, mock_get_db, mock_load_review_config
    ):
        """update_task(status='completed') with review ENABLED and approved review succeeds."""
        from a_sdlc.core.review_config import ReviewConfig
        from a_sdlc.server import update_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_latest_approved_review.return_value = {
            "id": 1,
            "task_id": "TEST-T00001",
            "round": 1,
            "reviewer_type": "subagent",
            "verdict": "approve",
            "findings": None,
            "test_output": None,
        }
        mock_db.update_task.return_value = {**self._make_task(), "status": "completed"}

        mock_load_review_config.return_value = ReviewConfig(enabled=True)

        result = update_task("TEST-T00001", status="completed")

        assert result["status"] == "updated"
        assert result["task"]["status"] == "completed"
        mock_db.update_task.assert_called_once()

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.get_db")
    def test_complete_task_inherits_gate_behavior(
        self, mock_get_db, mock_load_review_config
    ):
        """complete_task() inherits the review gate since it delegates to update_task."""
        from a_sdlc.core.review_config import ReviewConfig
        from a_sdlc.server import complete_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_latest_approved_review.return_value = None

        mock_load_review_config.return_value = ReviewConfig(enabled=True)

        result = complete_task("TEST-T00001")

        assert result["status"] == "error"
        assert "Cannot complete TEST-T00001" in result["message"]
        mock_db.update_task.assert_not_called()

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.get_db")
    def test_in_progress_not_affected_by_review_gate(
        self, mock_get_db, mock_load_review_config
    ):
        """update_task(status='in_progress') is NOT affected by the review gate."""
        from a_sdlc.server import update_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        task = self._make_task()
        task["status"] = "pending"
        mock_db.get_task.return_value = task
        mock_db.update_task.return_value = {**task, "status": "in_progress"}

        result = update_task("TEST-T00001", status="in_progress")

        assert result["status"] == "updated"
        # load_review_config should NOT be called for non-completed statuses
        mock_load_review_config.assert_not_called()
        mock_db.get_latest_approved_review.assert_not_called()

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.get_db")
    def test_blocked_status_not_affected_by_review_gate(
        self, mock_get_db, mock_load_review_config
    ):
        """update_task(status='blocked') is NOT affected by the review gate."""
        from a_sdlc.server import update_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.update_task.return_value = {**self._make_task(), "status": "blocked"}

        result = update_task("TEST-T00001", status="blocked")

        assert result["status"] == "updated"
        mock_load_review_config.assert_not_called()
        mock_db.get_latest_approved_review.assert_not_called()

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.get_db")
    def test_error_message_mentions_both_review_tools(
        self, mock_get_db, mock_load_review_config
    ):
        """Error message references both submit_self_review() and submit_review_verdict()."""
        from a_sdlc.core.review_config import ReviewConfig
        from a_sdlc.server import update_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_latest_approved_review.return_value = None

        mock_load_review_config.return_value = ReviewConfig(enabled=True)

        result = update_task("TEST-T00001", status="completed")

        msg = result["message"]
        assert "submit_self_review()" in msg
        assert "submit_review_verdict()" in msg
        assert ".sdlc/config.yaml" in msg

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.get_db")
    def test_complete_with_review_enabled_pass_verdict_succeeds(
        self, mock_get_db, mock_load_review_config
    ):
        """update_task(status='completed') with a 'pass' verdict also succeeds."""
        from a_sdlc.core.review_config import ReviewConfig
        from a_sdlc.server import update_task

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_task.return_value = self._make_task()
        mock_db.get_latest_approved_review.return_value = {
            "id": 2,
            "task_id": "TEST-T00001",
            "round": 1,
            "reviewer_type": "self",
            "verdict": "pass",
            "findings": None,
            "test_output": None,
        }
        mock_db.update_task.return_value = {**self._make_task(), "status": "completed"}

        mock_load_review_config.return_value = ReviewConfig(enabled=True)

        result = update_task("TEST-T00001", status="completed")

        assert result["status"] == "updated"
        mock_db.update_task.assert_called_once()
