"""Tests for MCP server tools — artifact detection in get_context()."""

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
