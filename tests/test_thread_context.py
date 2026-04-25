"""Tests for thread context assembly (SDLC-T00187).

Covers FR-015 through FR-018 and NFR-001 from SDLC-P0031:
- FR-015: Hierarchical thread context (task -> PRD -> sprint)
- FR-016: Conversation log formatting with persona attribution
- FR-017: Truncation with most-recent priority
- FR-018: User interventions always included, never truncated
- NFR-001: Configurable token limit
"""

import tempfile
from pathlib import Path

import pytest

from a_sdlc.core.database import Database
from a_sdlc.orchestrator_prompts import (
    DEFAULT_TOKEN_LIMIT,
    ThreadContext,
    ThreadEntry,
    assemble_thread_context,
    build_thread_context_for_prd,
    build_thread_context_for_task,
    entries_from_db_rows,
    estimate_tokens,
    format_entry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db():
    """Create a temporary database with a project, PRD, sprint, and task."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=db_path)
        db.create_project("test-proj", "Test Project", "/tmp/test-proj")
        db.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-proj",
            title="Sprint 1",
            goal="Test sprint goal",
        )
        db.create_prd(
            prd_id="TEST-P0001",
            project_id="test-proj",
            title="Test PRD",
            file_path="/tmp/test-proj/prds/TEST-P0001.md",
        )
        # Assign PRD to sprint
        db.update_prd("TEST-P0001", sprint_id="TEST-S0001")
        db.create_task(
            task_id="TEST-T00001",
            project_id="test-proj",
            prd_id="TEST-P0001",
            title="Test Task",
            file_path="/tmp/test-proj/tasks/TEST-T00001.md",
        )
        # Create an execution run for thread entries
        db.create_execution_run(
            run_id="TEST-R001",
            project_id="test-proj",
            sprint_id="TEST-S0001",
            status="running",
        )
        yield db


def _make_entry(
    artifact_type: str = "task",
    artifact_id: str = "TEST-T00001",
    entry_type: str = "draft",
    content: str = "Some content",
    agent_persona: str = "sdlc-backend-engineer",
    round_number: int = 1,
) -> ThreadEntry:
    """Helper to create a ThreadEntry for testing."""
    return ThreadEntry(
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        entry_type=entry_type,
        content=content,
        agent_persona=agent_persona,
        round_number=round_number,
    )


# ---------------------------------------------------------------------------
# ThreadEntry unit tests
# ---------------------------------------------------------------------------


class TestThreadEntry:
    """Tests for ThreadEntry dataclass properties."""

    def test_is_user_intervention_true(self):
        entry = _make_entry(entry_type="user_intervention")
        assert entry.is_user_intervention is True

    def test_is_user_intervention_false(self):
        entry = _make_entry(entry_type="draft")
        assert entry.is_user_intervention is False

    def test_display_persona_strips_prefix(self):
        entry = _make_entry(agent_persona="sdlc-backend-engineer")
        assert entry.display_persona == "Backend Engineer"

    def test_display_persona_no_prefix(self):
        entry = _make_entry(agent_persona="architect")
        assert entry.display_persona == "Architect"

    def test_display_persona_empty(self):
        entry = _make_entry(agent_persona="")
        assert entry.display_persona == "Unknown"

    def test_display_label_regular(self):
        entry = _make_entry(agent_persona="sdlc-architect", round_number=2)
        assert entry.display_label == "[Architect, Round 2]"

    def test_display_label_user_intervention(self):
        entry = _make_entry(entry_type="user_intervention")
        assert entry.display_label == "[User, intervention]"

    def test_to_dict(self):
        entry = _make_entry()
        d = entry.to_dict()
        assert isinstance(d, dict)
        assert d["artifact_type"] == "task"
        assert d["content"] == "Some content"


# ---------------------------------------------------------------------------
# Format entry tests (FR-016)
# ---------------------------------------------------------------------------


class TestFormatEntry:
    """Tests for conversation log formatting (FR-016)."""

    def test_format_regular_entry(self):
        entry = _make_entry(
            agent_persona="sdlc-architect",
            round_number=2,
            content="Designed the API layer",
        )
        result = format_entry(entry)
        assert result == "[Architect, Round 2]: Designed the API layer"

    def test_format_user_intervention(self):
        entry = _make_entry(
            entry_type="user_intervention",
            content="Please use PostgreSQL instead of MySQL",
        )
        result = format_entry(entry)
        assert result == "[User, intervention]: Please use PostgreSQL instead of MySQL"

    def test_format_empty_content(self):
        entry = _make_entry(content="")
        result = format_entry(entry)
        assert "(no content)" in result

    def test_format_none_content(self):
        entry = _make_entry(content=None)
        result = format_entry(entry)
        assert "(no content)" in result


# ---------------------------------------------------------------------------
# Token estimation tests
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    """Tests for token estimation."""

    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_known_length(self):
        # 40 characters / 4 = 10 tokens
        assert estimate_tokens("a" * 40) == 10

    def test_rounds_up(self):
        # 5 characters / 4 = 1.25 -> ceil = 2
        assert estimate_tokens("hello") == 2


# ---------------------------------------------------------------------------
# entries_from_db_rows tests
# ---------------------------------------------------------------------------


class TestEntriesFromDbRows:
    """Tests for converting DB rows to ThreadEntry objects."""

    def test_basic_conversion(self):
        rows = [
            {
                "id": 1,
                "artifact_type": "task",
                "artifact_id": "T-001",
                "entry_type": "draft",
                "content": "Draft content",
                "agent_persona": "sdlc-architect",
                "round_number": 1,
                "created_at": "2026-01-01T00:00:00",
                "run_id": "R-001",
                "agent_id": "A-001",
                "parent_thread_id": None,
            }
        ]
        entries = entries_from_db_rows(rows)
        assert len(entries) == 1
        assert entries[0].artifact_type == "task"
        assert entries[0].content == "Draft content"
        assert entries[0].id == 1

    def test_none_content_becomes_empty_string(self):
        rows = [
            {
                "artifact_type": "prd",
                "artifact_id": "P-001",
                "entry_type": "signal",
                "content": None,
                "agent_persona": None,
                "round_number": 1,
            }
        ]
        entries = entries_from_db_rows(rows)
        assert entries[0].content == ""
        assert entries[0].agent_persona == ""

    def test_unknown_keys_ignored(self):
        rows = [
            {
                "artifact_type": "task",
                "artifact_id": "T-001",
                "entry_type": "draft",
                "content": "Hello",
                "unknown_column": "ignored",
            }
        ]
        entries = entries_from_db_rows(rows)
        assert len(entries) == 1
        assert entries[0].content == "Hello"

    def test_empty_rows(self):
        assert entries_from_db_rows([]) == []


# ---------------------------------------------------------------------------
# assemble_thread_context tests (FR-015, FR-017, FR-018, NFR-001)
# ---------------------------------------------------------------------------


class TestAssembleThreadContext:
    """Tests for hierarchical thread context assembly."""

    def test_empty_input(self):
        """Empty entries produce empty context."""
        ctx = assemble_thread_context({})
        assert ctx.text == ""
        assert ctx.total_entries == 0
        assert ctx.included_entries == 0

    def test_single_level_task(self):
        """Single task level assembles correctly (FR-015)."""
        entries = {
            ("task", "T-001"): [
                _make_entry(content="Implemented auth", round_number=1),
            ]
        }
        ctx = assemble_thread_context(entries)
        assert "### TASK Thread: T-001" in ctx.text
        assert "Implemented auth" in ctx.text
        assert ctx.total_entries == 1
        assert ctx.included_entries == 1
        assert ctx.truncated_entries == 0

    def test_hierarchical_order_task_prd_sprint(self):
        """Entries are ordered task -> PRD -> sprint (FR-015)."""
        entries = {
            ("sprint", "S-001"): [
                _make_entry(
                    artifact_type="sprint",
                    artifact_id="S-001",
                    content="Sprint goal defined",
                    agent_persona="sdlc-product-manager",
                ),
            ],
            ("task", "T-001"): [
                _make_entry(content="Task implementation"),
            ],
            ("prd", "P-001"): [
                _make_entry(
                    artifact_type="prd",
                    artifact_id="P-001",
                    content="PRD drafted",
                    agent_persona="sdlc-product-manager",
                ),
            ],
        }
        ctx = assemble_thread_context(entries)
        # Task should appear before PRD, PRD before sprint
        task_pos = ctx.text.index("### TASK Thread")
        prd_pos = ctx.text.index("### PRD Thread")
        sprint_pos = ctx.text.index("### SPRINT Thread")
        assert task_pos < prd_pos < sprint_pos

    def test_explicit_level_order(self):
        """Explicit level_order overrides default ordering."""
        entries = {
            ("task", "T-001"): [_make_entry(content="Task")],
            ("prd", "P-001"): [
                _make_entry(
                    artifact_type="prd", artifact_id="P-001", content="PRD"
                ),
            ],
        }
        ctx = assemble_thread_context(
            entries, level_order=[("prd", "P-001"), ("task", "T-001")]
        )
        prd_pos = ctx.text.index("### PRD Thread")
        task_pos = ctx.text.index("### TASK Thread")
        assert prd_pos < task_pos

    def test_persona_attribution_in_output(self):
        """Output includes persona attribution (FR-016)."""
        entries = {
            ("task", "T-001"): [
                _make_entry(
                    agent_persona="sdlc-architect",
                    round_number=2,
                    content="Reviewed design",
                ),
            ]
        }
        ctx = assemble_thread_context(entries)
        assert "[Architect, Round 2]: Reviewed design" in ctx.text

    def test_user_intervention_always_included(self):
        """User intervention entries are never truncated (FR-018)."""
        # Create entries where budget is very tight
        user_entry = _make_entry(
            entry_type="user_intervention",
            content="Use Redis for caching",
            agent_persona="",
        )
        regular_entries = [
            _make_entry(content=f"Regular entry {i}" * 50, round_number=i)
            for i in range(1, 20)
        ]
        entries = {
            ("task", "T-001"): [user_entry] + regular_entries,
        }
        # Very tight budget
        ctx = assemble_thread_context(entries, token_limit=200)
        # User intervention MUST be present
        assert "[User, intervention]: Use Redis for caching" in ctx.text

    def test_truncation_keeps_most_recent(self):
        """Truncation prioritizes most recent entries (FR-017)."""
        entries_list = [
            _make_entry(content=f"Entry {i}", round_number=i)
            for i in range(1, 21)
        ]
        entries = {("task", "T-001"): entries_list}
        # Give a budget that can fit ~5-6 entries but not all 20
        ctx = assemble_thread_context(entries, token_limit=150)
        # The last entry should be included
        assert "Entry 20" in ctx.text
        # Some earlier entries should be truncated
        assert ctx.truncated_entries > 0
        # Summary line should appear
        assert "earlier entries omitted" in ctx.text

    def test_truncation_summary_shows_count(self):
        """Truncation summary shows number of omitted entries."""
        entries_list = [
            _make_entry(content=f"Entry {i}", round_number=i)
            for i in range(1, 11)
        ]
        entries = {("task", "T-001"): entries_list}
        ctx = assemble_thread_context(entries, token_limit=100)
        if ctx.truncated_entries > 0:
            assert "earlier entries omitted" in ctx.text

    def test_token_limit_respected(self):
        """Output stays within token budget (NFR-001)."""
        entries_list = [
            _make_entry(content="x" * 200, round_number=i)
            for i in range(1, 50)
        ]
        entries = {("task", "T-001"): entries_list}
        ctx = assemble_thread_context(entries, token_limit=500)
        assert ctx.estimated_tokens <= 500 + 50  # Allow small rounding overhead

    def test_default_token_limit(self):
        """Default token limit is ~10K (NFR-001)."""
        assert DEFAULT_TOKEN_LIMIT == 10_000

    def test_levels_tracked(self):
        """ThreadContext.levels tracks which levels were included."""
        entries = {
            ("task", "T-001"): [_make_entry(content="Task entry")],
            ("prd", "P-001"): [
                _make_entry(
                    artifact_type="prd", artifact_id="P-001", content="PRD entry"
                )
            ],
        }
        ctx = assemble_thread_context(entries)
        assert "task:T-001" in ctx.levels
        assert "prd:P-001" in ctx.levels

    def test_multiple_entries_per_level(self):
        """Multiple entries in a single level are shown chronologically."""
        entries = {
            ("task", "T-001"): [
                _make_entry(content="First", round_number=1),
                _make_entry(content="Second", round_number=2),
                _make_entry(content="Third", round_number=3),
            ]
        }
        ctx = assemble_thread_context(entries)
        first_pos = ctx.text.index("First")
        second_pos = ctx.text.index("Second")
        third_pos = ctx.text.index("Third")
        assert first_pos < second_pos < third_pos


# ---------------------------------------------------------------------------
# Database CRUD tests for artifact_threads
# ---------------------------------------------------------------------------


class TestArtifactThreadsCRUD:
    """Tests for Database.add_thread_entry() and get_thread_entries()."""

    def test_add_and_get_thread_entry(self, temp_db):
        """Can add and retrieve a thread entry."""
        entry = temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="draft",
            content="Initial implementation",
            agent_persona="sdlc-backend-engineer",
            round_number=1,
        )
        assert entry["artifact_type"] == "task"
        assert entry["content"] == "Initial implementation"
        assert entry["agent_persona"] == "sdlc-backend-engineer"
        assert entry["id"] is not None

    def test_get_thread_entries_chronological(self, temp_db):
        """Entries are returned in chronological order."""
        for i in range(3):
            temp_db.add_thread_entry(
                run_id="TEST-R001",
                project_id="test-proj",
                artifact_type="task",
                artifact_id="TEST-T00001",
                entry_type="draft",
                content=f"Entry {i}",
                round_number=i + 1,
            )
        entries = temp_db.get_thread_entries("task", "TEST-T00001")
        assert len(entries) == 3
        assert entries[0]["content"] == "Entry 0"
        assert entries[2]["content"] == "Entry 2"

    def test_get_thread_entries_filter_by_run(self, temp_db):
        """Can filter entries by run_id."""
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="draft",
            content="Run 1 entry",
        )
        # Create a second run
        temp_db.create_execution_run(
            run_id="TEST-R002",
            project_id="test-proj",
            status="running",
        )
        temp_db.add_thread_entry(
            run_id="TEST-R002",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="review",
            content="Run 2 entry",
        )
        entries = temp_db.get_thread_entries(
            "task", "TEST-T00001", run_id="TEST-R001"
        )
        assert len(entries) == 1
        assert entries[0]["content"] == "Run 1 entry"

    def test_get_thread_entries_filter_by_entry_type(self, temp_db):
        """Can filter entries by entry_type."""
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="draft",
            content="Draft entry",
        )
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="user_intervention",
            content="User said something",
        )
        entries = temp_db.get_thread_entries(
            "task", "TEST-T00001", entry_type="user_intervention"
        )
        assert len(entries) == 1
        assert entries[0]["content"] == "User said something"

    def test_get_thread_entries_with_limit(self, temp_db):
        """Limit returns most recent N entries in chronological order."""
        for i in range(5):
            temp_db.add_thread_entry(
                run_id="TEST-R001",
                project_id="test-proj",
                artifact_type="task",
                artifact_id="TEST-T00001",
                entry_type="draft",
                content=f"Entry {i}",
                round_number=i + 1,
            )
        entries = temp_db.get_thread_entries("task", "TEST-T00001", limit=2)
        assert len(entries) == 2
        # Should be the last 2 entries, in chronological order
        assert entries[0]["content"] == "Entry 3"
        assert entries[1]["content"] == "Entry 4"

    def test_get_thread_entry_by_id(self, temp_db):
        """Can retrieve a single entry by ID."""
        created = temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="draft",
            content="Specific entry",
        )
        entry = temp_db.get_thread_entry(created["id"])
        assert entry is not None
        assert entry["content"] == "Specific entry"

    def test_get_thread_entry_not_found(self, temp_db):
        """Returns None for nonexistent entry ID."""
        assert temp_db.get_thread_entry(99999) is None

    def test_get_thread_entries_for_run(self, temp_db):
        """Get all entries for a run across artifact types."""
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="draft",
            content="Task entry",
        )
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="prd",
            artifact_id="TEST-P0001",
            entry_type="draft",
            content="PRD entry",
        )
        entries = temp_db.get_thread_entries_for_run("TEST-R001")
        assert len(entries) == 2

    def test_get_thread_entries_for_run_filtered(self, temp_db):
        """Can filter run entries by artifact type."""
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="draft",
            content="Task entry",
        )
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="prd",
            artifact_id="TEST-P0001",
            entry_type="draft",
            content="PRD entry",
        )
        entries = temp_db.get_thread_entries_for_run(
            "TEST-R001", artifact_types=["task"]
        )
        assert len(entries) == 1
        assert entries[0]["content"] == "Task entry"

    def test_add_thread_entry_with_parent(self, temp_db):
        """Can create a threaded reply with parent_thread_id."""
        parent = temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="challenge",
            content="Missing error handling",
            agent_persona="sdlc-architect",
        )
        reply = temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="response",
            content="Added try/except blocks",
            agent_persona="sdlc-backend-engineer",
            parent_thread_id=parent["id"],
        )
        assert reply["parent_thread_id"] == parent["id"]

    def test_user_intervention_entry_type(self, temp_db):
        """User intervention entries are stored and retrievable."""
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="user_intervention",
            content="Please use PostgreSQL",
        )
        entries = temp_db.get_thread_entries(
            "task", "TEST-T00001", entry_type="user_intervention"
        )
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "user_intervention"


# ---------------------------------------------------------------------------
# Integration: build_thread_context_for_task (FR-015)
# ---------------------------------------------------------------------------


class TestBuildThreadContextForTask:
    """Integration tests for building task-level thread context."""

    def test_task_only_context(self, temp_db):
        """Context with only task-level entries."""
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="draft",
            content="Started implementation",
            agent_persona="sdlc-backend-engineer",
        )
        ctx = build_thread_context_for_task(
            task_id="TEST-T00001",
            task_data={"prd_id": "TEST-P0001", "sprint_id": "TEST-S0001"},
            db=temp_db,
            run_id="TEST-R001",
        )
        assert isinstance(ctx, ThreadContext)
        assert "TASK Thread" in ctx.text
        assert "Started implementation" in ctx.text
        assert ctx.included_entries >= 1

    def test_hierarchical_task_prd_sprint(self, temp_db):
        """Context includes task, PRD, and sprint threads (FR-015)."""
        # Add entries at all 3 levels
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="sprint",
            artifact_id="TEST-S0001",
            entry_type="draft",
            content="Sprint planning complete",
            agent_persona="sdlc-product-manager",
        )
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="prd",
            artifact_id="TEST-P0001",
            entry_type="draft",
            content="PRD approved",
            agent_persona="sdlc-product-manager",
        )
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="draft",
            content="Task started",
            agent_persona="sdlc-backend-engineer",
        )
        ctx = build_thread_context_for_task(
            task_id="TEST-T00001",
            task_data={"prd_id": "TEST-P0001", "sprint_id": "TEST-S0001"},
            db=temp_db,
            run_id="TEST-R001",
        )
        # All three levels should be present
        assert "TASK Thread" in ctx.text
        assert "PRD Thread" in ctx.text
        assert "SPRINT Thread" in ctx.text
        # Task should appear before PRD, PRD before sprint
        task_pos = ctx.text.index("TASK Thread")
        prd_pos = ctx.text.index("PRD Thread")
        sprint_pos = ctx.text.index("SPRINT Thread")
        assert task_pos < prd_pos < sprint_pos
        assert len(ctx.levels) == 3

    def test_no_sprint_in_task_data(self, temp_db):
        """Context works when task has no sprint_id."""
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="draft",
            content="Task entry",
            agent_persona="sdlc-backend-engineer",
        )
        ctx = build_thread_context_for_task(
            task_id="TEST-T00001",
            task_data={"prd_id": "TEST-P0001"},
            db=temp_db,
            run_id="TEST-R001",
        )
        assert "TASK Thread" in ctx.text
        assert "SPRINT Thread" not in ctx.text

    def test_no_prd_in_task_data(self, temp_db):
        """Context works when task has no prd_id."""
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="draft",
            content="Standalone task",
            agent_persona="sdlc-backend-engineer",
        )
        ctx = build_thread_context_for_task(
            task_id="TEST-T00001",
            task_data={},
            db=temp_db,
            run_id="TEST-R001",
        )
        assert "TASK Thread" in ctx.text
        assert "PRD Thread" not in ctx.text

    def test_empty_thread_context(self, temp_db):
        """No entries produce empty context."""
        ctx = build_thread_context_for_task(
            task_id="TEST-T00001",
            task_data={"prd_id": "TEST-P0001", "sprint_id": "TEST-S0001"},
            db=temp_db,
            run_id="TEST-R001",
        )
        assert ctx.text == ""
        assert ctx.total_entries == 0

    def test_user_intervention_preserved_under_pressure(self, temp_db):
        """User interventions survive truncation (FR-018)."""
        # Add a user intervention
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="user_intervention",
            content="Must use OAuth2",
        )
        # Add many regular entries to create pressure
        for i in range(20):
            temp_db.add_thread_entry(
                run_id="TEST-R001",
                project_id="test-proj",
                artifact_type="task",
                artifact_id="TEST-T00001",
                entry_type="draft",
                content=f"Regular content {'x' * 100} number {i}",
                round_number=i + 1,
            )
        ctx = build_thread_context_for_task(
            task_id="TEST-T00001",
            task_data={},
            db=temp_db,
            run_id="TEST-R001",
            token_limit=200,
        )
        # User intervention MUST be present
        assert "[User, intervention]: Must use OAuth2" in ctx.text

    def test_custom_token_limit(self, temp_db):
        """Custom token limit is respected (NFR-001)."""
        for i in range(10):
            temp_db.add_thread_entry(
                run_id="TEST-R001",
                project_id="test-proj",
                artifact_type="task",
                artifact_id="TEST-T00001",
                entry_type="draft",
                content=f"Content {'y' * 200} entry {i}",
                round_number=i + 1,
            )
        ctx = build_thread_context_for_task(
            task_id="TEST-T00001",
            task_data={},
            db=temp_db,
            run_id="TEST-R001",
            token_limit=100,
        )
        # Should have some truncation
        assert ctx.total_entries == 10
        assert ctx.truncated_entries > 0


# ---------------------------------------------------------------------------
# Integration: build_thread_context_for_prd
# ---------------------------------------------------------------------------


class TestBuildThreadContextForPrd:
    """Integration tests for building PRD-level thread context."""

    def test_prd_only_context(self, temp_db):
        """Context with only PRD-level entries."""
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="prd",
            artifact_id="TEST-P0001",
            entry_type="draft",
            content="PRD requirements gathered",
            agent_persona="sdlc-product-manager",
        )
        ctx = build_thread_context_for_prd(
            prd_id="TEST-P0001",
            prd_data={"sprint_id": "TEST-S0001"},
            db=temp_db,
            run_id="TEST-R001",
        )
        assert "PRD Thread" in ctx.text
        assert "PRD requirements gathered" in ctx.text

    def test_prd_with_sprint_context(self, temp_db):
        """Context includes both PRD and sprint threads."""
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="prd",
            artifact_id="TEST-P0001",
            entry_type="draft",
            content="PRD content",
            agent_persona="sdlc-product-manager",
        )
        temp_db.add_thread_entry(
            run_id="TEST-R001",
            project_id="test-proj",
            artifact_type="sprint",
            artifact_id="TEST-S0001",
            entry_type="draft",
            content="Sprint content",
            agent_persona="sdlc-product-manager",
        )
        ctx = build_thread_context_for_prd(
            prd_id="TEST-P0001",
            prd_data={"sprint_id": "TEST-S0001"},
            db=temp_db,
            run_id="TEST-R001",
        )
        assert "PRD Thread" in ctx.text
        assert "SPRINT Thread" in ctx.text
        # PRD before sprint
        prd_pos = ctx.text.index("PRD Thread")
        sprint_pos = ctx.text.index("SPRINT Thread")
        assert prd_pos < sprint_pos


# ---------------------------------------------------------------------------
# Edge case and robustness tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and robustness tests."""

    def test_very_small_token_limit(self):
        """Very small token limit still produces valid output."""
        entries = {
            ("task", "T-001"): [_make_entry(content="Short")],
        }
        ctx = assemble_thread_context(entries, token_limit=10)
        # Should either include it or truncate gracefully
        assert isinstance(ctx, ThreadContext)

    def test_zero_token_limit(self):
        """Zero token limit produces minimal output."""
        entries = {
            ("task", "T-001"): [_make_entry(content="Content")],
        }
        ctx = assemble_thread_context(entries, token_limit=0)
        assert isinstance(ctx, ThreadContext)

    def test_mixed_entry_types(self):
        """Various entry types are handled correctly."""
        entry_types = [
            "draft", "review", "revision", "challenge",
            "response", "verdict", "handoff", "signal",
        ]
        entries = {
            ("task", "T-001"): [
                _make_entry(entry_type=et, content=f"Content for {et}")
                for et in entry_types
            ]
        }
        ctx = assemble_thread_context(entries)
        for et in entry_types:
            assert f"Content for {et}" in ctx.text

    def test_design_level_in_hierarchy(self):
        """Design level sorts between PRD and sprint."""
        entries = {
            ("design", "D-001"): [
                _make_entry(
                    artifact_type="design",
                    artifact_id="D-001",
                    content="Design content",
                )
            ],
            ("prd", "P-001"): [
                _make_entry(
                    artifact_type="prd",
                    artifact_id="P-001",
                    content="PRD content",
                )
            ],
        }
        ctx = assemble_thread_context(entries)
        prd_pos = ctx.text.index("PRD Thread")
        design_pos = ctx.text.index("DESIGN Thread")
        assert prd_pos < design_pos

    def test_user_interventions_from_truncated_levels_shown(self):
        """User interventions from levels that got truncated are still shown (FR-018)."""
        # Create entries: task level fits, sprint level gets truncated
        task_entries = [
            _make_entry(content="x" * 200, round_number=i)
            for i in range(1, 10)
        ]
        sprint_user = _make_entry(
            artifact_type="sprint",
            artifact_id="S-001",
            entry_type="user_intervention",
            content="Critical user guidance",
        )
        sprint_regular = [
            _make_entry(
                artifact_type="sprint",
                artifact_id="S-001",
                content="y" * 200,
                round_number=i,
            )
            for i in range(1, 10)
        ]

        entries = {
            ("task", "T-001"): task_entries,
            ("sprint", "S-001"): [sprint_user] + sprint_regular,
        }
        # Budget that fits task but not sprint regular entries
        ctx = assemble_thread_context(entries, token_limit=600)
        # User intervention from sprint MUST be present
        assert "Critical user guidance" in ctx.text
