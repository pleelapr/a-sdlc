"""Tests for quality & traceability -- requirements, AC verifications, challenge records.

Covers SDLC-T00163 / P0029 entities: requirements, requirement_links,
ac_verifications, challenge_records, and the v11->v12 migration.

Also covers SDLC-T00164: parse_requirements MCP tool + depth classification.
"""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a_sdlc.core.database import SCHEMA_VERSION, Database
from a_sdlc.core.quality_config import QualityConfig
from a_sdlc.server import (
    _CANDIDATE_PATTERN,
    BEHAVIORAL_KEYWORDS,
    CHALLENGE_CHECKLISTS,
    INTEGRATION_KEYWORDS,
    REQ_PATTERN,
    STRUCTURAL_KEYWORDS,
    _auto_parse_requirements,
    _detect_stale_loop,
    _sprint_waivers,
    challenge_artifact,
    classify_depth,
    complete_sprint,
    create_remediation_tasks,
    get_challenge_status,
    get_quality_report,
    get_task_requirements,
    link_task_requirements,
    parse_requirements,
    record_challenge_round,
    split_prd,
    waive_sprint_quality,
)

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
        db.create_task(
            task_id="TEST-T00001",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Test Task 1",
            file_path="/tmp/test/tasks/TEST-T00001.md",
        )
        db.create_task(
            task_id="TEST-T00002",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Test Task 2",
            file_path="/tmp/test/tasks/TEST-T00002.md",
        )
        yield db


@pytest.fixture
def v11_db():
    """Create a database at schema version 11 (before quality tables)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_v11.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        conn.executescript("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT INTO schema_version (version) VALUES (11);

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
                assigned_agent_id TEXT,
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
            CREATE UNIQUE INDEX idx_task_claims_active
                ON task_claims(task_id) WHERE status = 'active';

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

            CREATE TABLE agent_teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                project_id TEXT NOT NULL,
                lead_agent_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (lead_agent_id) REFERENCES agents(id) ON DELETE SET NULL
            );
        """)
        conn.commit()
        conn.close()

        yield db_path


# =============================================================================
# Migration v11 -> v12 Tests
# =============================================================================


class TestMigrationV11ToV12:
    """Test the v11 -> v12 migration (add quality & traceability tables)."""

    def test_migration_creates_requirements_table(self, v11_db):
        """Migration should create the requirements table."""
        db = Database(db_path=v11_db)
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='requirements'"
            )
            assert cursor.fetchone() is not None

    def test_migration_creates_requirement_links_table(self, v11_db):
        """Migration should create the requirement_links table."""
        db = Database(db_path=v11_db)
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='requirement_links'"
            )
            assert cursor.fetchone() is not None

    def test_migration_creates_ac_verifications_table(self, v11_db):
        """Migration should create the ac_verifications table."""
        db = Database(db_path=v11_db)
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ac_verifications'"
            )
            assert cursor.fetchone() is not None

    def test_migration_creates_challenge_records_table(self, v11_db):
        """Migration should create the challenge_records table."""
        db = Database(db_path=v11_db)
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='challenge_records'"
            )
            assert cursor.fetchone() is not None

    def test_migration_creates_challenge_index(self, v11_db):
        """Migration should create the idx_challenge_artifact index."""
        db = Database(db_path=v11_db)
        with db.connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_challenge_artifact'"
            )
            assert cursor.fetchone() is not None

    def test_migration_updates_version(self, v11_db):
        """Migration should update schema to current SCHEMA_VERSION."""
        db = Database(db_path=v11_db)
        with db.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_migration_idempotent(self, v11_db):
        """Opening database twice should not cause errors."""
        Database(db_path=v11_db)
        db2 = Database(db_path=v11_db)
        with db2.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version")
            version = cursor.fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_migration_preserves_existing_data(self, v11_db):
        """Migration should preserve existing project/PRD/task data."""
        conn = sqlite3.connect(v11_db)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO projects (id, shortname, name, path) VALUES (?, ?, ?, ?)",
            ("proj-1", "PROJ", "Project One", "/tmp/proj1"),
        )
        conn.execute(
            "INSERT INTO prds (id, project_id, title, file_path) VALUES (?, ?, ?, ?)",
            ("PROJ-P0001", "proj-1", "Test PRD", "/tmp/proj1/prds/PROJ-P0001.md"),
        )
        conn.commit()
        conn.close()

        db = Database(db_path=v11_db)
        with db.connection() as conn:
            project = conn.execute(
                "SELECT * FROM projects WHERE id = 'proj-1'"
            ).fetchone()
            assert project is not None
            assert project["name"] == "Project One"


# =============================================================================
# Requirements CRUD Tests
# =============================================================================


class TestUpsertRequirement:
    """Test upsert_requirement behavior."""

    def test_insert_new_requirement(self, temp_db):
        """Inserting a new requirement should succeed."""
        req = temp_db.upsert_requirement(
            id="REQ-001",
            prd_id="TEST-P0001",
            req_type="functional",
            req_number="FR-001",
            summary="Users can log in",
        )
        assert req["id"] == "REQ-001"
        assert req["prd_id"] == "TEST-P0001"
        assert req["req_type"] == "functional"
        assert req["req_number"] == "FR-001"
        assert req["summary"] == "Users can log in"
        assert req["depth"] == "structural"

    def test_upsert_idempotent(self, temp_db):
        """Upserting the same requirement twice should update, not duplicate."""
        temp_db.upsert_requirement(
            id="REQ-001",
            prd_id="TEST-P0001",
            req_type="functional",
            req_number="FR-001",
            summary="Original summary",
        )
        req = temp_db.upsert_requirement(
            id="REQ-001",
            prd_id="TEST-P0001",
            req_type="functional",
            req_number="FR-001",
            summary="Updated summary",
        )
        assert req["summary"] == "Updated summary"
        # Should still be only one record
        reqs = temp_db.get_requirements("TEST-P0001")
        assert len(reqs) == 1

    def test_upsert_with_custom_depth(self, temp_db):
        """Upserting with a non-default depth should persist."""
        req = temp_db.upsert_requirement(
            id="REQ-002",
            prd_id="TEST-P0001",
            req_type="non-functional",
            req_number="NFR-001",
            summary="System responds within 200ms",
            depth="behavioral",
        )
        assert req["depth"] == "behavioral"


class TestGetRequirements:
    """Test get_requirements and get_requirement."""

    def test_get_all_requirements(self, temp_db):
        """Should return all requirements for a PRD."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.upsert_requirement("R2", "TEST-P0001", "functional", "FR-002", "Req 2")
        temp_db.upsert_requirement("R3", "TEST-P0001", "non-functional", "NFR-001", "Req 3")
        reqs = temp_db.get_requirements("TEST-P0001")
        assert len(reqs) == 3

    def test_get_requirements_with_type_filter(self, temp_db):
        """Should filter requirements by type."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.upsert_requirement("R2", "TEST-P0001", "non-functional", "NFR-001", "Req 2")
        reqs = temp_db.get_requirements("TEST-P0001", req_type="functional")
        assert len(reqs) == 1
        assert reqs[0]["req_type"] == "functional"

    def test_get_requirements_empty(self, temp_db):
        """Should return empty list for PRD with no requirements."""
        reqs = temp_db.get_requirements("TEST-P0001")
        assert reqs == []

    def test_get_requirement_by_id(self, temp_db):
        """Should return a single requirement by ID."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        req = temp_db.get_requirement("R1")
        assert req is not None
        assert req["id"] == "R1"

    def test_get_requirement_not_found(self, temp_db):
        """Should return None for nonexistent requirement."""
        assert temp_db.get_requirement("NONEXISTENT") is None


class TestDeleteRequirements:
    """Test delete_requirements."""

    def test_delete_all_for_prd(self, temp_db):
        """Should delete all requirements for a PRD and return count."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.upsert_requirement("R2", "TEST-P0001", "functional", "FR-002", "Req 2")
        deleted = temp_db.delete_requirements("TEST-P0001")
        assert deleted == 2
        assert temp_db.get_requirements("TEST-P0001") == []

    def test_delete_returns_zero_when_none(self, temp_db):
        """Should return 0 when no requirements exist for the PRD."""
        deleted = temp_db.delete_requirements("TEST-P0001")
        assert deleted == 0


# =============================================================================
# Requirement Links Tests
# =============================================================================


class TestLinkTaskRequirement:
    """Test link_task_requirement."""

    def test_link_creates_association(self, temp_db):
        """Linking should create an association."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        link = temp_db.link_task_requirement("R1", "TEST-T00001")
        assert link["requirement_id"] == "R1"
        assert link["task_id"] == "TEST-T00001"

    def test_link_duplicate_is_ignored(self, temp_db):
        """Linking the same pair twice should not raise an error."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.link_task_requirement("R1", "TEST-T00001")
        link = temp_db.link_task_requirement("R1", "TEST-T00001")
        assert link["requirement_id"] == "R1"


class TestGetTaskRequirements:
    """Test get_task_requirements JOIN behavior."""

    def test_returns_linked_requirements_with_verification_status(self, temp_db):
        """Should return requirements with a 'verified' field via LEFT JOIN."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.upsert_requirement("R2", "TEST-P0001", "functional", "FR-002", "Req 2")
        temp_db.link_task_requirement("R1", "TEST-T00001")
        temp_db.link_task_requirement("R2", "TEST-T00001")
        # Verify one
        temp_db.record_ac_verification("R1", "TEST-T00001", "agent-1", "test", "All tests pass")

        reqs = temp_db.get_task_requirements("TEST-T00001")
        assert len(reqs) == 2
        r1 = next(r for r in reqs if r["id"] == "R1")
        r2 = next(r for r in reqs if r["id"] == "R2")
        assert r1["verified"] == 1
        assert r2["verified"] == 0

    def test_returns_empty_for_unlinked_task(self, temp_db):
        """Should return empty list for a task with no linked requirements."""
        reqs = temp_db.get_task_requirements("TEST-T00001")
        assert reqs == []


class TestGetRequirementTasks:
    """Test get_requirement_tasks."""

    def test_returns_tasks_for_requirement(self, temp_db):
        """Should return all tasks linked to a requirement."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.link_task_requirement("R1", "TEST-T00001")
        temp_db.link_task_requirement("R1", "TEST-T00002")
        tasks = temp_db.get_requirement_tasks("R1")
        assert len(tasks) == 2
        task_ids = {t["id"] for t in tasks}
        assert task_ids == {"TEST-T00001", "TEST-T00002"}


class TestGetOrphanedRequirements:
    """Test get_orphaned_requirements."""

    def test_returns_unlinked_requirements(self, temp_db):
        """Should return requirements with zero linked tasks."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.upsert_requirement("R2", "TEST-P0001", "functional", "FR-002", "Req 2")
        temp_db.link_task_requirement("R1", "TEST-T00001")
        orphans = temp_db.get_orphaned_requirements("TEST-P0001")
        assert len(orphans) == 1
        assert orphans[0]["id"] == "R2"

    def test_returns_all_when_none_linked(self, temp_db):
        """All requirements should be orphaned if none are linked."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.upsert_requirement("R2", "TEST-P0001", "functional", "FR-002", "Req 2")
        orphans = temp_db.get_orphaned_requirements("TEST-P0001")
        assert len(orphans) == 2

    def test_returns_empty_when_all_linked(self, temp_db):
        """Should return empty list when all requirements have linked tasks."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.link_task_requirement("R1", "TEST-T00001")
        orphans = temp_db.get_orphaned_requirements("TEST-P0001")
        assert len(orphans) == 0


class TestGetCoverageStats:
    """Test get_coverage_stats."""

    def test_coverage_with_mixed_links(self, temp_db):
        """Should compute correct total/linked/orphaned counts."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.upsert_requirement("R2", "TEST-P0001", "functional", "FR-002", "Req 2")
        temp_db.upsert_requirement("R3", "TEST-P0001", "non-functional", "NFR-001", "Req 3")
        temp_db.link_task_requirement("R1", "TEST-T00001")
        stats = temp_db.get_coverage_stats("TEST-P0001")
        assert stats["total"] == 3
        assert stats["linked"] == 1
        assert stats["orphaned"] == 2
        assert "functional" in stats["by_type"]
        assert stats["by_type"]["functional"]["total"] == 2
        assert stats["by_type"]["functional"]["linked"] == 1
        assert stats["by_type"]["non-functional"]["total"] == 1
        assert stats["by_type"]["non-functional"]["linked"] == 0

    def test_coverage_empty(self, temp_db):
        """Should return zeros when no requirements exist."""
        stats = temp_db.get_coverage_stats("TEST-P0001")
        assert stats["total"] == 0
        assert stats["linked"] == 0
        assert stats["orphaned"] == 0
        assert stats["by_type"] == {}


# =============================================================================
# AC Verifications Tests
# =============================================================================


class TestRecordAcVerification:
    """Test record_ac_verification."""

    def test_record_new_verification(self, temp_db):
        """Recording a new verification should succeed."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.link_task_requirement("R1", "TEST-T00001")
        v = temp_db.record_ac_verification(
            "R1", "TEST-T00001", "agent-1", "test", "pytest passed"
        )
        assert v["requirement_id"] == "R1"
        assert v["task_id"] == "TEST-T00001"
        assert v["verified_by"] == "agent-1"
        assert v["evidence_type"] == "test"
        assert v["evidence"] == "pytest passed"

    def test_re_verification_overwrites(self, temp_db):
        """Re-verifying the same requirement+task should overwrite."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.link_task_requirement("R1", "TEST-T00001")
        temp_db.record_ac_verification("R1", "TEST-T00001", "agent-1", "test", "v1")
        v = temp_db.record_ac_verification("R1", "TEST-T00001", "agent-2", "manual", "v2")
        assert v["verified_by"] == "agent-2"
        assert v["evidence"] == "v2"
        # Should still be only one record
        verifications = temp_db.get_ac_verifications("TEST-T00001")
        assert len(verifications) == 1


class TestGetAcVerifications:
    """Test get_ac_verifications."""

    def test_returns_all_verifications_for_task(self, temp_db):
        """Should return all verification records for a task."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.upsert_requirement("R2", "TEST-P0001", "functional", "FR-002", "Req 2")
        temp_db.link_task_requirement("R1", "TEST-T00001")
        temp_db.link_task_requirement("R2", "TEST-T00001")
        temp_db.record_ac_verification("R1", "TEST-T00001", "agent-1", "test", "pass")
        temp_db.record_ac_verification("R2", "TEST-T00001", "agent-1", "test", "pass")
        verifications = temp_db.get_ac_verifications("TEST-T00001")
        assert len(verifications) == 2

    def test_returns_empty_for_no_verifications(self, temp_db):
        """Should return empty list for task with no verifications."""
        assert temp_db.get_ac_verifications("TEST-T00001") == []


class TestGetUnverifiedAcs:
    """Test get_unverified_acs."""

    def test_returns_unverified_requirements(self, temp_db):
        """Should return requirements linked to task but not verified."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.upsert_requirement("R2", "TEST-P0001", "functional", "FR-002", "Req 2")
        temp_db.link_task_requirement("R1", "TEST-T00001")
        temp_db.link_task_requirement("R2", "TEST-T00001")
        temp_db.record_ac_verification("R1", "TEST-T00001", "agent-1", "test", "pass")
        unverified = temp_db.get_unverified_acs("TEST-T00001")
        assert len(unverified) == 1
        assert unverified[0]["id"] == "R2"

    def test_returns_empty_when_all_verified(self, temp_db):
        """Should return empty list when all linked requirements are verified."""
        temp_db.upsert_requirement("R1", "TEST-P0001", "functional", "FR-001", "Req 1")
        temp_db.link_task_requirement("R1", "TEST-T00001")
        temp_db.record_ac_verification("R1", "TEST-T00001", "agent-1", "test", "pass")
        unverified = temp_db.get_unverified_acs("TEST-T00001")
        assert len(unverified) == 0

    def test_returns_empty_when_no_links(self, temp_db):
        """Should return empty list when task has no linked requirements."""
        unverified = temp_db.get_unverified_acs("TEST-T00001")
        assert len(unverified) == 0


# =============================================================================
# Challenge Records Tests
# =============================================================================


class TestCreateChallengeRound:
    """Test create_challenge_round."""

    def test_create_first_round(self, temp_db):
        """Creating a challenge round should succeed."""
        objections = json.dumps(["Missing error handling", "No test coverage"])
        cr = temp_db.create_challenge_round("prd", "TEST-P0001", 1, objections)
        assert cr["artifact_type"] == "prd"
        assert cr["artifact_id"] == "TEST-P0001"
        assert cr["round_number"] == 1
        assert cr["objections"] == objections
        assert cr["status"] == "open"
        assert cr["responses"] is None
        assert cr["verdict"] is None

    def test_create_with_context(self, temp_db):
        """Creating with challenger_context should persist."""
        cr = temp_db.create_challenge_round(
            "prd", "TEST-P0001", 1, "[]", challenger_context="security review"
        )
        assert cr["challenger_context"] == "security review"

    def test_create_multiple_rounds(self, temp_db):
        """Creating multiple rounds for the same artifact should succeed."""
        temp_db.create_challenge_round("prd", "TEST-P0001", 1, "[]")
        cr2 = temp_db.create_challenge_round("prd", "TEST-P0001", 2, "[]")
        assert cr2["round_number"] == 2


class TestUpdateChallengeRound:
    """Test update_challenge_round."""

    def test_update_responses(self, temp_db):
        """Updating responses should persist."""
        temp_db.create_challenge_round("prd", "TEST-P0001", 1, "[]")
        responses = json.dumps(["Fixed error handling", "Added tests"])
        updated = temp_db.update_challenge_round(
            "prd", "TEST-P0001", 1, responses=responses
        )
        assert updated is not None
        assert updated["responses"] == responses

    def test_update_verdict_and_status(self, temp_db):
        """Updating verdict and status should persist."""
        temp_db.create_challenge_round("prd", "TEST-P0001", 1, "[]")
        updated = temp_db.update_challenge_round(
            "prd", "TEST-P0001", 1, verdict="accepted", status="closed"
        )
        assert updated is not None
        assert updated["verdict"] == "accepted"
        assert updated["status"] == "closed"

    def test_update_nonexistent_returns_none(self, temp_db):
        """Updating a nonexistent round should return None."""
        result = temp_db.update_challenge_round(
            "prd", "NONEXISTENT", 99, verdict="rejected"
        )
        assert result is None

    def test_update_with_no_fields_returns_current(self, temp_db):
        """Updating with no fields should return the current record."""
        temp_db.create_challenge_round("prd", "TEST-P0001", 1, "[]")
        result = temp_db.update_challenge_round("prd", "TEST-P0001", 1)
        assert result is not None
        assert result["round_number"] == 1


class TestGetChallengeRounds:
    """Test get_challenge_rounds."""

    def test_returns_rounds_ordered(self, temp_db):
        """Should return rounds ordered by round_number."""
        temp_db.create_challenge_round("prd", "TEST-P0001", 2, "[]")
        temp_db.create_challenge_round("prd", "TEST-P0001", 1, "[]")
        rounds = temp_db.get_challenge_rounds("prd", "TEST-P0001")
        assert len(rounds) == 2
        assert rounds[0]["round_number"] == 1
        assert rounds[1]["round_number"] == 2

    def test_parses_json_fields(self, temp_db):
        """Should parse objections and responses from JSON strings."""
        objections = json.dumps(["issue 1", "issue 2"])
        responses = json.dumps(["fix 1", "fix 2"])
        temp_db.create_challenge_round("prd", "TEST-P0001", 1, objections)
        temp_db.update_challenge_round("prd", "TEST-P0001", 1, responses=responses)
        rounds = temp_db.get_challenge_rounds("prd", "TEST-P0001")
        assert rounds[0]["objections"] == ["issue 1", "issue 2"]
        assert rounds[0]["responses"] == ["fix 1", "fix 2"]

    def test_returns_empty_for_no_rounds(self, temp_db):
        """Should return empty list for artifact with no challenge rounds."""
        rounds = temp_db.get_challenge_rounds("prd", "NONEXISTENT")
        assert rounds == []


class TestGetChallengeStatus:
    """Test get_challenge_status."""

    def test_status_with_mixed_rounds(self, temp_db):
        """Should compute correct counts."""
        temp_db.create_challenge_round("prd", "TEST-P0001", 1, "[]")
        temp_db.update_challenge_round("prd", "TEST-P0001", 1, status="closed")
        temp_db.create_challenge_round("prd", "TEST-P0001", 2, "[]")

        status = temp_db.get_challenge_status("prd", "TEST-P0001")
        assert status["total_rounds"] == 2
        assert status["latest_status"] == "open"
        assert status["open_count"] == 1
        assert status["closed_count"] == 1

    def test_status_empty(self, temp_db):
        """Should return zeros for artifact with no challenge rounds."""
        status = temp_db.get_challenge_status("prd", "NONEXISTENT")
        assert status["total_rounds"] == 0
        assert status["latest_status"] is None
        assert status["open_count"] == 0
        assert status["closed_count"] == 0


# =============================================================================
# Schema Version Dynamic Reference Test
# =============================================================================


class TestSchemaVersionDynamic:
    """Verify that SCHEMA_VERSION is used dynamically, not hardcoded."""

    def test_schema_version_is_12_or_higher(self):
        """SCHEMA_VERSION should be at least 12 after this migration."""
        assert SCHEMA_VERSION >= 12

    def test_fresh_db_matches_schema_version(self):
        """A fresh database should have version == SCHEMA_VERSION."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "fresh.db"
            db = Database(db_path=db_path)
            with db.connection() as conn:
                version = conn.execute(
                    "SELECT version FROM schema_version"
                ).fetchone()[0]
            assert version == SCHEMA_VERSION


# =============================================================================
# Coverage Reporting MCP Tools (SDLC-T00168)
# =============================================================================


class TestGetCoverageReport:
    """Test get_quality_report('coverage', ...) MCP tool."""

    @patch("a_sdlc.server.get_db")
    def test_fully_linked_prd(self, mock_get_db):
        """Should return 100% linkage when all requirements are linked."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_prd.return_value = {"id": "P-0001", "project_id": "proj"}
        db.get_coverage_stats.return_value = {
            "total": 3, "linked": 3, "orphaned": 0,
            "by_type": {"FR": {"total": 2, "linked": 2}, "AC": {"total": 1, "linked": 1}},
        }
        db.get_orphaned_requirements.return_value = []
        db.get_requirements.return_value = [
            {"id": "r1", "req_number": "FR-001", "depth": "structural"},
            {"id": "r2", "req_number": "FR-002", "depth": "structural"},
            {"id": "r3", "req_number": "AC-001", "depth": "structural"},
        ]
        db.get_requirement_tasks.return_value = [
            {"id": "T1", "status": "completed"},
        ]
        db.get_ac_verifications.return_value = []

        result = get_quality_report("coverage", prd_id="P-0001")
        assert result["status"] == "ok"
        assert result["linkage"]["linkage_pct"] == 100.0
        assert result["linkage"]["orphaned_count"] == 0

    @patch("a_sdlc.server.get_db")
    def test_orphaned_requirements(self, mock_get_db):
        """Should identify orphaned requirements correctly."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_prd.return_value = {"id": "P-0001", "project_id": "proj"}
        db.get_coverage_stats.return_value = {
            "total": 3, "linked": 1, "orphaned": 2,
            "by_type": {"FR": {"total": 2, "linked": 1}, "AC": {"total": 1, "linked": 0}},
        }
        db.get_orphaned_requirements.return_value = [
            {"id": "r2", "req_number": "FR-002", "summary": "Orphaned req"},
            {"id": "r3", "req_number": "AC-001", "summary": "Unlinked AC"},
        ]
        db.get_requirements.return_value = [
            {"id": "r1", "req_number": "FR-001", "depth": "structural"},
        ]
        db.get_requirement_tasks.return_value = [{"id": "T1", "status": "pending"}]
        db.get_ac_verifications.return_value = []

        result = get_quality_report("coverage", prd_id="P-0001")
        assert result["status"] == "ok"
        assert result["linkage"]["orphaned_count"] == 2
        assert len(result["orphaned_requirements"]) == 2
        assert round(result["linkage"]["linkage_pct"], 1) == 33.3

    @patch("a_sdlc.server.get_db")
    def test_completion_coverage(self, mock_get_db):
        """Should compute completion percentage from linked task statuses."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_prd.return_value = {"id": "P-0001", "project_id": "proj"}
        db.get_coverage_stats.return_value = {
            "total": 1, "linked": 1, "orphaned": 0,
            "by_type": {"FR": {"total": 1, "linked": 1}},
        }
        db.get_orphaned_requirements.return_value = []
        db.get_requirements.return_value = [
            {"id": "r1", "req_number": "FR-001", "depth": "structural"},
        ]
        db.get_requirement_tasks.return_value = [
            {"id": "T1", "status": "completed"},
            {"id": "T2", "status": "in_progress"},
        ]
        db.get_ac_verifications.return_value = []

        result = get_quality_report("coverage", prd_id="P-0001")
        assert result["status"] == "ok"
        assert result["completion"]["completed_tasks"] == 1
        assert result["completion"]["total_tasks"] == 2
        assert result["completion"]["completion_pct"] == 50.0

    @patch("a_sdlc.server.get_db")
    def test_behavioral_gaps(self, mock_get_db):
        """Should detect behavioral requirements without test evidence."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_prd.return_value = {"id": "P-0001", "project_id": "proj"}
        db.get_coverage_stats.return_value = {
            "total": 2, "linked": 2, "orphaned": 0,
            "by_type": {"FR": {"total": 1, "linked": 1}, "AC": {"total": 1, "linked": 1}},
        }
        db.get_orphaned_requirements.return_value = []
        db.get_requirements.return_value = [
            {"id": "r1", "req_number": "FR-001", "depth": "behavioral"},
            {"id": "r2", "req_number": "AC-001", "depth": "structural"},
        ]
        # r1 has tasks but no test evidence; r2 is structural (not flagged)
        db.get_requirement_tasks.side_effect = [
            [{"id": "T1", "status": "pending"}],  # r1
            [{"id": "T2", "status": "completed"}],  # r2
        ]
        db.get_ac_verifications.side_effect = [
            [{"evidence_type": "manual", "requirement_id": "r1"}],  # T1
            [],  # T2
        ]

        result = get_quality_report("coverage", prd_id="P-0001")
        assert result["status"] == "ok"
        assert len(result["behavioral_gaps"]) == 1
        assert result["behavioral_gaps"][0]["id"] == "r1"

    @patch("a_sdlc.server.get_db")
    def test_zero_requirements(self, mock_get_db):
        """Should return 100% linkage and completion when no requirements exist."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_prd.return_value = {"id": "P-0001", "project_id": "proj"}
        db.get_coverage_stats.return_value = {
            "total": 0, "linked": 0, "orphaned": 0,
            "by_type": {},
        }
        db.get_orphaned_requirements.return_value = []
        db.get_requirements.return_value = []

        result = get_quality_report("coverage", prd_id="P-0001")
        assert result["status"] == "ok"
        assert result["linkage"]["linkage_pct"] == 100.0
        assert result["completion"]["completion_pct"] == 100.0
        assert result["behavioral_gaps"] == []

    @patch("a_sdlc.server.get_db")
    def test_nonexistent_prd(self, mock_get_db):
        """Should return error for non-existent PRD."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_prd.return_value = None

        result = get_quality_report("coverage", prd_id="NONEXISTENT")
        assert result["status"] == "error"
        assert "PRD not found" in result["message"]


class TestGetVerificationStatus:
    """Test get_quality_report('verification', ...) MCP tool."""

    @patch("a_sdlc.server.get_db")
    def test_all_acs_verified(self, mock_get_db):
        """Should return 100% when all ACs have verification evidence."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_prd.return_value = {"id": "P-0001", "project_id": "proj"}
        db.get_requirements.return_value = [
            {"id": "ac1", "req_number": "AC-001", "summary": "First AC", "depth": "structural"},
            {"id": "ac2", "req_number": "AC-002", "summary": "Second AC", "depth": "behavioral"},
        ]
        db.get_requirement_tasks.side_effect = [
            [{"id": "T1"}],  # ac1
            [{"id": "T2"}],  # ac2
        ]
        db.get_ac_verifications.side_effect = [
            [{"requirement_id": "ac1", "evidence_type": "test", "evidence": "passes"}],
            [{"requirement_id": "ac2", "evidence_type": "manual", "evidence": "verified"}],
        ]

        result = get_quality_report("verification", prd_id="P-0001")
        assert result["status"] == "ok"
        assert result["verified"] == 2
        assert result["total"] == 2
        assert result["verified_pct"] == 100.0
        assert result["acs"][0]["verified"] is True
        assert result["acs"][1]["verified"] is True

    @patch("a_sdlc.server.get_db")
    def test_partial_verification(self, mock_get_db):
        """Should show correct percentage with partial verification."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_prd.return_value = {"id": "P-0001", "project_id": "proj"}
        db.get_requirements.return_value = [
            {"id": "ac1", "req_number": "AC-001", "summary": "First AC", "depth": "structural"},
            {"id": "ac2", "req_number": "AC-002", "summary": "Second AC", "depth": "structural"},
        ]
        db.get_requirement_tasks.side_effect = [
            [{"id": "T1"}],  # ac1 -- has verification
            [],  # ac2 -- no tasks, no verification
        ]
        db.get_ac_verifications.side_effect = [
            [{"requirement_id": "ac1", "evidence_type": "test", "evidence": "ok"}],
        ]

        result = get_quality_report("verification", prd_id="P-0001")
        assert result["status"] == "ok"
        assert result["verified"] == 1
        assert result["total"] == 2
        assert result["verified_pct"] == 50.0
        assert result["acs"][0]["verified"] is True
        assert result["acs"][1]["verified"] is False

    @patch("a_sdlc.server.get_db")
    def test_zero_acs(self, mock_get_db):
        """Should return 100% when no ACs exist (vacuously true)."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_prd.return_value = {"id": "P-0001", "project_id": "proj"}
        db.get_requirements.return_value = []

        result = get_quality_report("verification", prd_id="P-0001")
        assert result["status"] == "ok"
        assert result["total"] == 0
        assert result["verified"] == 0
        assert result["verified_pct"] == 100.0

    @patch("a_sdlc.server.get_db")
    def test_nonexistent_prd(self, mock_get_db):
        """Should return error for non-existent PRD."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_prd.return_value = None

        result = get_quality_report("verification", prd_id="NONEXISTENT")
        assert result["status"] == "error"
        assert "PRD not found" in result["message"]


class TestGetSprintQualityReport:
    """Test get_quality_report('sprint', ...) MCP tool."""

    @patch("a_sdlc.server.get_db")
    def test_aggregates_across_prds(self, mock_get_db):
        """Should aggregate coverage and verification across multiple PRDs (AC-006)."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_sprint.return_value = {
            "id": "S-0001",
            "project_id": "proj",
            "status": "active",
        }
        db.get_sprint_prds.return_value = [
            {"id": "P-0001"},
            {"id": "P-0002"},
        ]
        # Coverage stats per PRD
        db.get_coverage_stats.side_effect = [
            {"total": 3, "linked": 2, "orphaned": 1, "by_type": {}},  # P-0001
            {"total": 2, "linked": 2, "orphaned": 0, "by_type": {}},  # P-0002
        ]
        # AC requirements per PRD
        db.get_requirements.side_effect = [
            [{"id": "ac1", "req_number": "AC-001"}],  # P-0001
            [{"id": "ac2", "req_number": "AC-001"}],  # P-0002
        ]
        # No linked tasks for ACs
        db.get_requirement_tasks.return_value = []
        # Challenge status -- no challenges
        db.get_challenge_status.return_value = {
            "total_rounds": 0, "latest_status": None,
            "open_count": 0, "closed_count": 0,
        }
        # Sprint tasks with no requirement links
        db.list_tasks_by_sprint.return_value = [
            {"id": "T1", "title": "Task 1", "prd_id": "P-0001"},
        ]
        db.get_task_requirements.return_value = []

        result = get_quality_report("sprint", sprint_id="S-0001")
        assert result["status"] == "ok"
        assert result["aggregate"]["total_requirements"] == 5
        assert result["aggregate"]["linked_requirements"] == 4
        assert result["aggregate"]["orphaned_requirements"] == 1
        assert result["aggregate"]["total_acs"] == 2
        assert len(result["prds"]) == 2

    @patch("a_sdlc.server.get_db")
    def test_challenge_stats(self, mock_get_db):
        """Should include challenge statistics (AC-016, FR-033)."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = [{"id": "P-0001"}]
        db.get_coverage_stats.return_value = {
            "total": 0, "linked": 0, "orphaned": 0, "by_type": {},
        }
        db.get_requirements.return_value = []

        # Challenge status: prd has challenges, design and split do not
        def challenge_status_side_effect(artifact_type, artifact_id):
            if artifact_type == "prd":
                return {
                    "total_rounds": 2, "latest_status": "closed",
                    "open_count": 0, "closed_count": 2,
                }
            return {
                "total_rounds": 0, "latest_status": None,
                "open_count": 0, "closed_count": 0,
            }

        db.get_challenge_status.side_effect = challenge_status_side_effect
        db.get_challenge_rounds.return_value = [
            {
                "round_number": 1,
                "status": "resolved",
                "objections": [
                    {"category": "gap", "text": "Missing req"},
                    {"category": "ambiguity", "text": "Unclear"},
                ],
                "verdict": json.dumps({
                    "resolved": ["Missing req"],
                    "accepted": ["Unclear"],
                    "escalated": [],
                }),
            },
            {
                "round_number": 2,
                "status": "resolved",
                "objections": [{"category": "gap", "text": "Another gap"}],
                "verdict": json.dumps({
                    "resolved": ["Another gap"],
                    "accepted": [],
                    "escalated": [],
                }),
            },
        ]
        db.list_tasks_by_sprint.return_value = []

        result = get_quality_report("sprint", sprint_id="S-0001")
        assert result["status"] == "ok"
        cs = result["challenge_stats"]
        assert cs["challenged"] == 1
        assert cs["unchallenged"] == 2
        assert cs["objections_by_category"]["gap"] == 2
        assert cs["objections_by_category"]["ambiguity"] == 1
        # Verdicts count individual items, not rounds
        assert cs["resolutions"]["resolved"] == 2  # "Missing req" + "Another gap"
        assert cs["resolutions"]["accepted"] == 1  # "Unclear"

    @patch("a_sdlc.server.get_db")
    def test_scope_drift(self, mock_get_db):
        """Should detect unlinked tasks as scope drift (AC-006)."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = [{"id": "P-0001"}]
        db.get_coverage_stats.return_value = {
            "total": 1, "linked": 1, "orphaned": 0, "by_type": {},
        }
        db.get_requirements.return_value = []
        db.get_challenge_status.return_value = {
            "total_rounds": 0, "latest_status": None,
            "open_count": 0, "closed_count": 0,
        }
        # Two tasks: one linked, one not
        db.list_tasks_by_sprint.return_value = [
            {"id": "T1", "title": "Linked task", "prd_id": "P-0001"},
            {"id": "T2", "title": "Orphan task", "prd_id": "P-0001"},
        ]
        db.get_task_requirements.side_effect = [
            [{"id": "r1"}],  # T1 is linked
            [],  # T2 has no links
        ]

        result = get_quality_report("sprint", sprint_id="S-0001")
        assert result["status"] == "ok"
        assert result["scope_drift"]["unlinked_count"] == 1
        assert result["scope_drift"]["unlinked_tasks"][0]["id"] == "T2"

    @patch("a_sdlc.server.get_db")
    def test_no_quality_data_backward_compat(self, mock_get_db):
        """Should return zeros gracefully when no quality data exists."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = []
        db.list_tasks_by_sprint.return_value = []

        result = get_quality_report("sprint", sprint_id="S-0001")
        assert result["status"] == "ok"
        assert result["aggregate"]["total_requirements"] == 0
        assert result["aggregate"]["coverage_pct"] == 100.0
        assert result["aggregate"]["verification_pct"] == 100.0
        assert result["challenge_stats"]["challenged"] == 0
        assert result["scope_drift"]["unlinked_count"] == 0
        assert result["pass"] is True

    @patch("a_sdlc.server.get_db")
    def test_pass_flag_true(self, mock_get_db):
        """Should set pass=True when coverage and verification are 100%."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = [{"id": "P-0001"}]
        db.get_coverage_stats.return_value = {
            "total": 1, "linked": 1, "orphaned": 0, "by_type": {},
        }
        db.get_requirements.return_value = [
            {"id": "ac1", "req_number": "AC-001"},
        ]
        db.get_requirement_tasks.return_value = [{"id": "T1"}]
        db.get_ac_verifications.return_value = [
            {"requirement_id": "ac1", "evidence_type": "test", "evidence": "ok"},
        ]
        db.get_challenge_status.return_value = {
            "total_rounds": 0, "latest_status": None,
            "open_count": 0, "closed_count": 0,
        }
        db.list_tasks_by_sprint.return_value = []

        result = get_quality_report("sprint", sprint_id="S-0001")
        assert result["status"] == "ok"
        assert result["pass"] is True

    @patch("a_sdlc.server.get_db")
    def test_pass_flag_false(self, mock_get_db):
        """Should set pass=False when coverage is incomplete."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = [{"id": "P-0001"}]
        db.get_coverage_stats.return_value = {
            "total": 2, "linked": 1, "orphaned": 1, "by_type": {},
        }
        db.get_requirements.return_value = []
        db.get_challenge_status.return_value = {
            "total_rounds": 0, "latest_status": None,
            "open_count": 0, "closed_count": 0,
        }
        db.list_tasks_by_sprint.return_value = []

        result = get_quality_report("sprint", sprint_id="S-0001")
        assert result["status"] == "ok"
        assert result["pass"] is False

    @patch("a_sdlc.server.get_db")
    def test_nonexistent_sprint(self, mock_get_db):
        """Should return error for non-existent sprint."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_sprint.return_value = None

        result = get_quality_report("sprint", sprint_id="NONEXISTENT")
        assert result["status"] == "error"
        assert "Sprint not found" in result["message"]

    @patch("a_sdlc.server.get_db")
    def test_performance_50_requirements(self, mock_get_db):
        """Should handle 50 requirements and return valid structure (NFR-003)."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = [{"id": "P-0001"}]
        # 50 requirements, all linked
        db.get_coverage_stats.return_value = {
            "total": 50, "linked": 50, "orphaned": 0, "by_type": {},
        }
        # 10 ACs among the 50
        ac_reqs = [
            {"id": f"ac{i}", "req_number": f"AC-{i:03d}"} for i in range(10)
        ]
        db.get_requirements.return_value = ac_reqs
        db.get_requirement_tasks.return_value = [{"id": "T1"}]
        db.get_ac_verifications.return_value = [
            {"requirement_id": "ac0", "evidence_type": "test", "evidence": "ok"},
        ]
        db.get_challenge_status.return_value = {
            "total_rounds": 0, "latest_status": None,
            "open_count": 0, "closed_count": 0,
        }
        db.list_tasks_by_sprint.return_value = []

        result = get_quality_report("sprint", sprint_id="S-0001")
        assert result["status"] == "ok"
        assert "aggregate" in result
        assert "challenge_stats" in result
        assert "scope_drift" in result
        assert "pass" in result

    @patch("a_sdlc.server.get_db")
    def test_effectiveness_in_sprint_report(self, mock_get_db):
        """Should include effectiveness metrics in challenge_stats."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = [{"id": "P-0001"}]
        db.get_coverage_stats.return_value = {
            "total": 0, "linked": 0, "orphaned": 0, "by_type": {},
        }
        db.get_requirements.return_value = []

        # prd artifact is challenged, design and split are not
        def challenge_status_side_effect(artifact_type, artifact_id):
            if artifact_type == "prd":
                return {
                    "total_rounds": 2, "latest_status": "resolved",
                    "open_count": 0, "closed_count": 2,
                }
            return {
                "total_rounds": 0, "latest_status": None,
                "open_count": 0, "closed_count": 0,
            }

        db.get_challenge_status.side_effect = challenge_status_side_effect
        db.get_challenge_rounds.return_value = [
            {
                "round_number": 1,
                "status": "resolved",
                "objections": [{"category": "gap", "text": "A"}],
                "verdict": json.dumps({
                    "resolved": ["A"], "accepted": [], "escalated": [],
                }),
            },
            {
                "round_number": 2,
                "status": "resolved",
                "objections": [{"category": "gap", "text": "B"}],
                "verdict": json.dumps({
                    "resolved": ["B"], "accepted": [], "escalated": [],
                }),
            },
        ]
        db.list_tasks_by_sprint.return_value = []

        result = get_quality_report("sprint", sprint_id="S-0001")
        assert result["status"] == "ok"
        eff = result["challenge_stats"]["effectiveness"]
        assert eff["first_round_resolution_rate"] == 1.0  # 1 first-round resolved / 1 challenged
        assert eff["escalation_rate"] == 0.0
        assert eff["auto_termination_rate"] == 0.0
        assert eff["avg_rounds_per_artifact"] == 2.0  # 2 rounds / 1 challenged
        assert eff["total_objections"] == 2
        assert eff["resolution_rate"] == 1.0  # 2 resolved / 2 objections

    @patch("a_sdlc.server.get_db")
    def test_verdict_resolution_counts_items(self, mock_get_db):
        """Verdict resolution should count individual items, not rounds."""
        db = MagicMock()
        mock_get_db.return_value = db

        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = [{"id": "P-0001"}]
        db.get_coverage_stats.return_value = {
            "total": 0, "linked": 0, "orphaned": 0, "by_type": {},
        }
        db.get_requirements.return_value = []

        def challenge_status_side_effect(artifact_type, artifact_id):
            if artifact_type == "prd":
                return {
                    "total_rounds": 1, "latest_status": "resolved",
                    "open_count": 0, "closed_count": 1,
                }
            return {
                "total_rounds": 0, "latest_status": None,
                "open_count": 0, "closed_count": 0,
            }

        db.get_challenge_status.side_effect = challenge_status_side_effect
        db.get_challenge_rounds.return_value = [
            {
                "round_number": 1,
                "status": "resolved",
                "objections": [
                    {"category": "gap", "text": "A"},
                    {"category": "gap", "text": "B"},
                    {"category": "ambiguity", "text": "C"},
                ],
                "verdict": json.dumps({
                    "resolved": ["A", "B"],
                    "accepted": ["C"],
                    "escalated": [],
                }),
            },
        ]
        db.list_tasks_by_sprint.return_value = []

        result = get_quality_report("sprint", sprint_id="S-0001")
        assert result["status"] == "ok"
        res = result["challenge_stats"]["resolutions"]
        # Should count individual items, not rounds
        assert res["resolved"] == 2  # A, B
        assert res["accepted"] == 1  # C
        assert res["escalated"] == 0


# =============================================================================
# REQ_PATTERN Regex Tests (SDLC-T00164)
# =============================================================================


class TestReqPatternRegex:
    """Test REQ_PATTERN regex against various markdown format variations."""

    def test_standard_bullet_colon(self):
        """Regex matches standard format: '- FR-001: description'."""
        text = "- FR-001: Users can log in via SSO"
        matches = REQ_PATTERN.findall(text)
        assert len(matches) == 1
        assert matches[0][0] == "FR-001"
        assert matches[0][1].strip() == "Users can log in via SSO"

    def test_bold_format(self):
        """Regex matches bold format: '**FR-001**: description'."""
        text = "**FR-002**: System stores audit logs"
        matches = REQ_PATTERN.findall(text)
        assert len(matches) == 1
        assert matches[0][0] == "FR-002"
        assert matches[0][1].strip() == "System stores audit logs"

    def test_dash_separator(self):
        """Regex matches dash separator: '- FR-001 - description'."""
        text = "- FR-003 - Agents hitting budget limits are paused"
        matches = REQ_PATTERN.findall(text)
        assert len(matches) == 1
        assert matches[0][0] == "FR-003"
        assert matches[0][1].strip() == "Agents hitting budget limits are paused"

    def test_nfr_prefix(self):
        """Regex matches NFR prefixed requirements."""
        text = "- NFR-001: Response time under 200ms"
        matches = REQ_PATTERN.findall(text)
        assert len(matches) == 1
        assert matches[0][0] == "NFR-001"

    def test_ac_prefix(self):
        """Regex matches AC prefixed requirements."""
        text = "* AC-005: All 18 requirements are parsed"
        matches = REQ_PATTERN.findall(text)
        assert len(matches) == 1
        assert matches[0][0] == "AC-005"

    def test_bullet_bold_combo(self):
        """Regex matches bullet + bold: '- **FR-001**: description'."""
        text = "- **FR-004**: Dashboard shows real-time metrics"
        matches = REQ_PATTERN.findall(text)
        assert len(matches) == 1
        assert matches[0][0] == "FR-004"

    def test_no_bullet(self):
        """Regex matches without a leading bullet."""
        text = "FR-010: Standalone requirement"
        matches = REQ_PATTERN.findall(text)
        assert len(matches) == 1
        assert matches[0][0] == "FR-010"

    def test_multiline_extraction(self):
        """Regex extracts multiple requirements from multiline text."""
        text = """## Requirements
- FR-001: First requirement
- NFR-001: Non-functional requirement
- AC-001: Acceptance criterion
"""
        matches = REQ_PATTERN.findall(text)
        assert len(matches) == 3
        ids = [m[0] for m in matches]
        assert ids == ["FR-001", "NFR-001", "AC-001"]

    def test_no_match_for_invalid_prefix(self):
        """Regex does not match non-standard prefixes like REQ-001."""
        text = "- REQ-001: This should not match"
        matches = REQ_PATTERN.findall(text)
        assert len(matches) == 0


# =============================================================================
# classify_depth Tests (SDLC-T00164)
# =============================================================================


class TestClassifyDepth:
    """Test classify_depth deterministic keyword classification."""

    def test_behavioral_enforce(self):
        """Text with 'enforce' should classify as behavioral."""
        assert classify_depth("System must enforce rate limits") == "behavioral"

    def test_behavioral_block(self):
        """Text with 'block' should classify as behavioral."""
        assert classify_depth("Block unauthorized access attempts") == "behavioral"

    def test_behavioral_pause(self):
        """Text with 'pause' should classify as behavioral (AC-008)."""
        assert classify_depth("Agents hitting budget limits are paused") == "behavioral"

    def test_behavioral_reject(self):
        """Text with 'reject' should classify as behavioral."""
        assert classify_depth("Reject invalid input data") == "behavioral"

    def test_integration_depends_on(self):
        """Text with 'depends on' should classify as integration."""
        assert classify_depth("This feature depends on the auth service") == "integration"

    def test_integration_integrates_with(self):
        """Text with 'integrates with' should classify as integration."""
        assert classify_depth("System integrates with Linear API") == "integration"

    def test_structural_table(self):
        """Text with 'table' should classify as structural (AC-008)."""
        assert classify_depth("agents table with columns X, Y") == "structural"

    def test_structural_column(self):
        """Text with 'column' should classify as structural."""
        assert classify_depth("Add status column to tasks") == "structural"

    def test_structural_schema(self):
        """Text with 'schema' should classify as structural."""
        assert classify_depth("Define database schema for requirements") == "structural"

    def test_default_structural(self):
        """Text with no matching keywords should default to structural."""
        assert classify_depth("Users can see a dashboard overview") == "structural"

    def test_ambiguity_behavioral_wins_over_structural(self):
        """When text matches both behavioral + structural, behavioral wins."""
        # "enforce" (behavioral) + "table" (structural) -> behavioral
        text = "Enforce access control on the users table"
        assert classify_depth(text) == "behavioral"

    def test_deterministic_same_input_same_output(self):
        """Same text must always produce the same classification."""
        text = "System must validate all API inputs"
        results = {classify_depth(text) for _ in range(100)}
        assert len(results) == 1
        assert results.pop() == "behavioral"

    def test_case_insensitive(self):
        """Classification should be case-insensitive."""
        assert classify_depth("ENFORCE strict limits") == "behavioral"
        assert classify_depth("Depends On external service") == "integration"

    def test_keyword_sets_are_frozensets(self):
        """Keyword sets should be frozensets (immutable)."""
        assert isinstance(BEHAVIORAL_KEYWORDS, frozenset)
        assert isinstance(INTEGRATION_KEYWORDS, frozenset)
        assert isinstance(STRUCTURAL_KEYWORDS, frozenset)


# =============================================================================
# parse_requirements MCP Tool Tests (SDLC-T00164)
# =============================================================================


class TestParseRequirements:
    """Test parse_requirements MCP tool end-to-end behavior."""

    PRD_CONTENT = """# Test PRD

## Functional Requirements

- FR-001: Users can log in via SSO
- **FR-002**: System stores audit logs in a table
- FR-003 - Agents hitting budget limits are paused

## Non-Functional Requirements

- NFR-001: Response time under 200ms
- NFR-002: System integrates with Linear for sync

## Acceptance Criteria

- AC-001: All requirements are parsed correctly
- AC-002: Depth classification is deterministic
"""

    def _mock_prd(self, content=None):
        """Create mock PRD metadata."""
        return {
            "id": "TEST-P0001",
            "project_id": "test-project",
            "file_path": "/tmp/test/prds/TEST-P0001.md",
            "title": "Test PRD",
        }

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_parse_returns_correct_counts(self, mock_get_db, mock_get_cm, mock_get_storage):
        """parse_requirements should return correct FR/NFR/AC counts."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = self._mock_prd()
        mock_get_db.return_value = mock_db

        mock_cm = MagicMock()
        mock_cm.read_content.return_value = self.PRD_CONTENT
        mock_get_cm.return_value = mock_cm

        mock_storage = MagicMock()
        mock_storage.delete_requirements.return_value = 0
        mock_storage.upsert_requirement.return_value = {}
        mock_get_storage.return_value = mock_storage

        result = parse_requirements("TEST-P0001")
        assert result["status"] == "ok"
        assert result["counts"]["FR"] == 3
        assert result["counts"]["NFR"] == 2
        assert result["counts"]["AC"] == 2
        assert result["total"] == 7

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_parse_returns_requirement_details(self, mock_get_db, mock_get_cm, mock_get_storage):
        """parse_requirements should return requirement details with depth."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = self._mock_prd()
        mock_get_db.return_value = mock_db

        mock_cm = MagicMock()
        mock_cm.read_content.return_value = self.PRD_CONTENT
        mock_get_cm.return_value = mock_cm

        mock_storage = MagicMock()
        mock_storage.delete_requirements.return_value = 0
        mock_storage.upsert_requirement.return_value = {}
        mock_get_storage.return_value = mock_storage

        result = parse_requirements("TEST-P0001")
        reqs = result["requirements"]
        assert len(reqs) == 7

        # FR-003 should be behavioral ("paused" triggers "pause" check -- wait,
        # actually "paused" contains "pause" -- yes it does)
        fr3 = next(r for r in reqs if r["req_number"] == "FR-003")
        assert fr3["depth"] == "behavioral"

        # NFR-002 should be integration ("integrates with")
        nfr2 = next(r for r in reqs if r["req_number"] == "NFR-002")
        assert nfr2["depth"] == "integration"

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_parse_calls_upsert_for_each_requirement(self, mock_get_db, mock_get_cm, mock_get_storage):
        """parse_requirements should call upsert_requirement for each extracted req."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = self._mock_prd()
        mock_get_db.return_value = mock_db

        mock_cm = MagicMock()
        mock_cm.read_content.return_value = self.PRD_CONTENT
        mock_get_cm.return_value = mock_cm

        mock_storage = MagicMock()
        mock_storage.delete_requirements.return_value = 0
        mock_storage.upsert_requirement.return_value = {}
        mock_get_storage.return_value = mock_storage

        parse_requirements("TEST-P0001")

        # Should have called delete_requirements once then upsert 7 times
        mock_storage.delete_requirements.assert_called_once_with("TEST-P0001")
        assert mock_storage.upsert_requirement.call_count == 7

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_idempotent_reparse(self, mock_get_db, mock_get_cm, mock_get_storage):
        """Re-running parse_requirements should delete then re-insert (no duplicates)."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = self._mock_prd()
        mock_get_db.return_value = mock_db

        mock_cm = MagicMock()
        mock_cm.read_content.return_value = "- FR-001: Single requirement"
        mock_get_cm.return_value = mock_cm

        mock_storage = MagicMock()
        mock_storage.delete_requirements.return_value = 0
        mock_storage.upsert_requirement.return_value = {}
        mock_get_storage.return_value = mock_storage

        # First parse
        result1 = parse_requirements("TEST-P0001")
        assert result1["total"] == 1

        # Second parse (idempotent)
        mock_storage.reset_mock()
        mock_storage.delete_requirements.return_value = 1  # Had 1 existing
        result2 = parse_requirements("TEST-P0001")
        assert result2["total"] == 1
        mock_storage.delete_requirements.assert_called_once_with("TEST-P0001")
        assert mock_storage.upsert_requirement.call_count == 1

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_prd_not_found(self, mock_get_db, mock_get_cm):
        """parse_requirements should return not_found for nonexistent PRD."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = None
        mock_get_db.return_value = mock_db

        result = parse_requirements("NONEXISTENT-P9999")
        assert result["status"] == "not_found"
        assert "not found" in result["message"].lower()

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_empty_prd_content(self, mock_get_db, mock_get_cm, mock_get_storage):
        """parse_requirements on empty PRD should return zero counts."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = self._mock_prd()
        mock_get_db.return_value = mock_db

        mock_cm = MagicMock()
        mock_cm.read_content.return_value = None
        mock_get_cm.return_value = mock_cm

        result = parse_requirements("TEST-P0001")
        assert result["status"] == "ok"
        assert result["total"] == 0
        assert result["requirements"] == []

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_no_matching_patterns(self, mock_get_db, mock_get_cm, mock_get_storage):
        """PRD with no FR/NFR/AC patterns should return empty list."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = self._mock_prd()
        mock_get_db.return_value = mock_db

        mock_cm = MagicMock()
        mock_cm.read_content.return_value = "# Just a title\n\nSome plain text here."
        mock_get_cm.return_value = mock_cm

        mock_storage = MagicMock()
        mock_storage.delete_requirements.return_value = 0
        mock_get_storage.return_value = mock_storage

        result = parse_requirements("TEST-P0001")
        assert result["status"] == "ok"
        assert result["total"] == 0
        assert result["requirements"] == []

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_unrecognized_candidates(self, mock_get_db, mock_get_cm, mock_get_storage):
        """Non-standard identifiers should appear in unrecognized_candidates."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = self._mock_prd()
        mock_get_db.return_value = mock_db

        mock_cm = MagicMock()
        mock_cm.read_content.return_value = (
            "- FR-001: Valid requirement\n"
            "- REQ-001: Non-standard identifier\n"
        )
        mock_get_cm.return_value = mock_cm

        mock_storage = MagicMock()
        mock_storage.delete_requirements.return_value = 0
        mock_storage.upsert_requirement.return_value = {}
        mock_get_storage.return_value = mock_storage

        result = parse_requirements("TEST-P0001")
        assert result["total"] == 1  # Only FR-001
        assert len(result["unrecognized_candidates"]) == 1
        assert result["unrecognized_candidates"][0]["id"] == "REQ-001"

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_requirement_id_format(self, mock_get_db, mock_get_cm, mock_get_storage):
        """Requirement IDs should follow '{prd_id}:{req_number}' format."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = self._mock_prd()
        mock_get_db.return_value = mock_db

        mock_cm = MagicMock()
        mock_cm.read_content.return_value = "- FR-001: Test requirement"
        mock_get_cm.return_value = mock_cm

        mock_storage = MagicMock()
        mock_storage.delete_requirements.return_value = 0
        mock_storage.upsert_requirement.return_value = {}
        mock_get_storage.return_value = mock_storage

        result = parse_requirements("TEST-P0001")
        assert result["requirements"][0]["id"] == "TEST-P0001:FR-001"

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_exception_returns_error(self, mock_get_db, mock_get_cm):
        """Exceptions should be caught and returned as error status."""
        mock_db = MagicMock()
        mock_db.get_prd.side_effect = RuntimeError("DB connection lost")
        mock_get_db.return_value = mock_db

        result = parse_requirements("TEST-P0001")
        assert result["status"] == "error"
        assert "DB connection lost" in result["message"]

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_duplicate_req_in_content_deduplicated(self, mock_get_db, mock_get_cm, mock_get_storage):
        """If the same FR-001 appears twice in content, it should be deduplicated."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = self._mock_prd()
        mock_get_db.return_value = mock_db

        mock_cm = MagicMock()
        mock_cm.read_content.return_value = (
            "- FR-001: First occurrence\n"
            "- FR-001: Duplicate occurrence\n"
        )
        mock_get_cm.return_value = mock_cm

        mock_storage = MagicMock()
        mock_storage.delete_requirements.return_value = 0
        mock_storage.upsert_requirement.return_value = {}
        mock_get_storage.return_value = mock_storage

        result = parse_requirements("TEST-P0001")
        assert result["total"] == 1
        assert mock_storage.upsert_requirement.call_count == 1


class TestCandidatePattern:
    """Test the _CANDIDATE_PATTERN for unrecognized requirement detection."""

    def test_matches_req_prefix(self):
        """_CANDIDATE_PATTERN should match REQ-001 style identifiers."""
        matches = _CANDIDATE_PATTERN.findall("- REQ-001: Some text")
        assert len(matches) == 1
        assert matches[0][0] == "REQ-001"

    def test_does_not_match_fr_prefix(self):
        """_CANDIDATE_PATTERN should not match FR/NFR/AC (those are standard)."""
        # FR, NFR, AC are handled by REQ_PATTERN, not _CANDIDATE_PATTERN
        matches = _CANDIDATE_PATTERN.findall("- FR-001: Standard req")
        assert len(matches) == 0


# =============================================================================
# AC Verification Gate in update_task (SDLC-T00167)
# =============================================================================


class TestUpdateTaskAcGate:
    """Test the AC verification gate in update_task MCP tool."""

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_unverified_acs_blocks_completion(
        self, mock_get_db, mock_quality_cfg, mock_review_cfg
    ):
        """Task with unverified ACs returns blocked status (AC-003)."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001", "status": "in_progress"}
        # Review gate passes
        mock_review_cfg.return_value = MagicMock(enabled=False)
        # Quality gate enabled
        mock_quality_cfg.return_value = QualityConfig(enabled=True, ac_gate=True)
        db.get_unverified_acs.return_value = [
            {"id": "R1", "summary": "Must handle errors", "depth": "structural"},
            {"id": "R2", "summary": "Must log events", "depth": "behavioral"},
        ]

        from a_sdlc.server import update_task

        result = update_task(task_id="T-001", status="completed")

        assert result["status"] == "blocked"
        assert result["reason"] == "unverified_acceptance_criteria"
        assert len(result["unverified"]) == 2
        assert result["unverified"][0]["ac_id"] == "R1"
        assert result["unverified"][1]["ac_id"] == "R2"
        # Must NOT have called update_task on the database
        db.update_task.assert_not_called()

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_all_acs_verified_allows_completion(
        self, mock_get_db, mock_quality_cfg, mock_review_cfg
    ):
        """Task completes after all ACs verified (AC-004)."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001", "status": "in_progress"}
        mock_review_cfg.return_value = MagicMock(enabled=False)
        mock_quality_cfg.return_value = QualityConfig(enabled=True, ac_gate=True)
        db.get_unverified_acs.return_value = []  # All verified
        db.update_task.return_value = {"id": "T-001", "status": "completed"}

        from a_sdlc.server import update_task

        result = update_task(task_id="T-001", status="completed")

        assert result["status"] == "updated"
        db.update_task.assert_called_once()

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_no_linked_acs_allows_completion(
        self, mock_get_db, mock_quality_cfg, mock_review_cfg
    ):
        """Task with no linked ACs completes normally (no false positives)."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001", "status": "in_progress"}
        mock_review_cfg.return_value = MagicMock(enabled=False)
        mock_quality_cfg.return_value = QualityConfig(enabled=True, ac_gate=True)
        db.get_unverified_acs.return_value = []  # No linked ACs at all
        db.update_task.return_value = {"id": "T-001", "status": "completed"}

        from a_sdlc.server import update_task

        result = update_task(task_id="T-001", status="completed")

        assert result["status"] == "updated"

    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.get_db")
    def test_no_quality_config_does_not_gate(
        self, mock_get_db, mock_review_cfg, mock_quality_cfg
    ):
        """No behavior change without quality config (AC-007 -- fail-open)."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001", "status": "in_progress"}
        mock_review_cfg.return_value = MagicMock(enabled=False)
        # Simulate config loading failure (e.g. missing yaml)
        mock_quality_cfg.side_effect = FileNotFoundError("config.yaml not found")
        db.update_task.return_value = {"id": "T-001", "status": "completed"}

        from a_sdlc.server import update_task

        result = update_task(task_id="T-001", status="completed")

        assert result["status"] == "updated"
        db.update_task.assert_called_once()

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_quality_disabled_does_not_gate(
        self, mock_get_db, mock_quality_cfg, mock_review_cfg
    ):
        """Gate does not fire when quality.enabled=false."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001", "status": "in_progress"}
        mock_review_cfg.return_value = MagicMock(enabled=False)
        mock_quality_cfg.return_value = QualityConfig(enabled=False, ac_gate=True)
        db.update_task.return_value = {"id": "T-001", "status": "completed"}

        from a_sdlc.server import update_task

        result = update_task(task_id="T-001", status="completed")

        assert result["status"] == "updated"
        # get_unverified_acs should NOT have been called
        db.get_unverified_acs.assert_not_called()

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_ac_gate_disabled_does_not_gate(
        self, mock_get_db, mock_quality_cfg, mock_review_cfg
    ):
        """Gate does not fire when quality.ac_gate=false (even if enabled)."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001", "status": "in_progress"}
        mock_review_cfg.return_value = MagicMock(enabled=False)
        mock_quality_cfg.return_value = QualityConfig(enabled=True, ac_gate=False)
        db.update_task.return_value = {"id": "T-001", "status": "completed"}

        from a_sdlc.server import update_task

        result = update_task(task_id="T-001", status="completed")

        assert result["status"] == "updated"
        db.get_unverified_acs.assert_not_called()

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_non_completion_status_skips_gate(
        self, mock_get_db, mock_quality_cfg, mock_review_cfg
    ):
        """Gate does not fire for non-completion status changes (e.g. in_progress)."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001", "status": "pending"}
        db.update_task.return_value = {"id": "T-001", "status": "in_progress"}

        from a_sdlc.server import update_task

        result = update_task(task_id="T-001", status="in_progress")

        assert result["status"] == "updated"
        # Neither config loader nor get_unverified_acs should be called
        mock_quality_cfg.assert_not_called()
        db.get_unverified_acs.assert_not_called()

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_blocked_response_lists_all_unverified(
        self, mock_get_db, mock_quality_cfg, mock_review_cfg
    ):
        """Blocked response includes details of all unverified ACs."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001", "status": "in_progress"}
        mock_review_cfg.return_value = MagicMock(enabled=False)
        mock_quality_cfg.return_value = QualityConfig(enabled=True, ac_gate=True)
        db.get_unverified_acs.return_value = [
            {"id": "R1", "summary": "Error handling", "depth": "structural"},
            {"id": "R2", "summary": "Logging", "depth": "behavioral"},
            {"id": "R3", "summary": "Performance", "depth": "structural"},
        ]

        from a_sdlc.server import update_task

        result = update_task(task_id="T-001", status="completed")

        assert result["status"] == "blocked"
        assert len(result["unverified"]) == 3
        summaries = [u["summary"] for u in result["unverified"]]
        assert "Error handling" in summaries
        assert "Logging" in summaries
        assert "Performance" in summaries

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_blocked_status_not_error(
        self, mock_get_db, mock_quality_cfg, mock_review_cfg
    ):
        """Gate failure returns 'blocked' status, not 'error'."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001", "status": "in_progress"}
        mock_review_cfg.return_value = MagicMock(enabled=False)
        mock_quality_cfg.return_value = QualityConfig(enabled=True, ac_gate=True)
        db.get_unverified_acs.return_value = [
            {"id": "R1", "summary": "AC 1", "depth": "structural"},
        ]

        from a_sdlc.server import update_task

        result = update_task(task_id="T-001", status="completed")

        assert result["status"] == "blocked"
        assert result["status"] != "error"

    @patch("a_sdlc.server.load_review_config")
    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_config_exception_is_caught_gracefully(
        self, mock_get_db, mock_quality_cfg, mock_review_cfg
    ):
        """Config loading exception is caught gracefully (fail-open)."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001", "status": "in_progress"}
        mock_review_cfg.return_value = MagicMock(enabled=False)
        # Simulate unexpected exception during config load
        mock_quality_cfg.side_effect = RuntimeError("Unexpected YAML parse error")
        db.update_task.return_value = {"id": "T-001", "status": "completed"}

        from a_sdlc.server import update_task

        result = update_task(task_id="T-001", status="completed")

        # Should complete despite config failure (fail-open)
        assert result["status"] == "updated"
        db.update_task.assert_called_once()


# =============================================================================
# verify_acceptance_criteria MCP Tool Tests (SDLC-T00166)
# =============================================================================


class TestVerifyAcceptanceCriteria:
    """Tests for the verify_acceptance_criteria MCP tool."""

    def _make_ac_req(self, ac_id="TEST-P0001:AC-001", depth="structural"):
        """Helper: create a mock AC requirement dict."""
        return {
            "id": ac_id,
            "prd_id": "TEST-P0001",
            "req_type": "AC",
            "req_number": "AC-001",
            "summary": "Test AC",
            "depth": depth,
        }

    @patch("a_sdlc.server._load_quality_config_safe")
    @patch("a_sdlc.server.get_db")
    def test_valid_verification_records_evidence(
        self, mock_get_db, mock_qcfg
    ):
        """Valid verification should record evidence and return ok."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_qcfg.return_value = None  # no quality config

        ac_id = "TEST-P0001:AC-001"
        task_id = "TEST-T00001"
        db.get_requirement.return_value = self._make_ac_req(ac_id)
        db.get_task_requirements.return_value = [{"id": ac_id}]
        db.record_ac_verification.return_value = {
            "id": 1,
            "requirement_id": ac_id,
            "task_id": task_id,
            "verified_by": "mcp_tool",
            "evidence_type": "test",
            "evidence": "All tests pass",
        }

        from a_sdlc.server import verify_acceptance_criteria

        result = verify_acceptance_criteria(
            task_id=task_id,
            ac_id=ac_id,
            evidence_type="test",
            evidence="All tests pass",
        )

        assert result["status"] == "ok"
        assert result["verification"]["ac_id"] == ac_id
        assert result["verification"]["task_id"] == task_id
        assert result["verification"]["evidence_type"] == "test"
        assert result["verification"]["evidence"] == "All tests pass"
        db.record_ac_verification.assert_called_once_with(
            requirement_id=ac_id,
            task_id=task_id,
            verified_by="mcp_tool",
            evidence_type="test",
            evidence="All tests pass",
        )

    @patch("a_sdlc.server._load_quality_config_safe")
    @patch("a_sdlc.server.get_db")
    def test_invalid_evidence_type_returns_error(
        self, mock_get_db, mock_qcfg
    ):
        """Invalid evidence_type should return an error."""
        mock_qcfg.return_value = None

        from a_sdlc.server import verify_acceptance_criteria

        result = verify_acceptance_criteria(
            task_id="TEST-T00001",
            ac_id="TEST-P0001:AC-001",
            evidence_type="screenshot",
            evidence="Looks good",
        )

        assert result["status"] == "error"
        assert "Invalid evidence_type" in result["message"]
        assert "screenshot" in result["message"]

    @patch("a_sdlc.server._load_quality_config_safe")
    @patch("a_sdlc.server.get_db")
    def test_nonexistent_ac_id_returns_error(
        self, mock_get_db, mock_qcfg
    ):
        """Non-existent ac_id should return an error."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_qcfg.return_value = None
        db.get_requirement.return_value = None

        from a_sdlc.server import verify_acceptance_criteria

        result = verify_acceptance_criteria(
            task_id="TEST-T00001",
            ac_id="NONEXISTENT:AC-999",
            evidence_type="test",
            evidence="All tests pass",
        )

        assert result["status"] == "error"
        assert "Requirement not found" in result["message"]

    @patch("a_sdlc.server._load_quality_config_safe")
    @patch("a_sdlc.server.get_db")
    def test_non_ac_requirement_returns_error(
        self, mock_get_db, mock_qcfg
    ):
        """Requirement that is not an AC (e.g., FR) should return an error."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_qcfg.return_value = None
        db.get_requirement.return_value = {
            "id": "TEST-P0001:FR-001",
            "prd_id": "TEST-P0001",
            "req_type": "functional",
            "req_number": "FR-001",
            "summary": "Functional req",
            "depth": "structural",
        }

        from a_sdlc.server import verify_acceptance_criteria

        result = verify_acceptance_criteria(
            task_id="TEST-T00001",
            ac_id="TEST-P0001:FR-001",
            evidence_type="test",
            evidence="Tests pass",
        )

        assert result["status"] == "error"
        assert "is not an AC" in result["message"]
        assert "functional" in result["message"]

    @patch("a_sdlc.server._load_quality_config_safe")
    @patch("a_sdlc.server.get_db")
    def test_task_not_linked_to_ac_returns_error(
        self, mock_get_db, mock_qcfg
    ):
        """Task not linked to the AC should return an error."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_qcfg.return_value = None

        ac_id = "TEST-P0001:AC-001"
        db.get_requirement.return_value = self._make_ac_req(ac_id)
        # Task has different requirement linked
        db.get_task_requirements.return_value = [{"id": "OTHER:AC-999"}]

        from a_sdlc.server import verify_acceptance_criteria

        result = verify_acceptance_criteria(
            task_id="TEST-T00001",
            ac_id=ac_id,
            evidence_type="test",
            evidence="Tests pass",
        )

        assert result["status"] == "error"
        assert "is not linked to" in result["message"]

    @patch("a_sdlc.server._load_quality_config_safe")
    @patch("a_sdlc.server.get_db")
    def test_behavioral_ac_rejects_manual_when_strict(
        self, mock_get_db, mock_qcfg
    ):
        """Behavioral AC should reject manual evidence when behavioral_test_required=true (AC-005)."""
        db = MagicMock()
        mock_get_db.return_value = db

        # Quality config with behavioral strictness enabled
        mock_qcfg.return_value = MagicMock(
            enabled=True, behavioral_test_required=True
        )

        ac_id = "TEST-P0001:AC-001"
        db.get_requirement.return_value = self._make_ac_req(
            ac_id, depth="behavioral"
        )
        db.get_task_requirements.return_value = [{"id": ac_id}]

        from a_sdlc.server import verify_acceptance_criteria

        result = verify_acceptance_criteria(
            task_id="TEST-T00001",
            ac_id=ac_id,
            evidence_type="manual",
            evidence="Checked manually",
        )

        assert result["status"] == "error"
        assert "requires test evidence" in result["message"]
        assert "manual" in result["message"]
        # Should NOT have recorded verification
        db.record_ac_verification.assert_not_called()

    @patch("a_sdlc.server._load_quality_config_safe")
    @patch("a_sdlc.server.get_db")
    def test_behavioral_ac_rejects_demo_when_strict(
        self, mock_get_db, mock_qcfg
    ):
        """Behavioral AC should also reject demo evidence when strict."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_qcfg.return_value = MagicMock(
            enabled=True, behavioral_test_required=True
        )

        ac_id = "TEST-P0001:AC-001"
        db.get_requirement.return_value = self._make_ac_req(
            ac_id, depth="behavioral"
        )
        db.get_task_requirements.return_value = [{"id": ac_id}]

        from a_sdlc.server import verify_acceptance_criteria

        result = verify_acceptance_criteria(
            task_id="TEST-T00001",
            ac_id=ac_id,
            evidence_type="demo",
            evidence="Demo recorded",
        )

        assert result["status"] == "error"
        assert "requires test evidence" in result["message"]

    @patch("a_sdlc.server._load_quality_config_safe")
    @patch("a_sdlc.server.get_db")
    def test_behavioral_ac_accepts_test_evidence(
        self, mock_get_db, mock_qcfg
    ):
        """Behavioral AC with evidence_type='test' should be accepted."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_qcfg.return_value = MagicMock(
            enabled=True, behavioral_test_required=True
        )

        ac_id = "TEST-P0001:AC-001"
        db.get_requirement.return_value = self._make_ac_req(
            ac_id, depth="behavioral"
        )
        db.get_task_requirements.return_value = [{"id": ac_id}]
        db.record_ac_verification.return_value = {"id": 1}

        from a_sdlc.server import verify_acceptance_criteria

        result = verify_acceptance_criteria(
            task_id="TEST-T00001",
            ac_id=ac_id,
            evidence_type="test",
            evidence="pytest: 42 passed",
        )

        assert result["status"] == "ok"
        db.record_ac_verification.assert_called_once()

    @patch("a_sdlc.server._load_quality_config_safe")
    @patch("a_sdlc.server.get_db")
    def test_structural_ac_accepts_manual_when_strict(
        self, mock_get_db, mock_qcfg
    ):
        """Non-behavioral (structural) AC should accept manual evidence even when strict."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_qcfg.return_value = MagicMock(
            enabled=True, behavioral_test_required=True
        )

        ac_id = "TEST-P0001:AC-001"
        db.get_requirement.return_value = self._make_ac_req(
            ac_id, depth="structural"
        )
        db.get_task_requirements.return_value = [{"id": ac_id}]
        db.record_ac_verification.return_value = {"id": 1}

        from a_sdlc.server import verify_acceptance_criteria

        result = verify_acceptance_criteria(
            task_id="TEST-T00001",
            ac_id=ac_id,
            evidence_type="manual",
            evidence="Verified manually",
        )

        assert result["status"] == "ok"
        db.record_ac_verification.assert_called_once()

    @patch("a_sdlc.server._load_quality_config_safe")
    @patch("a_sdlc.server.get_db")
    def test_no_quality_config_accepts_all_evidence(
        self, mock_get_db, mock_qcfg
    ):
        """When quality config is absent (None), all evidence types are accepted (AC-007)."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_qcfg.return_value = None  # No quality config

        ac_id = "TEST-P0001:AC-001"
        db.get_requirement.return_value = self._make_ac_req(
            ac_id, depth="behavioral"
        )
        db.get_task_requirements.return_value = [{"id": ac_id}]
        db.record_ac_verification.return_value = {"id": 1}

        from a_sdlc.server import verify_acceptance_criteria

        result = verify_acceptance_criteria(
            task_id="TEST-T00001",
            ac_id=ac_id,
            evidence_type="manual",
            evidence="Checked manually -- no config so should pass",
        )

        assert result["status"] == "ok"
        db.record_ac_verification.assert_called_once()

    @patch("a_sdlc.server._load_quality_config_safe")
    @patch("a_sdlc.server.get_db")
    def test_re_verification_overwrites_previous(
        self, mock_get_db, mock_qcfg
    ):
        """Re-verification should call record_ac_verification again (INSERT OR REPLACE)."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_qcfg.return_value = None

        ac_id = "TEST-P0001:AC-001"
        db.get_requirement.return_value = self._make_ac_req(ac_id)
        db.get_task_requirements.return_value = [{"id": ac_id}]
        db.record_ac_verification.return_value = {"id": 1}

        from a_sdlc.server import verify_acceptance_criteria

        # First verification
        result1 = verify_acceptance_criteria(
            task_id="TEST-T00001",
            ac_id=ac_id,
            evidence_type="manual",
            evidence="First pass",
        )
        assert result1["status"] == "ok"

        # Second verification (overwrite)
        result2 = verify_acceptance_criteria(
            task_id="TEST-T00001",
            ac_id=ac_id,
            evidence_type="test",
            evidence="Second pass -- with tests now",
        )
        assert result2["status"] == "ok"
        assert result2["verification"]["evidence_type"] == "test"
        assert db.record_ac_verification.call_count == 2

    @patch("a_sdlc.server._load_quality_config_safe")
    @patch("a_sdlc.server.get_db")
    def test_quality_config_disabled_accepts_all(
        self, mock_get_db, mock_qcfg
    ):
        """When quality config exists but enabled=False, all evidence types pass."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_qcfg.return_value = MagicMock(
            enabled=False, behavioral_test_required=True
        )

        ac_id = "TEST-P0001:AC-001"
        db.get_requirement.return_value = self._make_ac_req(
            ac_id, depth="behavioral"
        )
        db.get_task_requirements.return_value = [{"id": ac_id}]
        db.record_ac_verification.return_value = {"id": 1}

        from a_sdlc.server import verify_acceptance_criteria

        result = verify_acceptance_criteria(
            task_id="TEST-T00001",
            ac_id=ac_id,
            evidence_type="manual",
            evidence="Manual but config disabled",
        )

        assert result["status"] == "ok"
        db.record_ac_verification.assert_called_once()


# =============================================================================
# Requirement Linkage MCP Tool Tests (SDLC-T00165)
# =============================================================================


class TestLinkTaskRequirementsMCP:
    """Test the link_task_requirements MCP tool."""

    @patch("a_sdlc.server.get_db")
    def test_link_valid_requirements(self, mock_get_db):
        """Linking valid requirement IDs should succeed."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001", "title": "Task 1"}
        db.get_requirement.return_value = {"id": "R1", "req_number": "FR-001"}
        db.link_task_requirement.return_value = {
            "requirement_id": "R1",
            "task_id": "T-001",
        }

        result = link_task_requirements(
            task_id="T-001", requirement_ids=["R1", "R2"]
        )

        assert result["status"] == "ok"
        assert result["linked"] == 2
        assert result["task_id"] == "T-001"

    @patch("a_sdlc.server.get_db")
    def test_link_invalid_requirements_returns_error(self, mock_get_db):
        """Linking with invalid requirement IDs should return error."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001", "title": "Task 1"}
        db.get_requirement.side_effect = lambda rid: (
            {"id": "R1"} if rid == "R1" else None
        )

        result = link_task_requirements(
            task_id="T-001", requirement_ids=["R1", "INVALID"]
        )

        assert result["status"] == "error"
        assert "INVALID" in result["message"]
        db.link_task_requirement.assert_not_called()

    @patch("a_sdlc.server.get_db")
    def test_link_nonexistent_task_returns_error(self, mock_get_db):
        """Linking to a nonexistent task should return error."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = None

        result = link_task_requirements(
            task_id="NONEXISTENT", requirement_ids=["R1"]
        )

        assert result["status"] == "error"
        assert "Task not found" in result["message"]

    @patch("a_sdlc.server.get_db")
    def test_link_empty_requirement_ids(self, mock_get_db):
        """Linking with empty list should return error."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001"}

        result = link_task_requirements(task_id="T-001", requirement_ids=[])

        assert result["status"] == "error"
        assert "No requirement IDs" in result["message"]


class TestGetTaskRequirementsMCP:
    """Test the get_task_requirements MCP tool."""

    @patch("a_sdlc.server.get_db")
    def test_returns_grouped_requirements(self, mock_get_db):
        """Should return requirements grouped by type."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001"}
        db.get_task_requirements.return_value = [
            {"id": "R1", "req_type": "functional", "req_number": "FR-001", "depth": "structural", "verified": 1},
            {"id": "R2", "req_type": "functional", "req_number": "FR-002", "depth": "behavioral", "verified": 0},
            {"id": "R3", "req_type": "non-functional", "req_number": "NFR-001", "depth": "structural", "verified": 0},
        ]

        result = get_task_requirements(task_id="T-001")

        assert result["status"] == "ok"
        assert result["task_id"] == "T-001"
        assert result["total"] == 3
        assert len(result["requirements"]["functional"]) == 2
        assert len(result["requirements"]["non-functional"]) == 1

    @patch("a_sdlc.server.get_db")
    def test_includes_verification_status(self, mock_get_db):
        """Should include verified field from LEFT JOIN."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001"}
        db.get_task_requirements.return_value = [
            {"id": "R1", "req_type": "functional", "req_number": "FR-001", "depth": "structural", "verified": 1, "verified_by": "agent-1", "evidence_type": "test", "evidence": "pytest passed"},
        ]

        result = get_task_requirements(task_id="T-001")

        fr_reqs = result["requirements"]["functional"]
        assert fr_reqs[0]["verified"] == 1
        assert fr_reqs[0]["verified_by"] == "agent-1"

    @patch("a_sdlc.server.get_db")
    def test_empty_requirements_returns_empty_groups(self, mock_get_db):
        """Task with no linked requirements should return empty groups."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = {"id": "T-001"}
        db.get_task_requirements.return_value = []

        result = get_task_requirements(task_id="T-001")

        assert result["status"] == "ok"
        assert result["total"] == 0
        assert result["requirements"] == {}

    @patch("a_sdlc.server.get_db")
    def test_nonexistent_task_returns_error(self, mock_get_db):
        """Querying a nonexistent task should return error."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_task.return_value = None

        result = get_task_requirements(task_id="NONEXISTENT")

        assert result["status"] == "error"
        assert "Task not found" in result["message"]


# =============================================================================
# split_prd Auto-Linkage & Coverage Tests (SDLC-T00165)
# =============================================================================


class TestSplitPrdAutoLinkage:
    """Test split_prd modifications for auto-linkage and coverage."""

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_creates_links_from_traces_to(self, mock_get_db, mock_pid, mock_cm):
        """split_prd should create requirement links when traces_to present."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_pid.return_value = "proj-1"
        cm = MagicMock()
        mock_cm.return_value = cm
        db.get_prd.return_value = {"id": "PRD-001", "title": "Test PRD", "file_path": "/tmp/prd.md"}
        db.get_project.return_value = {"shortname": "TEST"}
        db.get_next_task_id.side_effect = ["TEST-T00001", "TEST-T00002"]
        cm.get_task_path.return_value = Path("/tmp/nonexistent")
        cm.write_task.return_value = Path("/tmp/tasks/TEST-T00001.md")
        db.get_requirements.return_value = [
            {"id": "PRD-001:FR-001", "req_number": "FR-001", "summary": "R1"},
            {"id": "PRD-001:FR-002", "req_number": "FR-002", "summary": "R2"},
            {"id": "PRD-001:AC-001", "req_number": "AC-001", "summary": "AC"},
        ]
        db.get_requirement.return_value = {"id": "PRD-001:FR-001"}
        db.create_task.side_effect = [
            {"id": "TEST-T00001", "title": "T1", "priority": "high", "component": "auth"},
            {"id": "TEST-T00002", "title": "T2", "priority": "medium", "component": None},
        ]
        db.link_task_requirement.return_value = {}
        db.get_coverage_stats.return_value = {"total": 3, "linked": 2, "orphaned": 1, "by_type": {}}
        db.get_orphaned_requirements.return_value = [{"req_number": "AC-001"}]

        result = split_prd(
            prd_id="PRD-001",
            task_specs=[
                {"title": "T1", "priority": "high", "component": "auth", "traces_to": ["FR-001", "FR-002"]},
                {"title": "T2", "traces_to": ["FR-001"]},
            ],
        )
        assert result["status"] == "success"
        assert "linkage" in result
        assert result["linkage"]["linked"] > 0

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_returns_coverage_stats(self, mock_get_db, mock_pid, mock_cm):
        """split_prd should return coverage stats when traces_to present."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_pid.return_value = "proj-1"
        cm = MagicMock()
        mock_cm.return_value = cm
        db.get_prd.return_value = {"id": "P-001", "file_path": "/tmp/prd.md"}
        db.get_project.return_value = {"shortname": "TEST"}
        db.get_next_task_id.return_value = "TEST-T00001"
        cm.get_task_path.return_value = Path("/tmp/nonexistent")
        cm.write_task.return_value = Path("/tmp/t.md")
        db.get_requirements.return_value = [{"id": "P-001:FR-001", "req_number": "FR-001", "summary": "R1"}]
        db.get_requirement.return_value = {"id": "P-001:FR-001"}
        db.create_task.return_value = {"id": "TEST-T00001", "title": "T1", "priority": "medium", "component": None}
        db.link_task_requirement.return_value = {}
        db.get_coverage_stats.return_value = {"total": 1, "linked": 1, "orphaned": 0, "by_type": {}}
        db.get_orphaned_requirements.return_value = []

        result = split_prd(prd_id="P-001", task_specs=[{"title": "T1", "traces_to": ["FR-001"]}])
        assert result["status"] == "success"
        assert "coverage" in result
        assert result["coverage"]["total"] == 1
        assert result["coverage"]["linked"] == 1
        assert result["coverage"]["orphaned"] == []
        assert result["coverage"]["linkage_pct"] == 100.0

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_coverage_with_orphaned(self, mock_get_db, mock_pid, mock_cm):
        """Coverage should report orphaned requirements correctly."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_pid.return_value = "proj-1"
        cm = MagicMock()
        mock_cm.return_value = cm
        db.get_prd.return_value = {"id": "P-001", "file_path": "/tmp/prd.md"}
        db.get_project.return_value = {"shortname": "TEST"}
        db.get_next_task_id.return_value = "TEST-T00001"
        cm.get_task_path.return_value = Path("/tmp/nonexistent")
        cm.write_task.return_value = Path("/tmp/t.md")
        db.get_requirements.return_value = [
            {"id": "P-001:FR-001", "req_number": "FR-001", "summary": "R1"},
            {"id": "P-001:FR-002", "req_number": "FR-002", "summary": "R2"},
            {"id": "P-001:NFR-001", "req_number": "NFR-001", "summary": "R3"},
        ]
        db.get_requirement.return_value = {"id": "P-001:FR-001"}
        db.create_task.return_value = {"id": "TEST-T00001", "title": "T1", "priority": "medium", "component": None}
        db.link_task_requirement.return_value = {}
        db.get_coverage_stats.return_value = {"total": 3, "linked": 1, "orphaned": 2, "by_type": {}}
        db.get_orphaned_requirements.return_value = [{"req_number": "FR-002"}, {"req_number": "NFR-001"}]

        result = split_prd(prd_id="P-001", task_specs=[{"title": "T1", "traces_to": ["FR-001"]}])
        assert result["coverage"]["total"] == 3
        assert result["coverage"]["linked"] == 1
        assert set(result["coverage"]["orphaned"]) == {"FR-002", "NFR-001"}
        assert result["coverage"]["linkage_pct"] == 33.3

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_without_traces_to_no_linkage(self, mock_get_db, mock_pid, mock_cm):
        """split_prd without traces_to should not create links (backward compat)."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_pid.return_value = "proj-1"
        cm = MagicMock()
        mock_cm.return_value = cm
        db.get_prd.return_value = {"id": "P-001", "file_path": "/tmp/prd.md"}
        db.get_project.return_value = {"shortname": "TEST"}
        db.get_next_task_id.return_value = "TEST-T00001"
        cm.get_task_path.return_value = Path("/tmp/nonexistent")
        cm.write_task.return_value = Path("/tmp/t.md")
        db.create_task.return_value = {"id": "TEST-T00001", "title": "T1", "priority": "medium", "component": None}

        result = split_prd(prd_id="P-001", task_specs=[{"title": "T1", "priority": "medium"}])
        assert result["status"] == "success"
        assert "linkage" not in result
        assert "coverage" not in result
        db.link_task_requirement.assert_not_called()

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_auto_parses_requirements(self, mock_get_db, mock_pid, mock_cm):
        """split_prd should auto-parse requirements when not yet parsed."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_pid.return_value = "proj-1"
        cm = MagicMock()
        mock_cm.return_value = cm
        db.get_project.return_value = {"shortname": "TEST"}
        db.get_next_task_id.return_value = "TEST-T00001"
        cm.get_task_path.return_value = Path("/tmp/nonexistent")
        cm.write_task.return_value = Path("/tmp/t.md")
        db.get_requirements.side_effect = [
            [],
            [{"id": "P-001:FR-001", "req_number": "FR-001", "summary": "Test req"}],
        ]
        db.get_requirement.return_value = {"id": "P-001:FR-001"}
        db.create_task.return_value = {"id": "TEST-T00001", "title": "T1", "priority": "medium", "component": None}
        db.link_task_requirement.return_value = {}
        db.get_coverage_stats.return_value = {"total": 1, "linked": 1, "orphaned": 0, "by_type": {}}
        db.get_orphaned_requirements.return_value = []
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("## Requirements\n**FR-001**: Users can log in\n")
            prd_file = f.name
        try:
            db.get_prd.return_value = {"id": "P-001", "file_path": prd_file}
            result = split_prd(prd_id="P-001", task_specs=[{"title": "T1", "traces_to": ["FR-001"]}])
            assert result["status"] == "success"
            db.upsert_requirement.assert_called()
        finally:
            Path(prd_file).unlink(missing_ok=True)


class TestCrossPrdRecommendations:
    """Test cross-PRD integration recommendation generation."""

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_recommendations_generated(self, mock_get_db, mock_pid, mock_cm):
        """Should generate recommendations when reqs reference other PRDs."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_pid.return_value = "proj-1"
        cm = MagicMock()
        mock_cm.return_value = cm
        db.get_prd.return_value = {"id": "PRD-P0001", "file_path": "/tmp/p.md"}
        db.get_project.return_value = {"shortname": "TEST"}
        db.get_next_task_id.return_value = "TEST-T00001"
        cm.get_task_path.return_value = Path("/tmp/nonexistent")
        cm.write_task.return_value = Path("/tmp/t.md")
        db.get_requirements.return_value = [
            {"id": "PRD-P0001:FR-001", "req_number": "FR-001", "summary": "Integrates with SDLC-P0028 auth"},
            {"id": "PRD-P0001:FR-002", "req_number": "FR-002", "summary": "Plain requirement"},
        ]
        db.get_requirement.return_value = {"id": "PRD-P0001:FR-001"}
        db.create_task.return_value = {"id": "TEST-T00001", "title": "T1", "priority": "medium", "component": None}
        db.link_task_requirement.return_value = {}
        db.get_coverage_stats.return_value = {"total": 2, "linked": 1, "orphaned": 1, "by_type": {}}
        db.get_orphaned_requirements.return_value = [{"req_number": "FR-002"}]

        result = split_prd(prd_id="PRD-P0001", task_specs=[{"title": "T1", "traces_to": ["FR-001"]}])
        assert "integration_recommendations" in result
        recs = result["integration_recommendations"]
        assert len(recs) == 1
        assert recs[0]["requirement"] == "FR-001"
        assert recs[0]["references_prd"] == "SDLC-P0028"

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_no_recommendations_without_cross_refs(self, mock_get_db, mock_pid, mock_cm):
        """Should not include recommendations when no cross-PRD refs exist."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_pid.return_value = "proj-1"
        cm = MagicMock()
        mock_cm.return_value = cm
        db.get_prd.return_value = {"id": "P-001", "file_path": "/tmp/p.md"}
        db.get_project.return_value = {"shortname": "TEST"}
        db.get_next_task_id.return_value = "TEST-T00001"
        cm.get_task_path.return_value = Path("/tmp/nonexistent")
        cm.write_task.return_value = Path("/tmp/t.md")
        db.get_requirements.return_value = [
            {"id": "P-001:FR-001", "req_number": "FR-001", "summary": "Simple requirement"},
        ]
        db.get_requirement.return_value = {"id": "P-001:FR-001"}
        db.create_task.return_value = {"id": "TEST-T00001", "title": "T1", "priority": "medium", "component": None}
        db.link_task_requirement.return_value = {}
        db.get_coverage_stats.return_value = {"total": 1, "linked": 1, "orphaned": 0, "by_type": {}}
        db.get_orphaned_requirements.return_value = []

        result = split_prd(prd_id="P-001", task_specs=[{"title": "T1", "traces_to": ["FR-001"]}])
        assert "integration_recommendations" not in result


class TestCoverageEdgeCases:
    """Test coverage computation edge cases."""

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_zero_requirements_gives_100_pct(self, mock_get_db, mock_pid, mock_cm):
        """Zero requirements should yield 100% linkage (vacuous truth)."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_pid.return_value = "proj-1"
        cm = MagicMock()
        mock_cm.return_value = cm
        db.get_prd.return_value = {"id": "P-001", "file_path": ""}
        db.get_project.return_value = {"shortname": "TEST"}
        db.get_next_task_id.return_value = "TEST-T00001"
        cm.get_task_path.return_value = Path("/tmp/nonexistent")
        cm.write_task.return_value = Path("/tmp/t.md")
        db.get_requirements.return_value = []
        db.create_task.return_value = {"id": "TEST-T00001", "title": "T1", "priority": "medium", "component": None}
        db.get_coverage_stats.return_value = {"total": 0, "linked": 0, "orphaned": 0, "by_type": {}}
        db.get_orphaned_requirements.return_value = []

        result = split_prd(prd_id="P-001", task_specs=[{"title": "T1", "traces_to": ["FR-001"]}])
        assert result["status"] == "success"
        assert result["coverage"]["linkage_pct"] == 100.0

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_all_requirements_linked(self, mock_get_db, mock_pid, mock_cm):
        """All requirements linked should yield 100% coverage."""
        db = MagicMock()
        mock_get_db.return_value = db
        mock_pid.return_value = "proj-1"
        cm = MagicMock()
        mock_cm.return_value = cm
        db.get_prd.return_value = {"id": "P-001", "file_path": "/tmp/p.md"}
        db.get_project.return_value = {"shortname": "TEST"}
        db.get_next_task_id.return_value = "TEST-T00001"
        cm.get_task_path.return_value = Path("/tmp/nonexistent")
        cm.write_task.return_value = Path("/tmp/t.md")
        db.get_requirements.return_value = [{"id": "P-001:FR-001", "req_number": "FR-001", "summary": "R1"}]
        db.get_requirement.return_value = {"id": "P-001:FR-001"}
        db.create_task.return_value = {"id": "TEST-T00001", "title": "T1", "priority": "medium", "component": None}
        db.link_task_requirement.return_value = {}
        db.get_coverage_stats.return_value = {"total": 1, "linked": 1, "orphaned": 0, "by_type": {}}
        db.get_orphaned_requirements.return_value = []

        result = split_prd(prd_id="P-001", task_specs=[{"title": "T1", "traces_to": ["FR-001"]}])
        assert result["coverage"]["linkage_pct"] == 100.0
        assert result["coverage"]["orphaned"] == []


class TestAutoParseRequirements:
    """Test the _auto_parse_requirements helper."""

    def test_parses_fr_requirements(self, temp_db):
        """Should parse FR-NNN requirements from markdown."""
        content = "## Requirements\n**FR-001**: Users can log in via SSO\n**FR-002**: Dashboard shows metrics\n"
        _auto_parse_requirements(temp_db, "TEST-P0001", content)
        reqs = temp_db.get_requirements("TEST-P0001")
        assert len(reqs) == 2
        numbers = {r["req_number"] for r in reqs}
        assert numbers == {"FR-001", "FR-002"}

    def test_parses_nfr_requirements(self, temp_db):
        """Should parse NFR-NNN requirements."""
        content = "**NFR-001**: Response time under 200ms\n"
        _auto_parse_requirements(temp_db, "TEST-P0001", content)
        reqs = temp_db.get_requirements("TEST-P0001")
        assert len(reqs) == 1
        assert reqs[0]["req_type"] == "non-functional"

    def test_parses_ac_requirements(self, temp_db):
        """Should parse AC-NNN requirements."""
        content = "**AC-001**: All tests pass\n**AC-002**: Coverage above 80%\n"
        _auto_parse_requirements(temp_db, "TEST-P0001", content)
        reqs = temp_db.get_requirements("TEST-P0001")
        assert len(reqs) == 2
        assert all(r["req_type"] == "ac" for r in reqs)

    def test_parses_mixed_types(self, temp_db):
        """Should parse all requirement types from mixed content."""
        content = "**FR-001**: Functional req\n**NFR-001**: Non-functional req\n**AC-001**: Acceptance criterion\n"
        _auto_parse_requirements(temp_db, "TEST-P0001", content)
        reqs = temp_db.get_requirements("TEST-P0001")
        assert len(reqs) == 3
        types = {r["req_type"] for r in reqs}
        assert types == {"functional", "non-functional", "ac"}

    def test_no_requirements_in_content(self, temp_db):
        """Should handle content with no parseable requirements."""
        content = "## Overview\nThis is a PRD with no formal requirements.\n"
        _auto_parse_requirements(temp_db, "TEST-P0001", content)
        reqs = temp_db.get_requirements("TEST-P0001")
        assert len(reqs) == 0

    def test_classifies_behavioral_depth(self, temp_db):
        """Should classify behavioral requirements with depth during auto-parse."""
        content = "**FR-001**: System must enforce rate limits on API calls\n"
        _auto_parse_requirements(temp_db, "TEST-P0001", content)
        reqs = temp_db.get_requirements("TEST-P0001")
        assert len(reqs) == 1
        assert reqs[0]["depth"] == "behavioral"

    def test_classifies_structural_depth(self, temp_db):
        """Should classify structural requirements with depth during auto-parse."""
        content = "**FR-001**: Create agents table with id and name columns\n"
        _auto_parse_requirements(temp_db, "TEST-P0001", content)
        reqs = temp_db.get_requirements("TEST-P0001")
        assert len(reqs) == 1
        assert reqs[0]["depth"] == "structural"

    def test_classifies_integration_depth(self, temp_db):
        """Should classify integration requirements with depth during auto-parse."""
        content = "**FR-001**: Routing depends on governance permissions\n"
        _auto_parse_requirements(temp_db, "TEST-P0001", content)
        reqs = temp_db.get_requirements("TEST-P0001")
        assert len(reqs) == 1
        assert reqs[0]["depth"] == "integration"


# =============================================================================
# Challenge MCP Tools Tests (SDLC-T00169)
# =============================================================================


class TestChallengeChecklists:
    """Test CHALLENGE_CHECKLISTS constant."""

    def test_all_four_artifact_types_present(self):
        """CHALLENGE_CHECKLISTS should contain prd, design, split, task keys."""
        assert set(CHALLENGE_CHECKLISTS.keys()) == {"prd", "design", "split", "task"}

    def test_each_checklist_is_nonempty_list_of_strings(self):
        """Each checklist should be a non-empty list of string questions."""
        for artifact_type, items in CHALLENGE_CHECKLISTS.items():
            assert isinstance(items, list), f"{artifact_type} checklist not a list"
            assert len(items) > 0, f"{artifact_type} checklist is empty"
            for item in items:
                assert isinstance(item, str), f"Non-string item in {artifact_type}"
                assert item.endswith("?"), f"Checklist item should be a question: {item}"


class TestDetectStaleLoop:
    """Test _detect_stale_loop helper function."""

    def test_empty_previous_returns_false(self):
        """Should return False when previous_objections is None."""
        is_stale, pct = _detect_stale_loop(
            [{"description": "issue A"}], None
        )
        assert is_stale is False
        assert pct == 0.0

    def test_empty_previous_list_returns_false(self):
        """Should return False when previous_objections is empty list."""
        is_stale, pct = _detect_stale_loop(
            [{"description": "issue A"}], []
        )
        assert is_stale is False
        assert pct == 0.0

    def test_zero_overlap_returns_false(self):
        """0% overlap should not be stale."""
        is_stale, pct = _detect_stale_loop(
            [{"description": "new issue"}],
            [{"description": "old issue"}],
        )
        assert is_stale is False
        assert pct == 0.0

    def test_full_overlap_returns_true(self):
        """100% overlap should be stale."""
        objections = [{"description": "issue A"}, {"description": "issue B"}]
        is_stale, pct = _detect_stale_loop(objections, objections)
        assert is_stale is True
        assert pct == 1.0

    def test_exactly_80_percent_returns_false(self):
        """Exactly 80% overlap should NOT be stale (> 0.8 required, not >=)."""
        current = [
            {"description": f"issue {i}"} for i in range(5)
        ]
        # 4 out of 5 match = 80% exactly
        previous = [
            {"description": f"issue {i}"} for i in range(4)
        ] + [{"description": "different"}]
        is_stale, pct = _detect_stale_loop(current, previous)
        assert is_stale is False
        assert pct == pytest.approx(0.8)

    def test_above_80_percent_returns_true(self):
        """Above 80% overlap should be stale."""
        # 5 out of 6 match = 83.3%
        current = [{"description": f"issue {i}"} for i in range(6)]
        previous = [{"description": f"issue {i}"} for i in range(5)] + [
            {"description": "other"}
        ]
        is_stale, pct = _detect_stale_loop(current, previous)
        assert is_stale is True
        assert pct > 0.8

    def test_empty_current_returns_false(self):
        """Empty current objections should not be stale."""
        is_stale, pct = _detect_stale_loop(
            [], [{"description": "old"}]
        )
        assert is_stale is False


class TestChallengeArtifactMCP:
    """Test challenge_artifact MCP tool."""

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_invalid_artifact_type_returns_error(
        self, mock_get_db, mock_get_cm, mock_get_storage
    ):
        """Should return error for unrecognized artifact_type."""
        result = challenge_artifact("bogus", "ID-001")
        assert result["status"] == "error"
        assert "Invalid artifact_type" in result["message"]

    @patch("a_sdlc.server._get_current_project_id", return_value="test-project")
    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_prd_returns_prompt_with_checklist(
        self, mock_get_db, mock_get_cm, mock_get_storage, mock_pid
    ):
        """challenge_artifact for PRD type should include checklist items in prompt."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = {
            "id": "TEST-P0001",
            "file_path": "/tmp/prd.md",
        }
        mock_db.get_project.return_value = {"path": "/tmp/nonexistent_project"}
        mock_get_db.return_value = mock_db

        mock_cm = MagicMock()
        mock_cm.read_content.return_value = "# My PRD\nSome requirements."
        mock_get_cm.return_value = mock_cm

        mock_storage = MagicMock()
        mock_storage.get_requirements.return_value = []
        mock_storage.get_challenge_rounds.return_value = []
        mock_storage.create_challenge_round.return_value = {}
        mock_get_storage.return_value = mock_storage

        result = challenge_artifact("prd", "TEST-P0001")

        assert result["status"] == "ok"
        assert result["round_number"] == 1
        assert result["checklist"] == CHALLENGE_CHECKLISTS["prd"]
        prompt = result["challenge_prompt"]
        assert "ARTIFACT CONTENT" in prompt
        assert "My PRD" in prompt
        assert "CHECKLIST" in prompt
        # Verify at least one checklist item appears numbered
        assert "1. Are all requirements testable and unambiguous?" in prompt

    @patch("a_sdlc.server._get_current_project_id", return_value="test-project")
    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_design_includes_requirements_with_depth(
        self, mock_get_db, mock_get_cm, mock_get_storage, mock_pid
    ):
        """challenge_artifact for design type should include requirements section."""
        mock_db = MagicMock()
        mock_db.get_project.return_value = {"path": "/tmp/nonexistent_project"}
        mock_get_db.return_value = mock_db

        mock_storage = MagicMock()
        mock_storage.get_design_by_prd.return_value = {
            "content": "# Design Doc\nSome design.",
        }
        mock_storage.get_requirements.return_value = [
            {"req_number": "FR-001", "depth": "behavioral", "summary": "Must validate"},
            {"req_number": "NFR-001", "depth": "structural", "summary": "Under 200ms"},
        ]
        mock_storage.get_challenge_rounds.return_value = []
        mock_storage.create_challenge_round.return_value = {}
        mock_get_storage.return_value = mock_storage

        result = challenge_artifact("design", "TEST-P0001")

        assert result["status"] == "ok"
        prompt = result["challenge_prompt"]
        assert "REQUIREMENTS" in prompt
        assert "FR-001 [behavioral]" in prompt
        assert "NFR-001 [structural]" in prompt

    @patch("a_sdlc.server._get_current_project_id", return_value="test-project")
    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_includes_lesson_learn_when_file_exists(
        self, mock_get_db, mock_get_cm, mock_get_storage, mock_pid
    ):
        """challenge_artifact should include lesson-learn content when files exist."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create lesson-learn file under fake project path
            sdlc_dir = Path(tmpdir) / ".sdlc"
            sdlc_dir.mkdir()
            lesson_file = sdlc_dir / "lesson-learn.md"
            lesson_file.write_text(
                "# Lessons\n- Always validate inputs", encoding="utf-8"
            )

            # Create global lesson file under fake home/.a-sdlc/
            fake_home = Path(tmpdir) / "fakehome"
            fake_home.mkdir()
            global_asdlc = fake_home / ".a-sdlc"
            global_asdlc.mkdir()
            global_lesson = global_asdlc / "lesson-learn.md"
            global_lesson.write_text(
                "# Global\n- Use transactions", encoding="utf-8"
            )

            mock_db = MagicMock()
            mock_db.get_prd.return_value = {"id": "TEST-P0001", "file_path": "/tmp/prd.md"}
            mock_db.get_project.return_value = {"path": tmpdir}
            mock_get_db.return_value = mock_db

            mock_cm = MagicMock()
            mock_cm.read_content.return_value = "# PRD Content"
            mock_get_cm.return_value = mock_cm

            mock_storage = MagicMock()
            mock_storage.get_requirements.return_value = []
            mock_storage.get_challenge_rounds.return_value = []
            mock_storage.create_challenge_round.return_value = {}
            mock_get_storage.return_value = mock_storage

            with patch("a_sdlc.server.Path") as mock_path_cls:
                # Keep Path(x) working for non-home calls, redirect home()
                real_path = Path

                def path_side_effect(*args, **kwargs):
                    return real_path(*args, **kwargs)

                mock_path_cls.side_effect = path_side_effect
                mock_path_cls.home.return_value = fake_home
                mock_path_cls.cwd = real_path.cwd

                result = challenge_artifact("prd", "TEST-P0001")

            assert result["status"] == "ok"
            prompt = result["challenge_prompt"]
            assert "LESSONS LEARNED" in prompt
            assert "Always validate inputs" in prompt
            assert "Use transactions" in prompt

    @patch("a_sdlc.server._get_current_project_id", return_value="test-project")
    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_round_2_includes_only_unresolved(
        self, mock_get_db, mock_get_cm, mock_get_storage, mock_pid
    ):
        """Round 2+ should include diff-based unresolved items only."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = {"id": "TEST-P0001", "file_path": "/tmp/prd.md"}
        mock_db.get_project.return_value = {"path": "/tmp/nonexistent_project"}
        mock_get_db.return_value = mock_db

        mock_cm = MagicMock()
        mock_cm.read_content.return_value = "PRD content"
        mock_get_cm.return_value = mock_cm

        # Simulate a previous round with some objections and a verdict
        round1 = {
            "round_number": 1,
            "objections": json.dumps([
                {"description": "Missing edge case A"},
                {"description": "No error handling for B"},
                {"description": "Ambiguous requirement C"},
            ]),
            "verdict": json.dumps({
                "resolved": [{"description": "Missing edge case A"}],
                "accepted": [],
                "escalated": [],
            }),
            "status": "in_progress",
        }

        mock_storage = MagicMock()
        mock_storage.get_requirements.return_value = []
        mock_storage.get_challenge_rounds.return_value = [round1]
        mock_storage.create_challenge_round.return_value = {}
        mock_get_storage.return_value = mock_storage

        result = challenge_artifact("prd", "TEST-P0001")

        assert result["status"] == "ok"
        assert result["round_number"] == 2
        prompt = result["challenge_prompt"]
        assert "PREVIOUS UNRESOLVED" in prompt
        # The resolved issue A should NOT appear in unresolved
        assert "Missing edge case A" not in prompt.split("PREVIOUS UNRESOLVED")[1]
        # Unresolved items B and C should appear
        assert "No error handling for B" in prompt
        assert "Ambiguous requirement C" in prompt

    @patch("a_sdlc.server.get_storage")
    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_prd_not_found_returns_not_found(
        self, mock_get_db, mock_get_cm, mock_get_storage
    ):
        """Should return not_found when PRD does not exist."""
        mock_db = MagicMock()
        mock_db.get_prd.return_value = None
        mock_get_db.return_value = mock_db

        result = challenge_artifact("prd", "NONEXISTENT")
        assert result["status"] == "not_found"


class TestRecordChallengeRoundMCP:
    """Test record_challenge_round MCP tool."""

    @patch("a_sdlc.server._load_challenge_config", return_value={"enabled": True, "max_rounds": 5})
    @patch("a_sdlc.server.get_storage")
    def test_stores_objections(self, mock_get_storage, mock_config):
        """Should store objections via storage update."""
        mock_storage = MagicMock()
        mock_storage.get_challenge_rounds.return_value = []
        mock_get_storage.return_value = mock_storage

        objections = [{"description": "Issue 1"}, {"description": "Issue 2"}]
        result = record_challenge_round("prd", "TEST-P0001", 1, objections)

        assert result["status"] == "ok"
        assert result["round_number"] == 1
        assert result["total_objections"] == 2
        mock_storage.update_challenge_round.assert_called_once()

    @patch("a_sdlc.server._load_challenge_config", return_value={"enabled": True, "max_rounds": 5})
    @patch("a_sdlc.server.get_storage")
    def test_stale_loop_auto_terminates(self, mock_get_storage, mock_config):
        """Stale loop (>80% overlap) should auto-terminate (AC-013)."""
        same_objections = [{"description": f"issue {i}"} for i in range(5)]
        round1 = {
            "round_number": 1,
            "objections": json.dumps(same_objections),
            "status": "open",
        }
        mock_storage = MagicMock()
        mock_storage.get_challenge_rounds.return_value = [round1]
        mock_get_storage.return_value = mock_storage

        result = record_challenge_round("prd", "TEST-P0001", 2, same_objections)

        assert result["status"] == "auto_terminated"
        assert result["reason"] == "stale_loop_detected"
        assert result["overlap_pct"] == 1.0
        # Verify storage was updated with auto_terminated status
        mock_storage.update_challenge_round.assert_called_once()
        call_kwargs = mock_storage.update_challenge_round.call_args
        assert call_kwargs.kwargs.get("status") == "auto_terminated" or (
            call_kwargs[1].get("status") == "auto_terminated"
        )

    @patch("a_sdlc.server._load_challenge_config", return_value={"enabled": True, "max_rounds": 5})
    @patch("a_sdlc.server.get_storage")
    def test_responses_and_verdict_updates_round(self, mock_get_storage, mock_config):
        """Should update round with responses and verdict."""
        mock_storage = MagicMock()
        mock_storage.get_challenge_rounds.return_value = []
        mock_get_storage.return_value = mock_storage

        objections = [{"description": "Issue 1"}]
        responses = [{"description": "Issue 1", "response": "Fixed"}]
        verdict = {"resolved": ["Issue 1"], "accepted": [], "escalated": []}

        result = record_challenge_round(
            "prd", "TEST-P0001", 1, objections,
            responses=responses, verdict=verdict,
        )

        assert result["status"] == "ok"
        assert result["unresolved"] == 0
        assert result["total_objections"] == 1
        call_kwargs = mock_storage.update_challenge_round.call_args
        # Verify verdict was passed as JSON string
        kw = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert "verdict" in kw
        assert json.loads(kw["verdict"]) == verdict

    @patch("a_sdlc.server._load_challenge_config", return_value={"enabled": True, "max_rounds": 3})
    @patch("a_sdlc.server.get_storage")
    def test_max_rounds_triggers_escalated(self, mock_get_storage, mock_config):
        """Should return escalated when round_number >= max_rounds."""
        mock_storage = MagicMock()
        mock_storage.get_challenge_rounds.return_value = [
            {"round_number": 1, "objections": "[]", "status": "open"},
            {"round_number": 2, "objections": "[]", "status": "open"},
        ]
        mock_get_storage.return_value = mock_storage

        objections = [{"description": "Still unresolved"}]
        result = record_challenge_round("prd", "TEST-P0001", 3, objections)

        assert result["status"] == "escalated"

    def test_invalid_artifact_type_returns_error(self):
        """Should return error for invalid artifact_type."""
        result = record_challenge_round("invalid", "ID", 1, [])
        assert result["status"] == "error"
        assert "Invalid artifact_type" in result["message"]

    def test_invalid_round_number_returns_error(self):
        """Should return error for non-positive round_number."""
        result = record_challenge_round("prd", "ID", 0, [])
        assert result["status"] == "error"
        assert "round_number" in result["message"]


class TestGetChallengeStatusMCP:
    """Test get_challenge_status MCP tool."""

    @patch("a_sdlc.server.get_storage")
    def test_no_rounds_returns_unchallenged(self, mock_get_storage):
        """Should return 'unchallenged' when no rounds exist."""
        mock_storage = MagicMock()
        mock_storage.get_challenge_rounds.return_value = []
        mock_get_storage.return_value = mock_storage

        result = get_challenge_status("prd", "TEST-P0001")

        assert result["status"] == "ok"
        assert result["challenge_status"] == "unchallenged"
        assert result["stats"]["total_rounds"] == 0
        assert result["stats"]["total_objections"] == 0

    @patch("a_sdlc.server.get_storage")
    def test_resolved_rounds_returns_resolved(self, mock_get_storage):
        """Should return 'resolved' when all rounds are resolved."""
        mock_storage = MagicMock()
        mock_storage.get_challenge_rounds.return_value = [
            {
                "round_number": 1,
                "objections": json.dumps([{"description": "issue"}]),
                "verdict": json.dumps({"resolved": ["issue"], "accepted": [], "escalated": []}),
                "status": "resolved",
            },
        ]
        mock_get_storage.return_value = mock_storage

        result = get_challenge_status("prd", "TEST-P0001")

        assert result["status"] == "ok"
        assert result["challenge_status"] == "resolved"
        assert result["stats"]["total_rounds"] == 1
        assert result["stats"]["resolved"] == 1

    @patch("a_sdlc.server.get_storage")
    def test_escalated_items_returns_escalated(self, mock_get_storage):
        """Should return 'escalated' when verdict has escalated items."""
        mock_storage = MagicMock()
        mock_storage.get_challenge_rounds.return_value = [
            {
                "round_number": 1,
                "objections": json.dumps([{"description": "critical gap"}]),
                "verdict": json.dumps({
                    "resolved": [],
                    "accepted": [],
                    "escalated": ["critical gap"],
                }),
                "status": "escalated",
            },
        ]
        mock_get_storage.return_value = mock_storage

        result = get_challenge_status("prd", "TEST-P0001")

        assert result["status"] == "ok"
        assert result["challenge_status"] == "escalated"
        assert result["stats"]["escalated"] == 1

    @patch("a_sdlc.server.get_storage")
    def test_stats_aggregation(self, mock_get_storage):
        """Stats should aggregate across all rounds correctly."""
        mock_storage = MagicMock()
        mock_storage.get_challenge_rounds.return_value = [
            {
                "round_number": 1,
                "objections": json.dumps([
                    {"description": "A"}, {"description": "B"}, {"description": "C"},
                ]),
                "verdict": json.dumps({
                    "resolved": ["A"],
                    "accepted": ["B"],
                    "escalated": [],
                }),
                "status": "in_progress",
            },
            {
                "round_number": 2,
                "objections": json.dumps([{"description": "C revised"}]),
                "verdict": json.dumps({
                    "resolved": ["C revised"],
                    "accepted": [],
                    "escalated": [],
                }),
                "status": "resolved",
            },
        ]
        mock_get_storage.return_value = mock_storage

        result = get_challenge_status("prd", "TEST-P0001")

        assert result["status"] == "ok"
        stats = result["stats"]
        assert stats["total_rounds"] == 2
        assert stats["total_objections"] == 4  # 3 + 1
        assert stats["resolved"] == 2  # A + C revised
        assert stats["accepted"] == 1  # B

    @patch("a_sdlc.server.get_storage")
    def test_auto_terminated_propagation(self, mock_get_storage):
        """Should return 'auto_terminated' when latest round is auto_terminated."""
        mock_storage = MagicMock()
        mock_storage.get_challenge_rounds.return_value = [
            {
                "round_number": 1,
                "objections": json.dumps([{"description": "issue"}]),
                "verdict": None,
                "status": "open",
            },
            {
                "round_number": 2,
                "objections": json.dumps([{"description": "issue"}]),
                "verdict": None,
                "status": "auto_terminated",
            },
        ]
        mock_get_storage.return_value = mock_storage

        result = get_challenge_status("prd", "TEST-P0001")

        assert result["status"] == "ok"
        assert result["challenge_status"] == "auto_terminated"

    def test_invalid_artifact_type_returns_error(self):
        """Should return error for invalid artifact_type."""
        result = get_challenge_status("invalid", "ID")
        assert result["status"] == "error"
        assert "Invalid artifact_type" in result["message"]

    @patch("a_sdlc.server.get_storage")
    def test_effectiveness_metrics(self, mock_get_storage):
        """Should include effectiveness metrics in response."""
        mock_storage = MagicMock()
        mock_storage.get_challenge_rounds.return_value = [
            {
                "round_number": 1,
                "objections": json.dumps([{"description": "A"}, {"description": "B"}]),
                "verdict": json.dumps({"resolved": ["A"], "accepted": ["B"], "escalated": []}),
                "status": "resolved",
            },
            {
                "round_number": 2,
                "objections": json.dumps([{"description": "C"}]),
                "verdict": json.dumps({"resolved": [], "accepted": [], "escalated": ["C"]}),
                "status": "escalated",
            },
            {
                "round_number": 3,
                "objections": json.dumps([{"description": "D"}]),
                "verdict": None,
                "status": "in_progress",
            },
        ]
        mock_get_storage.return_value = mock_storage

        result = get_challenge_status("prd", "TEST-P0001")

        assert result["status"] == "ok"
        eff = result["effectiveness"]
        # Round 1 was resolved → first_round_resolution_rate = 1/3
        assert eff["first_round_resolution_rate"] == round(1 / 3, 2)
        # 1 escalated out of 3 rounds
        assert eff["escalation_rate"] == round(1 / 3, 2)
        # No auto_terminated
        assert eff["auto_termination_rate"] == 0.0
        assert eff["avg_rounds"] == 3
        # 4 total objections, 1 resolved + 1 accepted = 2
        assert eff["total_objections"] == 4
        assert eff["resolution_rate"] == round(2 / 4, 2)

    @patch("a_sdlc.server.get_storage")
    def test_auto_terminated_effectiveness(self, mock_get_storage):
        """Should reflect auto_termination_rate when rounds are auto_terminated."""
        mock_storage = MagicMock()
        mock_storage.get_challenge_rounds.return_value = [
            {
                "round_number": 1,
                "objections": json.dumps([{"description": "stale"}]),
                "verdict": None,
                "status": "open",
            },
            {
                "round_number": 2,
                "objections": json.dumps([{"description": "stale"}]),
                "verdict": None,
                "status": "auto_terminated",
            },
        ]
        mock_get_storage.return_value = mock_storage

        result = get_challenge_status("prd", "TEST-P0001")

        assert result["status"] == "ok"
        eff = result["effectiveness"]
        assert eff["auto_termination_rate"] == 0.5  # 1 out of 2
        assert eff["first_round_resolution_rate"] == 0.0
        assert eff["resolution_rate"] == 0.0


# =============================================================================
# Remediation Tasks (SDLC-T00170 / FR-036 / AC-021)
# =============================================================================


class TestCreateRemediationTasks:
    """Test create_remediation_tasks MCP tool."""

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_orphaned_requirements_create_tasks(self, mock_get_db, mock_get_cm):
        """Should create 'Remediate:' tasks for orphaned requirements (FR-036)."""
        db = MagicMock()
        mock_get_db.return_value = db
        cm = MagicMock()
        mock_get_cm.return_value = cm
        cm.write_task.return_value = Path("/tmp/tasks/T00001.md")

        db.get_sprint.return_value = {"id": "S-0001", "project_id": "proj"}
        db.get_sprint_prds.return_value = [{"id": "P-0001"}]
        db.get_orphaned_requirements.return_value = [
            {"id": "r1", "req_number": "FR-001", "summary": "Login feature"},
        ]
        db.get_next_task_id.return_value = "PROJ-T00099"
        db.create_task.return_value = {"id": "PROJ-T00099"}
        # AC requirements per PRD (none, so no unverified AC tasks)
        db.get_requirements.return_value = []
        # Sprint tasks (none, so no scope drift tasks)
        db.list_tasks_by_sprint.return_value = []

        result = create_remediation_tasks("S-0001")

        assert result["status"] == "ok"
        assert result["created"] == 1
        assert result["tasks"][0]["title"] == "Remediate: FR-001 \u2014 Login feature"
        assert result["tasks"][0]["gap_type"] == "orphaned_requirement"
        assert result["tasks"][0]["source_id"] == "r1"

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_unverified_acs_create_tasks(self, mock_get_db, mock_get_cm):
        """Should create 'Verify:' tasks for unverified acceptance criteria (FR-036)."""
        db = MagicMock()
        mock_get_db.return_value = db
        cm = MagicMock()
        mock_get_cm.return_value = cm
        cm.write_task.return_value = Path("/tmp/tasks/T00001.md")

        db.get_sprint.return_value = {"id": "S-0001", "project_id": "proj"}
        db.get_sprint_prds.return_value = [{"id": "P-0001"}]
        db.get_orphaned_requirements.return_value = []  # No orphaned reqs
        db.get_requirements.return_value = [
            {"id": "ac1", "req_number": "AC-001", "summary": "User sees dashboard"},
        ]
        # AC has linked tasks but no verification
        db.get_requirement_tasks.return_value = [{"id": "T1"}]
        db.get_ac_verifications.return_value = []  # No verifications
        db.get_next_task_id.return_value = "PROJ-T00100"
        db.create_task.return_value = {"id": "PROJ-T00100"}
        db.list_tasks_by_sprint.return_value = []

        result = create_remediation_tasks("S-0001")

        assert result["status"] == "ok"
        assert result["created"] == 1
        assert result["tasks"][0]["title"] == "Verify: AC-001 \u2014 User sees dashboard"
        assert result["tasks"][0]["gap_type"] == "unverified_ac"

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_scope_drift_creates_trace_tasks(self, mock_get_db, mock_get_cm):
        """Should create 'Trace:' tasks for unlinked (scope drift) tasks (FR-036)."""
        db = MagicMock()
        mock_get_db.return_value = db
        cm = MagicMock()
        mock_get_cm.return_value = cm
        cm.write_task.return_value = Path("/tmp/tasks/T00001.md")

        db.get_sprint.return_value = {"id": "S-0001", "project_id": "proj"}
        db.get_sprint_prds.return_value = [{"id": "P-0001"}]
        db.get_orphaned_requirements.return_value = []
        db.get_requirements.return_value = []
        db.list_tasks_by_sprint.return_value = [
            {"id": "T-DRIFT", "title": "Ad-hoc task", "prd_id": "P-0001"},
        ]
        db.get_task_requirements.return_value = []  # No requirement links
        db.get_next_task_id.return_value = "PROJ-T00101"
        db.create_task.return_value = {"id": "PROJ-T00101"}

        result = create_remediation_tasks("S-0001")

        assert result["status"] == "ok"
        assert result["created"] == 1
        assert result["tasks"][0]["title"] == "Trace: T-DRIFT"
        assert result["tasks"][0]["gap_type"] == "scope_drift"
        assert result["tasks"][0]["source_id"] == "T-DRIFT"

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_remediation_metadata_tag(self, mock_get_db, mock_get_cm):
        """Should tag all remediation tasks with remediation:true metadata (AC-021)."""
        db = MagicMock()
        mock_get_db.return_value = db
        cm = MagicMock()
        mock_get_cm.return_value = cm
        cm.write_task.return_value = Path("/tmp/tasks/T00001.md")

        db.get_sprint.return_value = {"id": "S-0001", "project_id": "proj"}
        db.get_sprint_prds.return_value = [{"id": "P-0001"}]
        db.get_orphaned_requirements.return_value = [
            {"id": "r1", "req_number": "FR-001", "summary": "Feature"},
        ]
        db.get_next_task_id.return_value = "PROJ-T00099"
        db.create_task.return_value = {"id": "PROJ-T00099"}
        db.get_requirements.return_value = []
        db.list_tasks_by_sprint.return_value = []

        create_remediation_tasks("S-0001")

        # Verify write_task was called with remediation:true in data
        call_kwargs = cm.write_task.call_args
        assert call_kwargs is not None
        data = call_kwargs.kwargs.get("data") or call_kwargs[1].get("data")
        assert data["remediation"] is True

    @patch("a_sdlc.server.get_content_manager")
    @patch("a_sdlc.server.get_db")
    def test_no_gaps_returns_empty(self, mock_get_db, mock_get_cm):
        """Should return zero created tasks when no gaps exist."""
        db = MagicMock()
        mock_get_db.return_value = db
        cm = MagicMock()
        mock_get_cm.return_value = cm

        db.get_sprint.return_value = {"id": "S-0001", "project_id": "proj"}
        db.get_sprint_prds.return_value = [{"id": "P-0001"}]
        db.get_orphaned_requirements.return_value = []
        db.get_requirements.return_value = []
        db.list_tasks_by_sprint.return_value = []

        result = create_remediation_tasks("S-0001")

        assert result["status"] == "ok"
        assert result["created"] == 0
        assert result["tasks"] == []

    @patch("a_sdlc.server.get_db")
    def test_sprint_not_found(self, mock_get_db):
        """Should return error when sprint does not exist."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_sprint.return_value = None

        result = create_remediation_tasks("NONEXISTENT")

        assert result["status"] == "error"
        assert "Sprint not found" in result["message"]


# =============================================================================
# Sprint Completion Gap Gate (SDLC-T00170 / FR-037 / AC-023)
# =============================================================================


class TestCompleteSprintGapGate:
    """Test sprint completion quality gate in complete_sprint."""

    @patch("a_sdlc.server.get_quality_report")
    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_blocked_when_gaps_exist(self, mock_get_db, mock_load_qc, mock_report):
        """Should return blocked status when unresolved gaps exist (AC-023)."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }

        mock_load_qc.return_value = QualityConfig(enabled=True)
        mock_report.return_value = {
            "status": "ok",
            "pass": False,
            "aggregate": {
                "orphaned_requirements": 2,
                "total_acs": 3,
                "verified_acs": 1,
            },
            "scope_drift": {"unlinked_count": 1},
        }

        # Clear any lingering waivers
        _sprint_waivers.pop("S-0001", None)

        result = complete_sprint("S-0001")

        assert result["status"] == "blocked"
        assert result["reason"] == "unresolved_gaps"
        assert result["gaps"]["orphaned_requirements"] == 2
        assert result["gaps"]["unverified_acs"] == 2  # total - verified
        assert result["gaps"]["unlinked_tasks"] == 1

    @patch("a_sdlc.server.get_quality_report")
    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_succeeds_when_no_gaps(self, mock_get_db, mock_load_qc, mock_report):
        """Should complete sprint when quality report passes (AC-023)."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = []
        db.list_tasks_by_sprint.return_value = []
        db.update_sprint.return_value = {
            "id": "S-0001", "status": "completed",
        }

        mock_load_qc.return_value = QualityConfig(enabled=True)
        mock_report.return_value = {
            "status": "ok",
            "pass": True,
            "aggregate": {
                "orphaned_requirements": 0,
                "total_acs": 0,
                "verified_acs": 0,
            },
            "scope_drift": {"unlinked_count": 0},
        }

        _sprint_waivers.pop("S-0001", None)

        result = complete_sprint("S-0001")

        assert result["status"] == "completed"
        db.update_sprint.assert_called_once_with("S-0001", status="completed")

    @patch("a_sdlc.server.get_db")
    def test_waiver_bypasses_gap_check(self, mock_get_db):
        """Should allow completion when waiver is active (AC-023)."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = []
        db.list_tasks_by_sprint.return_value = []
        db.update_sprint.return_value = {
            "id": "S-0001", "status": "completed",
        }

        # Place an active waiver
        _sprint_waivers["S-0001"] = {
            "sprint_id": "S-0001",
            "reason": "Acceptable for MVP",
            "waived_at": "2025-01-01T00:00:00+00:00",
        }

        try:
            result = complete_sprint("S-0001")
            assert result["status"] == "completed"
            db.update_sprint.assert_called_once_with("S-0001", status="completed")
        finally:
            _sprint_waivers.pop("S-0001", None)

    @patch("a_sdlc.server.get_db")
    def test_force_bypasses_gap_check(self, mock_get_db):
        """Should allow completion when force=True regardless of gaps."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = []
        db.list_tasks_by_sprint.return_value = []
        db.update_sprint.return_value = {
            "id": "S-0001", "status": "completed",
        }

        _sprint_waivers.pop("S-0001", None)

        result = complete_sprint("S-0001", force=True)

        assert result["status"] == "completed"

    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_no_quality_config_no_gate(self, mock_get_db, mock_load_qc):
        """Should complete sprint without gate when quality is disabled (AC-007)."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = []
        db.list_tasks_by_sprint.return_value = []
        db.update_sprint.return_value = {
            "id": "S-0001", "status": "completed",
        }

        # Quality disabled (default)
        mock_load_qc.return_value = QualityConfig(enabled=False)

        _sprint_waivers.pop("S-0001", None)

        result = complete_sprint("S-0001")

        assert result["status"] == "completed"

    @patch("a_sdlc.server.load_quality_config")
    @patch("a_sdlc.server.get_db")
    def test_config_load_failure_is_fail_open(self, mock_get_db, mock_load_qc):
        """Should complete sprint when config loading raises an exception (fail-open)."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_sprint.return_value = {
            "id": "S-0001", "project_id": "proj", "status": "active",
        }
        db.get_sprint_prds.return_value = []
        db.list_tasks_by_sprint.return_value = []
        db.update_sprint.return_value = {
            "id": "S-0001", "status": "completed",
        }

        mock_load_qc.side_effect = Exception("Config file corrupted")

        _sprint_waivers.pop("S-0001", None)

        result = complete_sprint("S-0001")

        assert result["status"] == "completed"


# =============================================================================
# Waive Sprint Quality (SDLC-T00170 / FR-037 / AC-023)
# =============================================================================


class TestWaiveSprintQuality:
    """Test waive_sprint_quality MCP tool."""

    @patch("a_sdlc.server.get_db")
    def test_successful_waiver(self, mock_get_db):
        """Should store waiver with reason and timestamp."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_sprint.return_value = {"id": "S-0001", "project_id": "proj"}

        _sprint_waivers.pop("S-0001", None)

        try:
            result = waive_sprint_quality("S-0001", "Acceptable for MVP release")

            assert result["status"] == "ok"
            assert result["waiver"]["sprint_id"] == "S-0001"
            assert result["waiver"]["reason"] == "Acceptable for MVP release"
            assert "waived_at" in result["waiver"]
            assert "S-0001" in _sprint_waivers
        finally:
            _sprint_waivers.pop("S-0001", None)

    @patch("a_sdlc.server.get_db")
    def test_sprint_not_found(self, mock_get_db):
        """Should return error when sprint does not exist."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_sprint.return_value = None

        result = waive_sprint_quality("NONEXISTENT", "reason")

        assert result["status"] == "error"
        assert "Sprint not found" in result["message"]

    @patch("a_sdlc.server.get_db")
    def test_empty_reason_rejected(self, mock_get_db):
        """Should reject waiver with empty or whitespace-only reason."""
        db = MagicMock()
        mock_get_db.return_value = db
        db.get_sprint.return_value = {"id": "S-0001", "project_id": "proj"}

        result = waive_sprint_quality("S-0001", "   ")

        assert result["status"] == "error"
        assert "non-empty reason" in result["message"]
