"""Tests for init file generation (CLAUDE.md, lesson-learn.md)."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from a_sdlc.core.init_files import (
    _load_template,
    ensure_global_lesson_learn,
    generate_claude_md,
    generate_init_files,
    generate_lesson_learn,
)


@pytest.fixture
def temp_project():
    """Create a temporary project directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_global_dir():
    """Create a temporary global directory for ~/.a-sdlc/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("a_sdlc.core.init_files.get_data_dir", return_value=Path(tmpdir)):
            yield Path(tmpdir)


class TestLoadTemplate:
    """Tests for _load_template."""

    def test_loads_claude_md_template(self):
        content = _load_template("claude-md.template.md")
        assert "CLAUDE.md" in content
        assert "{{PROJECT_OVERVIEW}}" in content

    def test_loads_lesson_learn_template(self):
        content = _load_template("lesson-learn.template.md")
        assert "Lessons Learned" in content
        assert "MUST" in content
        assert "SHOULD" in content
        assert "MAY" in content

    def test_raises_for_missing_template(self):
        with pytest.raises(FileNotFoundError):
            _load_template("nonexistent-template.md")


class TestGenerateClaudeMd:
    """Tests for generate_claude_md."""

    def test_creates_claude_md(self, temp_project):
        result = generate_claude_md(temp_project, "My Project")
        assert result["status"] == "created"
        claude_md = temp_project / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "My Project" in content
        assert "lesson-learn" in content.lower()

    def test_skips_existing_claude_md(self, temp_project):
        claude_md = temp_project / "CLAUDE.md"
        claude_md.write_text("# Existing CLAUDE.md")

        result = generate_claude_md(temp_project, "My Project")
        assert result["status"] == "exists"
        assert claude_md.read_text() == "# Existing CLAUDE.md"

    def test_overwrites_when_forced(self, temp_project):
        claude_md = temp_project / "CLAUDE.md"
        claude_md.write_text("# Old content")

        result = generate_claude_md(temp_project, "My Project", overwrite=True)
        assert result["status"] == "created"
        assert "My Project" in claude_md.read_text()

    def test_contains_asdlc_managed_marker(self, temp_project):
        generate_claude_md(temp_project, "Test Project")
        content = (temp_project / "CLAUDE.md").read_text()
        assert "<!-- a-sdlc:managed -->" in content

    def test_contains_lesson_learn_references(self, temp_project):
        generate_claude_md(temp_project, "Test Project")
        content = (temp_project / "CLAUDE.md").read_text()
        assert ".sdlc/lesson-learn.md" in content
        assert "~/.a-sdlc/lesson-learn.md" in content

    def test_contains_corrections_log_reference(self, temp_project):
        generate_claude_md(temp_project, "Test Project")
        content = (temp_project / "CLAUDE.md").read_text()
        assert "corrections.log" in content

    def test_contains_sdlc_help_reference(self, temp_project):
        generate_claude_md(temp_project, "Test Project")
        content = (temp_project / "CLAUDE.md").read_text()
        assert "/sdlc:help" in content


class TestGenerateLessonLearn:
    """Tests for generate_lesson_learn."""

    def test_creates_lesson_learn(self, temp_project):
        result = generate_lesson_learn(temp_project)
        assert result["status"] == "created"
        lesson_file = temp_project / ".sdlc" / "lesson-learn.md"
        assert lesson_file.exists()
        content = lesson_file.read_text()
        assert "Lessons Learned" in content

    def test_creates_sdlc_directory(self, temp_project):
        generate_lesson_learn(temp_project)
        assert (temp_project / ".sdlc").is_dir()

    def test_skips_existing_lesson_learn(self, temp_project):
        sdlc_dir = temp_project / ".sdlc"
        sdlc_dir.mkdir()
        lesson_file = sdlc_dir / "lesson-learn.md"
        lesson_file.write_text("# Existing lessons")

        result = generate_lesson_learn(temp_project)
        assert result["status"] == "exists"
        assert lesson_file.read_text() == "# Existing lessons"

    def test_overwrites_when_forced(self, temp_project):
        sdlc_dir = temp_project / ".sdlc"
        sdlc_dir.mkdir()
        lesson_file = sdlc_dir / "lesson-learn.md"
        lesson_file.write_text("# Old")

        result = generate_lesson_learn(temp_project, overwrite=True)
        assert result["status"] == "created"
        assert "Lessons Learned" in lesson_file.read_text()

    def test_contains_categories(self, temp_project):
        generate_lesson_learn(temp_project)
        content = (temp_project / ".sdlc" / "lesson-learn.md").read_text()
        assert "## Testing" in content
        assert "## Code Quality" in content
        assert "## Task Completeness" in content
        assert "## Integration" in content
        assert "## Documentation" in content


class TestEnsureGlobalLessonLearn:
    """Tests for ensure_global_lesson_learn."""

    def test_creates_global_lesson_learn(self, temp_global_dir):
        result = ensure_global_lesson_learn()
        assert result["status"] == "created"
        global_file = temp_global_dir / "lesson-learn.md"
        assert global_file.exists()
        assert "Lessons Learned" in global_file.read_text()

    def test_skips_if_exists(self, temp_global_dir):
        global_file = temp_global_dir / "lesson-learn.md"
        global_file.write_text("# Global lessons")

        result = ensure_global_lesson_learn()
        assert result["status"] == "exists"
        assert global_file.read_text() == "# Global lessons"


class TestGenerateInitFiles:
    """Tests for generate_init_files orchestrator."""

    def test_generates_all_files(self, temp_project, temp_global_dir):
        result = generate_init_files(temp_project, "My Project")
        assert len(result["results"]) == 3

        statuses = [r["status"] for r in result["results"]]
        assert statuses == ["created", "created", "created"]

        assert (temp_project / "CLAUDE.md").exists()
        assert (temp_project / ".sdlc" / "lesson-learn.md").exists()
        assert (temp_global_dir / "lesson-learn.md").exists()

    def test_idempotent_on_second_run(self, temp_project, temp_global_dir):
        generate_init_files(temp_project, "My Project")
        result = generate_init_files(temp_project, "My Project")

        statuses = [r["status"] for r in result["results"]]
        assert statuses == ["exists", "exists", "exists"]

    def test_preserves_existing_files(self, temp_project, temp_global_dir):
        # Pre-create files with custom content
        (temp_project / "CLAUDE.md").write_text("# Custom CLAUDE")
        sdlc_dir = temp_project / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "lesson-learn.md").write_text("# Custom lessons")

        generate_init_files(temp_project, "My Project")

        assert (temp_project / "CLAUDE.md").read_text() == "# Custom CLAUDE"
        assert (sdlc_dir / "lesson-learn.md").read_text() == "# Custom lessons"
