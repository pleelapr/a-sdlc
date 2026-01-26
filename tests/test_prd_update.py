"""Tests for PRD update functionality."""

import pytest
from datetime import datetime
from a_sdlc.artifacts.prd import (
    PRD,
    parse_version,
    bump_version,
    extract_sections,
    update_section,
    detect_change_type,
)


class TestVersioning:
    """Test semantic versioning utilities."""

    def test_parse_version(self):
        """Test version string parsing."""
        assert parse_version("1.2.3") == (1, 2, 3)
        assert parse_version("0.1.0") == (0, 1, 0)
        assert parse_version("10.20.30") == (10, 20, 30)

    def test_bump_major(self):
        """Test major version bump."""
        assert bump_version("1.2.3", "major") == "2.0.0"
        assert bump_version("0.5.1", "major") == "1.0.0"
        assert bump_version("9.9.9", "major") == "10.0.0"

    def test_bump_minor(self):
        """Test minor version bump."""
        assert bump_version("1.2.3", "minor") == "1.3.0"
        assert bump_version("0.0.1", "minor") == "0.1.0"
        assert bump_version("2.9.5", "minor") == "2.10.0"

    def test_bump_patch(self):
        """Test patch version bump."""
        assert bump_version("1.2.3", "patch") == "1.2.4"
        assert bump_version("0.0.0", "patch") == "0.0.1"
        assert bump_version("1.0.9", "patch") == "1.0.10"


class TestSectionParsing:
    """Test markdown section parsing."""

    def test_extract_sections_simple(self):
        """Test basic section extraction."""
        markdown = "## Overview\nContent here\n## Goals\nGoal content"
        sections = extract_sections(markdown)

        assert "Overview" in sections
        assert "Goals" in sections
        assert sections["Overview"] == "Content here"
        assert sections["Goals"] == "Goal content"

    def test_extract_sections_multiline(self):
        """Test section extraction with multiple lines."""
        markdown = """## Overview
Line 1
Line 2
Line 3

## Goals
Goal 1
Goal 2"""
        sections = extract_sections(markdown)

        assert "Overview" in sections
        assert "Line 1" in sections["Overview"]
        assert "Line 3" in sections["Overview"]
        assert "Goal 1" in sections["Goals"]

    def test_extract_sections_empty(self):
        """Test extraction from content without sections."""
        markdown = "Just some content\nNo sections here"
        sections = extract_sections(markdown)

        assert len(sections) == 0

    def test_extract_sections_with_subsections(self):
        """Test sections with subsections (### headers)."""
        markdown = """## Overview
Main content

### Subsection
Subsection content

## Goals
Goals here"""
        sections = extract_sections(markdown)

        # Should only extract ## level sections
        assert "Overview" in sections
        assert "Goals" in sections
        assert "Subsection" not in sections
        assert "### Subsection" in sections["Overview"]

    def test_update_section(self):
        """Test updating a specific section."""
        markdown = "## Overview\nOld content\n## Goals\nGoal content"
        updated = update_section(markdown, "Overview", "New content")

        assert "New content" in updated
        assert "Old content" not in updated
        # Goals should remain unchanged
        assert "Goal content" in updated

    def test_update_section_not_found(self):
        """Test updating non-existent section."""
        markdown = "## Overview\nContent"

        with pytest.raises(KeyError, match="Section not found"):
            update_section(markdown, "NonExistent", "New content")

    def test_update_section_preserves_order(self):
        """Test that section order is preserved."""
        markdown = "## First\nContent 1\n## Second\nContent 2\n## Third\nContent 3"
        updated = update_section(markdown, "Second", "New content 2")

        lines = updated.split("\n")
        first_idx = next(i for i, line in enumerate(lines) if "First" in line)
        second_idx = next(i for i, line in enumerate(lines) if "Second" in line)
        third_idx = next(i for i, line in enumerate(lines) if "Third" in line)

        assert first_idx < second_idx < third_idx


class TestChangeDetection:
    """Test change type detection."""

    def test_detect_structural_change_added_section(self):
        """Test detection when section is added."""
        original = "## Overview\nContent"
        updated = "## Overview\nContent\n## New Section\nNew content"

        assert detect_change_type(original, updated) == "structural"

    def test_detect_structural_change_removed_section(self):
        """Test detection when section is removed."""
        original = "## Overview\nContent\n## Goals\nGoals"
        updated = "## Overview\nContent"

        assert detect_change_type(original, updated) == "structural"

    def test_detect_content_change(self):
        """Test detection of significant content changes."""
        original = "## Overview\nShort content"
        updated = "## Overview\n" + "Long content " * 50  # >200 chars difference

        assert detect_change_type(original, updated) == "content"

    def test_detect_typo(self):
        """Test detection of minor text changes."""
        original = "## Overview\nThis is content with a typo"
        updated = "## Overview\nThis is content with a correction"

        assert detect_change_type(original, updated) == "typo"


class TestPRDClassMethods:
    """Test PRD class methods for updates."""

    def test_get_sections(self):
        """Test PRD get_sections method."""
        prd = PRD(
            id="test",
            title="Test",
            content="## Overview\nContent\n## Goals\nGoals",
        )

        sections = prd.get_sections()

        assert "Overview" in sections
        assert "Goals" in sections

    def test_update_section_content(self):
        """Test PRD update_section_content method."""
        prd = PRD(
            id="test",
            title="Test",
            content="## Overview\nOld\n## Goals\nGoals",
        )

        original_time = prd.updated_at
        prd.update_section_content("Overview", "New content")

        assert "New content" in prd.content
        assert "Old" not in prd.content
        assert prd.updated_at >= original_time

    def test_bump_version_auto(self):
        """Test PRD bump_version_auto method."""
        prd = PRD(
            id="test",
            title="Test",
            content="Content",
            version="1.0.0",
        )

        prd.bump_version_auto("minor")

        assert prd.version == "1.1.0"

    def test_bump_version_auto_updates_timestamp(self):
        """Test that version bump updates timestamp."""
        prd = PRD(
            id="test",
            title="Test",
            content="Content",
            version="1.0.0",
        )

        original_time = prd.updated_at
        prd.bump_version_auto("patch")

        assert prd.updated_at >= original_time


class TestPRDLocalUpdateHistory:
    """Test LocalPRDPlugin update history tracking."""

    def test_add_update_history(self, tmp_path):
        """Test adding update history entry."""
        from a_sdlc.artifacts.prd_local import LocalPRDPlugin

        plugin = LocalPRDPlugin({"prds_dir": str(tmp_path)})

        prd = PRD(
            id="test-prd",
            title="Test PRD",
            content="## Overview\nContent",
            version="1.0.0",
        )
        plugin.store_prd(prd)

        # Add update history
        plugin.add_update_history(
            prd_id="test-prd",
            version="1.1.0",
            change_type="minor",
            sections_modified=["Overview", "Goals"],
            summary="Updated overview and goals",
        )

        # Verify metadata
        history = plugin.get_update_history("test-prd")
        assert len(history) == 1
        assert history[0]["version"] == "1.1.0"
        assert history[0]["change_type"] == "minor"
        assert "Overview" in history[0]["sections_modified"]
        assert history[0]["summary"] == "Updated overview and goals"

    def test_multiple_update_history_entries(self, tmp_path):
        """Test multiple update history entries."""
        from a_sdlc.artifacts.prd_local import LocalPRDPlugin

        plugin = LocalPRDPlugin({"prds_dir": str(tmp_path)})

        prd = PRD(
            id="test-prd",
            title="Test PRD",
            content="Content",
            version="1.0.0",
        )
        plugin.store_prd(prd)

        # Add multiple updates
        plugin.add_update_history(
            prd_id="test-prd",
            version="1.1.0",
            change_type="minor",
            sections_modified=["Overview"],
            summary="First update",
        )

        plugin.add_update_history(
            prd_id="test-prd",
            version="1.2.0",
            change_type="minor",
            sections_modified=["Goals"],
            summary="Second update",
        )

        # Verify multiple entries
        history = plugin.get_update_history("test-prd")
        assert len(history) == 2
        assert history[0]["summary"] == "First update"
        assert history[1]["summary"] == "Second update"

    def test_get_update_history_empty(self, tmp_path):
        """Test getting history for PRD with no updates."""
        from a_sdlc.artifacts.prd_local import LocalPRDPlugin

        plugin = LocalPRDPlugin({"prds_dir": str(tmp_path)})

        history = plugin.get_update_history("nonexistent")
        assert history == []


class TestIntegration:
    """Integration tests for full update workflow."""

    def test_full_update_workflow(self, tmp_path):
        """Test complete update workflow."""
        from a_sdlc.artifacts.prd_local import LocalPRDPlugin

        plugin = LocalPRDPlugin({"prds_dir": str(tmp_path)})

        # Create initial PRD
        prd = PRD(
            id="feature-auth",
            title="Authentication Feature",
            content="## Overview\nOriginal content\n## Goals\nOriginal goals",
            version="1.0.0",
        )
        plugin.store_prd(prd)

        # Load and update
        loaded_prd = plugin.get_prd("feature-auth")
        assert loaded_prd is not None

        # Update a section
        loaded_prd.update_section_content("Overview", "Updated content")

        # Bump version
        loaded_prd.bump_version_auto("minor")

        # Save
        plugin.store_prd(loaded_prd)

        # Track history
        plugin.add_update_history(
            prd_id="feature-auth",
            version=loaded_prd.version,
            change_type="minor",
            sections_modified=["Overview"],
            summary="Updated overview section",
        )

        # Verify final state
        final_prd = plugin.get_prd("feature-auth")
        assert final_prd is not None
        assert final_prd.version == "1.1.0"
        assert "Updated content" in final_prd.content

        history = plugin.get_update_history("feature-auth")
        assert len(history) == 1
        assert history[0]["version"] == "1.1.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
