"""Tests for init file generation (CLAUDE.md, lesson-learn.md, config.yaml)."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from a_sdlc.cli_targets import CLAUDE_TARGET, GEMINI_TARGET
from a_sdlc.core.init_files import (
    _extract_template_sections,
    _load_template,
    ensure_global_lesson_learn,
    generate_claude_md,
    generate_config_yaml,
    generate_context_file,
    generate_gemini_md,
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
    with (
        tempfile.TemporaryDirectory() as tmpdir,
        patch("a_sdlc.core.init_files.get_data_dir", return_value=Path(tmpdir)),
    ):
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

    def test_loads_config_template(self):
        content = _load_template("config.template.yaml")
        assert "testing:" in content
        assert "review:" in content
        assert "git:" in content
        assert "sprint:" in content

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


class TestGenerateConfigYaml:
    """Tests for generate_config_yaml."""

    def test_creates_config_yaml(self, temp_project):
        result = generate_config_yaml(temp_project)
        assert result["status"] == "created"
        config_file = temp_project / ".sdlc" / "config.yaml"
        assert config_file.exists()

    def test_creates_sdlc_directory(self, temp_project):
        generate_config_yaml(temp_project)
        assert (temp_project / ".sdlc").is_dir()

    def test_skips_existing_complete_config(self, temp_project):
        """When existing config has all template sections, returns 'exists'."""
        sdlc_dir = temp_project / ".sdlc"
        sdlc_dir.mkdir()
        config_file = sdlc_dir / "config.yaml"
        # Write a complete config using the template itself
        template = _load_template("config.template.yaml")
        config_file.write_text(template, encoding="utf-8")

        result = generate_config_yaml(temp_project)
        assert result["status"] == "exists"

    def test_overwrites_when_forced(self, temp_project):
        sdlc_dir = temp_project / ".sdlc"
        sdlc_dir.mkdir()
        config_file = sdlc_dir / "config.yaml"
        config_file.write_text("old: true")

        result = generate_config_yaml(temp_project, overwrite=True)
        assert result["status"] == "created"
        assert "testing:" in config_file.read_text()

    def test_contains_testing_section(self, temp_project):
        generate_config_yaml(temp_project)
        content = (temp_project / ".sdlc" / "config.yaml").read_text()
        assert "testing:" in content
        assert "commands:" in content
        assert "coverage:" in content
        assert "relevance:" in content

    def test_contains_review_section(self, temp_project):
        generate_config_yaml(temp_project)
        content = (temp_project / ".sdlc" / "config.yaml").read_text()
        assert "review:" in content
        assert "enabled: false" in content  # master toggle defaults off
        assert "self_review:" in content
        assert "subagent_review:" in content
        assert "max_rounds:" in content
        assert "evidence_required:" in content

    def test_contains_git_section(self, temp_project):
        generate_config_yaml(temp_project)
        content = (temp_project / ".sdlc" / "config.yaml").read_text()
        assert "git:" in content
        assert "auto_commit:" in content
        assert "auto_pr:" in content
        assert "auto_merge:" in content
        assert "worktree_enabled:" in content

    def test_has_yaml_comments(self, temp_project):
        generate_config_yaml(temp_project)
        content = (temp_project / ".sdlc" / "config.yaml").read_text()
        assert "#" in content

    def test_is_valid_yaml(self, temp_project):
        generate_config_yaml(temp_project)
        content = (temp_project / ".sdlc" / "config.yaml").read_text()
        parsed = yaml.safe_load(content)
        assert "testing" in parsed
        assert "review" in parsed
        assert "git" in parsed
        assert "sprint" in parsed


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
        result = generate_init_files(temp_project, "My Project", targets=[CLAUDE_TARGET])
        assert len(result["results"]) == 4

        statuses = [r["status"] for r in result["results"]]
        assert statuses == ["created", "created", "created", "created"]

        assert (temp_project / "CLAUDE.md").exists()
        assert (temp_project / ".sdlc" / "lesson-learn.md").exists()
        assert (temp_project / ".sdlc" / "config.yaml").exists()
        assert (temp_global_dir / "lesson-learn.md").exists()

    def test_idempotent_on_second_run(self, temp_project, temp_global_dir):
        generate_init_files(temp_project, "My Project", targets=[CLAUDE_TARGET])
        result = generate_init_files(temp_project, "My Project", targets=[CLAUDE_TARGET])

        statuses = [r["status"] for r in result["results"]]
        assert statuses == ["exists", "exists", "exists", "exists"]

    def test_preserves_existing_files(self, temp_project, temp_global_dir):
        # Pre-create files with custom content
        (temp_project / "CLAUDE.md").write_text("# Custom CLAUDE")
        sdlc_dir = temp_project / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "lesson-learn.md").write_text("# Custom lessons")

        generate_init_files(temp_project, "My Project", targets=[CLAUDE_TARGET])

        assert (temp_project / "CLAUDE.md").read_text() == "# Custom CLAUDE"
        assert (sdlc_dir / "lesson-learn.md").read_text() == "# Custom lessons"


class TestGenerateGeminiMd:
    """Tests for generate_gemini_md()."""

    def test_creates_gemini_md(self, tmp_path):
        result = generate_gemini_md(tmp_path, "Test Project")
        assert result["status"] == "created"
        gemini_path = tmp_path / "GEMINI.md"
        assert gemini_path.exists()

    def test_replaces_project_overview(self, tmp_path):
        generate_gemini_md(tmp_path, "My Project")
        content = (tmp_path / "GEMINI.md").read_text()
        assert "My Project" in content
        assert "{{PROJECT_OVERVIEW}}" not in content

    def test_replaces_dev_commands(self, tmp_path):
        generate_gemini_md(tmp_path, "Test")
        content = (tmp_path / "GEMINI.md").read_text()
        assert "{{DEVELOPMENT_COMMANDS}}" not in content

    def test_contains_managed_marker(self, tmp_path):
        generate_gemini_md(tmp_path, "Test")
        content = (tmp_path / "GEMINI.md").read_text()
        assert "<!-- a-sdlc:managed -->" in content

    def test_contains_gemini_reference(self, tmp_path):
        generate_gemini_md(tmp_path, "Test")
        content = (tmp_path / "GEMINI.md").read_text()
        assert "Gemini CLI" in content

    def test_skips_if_exists(self, tmp_path):
        (tmp_path / "GEMINI.md").write_text("existing")
        result = generate_gemini_md(tmp_path, "Test")
        assert result["status"] == "exists"
        assert (tmp_path / "GEMINI.md").read_text() == "existing"

    def test_overwrites_if_flag_set(self, tmp_path):
        (tmp_path / "GEMINI.md").write_text("old")
        result = generate_gemini_md(tmp_path, "Test", overwrite=True)
        assert result["status"] == "created"
        assert "Gemini CLI" in (tmp_path / "GEMINI.md").read_text()


class TestGenerateContextFile:
    """Tests for generate_context_file()."""

    def test_claude_target_generates_claude_md(self, tmp_path):
        generate_context_file(tmp_path, "Test", CLAUDE_TARGET)
        assert (tmp_path / "CLAUDE.md").exists()

    def test_gemini_target_generates_gemini_md(self, tmp_path):
        generate_context_file(tmp_path, "Test", GEMINI_TARGET)
        assert (tmp_path / "GEMINI.md").exists()


class TestGenerateInitFilesMultiTarget:
    """Tests for multi-target generate_init_files()."""

    def test_explicit_targets(self, tmp_path):
        generate_init_files(
            tmp_path, "Test", targets=[CLAUDE_TARGET, GEMINI_TARGET]
        )
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / "GEMINI.md").exists()

    def test_single_target(self, tmp_path):
        generate_init_files(
            tmp_path, "Test", targets=[GEMINI_TARGET]
        )
        assert not (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / "GEMINI.md").exists()

    def test_auto_detect_with_mock(self, tmp_path):
        with patch("a_sdlc.core.init_files.detect_targets", return_value=[CLAUDE_TARGET]):
            generate_init_files(tmp_path, "Test")
            assert (tmp_path / "CLAUDE.md").exists()


class TestExtractTemplateSections:
    """Tests for _extract_template_sections()."""

    def test_returns_all_template_keys(self):
        template = _load_template("config.template.yaml")
        sections = _extract_template_sections(template)
        parsed = yaml.safe_load(template)
        assert set(sections.keys()) == set(parsed.keys())

    def test_section_contains_its_key_line(self):
        template = _load_template("config.template.yaml")
        sections = _extract_template_sections(template)
        for key, text in sections.items():
            assert f"{key}:" in text

    def test_section_includes_preceding_comments(self):
        template = _load_template("config.template.yaml")
        sections = _extract_template_sections(template)
        # The quality section has a comment "# Quality Gates & Challenge System"
        assert sections["quality"].startswith("#")

    def test_simple_two_section_template(self):
        text = "alpha:\n  x: 1\n\n# Beta comment\nbeta:\n  y: 2\n"
        sections = _extract_template_sections(text)
        assert set(sections.keys()) == {"alpha", "beta"}
        assert "x: 1" in sections["alpha"]
        assert "# Beta comment" in sections["beta"]
        assert "y: 2" in sections["beta"]

    def test_no_sections_returns_empty(self):
        sections = _extract_template_sections("# just a comment\n")
        assert sections == {}


class TestConfigYamlUpgrade:
    """Tests for the config upgrade path in generate_config_yaml()."""

    def test_appends_missing_sections(self, temp_project):
        """An incomplete config gets missing sections appended."""
        sdlc_dir = temp_project / ".sdlc"
        sdlc_dir.mkdir()
        config_file = sdlc_dir / "config.yaml"
        # Write a minimal config with only 'testing' section
        config_file.write_text("testing:\n  defaults:\n    required:\n    - unit\n")

        result = generate_config_yaml(temp_project)
        assert result["status"] == "updated"
        assert "added_sections" in result
        assert "review" in result["added_sections"]
        assert "quality" in result["added_sections"]

        # Verify the upgraded file is valid YAML with all sections
        content = config_file.read_text()
        parsed = yaml.safe_load(content)
        template_parsed = yaml.safe_load(_load_template("config.template.yaml"))
        for key in template_parsed:
            assert key in parsed, f"Missing section: {key}"

    def test_preserves_existing_values(self, temp_project):
        """Existing user values must not be overwritten."""
        sdlc_dir = temp_project / ".sdlc"
        sdlc_dir.mkdir()
        config_file = sdlc_dir / "config.yaml"
        config_file.write_text(
            "testing:\n  commands:\n    unit: 'pytest tests/'\n"
        )

        generate_config_yaml(temp_project)

        content = config_file.read_text()
        parsed = yaml.safe_load(content)
        # User's custom command must survive
        assert parsed["testing"]["commands"]["unit"] == "pytest tests/"

    def test_idempotent_after_upgrade(self, temp_project):
        """Second call after upgrade returns 'exists'."""
        sdlc_dir = temp_project / ".sdlc"
        sdlc_dir.mkdir()
        config_file = sdlc_dir / "config.yaml"
        config_file.write_text("testing:\n  defaults:\n    required:\n    - unit\n")

        result1 = generate_config_yaml(temp_project)
        assert result1["status"] == "updated"

        result2 = generate_config_yaml(temp_project)
        assert result2["status"] == "exists"

    def test_overwrite_replaces_entire_file(self, temp_project):
        """overwrite=True still replaces the whole file."""
        sdlc_dir = temp_project / ".sdlc"
        sdlc_dir.mkdir()
        config_file = sdlc_dir / "config.yaml"
        config_file.write_text("custom_key: true\n")

        result = generate_config_yaml(temp_project, overwrite=True)
        assert result["status"] == "created"

        parsed = yaml.safe_load(config_file.read_text())
        assert "custom_key" not in parsed
        assert "testing" in parsed

    def test_upgrade_comment_header_present(self, temp_project):
        """Upgraded file contains the separator comment."""
        sdlc_dir = temp_project / ".sdlc"
        sdlc_dir.mkdir()
        config_file = sdlc_dir / "config.yaml"
        config_file.write_text("testing:\n  defaults:\n    required:\n    - unit\n")

        generate_config_yaml(temp_project)

        content = config_file.read_text()
        assert "Added by a-sdlc upgrade" in content

    def test_upgrade_preserves_comments_in_appended_sections(self, temp_project):
        """Appended sections retain their template comments."""
        sdlc_dir = temp_project / ".sdlc"
        sdlc_dir.mkdir()
        config_file = sdlc_dir / "config.yaml"
        config_file.write_text("testing:\n  defaults:\n    required:\n    - unit\n")

        generate_config_yaml(temp_project)

        content = config_file.read_text()
        # Quality section has a descriptive comment in the template
        assert "Quality Gates" in content
