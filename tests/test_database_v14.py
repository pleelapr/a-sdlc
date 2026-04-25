"""Tests for v14 database migration -- work_queue, artifact_threads, execution_runs extensions."""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from a_sdlc.core.database import SCHEMA_VERSION, Database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
        # Create agent for FK testing
        with db.connection() as conn:
            conn.execute(
                "INSERT INTO agents (id, project_id, persona_type, display_name) "
                "VALUES (?, ?, ?, ?)",
                ("agent-001", "test-project", "implementer", "Test Agent"),
            )
        # Create execution run for FK testing
        db.create_execution_run(
            run_id="run-001",
            project_id="test-project",
            sprint_id="TEST-S0001",
        )
        yield db


@pytest.fixture
def v13_db():
    """Create a database at schema version 13 (before work_queue/artifact_threads)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_v13.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # Build the complete v13 schema manually
        conn.executescript("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT INTO schema_version (version) VALUES (13);

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
            CREATE INDEX idx_prds_project ON prds(project_id);
            CREATE INDEX idx_prds_status ON prds(status);
            CREATE INDEX idx_prds_sprint ON prds(sprint_id);

            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                prd_id TEXT,
                title TEXT NOT NULL,
                file_path TEXT,
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'medium',
                component TEXT,
                assigned_agent_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE SET NULL,
                FOREIGN KEY (assigned_agent_id) REFERENCES agents(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_tasks_project ON tasks(project_id);
            CREATE INDEX idx_tasks_status ON tasks(status);
            CREATE INDEX idx_tasks_prd ON tasks(prd_id);
            CREATE INDEX idx_tasks_assigned_agent ON tasks(assigned_agent_id);

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
            CREATE INDEX idx_sprints_project ON sprints(project_id);
            CREATE INDEX idx_sprints_status ON sprints(status);

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
            CREATE INDEX idx_sync_entity ON sync_mappings(entity_type, local_id);
            CREATE INDEX idx_sync_external ON sync_mappings(external_system, external_id);

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
            CREATE INDEX idx_designs_prd ON designs(prd_id);
            CREATE INDEX idx_designs_project ON designs(project_id);

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
            CREATE INDEX idx_external_config_project ON external_config(project_id);

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
            CREATE INDEX idx_worktrees_project ON worktrees(project_id);
            CREATE INDEX idx_worktrees_prd ON worktrees(prd_id);
            CREATE INDEX idx_worktrees_sprint ON worktrees(sprint_id);
            CREATE INDEX idx_worktrees_status ON worktrees(status);

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
            CREATE INDEX idx_reviews_task ON reviews(task_id);
            CREATE INDEX idx_reviews_project ON reviews(project_id);

            CREATE TABLE agents (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                persona_type TEXT NOT NULL,
                display_name TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                permissions_profile TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_by TEXT,
                team_id TEXT,
                reports_to_agent_id TEXT,
                hired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                suspended_at TIMESTAMP,
                retired_at TIMESTAMP,
                performance_score REAL DEFAULT 50.0,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_agents_project ON agents(project_id);
            CREATE INDEX idx_agents_status ON agents(status);
            CREATE INDEX idx_agents_persona ON agents(persona_type);

            CREATE TABLE agent_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                permission_type TEXT NOT NULL,
                permission_value TEXT NOT NULL,
                allowed INTEGER DEFAULT 1,
                UNIQUE(agent_id, permission_type, permission_value),
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_agent_perms_agent ON agent_permissions(agent_id);

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
            CREATE INDEX idx_agent_budgets_agent ON agent_budgets(agent_id);
            CREATE INDEX idx_agent_budgets_run ON agent_budgets(run_id);

            -- v13 execution_runs: NO run_type, goal, current_phase, config,
            -- clarification_question, clarification_answer columns
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
            CREATE INDEX idx_execution_runs_project ON execution_runs(project_id);
            CREATE INDEX idx_execution_runs_sprint ON execution_runs(sprint_id);
            CREATE INDEX idx_execution_runs_status ON execution_runs(status);

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
            CREATE INDEX idx_audit_log_project ON audit_log(project_id);
            CREATE INDEX idx_audit_log_agent ON audit_log(agent_id);
            CREATE INDEX idx_audit_log_run ON audit_log(run_id);
            CREATE INDEX idx_audit_log_action ON audit_log(action_type);

            CREATE TABLE task_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                released_at TIMESTAMP,
                status TEXT DEFAULT 'active',
                release_reason TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_task_claims_task ON task_claims(task_id);
            CREATE INDEX idx_task_claims_agent ON task_claims(agent_id);
            CREATE INDEX idx_task_claims_status ON task_claims(status);
            CREATE UNIQUE INDEX idx_task_claims_active ON task_claims(task_id) WHERE status = 'active';

            CREATE TABLE agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_agent_id TEXT NOT NULL,
                to_agent_id TEXT NOT NULL,
                message_type TEXT NOT NULL,
                content TEXT NOT NULL,
                related_task_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                read_at TIMESTAMP,
                FOREIGN KEY (from_agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                FOREIGN KEY (to_agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                FOREIGN KEY (related_task_id) REFERENCES tasks(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_agent_messages_to ON agent_messages(to_agent_id);
            CREATE INDEX idx_agent_messages_from ON agent_messages(from_agent_id);
            CREATE INDEX idx_agent_messages_task ON agent_messages(related_task_id);

            CREATE TABLE agent_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                sprint_id TEXT,
                tasks_completed INTEGER DEFAULT 0,
                tasks_failed INTEGER DEFAULT 0,
                avg_quality_score REAL,
                avg_completion_time_min REAL,
                corrections_count INTEGER DEFAULT 0,
                review_pass_rate REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agent_id, sprint_id),
                FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_agent_perf_agent ON agent_performance(agent_id);
            CREATE INDEX idx_agent_perf_sprint ON agent_performance(sprint_id);

            CREATE TABLE agent_teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                project_id TEXT NOT NULL,
                lead_agent_id TEXT,
                sprint_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (lead_agent_id) REFERENCES agents(id) ON DELETE SET NULL,
                FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
            );
            CREATE INDEX idx_agent_teams_project ON agent_teams(project_id);
            CREATE INDEX idx_agent_teams_lead ON agent_teams(lead_agent_id);
            CREATE INDEX idx_agent_teams_sprint ON agent_teams(sprint_id);

            CREATE TABLE requirements (
                id TEXT PRIMARY KEY,
                prd_id TEXT NOT NULL,
                req_type TEXT NOT NULL,
                req_number TEXT NOT NULL,
                summary TEXT NOT NULL,
                depth TEXT DEFAULT 'structural',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(prd_id, req_number),
                FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_requirements_prd ON requirements(prd_id);
            CREATE INDEX idx_requirements_type ON requirements(req_type);

            CREATE TABLE requirement_links (
                requirement_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (requirement_id, task_id),
                FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE ac_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requirement_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                verified_by TEXT,
                evidence_type TEXT,
                evidence TEXT,
                verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(requirement_id, task_id),
                FOREIGN KEY (requirement_id) REFERENCES requirements(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );
            CREATE INDEX idx_ac_verifications_task ON ac_verifications(task_id);

            CREATE TABLE challenge_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artifact_type TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                round_number INTEGER NOT NULL,
                objections TEXT,
                responses TEXT,
                verdict TEXT,
                challenger_context TEXT,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(artifact_type, artifact_id, round_number)
            );
            CREATE INDEX idx_challenge_artifact ON challenge_records(artifact_type, artifact_id);
        """)
        # Seed test data
        conn.execute(
            "INSERT INTO projects (id, shortname, name, path) VALUES (?, ?, ?, ?)",
            ("proj-1", "PROJ", "Project One", "/tmp/proj1"),
        )
        conn.execute(
            "INSERT INTO sprints (id, project_id, title) VALUES (?, ?, ?)",
            ("PROJ-S0001", "proj-1", "Sprint 1"),
        )
        conn.execute(
            "INSERT INTO execution_runs (id, project_id, sprint_id, status) "
            "VALUES (?, ?, ?, ?)",
            ("run-existing", "proj-1", "PROJ-S0001", "completed"),
        )
        conn.commit()
        conn.close()
        yield db_path


# ---------------------------------------------------------------------------
# TestSchemaV14Version
# ---------------------------------------------------------------------------


class TestSchemaV14Version:
    """Basic version checks for v14 schema."""

    def test_schema_version_constant(self):
        assert SCHEMA_VERSION >= 14

    def test_fresh_db_has_version_14(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            assert row["version"] == SCHEMA_VERSION

    def test_fresh_db_has_work_queue_table(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='work_queue'"
            ).fetchone()
            assert row is not None

    def test_fresh_db_has_artifact_threads_table(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='artifact_threads'"
            ).fetchone()
            assert row is not None


# ---------------------------------------------------------------------------
# TestMigrationV13ToV14
# ---------------------------------------------------------------------------


class TestMigrationV13ToV14:
    """Migration from v13 to v14."""

    def test_migration_creates_work_queue_table(self, v13_db):
        db = Database(db_path=v13_db)
        with db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='work_queue'"
            ).fetchone()
            assert row is not None

    def test_migration_creates_artifact_threads_table(self, v13_db):
        db = Database(db_path=v13_db)
        with db.connection() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='artifact_threads'"
            ).fetchone()
            assert row is not None

    def test_migration_updates_version_to_14(self, v13_db):
        db = Database(db_path=v13_db)
        with db.connection() as conn:
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            assert row["version"] == SCHEMA_VERSION

    def test_migration_adds_execution_runs_columns(self, v13_db):
        db = Database(db_path=v13_db)
        with db.connection() as conn:
            info = conn.execute("PRAGMA table_info(execution_runs)").fetchall()
            col_names = {r["name"] for r in info}
            expected_new = {
                "run_type", "goal", "current_phase",
                "config", "clarification_question", "clarification_answer",
            }
            assert expected_new.issubset(col_names)

    def test_migration_preserves_existing_execution_runs(self, v13_db):
        db = Database(db_path=v13_db)
        with db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM execution_runs WHERE id = ?", ("run-existing",)
            ).fetchone()
            assert row is not None
            assert row["status"] == "completed"
            assert row["project_id"] == "proj-1"
            assert row["sprint_id"] == "PROJ-S0001"
            assert row["run_type"] == "sprint"
            assert row["goal"] is None
            assert row["current_phase"] is None
            assert row["config"] is None
            assert row["clarification_question"] is None
            assert row["clarification_answer"] is None

    def test_migration_preserves_existing_project_data(self, v13_db):
        db = Database(db_path=v13_db)
        with db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", ("proj-1",)
            ).fetchone()
            assert row is not None
            assert row["shortname"] == "PROJ"
            assert row["name"] == "Project One"

    def test_migration_idempotent(self, v13_db):
        Database(db_path=v13_db)
        # Opening a second time should not raise
        db2 = Database(db_path=v13_db)
        with db2.connection() as conn:
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            assert row["version"] == SCHEMA_VERSION

    def test_migration_work_queue_indexes(self, v13_db):
        db = Database(db_path=v13_db)
        with db.connection() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='work_queue'"
            ).fetchall()
            index_names = {r["name"] for r in rows}
            expected = {
                "idx_work_queue_run",
                "idx_work_queue_status",
                "idx_work_queue_run_status",
                "idx_work_queue_project",
            }
            assert expected.issubset(index_names)

    def test_migration_artifact_threads_indexes(self, v13_db):
        db = Database(db_path=v13_db)
        with db.connection() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='artifact_threads'"
            ).fetchall()
            index_names = {r["name"] for r in rows}
            expected = {
                "idx_artifact_threads_run",
                "idx_artifact_threads_artifact",
                "idx_artifact_threads_run_artifact",
                "idx_artifact_threads_entry_type",
                "idx_artifact_threads_parent",
            }
            assert expected.issubset(index_names)


# ---------------------------------------------------------------------------
# TestWorkQueueTable
# ---------------------------------------------------------------------------


class TestWorkQueueTable:
    """work_queue CRUD and constraints."""

    def test_work_queue_columns(self, temp_db):
        with temp_db.connection() as conn:
            info = conn.execute("PRAGMA table_info(work_queue)").fetchall()
            col_names = [r["name"] for r in info]
            assert len(col_names) == 18
            expected = [
                "id", "run_id", "project_id", "work_type",
                "artifact_type", "artifact_id", "status", "priority",
                "depends_on", "assigned_agent_id", "config", "result",
                "retry_count", "pid", "log_path",
                "created_at", "started_at", "completed_at",
            ]
            assert col_names == expected

    def test_insert_minimal_work_queue_item(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO work_queue (id, run_id, project_id, work_type) "
                "VALUES (?, ?, ?, ?)",
                ("wq-001", "run-001", "test-project", "pm"),
            )
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM work_queue WHERE id = ?", ("wq-001",)
            ).fetchone()
            assert row["status"] == "pending"
            assert row["priority"] == 0
            assert row["retry_count"] == 0

    def test_insert_full_work_queue_item(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                """INSERT INTO work_queue
                   (id, run_id, project_id, work_type, artifact_type, artifact_id,
                    status, priority, depends_on, assigned_agent_id, config, result,
                    retry_count, pid, log_path, created_at, started_at, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "wq-full", "run-001", "test-project", "implement",
                    "prd", "TEST-P0001", "in_progress", 5,
                    '["wq-001"]', "agent-001",
                    '{"max_turns": 10}', '{"signal": "APPROVED"}',
                    2, 12345, "/tmp/log.txt",
                    "2025-01-01T00:00:00", "2025-01-01T00:01:00", "2025-01-01T00:10:00",
                ),
            )
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM work_queue WHERE id = ?", ("wq-full",)
            ).fetchone()
            assert row["work_type"] == "implement"
            assert row["artifact_type"] == "prd"
            assert row["priority"] == 5
            assert row["pid"] == 12345
            assert row["retry_count"] == 2

    def test_work_queue_run_fk_cascade(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO work_queue (id, run_id, project_id, work_type) "
                "VALUES (?, ?, ?, ?)",
                ("wq-cascade", "run-001", "test-project", "pm"),
            )
        # Delete the execution run
        with temp_db.connection() as conn:
            conn.execute("DELETE FROM execution_runs WHERE id = ?", ("run-001",))
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM work_queue WHERE id = ?", ("wq-cascade",)
            ).fetchone()
            assert row is None

    def test_work_queue_project_fk_cascade(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO work_queue (id, run_id, project_id, work_type) "
                "VALUES (?, ?, ?, ?)",
                ("wq-proj-cascade", "run-001", "test-project", "pm"),
            )
        # Delete the project (cascades through)
        with temp_db.connection() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", ("test-project",))
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM work_queue WHERE id = ?", ("wq-proj-cascade",)
            ).fetchone()
            assert row is None

    def test_work_queue_agent_fk_set_null(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO work_queue (id, run_id, project_id, work_type, assigned_agent_id) "
                "VALUES (?, ?, ?, ?, ?)",
                ("wq-agent", "run-001", "test-project", "pm", "agent-001"),
            )
        with temp_db.connection() as conn:
            conn.execute("DELETE FROM agents WHERE id = ?", ("agent-001",))
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM work_queue WHERE id = ?", ("wq-agent",)
            ).fetchone()
            assert row is not None
            assert row["assigned_agent_id"] is None

    def test_work_queue_depends_on_json(self, temp_db):
        deps = '["wq-001","wq-002"]'
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO work_queue (id, run_id, project_id, work_type, depends_on) "
                "VALUES (?, ?, ?, ?, ?)",
                ("wq-deps", "run-001", "test-project", "pm", deps),
            )
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT depends_on FROM work_queue WHERE id = ?", ("wq-deps",)
            ).fetchone()
            parsed = json.loads(row["depends_on"])
            assert parsed == ["wq-001", "wq-002"]

    def test_work_queue_config_json(self, temp_db):
        cfg = '{"max_turns": 5, "persona_type": "pm"}'
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO work_queue (id, run_id, project_id, work_type, config) "
                "VALUES (?, ?, ?, ?, ?)",
                ("wq-cfg", "run-001", "test-project", "pm", cfg),
            )
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT config FROM work_queue WHERE id = ?", ("wq-cfg",)
            ).fetchone()
            parsed = json.loads(row["config"])
            assert parsed == {"max_turns": 5, "persona_type": "pm"}

    def test_work_queue_result_json(self, temp_db):
        result = '{"signal": "APPROVED", "round": 2}'
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO work_queue (id, run_id, project_id, work_type, result) "
                "VALUES (?, ?, ?, ?, ?)",
                ("wq-result", "run-001", "test-project", "pm", result),
            )
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT result FROM work_queue WHERE id = ?", ("wq-result",)
            ).fetchone()
            parsed = json.loads(row["result"])
            assert parsed == {"signal": "APPROVED", "round": 2}

    def test_work_queue_status_values(self, temp_db):
        statuses = [
            "pending", "in_progress", "completed", "failed", "skipped",
            "escalated", "awaiting_clarification", "paused", "cancelled",
        ]
        for i, status in enumerate(statuses):
            with temp_db.connection() as conn:
                conn.execute(
                    "INSERT INTO work_queue (id, run_id, project_id, work_type, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (f"wq-status-{i}", "run-001", "test-project", "pm", status),
                )
        with temp_db.connection() as conn:
            rows = conn.execute(
                "SELECT status FROM work_queue WHERE id LIKE 'wq-status-%' ORDER BY id"
            ).fetchall()
            assert [r["status"] for r in rows] == statuses

    def test_work_queue_work_type_values(self, temp_db):
        work_types = [
            "pm", "design", "split", "challenge",
            "revise", "implement", "qa", "failure_triage",
        ]
        for i, wt in enumerate(work_types):
            with temp_db.connection() as conn:
                conn.execute(
                    "INSERT INTO work_queue (id, run_id, project_id, work_type) "
                    "VALUES (?, ?, ?, ?)",
                    (f"wq-wt-{i}", "run-001", "test-project", wt),
                )
        with temp_db.connection() as conn:
            rows = conn.execute(
                "SELECT work_type FROM work_queue WHERE id LIKE 'wq-wt-%' ORDER BY id"
            ).fetchall()
            assert [r["work_type"] for r in rows] == work_types

    def test_work_queue_nullable_fields(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO work_queue (id, run_id, project_id, work_type) "
                "VALUES (?, ?, ?, ?)",
                ("wq-nulls", "run-001", "test-project", "pm"),
            )
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM work_queue WHERE id = ?", ("wq-nulls",)
            ).fetchone()
            nullable_fields = [
                "artifact_type", "artifact_id", "assigned_agent_id",
                "config", "result", "pid", "log_path",
                "started_at", "completed_at",
            ]
            for field in nullable_fields:
                assert row[field] is None, f"{field} should be nullable"


# ---------------------------------------------------------------------------
# TestArtifactThreadsTable
# ---------------------------------------------------------------------------


class TestArtifactThreadsTable:
    """artifact_threads CRUD and constraints."""

    def test_artifact_threads_columns(self, temp_db):
        with temp_db.connection() as conn:
            info = conn.execute("PRAGMA table_info(artifact_threads)").fetchall()
            col_names = [r["name"] for r in info]
            assert len(col_names) == 12
            expected = [
                "id", "run_id", "project_id", "artifact_type", "artifact_id",
                "agent_id", "agent_persona", "round_number", "entry_type",
                "content", "parent_thread_id", "created_at",
            ]
            assert col_names == expected

    def test_artifact_threads_autoincrement_id(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO artifact_threads "
                "(run_id, project_id, artifact_type, artifact_id, entry_type) "
                "VALUES (?, ?, ?, ?, ?)",
                ("run-001", "test-project", "prd", "TEST-P0001", "creation"),
            )
            conn.execute(
                "INSERT INTO artifact_threads "
                "(run_id, project_id, artifact_type, artifact_id, entry_type) "
                "VALUES (?, ?, ?, ?, ?)",
                ("run-001", "test-project", "prd", "TEST-P0001", "challenge"),
            )
        with temp_db.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM artifact_threads ORDER BY id"
            ).fetchall()
            assert len(rows) == 2
            assert rows[1]["id"] > rows[0]["id"]

    def test_insert_artifact_thread_entry(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                """INSERT INTO artifact_threads
                   (run_id, project_id, artifact_type, artifact_id,
                    agent_id, agent_persona, round_number, entry_type,
                    content, parent_thread_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    "run-001", "test-project", "prd", "TEST-P0001",
                    "agent-001", "pm", 2, "revision",
                    '{"changes": ["updated scope"]}', None,
                ),
            )
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM artifact_threads WHERE run_id = ? AND entry_type = ?",
                ("run-001", "revision"),
            ).fetchone()
            assert row is not None
            assert row["agent_persona"] == "pm"
            assert row["round_number"] == 2

    def test_artifact_threads_self_referencing_fk(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO artifact_threads "
                "(run_id, project_id, artifact_type, artifact_id, entry_type) "
                "VALUES (?, ?, ?, ?, ?)",
                ("run-001", "test-project", "prd", "TEST-P0001", "creation"),
            )
            parent_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO artifact_threads "
                "(run_id, project_id, artifact_type, artifact_id, entry_type, parent_thread_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("run-001", "test-project", "prd", "TEST-P0001", "challenge", parent_id),
            )
            child_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        with temp_db.connection() as conn:
            child = conn.execute(
                "SELECT * FROM artifact_threads WHERE id = ?", (child_id,)
            ).fetchone()
            assert child["parent_thread_id"] == parent_id

    def test_artifact_threads_parent_fk_set_null(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO artifact_threads "
                "(run_id, project_id, artifact_type, artifact_id, entry_type) "
                "VALUES (?, ?, ?, ?, ?)",
                ("run-001", "test-project", "prd", "TEST-P0001", "creation"),
            )
            parent_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO artifact_threads "
                "(run_id, project_id, artifact_type, artifact_id, entry_type, parent_thread_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("run-001", "test-project", "prd", "TEST-P0001", "challenge", parent_id),
            )
            child_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            # Delete parent
            conn.execute("DELETE FROM artifact_threads WHERE id = ?", (parent_id,))
        with temp_db.connection() as conn:
            child = conn.execute(
                "SELECT * FROM artifact_threads WHERE id = ?", (child_id,)
            ).fetchone()
            assert child is not None
            assert child["parent_thread_id"] is None

    def test_artifact_threads_run_fk_cascade(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO artifact_threads "
                "(run_id, project_id, artifact_type, artifact_id, entry_type) "
                "VALUES (?, ?, ?, ?, ?)",
                ("run-001", "test-project", "prd", "TEST-P0001", "creation"),
            )
        with temp_db.connection() as conn:
            conn.execute("DELETE FROM execution_runs WHERE id = ?", ("run-001",))
        with temp_db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM artifact_threads WHERE run_id = ?", ("run-001",)
            ).fetchall()
            assert len(rows) == 0

    def test_artifact_threads_agent_fk_set_null(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO artifact_threads "
                "(run_id, project_id, artifact_type, artifact_id, entry_type, agent_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("run-001", "test-project", "prd", "TEST-P0001", "creation", "agent-001"),
            )
            thread_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        with temp_db.connection() as conn:
            conn.execute("DELETE FROM agents WHERE id = ?", ("agent-001",))
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM artifact_threads WHERE id = ?", (thread_id,)
            ).fetchone()
            assert row is not None
            assert row["agent_id"] is None

    def test_artifact_threads_entry_type_values(self, temp_db):
        entry_types = [
            "creation", "challenge", "revision", "approval",
            "signal", "escalation", "clarification", "user_intervention",
        ]
        for i, et in enumerate(entry_types):
            with temp_db.connection() as conn:
                conn.execute(
                    "INSERT INTO artifact_threads "
                    "(run_id, project_id, artifact_type, artifact_id, entry_type) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("run-001", "test-project", "prd", f"art-{i}", et),
                )
        with temp_db.connection() as conn:
            rows = conn.execute(
                "SELECT entry_type FROM artifact_threads ORDER BY artifact_id"
            ).fetchall()
            assert [r["entry_type"] for r in rows] == entry_types

    def test_artifact_threads_content_json(self, temp_db):
        content = '{"changes": ["scope update", "added section"]}'
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO artifact_threads "
                "(run_id, project_id, artifact_type, artifact_id, entry_type, content) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("run-001", "test-project", "prd", "TEST-P0001", "revision", content),
            )
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT content FROM artifact_threads WHERE entry_type = 'revision'"
            ).fetchone()
            parsed = json.loads(row["content"])
            assert parsed == {"changes": ["scope update", "added section"]}

    def test_artifact_threads_round_number_default(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO artifact_threads "
                "(run_id, project_id, artifact_type, artifact_id, entry_type) "
                "VALUES (?, ?, ?, ?, ?)",
                ("run-001", "test-project", "prd", "TEST-P0001", "creation"),
            )
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT round_number FROM artifact_threads"
            ).fetchone()
            assert row["round_number"] == 1

    def test_artifact_threads_nullable_fields(self, temp_db):
        with temp_db.connection() as conn:
            conn.execute(
                "INSERT INTO artifact_threads "
                "(run_id, project_id, artifact_type, artifact_id, entry_type) "
                "VALUES (?, ?, ?, ?, ?)",
                ("run-001", "test-project", "prd", "TEST-P0001", "creation"),
            )
        with temp_db.connection() as conn:
            row = conn.execute("SELECT * FROM artifact_threads").fetchone()
            nullable_fields = ["agent_id", "agent_persona", "content", "parent_thread_id"]
            for field in nullable_fields:
                assert row[field] is None, f"{field} should be nullable"


# ---------------------------------------------------------------------------
# TestExecutionRunsExtensions
# ---------------------------------------------------------------------------


class TestExecutionRunsExtensions:
    """New columns on execution_runs."""

    def test_run_type_default_sprint(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT run_type FROM execution_runs WHERE id = ?", ("run-001",)
            ).fetchone()
            assert row["run_type"] == "sprint"

    def test_run_type_settable(self, temp_db):
        result = temp_db.update_execution_run("run-001", run_type="pipeline")
        assert result is not None
        assert result["run_type"] == "pipeline"

    def test_goal_nullable(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT goal FROM execution_runs WHERE id = ?", ("run-001",)
            ).fetchone()
            assert row["goal"] is None

    def test_current_phase_nullable(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT current_phase FROM execution_runs WHERE id = ?", ("run-001",)
            ).fetchone()
            assert row["current_phase"] is None

    def test_config_column_json(self, temp_db):
        cfg = '{"phases": ["pm", "design", "split"]}'
        temp_db.update_execution_run("run-001", config=cfg)
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT config FROM execution_runs WHERE id = ?", ("run-001",)
            ).fetchone()
            parsed = json.loads(row["config"])
            assert parsed == {"phases": ["pm", "design", "split"]}

    def test_clarification_columns_nullable(self, temp_db):
        with temp_db.connection() as conn:
            row = conn.execute(
                "SELECT clarification_question, clarification_answer "
                "FROM execution_runs WHERE id = ?",
                ("run-001",),
            ).fetchone()
            assert row["clarification_question"] is None
            assert row["clarification_answer"] is None

    def test_update_execution_run_new_fields(self, temp_db):
        result = temp_db.update_execution_run(
            "run-001",
            goal="Build auth",
            current_phase="pm",
            config="{}",
        )
        assert result is not None
        assert result["goal"] == "Build auth"
        assert result["current_phase"] == "pm"
        assert result["config"] == "{}"

    def test_existing_execution_run_data_preserved(self, v13_db):
        db = Database(db_path=v13_db)
        with db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM execution_runs WHERE id = ?", ("run-existing",)
            ).fetchone()
            assert row is not None
            # Original data preserved
            assert row["status"] == "completed"
            assert row["project_id"] == "proj-1"
            assert row["sprint_id"] == "PROJ-S0001"
            # New columns have correct defaults/NULLs
            assert row["run_type"] == "sprint"
            assert row["goal"] is None
            assert row["current_phase"] is None
            assert row["config"] is None
            assert row["clarification_question"] is None
            assert row["clarification_answer"] is None
