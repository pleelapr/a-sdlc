"""Tests for objective file management in ContentManager."""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from a_sdlc.core.content import ContentManager


@pytest.fixture
def temp_content():
    """Create a temporary ContentManager instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cm = ContentManager(base_path=Path(tmpdir))
        yield cm


class TestGetObjectivesDir:
    """Test get_objectives_dir() method."""

    def test_returns_correct_path(self, temp_content):
        """Test that get_objectives_dir returns path with correct structure."""
        obj_dir = temp_content.get_objectives_dir("test-project")
        assert obj_dir == temp_content.base_path / "test-project" / "objectives"

    def test_creates_directory(self, temp_content):
        """Test that get_objectives_dir creates the directory if it does not exist."""
        obj_dir = temp_content.get_objectives_dir("test-project")
        assert obj_dir.exists()
        assert obj_dir.is_dir()

    def test_directory_name_is_objectives(self, temp_content):
        """Test that the directory is named 'objectives'."""
        obj_dir = temp_content.get_objectives_dir("test-project")
        assert obj_dir.name == "objectives"

    def test_parent_structure(self, temp_content):
        """Test that objectives dir is nested under project directory."""
        obj_dir = temp_content.get_objectives_dir("my-project")
        assert obj_dir.parent.name == "my-project"

    def test_idempotent(self, temp_content):
        """Test that calling get_objectives_dir twice returns the same path."""
        dir1 = temp_content.get_objectives_dir("test-project")
        dir2 = temp_content.get_objectives_dir("test-project")
        assert dir1 == dir2
        assert dir1.exists()

    def test_returns_path_object(self, temp_content):
        """Test that the return type is a Path object."""
        obj_dir = temp_content.get_objectives_dir("test-project")
        assert isinstance(obj_dir, Path)


class TestGetObjectivePath:
    """Test get_objective_path() method."""

    def test_returns_correct_path(self, temp_content):
        """Test that get_objective_path returns the correct file path."""
        path = temp_content.get_objective_path("test-project", "SDLC-R0042")
        assert path.name == "SDLC-R0042.md"
        assert "objectives" in str(path)

    def test_uses_run_id_as_filename(self, temp_content):
        """Test that the run_id is used as the filename stem."""
        path = temp_content.get_objective_path("test-project", "MY-R0001")
        assert path.stem == "MY-R0001"
        assert path.suffix == ".md"

    def test_returns_path_object(self, temp_content):
        """Test that the return type is a Path object."""
        path = temp_content.get_objective_path("test-project", "SDLC-R0042")
        assert isinstance(path, Path)

    def test_creates_parent_directory(self, temp_content):
        """Test that get_objective_path creates the objectives directory."""
        path = temp_content.get_objective_path("new-project", "SDLC-R0001")
        assert path.parent.exists()


class TestCreateObjectiveFile:
    """Test create_objective_file() method."""

    def test_creates_file(self, temp_content):
        """Test that create_objective_file creates a markdown file."""
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API with CRUD"
        )
        assert path.exists()
        assert path.is_file()

    def test_returns_path_object(self, temp_content):
        """Test that create_objective_file returns a Path object."""
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API"
        )
        assert isinstance(path, Path)

    def test_file_has_correct_name(self, temp_content):
        """Test that the created file uses run_id as filename."""
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API"
        )
        assert path.name == "SDLC-R0042.md"

    def test_creates_directory_if_not_exists(self, temp_content):
        """Test that objective directory is created if it does not exist."""
        path = temp_content.create_objective_file(
            "new-project", "SDLC-R0001", "Some objective"
        )
        assert path.parent.exists()
        assert path.parent.name == "objectives"

    def test_content_includes_title(self, temp_content):
        """Test that the file content includes the objective description as title."""
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API with CRUD and auth"
        )
        content = path.read_text(encoding="utf-8")
        assert content.startswith("# Objective: Build REST API with CRUD and auth\n")

    def test_content_includes_run_id(self, temp_content):
        """Test that the file content includes the run ID."""
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API"
        )
        content = path.read_text(encoding="utf-8")
        assert "**Run ID**: SDLC-R0042" in content

    def test_content_includes_status(self, temp_content):
        """Test that the file content includes in_progress status."""
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API"
        )
        content = path.read_text(encoding="utf-8")
        assert "**Status**: in_progress" in content

    def test_content_includes_created_timestamp(self, temp_content):
        """Test that the file content includes a created timestamp in ISO format."""
        before = datetime.now()
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API"
        )
        after = datetime.now()
        content = path.read_text(encoding="utf-8")
        assert "**Created**: " in content
        # Extract the timestamp and validate it is between before and after
        for line in content.split("\n"):
            if line.startswith("**Created**: "):
                ts_str = line.replace("**Created**: ", "")
                ts = datetime.fromisoformat(ts_str)
                assert before <= ts <= after

    def test_content_includes_acceptance_criteria_section(self, temp_content):
        """Test that the file content includes acceptance criteria placeholder."""
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API"
        )
        content = path.read_text(encoding="utf-8")
        assert "## Acceptance Criteria" in content
        assert "(Generated by orchestrator in Phase 1)" in content

    def test_content_includes_iteration_history_section(self, temp_content):
        """Test that the file content includes iteration history placeholder."""
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API"
        )
        content = path.read_text(encoding="utf-8")
        assert "## Iteration History" in content

    def test_content_matches_expected_template(self, temp_content):
        """Test that the full content matches the expected template structure."""
        fixed_time = datetime(2026, 3, 28, 14, 23, 45, 123456)
        with patch("a_sdlc.core.content.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            path = temp_content.create_objective_file(
                "test-project", "SDLC-R0042", "Build REST API with CRUD and auth"
            )
        content = path.read_text(encoding="utf-8")
        expected = (
            "# Objective: Build REST API with CRUD and auth\n"
            "\n"
            "**Run ID**: SDLC-R0042\n"
            "**Status**: in_progress\n"
            "**Created**: 2026-03-28T14:23:45.123456\n"
            "\n"
            "## Acceptance Criteria\n"
            "\n"
            "(Generated by orchestrator in Phase 1)\n"
            "\n"
            "## Iteration History\n"
            "\n"
        )
        assert content == expected

    def test_special_characters_in_description(self, temp_content):
        """Test that special characters in description are preserved."""
        desc = "Add E2E tests for checkout & payment (v2.0)"
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0001", desc
        )
        content = path.read_text(encoding="utf-8")
        assert f"# Objective: {desc}" in content


class TestReadObjective:
    """Test read_objective() method."""

    def test_read_existing_objective(self, temp_content):
        """Test reading an existing objective file returns its content."""
        temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API"
        )
        content = temp_content.read_objective("test-project", "SDLC-R0042")
        assert content is not None
        assert "# Objective: Build REST API" in content

    def test_read_nonexistent_objective(self, temp_content):
        """Test reading a nonexistent objective returns None."""
        content = temp_content.read_objective("test-project", "NONEXISTENT")
        assert content is None

    def test_read_from_nonexistent_project(self, temp_content):
        """Test reading objective from nonexistent project returns None."""
        content = temp_content.read_objective("nonexistent-project", "SDLC-R0001")
        assert content is None

    def test_write_and_read_roundtrip(self, temp_content):
        """Test that create followed by read returns the same content."""
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API"
        )
        written_content = path.read_text(encoding="utf-8")
        read_content = temp_content.read_objective("test-project", "SDLC-R0042")
        assert read_content == written_content


class TestListObjectiveFiles:
    """Test list_objective_files() method."""

    def test_list_empty(self, temp_content):
        """Test listing objectives when none exist returns empty list."""
        result = temp_content.list_objective_files("test-project")
        assert result == []

    def test_list_single_objective(self, temp_content):
        """Test listing a single objective file."""
        temp_content.create_objective_file(
            "test-project", "SDLC-R0001", "Objective one"
        )
        result = temp_content.list_objective_files("test-project")
        assert len(result) == 1
        assert result[0].name == "SDLC-R0001.md"

    def test_list_multiple_objectives_sorted(self, temp_content):
        """Test that multiple objectives are returned sorted."""
        temp_content.create_objective_file(
            "test-project", "SDLC-R0003", "Third"
        )
        temp_content.create_objective_file(
            "test-project", "SDLC-R0001", "First"
        )
        temp_content.create_objective_file(
            "test-project", "SDLC-R0002", "Second"
        )
        result = temp_content.list_objective_files("test-project")
        assert len(result) == 3
        assert result[0].stem == "SDLC-R0001"
        assert result[1].stem == "SDLC-R0002"
        assert result[2].stem == "SDLC-R0003"

    def test_list_returns_path_objects(self, temp_content):
        """Test that list returns Path objects."""
        temp_content.create_objective_file(
            "test-project", "SDLC-R0001", "Objective"
        )
        result = temp_content.list_objective_files("test-project")
        assert all(isinstance(p, Path) for p in result)

    def test_list_from_nonexistent_project(self, temp_content):
        """Test listing objectives from nonexistent project returns empty list."""
        result = temp_content.list_objective_files("nonexistent-project")
        assert result == []

    def test_list_only_md_files(self, temp_content):
        """Test that list only returns .md files."""
        temp_content.create_objective_file(
            "test-project", "SDLC-R0001", "Objective"
        )
        # Create a non-md file in the objectives directory
        obj_dir = temp_content.base_path / "test-project" / "objectives"
        (obj_dir / "notes.txt").write_text("not a markdown file")
        result = temp_content.list_objective_files("test-project")
        assert len(result) == 1
        assert result[0].suffix == ".md"


class TestDeleteObjective:
    """Test delete_objective() method."""

    def test_delete_existing_objective(self, temp_content):
        """Test deleting an existing objective file."""
        temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API"
        )
        result = temp_content.delete_objective("test-project", "SDLC-R0042")
        assert result is True
        assert temp_content.read_objective("test-project", "SDLC-R0042") is None

    def test_delete_nonexistent_objective(self, temp_content):
        """Test deleting a nonexistent objective returns False."""
        result = temp_content.delete_objective("test-project", "NONEXISTENT")
        assert result is False

    def test_delete_removes_file_from_disk(self, temp_content):
        """Test that delete actually removes the file from disk."""
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API"
        )
        assert path.exists()
        temp_content.delete_objective("test-project", "SDLC-R0042")
        assert not path.exists()

    def test_delete_does_not_affect_other_objectives(self, temp_content):
        """Test that deleting one objective does not affect others."""
        temp_content.create_objective_file(
            "test-project", "SDLC-R0001", "First"
        )
        temp_content.create_objective_file(
            "test-project", "SDLC-R0002", "Second"
        )
        temp_content.delete_objective("test-project", "SDLC-R0001")
        assert temp_content.read_objective("test-project", "SDLC-R0002") is not None
        assert len(temp_content.list_objective_files("test-project")) == 1


class TestObjectiveIntegration:
    """Integration-level tests for objective file operations."""

    def test_full_lifecycle(self, temp_content):
        """Test create, read, list, delete lifecycle."""
        # Create
        path = temp_content.create_objective_file(
            "test-project", "SDLC-R0042", "Build REST API"
        )
        assert path.exists()

        # Read
        content = temp_content.read_objective("test-project", "SDLC-R0042")
        assert content is not None
        assert "Build REST API" in content

        # List
        files = temp_content.list_objective_files("test-project")
        assert len(files) == 1

        # Delete
        result = temp_content.delete_objective("test-project", "SDLC-R0042")
        assert result is True

        # Verify gone
        assert temp_content.read_objective("test-project", "SDLC-R0042") is None
        assert len(temp_content.list_objective_files("test-project")) == 0

    def test_objectives_isolated_per_project(self, temp_content):
        """Test that objectives from different projects are isolated."""
        temp_content.create_objective_file(
            "project-a", "SDLC-R0001", "Objective A"
        )
        temp_content.create_objective_file(
            "project-b", "SDLC-R0001", "Objective B"
        )
        a_content = temp_content.read_objective("project-a", "SDLC-R0001")
        b_content = temp_content.read_objective("project-b", "SDLC-R0001")
        assert "Objective A" in a_content
        assert "Objective B" in b_content
        assert a_content != b_content

    def test_delete_project_content_removes_objectives(self, temp_content):
        """Test that delete_project_content also removes objective files."""
        temp_content.create_objective_file(
            "test-project", "SDLC-R0001", "Objective"
        )
        temp_content.delete_project_content("test-project")
        assert temp_content.list_objective_files("test-project") == []

    def test_objective_file_coexists_with_other_content(self, temp_content):
        """Test that objectives coexist with PRDs, tasks, and designs."""
        # Create various content types
        temp_content.write_prd("test-project", "TEST-P0001", "PRD", "Content")
        temp_content.write_task(
            "test-project", "TEST-T00001", "Task", "Description"
        )
        temp_content.write_design("test-project", "TEST-P0001", "# Design")
        temp_content.create_objective_file(
            "test-project", "SDLC-R0001", "Objective"
        )

        # All content types should be accessible
        assert temp_content.read_prd("test-project", "TEST-P0001") is not None
        assert temp_content.read_task("test-project", "TEST-T00001") is not None
        assert temp_content.read_design("test-project", "TEST-P0001") is not None
        assert temp_content.read_objective("test-project", "SDLC-R0001") is not None
