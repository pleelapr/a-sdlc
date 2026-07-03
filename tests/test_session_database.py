"""Comprehensive tests for SessionDatabase (ORM-based replacement for Database)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from a_sdlc.core.engine import reset_engine_cache
from a_sdlc.core.session_database import SessionDatabase
from a_sdlc.core.storage_config import StorageConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    """Ensure the engine cache is reset between tests."""
    reset_engine_cache()
    yield
    reset_engine_cache()


@pytest.fixture
def db():
    """Create a fresh in-memory SessionDatabase for each test."""
    cfg = StorageConfig(database_url="sqlite:///:memory:")
    return SessionDatabase(config=cfg)


@pytest.fixture
def db_with_project(db: SessionDatabase):
    """SessionDatabase with a seeded project."""
    db.create_project("proj-1", "My Project", shortname="MYPR")
    return db


@pytest.fixture
def db_full(db_with_project: SessionDatabase):
    """SessionDatabase with project, PRD, sprint, task seeded."""
    db = db_with_project
    db.create_prd(
        prd_id="MYPR-P0001",
        project_id="proj-1",
        title="Test PRD",
        file_path="/tmp/prds/MYPR-P0001.md",
    )
    db.create_sprint(
        sprint_id="MYPR-S0001",
        project_id="proj-1",
        title="Sprint 1",
        goal="Test sprint",
    )
    db.create_task(
        task_id="MYPR-T00001",
        project_id="proj-1",
        prd_id="MYPR-P0001",
        title="Test Task",
        file_path="/tmp/tasks/MYPR-T00001.md",
    )
    # Assign PRD to sprint
    db.update_prd("MYPR-P0001", sprint_id="MYPR-S0001")
    return db


# ---------------------------------------------------------------------------
# Engine & Initialization Tests
# ---------------------------------------------------------------------------


class TestEngineInit:
    """Tests for engine factory and SessionDatabase initialization."""

    def test_create_from_config(self):
        cfg = StorageConfig(database_url="sqlite:///:memory:")
        db = SessionDatabase(config=cfg)
        assert db is not None

    def test_create_from_db_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = SessionDatabase(db_path=db_path)
            assert db is not None
            assert db_path.exists()
            # Dispose engine so Windows can clean up the temp directory
            db._engine.dispose()

    def test_tables_created(self, db: SessionDatabase):
        # Simple smoke test: we can create a project
        result = db.create_project("p1", "P1", shortname="PONE")
        assert result is not None
        assert result["id"] == "p1"


# ---------------------------------------------------------------------------
# Project Tests
# ---------------------------------------------------------------------------


class TestProjects:
    """Tests for project CRUD operations."""

    def test_create_project(self, db: SessionDatabase):
        p = db.create_project("proj-1", "My Project", shortname="MYPR")
        assert p is not None
        assert p["id"] == "proj-1"
        assert p["shortname"] == "MYPR"
        assert p["name"] == "My Project"

    def test_create_project_auto_shortname(self, db: SessionDatabase):
        p = db.create_project("p1", "Hello World")
        assert p is not None
        assert len(p["shortname"]) == 4

    def test_create_project_invalid_shortname(self, db: SessionDatabase):
        with pytest.raises(ValueError, match="4 characters"):
            db.create_project("p1", "Test", shortname="AB")

    def test_create_project_duplicate_shortname(self, db: SessionDatabase):
        db.create_project("p1", "First", shortname="ABCD")
        with pytest.raises(ValueError, match="already in use"):
            db.create_project("p2", "Second", shortname="ABCD")

    def test_get_project(self, db_with_project: SessionDatabase):
        p = db_with_project.get_project("proj-1")
        assert p is not None
        assert p["name"] == "My Project"

    def test_get_project_not_found(self, db: SessionDatabase):
        assert db.get_project("nonexistent") is None

    def test_get_project_by_shortname(self, db_with_project: SessionDatabase):
        p = db_with_project.get_project_by_shortname("MYPR")
        assert p is not None
        assert p["id"] == "proj-1"

    def test_list_projects(self, db: SessionDatabase):
        db.create_project("p1", "P1", shortname="AAAA")
        db.create_project("p2", "P2", shortname="BBBB")
        projects = db.list_projects()
        assert len(projects) == 2

    def test_list_projects_limit(self, db: SessionDatabase):
        db.create_project("p1", "P1", shortname="AAAA")
        db.create_project("p2", "P2", shortname="BBBB")
        db.create_project("p3", "P3", shortname="CCCC")
        assert len(db.list_projects(limit=2)) == 2
        assert len(db.list_projects()) == 3  # default: all rows

    def test_touch_project_returns_and_touches(self, db: SessionDatabase):
        db.create_project("p1", "P1", shortname="AAAA")
        result = db.touch_project("p1")
        assert result is not None
        assert result["id"] == "p1"

    def test_touch_project_missing_returns_none(self, db: SessionDatabase):
        assert db.touch_project("nope") is None

    def test_delete_project(self, db_with_project: SessionDatabase):
        assert db_with_project.delete_project("proj-1") is True
        assert db_with_project.get_project("proj-1") is None

    def test_delete_project_not_found(self, db: SessionDatabase):
        assert db.delete_project("nope") is False

    def test_get_most_recent_project(self, db: SessionDatabase):
        db.create_project("p1", "P1", shortname="AAAA")
        db.create_project("p2", "P2", shortname="BBBB")
        p = db.get_most_recent_project()
        assert p is not None
        # The most recently created should be the most recently accessed
        assert p["id"] == "p2"

    def test_is_shortname_available(self, db_with_project: SessionDatabase):
        assert db_with_project.is_shortname_available("MYPR") is False
        assert db_with_project.is_shortname_available("ZZZZ") is True

    def test_validate_shortname(self):
        ok, _ = SessionDatabase.validate_shortname("ABCD")
        assert ok is True
        ok, msg = SessionDatabase.validate_shortname("ab")
        assert ok is False
        assert "4 characters" in msg
        ok, msg = SessionDatabase.validate_shortname("abc4")
        assert ok is False


# ---------------------------------------------------------------------------
# PRD Tests
# ---------------------------------------------------------------------------


class TestPRDs:
    """Tests for PRD CRUD operations."""

    def test_create_prd(self, db_with_project: SessionDatabase):
        prd = db_with_project.create_prd("MYPR-P0001", "proj-1", "My PRD", file_path="/tmp/prd.md")
        assert prd is not None
        assert prd["id"] == "MYPR-P0001"
        assert prd["status"] == "draft"
        assert prd["title"] == "My PRD"

    def test_get_prd(self, db_full: SessionDatabase):
        prd = db_full.get_prd("MYPR-P0001")
        assert prd is not None
        assert prd["title"] == "Test PRD"

    def test_get_prd_not_found(self, db: SessionDatabase):
        assert db.get_prd("nope") is None

    def test_list_prds(self, db_full: SessionDatabase):
        prds = db_full.list_prds("proj-1")
        assert len(prds) == 1
        assert prds[0]["id"] == "MYPR-P0001"

    def test_list_prds_by_status(self, db_full: SessionDatabase):
        assert len(db_full.list_prds("proj-1", status="draft")) == 1
        assert len(db_full.list_prds("proj-1", status="approved")) == 0

    def test_list_prds_by_sprint(self, db_full: SessionDatabase):
        prds = db_full.list_prds("proj-1", sprint_id="MYPR-S0001")
        assert len(prds) == 1

    def test_update_prd_status(self, db_full: SessionDatabase):
        prd = db_full.update_prd("MYPR-P0001", status="ready")
        assert prd is not None
        assert prd["status"] == "ready"
        assert prd["ready_at"] is not None

    def test_update_prd_status_completed(self, db_full: SessionDatabase):
        prd = db_full.update_prd("MYPR-P0001", status="completed")
        assert prd is not None
        assert prd["completed_at"] is not None

    def test_update_prd_not_found(self, db: SessionDatabase):
        assert db.update_prd("nope", title="X") is None

    def test_delete_prd(self, db_full: SessionDatabase):
        # Must delete dependent task first (FK constraint)
        db_full.delete_task("MYPR-T00001")
        assert db_full.delete_prd("MYPR-P0001") is True
        assert db_full.get_prd("MYPR-P0001") is None

    def test_get_next_prd_id(self, db_with_project: SessionDatabase):
        prd_id = db_with_project.get_next_prd_id("proj-1")
        assert prd_id == "MYPR-P0001"

    def test_get_next_prd_id_increments(self, db_full: SessionDatabase):
        prd_id = db_full.get_next_prd_id("proj-1")
        assert prd_id == "MYPR-P0002"


# ---------------------------------------------------------------------------
# Task Tests
# ---------------------------------------------------------------------------


class TestTasks:
    """Tests for task CRUD operations."""

    def test_create_task(self, db_with_project: SessionDatabase):
        task = db_with_project.create_task("MYPR-T00001", "proj-1", "My Task", priority="high")
        assert task is not None
        assert task["id"] == "MYPR-T00001"
        assert task["priority"] == "high"
        assert task["status"] == "pending"

    def test_get_task(self, db_full: SessionDatabase):
        task = db_full.get_task("MYPR-T00001")
        assert task is not None
        assert task["title"] == "Test Task"

    def test_get_task_not_found(self, db: SessionDatabase):
        assert db.get_task("nope") is None

    def test_list_tasks(self, db_full: SessionDatabase):
        tasks = db_full.list_tasks("proj-1")
        assert len(tasks) == 1

    def test_list_tasks_by_status(self, db_full: SessionDatabase):
        assert len(db_full.list_tasks("proj-1", status="pending")) == 1
        assert len(db_full.list_tasks("proj-1", status="completed")) == 0

    def test_list_tasks_by_prd(self, db_full: SessionDatabase):
        tasks = db_full.list_tasks("proj-1", prd_id="MYPR-P0001")
        assert len(tasks) == 1

    def test_update_task_in_progress(self, db_full: SessionDatabase):
        task = db_full.update_task("MYPR-T00001", status="in_progress")
        assert task is not None
        assert task["status"] == "in_progress"
        assert task["started_at"] is not None

    def test_update_task_completed(self, db_full: SessionDatabase):
        db_full.update_task("MYPR-T00001", status="in_progress")
        task = db_full.update_task("MYPR-T00001", status="completed")
        assert task is not None
        assert task["status"] == "completed"
        assert task["completed_at"] is not None

    def test_update_task_not_found(self, db: SessionDatabase):
        assert db.update_task("nope", title="X") is None

    def test_delete_task(self, db_full: SessionDatabase):
        assert db_full.delete_task("MYPR-T00001") is True
        assert db_full.get_task("MYPR-T00001") is None

    def test_get_next_task_id(self, db_with_project: SessionDatabase):
        assert db_with_project.get_next_task_id("proj-1") == "MYPR-T00001"

    def test_get_next_task_id_increments(self, db_full: SessionDatabase):
        assert db_full.get_next_task_id("proj-1") == "MYPR-T00002"


# ---------------------------------------------------------------------------
# Sprint Tests
# ---------------------------------------------------------------------------


class TestSprints:
    """Tests for sprint CRUD operations."""

    def test_create_sprint(self, db_with_project: SessionDatabase):
        sprint = db_with_project.create_sprint("MYPR-S0001", "proj-1", "Sprint 1", goal="Do stuff")
        assert sprint is not None
        assert sprint["id"] == "MYPR-S0001"
        assert sprint["status"] == "planned"

    def test_get_sprint(self, db_full: SessionDatabase):
        sprint = db_full.get_sprint("MYPR-S0001")
        assert sprint is not None
        assert sprint["title"] == "Sprint 1"
        assert "prd_count" in sprint
        assert sprint["prd_count"] == 1

    def test_get_sprint_with_task_counts(self, db_full: SessionDatabase):
        sprint = db_full.get_sprint("MYPR-S0001")
        assert sprint is not None
        assert "task_counts" in sprint
        # Task inherited via PRD
        assert sprint["task_counts"].get("pending", 0) == 1

    def test_get_sprint_not_found(self, db: SessionDatabase):
        assert db.get_sprint("nope") is None

    def test_list_sprints(self, db_full: SessionDatabase):
        sprints = db_full.list_sprints("proj-1")
        assert len(sprints) == 1

    def test_update_sprint_active(self, db_full: SessionDatabase):
        sprint = db_full.update_sprint("MYPR-S0001", status="active")
        assert sprint is not None
        assert sprint["status"] == "active"
        assert sprint["started_at"] is not None

    def test_update_sprint_completed(self, db_full: SessionDatabase):
        db_full.update_sprint("MYPR-S0001", status="active")
        sprint = db_full.update_sprint("MYPR-S0001", status="completed")
        assert sprint is not None
        assert sprint["completed_at"] is not None

    def test_delete_sprint(self, db_full: SessionDatabase):
        # Unassign PRD from sprint first (FK constraint)
        db_full.update_prd("MYPR-P0001", sprint_id=None)
        assert db_full.delete_sprint("MYPR-S0001") is True
        assert db_full.get_sprint("MYPR-S0001") is None

    def test_get_sprint_prds(self, db_full: SessionDatabase):
        prds = db_full.get_sprint_prds("MYPR-S0001")
        assert len(prds) == 1
        assert prds[0]["id"] == "MYPR-P0001"

    def test_assign_prd_to_sprint(self, db_full: SessionDatabase):
        db_full.create_prd("MYPR-P0002", "proj-1", "PRD 2")
        db_full.assign_prd_to_sprint("MYPR-P0002", "MYPR-S0001")
        prds = db_full.get_sprint_prds("MYPR-S0001")
        assert len(prds) == 2

    def test_get_next_sprint_id(self, db_with_project: SessionDatabase):
        assert db_with_project.get_next_sprint_id("proj-1") == "MYPR-S0001"


# ---------------------------------------------------------------------------
# Design Tests
# ---------------------------------------------------------------------------


class TestDesigns:
    """Tests for design CRUD operations."""

    def test_create_design(self, db_full: SessionDatabase):
        design = db_full.create_design(
            "MYPR-D0001", "MYPR-P0001", "proj-1", file_path="/tmp/designs/d1.md"
        )
        assert design is not None
        assert design["id"] == "MYPR-D0001"

    def test_get_design(self, db_full: SessionDatabase):
        db_full.create_design("MYPR-D0001", "MYPR-P0001", "proj-1")
        design = db_full.get_design("MYPR-D0001")
        assert design is not None

    def test_get_design_by_prd(self, db_full: SessionDatabase):
        db_full.create_design("MYPR-D0001", "MYPR-P0001", "proj-1")
        design = db_full.get_design_by_prd("MYPR-P0001")
        assert design is not None
        assert design["prd_id"] == "MYPR-P0001"

    def test_list_designs(self, db_full: SessionDatabase):
        db_full.create_design("MYPR-D0001", "MYPR-P0001", "proj-1")
        designs = db_full.list_designs("proj-1")
        assert len(designs) == 1

    def test_update_design(self, db_full: SessionDatabase):
        db_full.create_design("MYPR-D0001", "MYPR-P0001", "proj-1")
        result = db_full.update_design("MYPR-D0001", file_path="/new/path.md")
        assert result is not None
        assert result["file_path"] == "/new/path.md"

    def test_delete_design(self, db_full: SessionDatabase):
        db_full.create_design("MYPR-D0001", "MYPR-P0001", "proj-1")
        assert db_full.delete_design("MYPR-D0001") is True
        assert db_full.get_design("MYPR-D0001") is None


# ---------------------------------------------------------------------------
# Sync Mapping Tests
# ---------------------------------------------------------------------------


class TestSyncMappings:
    """Tests for sync mapping operations."""

    def test_create_sync_mapping(self, db_full: SessionDatabase):
        m = db_full.create_sync_mapping("sprint", "MYPR-S0001", "linear", "ext-123")
        assert m["entity_type"] == "sprint"
        assert m["external_id"] == "ext-123"

    def test_get_sync_mapping(self, db_full: SessionDatabase):
        db_full.create_sync_mapping("sprint", "MYPR-S0001", "linear", "ext-123")
        m = db_full.get_sync_mapping("sprint", "MYPR-S0001", "linear")
        assert m is not None
        assert m["external_id"] == "ext-123"

    def test_get_sync_mapping_by_external(self, db_full: SessionDatabase):
        db_full.create_sync_mapping("sprint", "MYPR-S0001", "linear", "ext-123")
        m = db_full.get_sync_mapping_by_external("sprint", "linear", "ext-123")
        assert m is not None
        assert m["local_id"] == "MYPR-S0001"

    def test_list_sync_mappings(self, db_full: SessionDatabase):
        db_full.create_sync_mapping("sprint", "MYPR-S0001", "linear", "ext-1")
        db_full.create_sync_mapping("task", "MYPR-T00001", "jira", "ext-2")
        mappings = db_full.list_sync_mappings()
        assert len(mappings) == 2

    def test_list_sync_mappings_filtered(self, db_full: SessionDatabase):
        db_full.create_sync_mapping("sprint", "MYPR-S0001", "linear", "ext-1")
        db_full.create_sync_mapping("task", "MYPR-T00001", "jira", "ext-2")
        mappings = db_full.list_sync_mappings(entity_type="sprint")
        assert len(mappings) == 1

    def test_update_sync_mapping(self, db_full: SessionDatabase):
        db_full.create_sync_mapping("sprint", "MYPR-S0001", "linear", "ext-123")
        m = db_full.update_sync_mapping("sprint", "MYPR-S0001", "linear", sync_status="synced")
        assert m is not None
        assert m["sync_status"] == "synced"

    def test_delete_sync_mapping(self, db_full: SessionDatabase):
        db_full.create_sync_mapping("sprint", "MYPR-S0001", "linear", "ext-123")
        assert db_full.delete_sync_mapping("sprint", "MYPR-S0001", "linear") is True
        assert db_full.get_sync_mapping("sprint", "MYPR-S0001", "linear") is None


# ---------------------------------------------------------------------------
# External Config Tests
# ---------------------------------------------------------------------------


class TestExternalConfig:
    """Tests for external config operations."""

    def test_set_and_get_config(self, db_full: SessionDatabase):
        cfg = {"api_key": "test-key", "team_id": "team-1"}
        db_full.set_external_config("proj-1", "linear", cfg)
        result = db_full.get_external_config("proj-1", "linear")
        assert result is not None
        assert result["config"]["api_key"] == "test-key"

    def test_update_config(self, db_full: SessionDatabase):
        db_full.set_external_config("proj-1", "linear", {"key": "v1"})
        db_full.set_external_config("proj-1", "linear", {"key": "v2"})
        result = db_full.get_external_config("proj-1", "linear")
        assert result["config"]["key"] == "v2"

    def test_delete_config(self, db_full: SessionDatabase):
        db_full.set_external_config("proj-1", "jira", {"token": "abc"})
        assert db_full.delete_external_config("proj-1", "jira") is True
        assert db_full.get_external_config("proj-1", "jira") is None

    def test_list_configs(self, db_full: SessionDatabase):
        db_full.set_external_config("proj-1", "linear", {"key": "1"})
        db_full.set_external_config("proj-1", "jira", {"key": "2"})
        configs = db_full.list_external_configs("proj-1")
        assert len(configs) == 2


# ---------------------------------------------------------------------------
# Review Tests
# ---------------------------------------------------------------------------


class TestReviews:
    """Tests for review operations."""

    def test_create_review(self, db_full: SessionDatabase):
        review = db_full.create_review(
            task_id="MYPR-T00001",
            project_id="proj-1",
            round_num=1,
            reviewer_type="self",
            verdict="pass",
            findings="All good",
        )
        assert review is not None
        assert review["verdict"] == "pass"

    def test_create_review_invalid_type(self, db_full: SessionDatabase):
        with pytest.raises(ValueError, match="Invalid reviewer_type"):
            db_full.create_review("MYPR-T00001", "proj-1", 1, "invalid", "pass")

    def test_create_review_invalid_verdict(self, db_full: SessionDatabase):
        with pytest.raises(ValueError, match="Invalid verdict"):
            db_full.create_review("MYPR-T00001", "proj-1", 1, "self", "invalid")

    def test_get_reviews_for_task(self, db_full: SessionDatabase):
        db_full.create_review("MYPR-T00001", "proj-1", 1, "self", "fail")
        db_full.create_review("MYPR-T00001", "proj-1", 2, "self", "pass")
        reviews = db_full.get_reviews_for_task("MYPR-T00001")
        assert len(reviews) == 2

    def test_get_latest_approved_review(self, db_full: SessionDatabase):
        db_full.create_review("MYPR-T00001", "proj-1", 1, "self", "fail")
        db_full.create_review("MYPR-T00001", "proj-1", 2, "self", "pass")
        approved = db_full.get_latest_approved_review("MYPR-T00001")
        assert approved is not None
        assert approved["verdict"] == "pass"

    def test_get_latest_approved_review_none(self, db_full: SessionDatabase):
        db_full.create_review("MYPR-T00001", "proj-1", 1, "self", "fail")
        assert db_full.get_latest_approved_review("MYPR-T00001") is None


# ---------------------------------------------------------------------------
# Audit Log Tests
# ---------------------------------------------------------------------------


class TestAuditLog:
    """Tests for audit log operations."""

    def test_append_audit_log(self, db_full: SessionDatabase):
        entry = db_full.append_audit_log(
            project_id="proj-1",
            action_type="task_completed",
            outcome="success",
            target_entity="MYPR-T00001",
        )
        assert entry is not None
        assert entry["action_type"] == "task_completed"

    def test_append_with_details_dict(self, db_full: SessionDatabase):
        entry = db_full.append_audit_log(
            project_id="proj-1",
            action_type="test",
            outcome="success",
            details={"key": "value"},
        )
        assert entry is not None
        assert entry["details"] is not None

    def test_get_audit_log(self, db_full: SessionDatabase):
        db_full.append_audit_log("proj-1", "action1", "success")
        db_full.append_audit_log("proj-1", "action2", "failure")
        logs = db_full.get_audit_log("proj-1")
        assert len(logs) == 2

    def test_get_audit_log_filtered(self, db_full: SessionDatabase):
        db_full.append_audit_log("proj-1", "action1", "success")
        db_full.append_audit_log("proj-1", "action2", "failure")
        logs = db_full.get_audit_log("proj-1", action_type="action1")
        assert len(logs) == 1


# ---------------------------------------------------------------------------
# Worktree Tests
# ---------------------------------------------------------------------------


class TestWorktrees:
    """Tests for worktree operations."""

    def test_create_worktree(self, db_full: SessionDatabase):
        wt = db_full.create_worktree(
            "MYPR-W0001",
            "proj-1",
            "MYPR-P0001",
            branch_name="feat/prd-1",
            path="/tmp/worktrees/prd-1",
        )
        assert wt is not None
        assert wt["id"] == "MYPR-W0001"
        assert wt["status"] == "active"

    def test_get_worktree(self, db_full: SessionDatabase):
        db_full.create_worktree("MYPR-W0001", "proj-1", "MYPR-P0001", "feat/prd-1", "/tmp/wt")
        wt = db_full.get_worktree("MYPR-W0001")
        assert wt is not None

    def test_get_worktree_by_prd(self, db_full: SessionDatabase):
        db_full.create_worktree("MYPR-W0001", "proj-1", "MYPR-P0001", "feat/prd-1", "/tmp/wt")
        wt = db_full.get_worktree_by_prd("MYPR-P0001")
        assert wt is not None

    def test_list_worktrees(self, db_full: SessionDatabase):
        db_full.create_worktree("MYPR-W0001", "proj-1", "MYPR-P0001", "feat/prd-1", "/tmp/wt1")
        wts = db_full.list_worktrees("proj-1")
        assert len(wts) == 1

    def test_update_worktree(self, db_full: SessionDatabase):
        db_full.create_worktree("MYPR-W0001", "proj-1", "MYPR-P0001", "feat/prd-1", "/tmp/wt")
        result = db_full.update_worktree("MYPR-W0001", status="completed")
        assert result is not None
        assert result["status"] == "completed"
        assert result["cleaned_at"] is not None

    def test_update_worktree_invalid_field(self, db_full: SessionDatabase):
        db_full.create_worktree("MYPR-W0001", "proj-1", "MYPR-P0001", "feat/prd-1", "/tmp/wt")
        with pytest.raises(ValueError, match="Invalid worktree fields"):
            db_full.update_worktree("MYPR-W0001", invalid_field="x")

    def test_delete_worktree(self, db_full: SessionDatabase):
        db_full.create_worktree("MYPR-W0001", "proj-1", "MYPR-P0001", "feat/prd-1", "/tmp/wt")
        assert db_full.delete_worktree("MYPR-W0001") is True
        assert db_full.get_worktree("MYPR-W0001") is None


# ---------------------------------------------------------------------------
# Integration / Cross-Entity Tests
# ---------------------------------------------------------------------------


class TestIntegration:
    """Tests for cross-entity operations and data integrity."""

    def test_prd_sprint_task_relationship(self, db_full: SessionDatabase):
        """Verify the sprint -> PRD -> task hierarchy."""
        sprint = db_full.get_sprint("MYPR-S0001")
        assert sprint["prd_count"] == 1
        assert sprint["task_counts"]["pending"] == 1

        prds = db_full.get_sprint_prds("MYPR-S0001")
        assert len(prds) == 1
        assert prds[0]["id"] == "MYPR-P0001"

    def test_dict_return_types(self, db_full: SessionDatabase):
        """All returns should be plain dicts, not SQLModel objects."""
        project = db_full.get_project("proj-1")
        assert isinstance(project, dict)

        prd = db_full.get_prd("MYPR-P0001")
        assert isinstance(prd, dict)

        task = db_full.get_task("MYPR-T00001")
        assert isinstance(task, dict)

        sprint = db_full.get_sprint("MYPR-S0001")
        assert isinstance(sprint, dict)

    def test_id_generation_sequence(self, db_with_project: SessionDatabase):
        """ID generators should produce sequential IDs."""
        prd_id1 = db_with_project.get_next_prd_id("proj-1")
        assert prd_id1 == "MYPR-P0001"

        db_with_project.create_prd(prd_id1, "proj-1", "PRD 1")
        prd_id2 = db_with_project.get_next_prd_id("proj-1")
        assert prd_id2 == "MYPR-P0002"

    def test_multiple_sessions_isolated(self, db_full: SessionDatabase):
        """Each operation uses its own session (short-lived)."""
        # Create in one session
        db_full.create_task("MYPR-T00002", "proj-1", "Task 2")
        # Read in another session
        task = db_full.get_task("MYPR-T00002")
        assert task is not None
        assert task["title"] == "Task 2"
