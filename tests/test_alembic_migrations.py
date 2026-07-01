"""Tests for Alembic migration framework -- baseline v15 migration.

Validates that:
- The baseline migration creates all 15 tables with correct columns
- Foreign keys and unique constraints are present
- Indexes match the expected set from the v15 schema
- Downgrade drops all tables cleanly
- Re-upgrade after downgrade produces identical schema
- The migration is idempotent (stamp + upgrade is safe)
- SQLModel metadata matches the migration output
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config
from sqlmodel import SQLModel

import a_sdlc.core.models  # noqa: F401  -- populate SQLModel.metadata
from alembic import command

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def alembic_cfg(tmp_path: Path) -> Config:
    """Create an Alembic Config pointing at a temporary SQLite database."""
    db_path = tmp_path / "test_migration.db"
    url = f"sqlite:///{db_path}"

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))

    return cfg


@pytest.fixture
def migrated_db(alembic_cfg: Config) -> Config:
    """Run upgrade to head and return the config."""
    command.upgrade(alembic_cfg, "head")
    return alembic_cfg


def _get_connection(cfg: Config) -> sqlite3.Connection:
    """Get a raw sqlite3 connection from the alembic config URL."""
    url = cfg.get_main_option("sqlalchemy.url")
    assert url is not None
    # Extract path from sqlite:///path
    db_path = url.replace("sqlite:///", "")
    return sqlite3.connect(db_path)


def _get_tables(conn: sqlite3.Connection) -> set[str]:
    """Get all user table names from the database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return {row[0] for row in cursor.fetchall()}


def _get_indexes(conn: sqlite3.Connection) -> set[str]:
    """Get all user index names from the database."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name NOT LIKE 'sqlite_%' AND name IS NOT NULL"
    )
    return {row[0] for row in cursor.fetchall()}


def _get_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Get column names for a table."""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


def _get_foreign_keys(conn: sqlite3.Connection, table: str) -> list[dict]:
    """Get foreign key info for a table."""
    cursor = conn.execute(f"PRAGMA foreign_key_list({table})")
    return [
        {"table": row[2], "from": row[3], "to": row[4]}
        for row in cursor.fetchall()
    ]


# ---------------------------------------------------------------------------
# Expected schema constants
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "alembic_version",
    "schema_version",
    "projects",
    "sprints",
    "prds",
    "tasks",
    "designs",
    "sync_mappings",
    "external_config",
    "worktrees",
    "reviews",
    "audit_log",
    "requirements",
    "requirement_links",
    "ac_verifications",
    "challenge_records",
}

# All indexes from the v15 schema (named ones)
EXPECTED_INDEXES = {
    # projects (idx_projects_path dropped in migration 0003)
    "idx_projects_shortname",
    # sprints
    "idx_sprints_project",
    "idx_sprints_status",
    # prds
    "idx_prds_project",
    "idx_prds_status",
    "idx_prds_sprint",
    # tasks
    "idx_tasks_project",
    "idx_tasks_status",
    "idx_tasks_prd",
    # designs
    "idx_designs_prd",
    "idx_designs_project",
    # sync_mappings
    "idx_sync_entity",
    "idx_sync_external",
    # external_config
    "idx_external_config_project",
    # worktrees
    "idx_worktrees_project",
    "idx_worktrees_prd",
    "idx_worktrees_sprint",
    "idx_worktrees_status",
    # reviews
    "idx_reviews_task",
    "idx_reviews_project",
    # audit_log
    "idx_audit_log_project",
    "idx_audit_log_agent",
    "idx_audit_log_run",
    "idx_audit_log_action",
    # requirements
    "idx_requirements_prd",
    "idx_requirements_type",
    # ac_verifications
    "idx_ac_verifications_task",
    # challenge_records
    "idx_challenge_artifact",
}


# ---------------------------------------------------------------------------
# Tests: upgrade to head
# ---------------------------------------------------------------------------


class TestUpgrade:
    """Tests for the baseline migration upgrade path."""

    def test_upgrade_creates_all_tables(self, migrated_db: Config) -> None:
        """All 15 tables + alembic_version should exist after upgrade."""
        conn = _get_connection(migrated_db)
        tables = _get_tables(conn)
        conn.close()

        assert tables == EXPECTED_TABLES

    def test_schema_version_is_15(self, migrated_db: Config) -> None:
        """The schema_version table should contain version 15."""
        conn = _get_connection(migrated_db)
        cursor = conn.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 15

    def test_all_named_indexes_exist(self, migrated_db: Config) -> None:
        """All named indexes from the v15 schema should be present."""
        conn = _get_connection(migrated_db)
        indexes = _get_indexes(conn)
        conn.close()

        missing = EXPECTED_INDEXES - indexes
        assert not missing, f"Missing indexes: {missing}"

    def test_alembic_version_at_head(self, migrated_db: Config) -> None:
        """The alembic_version table should be at the latest revision."""
        conn = _get_connection(migrated_db)
        cursor = conn.execute("SELECT version_num FROM alembic_version")
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "0003"


# ---------------------------------------------------------------------------
# Tests: table columns
# ---------------------------------------------------------------------------


class TestTableColumns:
    """Verify that key tables have the expected columns."""

    @pytest.mark.parametrize(
        "table,expected_cols",
        [
            (
                "projects",
                ["id", "shortname", "name", "created_at", "last_accessed"],
            ),
            (
                "prds",
                [
                    "id",
                    "project_id",
                    "sprint_id",
                    "title",
                    "file_path",
                    "status",
                    "source",
                    "version",
                    "created_at",
                    "updated_at",
                    "ready_at",
                    "split_at",
                    "completed_at",
                ],
            ),
            (
                "tasks",
                [
                    "id",
                    "project_id",
                    "prd_id",
                    "title",
                    "file_path",
                    "status",
                    "priority",
                    "component",
                    "created_at",
                    "updated_at",
                    "started_at",
                    "completed_at",
                ],
            ),
            (
                "sprints",
                [
                    "id",
                    "project_id",
                    "title",
                    "goal",
                    "status",
                    "external_id",
                    "external_url",
                    "created_at",
                    "started_at",
                    "completed_at",
                ],
            ),
        ],
    )
    def test_table_has_expected_columns(
        self,
        migrated_db: Config,
        table: str,
        expected_cols: list[str],
    ) -> None:
        """Each table should have exactly the expected columns."""
        conn = _get_connection(migrated_db)
        actual_cols = _get_columns(conn, table)
        conn.close()

        assert actual_cols == expected_cols, (
            f"Table '{table}' columns mismatch.\n"
            f"  Expected: {expected_cols}\n"
            f"  Actual:   {actual_cols}"
        )


# ---------------------------------------------------------------------------
# Tests: foreign keys
# ---------------------------------------------------------------------------


class TestForeignKeys:
    """Verify foreign key constraints on key tables."""

    def test_prds_foreign_keys(self, migrated_db: Config) -> None:
        """PRDs should have FKs to projects and sprints."""
        conn = _get_connection(migrated_db)
        fks = _get_foreign_keys(conn, "prds")
        conn.close()

        fk_targets = {(fk["from"], fk["table"]) for fk in fks}
        assert ("project_id", "projects") in fk_targets
        assert ("sprint_id", "sprints") in fk_targets

    def test_tasks_foreign_keys(self, migrated_db: Config) -> None:
        """Tasks should have FKs to projects and prds."""
        conn = _get_connection(migrated_db)
        fks = _get_foreign_keys(conn, "tasks")
        conn.close()

        fk_targets = {(fk["from"], fk["table"]) for fk in fks}
        assert ("project_id", "projects") in fk_targets
        assert ("prd_id", "prds") in fk_targets


# ---------------------------------------------------------------------------
# Tests: downgrade
# ---------------------------------------------------------------------------


class TestDowngrade:
    """Tests for the downgrade path."""

    def test_downgrade_drops_all_tables(self, migrated_db: Config) -> None:
        """Downgrade to base should drop all 15 tables."""
        command.downgrade(migrated_db, "base")

        conn = _get_connection(migrated_db)
        tables = _get_tables(conn)
        conn.close()

        # Only alembic_version should remain (Alembic manages it)
        # After downgrade to base, alembic_version row is removed but table may persist
        remaining_user_tables = tables - {"alembic_version"}
        assert not remaining_user_tables, (
            f"Tables remaining after downgrade: {remaining_user_tables}"
        )

    def test_re_upgrade_after_downgrade(self, migrated_db: Config) -> None:
        """Downgrade then re-upgrade should produce the same schema."""
        command.downgrade(migrated_db, "base")
        command.upgrade(migrated_db, "head")

        conn = _get_connection(migrated_db)
        tables = _get_tables(conn)
        indexes = _get_indexes(conn)
        conn.close()

        assert tables == EXPECTED_TABLES
        missing_indexes = EXPECTED_INDEXES - indexes
        assert not missing_indexes, f"Missing indexes after re-upgrade: {missing_indexes}"


# ---------------------------------------------------------------------------
# Tests: unique constraints
# ---------------------------------------------------------------------------


class TestUniqueConstraints:
    """Verify that unique constraints are enforced."""

    def test_sync_mappings_unique(self, migrated_db: Config) -> None:
        """sync_mappings should enforce UNIQUE(entity_type, local_id, external_system)."""
        conn = _get_connection(migrated_db)
        conn.execute("PRAGMA foreign_keys = OFF")

        conn.execute(
            "INSERT INTO sync_mappings (entity_type, local_id, external_system, external_id) "
            "VALUES ('task', 'T1', 'linear', 'ext-1')"
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sync_mappings (entity_type, local_id, external_system, external_id) "
                "VALUES ('task', 'T1', 'linear', 'ext-2')"
            )
        conn.close()

    def test_requirements_unique(self, migrated_db: Config) -> None:
        """requirements should enforce UNIQUE(prd_id, req_number)."""
        conn = _get_connection(migrated_db)
        conn.execute("PRAGMA foreign_keys = OFF")

        conn.execute(
            "INSERT INTO requirements (id, prd_id, req_type, req_number, summary) "
            "VALUES ('r1', 'p1', 'functional', 'FR-001', 'Summary')"
        )

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO requirements (id, prd_id, req_type, req_number, summary) "
                "VALUES ('r2', 'p1', 'functional', 'FR-001', 'Duplicate')"
            )
        conn.close()



# ---------------------------------------------------------------------------
# Tests: metadata alignment
# ---------------------------------------------------------------------------


class TestMetadataAlignment:
    """Verify that SQLModel metadata aligns with migration output."""

    def test_all_model_tables_present_in_migration(self, migrated_db: Config) -> None:
        """Every table in SQLModel.metadata should exist in the migrated DB."""
        conn = _get_connection(migrated_db)
        db_tables = _get_tables(conn)
        conn.close()

        model_tables = set(SQLModel.metadata.tables.keys())

        # All model tables should be in the DB
        missing = model_tables - db_tables
        assert not missing, f"Model tables not in migration: {missing}"

    def test_model_column_count_matches(self, migrated_db: Config) -> None:
        """Each model table should have the same number of columns."""
        conn = _get_connection(migrated_db)

        for table_name, table_obj in SQLModel.metadata.tables.items():
            db_cols = _get_columns(conn, table_name)
            model_cols = [c.name for c in table_obj.columns]

            assert len(db_cols) == len(model_cols), (
                f"Column count mismatch for '{table_name}': "
                f"DB has {len(db_cols)} ({db_cols}), "
                f"Model has {len(model_cols)} ({model_cols})"
            )

        conn.close()


# ---------------------------------------------------------------------------
# Tests: data insertion smoke test
# ---------------------------------------------------------------------------


class TestDataInsertion:
    """Smoke tests to verify the schema supports basic CRUD operations."""

    def test_insert_project_and_related_entities(self, migrated_db: Config) -> None:
        """Should be able to insert a project with related sprints, PRDs, tasks."""
        conn = _get_connection(migrated_db)
        conn.execute("PRAGMA foreign_keys = ON")

        # Insert project
        conn.execute(
            "INSERT INTO projects (id, shortname, name) "
            "VALUES ('proj-1', 'TEST', 'Test Project')"
        )

        # Insert sprint
        conn.execute(
            "INSERT INTO sprints (id, project_id, title, goal) "
            "VALUES ('TEST-S0001', 'proj-1', 'Sprint 1', 'First sprint')"
        )

        # Insert PRD linked to sprint
        conn.execute(
            "INSERT INTO prds (id, project_id, sprint_id, title) "
            "VALUES ('TEST-P0001', 'proj-1', 'TEST-S0001', 'Test PRD')"
        )

        # Insert task linked to PRD
        conn.execute(
            "INSERT INTO tasks (id, project_id, prd_id, title) "
            "VALUES ('TEST-T00001', 'proj-1', 'TEST-P0001', 'Task 1')"
        )

        conn.commit()

        # Verify we can query across relationships
        cursor = conn.execute(
            "SELECT t.id, t.title, p.title as prd_title, s.title as sprint_title "
            "FROM tasks t "
            "JOIN prds p ON t.prd_id = p.id "
            "JOIN sprints s ON p.sprint_id = s.id "
            "WHERE t.id = 'TEST-T00001'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "TEST-T00001"
        assert row[1] == "Task 1"
        assert row[2] == "Test PRD"
        assert row[3] == "Sprint 1"

        conn.close()



# ---------------------------------------------------------------------------
# Tests: offline mode
# ---------------------------------------------------------------------------


class TestOfflineMode:
    """Test that offline migration SQL generation works."""

    def test_offline_upgrade_generates_sql(
        self, alembic_cfg: Config, capsys: pytest.CaptureFixture
    ) -> None:
        """Offline mode should generate SQL without connecting to DB."""
        alembic_cfg.set_main_option("sqlalchemy.url", "sqlite:///offline_test.db")

        # Run in offline mode by capturing SQL output
        command.upgrade(alembic_cfg, "head", sql=True)

        captured = capsys.readouterr()
        output = captured.out

        # Should contain CREATE TABLE statements
        assert "CREATE TABLE" in output
        assert "projects" in output
        assert "schema_version" in output
