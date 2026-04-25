"""Tests for persona loading/parsing, prompt builders, thread context, and signals.

Covers FR-001 through FR-018 and AC-001 through AC-005 from SDLC-P0031:
- FR-001: Load persona definition from markdown with YAML frontmatter
- FR-002: Extract behavioral mindset and focus areas sections
- FR-003: Persona override support (project-level > built-in)
- FR-004 through FR-010a: Phase-specific prompt builders
- FR-011 through FR-014: Signal protocol parsing
- FR-015 through FR-018: Hierarchical thread context assembly
"""

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a_sdlc.orchestrator_prompts import (
    CHARS_PER_TOKEN,
    DEFAULT_TOKEN_LIMIT,
    SIGNAL_PROTOCOL_INSTRUCTIONS,
    ThreadContext,
    ThreadEntry,
    _extract_markdown_sections,
    _format_section_header,
    _format_thread_entries,
    _minimal_persona,
    _parse_persona_frontmatter,
    assemble_thread_context,
    build_challenger_prompt,
    build_design_prompt,
    build_engineer_prompt,
    build_failure_triage_prompt,
    build_pm_prompt,
    build_qa_prompt,
    build_revision_prompt,
    build_split_prompt,
    entries_from_db_rows,
    estimate_tokens,
    format_entry,
    load_persona,
    parse_signal,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_persona_content():
    """Full persona markdown content matching the production format."""
    return textwrap.dedent("""\
        ---
        name: sdlc-test-engineer
        description: Test persona for unit tests
        category: sdlc
        tools: Read, Write, Bash
        memory: user
        ---

        # SDLC Test Engineer

        ## Triggers

        - Trigger one
        - Trigger two

        ## Behavioral Mindset

        Think carefully about testing. Every test must verify one thing.

        ## Focus Areas

        - **Unit Testing**: Write isolated unit tests.
        - **Integration Testing**: Write integration tests.

        ## Key Actions

        1. **Read Code**: Use Read tool to understand code.
        2. **Write Tests**: Use Write tool to create tests.

        ## Shared Context

        Read lesson-learn.md before starting.

        ## Outputs

        - Test files
        - Coverage reports
    """)


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory with persona override."""
    personas_dir = tmp_path / ".sdlc" / "personas"
    personas_dir.mkdir(parents=True)
    override_content = textwrap.dedent("""\
        ---
        name: sdlc-architect
        description: Project-specific architect override
        category: custom
        tools: Read, Grep
        memory: project
        ---

        # Custom Architect

        ## Triggers

        - Custom trigger

        ## Behavioral Mindset

        Custom mindset for this project.

        ## Focus Areas

        - **Custom Focus**: Project-specific focus.

        ## Key Actions

        1. **Custom Action**: Do custom things.
    """)
    (personas_dir / "sdlc-architect.md").write_text(override_content)
    return tmp_path


# ---------------------------------------------------------------------------
# TestParsePersonaFrontmatter
# ---------------------------------------------------------------------------


class TestParsePersonaFrontmatter:
    """Low-level frontmatter parser tests."""

    def test_parse_standard_frontmatter(self, sample_persona_content):
        """Parses all 5 keys from the standard persona format."""
        metadata, body = _parse_persona_frontmatter(sample_persona_content)
        assert metadata["name"] == "sdlc-test-engineer"
        assert metadata["description"] == "Test persona for unit tests"
        assert metadata["category"] == "sdlc"
        assert metadata["tools"] == "Read, Write, Bash"
        assert metadata["memory"] == "user"
        assert "# SDLC Test Engineer" in body

    def test_parse_no_frontmatter(self):
        """Content without --- markers returns ({}, full_content)."""
        content = "# Just a heading\n\nSome text."
        metadata, body = _parse_persona_frontmatter(content)
        assert metadata == {}
        assert body == content

    def test_parse_empty_string(self):
        """Empty string returns ({}, '')."""
        metadata, body = _parse_persona_frontmatter("")
        assert metadata == {}
        assert body == ""

    def test_parse_only_opening_marker(self):
        """Content with only one --- returns ({}, full_content)."""
        content = "---\nname: test\nNo closing marker"
        metadata, body = _parse_persona_frontmatter(content)
        assert metadata == {}
        assert body == content

    def test_parse_keys_normalized_to_lowercase(self):
        """Keys like Name:, TOOLS: are lowercased in the returned dict."""
        content = "---\nName: Test\nTOOLS: Read\nCategory: sdlc\n---\nBody"
        metadata, body = _parse_persona_frontmatter(content)
        assert "name" in metadata
        assert "tools" in metadata
        assert "category" in metadata
        assert metadata["name"] == "Test"
        assert metadata["tools"] == "Read"

    def test_parse_multiline_continuation(self):
        """Indented line appended to previous key's value."""
        content = "---\ndescription: A long\n  description value\nname: test\n---\nBody"
        metadata, body = _parse_persona_frontmatter(content)
        assert metadata["description"] == "A long description value"
        assert metadata["name"] == "test"

    def test_parse_value_with_colons(self):
        """Value containing colons preserves the full value after first colon."""
        content = "---\ndescription: System design: authority activated\n---\nBody"
        metadata, body = _parse_persona_frontmatter(content)
        assert metadata["description"] == "System design: authority activated"

    def test_parse_body_is_content_after_second_marker(self):
        """Body starts after the second ---."""
        content = "---\nname: test\n---\n# The Body\n\nContent here."
        metadata, body = _parse_persona_frontmatter(content)
        assert body.startswith("# The Body")
        assert "Content here." in body

    def test_parse_frontmatter_whitespace(self):
        """Extra blank lines inside frontmatter block are tolerated."""
        content = "---\nname: test\n\ntools: Read\n\n---\nBody"
        metadata, body = _parse_persona_frontmatter(content)
        assert metadata["name"] == "test"
        assert metadata["tools"] == "Read"
        assert "Body" in body


# ---------------------------------------------------------------------------
# TestExtractMarkdownSections
# ---------------------------------------------------------------------------


class TestExtractMarkdownSections:
    """Section extractor tests."""

    def test_extract_all_four_sections(self, sample_persona_content):
        """Given a full persona body, all four sections are extracted."""
        _, body = _parse_persona_frontmatter(sample_persona_content)
        sections = _extract_markdown_sections(body)
        assert "triggers" in sections
        assert "behavioral_mindset" in sections
        assert "focus_areas" in sections
        assert "key_actions" in sections

    def test_extract_preserves_markdown_formatting(self, sample_persona_content):
        """Bullet lists, bold text, and numbered lists are preserved."""
        _, body = _parse_persona_frontmatter(sample_persona_content)
        sections = _extract_markdown_sections(body)
        assert "- Trigger one" in sections["triggers"]
        assert "- Trigger two" in sections["triggers"]
        assert "**Unit Testing**" in sections["focus_areas"]
        assert "1. **Read Code**" in sections["key_actions"]

    def test_extract_missing_sections(self):
        """Body missing Key Actions returns dict without key_actions key."""
        body = textwrap.dedent("""\
            # Title

            ## Triggers

            - trigger

            ## Behavioral Mindset

            Think.

            ## Focus Areas

            - focus
        """)
        sections = _extract_markdown_sections(body)
        assert "triggers" in sections
        assert "behavioral_mindset" in sections
        assert "focus_areas" in sections
        assert "key_actions" not in sections

    def test_extract_ignores_non_target_sections(self, sample_persona_content):
        """Shared Context, Outputs, Boundaries are not extracted."""
        _, body = _parse_persona_frontmatter(sample_persona_content)
        sections = _extract_markdown_sections(body)
        assert "shared_context" not in sections
        assert "outputs" not in sections
        assert "boundaries" not in sections

    def test_extract_empty_body(self):
        """Empty string returns {}."""
        sections = _extract_markdown_sections("")
        assert sections == {}

    def test_extract_section_at_end_of_file(self):
        """Last section (no following ##) is captured correctly."""
        body = textwrap.dedent("""\
            ## Triggers

            - final trigger
        """)
        sections = _extract_markdown_sections(body)
        assert "triggers" in sections
        assert "- final trigger" in sections["triggers"]

    def test_extract_strips_whitespace(self):
        """Extracted section content has leading/trailing whitespace stripped."""
        body = "## Triggers\n\n  - item  \n\n"
        sections = _extract_markdown_sections(body)
        assert sections["triggers"] == "- item"


# ---------------------------------------------------------------------------
# TestLoadPersona
# ---------------------------------------------------------------------------


class TestLoadPersona:
    """Integration tests for the main load_persona function."""

    def test_load_builtin_architect(self):
        """load_persona('sdlc-architect') returns dict with all keys populated."""
        persona = load_persona("sdlc-architect")
        assert persona["name"] == "sdlc-architect"
        assert isinstance(persona["tools"], list)
        assert len(persona["tools"]) > 0
        assert persona["triggers"] is not None
        assert persona["behavioral_mindset"] is not None
        assert persona["focus_areas"] is not None
        assert persona["key_actions"] is not None

    @pytest.mark.parametrize(
        "persona_type",
        [
            "sdlc-architect",
            "sdlc-backend-engineer",
            "sdlc-frontend-engineer",
            "sdlc-devops-engineer",
            "sdlc-product-manager",
            "sdlc-qa-engineer",
            "sdlc-security-engineer",
        ],
    )
    def test_load_builtin_all_personas(self, persona_type):
        """Each built-in persona returns a dict with name, tools, raw_content."""
        persona = load_persona(persona_type)
        assert persona["name"] == persona_type
        assert isinstance(persona["tools"], list)
        assert len(persona["tools"]) > 0
        assert isinstance(persona["raw_content"], str)
        assert len(persona["raw_content"]) > 0

    def test_load_auto_prefix(self):
        """load_persona('architect') produces same name as 'sdlc-architect'."""
        p1 = load_persona("architect")
        p2 = load_persona("sdlc-architect")
        assert p1["name"] == p2["name"]
        assert p1["tools"] == p2["tools"]

    def test_load_project_override_takes_precedence(self, tmp_project):
        """Project override is loaded instead of built-in."""
        persona = load_persona("sdlc-architect", project_dir=str(tmp_project))
        assert persona["description"] == "Project-specific architect override"
        assert persona["category"] == "custom"

    def test_load_fallback_to_builtin_when_no_override(self, tmp_project):
        """Falls back to built-in when no project override exists."""
        persona = load_persona(
            "sdlc-backend-engineer", project_dir=str(tmp_project)
        )
        assert persona["name"] == "sdlc-backend-engineer"
        assert persona["category"] == "sdlc"

    def test_load_missing_persona_returns_minimal(self):
        """Nonexistent persona returns minimal dict with correct name."""
        persona = load_persona("sdlc-nonexistent")
        assert persona["name"] == "sdlc-nonexistent"
        assert persona["tools"] == []
        assert persona["raw_content"] == ""

    def test_load_tools_parsed_as_list(self):
        """tools field is a list of strings, not a comma-separated string."""
        persona = load_persona("sdlc-architect")
        assert isinstance(persona["tools"], list)
        assert persona["tools"] == ["Read", "Grep", "Glob", "Bash"]

    def test_load_memory_parsed_as_list(self):
        """memory field is a list of strings."""
        persona = load_persona("sdlc-architect")
        assert isinstance(persona["memory"], list)
        assert persona["memory"] == ["user"]

    def test_load_source_path_is_absolute(self):
        """source_path is a non-empty absolute path string."""
        persona = load_persona("sdlc-architect")
        assert isinstance(persona["source_path"], str)
        assert len(persona["source_path"]) > 0
        assert Path(persona["source_path"]).is_absolute()

    def test_load_source_path_reflects_override(self, tmp_project):
        """When loading from project override, source_path points to override."""
        persona = load_persona("sdlc-architect", project_dir=str(tmp_project))
        assert str(tmp_project) in persona["source_path"]

    def test_load_read_error_returns_minimal(self, tmp_path):
        """OSError during read returns minimal persona."""
        # Create a persona directory with a file we control
        personas_dir = tmp_path / ".sdlc" / "personas"
        personas_dir.mkdir(parents=True)
        persona_file = personas_dir / "sdlc-broken.md"
        persona_file.write_text("content")

        with patch.object(Path, "read_text", side_effect=OSError("disk error")):
            persona = load_persona("sdlc-broken", project_dir=str(tmp_path))

        assert persona["name"] == "sdlc-broken"
        assert persona["tools"] == []

    def test_load_parse_error_returns_partial(self, tmp_path):
        """Parse error returns dict with raw_content populated."""
        personas_dir = tmp_path / ".sdlc" / "personas"
        personas_dir.mkdir(parents=True)
        persona_file = personas_dir / "sdlc-badparse.md"
        persona_file.write_text("---\nname: badparse\n---\n# Content")

        with patch(
            "a_sdlc.orchestrator_prompts._parse_persona_frontmatter",
            side_effect=ValueError("parse boom"),
        ):
            persona = load_persona("sdlc-badparse", project_dir=str(tmp_path))

        assert persona["name"] == "sdlc-badparse"
        # raw_content should be populated from the file read
        assert "# Content" in persona["raw_content"]
        assert persona["source_path"] != ""


# ---------------------------------------------------------------------------
# TestMinimalPersona
# ---------------------------------------------------------------------------


class TestMinimalPersona:
    """Fallback dict shape tests."""

    _EXPECTED_KEYS = {
        "name",
        "description",
        "category",
        "tools",
        "memory",
        "triggers",
        "behavioral_mindset",
        "focus_areas",
        "key_actions",
        "raw_content",
        "source_path",
    }

    def test_minimal_persona_has_all_keys(self):
        """Returned dict contains all 11 expected keys."""
        persona = _minimal_persona("sdlc-foo")
        assert set(persona.keys()) == self._EXPECTED_KEYS

    def test_minimal_persona_name_matches_input(self):
        """name matches the input persona_type."""
        persona = _minimal_persona("sdlc-foo")
        assert persona["name"] == "sdlc-foo"

    def test_minimal_persona_tools_is_empty_list(self):
        """tools is [], not None or ''."""
        persona = _minimal_persona("sdlc-foo")
        assert persona["tools"] == []
        assert isinstance(persona["tools"], list)

    def test_minimal_persona_raw_content_is_empty_string(self):
        """raw_content is '', not None."""
        persona = _minimal_persona("sdlc-foo")
        assert persona["raw_content"] == ""
        assert isinstance(persona["raw_content"], str)


# ---------------------------------------------------------------------------
# Prompt Builder Tests (preserved from SDLC-T00187)
# ---------------------------------------------------------------------------


class TestPromptBuilders:
    """Tests for phase-specific prompt builders."""

    def test_build_pm_prompt(self):
        """PM prompt includes goal and project context."""
        goal = "Implement a new auth system"
        project_context = {"project_id": "test-proj", "status": "active"}
        prompt = build_pm_prompt(goal, project_context)

        assert "Product Manager" in prompt
        assert goal in prompt
        assert "test-proj" in prompt
        assert "Goal Interpretation Protocol" in prompt
        assert SIGNAL_PROTOCOL_INSTRUCTIONS in prompt

    def test_build_design_prompt(self):
        """Design prompt includes PRD IDs."""
        prd_ids = ["P-001", "P-002"]
        prompt = build_design_prompt(prd_ids)

        assert "Software Architect" in prompt
        assert "P-001, P-002" in prompt
        assert "create_design" in prompt

    def test_build_split_prompt(self):
        """Split prompt includes PRD IDs."""
        prd_ids = ["P-001"]
        prompt = build_split_prompt(prd_ids)

        assert "Software Architect" in prompt
        assert "P-001" in prompt
        assert "create_task" in prompt

    def test_build_challenger_prompt(self):
        """Challenger prompt includes artifact content and checklist."""
        artifact_content = "# Test PRD\nRequirements..."
        checklist = ["Is it clear?", "Is it feasible?"]
        prompt = build_challenger_prompt(
            "prd", "P-001", artifact_content, checklist
        )

        assert "CHALLENGER" in prompt
        assert artifact_content in prompt
        assert "Is it clear?" in prompt
        assert "READ-ONLY" in prompt

    def test_build_revision_prompt(self):
        """Revision prompt includes objections."""
        objections = [{"description": "Missing error handling"}]
        prompt = build_revision_prompt("design", "D-001", objections)

        assert "REVISION" in prompt
        assert "Missing error handling" in prompt

    def test_build_qa_prompt(self):
        """QA prompt includes task outcomes."""
        outcomes = [{"task_id": "T-001", "status": "completed"}]
        prompt = build_qa_prompt("S-001", outcomes)

        assert "QA Engineer" in prompt
        assert "S-001" in prompt
        assert "T-001" in prompt
        assert "QA VERIFICATION" in prompt

    def test_build_failure_triage_prompt(self):
        """Failure triage prompt includes error output."""
        error = "ZeroDivisionError: division by zero"
        prompt = build_failure_triage_prompt("T-001", error)

        assert "Software Architect" in prompt
        assert "FAILURE TRIAGE" in prompt
        assert error in prompt


# ---------------------------------------------------------------------------
# ThreadEntry Dataclass Tests
# ---------------------------------------------------------------------------


class TestThreadEntry:
    """Tests for the ThreadEntry dataclass and its properties."""

    def test_basic_construction(self):
        """ThreadEntry can be constructed with required fields."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="PROJ-T00001",
            entry_type="implementation",
            content="Implemented the feature",
            agent_persona="sdlc-backend-engineer",
            round_number=2,
        )
        assert entry.artifact_type == "task"
        assert entry.artifact_id == "PROJ-T00001"
        assert entry.entry_type == "implementation"
        assert entry.content == "Implemented the feature"
        assert entry.agent_persona == "sdlc-backend-engineer"
        assert entry.round_number == 2

    def test_is_user_intervention_true(self):
        """is_user_intervention returns True for user_intervention entry_type."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="user_intervention",
            content="Do not touch auth",
        )
        assert entry.is_user_intervention is True

    def test_is_user_intervention_false(self):
        """is_user_intervention returns False for non-intervention entries."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="implementation",
        )
        assert entry.is_user_intervention is False

    def test_display_persona_strips_prefix(self):
        """display_persona strips sdlc- prefix and title-cases."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="comment",
            agent_persona="sdlc-backend-engineer",
        )
        assert entry.display_persona == "Backend Engineer"

    def test_display_persona_no_prefix(self):
        """display_persona handles personas without sdlc- prefix."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="comment",
            agent_persona="custom-reviewer",
        )
        assert entry.display_persona == "Custom Reviewer"

    def test_display_persona_empty(self):
        """display_persona returns 'Unknown' when agent_persona is empty."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="comment",
            agent_persona="",
        )
        assert entry.display_persona == "Unknown"

    def test_display_label_regular_entry(self):
        """display_label shows '[Persona, Round N]' for regular entries."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="review",
            agent_persona="sdlc-architect",
            round_number=3,
        )
        assert entry.display_label == "[Architect, Round 3]"

    def test_display_label_user_intervention(self):
        """display_label shows '[User, intervention]' for user entries."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="user_intervention",
            agent_persona="user",
        )
        assert entry.display_label == "[User, intervention]"

    def test_to_dict(self):
        """to_dict returns a complete dictionary representation."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="comment",
            content="test",
            agent_persona="sdlc-architect",
            round_number=1,
        )
        d = entry.to_dict()
        assert isinstance(d, dict)
        assert d["artifact_type"] == "task"
        assert d["artifact_id"] == "T1"
        assert d["content"] == "test"

    def test_default_values(self):
        """Default field values are set correctly."""
        entry = ThreadEntry(
            artifact_type="prd",
            artifact_id="P1",
            entry_type="decision",
        )
        assert entry.content == ""
        assert entry.agent_persona == ""
        assert entry.round_number == 1
        assert entry.created_at == ""
        assert entry.run_id == ""
        assert entry.agent_id == ""
        assert entry.parent_thread_id is None
        assert entry.id is None


# ---------------------------------------------------------------------------
# TestEntriesFromDbRows
# ---------------------------------------------------------------------------


class TestEntriesFromDbRows:
    """Tests for the entries_from_db_rows converter function."""

    def test_empty_rows(self):
        """Empty list produces empty result."""
        assert entries_from_db_rows([]) == []

    def test_standard_row(self):
        """Standard DB row is converted to ThreadEntry correctly."""
        rows = [
            {
                "artifact_type": "task",
                "artifact_id": "PROJ-T00001",
                "entry_type": "implementation",
                "content": "Done",
                "agent_persona": "sdlc-backend-engineer",
                "round_number": 2,
            }
        ]
        entries = entries_from_db_rows(rows)
        assert len(entries) == 1
        assert entries[0].artifact_type == "task"
        assert entries[0].content == "Done"
        assert entries[0].round_number == 2

    def test_none_content_becomes_empty_string(self):
        """None content from DB is converted to empty string."""
        rows = [
            {
                "artifact_type": "prd",
                "artifact_id": "P1",
                "entry_type": "comment",
                "content": None,
                "agent_persona": None,
            }
        ]
        entries = entries_from_db_rows(rows)
        assert entries[0].content == ""
        assert entries[0].agent_persona == ""

    def test_unknown_keys_ignored(self):
        """Keys not in ThreadEntry fields are silently dropped."""
        rows = [
            {
                "artifact_type": "task",
                "artifact_id": "T1",
                "entry_type": "comment",
                "some_unknown_field": "should be ignored",
            }
        ]
        entries = entries_from_db_rows(rows)
        assert len(entries) == 1
        assert entries[0].artifact_type == "task"

    def test_multiple_rows(self):
        """Multiple rows produce multiple ThreadEntry instances."""
        rows = [
            {"artifact_type": "task", "artifact_id": "T1", "entry_type": "a"},
            {"artifact_type": "task", "artifact_id": "T2", "entry_type": "b"},
            {"artifact_type": "prd", "artifact_id": "P1", "entry_type": "c"},
        ]
        entries = entries_from_db_rows(rows)
        assert len(entries) == 3
        assert entries[2].artifact_type == "prd"


# ---------------------------------------------------------------------------
# TestEstimateTokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    """Tests for the token estimation helper."""

    def test_empty_string(self):
        """Empty string returns 0 tokens."""
        assert estimate_tokens("") == 0

    def test_known_length(self):
        """40-char string produces 10 tokens at 4 chars/token."""
        assert estimate_tokens("x" * 40) == 10

    def test_rounds_up(self):
        """Non-exact multiples round up (ceiling)."""
        # 5 chars -> ceil(5/4) = 2
        assert estimate_tokens("hello") == 2

    def test_single_char(self):
        """Single character produces 1 token."""
        assert estimate_tokens("a") == 1


# ---------------------------------------------------------------------------
# TestFormatEntry
# ---------------------------------------------------------------------------


class TestFormatEntry:
    """Tests for the format_entry function."""

    def test_regular_entry(self):
        """Regular entry formats as '[Persona, Round N]: content'."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="review",
            content="Looks good",
            agent_persona="sdlc-architect",
            round_number=2,
        )
        result = format_entry(entry)
        assert result == "[Architect, Round 2]: Looks good"

    def test_user_intervention_entry(self):
        """User intervention uses special label."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="user_intervention",
            content="Stop work immediately",
            agent_persona="user",
        )
        result = format_entry(entry)
        assert result == "[User, intervention]: Stop work immediately"

    def test_empty_content(self):
        """Empty content shows '(no content)' placeholder."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="comment",
            content="",
            agent_persona="sdlc-qa-engineer",
        )
        result = format_entry(entry)
        assert "(no content)" in result

    def test_whitespace_content_trimmed(self):
        """Content with leading/trailing whitespace is stripped."""
        entry = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="comment",
            content="  trimmed  ",
            agent_persona="sdlc-architect",
        )
        result = format_entry(entry)
        assert "trimmed" in result
        assert result.endswith("trimmed")


# ---------------------------------------------------------------------------
# TestFormatSectionHeader
# ---------------------------------------------------------------------------


class TestFormatSectionHeader:
    """Tests for the _format_section_header helper."""

    def test_task_header(self):
        """Task type produces uppercase TASK header."""
        header = _format_section_header("task", "PROJ-T00001")
        assert header == "### TASK Thread: PROJ-T00001"

    def test_prd_header(self):
        """PRD type produces uppercase PRD header."""
        header = _format_section_header("prd", "PROJ-P0001")
        assert "PRD" in header
        assert "PROJ-P0001" in header

    def test_sprint_header(self):
        """Sprint type produces uppercase SPRINT header."""
        header = _format_section_header("sprint", "PROJ-S0001")
        assert "SPRINT" in header
        assert "PROJ-S0001" in header


# ---------------------------------------------------------------------------
# TestThreadContextAssembly (FR-015 through FR-018)
# ---------------------------------------------------------------------------


class TestThreadContextAssembly:
    """Tests for thread context assembly (FR-015 through FR-018)."""

    def test_assemble_empty_dict(self):
        """Empty entries_by_level returns empty ThreadContext."""
        result = assemble_thread_context({})
        assert isinstance(result, ThreadContext)
        assert result.text == ""
        assert result.total_entries == 0
        assert result.included_entries == 0
        assert result.truncated_entries == 0
        assert result.levels == []

    def test_assemble_single_level_task(self):
        """Single task level with one entry produces formatted output."""
        entries = {
            ("task", "PROJ-T00001"): [
                ThreadEntry(
                    artifact_type="task",
                    artifact_id="PROJ-T00001",
                    entry_type="implementation",
                    content="Implemented the database migration",
                    agent_persona="sdlc-backend-engineer",
                    round_number=1,
                ),
            ],
        }
        result = assemble_thread_context(entries)
        assert isinstance(result, ThreadContext)
        assert "PROJ-T00001" in result.text
        assert "database migration" in result.text
        assert result.total_entries == 1
        assert result.included_entries == 1
        assert result.truncated_entries == 0

    def test_assemble_hierarchical_three_levels(self):
        """Task + PRD + sprint entries; all three levels present (FR-015, AC-005)."""
        entries = {
            ("sprint", "PROJ-S0001"): [
                ThreadEntry(
                    artifact_type="sprint",
                    artifact_id="PROJ-S0001",
                    entry_type="planning",
                    content="Sprint goal defined for MVP",
                    agent_persona="sdlc-product-manager",
                    round_number=1,
                ),
            ],
            ("prd", "PROJ-P0001"): [
                ThreadEntry(
                    artifact_type="prd",
                    artifact_id="PROJ-P0001",
                    entry_type="design",
                    content="Architecture design approved",
                    agent_persona="sdlc-architect",
                    round_number=1,
                ),
            ],
            ("task", "PROJ-T00001"): [
                ThreadEntry(
                    artifact_type="task",
                    artifact_id="PROJ-T00001",
                    entry_type="implementation",
                    content="Task implementation started",
                    agent_persona="sdlc-backend-engineer",
                    round_number=1,
                ),
            ],
        }
        result = assemble_thread_context(entries)

        assert "Sprint goal defined" in result.text
        assert "Architecture design approved" in result.text
        assert "Task implementation started" in result.text
        assert result.total_entries == 3
        assert result.included_entries == 3
        assert len(result.levels) == 3

    def test_level_ordering_task_before_prd_before_sprint(self):
        """Default ordering puts task first, then prd, then sprint."""
        entries = {
            ("sprint", "S1"): [
                ThreadEntry(
                    artifact_type="sprint",
                    artifact_id="S1",
                    entry_type="planning",
                    content="SPRINT_MARKER",
                    agent_persona="pm",
                ),
            ],
            ("prd", "P1"): [
                ThreadEntry(
                    artifact_type="prd",
                    artifact_id="P1",
                    entry_type="design",
                    content="PRD_MARKER",
                    agent_persona="arch",
                ),
            ],
            ("task", "T1"): [
                ThreadEntry(
                    artifact_type="task",
                    artifact_id="T1",
                    entry_type="impl",
                    content="TASK_MARKER",
                    agent_persona="eng",
                ),
            ],
        }
        result = assemble_thread_context(entries)
        task_pos = result.text.index("TASK_MARKER")
        prd_pos = result.text.index("PRD_MARKER")
        sprint_pos = result.text.index("SPRINT_MARKER")
        assert task_pos < prd_pos < sprint_pos, (
            "Expected task -> prd -> sprint ordering"
        )

    def test_explicit_level_order(self):
        """Explicit level_order overrides default ordering."""
        entries = {
            ("task", "T1"): [
                ThreadEntry(
                    artifact_type="task",
                    artifact_id="T1",
                    entry_type="impl",
                    content="TASK_CONTENT",
                    agent_persona="eng",
                ),
            ],
            ("sprint", "S1"): [
                ThreadEntry(
                    artifact_type="sprint",
                    artifact_id="S1",
                    entry_type="plan",
                    content="SPRINT_CONTENT",
                    agent_persona="pm",
                ),
            ],
        }
        # Force sprint before task
        result = assemble_thread_context(
            entries,
            level_order=[("sprint", "S1"), ("task", "T1")],
        )
        sprint_pos = result.text.index("SPRINT_CONTENT")
        task_pos = result.text.index("TASK_CONTENT")
        assert sprint_pos < task_pos

    def test_budget_truncation_drops_older_entries(self):
        """Entries exceeding token budget are truncated, keeping most recent (FR-017)."""
        entries = {
            ("task", "T1"): [
                ThreadEntry(
                    artifact_type="task",
                    artifact_id="T1",
                    entry_type="analysis",
                    content=f"Analysis round {i}: " + "x" * 500,
                    agent_persona="sdlc-architect",
                    round_number=i,
                )
                for i in range(50)
            ],
        }
        # Use a small token limit to force truncation
        result = assemble_thread_context(entries, token_limit=500)

        assert result.truncated_entries > 0
        # Most recent entries should be present
        assert "Analysis round 49" in result.text
        # Truncation marker should be present
        assert "omit" in result.text.lower() or "..." in result.text

    def test_user_intervention_never_truncated(self):
        """User intervention entries always survive truncation (FR-018)."""
        filler = [
            ThreadEntry(
                artifact_type="task",
                artifact_id="T1",
                entry_type="analysis",
                content="Filler content " + "y" * 500,
                agent_persona="sdlc-architect",
                round_number=i,
            )
            for i in range(50)
        ]
        intervention = ThreadEntry(
            artifact_type="task",
            artifact_id="T1",
            entry_type="user_intervention",
            content="CRITICAL: Do not modify the auth module",
            agent_persona="user",
            round_number=0,
        )
        entries = {
            ("task", "T1"): [*filler, intervention],
        }
        result = assemble_thread_context(entries, token_limit=500)

        assert "CRITICAL: Do not modify the auth module" in result.text

    def test_thread_context_metadata(self):
        """ThreadContext metadata fields are populated correctly."""
        entries = {
            ("task", "T1"): [
                ThreadEntry(
                    artifact_type="task",
                    artifact_id="T1",
                    entry_type="impl",
                    content="Done",
                    agent_persona="eng",
                ),
            ],
        }
        result = assemble_thread_context(entries)
        assert result.estimated_tokens > 0
        assert result.total_entries == 1
        assert isinstance(result.levels, list)

    def test_multiple_entries_same_level(self):
        """Multiple entries in the same level are all included when budget allows."""
        entries = {
            ("task", "T1"): [
                ThreadEntry(
                    artifact_type="task",
                    artifact_id="T1",
                    entry_type="impl",
                    content=f"Step {i}",
                    agent_persona="eng",
                    round_number=i,
                )
                for i in range(5)
            ],
        }
        result = assemble_thread_context(entries)
        for i in range(5):
            assert f"Step {i}" in result.text
        assert result.included_entries == 5
        assert result.truncated_entries == 0


# ---------------------------------------------------------------------------
# TestBuildThreadContextForTask
# ---------------------------------------------------------------------------


class TestBuildThreadContextForTask:
    """Tests for build_thread_context_for_task with mocked DB."""

    def test_queries_all_three_levels(self):
        """Queries task, PRD, and sprint thread entries."""
        from a_sdlc.orchestrator_prompts import build_thread_context_for_task

        mock_db = MagicMock()
        mock_db.get_thread_entries.side_effect = [
            # Task entries
            [
                {
                    "artifact_type": "task",
                    "artifact_id": "T1",
                    "entry_type": "impl",
                    "content": "task work",
                    "agent_persona": "eng",
                    "round_number": 1,
                }
            ],
            # PRD entries
            [
                {
                    "artifact_type": "prd",
                    "artifact_id": "P1",
                    "entry_type": "design",
                    "content": "prd design",
                    "agent_persona": "arch",
                    "round_number": 1,
                }
            ],
            # Sprint entries
            [
                {
                    "artifact_type": "sprint",
                    "artifact_id": "S1",
                    "entry_type": "plan",
                    "content": "sprint plan",
                    "agent_persona": "pm",
                    "round_number": 1,
                }
            ],
        ]

        task_data = {"prd_id": "P1", "sprint_id": "S1"}
        result = build_thread_context_for_task("T1", task_data, db=mock_db)

        assert isinstance(result, ThreadContext)
        assert "task work" in result.text
        assert "prd design" in result.text
        assert "sprint plan" in result.text
        assert mock_db.get_thread_entries.call_count == 3

    def test_no_prd_id_skips_parent_levels(self):
        """No prd_id means only task-level entries are queried."""
        from a_sdlc.orchestrator_prompts import build_thread_context_for_task

        mock_db = MagicMock()
        mock_db.get_thread_entries.return_value = []

        task_data = {}
        result = build_thread_context_for_task("T1", task_data, db=mock_db)

        assert isinstance(result, ThreadContext)
        # Only one call: for task entries (no prd_id or sprint_id)
        assert mock_db.get_thread_entries.call_count == 1

    def test_empty_entries_returns_empty_context(self):
        """Empty DB results produce empty context."""
        from a_sdlc.orchestrator_prompts import build_thread_context_for_task

        mock_db = MagicMock()
        mock_db.get_thread_entries.return_value = []

        task_data = {"prd_id": "P1", "sprint_id": "S1"}
        result = build_thread_context_for_task("T1", task_data, db=mock_db)

        assert result.text == ""
        assert result.total_entries == 0


# ---------------------------------------------------------------------------
# TestBuildThreadContextForPrd
# ---------------------------------------------------------------------------


class TestBuildThreadContextForPrd:
    """Tests for build_thread_context_for_prd with mocked DB."""

    def test_queries_prd_and_sprint(self):
        """Queries PRD and sprint levels."""
        from a_sdlc.orchestrator_prompts import build_thread_context_for_prd

        mock_db = MagicMock()
        mock_db.get_thread_entries.side_effect = [
            [
                {
                    "artifact_type": "prd",
                    "artifact_id": "P1",
                    "entry_type": "review",
                    "content": "prd review",
                    "agent_persona": "pm",
                    "round_number": 1,
                }
            ],
            [
                {
                    "artifact_type": "sprint",
                    "artifact_id": "S1",
                    "entry_type": "plan",
                    "content": "sprint context",
                    "agent_persona": "pm",
                    "round_number": 1,
                }
            ],
        ]

        prd_data = {"sprint_id": "S1"}
        result = build_thread_context_for_prd("P1", prd_data, db=mock_db)

        assert "prd review" in result.text
        assert "sprint context" in result.text
        assert mock_db.get_thread_entries.call_count == 2


# ---------------------------------------------------------------------------
# TestSignalProtocol (FR-011 through FR-014)
# ---------------------------------------------------------------------------


class TestSignalProtocol:
    """Tests for signal protocol parsing (FR-011 through FR-014)."""

    def test_parse_phase_signal(self):
        """Parse a complete PHASE-SIGNAL block (FR-011)."""
        output = textwrap.dedent("""\
            Some preamble text.

            ---PHASE-SIGNAL---
            work_type: design
            artifact_ids: SDLC-P0031
            next_work_type: split
            starting_phase: split
            summary: Architecture design completed for agent prompts PRD
            ---END-PHASE-SIGNAL---

            Some trailing text.
        """)
        signal = parse_signal(output, "PHASE-SIGNAL")

        assert signal is not None
        assert signal["work_type"] == "design"
        assert signal["artifact_ids"] == "SDLC-P0031"
        assert signal["next_work_type"] == "split"
        assert signal["starting_phase"] == "split"
        assert "Architecture design completed" in signal["summary"]

    def test_parse_clarification_signal(self):
        """Parse a CLARIFICATION-NEEDED block (FR-012)."""
        output = textwrap.dedent("""\
            ---CLARIFICATION-NEEDED---
            question: Should the API support batch operations?
            context: The PRD mentions bulk imports but doesn't specify API shape
            options: REST batch endpoint, GraphQL mutation, async job queue
            ---END-CLARIFICATION-NEEDED---
        """)
        signal = parse_signal(output, "CLARIFICATION-NEEDED")

        assert signal is not None
        assert "batch operations" in signal["question"]
        assert "options" in signal

    def test_parse_thread_entry_signal(self):
        """Parse a THREAD-ENTRY block (FR-013/FR-014)."""
        output = textwrap.dedent("""\
            ---THREAD-ENTRY---
            entry_type: implementation
            content: Implemented 3 API endpoints with input validation
            ---END-THREAD-ENTRY---
        """)
        signal = parse_signal(output, "THREAD-ENTRY")

        assert signal is not None
        assert signal["entry_type"] == "implementation"
        assert "3 API endpoints" in signal["content"]

    def test_parse_failure_triage_signal(self):
        """Parse a FAILURE-TRIAGE block."""
        output = textwrap.dedent("""\
            ---FAILURE-TRIAGE---
            decision: retry
            reason: Test failure caused by race condition in async handler
            new_work_items: []
            ---END-FAILURE-TRIAGE---
        """)
        signal = parse_signal(output, "FAILURE-TRIAGE")

        assert signal is not None
        assert signal["decision"] == "retry"
        assert "race condition" in signal["reason"]

    def test_parse_missing_signal_returns_none(self):
        """Output without a signal block returns None."""
        output = "Just some normal output without any signal markers."
        signal = parse_signal(output, "PHASE-SIGNAL")
        assert signal is None

    def test_parse_wrong_signal_type_returns_none(self):
        """Looking for wrong signal type returns None even when another exists."""
        output = textwrap.dedent("""\
            ---PHASE-SIGNAL---
            work_type: design
            ---END-PHASE-SIGNAL---
        """)
        signal = parse_signal(output, "CLARIFICATION-NEEDED")
        assert signal is None

    def test_parse_signal_with_generic_end_marker(self):
        """Generic ---END-SIGNAL--- terminator is accepted."""
        output = textwrap.dedent("""\
            ---PHASE-SIGNAL---
            work_type: implement
            summary: Done
            ---END-SIGNAL---
        """)
        signal = parse_signal(output, "PHASE-SIGNAL")

        assert signal is not None
        assert signal["work_type"] == "implement"
        assert signal["summary"] == "Done"

    def test_parse_signal_value_with_colons(self):
        """Values containing colons are preserved correctly."""
        output = textwrap.dedent("""\
            ---THREAD-ENTRY---
            entry_type: decision
            content: Architecture: use microservices with gRPC: final decision
            ---END-THREAD-ENTRY---
        """)
        signal = parse_signal(output, "THREAD-ENTRY")

        assert signal is not None
        assert signal["content"] == (
            "Architecture: use microservices with gRPC: final decision"
        )

    def test_parse_signal_surrounded_by_prose(self):
        """Signal block embedded in extensive prose is still found."""
        output = (
            "Here is my analysis.\n" * 20
            + "---PHASE-SIGNAL---\n"
            + "work_type: qa\n"
            + "summary: All tests pass\n"
            + "---END-PHASE-SIGNAL---\n"
            + "And more text follows.\n" * 10
        )
        signal = parse_signal(output, "PHASE-SIGNAL")

        assert signal is not None
        assert signal["work_type"] == "qa"

    def test_signal_protocol_instructions_contains_all_types(self):
        """SIGNAL_PROTOCOL_INSTRUCTIONS constant references all 4 signal types."""
        assert isinstance(SIGNAL_PROTOCOL_INSTRUCTIONS, str)
        assert "PHASE-SIGNAL" in SIGNAL_PROTOCOL_INSTRUCTIONS
        assert "CLARIFICATION-NEEDED" in SIGNAL_PROTOCOL_INSTRUCTIONS
        assert "THREAD-ENTRY" in SIGNAL_PROTOCOL_INSTRUCTIONS
        assert "FAILURE-TRIAGE" in SIGNAL_PROTOCOL_INSTRUCTIONS

    def test_signal_protocol_instructions_has_end_markers(self):
        """SIGNAL_PROTOCOL_INSTRUCTIONS includes END markers for each type."""
        assert "END-PHASE-SIGNAL" in SIGNAL_PROTOCOL_INSTRUCTIONS
        assert "END-THREAD-ENTRY" in SIGNAL_PROTOCOL_INSTRUCTIONS
        assert "END-CLARIFICATION-NEEDED" in SIGNAL_PROTOCOL_INSTRUCTIONS
        assert "END-FAILURE-TRIAGE" in SIGNAL_PROTOCOL_INSTRUCTIONS


# ---------------------------------------------------------------------------
# TestFormatThreadEntries
# ---------------------------------------------------------------------------


class TestFormatThreadEntries:
    """Tests for the _format_thread_entries convenience helper."""

    def test_empty_list(self):
        """Empty input produces empty output."""
        assert _format_thread_entries([]) == []

    def test_single_entry(self):
        """Single entry produces one formatted line."""
        entries = [
            {
                "persona": "sdlc-architect",
                "round_number": 2,
                "entry_type": "review",
                "content": "Design looks good",
            },
        ]
        lines = _format_thread_entries(entries)
        assert isinstance(lines, list)
        assert len(lines) == 1
        formatted = lines[0]
        assert "Architect" in formatted
        assert "Round 2" in formatted
        assert "review" in formatted
        assert "Design looks good" in formatted

    def test_persona_prefix_stripped(self):
        """sdlc- prefix is stripped and result is title-cased."""
        entries = [
            {
                "persona": "sdlc-backend-engineer",
                "round_number": 1,
                "entry_type": "impl",
                "content": "Done",
            },
        ]
        lines = _format_thread_entries(entries)
        assert "Backend Engineer" in lines[0]

    def test_multiple_entries(self):
        """Multiple entries produce multiple lines."""
        entries = [
            {
                "persona": "sdlc-architect",
                "round_number": 1,
                "entry_type": "design",
                "content": "Step 1",
            },
            {
                "persona": "sdlc-qa-engineer",
                "round_number": 2,
                "entry_type": "review",
                "content": "Step 2",
            },
        ]
        lines = _format_thread_entries(entries)
        assert len(lines) == 2
        assert "Step 1" in lines[0]
        assert "Step 2" in lines[1]

    def test_missing_fields_use_defaults(self):
        """Missing dict keys fall back to sensible defaults."""
        entries = [{}]
        lines = _format_thread_entries(entries)
        assert len(lines) == 1
        assert "Unknown" in lines[0]
        assert "Round 0" in lines[0]
        assert "(no content)" in lines[0]

    def test_format_matches_expected_pattern(self):
        """Output matches '[Persona, Round N, entry_type]: content'."""
        entries = [
            {
                "persona": "sdlc-product-manager",
                "round_number": 3,
                "entry_type": "planning",
                "content": "Sprint scope finalized",
            },
        ]
        lines = _format_thread_entries(entries)
        formatted = lines[0]
        assert formatted.startswith("[Product Manager, Round 3, planning]:")
        assert "Sprint scope finalized" in formatted


# ---------------------------------------------------------------------------
# Additional Prompt Builder Tests (FR-009, expanded AC coverage)
# ---------------------------------------------------------------------------


class TestPromptBuildersExpanded:
    """Extended prompt builder tests covering engineer, cross-cutting signal, etc."""

    @pytest.fixture(autouse=True)
    def _mock_server_module(self):
        """Mock a_sdlc.server to avoid importing the MCP dependency chain."""
        mock_server = MagicMock()
        mock_server.build_execute_task_prompt = MagicMock(return_value="BASE PROMPT")
        with patch.dict(sys.modules, {"a_sdlc.server": mock_server}):
            # Store reference for tests that need to configure/inspect the mock
            self._mock_build_execute_task_prompt = mock_server.build_execute_task_prompt
            yield

    # ---- Engineer prompt (FR-009, AC-002) ----

    def test_build_engineer_prompt_wraps_existing(self):
        """AC-002: Engineer prompt includes base prompt + persona prefix."""
        self._mock_build_execute_task_prompt.return_value = (
            "BASE PROMPT: implement task T00001"
        )

        task = {"id": "PROJ-T00001", "title": "Add API endpoint", "prd_id": "P1"}
        prompt = build_engineer_prompt(
            task_id="PROJ-T00001",
            task=task,
        )

        assert isinstance(prompt, str)
        assert "BASE PROMPT" in prompt
        # Persona content from sdlc-backend-engineer
        assert "Engineer" in prompt or "engineer" in prompt.lower()

    def test_build_engineer_prompt_includes_thread_history(self):
        """Engineer prompt includes thread history string."""
        self._mock_build_execute_task_prompt.return_value = "BASE"

        thread_text = "### TASK Thread: T1\n[Architect, Round 1]: Use repository pattern"
        prompt = build_engineer_prompt(
            task_id="T1",
            task={"id": "T1", "title": "Test"},
            thread_history=thread_text,
        )

        assert "repository pattern" in prompt

    def test_build_engineer_prompt_custom_persona(self):
        """Engineer prompt supports custom persona type."""
        self._mock_build_execute_task_prompt.return_value = "BASE"

        prompt = build_engineer_prompt(
            task_id="T1",
            task={"id": "T1", "title": "Frontend work"},
            persona_type="sdlc-frontend-engineer",
        )

        assert isinstance(prompt, str)
        # Should load frontend persona
        assert len(prompt) > len("BASE")

    def test_build_engineer_prompt_dispatch_info(self):
        """Engineer prompt passes dispatch_info to base builder."""
        self._mock_build_execute_task_prompt.return_value = "BASE"

        build_engineer_prompt(
            task_id="T1",
            task={"id": "T1", "title": "T"},
            dispatch_info="depends on T0",
        )

        # Verify dispatch_info was passed to the base builder
        self._mock_build_execute_task_prompt.assert_called_once_with(
            "T1", {"id": "T1", "title": "T"}, dispatch_info="depends on T0"
        )

    # ---- PM prompt with goal_file_content (FR-004) ----

    def test_build_pm_prompt_with_goal_file(self):
        """PM prompt includes detailed specification when goal_file_content given."""
        prompt = build_pm_prompt(
            goal="Implement feature X",
            project_context={"project_id": "PROJ"},
            goal_file_content="## Detailed Requirements\n- Req 1\n- Req 2",
        )
        assert "Detailed Specification" in prompt
        assert "Req 1" in prompt
        assert "Req 2" in prompt

    def test_build_pm_prompt_without_goal_file(self):
        """PM prompt omits specification section when no goal_file_content."""
        prompt = build_pm_prompt(
            goal="Implement feature X",
            project_context={"project_id": "PROJ"},
        )
        assert "Detailed Specification" not in prompt

    # ---- Challenger prompt expanded (FR-007) ----

    def test_build_challenger_prompt_enforces_readonly(self):
        """Challenger prompt text contains READ-ONLY instruction."""
        prompt = build_challenger_prompt(
            artifact_type="design",
            artifact_id="D-001",
            artifact_content="# Architecture\nDesign details here.",
            checklist=["Is it scalable?"],
        )
        assert "READ-ONLY" in prompt

    def test_build_challenger_prompt_custom_persona(self):
        """Challenger can use a custom persona type."""
        prompt = build_challenger_prompt(
            artifact_type="prd",
            artifact_id="P-001",
            artifact_content="# PRD",
            checklist=["Check 1"],
            persona_type="sdlc-security-engineer",
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    # ---- Revision prompt expanded (FR-008) ----

    def test_build_revision_prompt_prd_uses_pm_persona(self):
        """Revision for PRD artifact uses product-manager persona."""
        prompt = build_revision_prompt(
            "prd", "P-001", [{"description": "Missing NFR"}]
        )
        assert "Product Manager" in prompt

    def test_build_revision_prompt_design_uses_architect_persona(self):
        """Revision for design artifact uses architect persona."""
        prompt = build_revision_prompt(
            "design", "D-001", [{"description": "Scalability concern"}]
        )
        assert "Software Architect" in prompt or "Architect" in prompt

    def test_build_revision_prompt_multiple_objections(self):
        """Multiple objections are all included in the revision prompt."""
        objections = [
            {"description": "Missing error handling"},
            {"description": "No pagination support"},
            {"description": "Security review needed"},
        ]
        prompt = build_revision_prompt("prd", "P-001", objections)
        assert "Missing error handling" in prompt
        assert "No pagination support" in prompt
        assert "Security review needed" in prompt

    # ---- QA prompt expanded (FR-010) ----

    def test_build_qa_prompt_includes_outcomes(self):
        """QA prompt includes serialized task outcomes."""
        outcomes = [
            {"task_id": "T-001", "status": "completed"},
            {"task_id": "T-002", "status": "failed"},
        ]
        prompt = build_qa_prompt("S-001", outcomes)
        assert "T-001" in prompt
        assert "T-002" in prompt
        assert "failed" in prompt

    # ---- Failure triage expanded (FR-010a) ----

    def test_build_failure_triage_includes_retry_count(self):
        """Failure triage prompt includes the retry count."""
        prompt = build_failure_triage_prompt(
            failed_item="PROJ-T00005",
            error_output="AssertionError: expected 200",
            retry_count=2,
        )
        assert "2" in prompt
        assert "FAILURE-TRIAGE" in prompt

    def test_build_failure_triage_includes_decision_options(self):
        """Failure triage prompt mentions possible decisions."""
        prompt = build_failure_triage_prompt(
            failed_item="T-001",
            error_output="Error",
        )
        assert any(
            option in prompt.lower()
            for option in ["retry", "skip", "redesign", "escalate"]
        )

    # ---- Cross-cutting: all builders include signal protocol (AC-004) ----

    def test_all_prompts_include_signal_protocol(self):
        """AC-004: All builder outputs include signal protocol section."""
        self._mock_build_execute_task_prompt.return_value = "BASE"

        prompts = {
            "pm": build_pm_prompt(
                goal="Test", project_context={}
            ),
            "design": build_design_prompt(prd_ids=["P1"]),
            "split": build_split_prompt(prd_ids=["P1"]),
            "challenger": build_challenger_prompt(
                artifact_type="prd",
                artifact_id="P1",
                artifact_content="Content",
                checklist=["Q1"],
            ),
            "revision": build_revision_prompt(
                "prd", "P1", [{"description": "issue"}]
            ),
            "qa": build_qa_prompt("S-001", []),
            "failure_triage": build_failure_triage_prompt("T-001", "Error"),
        }

        for builder_name, prompt in prompts.items():
            assert SIGNAL_PROTOCOL_INSTRUCTIONS in prompt, (
                f"{builder_name} prompt does not include signal protocol"
            )

    # ---- Thread context hierarchical in PM prompt (AC-005) ----

    def test_pm_prompt_with_thread_history(self):
        """PM prompt passes thread_history into output."""
        thread_text = (
            "## Thread Context\n"
            "### SPRINT Thread: S1\n"
            "[Product Manager, Round 1]: Sprint goal\n"
        )
        prompt = build_pm_prompt(
            goal="Continue work",
            project_context={"project_id": "PROJ"},
            thread_history=thread_text,
        )
        assert "Sprint goal" in prompt


# ---------------------------------------------------------------------------
# TestConstants
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module-level constants."""

    def test_default_token_limit(self):
        """DEFAULT_TOKEN_LIMIT is a positive integer."""
        assert isinstance(DEFAULT_TOKEN_LIMIT, int)
        assert DEFAULT_TOKEN_LIMIT > 0

    def test_chars_per_token(self):
        """CHARS_PER_TOKEN is 4."""
        assert CHARS_PER_TOKEN == 4

    def test_signal_protocol_instructions_is_nonempty(self):
        """SIGNAL_PROTOCOL_INSTRUCTIONS is a non-empty string."""
        assert isinstance(SIGNAL_PROTOCOL_INSTRUCTIONS, str)
        assert len(SIGNAL_PROTOCOL_INSTRUCTIONS) > 100
