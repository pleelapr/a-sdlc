"""Tests for work pickup -- task claims, routing, agent messaging.

Covers P0027 entities: task_claims, agent_messages, and
the assigned_agent_id column on tasks.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from a_sdlc.core.database import SCHEMA_VERSION, Database

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db():
    """Create a temporary database instance (fresh, current schema)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=db_path)
        db.create_project("test-project", "Test Project", "/tmp/test")
        db.create_prd(
            prd_id="TEST-P0001",
            project_id="test-project",
            title="Test PRD",
            file_path="/tmp/test/prds/TEST-P0001.md",
        )
        db.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-project",
            title="Sprint 1",
            goal="Test sprint",
        )
        # Create a pending task
        db.create_task(
            task_id="TEST-T00001",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Pending Task 1",
            file_path="/tmp/test/tasks/TEST-T00001.md",
            priority="high",
        )
        # Create an agent
        db.create_agent(
            agent_id="TEST-A001",
            project_id="test-project",
            persona_type="backend-engineer",
            display_name="Backend Agent",
        )
        yield db


@pytest.fixture
def v9_db():
    """Create a database at schema version 9 (before task claims/messages)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_v9.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        conn.executescript("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT INTO schema_version (version) VALUES (9);

            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                shortname TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX idx_projects_path ON projects(path);
            CREATE UNIQUE INDEX idx_projects_shortname ON projects(shortname);

            CREATE TABLE prds (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                sprint_id TEXT,
                title TEXT NOT NULL,
                file_path TEXT,
                status TEXT DEFAULT 'draft',
                source TEXT,
                version TEXT DEFAULT '1.0.0',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ready_at TIMESTAMP,
                split_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );

            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                prd_id TEXT,
                title TEXT NOT NULL,
                file_path TEXT,
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'medium',
                component TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE SET NULL
            );

            CREATE TABLE sprints (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                goal TEXT,
                status TEXT DEFAULT 'planned',
                external_id TEXT,
                external_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE sync_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                local_id TEXT NOT NULL,
                external_system TEXT NOT NULL,
                external_id TEXT NOT NULL,
                sync_status TEXT DEFAULT 'synced',
                last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(entity_type, local_id, external_system)
            );

            CREATE TABLE designs (
                id TEXT PRIMARY KEY,
                prd_id TEXT UNIQUE NOT NULL,
                project_id TEXT NOT NULL,
                file_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE external_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                system TEXT NOT NULL,
                config JSON NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, system),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE worktrees (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                prd_id TEXT NOT NULL,
                sprint_id TEXT,
                branch_name TEXT NOT NULL,
                path TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                pr_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                cleaned_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );

            CREATE TABLE reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                round INTEGER NOT NULL DEFAULT 1,
                reviewer_type TEXT NOT NULL,
                verdict TEXT NOT NULL,
                findings TEXT,
                test_output TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            -- V9 governance tables (but without v10 task_claims, agent_messages)
            CREATE TABLE agents (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                persona_type TEXT NOT NULL,
                display_name TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                permissions_profile TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_by TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE agent_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                permission_type TEXT NOT NULL,
                permission_value TEXT NOT NULL,
                allowed INTEGER DEFAULT 1,
                UNIQUE(agent_id, permission_type, permission_value),
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            );

            CREATE TABLE agent_budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                run_id TEXT,
                token_limit INTEGER,
                token_used INTEGER DEFAULT 0,
                cost_limit_cents INTEGER,
                cost_used_cents INTEGER DEFAULT 0,
                alert_threshold_pct INTEGER DEFAULT 90,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            );

            CREATE TABLE execution_runs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                sprint_id TEXT,
                status TEXT DEFAULT 'pending',
                governance_config TEXT,
                total_budget_cents INTEGER,
                total_spent_cents INTEGER DEFAULT 0,
                agent_count INTEGER DEFAULT 0,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );

            CREATE TABLE audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                agent_id TEXT,
                run_id TEXT,
                action_type TEXT NOT NULL,
                target_entity TEXT,
                outcome TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()

        yield db_path


# =============================================================================
# Migration v9 -> v10 Tests
# =============================================================================


class TestMigrationV9ToV10:
    """Test the v9 -> v10 migration (add task claims, messages, assigned_agent_id)."""

    def test_migration_creates_task_claims_table(self, v9_db):
        """Migration from v9 should create the task_claims table."""
        db = Database(db_path=v9_db)
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='task_claims'"
            )
            assert cursor.fetchone() is not None

    def test_migration_creates_agent_messages_table(self, v9_db):
        """Migration from v9 should create the agent_messages table."""
        db = Database(db_path=v9_db)
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_messages'"
            )
            assert cursor.fetchone() is not None

    def test_migration_adds_assigned_agent_id_column(self, v9_db):
        """Migration from v9 should add assigned_agent_id to tasks."""
        db = Database(db_path=v9_db)
        with db.connection() as conn:
            cursor = conn.execute("PRAGMA table_info(tasks)")
            columns = {row[1] for row in cursor.fetchall()}
        assert "assigned_agent_id" in columns

    def test_migration_updates_version(self, v9_db):
        """Migration from v9 should chain up to current SCHEMA_VERSION."""
        db = Database(db_path=v9_db)
        with db.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_migration_idempotent(self, v9_db):
        """Opening database twice should not cause errors."""
        Database(db_path=v9_db)
        db2 = Database(db_path=v9_db)
        with db2.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == SCHEMA_VERSION


# =============================================================================
# Task Claim Tests
# =============================================================================


class TestClaimTask:
    """Test claim_task happy path and error scenarios."""

    def test_claim_task_happy_path(self, temp_db):
        """Test claiming a pending task succeeds."""
        claim = temp_db.claim_task("TEST-T00001", "TEST-A001")
        assert claim is not None
        assert claim["task_id"] == "TEST-T00001"
        assert claim["agent_id"] == "TEST-A001"
        assert claim["status"] == "active"
        # Task should be in_progress now
        task = temp_db.get_task("TEST-T00001")
        assert task["status"] == "in_progress"
        assert task["assigned_agent_id"] == "TEST-A001"

    def test_claim_task_already_claimed_raises(self, temp_db):
        """Test that claiming an already-claimed task raises ValueError.

        After the first claim, the task status becomes 'in_progress',
        so the second attempt is rejected with a 'not pending' error.
        """
        temp_db.claim_task("TEST-T00001", "TEST-A001")
        temp_db.create_agent(
            agent_id="TEST-A002",
            project_id="test-project",
            persona_type="frontend-engineer",
            display_name="Frontend Agent",
        )
        with pytest.raises(ValueError, match="not pending"):
            temp_db.claim_task("TEST-T00001", "TEST-A002")

    def test_claim_task_not_pending_raises(self, temp_db):
        """Test that claiming a non-pending task raises ValueError."""
        # Set task to in_progress manually
        temp_db.update_task("TEST-T00001", status="in_progress")
        with pytest.raises(ValueError, match="not pending"):
            temp_db.claim_task("TEST-T00001", "TEST-A001")

    def test_claim_task_not_found_raises(self, temp_db):
        """Test that claiming a nonexistent task raises ValueError."""
        with pytest.raises(ValueError, match="Task not found"):
            temp_db.claim_task("NONEXISTENT", "TEST-A001")


class TestReleaseTask:
    """Test release_task resets task to pending."""

    def test_release_task_happy_path(self, temp_db):
        """Test releasing a claimed task succeeds."""
        temp_db.claim_task("TEST-T00001", "TEST-A001")
        claim = temp_db.release_task("TEST-T00001", "TEST-A001", reason="manual")
        assert claim is not None
        assert claim["status"] == "released"
        assert claim["release_reason"] == "manual"
        # Task should be pending again
        task = temp_db.get_task("TEST-T00001")
        assert task["status"] == "pending"
        assert task["assigned_agent_id"] is None

    def test_release_task_no_active_claim(self, temp_db):
        """Test releasing a task with no active claim returns a released claim or None."""
        result = temp_db.release_task("TEST-T00001", "TEST-A001")
        # No active claim to release; method returns the latest claim or None
        # Either None or a released-status row is acceptable
        if result is not None:
            assert result["status"] != "active"


class TestGetActiveClaim:
    """Test get_active_claim returns active claim or None."""

    def test_active_claim_exists(self, temp_db):
        """Test that get_active_claim returns the active claim."""
        temp_db.claim_task("TEST-T00001", "TEST-A001")
        claim = temp_db.get_active_claim("TEST-T00001")
        assert claim is not None
        assert claim["task_id"] == "TEST-T00001"
        assert claim["status"] == "active"

    def test_no_active_claim(self, temp_db):
        """Test that get_active_claim returns None when no claim exists."""
        claim = temp_db.get_active_claim("TEST-T00001")
        assert claim is None

    def test_released_claim_not_active(self, temp_db):
        """Test that a released claim is not returned by get_active_claim."""
        temp_db.claim_task("TEST-T00001", "TEST-A001")
        temp_db.release_task("TEST-T00001", "TEST-A001")
        claim = temp_db.get_active_claim("TEST-T00001")
        assert claim is None


class TestListClaimsByAgent:
    """Test list_claims_by_agent returns claim history."""

    def test_returns_all_claims_for_agent(self, temp_db):
        """Test that all claims (active and released) are returned."""
        # Create a second task
        temp_db.create_task(
            task_id="TEST-T00002",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Pending Task 2",
        )
        temp_db.claim_task("TEST-T00001", "TEST-A001")
        temp_db.release_task("TEST-T00001", "TEST-A001")
        temp_db.claim_task("TEST-T00002", "TEST-A001")
        claims = temp_db.list_claims_by_agent("TEST-A001")
        assert len(claims) == 2

    def test_returns_empty_for_no_claims(self, temp_db):
        """Test that an empty list is returned when no claims exist."""
        claims = temp_db.list_claims_by_agent("TEST-A001")
        assert claims == []


class TestDetectStaleClaims:
    """Test detect_stale_claims finds old active claims."""

    def test_no_stale_claims(self, temp_db):
        """Test that new claims are not detected as stale."""
        temp_db.claim_task("TEST-T00001", "TEST-A001")
        stale = temp_db.detect_stale_claims(timeout_minutes=30)
        assert len(stale) == 0

    def test_stale_claim_detected(self, temp_db):
        """Test that an old active claim is detected by backdating claimed_at."""
        temp_db.claim_task("TEST-T00001", "TEST-A001")
        # Manually backdate the claim for a reliable test
        with temp_db.connection() as conn:
            conn.execute(
                "UPDATE task_claims SET claimed_at = datetime('now', '-60 minutes') "
                "WHERE task_id = 'TEST-T00001' AND status = 'active'"
            )
        stale = temp_db.detect_stale_claims(timeout_minutes=30)
        assert len(stale) == 1
        assert stale[0]["task_id"] == "TEST-T00001"


class TestGetAvailableWork:
    """Test get_available_work returns unclaimed pending tasks sorted by priority."""

    def test_returns_pending_unclaimed_tasks(self, temp_db):
        """Test that available work includes pending unclaimed tasks."""
        tasks = temp_db.get_available_work("test-project", "TEST-A001")
        assert len(tasks) == 1
        assert tasks[0]["id"] == "TEST-T00001"

    def test_excludes_claimed_tasks(self, temp_db):
        """Test that claimed tasks are excluded from available work."""
        temp_db.claim_task("TEST-T00001", "TEST-A001")
        tasks = temp_db.get_available_work("test-project", "TEST-A001")
        assert len(tasks) == 0

    def test_sorted_by_priority(self, temp_db):
        """Test that available tasks are sorted by priority (critical first)."""
        temp_db.create_task(
            task_id="TEST-T00002",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Low Priority",
            priority="low",
        )
        temp_db.create_task(
            task_id="TEST-T00003",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Critical Priority",
            priority="critical",
        )
        tasks = temp_db.get_available_work("test-project", "TEST-A001")
        priorities = [t["priority"] for t in tasks]
        assert priorities[0] == "critical"
        assert priorities[-1] == "low"

    def test_agent_not_found_raises(self, temp_db):
        """Test that a nonexistent agent raises ValueError."""
        with pytest.raises(ValueError, match="Agent not found"):
            temp_db.get_available_work("test-project", "NONEXISTENT")

    def test_sprint_filter(self, temp_db):
        """Test filtering available work by sprint (via PRD relationship)."""
        # Assign PRD to sprint
        temp_db.update_prd("TEST-P0001", sprint_id="TEST-S0001")
        tasks = temp_db.get_available_work(
            "test-project", "TEST-A001", sprint_id="TEST-S0001"
        )
        assert len(tasks) == 1

    def test_sprint_filter_excludes_other_sprints(self, temp_db):
        """Test that sprint filter excludes tasks from other sprints."""
        temp_db.create_sprint(
            sprint_id="TEST-S0002",
            project_id="test-project",
            title="Sprint 2",
            goal="Other sprint",
        )
        temp_db.update_prd("TEST-P0001", sprint_id="TEST-S0002")
        tasks = temp_db.get_available_work(
            "test-project", "TEST-A001", sprint_id="TEST-S0001"
        )
        assert len(tasks) == 0


# =============================================================================
# Concurrent Claim Simulation
# =============================================================================


class TestConcurrentClaimSimulation:
    """Simulate concurrent claim attempts using unique index constraint."""

    def test_unique_active_claim_constraint_via_direct_insert(self, temp_db):
        """Test that the unique partial index prevents duplicate active claims.

        Bypasses the Python-level status check by inserting directly into
        task_claims to verify the database-level constraint.
        """
        temp_db.claim_task("TEST-T00001", "TEST-A001")
        temp_db.create_agent(
            agent_id="TEST-A002",
            project_id="test-project",
            persona_type="frontend-engineer",
            display_name="Frontend Agent",
        )
        # Direct SQL insert to bypass Python status check and test the DB constraint
        with pytest.raises(sqlite3.IntegrityError), temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO task_claims (task_id, agent_id, status) "
                "VALUES (?, ?, 'active')",
                ("TEST-T00001", "TEST-A002"),
            )


# =============================================================================
# Agent Message Tests
# =============================================================================


class TestSendAgentMessage:
    """Test send_agent_message operations."""

    def test_send_message_basic(self, temp_db):
        """Test sending a basic message between agents."""
        temp_db.create_agent(
            agent_id="TEST-A002",
            project_id="test-project",
            persona_type="qa-engineer",
            display_name="QA Agent",
        )
        msg = temp_db.send_agent_message(
            from_agent_id="TEST-A001",
            to_agent_id="TEST-A002",
            message_type="handoff",
            content="Task complete, please review.",
        )
        assert msg is not None
        assert msg["from_agent_id"] == "TEST-A001"
        assert msg["to_agent_id"] == "TEST-A002"
        assert msg["message_type"] == "handoff"
        assert msg["content"] == "Task complete, please review."
        assert msg["read_at"] is None

    def test_send_message_with_related_task(self, temp_db):
        """Test sending a message related to a task."""
        temp_db.create_agent(
            agent_id="TEST-A002",
            project_id="test-project",
            persona_type="qa-engineer",
            display_name="QA Agent",
        )
        msg = temp_db.send_agent_message(
            from_agent_id="TEST-A001",
            to_agent_id="TEST-A002",
            message_type="blocker",
            content="Blocked on dependency.",
            related_task_id="TEST-T00001",
        )
        assert msg["related_task_id"] == "TEST-T00001"


class TestGetAgentMessages:
    """Test get_agent_messages operations."""

    def _setup_messages(self, db):
        """Helper: create agents and send messages."""
        db.create_agent(
            agent_id="TEST-A002",
            project_id="test-project",
            persona_type="qa-engineer",
            display_name="QA Agent",
        )
        db.send_agent_message("TEST-A001", "TEST-A002", "handoff", "msg 1")
        db.send_agent_message("TEST-A001", "TEST-A002", "question", "msg 2")
        db.send_agent_message("TEST-A002", "TEST-A001", "response", "msg 3")

    def test_get_messages_for_recipient(self, temp_db):
        """Test getting messages for a specific recipient."""
        self._setup_messages(temp_db)
        messages = temp_db.get_agent_messages("TEST-A002")
        assert len(messages) == 2
        for msg in messages:
            assert msg["to_agent_id"] == "TEST-A002"

    def test_get_messages_unread_only(self, temp_db):
        """Test filtering unread-only messages."""
        self._setup_messages(temp_db)
        # Mark one as read
        messages = temp_db.get_agent_messages("TEST-A002")
        temp_db.mark_message_read(messages[0]["id"])
        unread = temp_db.get_agent_messages("TEST-A002", unread_only=True)
        assert len(unread) == 1

    def test_get_messages_empty(self, temp_db):
        """Test getting messages when none exist."""
        messages = temp_db.get_agent_messages("TEST-A001")
        assert messages == []


class TestMarkMessageRead:
    """Test mark_message_read operations."""

    def test_mark_read(self, temp_db):
        """Test marking a message as read sets read_at."""
        temp_db.create_agent(
            agent_id="TEST-A002",
            project_id="test-project",
            persona_type="qa-engineer",
            display_name="QA Agent",
        )
        msg = temp_db.send_agent_message(
            "TEST-A001", "TEST-A002", "handoff", "test"
        )
        assert msg["read_at"] is None
        updated = temp_db.mark_message_read(msg["id"])
        assert updated is not None
        assert updated["read_at"] is not None

    def test_mark_read_not_found(self, temp_db):
        """Test marking a nonexistent message returns None."""
        result = temp_db.mark_message_read(99999)
        assert result is None
