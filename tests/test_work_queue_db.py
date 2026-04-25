"""Tests for work queue and artifact thread CRUD operations in database.py."""

import json
import tempfile
from pathlib import Path

import pytest

from a_sdlc.core.database import Database
from a_sdlc.storage import HybridStorage


@pytest.fixture
def temp_db():
    """Create a temporary database instance with project, PRD, sprint, and run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=db_path)
        # create_project(project_id, name, path, shortname=None)
        db.create_project("test-project", "Test Project", "/tmp/test", shortname="TEST")
        db.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-project",
            title="Sprint 1",
            goal="Test sprint",
        )
        db.create_prd(
            prd_id="TEST-P0001",
            project_id="test-project",
            title="Test PRD",
            file_path="/tmp/test/prds/TEST-P0001.md",
            sprint_id="TEST-S0001",
        )
        db.create_task(
            task_id="TEST-T00001",
            project_id="test-project",
            title="Test Task",
            file_path="/tmp/test/tasks/TEST-T00001.md",
            prd_id="TEST-P0001",
        )
        db.create_execution_run(
            run_id="TEST-R001",
            project_id="test-project",
            sprint_id="TEST-S0001",
        )
        db.create_agent(
            agent_id="agent-1",
            project_id="test-project",
            persona_type="backend-engineer",
            display_name="Agent 1",
        )
        yield db


# =========================================================================
# TestWorkItemCRUD
# =========================================================================


class TestWorkItemCRUD:
    """Tests for work item create, get, list, update, and ID generation."""

    def test_create_work_item_auto_id(self, temp_db):
        """create_work_item generates an ID like TEST-W00001."""
        item = temp_db.create_work_item(
            run_id="TEST-R001",
            project_id="test-project",
            work_type="task_implement",
        )
        assert item["id"] == "TEST-W00001"
        assert item["status"] == "pending"
        assert item["work_type"] == "task_implement"

    def test_create_work_item_increments_id(self, temp_db):
        """Second work item gets W00002."""
        temp_db.create_work_item(
            run_id="TEST-R001",
            project_id="test-project",
            work_type="task_implement",
        )
        item2 = temp_db.create_work_item(
            run_id="TEST-R001",
            project_id="test-project",
            work_type="prd_generate",
        )
        assert item2["id"] == "TEST-W00002"

    def test_create_work_item_with_depends_on_list(self, temp_db):
        """depends_on list is serialized and deserialized as JSON."""
        item = temp_db.create_work_item(
            run_id="TEST-R001",
            project_id="test-project",
            work_type="task_implement",
            depends_on=["TEST-W00100", "TEST-W00200"],
        )
        assert item["depends_on"] == ["TEST-W00100", "TEST-W00200"]

    def test_create_work_item_with_config_dict(self, temp_db):
        """config dict is serialized and deserialized as JSON."""
        cfg = {"max_retries": 3, "timeout": 60}
        item = temp_db.create_work_item(
            run_id="TEST-R001",
            project_id="test-project",
            work_type="task_implement",
            config=cfg,
        )
        assert item["config"] == cfg

    def test_create_work_item_with_priority(self, temp_db):
        """Priority is stored correctly."""
        item = temp_db.create_work_item(
            run_id="TEST-R001",
            project_id="test-project",
            work_type="task_implement",
            priority=5,
        )
        assert item["priority"] == 5

    def test_create_work_item_with_artifact(self, temp_db):
        """artifact_type and artifact_id are stored."""
        item = temp_db.create_work_item(
            run_id="TEST-R001",
            project_id="test-project",
            work_type="task_implement",
            artifact_type="task",
            artifact_id="TEST-T00001",
        )
        assert item["artifact_type"] == "task"
        assert item["artifact_id"] == "TEST-T00001"

    def test_get_work_item_found(self, temp_db):
        """get_work_item returns parsed item when found."""
        created = temp_db.create_work_item(
            run_id="TEST-R001",
            project_id="test-project",
            work_type="task_implement",
            depends_on=["dep-1"],
        )
        fetched = temp_db.get_work_item(created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["depends_on"] == ["dep-1"]

    def test_get_work_item_not_found(self, temp_db):
        """get_work_item returns None for non-existent item."""
        assert temp_db.get_work_item("NONEXISTENT") is None

    def test_get_work_items_returns_all(self, temp_db):
        """get_work_items returns all items for a run."""
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="b",
        )
        items = temp_db.get_work_items("TEST-R001")
        assert len(items) == 2

    def test_get_work_items_filter_by_status(self, temp_db):
        """get_work_items filters by status."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        temp_db.update_work_item(item["id"], status="in_progress")
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="b",
        )
        pending = temp_db.get_work_items("TEST-R001", status="pending")
        assert len(pending) == 1
        assert pending[0]["work_type"] == "b"

    def test_get_work_items_ordered_by_priority_desc(self, temp_db):
        """get_work_items returns items ordered by priority DESC."""
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project",
            work_type="low", priority=1,
        )
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project",
            work_type="high", priority=10,
        )
        items = temp_db.get_work_items("TEST-R001")
        assert items[0]["work_type"] == "high"
        assert items[1]["work_type"] == "low"

    def test_update_work_item_status(self, temp_db):
        """update_work_item changes status."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        updated = temp_db.update_work_item(item["id"], status="in_progress")
        assert updated["status"] == "in_progress"

    def test_update_work_item_auto_started_at(self, temp_db):
        """Transitioning to in_progress auto-sets started_at."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        assert item["started_at"] is None
        updated = temp_db.update_work_item(item["id"], status="in_progress")
        assert updated["started_at"] is not None

    def test_update_work_item_auto_completed_at(self, temp_db):
        """Transitioning to completed auto-sets completed_at."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        updated = temp_db.update_work_item(item["id"], status="completed")
        assert updated["completed_at"] is not None

    def test_count_work_items_by_status(self, temp_db):
        """count_work_items_by_status returns correct counts."""
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="b",
        )
        item3 = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="c",
        )
        temp_db.update_work_item(item3["id"], status="completed")
        counts = temp_db.count_work_items_by_status("TEST-R001")
        assert counts.get("pending") == 2
        assert counts.get("completed") == 1

    def test_get_next_work_item_id(self, temp_db):
        """get_next_work_item_id returns correct format."""
        wid = temp_db.get_next_work_item_id("test-project")
        assert wid == "TEST-W00001"
        # After creating one item, next ID should be W00002
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        wid2 = temp_db.get_next_work_item_id("test-project")
        assert wid2 == "TEST-W00002"

    def test_get_next_work_item_id_invalid_project(self, temp_db):
        """get_next_work_item_id raises ValueError for unknown project."""
        with pytest.raises(ValueError, match="Project not found"):
            temp_db.get_next_work_item_id("nonexistent")


# =========================================================================
# TestDispatchableItems
# =========================================================================


class TestDispatchableItems:
    """Tests for the get_dispatchable_items dispatch logic."""

    def test_dispatch_empty_queue(self, temp_db):
        """Empty queue returns empty list."""
        result = temp_db.get_dispatchable_items("TEST-R001")
        assert result == []

    def test_dispatch_single_pending(self, temp_db):
        """Single pending item with no deps is dispatchable."""
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        result = temp_db.get_dispatchable_items("TEST-R001")
        assert len(result) == 1

    def test_dispatch_respects_max_concurrent(self, temp_db):
        """Dispatch returns nothing when in_progress count >= max_concurrent."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        temp_db.update_work_item(item["id"], status="in_progress")
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="b",
        )
        # max_concurrent=1 and 1 item already in_progress
        result = temp_db.get_dispatchable_items("TEST-R001", max_concurrent=1)
        assert result == []

    def test_dispatch_limits_to_available_slots(self, temp_db):
        """Dispatch returns at most max_concurrent - in_progress items."""
        for i in range(5):
            temp_db.create_work_item(
                run_id="TEST-R001", project_id="test-project", work_type=f"t{i}",
            )
        result = temp_db.get_dispatchable_items("TEST-R001", max_concurrent=2)
        assert len(result) == 2

    def test_dispatch_blocks_on_unmet_dependencies(self, temp_db):
        """Item with unmet dependencies is not dispatchable."""
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
            depends_on=["NONEXISTENT-ID"],
        )
        result = temp_db.get_dispatchable_items("TEST-R001")
        assert result == []

    def test_dispatch_allows_met_dependencies(self, temp_db):
        """Item whose dependencies are all completed is dispatchable."""
        dep = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="dep",
        )
        temp_db.update_work_item(dep["id"], status="completed")
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="child",
            depends_on=[dep["id"]],
        )
        result = temp_db.get_dispatchable_items("TEST-R001")
        assert len(result) == 1
        assert result[0]["work_type"] == "child"

    def test_dispatch_priority_ordering(self, temp_db):
        """Higher priority items come first in dispatch results."""
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project",
            work_type="low", priority=1,
        )
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project",
            work_type="high", priority=10,
        )
        result = temp_db.get_dispatchable_items("TEST-R001", max_concurrent=1)
        assert result[0]["work_type"] == "high"

    def test_dispatch_skips_non_pending(self, temp_db):
        """Only pending items are considered for dispatch."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        temp_db.update_work_item(item["id"], status="failed")
        result = temp_db.get_dispatchable_items("TEST-R001")
        assert result == []


# =========================================================================
# TestPerItemControl
# =========================================================================


class TestPerItemControl:
    """Tests for pause, cancel, skip, force_approve, retry, answer."""

    def test_pause_from_pending(self, temp_db):
        """Pausing a pending item sets status to paused."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        paused = temp_db.pause_work_item(item["id"])
        assert paused["status"] == "paused"

    def test_pause_from_in_progress(self, temp_db):
        """Pausing an in_progress item sets status to paused."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        temp_db.update_work_item(item["id"], status="in_progress")
        paused = temp_db.pause_work_item(item["id"])
        assert paused["status"] == "paused"

    def test_pause_invalid_state(self, temp_db):
        """Pausing a completed item raises ValueError."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        temp_db.update_work_item(item["id"], status="completed")
        with pytest.raises(ValueError, match="Cannot pause"):
            temp_db.pause_work_item(item["id"])

    def test_cancel_from_pending(self, temp_db):
        """Cancelling a pending item sets status to cancelled."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        cancelled = temp_db.cancel_work_item(item["id"])
        assert cancelled["status"] == "cancelled"

    def test_cancel_invalid_terminal(self, temp_db):
        """Cancelling a completed item raises ValueError."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        temp_db.update_work_item(item["id"], status="completed")
        with pytest.raises(ValueError, match="Cannot cancel"):
            temp_db.cancel_work_item(item["id"])

    def test_skip_from_pending(self, temp_db):
        """Skipping a pending item sets status to skipped."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        skipped = temp_db.skip_work_item(item["id"], reason="not needed")
        assert skipped["status"] == "skipped"
        assert skipped["result"] == "not needed"

    def test_skip_invalid_state(self, temp_db):
        """Skipping an in_progress item raises ValueError."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        temp_db.update_work_item(item["id"], status="in_progress")
        with pytest.raises(ValueError, match="Cannot skip"):
            temp_db.skip_work_item(item["id"])

    def test_force_approve(self, temp_db):
        """Force-approving sets status=completed, result=force_approved."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        approved = temp_db.force_approve_work_item(item["id"])
        assert approved["status"] == "completed"
        assert approved["result"] == "force_approved"

    def test_retry_from_failed(self, temp_db):
        """Retrying a failed item resets to pending and increments retry_count."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        temp_db.update_work_item(item["id"], status="failed")
        retried = temp_db.retry_work_item(item["id"])
        assert retried["status"] == "pending"
        assert retried["retry_count"] == 1

    def test_retry_invalid_state(self, temp_db):
        """Retrying a pending item raises ValueError."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        with pytest.raises(ValueError, match="Cannot retry"):
            temp_db.retry_work_item(item["id"])

    def test_answer_question_item(self, temp_db):
        """Answering a question item sets status=completed, result=answer."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="question",
        )
        answered = temp_db.answer_work_item(item["id"], "yes")
        assert answered["status"] == "completed"
        assert answered["result"] == "yes"

    def test_answer_non_question_raises(self, temp_db):
        """Answering a non-question item raises ValueError."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="task_implement",
        )
        with pytest.raises(ValueError, match="must be 'question'"):
            temp_db.answer_work_item(item["id"], "yes")


# =========================================================================
# TestThreadEntryCRUD
# =========================================================================


class TestThreadEntryCRUD:
    """Tests for artifact thread entry creation and retrieval."""

    def test_create_thread_entry(self, temp_db):
        """Creating a thread entry returns a dict with correct fields."""
        entry = temp_db.create_artifact_thread_entry(
            run_id="TEST-R001",
            project_id="test-project",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="creation",
        )
        assert entry["artifact_type"] == "task"
        assert entry["entry_type"] == "creation"
        assert entry["id"] is not None

    def test_thread_entry_json_content_roundtrip(self, temp_db):
        """JSON content stored as string is returned as-is (raw string)."""
        content_data = {"summary": "Created task", "details": [1, 2, 3]}
        entry = temp_db.create_artifact_thread_entry(
            run_id="TEST-R001",
            project_id="test-project",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="creation",
            content=json.dumps(content_data),
        )
        # create_artifact_thread_entry returns dict(row), content is raw string.
        # Verify JSON round-trip: stored string can be deserialized back.
        raw = entry["content"]
        assert json.loads(raw) == content_data

    def test_thread_entry_with_agent(self, temp_db):
        """Thread entry stores agent_id and agent_persona."""
        entry = temp_db.create_artifact_thread_entry(
            run_id="TEST-R001",
            project_id="test-project",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="challenge",
            agent_id="agent-1",
            agent_persona="architect",
        )
        assert entry["agent_id"] == "agent-1"
        assert entry["agent_persona"] == "architect"

    def test_thread_entry_round_number(self, temp_db):
        """Thread entry stores round_number."""
        entry = temp_db.create_artifact_thread_entry(
            run_id="TEST-R001",
            project_id="test-project",
            artifact_type="task",
            artifact_id="TEST-T00001",
            entry_type="challenge",
            round_number=3,
        )
        assert entry["round_number"] == 3

    def test_list_artifact_threads(self, temp_db):
        """list_artifact_threads returns entries for a run."""
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="task", artifact_id="TEST-T00001",
            entry_type="creation",
        )
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="prd", artifact_id="TEST-P0001",
            entry_type="creation",
        )
        all_entries = temp_db.list_artifact_threads("TEST-R001")
        assert len(all_entries) == 2

    def test_list_artifact_threads_filter_type(self, temp_db):
        """list_artifact_threads filters by artifact_type."""
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="task", artifact_id="TEST-T00001",
            entry_type="creation",
        )
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="prd", artifact_id="TEST-P0001",
            entry_type="creation",
        )
        task_entries = temp_db.list_artifact_threads(
            "TEST-R001", artifact_type="task"
        )
        assert len(task_entries) == 1
        assert task_entries[0]["artifact_type"] == "task"

    def test_get_thread_entries_for_run(self, temp_db):
        """get_thread_entries_for_run returns all entries for a run."""
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="task", artifact_id="TEST-T00001",
            entry_type="creation",
        )
        entries = temp_db.get_thread_entries_for_run("TEST-R001")
        assert len(entries) == 1

    def test_get_thread_entry_by_id(self, temp_db):
        """get_thread_entry returns a single entry by ID."""
        created = temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="task", artifact_id="TEST-T00001",
            entry_type="creation",
        )
        fetched = temp_db.get_thread_entry(created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_count_thread_entries(self, temp_db):
        """count_thread_entries returns correct count for a run."""
        assert temp_db.count_thread_entries("TEST-R001") == 0
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="task", artifact_id="TEST-T00001",
            entry_type="creation",
        )
        assert temp_db.count_thread_entries("TEST-R001") == 1

    def test_list_artifact_threads_by_artifact(self, temp_db):
        """list_artifact_threads_by_artifact returns entries for specific artifact."""
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="task", artifact_id="TEST-T00001",
            entry_type="creation",
        )
        entries = temp_db.list_artifact_threads_by_artifact("task", "TEST-T00001")
        assert len(entries) == 1

    def test_parent_thread_id(self, temp_db):
        """Thread entries can reference a parent entry."""
        parent = temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="task", artifact_id="TEST-T00001",
            entry_type="creation",
        )
        child = temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="task", artifact_id="TEST-T00001",
            entry_type="revision",
            parent_thread_id=parent["id"],
        )
        assert child["parent_thread_id"] == parent["id"]


# =========================================================================
# TestHierarchicalThread
# =========================================================================


class TestHierarchicalThread:
    """Tests for get_hierarchical_thread across sprint/PRD/task levels."""

    def test_task_level_hierarchy(self, temp_db):
        """Task hierarchy includes sprint, PRD, and task entries."""
        # Create entries at each level
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="sprint", artifact_id="TEST-S0001",
            entry_type="creation", content="Sprint started",
        )
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="prd", artifact_id="TEST-P0001",
            entry_type="creation", content="PRD created",
        )
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="task", artifact_id="TEST-T00001",
            entry_type="creation", content="Task started",
        )

        entries = temp_db.get_hierarchical_thread(
            "task", "TEST-T00001", "TEST-R001"
        )
        assert len(entries) == 3
        # Sprint entries first, then PRD, then task
        assert entries[0]["hierarchy_level"] == "sprint"
        assert entries[1]["hierarchy_level"] == "prd"
        assert entries[2]["hierarchy_level"] == "task"

    def test_prd_level_hierarchy(self, temp_db):
        """PRD hierarchy includes sprint and PRD entries."""
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="sprint", artifact_id="TEST-S0001",
            entry_type="creation",
        )
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="prd", artifact_id="TEST-P0001",
            entry_type="creation",
        )

        entries = temp_db.get_hierarchical_thread(
            "prd", "TEST-P0001", "TEST-R001"
        )
        assert len(entries) == 2
        assert entries[0]["hierarchy_level"] == "sprint"
        assert entries[1]["hierarchy_level"] == "prd"

    def test_sprint_level_hierarchy(self, temp_db):
        """Sprint hierarchy includes only sprint entries."""
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="sprint", artifact_id="TEST-S0001",
            entry_type="creation",
        )
        entries = temp_db.get_hierarchical_thread(
            "sprint", "TEST-S0001", "TEST-R001"
        )
        assert len(entries) == 1
        assert entries[0]["hierarchy_level"] == "sprint"

    def test_hierarchy_no_sprint(self, temp_db):
        """Task with PRD not assigned to sprint omits sprint-level entries."""
        # Create a PRD without sprint_id
        temp_db.create_prd(
            prd_id="TEST-P0002", project_id="test-project",
            title="Unsprinted PRD",
            file_path="/tmp/test/prds/TEST-P0002.md",
        )
        temp_db.create_task(
            task_id="TEST-T00002", project_id="test-project",
            title="Unsprinted Task",
            file_path="/tmp/test/tasks/TEST-T00002.md",
            prd_id="TEST-P0002",
        )
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="prd", artifact_id="TEST-P0002",
            entry_type="creation",
        )
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="task", artifact_id="TEST-T00002",
            entry_type="creation",
        )

        entries = temp_db.get_hierarchical_thread(
            "task", "TEST-T00002", "TEST-R001"
        )
        # Should only have PRD and task entries (no sprint)
        assert len(entries) == 2
        levels = [e["hierarchy_level"] for e in entries]
        assert "sprint" not in levels
        assert levels == ["prd", "task"]


# =========================================================================
# TestRunStateHash
# =========================================================================


class TestRunStateHash:
    """Tests for get_run_state_hash change detection."""

    def test_hash_empty_run(self, temp_db):
        """Hash for run with no items or threads is deterministic."""
        h1 = temp_db.get_run_state_hash("TEST-R001")
        h2 = temp_db.get_run_state_hash("TEST-R001")
        assert h1 == h2
        assert h1 != ""

    def test_hash_changes_on_work_item_add(self, temp_db):
        """Hash changes when a work item is added."""
        h_before = temp_db.get_run_state_hash("TEST-R001")
        temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        h_after = temp_db.get_run_state_hash("TEST-R001")
        assert h_before != h_after

    def test_hash_changes_on_status_update(self, temp_db):
        """Hash changes when a work item status changes."""
        item = temp_db.create_work_item(
            run_id="TEST-R001", project_id="test-project", work_type="a",
        )
        h_before = temp_db.get_run_state_hash("TEST-R001")
        temp_db.update_work_item(item["id"], status="completed")
        h_after = temp_db.get_run_state_hash("TEST-R001")
        assert h_before != h_after

    def test_hash_changes_on_thread_add(self, temp_db):
        """Hash changes when a thread entry is added."""
        h_before = temp_db.get_run_state_hash("TEST-R001")
        temp_db.create_artifact_thread_entry(
            run_id="TEST-R001", project_id="test-project",
            artifact_type="task", artifact_id="TEST-T00001",
            entry_type="creation",
        )
        h_after = temp_db.get_run_state_hash("TEST-R001")
        assert h_before != h_after


# =========================================================================
# TestHybridStorageDelegation
# =========================================================================


class TestHybridStorageDelegation:
    """Tests verifying HybridStorage delegates to Database correctly."""

    def test_create_and_get_work_item(self):
        """HybridStorage.create_work_item delegates to Database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = HybridStorage(base_path=Path(tmpdir))
            storage._db.create_project(
                "test-project", "Test", "/tmp/test", shortname="TEST"
            )
            storage._db.create_sprint(
                sprint_id="TEST-S0001", project_id="test-project",
                title="Sprint 1", goal="goal",
            )
            storage._db.create_execution_run(
                run_id="TEST-R001", project_id="test-project",
                sprint_id="TEST-S0001",
            )
            item = storage.create_work_item(
                run_id="TEST-R001", project_id="test-project",
                work_type="task_implement", priority=5,
            )
            assert item["id"] == "TEST-W00001"
            assert item["priority"] == 5

            fetched = storage.get_work_item(item["id"])
            assert fetched is not None
            assert fetched["id"] == item["id"]

    def test_dispatch_and_control(self):
        """HybridStorage dispatch and per-item control methods work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = HybridStorage(base_path=Path(tmpdir))
            storage._db.create_project(
                "test-project", "Test", "/tmp/test", shortname="TEST"
            )
            storage._db.create_sprint(
                sprint_id="TEST-S0001", project_id="test-project",
                title="Sprint 1", goal="goal",
            )
            storage._db.create_execution_run(
                run_id="TEST-R001", project_id="test-project",
                sprint_id="TEST-S0001",
            )
            item = storage.create_work_item(
                run_id="TEST-R001", project_id="test-project",
                work_type="task_implement",
            )
            # Dispatch should return the item
            dispatchable = storage.get_dispatchable_items("TEST-R001")
            assert len(dispatchable) == 1

            # Pause via HybridStorage
            paused = storage.pause_work_item(item["id"])
            assert paused["status"] == "paused"
