"""Tests for agent governance tables -- database migration and CRUD operations.

Covers P0026 entities: agents, agent_permissions, agent_budgets,
execution_runs, and audit_log.
"""

import json
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
        db.create_task(
            task_id="TEST-T00001",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Test Task",
            file_path="/tmp/test/tasks/TEST-T00001.md",
        )
        yield db


@pytest.fixture
def v8_db():
    """Create a database at schema version 8 (before governance tables)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_v8.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        # Minimal v8 schema: schema_version + tables that existed before v9
        conn.executescript("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT INTO schema_version (version) VALUES (8);

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
        """)
        conn.commit()
        conn.close()

        yield db_path


def _create_agent(db, agent_id="TEST-A001", status="active"):
    """Helper: create an agent in the test project."""
    return db.create_agent(
        agent_id=agent_id,
        project_id="test-project",
        persona_type="backend-engineer",
        display_name="Test Agent",
        status=status,
    )


# =============================================================================
# Schema Version Tests
# =============================================================================


class TestSchemaVersion:
    """Test that the schema version is at the expected value."""

    def test_schema_version_constant(self):
        """SCHEMA_VERSION constant should be at least 9 (governance tables)."""
        assert SCHEMA_VERSION >= 9

    def test_fresh_db_has_current_version(self, temp_db):
        """A fresh database should have the current SCHEMA_VERSION."""
        with temp_db.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_fresh_db_has_agents_table(self, temp_db):
        """A fresh database should have the agents table."""
        with temp_db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agents'"
            )
            assert cursor.fetchone() is not None

    def test_fresh_db_has_all_governance_tables(self, temp_db):
        """A fresh database should have all 5 governance tables."""
        expected_tables = {
            "agents", "agent_permissions", "agent_budgets",
            "execution_runs", "audit_log",
        }
        with temp_db.connection() as conn:
            for table in expected_tables:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                assert cursor.fetchone() is not None, f"Table {table} not found"


# =============================================================================
# Migration v8 -> v9 Tests
# =============================================================================


class TestMigrationV8ToV9:
    """Test the v8 -> v9 migration (add governance tables)."""

    def test_migration_creates_five_governance_tables(self, v8_db):
        """Migration from v8 should create 5 governance tables."""
        db = Database(db_path=v8_db)
        expected_tables = {
            "agents", "agent_permissions", "agent_budgets",
            "execution_runs", "audit_log",
        }
        with db.connection() as conn:
            for table in expected_tables:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                assert cursor.fetchone() is not None, f"Table {table} not found"

    def test_migration_updates_version(self, v8_db):
        """Migration from v8 should chain up to current SCHEMA_VERSION."""
        db = Database(db_path=v8_db)
        with db.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_migration_agents_table_columns(self, v8_db):
        """Migration should create agents table with correct columns."""
        db = Database(db_path=v8_db)
        with db.connection() as conn:
            cursor = conn.execute("PRAGMA table_info(agents)")
            actual_columns = {row[1] for row in cursor.fetchall()}
        # Should include v9 base columns + v11 added columns
        required_columns = {
            "id", "project_id", "persona_type", "display_name",
            "status", "permissions_profile", "created_at", "approved_by",
        }
        assert required_columns.issubset(actual_columns)

    def test_migration_preserves_existing_data(self, v8_db):
        """Migration should preserve existing project data."""
        conn = sqlite3.connect(v8_db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO projects (id, shortname, name, path) VALUES (?, ?, ?, ?)",
            ("proj-1", "PROJ", "Project One", "/tmp/proj1"),
        )
        conn.commit()
        conn.close()

        db = Database(db_path=v8_db)
        project = db.get_project("proj-1")
        assert project is not None
        assert project["shortname"] == "PROJ"

    def test_migration_idempotent(self, v8_db):
        """Opening database twice should not cause errors."""
        Database(db_path=v8_db)
        db2 = Database(db_path=v8_db)
        with db2.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_migration_creates_indexes(self, v8_db):
        """Migration should create expected indexes on agents table."""
        db = Database(db_path=v8_db)
        expected_indexes = {
            "idx_agents_project",
            "idx_agents_status",
            "idx_agents_persona",
        }
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='agents'"
            )
            actual_indexes = {row[0] for row in cursor.fetchall()}
        assert expected_indexes.issubset(actual_indexes)


# =============================================================================
# Agent CRUD Tests
# =============================================================================


class TestAgentCRUD:
    """Test agent create, get, list, update, delete operations."""

    def test_create_agent_basic(self, temp_db):
        """Test creating an agent with required fields."""
        agent = temp_db.create_agent(
            agent_id="TEST-A001",
            project_id="test-project",
            persona_type="backend-engineer",
            display_name="Backend Agent",
        )
        assert agent is not None
        assert agent["id"] == "TEST-A001"
        assert agent["project_id"] == "test-project"
        assert agent["persona_type"] == "backend-engineer"
        assert agent["display_name"] == "Backend Agent"
        assert agent["status"] == "active"
        assert agent["created_at"] is not None

    def test_create_agent_with_optional_fields(self, temp_db):
        """Test creating an agent with optional fields."""
        agent = temp_db.create_agent(
            agent_id="TEST-A002",
            project_id="test-project",
            persona_type="qa-engineer",
            display_name="QA Agent",
            status="proposed",
            permissions_profile="readonly",
            approved_by="human",
        )
        assert agent["status"] == "proposed"
        assert agent["permissions_profile"] == "readonly"
        assert agent["approved_by"] == "human"

    def test_get_agent(self, temp_db):
        """Test retrieving an agent by ID."""
        _create_agent(temp_db)
        agent = temp_db.get_agent("TEST-A001")
        assert agent is not None
        assert agent["id"] == "TEST-A001"

    def test_get_agent_not_found(self, temp_db):
        """Test retrieving a nonexistent agent returns None."""
        agent = temp_db.get_agent("NONEXISTENT")
        assert agent is None

    def test_list_agents_all(self, temp_db):
        """Test listing all agents for a project."""
        _create_agent(temp_db, "TEST-A001")
        _create_agent(temp_db, "TEST-A002")
        agents = temp_db.list_agents("test-project")
        assert len(agents) == 2

    def test_list_agents_empty(self, temp_db):
        """Test listing agents when none exist."""
        agents = temp_db.list_agents("test-project")
        assert agents == []

    def test_list_agents_status_filter(self, temp_db):
        """Test listing agents filtered by status."""
        _create_agent(temp_db, "TEST-A001", status="active")
        _create_agent(temp_db, "TEST-A002", status="suspended")
        active = temp_db.list_agents("test-project", status="active")
        assert len(active) == 1
        assert active[0]["id"] == "TEST-A001"

    def test_update_agent_fields(self, temp_db):
        """Test updating agent fields dynamically."""
        _create_agent(temp_db)
        updated = temp_db.update_agent("TEST-A001", display_name="Renamed Agent")
        assert updated is not None
        assert updated["display_name"] == "Renamed Agent"

    def test_update_agent_no_kwargs(self, temp_db):
        """Test update_agent with no kwargs returns current agent."""
        _create_agent(temp_db)
        result = temp_db.update_agent("TEST-A001")
        assert result is not None
        assert result["id"] == "TEST-A001"

    def test_update_agent_status(self, temp_db):
        """Test updating agent status."""
        _create_agent(temp_db)
        updated = temp_db.update_agent_status("TEST-A001", "suspended")
        assert updated is not None
        assert updated["status"] == "suspended"

    def test_update_agent_status_not_found(self, temp_db):
        """Test updating status of nonexistent agent returns None."""
        result = temp_db.update_agent_status("NONEXISTENT", "active")
        assert result is None

    def test_delete_agent_soft_deletes(self, temp_db):
        """Test that delete_agent soft-deletes by setting status to retired."""
        _create_agent(temp_db)
        result = temp_db.delete_agent("TEST-A001")
        assert result is True
        agent = temp_db.get_agent("TEST-A001")
        assert agent is not None
        assert agent["status"] == "retired"

    def test_delete_agent_not_found(self, temp_db):
        """Test deleting a nonexistent agent returns False."""
        result = temp_db.delete_agent("NONEXISTENT")
        assert result is False

    def test_agent_id_format(self, temp_db):
        """Test that generated agent IDs follow the {SHORTNAME}-A{NNN} format."""
        agent_id = temp_db.get_next_agent_id("test-project")
        project = temp_db.get_project("test-project")
        shortname = project["shortname"]
        assert agent_id.startswith(f"{shortname}-A")
        # The number part should be zero-padded to 3 digits
        number_part = agent_id.split("-A")[1]
        assert len(number_part) == 3
        assert number_part.isdigit()


# =============================================================================
# Permission CRUD Tests
# =============================================================================


class TestPermissionCRUD:
    """Test permission set, check, and list operations."""

    def test_set_permission(self, temp_db):
        """Test setting a permission for an agent."""
        _create_agent(temp_db)
        perm = temp_db.set_agent_permission(
            "TEST-A001", "tool", "git_push", allowed=1
        )
        assert perm is not None
        assert perm["agent_id"] == "TEST-A001"
        assert perm["permission_type"] == "tool"
        assert perm["permission_value"] == "git_push"
        assert perm["allowed"] == 1

    def test_check_permission_allowed(self, temp_db):
        """Test that check_agent_permission returns True when allowed."""
        _create_agent(temp_db)
        temp_db.set_agent_permission("TEST-A001", "tool", "git_push", allowed=1)
        result = temp_db.check_agent_permission("TEST-A001", "tool", "git_push")
        assert result is True

    def test_check_permission_denied(self, temp_db):
        """Test that check_agent_permission returns False when denied."""
        _create_agent(temp_db)
        temp_db.set_agent_permission("TEST-A001", "tool", "git_push", allowed=0)
        result = temp_db.check_agent_permission("TEST-A001", "tool", "git_push")
        assert result is False

    def test_check_permission_default_deny(self, temp_db):
        """Test that unset permission returns False (default-deny)."""
        _create_agent(temp_db)
        result = temp_db.check_agent_permission("TEST-A001", "tool", "deploy")
        assert result is False

    def test_get_permissions(self, temp_db):
        """Test getting all permissions for an agent."""
        _create_agent(temp_db)
        temp_db.set_agent_permission("TEST-A001", "tool", "git_push", allowed=1)
        temp_db.set_agent_permission("TEST-A001", "file_path", "/src/", allowed=1)
        perms = temp_db.get_agent_permissions("TEST-A001")
        assert len(perms) == 2

    def test_set_permission_upsert(self, temp_db):
        """Test that set_agent_permission upserts on duplicate."""
        _create_agent(temp_db)
        temp_db.set_agent_permission("TEST-A001", "tool", "git_push", allowed=1)
        temp_db.set_agent_permission("TEST-A001", "tool", "git_push", allowed=0)
        result = temp_db.check_agent_permission("TEST-A001", "tool", "git_push")
        assert result is False
        # Should still be just 1 row, not 2
        perms = temp_db.get_agent_permissions("TEST-A001")
        tool_perms = [p for p in perms if p["permission_value"] == "git_push"]
        assert len(tool_perms) == 1


# =============================================================================
# Budget CRUD Tests
# =============================================================================


class TestBudgetCRUD:
    """Test budget create, get, and update operations."""

    def test_create_budget(self, temp_db):
        """Test creating a budget for an agent."""
        _create_agent(temp_db)
        budget = temp_db.create_agent_budget(
            agent_id="TEST-A001",
            token_limit=100000,
            cost_limit_cents=500,
        )
        assert budget is not None
        assert budget["agent_id"] == "TEST-A001"
        assert budget["token_limit"] == 100000
        assert budget["cost_limit_cents"] == 500
        assert budget["token_used"] == 0
        assert budget["cost_used_cents"] == 0
        assert budget["alert_threshold_pct"] == 90

    def test_create_budget_with_run_id(self, temp_db):
        """Test creating a budget scoped to a run."""
        _create_agent(temp_db)
        budget = temp_db.create_agent_budget(
            agent_id="TEST-A001",
            run_id="TEST-R001",
            token_limit=50000,
            cost_limit_cents=250,
        )
        assert budget["run_id"] == "TEST-R001"

    def test_get_budget_most_recent(self, temp_db):
        """Test that get_agent_budget without run_id returns most recent."""
        _create_agent(temp_db)
        temp_db.create_agent_budget("TEST-A001", token_limit=10000)
        budget2 = temp_db.create_agent_budget("TEST-A001", token_limit=20000)
        result = temp_db.get_agent_budget("TEST-A001")
        assert result is not None
        assert result["id"] == budget2["id"]
        assert result["token_limit"] == 20000

    def test_get_budget_by_run_id(self, temp_db):
        """Test getting a budget filtered by run_id."""
        _create_agent(temp_db)
        temp_db.create_agent_budget("TEST-A001", run_id="run-1", token_limit=10000)
        temp_db.create_agent_budget("TEST-A001", run_id="run-2", token_limit=20000)
        result = temp_db.get_agent_budget("TEST-A001", run_id="run-1")
        assert result is not None
        assert result["token_limit"] == 10000

    def test_get_budget_not_found(self, temp_db):
        """Test that missing budget returns None."""
        _create_agent(temp_db)
        result = temp_db.get_agent_budget("TEST-A001")
        assert result is None

    def test_update_budget_delta(self, temp_db):
        """Test updating budget with delta values."""
        _create_agent(temp_db)
        budget = temp_db.create_agent_budget(
            "TEST-A001", token_limit=100000, cost_limit_cents=500
        )
        updated = temp_db.update_agent_budget(
            budget["id"], token_used_delta=5000, cost_used_delta=25
        )
        assert updated is not None
        assert updated["token_used"] == 5000
        assert updated["cost_used_cents"] == 25

    def test_update_budget_not_found(self, temp_db):
        """Test updating a nonexistent budget returns None."""
        result = temp_db.update_agent_budget(9999, token_used_delta=100)
        assert result is None

    def test_update_budget_cumulative_delta(self, temp_db):
        """Test that multiple delta updates accumulate correctly."""
        _create_agent(temp_db)
        budget = temp_db.create_agent_budget(
            "TEST-A001", token_limit=100000, cost_limit_cents=500
        )
        temp_db.update_agent_budget(budget["id"], token_used_delta=1000)
        updated = temp_db.update_agent_budget(budget["id"], token_used_delta=2000)
        assert updated["token_used"] == 3000


# =============================================================================
# Execution Run CRUD Tests
# =============================================================================


class TestExecutionRunCRUD:
    """Test execution run create, get, and update operations."""

    def test_create_run(self, temp_db):
        """Test creating an execution run."""
        run = temp_db.create_execution_run(
            run_id="TEST-R001",
            project_id="test-project",
            sprint_id="TEST-S0001",
            total_budget_cents=1000,
            agent_count=3,
        )
        assert run is not None
        assert run["id"] == "TEST-R001"
        assert run["project_id"] == "test-project"
        assert run["sprint_id"] == "TEST-S0001"
        assert run["status"] == "pending"
        assert run["total_budget_cents"] == 1000
        assert run["total_spent_cents"] == 0
        assert run["agent_count"] == 3

    def test_get_run(self, temp_db):
        """Test retrieving an execution run by ID."""
        temp_db.create_execution_run("TEST-R001", "test-project")
        run = temp_db.get_execution_run("TEST-R001")
        assert run is not None
        assert run["id"] == "TEST-R001"

    def test_get_run_not_found(self, temp_db):
        """Test retrieving a nonexistent run returns None."""
        result = temp_db.get_execution_run("NONEXISTENT")
        assert result is None

    def test_update_run(self, temp_db):
        """Test updating execution run fields."""
        temp_db.create_execution_run("TEST-R001", "test-project")
        updated = temp_db.update_execution_run(
            "TEST-R001", status="running", agent_count=5
        )
        assert updated is not None
        assert updated["status"] == "running"
        assert updated["agent_count"] == 5

    def test_update_run_not_found(self, temp_db):
        """Test updating a nonexistent run returns None."""
        result = temp_db.update_execution_run("NONEXISTENT", status="running")
        assert result is None

    def test_update_run_no_kwargs(self, temp_db):
        """Test update_execution_run with no kwargs returns current run."""
        temp_db.create_execution_run("TEST-R001", "test-project")
        result = temp_db.update_execution_run("TEST-R001")
        assert result is not None
        assert result["id"] == "TEST-R001"

    def test_run_id_format(self, temp_db):
        """Test that generated run IDs follow the {SHORTNAME}-R{NNN} format."""
        run_id = temp_db.get_next_run_id("test-project")
        project = temp_db.get_project("test-project")
        shortname = project["shortname"]
        assert run_id.startswith(f"{shortname}-R")
        number_part = run_id.split("-R")[1]
        assert len(number_part) == 3
        assert number_part.isdigit()


# =============================================================================
# Audit Log Tests
# =============================================================================


class TestAuditLog:
    """Test audit log append and get operations."""

    def test_append_audit_log_basic(self, temp_db):
        """Test appending a basic audit log entry."""
        entry = temp_db.append_audit_log(
            project_id="test-project",
            action_type="task_completed",
            outcome="success",
        )
        assert entry is not None
        assert entry["project_id"] == "test-project"
        assert entry["action_type"] == "task_completed"
        assert entry["outcome"] == "success"
        assert entry["created_at"] is not None

    def test_append_audit_log_with_all_fields(self, temp_db):
        """Test appending an audit log entry with all optional fields."""
        _create_agent(temp_db)
        entry = temp_db.append_audit_log(
            project_id="test-project",
            action_type="permission_denied",
            outcome="denied",
            agent_id="TEST-A001",
            run_id="TEST-R001",
            target_entity="TEST-T00001",
            details={"reason": "no permission for git_push"},
        )
        assert entry["agent_id"] == "TEST-A001"
        assert entry["run_id"] == "TEST-R001"
        assert entry["target_entity"] == "TEST-T00001"
        parsed = json.loads(entry["details"])
        assert parsed["reason"] == "no permission for git_push"

    def test_append_audit_log_string_details(self, temp_db):
        """Test appending audit log with string details."""
        entry = temp_db.append_audit_log(
            project_id="test-project",
            action_type="test",
            outcome="success",
            details="plain string details",
        )
        assert entry["details"] == "plain string details"

    def test_get_audit_log_all(self, temp_db):
        """Test getting all audit log entries for a project."""
        for i in range(3):
            temp_db.append_audit_log(
                "test-project", f"action_{i}", "success"
            )
        logs = temp_db.get_audit_log("test-project")
        assert len(logs) == 3

    def test_get_audit_log_empty(self, temp_db):
        """Test getting audit log when no entries exist."""
        logs = temp_db.get_audit_log("test-project")
        assert logs == []

    def test_get_audit_log_filter_agent(self, temp_db):
        """Test filtering audit log by agent_id."""
        _create_agent(temp_db)
        _create_agent(temp_db, "TEST-A002")
        temp_db.append_audit_log(
            "test-project", "action", "success", agent_id="TEST-A001"
        )
        temp_db.append_audit_log(
            "test-project", "action", "success", agent_id="TEST-A002"
        )
        logs = temp_db.get_audit_log("test-project", agent_id="TEST-A001")
        assert len(logs) == 1
        assert logs[0]["agent_id"] == "TEST-A001"

    def test_get_audit_log_filter_action_type(self, temp_db):
        """Test filtering audit log by action_type."""
        temp_db.append_audit_log("test-project", "create", "success")
        temp_db.append_audit_log("test-project", "delete", "success")
        logs = temp_db.get_audit_log("test-project", action_type="create")
        assert len(logs) == 1
        assert logs[0]["action_type"] == "create"

    def test_get_audit_log_limit(self, temp_db):
        """Test that audit log respects the limit parameter."""
        for _i in range(10):
            temp_db.append_audit_log("test-project", "action", "success")
        logs = temp_db.get_audit_log("test-project", limit=3)
        assert len(logs) == 3

    def test_get_audit_log_ordered_desc(self, temp_db):
        """Test that audit log entries are ordered by created_at descending."""
        temp_db.append_audit_log("test-project", "first", "success")
        temp_db.append_audit_log("test-project", "second", "success")
        logs = temp_db.get_audit_log("test-project")
        # Most recent should be first
        assert logs[0]["action_type"] == "second"
