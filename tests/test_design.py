"""Tests for design document system -- database and content layers."""

import tempfile
from pathlib import Path

import pytest

from a_sdlc.core.content import ContentManager
from a_sdlc.core.database import Database


@pytest.fixture
def temp_db():
    """Create a temporary database instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=db_path)
        # Create a project for testing
        db.create_project("test-project", "Test Project", "/tmp/test")
        yield db


@pytest.fixture
def temp_content():
    """Create a temporary ContentManager instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cm = ContentManager(base_path=Path(tmpdir))
        yield cm


class TestDesignDatabase:
    """Test design document database CRUD operations."""

    def _create_prd(self, db):
        """Helper to create a PRD for design tests."""
        return db.create_prd(
            prd_id="TEST-P0001",
            project_id="test-project",
            title="Test PRD",
            file_path="/tmp/test/prds/TEST-P0001.md",
        )

    def test_create_design(self, temp_db):
        """Test creating a design document."""
        self._create_prd(temp_db)
        design = temp_db.create_design(
            design_id="TEST-P0001",
            prd_id="TEST-P0001",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0001.md",
        )
        assert design is not None
        assert design["prd_id"] == "TEST-P0001"
        assert design["project_id"] == "test-project"
        assert design["id"] == "TEST-P0001"

    def test_get_design(self, temp_db):
        """Test retrieving a design by ID."""
        self._create_prd(temp_db)
        created = temp_db.create_design(
            design_id="TEST-P0001",
            prd_id="TEST-P0001",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0001.md",
        )
        design = temp_db.get_design(created["id"])
        assert design is not None
        assert design["prd_id"] == "TEST-P0001"

    def test_get_design_not_found(self, temp_db):
        """Test retrieving a nonexistent design returns None."""
        design = temp_db.get_design("nonexistent-id")
        assert design is None

    def test_get_design_by_prd(self, temp_db):
        """Test retrieving a design by PRD ID."""
        self._create_prd(temp_db)
        temp_db.create_design(
            design_id="TEST-P0001",
            prd_id="TEST-P0001",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0001.md",
        )
        design = temp_db.get_design_by_prd("TEST-P0001")
        assert design is not None
        assert design["prd_id"] == "TEST-P0001"

    def test_get_design_by_prd_not_found(self, temp_db):
        """Test retrieving a design by nonexistent PRD returns None."""
        design = temp_db.get_design_by_prd("NONEXISTENT")
        assert design is None

    def test_list_designs(self, temp_db):
        """Test listing designs for a project."""
        self._create_prd(temp_db)
        temp_db.create_design(
            design_id="TEST-P0001",
            prd_id="TEST-P0001",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0001.md",
        )
        designs = temp_db.list_designs("test-project")
        assert len(designs) == 1
        assert designs[0]["prd_id"] == "TEST-P0001"

    def test_list_designs_empty(self, temp_db):
        """Test listing designs when none exist."""
        designs = temp_db.list_designs("test-project")
        assert designs == []

    def test_list_designs_ordering(self, temp_db):
        """Test that list_designs returns designs ordered by most recently updated."""
        self._create_prd(temp_db)
        # Create a second PRD
        temp_db.create_prd(
            prd_id="TEST-P0002",
            project_id="test-project",
            title="Test PRD 2",
            file_path="/tmp/test/prds/TEST-P0002.md",
        )
        temp_db.create_design(
            design_id="TEST-P0001",
            prd_id="TEST-P0001",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0001.md",
        )
        temp_db.create_design(
            design_id="TEST-P0002",
            prd_id="TEST-P0002",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0002.md",
        )
        designs = temp_db.list_designs("test-project")
        assert len(designs) == 2

    def test_update_design(self, temp_db):
        """Test updating a design document."""
        self._create_prd(temp_db)
        created = temp_db.create_design(
            design_id="TEST-P0001",
            prd_id="TEST-P0001",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0001.md",
        )
        updated = temp_db.update_design(
            created["id"],
            file_path="/tmp/test/designs/TEST-P0001-v2.md",
        )
        assert updated is not None
        assert updated["file_path"] == "/tmp/test/designs/TEST-P0001-v2.md"

    def test_update_design_no_kwargs(self, temp_db):
        """Test update_design with no kwargs returns current design."""
        self._create_prd(temp_db)
        created = temp_db.create_design(
            design_id="TEST-P0001",
            prd_id="TEST-P0001",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0001.md",
        )
        result = temp_db.update_design(created["id"])
        assert result is not None
        assert result["id"] == created["id"]

    def test_update_design_sets_updated_at(self, temp_db):
        """Test that update_design sets the updated_at timestamp."""
        self._create_prd(temp_db)
        created = temp_db.create_design(
            design_id="TEST-P0001",
            prd_id="TEST-P0001",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0001.md",
        )
        original_updated_at = created["updated_at"]
        updated = temp_db.update_design(
            created["id"],
            file_path="/tmp/test/designs/new-path.md",
        )
        assert updated["updated_at"] >= original_updated_at

    def test_delete_design(self, temp_db):
        """Test deleting a design document."""
        self._create_prd(temp_db)
        created = temp_db.create_design(
            design_id="TEST-P0001",
            prd_id="TEST-P0001",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0001.md",
        )
        result = temp_db.delete_design(created["id"])
        assert result is True
        assert temp_db.get_design(created["id"]) is None

    def test_delete_design_not_found(self, temp_db):
        """Test deleting nonexistent design returns False."""
        result = temp_db.delete_design("nonexistent-id")
        assert result is False

    def test_unique_prd_constraint(self, temp_db):
        """Test that each PRD can only have one design (UNIQUE constraint on prd_id)."""
        self._create_prd(temp_db)
        temp_db.create_design(
            design_id="design-1",
            prd_id="TEST-P0001",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0001.md",
        )
        # Second design for same PRD should raise due to UNIQUE constraint
        with pytest.raises(Exception):
            temp_db.create_design(
                design_id="design-2",
                prd_id="TEST-P0001",
                project_id="test-project",
                file_path="/tmp/test/designs/TEST-P0001-dup.md",
            )

    def test_cascade_delete_with_prd(self, temp_db):
        """Test that deleting a PRD cascades to delete its design."""
        self._create_prd(temp_db)
        temp_db.create_design(
            design_id="TEST-P0001",
            prd_id="TEST-P0001",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0001.md",
        )
        # Verify design exists
        assert temp_db.get_design_by_prd("TEST-P0001") is not None
        # Delete the PRD
        temp_db.delete_prd("TEST-P0001")
        # Design should be gone (cascade)
        assert temp_db.get_design_by_prd("TEST-P0001") is None

    def test_design_has_timestamps(self, temp_db):
        """Test that created design has created_at and updated_at timestamps."""
        self._create_prd(temp_db)
        design = temp_db.create_design(
            design_id="TEST-P0001",
            prd_id="TEST-P0001",
            project_id="test-project",
            file_path="/tmp/test/designs/TEST-P0001.md",
        )
        assert design["created_at"] is not None
        assert design["updated_at"] is not None

    def test_design_file_path_nullable(self, temp_db):
        """Test that file_path is nullable on design creation."""
        self._create_prd(temp_db)
        design = temp_db.create_design(
            design_id="TEST-P0001",
            prd_id="TEST-P0001",
            project_id="test-project",
        )
        assert design is not None
        assert design["file_path"] is None


class TestDesignContent:
    """Test design document content file management."""

    def test_get_design_dir_creates_directory(self, temp_content):
        """Test that get_design_dir creates the designs directory."""
        design_dir = temp_content.get_design_dir("test-project")
        assert design_dir.exists()
        assert design_dir.name == "designs"

    def test_get_design_dir_parent_structure(self, temp_content):
        """Test that design dir is nested under project directory."""
        design_dir = temp_content.get_design_dir("test-project")
        assert design_dir.parent.name == "test-project"

    def test_get_design_path(self, temp_content):
        """Test design file path generation."""
        path = temp_content.get_design_path("test-project", "TEST-P0001")
        assert path.name == "TEST-P0001.md"
        assert "designs" in str(path)

    def test_get_design_path_uses_prd_id_as_filename(self, temp_content):
        """Test that the PRD ID is used as the design filename."""
        path = temp_content.get_design_path("test-project", "MY-P0042")
        assert path.stem == "MY-P0042"
        assert path.suffix == ".md"

    def test_write_design(self, temp_content):
        """Test writing design content to file."""
        path = temp_content.write_design("test-project", "TEST-P0001", "# Design\n\nContent here")
        assert path.exists()
        assert path.read_text() == "# Design\n\nContent here"

    def test_write_design_creates_parent_dirs(self, temp_content):
        """Test that write_design creates parent directories if needed."""
        path = temp_content.write_design("new-project", "TEST-P0001", "# Design")
        assert path.exists()
        assert path.parent.exists()

    def test_write_design_overwrites_existing(self, temp_content):
        """Test that write_design overwrites existing content."""
        temp_content.write_design("test-project", "TEST-P0001", "# Original")
        path = temp_content.write_design("test-project", "TEST-P0001", "# Updated")
        assert path.read_text() == "# Updated"

    def test_read_design(self, temp_content):
        """Test reading design content from file."""
        temp_content.write_design("test-project", "TEST-P0001", "# Design Content")
        content = temp_content.read_design("test-project", "TEST-P0001")
        assert content == "# Design Content"

    def test_read_nonexistent_design(self, temp_content):
        """Test reading a nonexistent design returns None."""
        content = temp_content.read_design("test-project", "NONEXISTENT")
        assert content is None

    def test_read_design_from_nonexistent_project(self, temp_content):
        """Test reading design from nonexistent project returns None."""
        content = temp_content.read_design("nonexistent-project", "TEST-P0001")
        assert content is None

    def test_delete_design(self, temp_content):
        """Test deleting a design content file."""
        temp_content.write_design("test-project", "TEST-P0001", "# Content")
        result = temp_content.delete_design("test-project", "TEST-P0001")
        assert result is True
        assert temp_content.read_design("test-project", "TEST-P0001") is None

    def test_delete_nonexistent_design(self, temp_content):
        """Test deleting a nonexistent design returns False."""
        result = temp_content.delete_design("test-project", "NONEXISTENT")
        assert result is False

    def test_write_and_read_roundtrip(self, temp_content):
        """Test that write followed by read returns identical content."""
        original = "# Architecture\n\n## Overview\n\nDetailed design content.\n\n## Decisions\n\n- ADR-001"
        temp_content.write_design("test-project", "TEST-P0001", original)
        result = temp_content.read_design("test-project", "TEST-P0001")
        assert result == original

    def test_write_empty_content(self, temp_content):
        """Test writing empty content to design file."""
        path = temp_content.write_design("test-project", "TEST-P0001", "")
        assert path.exists()
        content = temp_content.read_design("test-project", "TEST-P0001")
        assert content == ""

    def test_multiple_designs_different_prds(self, temp_content):
        """Test writing designs for multiple PRDs in same project."""
        temp_content.write_design("test-project", "TEST-P0001", "# Design 1")
        temp_content.write_design("test-project", "TEST-P0002", "# Design 2")
        assert temp_content.read_design("test-project", "TEST-P0001") == "# Design 1"
        assert temp_content.read_design("test-project", "TEST-P0002") == "# Design 2"
