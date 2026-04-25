"""Tests for markdown-to-TOML transpiler."""

import time
from importlib import resources
from pathlib import Path

from a_sdlc.transpiler import (
    TranspiledCommand,
    _apply_tool_replacements,
    _escape_toml_multiline,
    _extract_description,
    transpile_all,
    transpile_template,
    write_toml,
)

# Sample template content for testing
SIMPLE_TEMPLATE = """# /sdlc:prd-list

## Purpose

List all PRDs for the current project.

## Usage

Use the MCP tool to list PRDs:

```
mcp__asdlc__list_prds()
```

Display results in a table format.
"""

TEMPLATE_WITH_TOOLS = """# /sdlc:task-start

## Purpose

Start working on a specific task.

## Steps

1. Use Read(file_path) to read the task file
2. Use AskUserQuestion to confirm the approach
3. Use TodoWrite to create a checklist
4. Use Write(file_path, content) to update files
5. Use Edit(file_path, old, new) to modify code
6. Call mcp__asdlc__update_task(task_id, status="in_progress")
7. Use TaskCreate to note subtasks
8. Use TaskUpdate to mark progress
"""


class TestExtractDescription:
    """Tests for _extract_description()."""

    def test_extracts_first_line_after_purpose(self):
        result = _extract_description(SIMPLE_TEMPLATE)
        assert result == "List all PRDs for the current project."

    def test_empty_for_no_purpose_section(self):
        content = "# Title\n\n## Usage\n\nSome usage text."
        result = _extract_description(content)
        assert result == ""

    def test_skips_empty_lines(self):
        content = "## Purpose\n\n\n  \nActual description here."
        result = _extract_description(content)
        assert result == "Actual description here."

    def test_stops_at_next_heading(self):
        content = "## Purpose\n\n## Next Section\n\nNot this."
        result = _extract_description(content)
        assert result == ""


class TestApplyToolReplacements:
    """Tests for _apply_tool_replacements()."""

    def test_replaces_ask_user_question(self):
        result = _apply_tool_replacements("Use AskUserQuestion to get input")
        assert "AskUserQuestion" not in result
        assert "ask the user for their choice" in result

    def test_replaces_write(self):
        result = _apply_tool_replacements("Use Write(file_path) to save")
        assert "Write(" not in result
        assert "write to the file at" in result

    def test_replaces_edit(self):
        result = _apply_tool_replacements("Use Edit(file_path) to modify")
        assert "Edit(" not in result
        assert "edit the file at" in result

    def test_replaces_read(self):
        result = _apply_tool_replacements("Use Read(file_path) to view")
        assert "Read(" not in result
        assert "read the file at" in result

    def test_replaces_todo_write(self):
        result = _apply_tool_replacements("Use TodoWrite for tasks")
        assert "TodoWrite" not in result
        assert "track the following tasks" in result

    def test_replaces_task_create(self):
        result = _apply_tool_replacements("Use TaskCreate for new task")
        assert "TaskCreate" not in result
        assert "note the following task" in result

    def test_replaces_task_update(self):
        result = _apply_tool_replacements("Use TaskUpdate for status")
        assert "TaskUpdate" not in result
        assert "update the task status" in result

    def test_preserves_mcp_asdlc_references(self):
        text = "Call mcp__asdlc__list_prds() and mcp__asdlc__get_task()"
        result = _apply_tool_replacements(text)
        assert "mcp__asdlc__list_prds()" in result
        assert "mcp__asdlc__get_task()" in result

    def test_preserves_non_tool_text(self):
        text = "This is normal text without any tool references."
        result = _apply_tool_replacements(text)
        assert result == text

    def test_multiple_replacements_in_one_template(self):
        result = _apply_tool_replacements(TEMPLATE_WITH_TOOLS)
        assert "AskUserQuestion" not in result
        assert "TodoWrite" not in result
        assert "Write(" not in result
        assert "Edit(" not in result
        assert "Read(" not in result
        assert "TaskCreate" not in result
        assert "TaskUpdate" not in result
        assert "mcp__asdlc__update_task" in result


class TestEscapeTomlMultiline:
    """Tests for _escape_toml_multiline()."""

    def test_no_special_chars(self):
        text = 'Normal text with "double quotes"'
        assert _escape_toml_multiline(text) == text

    def test_triple_quotes_escaped(self):
        text = 'Has """triple""" quotes'
        result = _escape_toml_multiline(text)
        assert '"""' not in result

    def test_backslashes_escaped(self):
        text = r"Has \`\`\` escaped backticks"
        result = _escape_toml_multiline(text)
        assert "\\\\" in result
        assert result == r"Has \\`\\`\\` escaped backticks"

    def test_backslash_before_triple_quotes(self):
        text = 'Slash \\ then """triple"""'
        result = _escape_toml_multiline(text)
        assert '"""' not in result
        assert "\\\\" in result


class TestTranspileTemplate:
    """Tests for transpile_template()."""

    def test_name_from_filename(self, tmp_path):
        md_file = tmp_path / "prd-list.md"
        md_file.write_text(SIMPLE_TEMPLATE)
        result = transpile_template(md_file)
        assert result.name == "prd-list"

    def test_description_extracted(self, tmp_path):
        md_file = tmp_path / "prd-list.md"
        md_file.write_text(SIMPLE_TEMPLATE)
        result = transpile_template(md_file)
        assert result.description == "List all PRDs for the current project."

    def test_tools_replaced_in_prompt(self, tmp_path):
        md_file = tmp_path / "task-start.md"
        md_file.write_text(TEMPLATE_WITH_TOOLS)
        result = transpile_template(md_file)
        assert "AskUserQuestion" not in result.prompt
        assert "mcp__asdlc__update_task" in result.prompt

    def test_args_appended(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text(SIMPLE_TEMPLATE)
        result = transpile_template(md_file)
        assert "{{args}}" in result.prompt

    def test_source_path_stored(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text(SIMPLE_TEMPLATE)
        result = transpile_template(md_file)
        assert result.source_path == md_file

    def test_mcp_references_preserved(self, tmp_path):
        md_file = tmp_path / "test.md"
        md_file.write_text(SIMPLE_TEMPLATE)
        result = transpile_template(md_file)
        assert "mcp__asdlc__list_prds()" in result.prompt


class TestWriteToml:
    """Tests for write_toml()."""

    def test_creates_toml_file(self, tmp_path):
        command = TranspiledCommand(
            name="test-cmd",
            description="A test command",
            prompt="Do the thing.\n\n{{args}}\n",
            source_path=Path("/fake/test-cmd.md"),
        )
        path = write_toml(command, tmp_path)
        assert path.exists()
        assert path.name == "test-cmd.toml"

    def test_toml_has_description(self, tmp_path):
        command = TranspiledCommand(
            name="test",
            description="Test description",
            prompt="prompt text\n\n{{args}}\n",
            source_path=Path("/fake/test.md"),
        )
        write_toml(command, tmp_path)
        content = (tmp_path / "test.toml").read_text(encoding="utf-8")
        assert 'description = "Test description"' in content

    def test_toml_has_prompt(self, tmp_path):
        command = TranspiledCommand(
            name="test",
            description="Test",
            prompt="prompt body\n\n{{args}}\n",
            source_path=Path("/fake/test.md"),
        )
        write_toml(command, tmp_path)
        content = (tmp_path / "test.toml").read_text(encoding="utf-8")
        assert 'prompt = """' in content
        assert "prompt body" in content

    def test_creates_target_dir(self, tmp_path):
        target = tmp_path / "new" / "dir"
        command = TranspiledCommand(
            name="test",
            description="Test",
            prompt="body\n\n{{args}}\n",
            source_path=Path("/fake/test.md"),
        )
        write_toml(command, target)
        assert target.exists()

    def test_description_with_quotes_escaped(self, tmp_path):
        command = TranspiledCommand(
            name="test",
            description='Has "quotes" inside',
            prompt="body\n\n{{args}}\n",
            source_path=Path("/fake/test.md"),
        )
        write_toml(command, tmp_path)
        content = (tmp_path / "test.toml").read_text(encoding="utf-8")
        assert '\\"quotes\\"' in content


class TestTranspileAll:
    """Tests for transpile_all()."""

    def test_processes_all_md_files(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        (source / "cmd-a.md").write_text("## Purpose\n\nCommand A.\n\nBody A.")
        (source / "cmd-b.md").write_text("## Purpose\n\nCommand B.\n\nBody B.")

        names = transpile_all(source, target)
        assert sorted(names) == ["cmd-a", "cmd-b"]
        assert (target / "cmd-a.toml").exists()
        assert (target / "cmd-b.toml").exists()

    def test_skips_underscore_prefixed(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        (source / "public.md").write_text("## Purpose\n\nPublic.\n\nBody.")
        (source / "_internal.md").write_text("## Purpose\n\nInternal.\n\nBody.")

        names = transpile_all(source, target)
        assert names == ["public"]
        assert (target / "public.toml").exists()
        assert not (target / "_internal.toml").exists()

    def test_returns_sorted_names(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        (source / "z-cmd.md").write_text("## Purpose\n\nZ.\n\nBody.")
        (source / "a-cmd.md").write_text("## Purpose\n\nA.\n\nBody.")

        names = transpile_all(source, target)
        assert names == ["a-cmd", "z-cmd"]

    def test_empty_source_dir(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        names = transpile_all(source, target)
        assert names == []

    def test_skips_non_md_files(self, tmp_path):
        source = tmp_path / "source"
        source.mkdir()
        target = tmp_path / "target"

        (source / "cmd.md").write_text("## Purpose\n\nCmd.\n\nBody.")
        (source / "readme.txt").write_text("not a template")
        (source / ".version").write_text("0.1.0")

        names = transpile_all(source, target)
        assert names == ["cmd"]


class TestFullCatalogTranspilation:
    """Integration tests validating transpilation against all real templates."""

    @staticmethod
    def _get_template_dir() -> Path:
        """Get the actual bundled template directory."""
        try:
            return Path(str(resources.files("a_sdlc").joinpath("templates")))
        except (TypeError, AttributeError):
            return Path(__file__).parent.parent / "src" / "a_sdlc" / "templates"

    def test_all_templates_transpile_without_errors(self, tmp_path):
        """All deployable templates should transpile successfully."""
        template_dir = self._get_template_dir()
        names = transpile_all(template_dir, tmp_path)
        assert len(names) >= 40  # At least 40 deployable templates

    def test_correct_file_count(self, tmp_path):
        """Transpiled count should match deployable template count."""
        template_dir = self._get_template_dir()
        # Count deployable .md files (exclude underscore-prefixed)
        deployable = [f for f in template_dir.glob("*.md") if not f.name.startswith("_")]
        names = transpile_all(template_dir, tmp_path)
        assert len(names) == len(deployable)

    def test_no_claude_tool_names_in_output(self, tmp_path):
        """No Claude-specific tool names should remain in transpiled output."""
        template_dir = self._get_template_dir()
        transpile_all(template_dir, tmp_path)

        claude_tools = ["AskUserQuestion", "TodoWrite"]
        for toml_file in tmp_path.glob("*.toml"):
            content = toml_file.read_text(encoding="utf-8")
            for tool in claude_tools:
                assert tool not in content, (
                    f"Claude tool '{tool}' found in {toml_file.name}"
                )

    def test_mcp_references_preserved(self, tmp_path):
        """All mcp__asdlc__ references should be preserved in output."""
        template_dir = self._get_template_dir()
        transpile_all(template_dir, tmp_path)

        # Check a few known templates that use MCP calls
        for name in ["prd-list", "task-list", "sprint-show"]:
            toml_file = tmp_path / f"{name}.toml"
            if toml_file.exists():
                content = toml_file.read_text(encoding="utf-8")
                assert "mcp__asdlc__" in content, (
                    f"MCP references missing in {name}.toml"
                )

    def test_args_in_every_output(self, tmp_path):
        """Every transpiled file must contain {{args}}."""
        template_dir = self._get_template_dir()
        transpile_all(template_dir, tmp_path)

        for toml_file in tmp_path.glob("*.toml"):
            content = toml_file.read_text(encoding="utf-8")
            assert "{{args}}" in content, (
                f"{{{{args}}}} missing in {toml_file.name}"
            )

    def test_description_in_every_output(self, tmp_path):
        """Every transpiled file must have a description field."""
        template_dir = self._get_template_dir()
        transpile_all(template_dir, tmp_path)

        for toml_file in tmp_path.glob("*.toml"):
            content = toml_file.read_text(encoding="utf-8")
            assert content.startswith('description = "'), (
                f"Missing description in {toml_file.name}"
            )

    def test_toml_structure_in_every_output(self, tmp_path):
        """Every output must have both description and prompt fields."""
        template_dir = self._get_template_dir()
        transpile_all(template_dir, tmp_path)

        for toml_file in tmp_path.glob("*.toml"):
            content = toml_file.read_text(encoding="utf-8")
            assert 'description = "' in content, f"No description in {toml_file.name}"
            assert 'prompt = """' in content, f"No prompt in {toml_file.name}"

    def test_performance_under_five_seconds(self, tmp_path):
        """Full transpilation must complete in <5 seconds (NFR-001)."""
        template_dir = self._get_template_dir()
        start = time.perf_counter()
        transpile_all(template_dir, tmp_path)
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, f"Transpilation took {elapsed:.2f}s (limit: 5s)"

    def test_core_workflows_transpile(self, tmp_path):
        """5 core workflow templates must transpile correctly (AC-004)."""
        template_dir = self._get_template_dir()
        transpile_all(template_dir, tmp_path)

        core_workflows = ["init", "prd-generate", "prd-split", "task-start", "sprint-run"]
        for name in core_workflows:
            toml_file = tmp_path / f"{name}.toml"
            assert toml_file.exists(), f"Core workflow {name}.toml not found"
            content = toml_file.read_text(encoding="utf-8")
            # Should have valid structure
            assert 'description = "' in content
            assert 'prompt = """' in content
            # Should have some content (not empty prompt)
            assert len(content) > 100, f"{name}.toml seems too short"

    def test_output_files_are_toml_not_md(self, tmp_path):
        """Output should be .toml files, not .md files."""
        template_dir = self._get_template_dir()
        transpile_all(template_dir, tmp_path)

        toml_files = list(tmp_path.glob("*.toml"))
        md_files = list(tmp_path.glob("*.md"))
        assert len(toml_files) > 0, "No .toml files produced"
        assert len(md_files) == 0, "Should not produce .md files"

    def test_all_output_files_are_valid_toml(self, tmp_path):
        """Every transpiled file must be parseable as valid TOML."""
        import tomllib

        template_dir = self._get_template_dir()
        transpile_all(template_dir, tmp_path)

        for toml_file in tmp_path.glob("*.toml"):
            content = toml_file.read_text(encoding="utf-8")
            try:
                parsed = tomllib.loads(content)
            except tomllib.TOMLDecodeError as e:
                raise AssertionError(
                    f"{toml_file.name} is not valid TOML: {e}"
                ) from e
            assert "description" in parsed, f"{toml_file.name} missing description"
            assert "prompt" in parsed, f"{toml_file.name} missing prompt"
