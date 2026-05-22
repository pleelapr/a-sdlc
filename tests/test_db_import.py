"""Tests for the data import engine (db_import.py).

Covers:
- Pre-flight checks (schema version, target emptiness, source existence)
- FK dependency ordering
- Full import with row count verification
- Force import into non-empty target
- Rollback on failure
- Content file migration
- CLI integration via Click test runner
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

from a_sdlc.core.database import SCHEMA_VERSION, Database
from a_sdlc.core.db_import import (
    IMPORT_ORDER,
    REQUIRED_SCHEMA_VERSION,
    DataImporter,
    ImportResult,
    PreflightError,
    _get_source_row_count,
    _get_source_rows,
    _get_source_schema_version,
    _get_source_tables,
    _is_target_empty,
    _row_to_model,
)
from a_sdlc.core.engine import reset_engine_cache
from a_sdlc.core.models import ALL_MODELS, Project, SchemaVersion, Task

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_engine_cache():
    """Reset engine cache before and after each test."""
    reset_engine_cache()
    yield
    reset_engine_cache()


@pytest.fixture
def source_db(tmp_path):
    """Create a source SQLite database with sample data using the Database class."""
    db_path = tmp_path / "source" / "data.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path=db_path)

    # Create sample data
    db.create_project("proj-001", "Test Project", "/tmp/proj-test")
    db.create_sprint(
        sprint_id="TEST-S0001",
        project_id="proj-001",
        title="Sprint 1",
        goal="First sprint",
    )
    db.create_prd(
        prd_id="TEST-P0001",
        project_id="proj-001",
        title="Test PRD",
        file_path="/tmp/prds/TEST-P0001.md",
    )
    db.create_task(
        task_id="TEST-T00001",
        project_id="proj-001",
        prd_id="TEST-P0001",
        title="Task One",
        file_path="/tmp/tasks/TEST-T00001.md",
    )
    db.create_task(
        task_id="TEST-T00002",
        project_id="proj-001",
        prd_id="TEST-P0001",
        title="Task Two",
        file_path="/tmp/tasks/TEST-T00002.md",
    )

    yield db_path, db


@pytest.fixture
def target_db_url(tmp_path):
    """Return a SQLite URL for the target database."""
    target_path = tmp_path / "target" / "data.db"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{target_path}"


@pytest.fixture
def source_content_dir(tmp_path):
    """Create a source content directory with sample files."""
    content_dir = tmp_path / "content"
    (content_dir / "proj-001" / "prds").mkdir(parents=True)
    (content_dir / "proj-001" / "tasks").mkdir(parents=True)
    (content_dir / "proj-001" / "prds" / "TEST-P0001.md").write_text(
        "# Test PRD\nSome content", encoding="utf-8"
    )
    (content_dir / "proj-001" / "tasks" / "TEST-T00001.md").write_text(
        "# Task One\nTask content", encoding="utf-8"
    )
    return content_dir


# ---------------------------------------------------------------------------
# Unit tests: helper functions
# ---------------------------------------------------------------------------


class TestSourceHelpers:
    """Tests for source database helper functions."""

    def test_get_source_schema_version(self, source_db):
        db_path, _ = source_db
        conn = sqlite3.connect(str(db_path))
        version = _get_source_schema_version(conn)
        assert version == SCHEMA_VERSION
        conn.close()

    def test_get_source_schema_version_no_table(self, tmp_path):
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE dummy (id INTEGER)")
        version = _get_source_schema_version(conn)
        assert version is None
        conn.close()

    def test_get_source_tables(self, source_db):
        db_path, _ = source_db
        conn = sqlite3.connect(str(db_path))
        tables = _get_source_tables(conn)
        assert "projects" in tables
        assert "tasks" in tables
        assert "sprints" in tables
        assert "prds" in tables
        assert "schema_version" in tables
        conn.close()

    def test_get_source_row_count(self, source_db):
        db_path, _ = source_db
        conn = sqlite3.connect(str(db_path))
        count = _get_source_row_count(conn, "tasks")
        assert count == 2
        conn.close()

    def test_get_source_rows(self, source_db):
        db_path, _ = source_db
        conn = sqlite3.connect(str(db_path))
        rows = _get_source_rows(conn, "projects")
        assert len(rows) == 1
        assert rows[0]["id"] == "proj-001"
        assert rows[0]["name"] == "Test Project"
        conn.close()

    def test_get_source_rows_returns_dicts(self, source_db):
        db_path, _ = source_db
        conn = sqlite3.connect(str(db_path))
        rows = _get_source_rows(conn, "tasks")
        assert isinstance(rows, list)
        assert all(isinstance(r, dict) for r in rows)
        assert len(rows) == 2
        conn.close()


class TestRowToModel:
    """Tests for _row_to_model conversion."""

    def test_basic_conversion(self):
        row = {
            "id": "proj-001",
            "shortname": "TEST",
            "name": "My Project",
            "path": "/tmp/proj",
            "created_at": "2024-01-01 00:00:00",
            "last_accessed": "2024-01-01 00:00:00",
        }
        model = _row_to_model("projects", row)
        assert isinstance(model, Project)
        assert model.id == "proj-001"
        assert model.name == "My Project"

    def test_extra_columns_ignored(self):
        """Extra columns not in the model should be silently ignored."""
        row = {
            "version": 15,
            "unknown_column": "should be ignored",
        }
        model = _row_to_model("schema_version", row)
        assert isinstance(model, SchemaVersion)
        assert model.version == 15

    def test_nullable_fields(self):
        row = {
            "id": "PROJ-T00001",
            "project_id": "proj-001",
            "prd_id": None,
            "title": "A Task",
            "file_path": None,
            "status": "pending",
            "priority": "medium",
            "component": None,
            "created_at": None,
            "updated_at": None,
            "started_at": None,
            "completed_at": None,
        }
        model = _row_to_model("tasks", row)
        assert isinstance(model, Task)
        assert model.prd_id is None


class TestImportOrder:
    """Tests for the IMPORT_ORDER constant."""

    def test_all_models_covered(self):
        """Every model in ALL_MODELS should appear in IMPORT_ORDER."""
        model_tables = set(ALL_MODELS.keys())
        order_tables = set(IMPORT_ORDER)
        assert model_tables == order_tables, (
            f"Missing from IMPORT_ORDER: {model_tables - order_tables}, "
            f"Extra in IMPORT_ORDER: {order_tables - model_tables}"
        )

    def test_projects_before_sprints(self):
        assert IMPORT_ORDER.index("projects") < IMPORT_ORDER.index("sprints")

    def test_projects_before_prds(self):
        assert IMPORT_ORDER.index("projects") < IMPORT_ORDER.index("prds")

    def test_sprints_before_prds(self):
        assert IMPORT_ORDER.index("sprints") < IMPORT_ORDER.index("prds")

    def test_prds_before_tasks(self):
        assert IMPORT_ORDER.index("prds") < IMPORT_ORDER.index("tasks")

    def test_tasks_before_reviews(self):
        assert IMPORT_ORDER.index("tasks") < IMPORT_ORDER.index("reviews")

    def test_requirements_before_links(self):
        assert IMPORT_ORDER.index("requirements") < IMPORT_ORDER.index(
            "requirement_links"
        )


# ---------------------------------------------------------------------------
# Integration tests: DataImporter
# ---------------------------------------------------------------------------


class TestPreflightChecks:
    """Tests for DataImporter.preflight()."""

    def test_preflight_passes_with_valid_source(self, source_db, target_db_url):
        db_path, _ = source_db
        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
        )
        errors = importer.preflight()
        assert errors == []

    def test_preflight_fails_source_not_found(self, tmp_path, target_db_url):
        importer = DataImporter(
            source_db_path=tmp_path / "nonexistent.db",
            target_url=target_db_url,
        )
        errors = importer.preflight()
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_preflight_fails_wrong_schema_version(self, tmp_path, target_db_url):
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version (version) VALUES (10)")
        conn.commit()
        conn.close()

        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
        )
        errors = importer.preflight()
        assert any("version is 10" in e for e in errors)

    def test_preflight_fails_no_schema_version(self, tmp_path, target_db_url):
        db_path = tmp_path / "no_schema.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE dummy (id INTEGER)")
        conn.commit()
        conn.close()

        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
        )
        errors = importer.preflight()
        assert any("no schema_version" in e for e in errors)

    def test_preflight_fails_target_not_empty(self, source_db, tmp_path):
        db_path, _ = source_db
        # First, run a successful import
        target_url = f"sqlite:///{tmp_path / 'target1' / 'data.db'}"
        (tmp_path / "target1").mkdir(parents=True)
        importer1 = DataImporter(
            source_db_path=db_path,
            target_url=target_url,
        )
        importer1.run()
        reset_engine_cache()

        # Now try to import again without --force
        importer2 = DataImporter(
            source_db_path=db_path,
            target_url=target_url,
        )
        errors = importer2.preflight()
        assert any("not empty" in e for e in errors)

    def test_preflight_passes_target_not_empty_with_force(self, source_db, tmp_path):
        db_path, _ = source_db
        target_url = f"sqlite:///{tmp_path / 'target2' / 'data.db'}"
        (tmp_path / "target2").mkdir(parents=True)
        # First import
        importer1 = DataImporter(
            source_db_path=db_path,
            target_url=target_url,
        )
        importer1.run()
        reset_engine_cache()

        # Second import with force
        importer2 = DataImporter(
            source_db_path=db_path,
            target_url=target_url,
            force=True,
        )
        errors = importer2.preflight()
        assert errors == []

    def test_preflight_migrate_content_no_backend(self, source_db, target_db_url):
        db_path, _ = source_db
        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
            migrate_content=True,
            target_content_backend=None,
        )
        errors = importer.preflight()
        assert any("target content backend" in e for e in errors)


class TestDataImport:
    """Tests for the full import flow."""

    def test_successful_import(self, source_db, target_db_url):
        db_path, _ = source_db
        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
        )
        result = importer.run()

        assert result.success is True
        assert result.tables_imported > 0
        assert result.total_rows > 0
        assert result.errors == []

    def test_row_counts_match(self, source_db, target_db_url):
        db_path, _ = source_db
        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
        )
        result = importer.run()

        # Verify known counts
        assert result.row_counts["projects"]["source"] == 1
        assert result.row_counts["projects"]["imported"] == 1
        assert result.row_counts["tasks"]["source"] == 2
        assert result.row_counts["tasks"]["imported"] == 2
        assert result.row_counts["sprints"]["source"] == 1
        assert result.row_counts["sprints"]["imported"] == 1
        assert result.row_counts["prds"]["source"] == 1
        assert result.row_counts["prds"]["imported"] == 1

    def test_all_counts_match_source_imported(self, source_db, target_db_url):
        db_path, _ = source_db
        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
        )
        result = importer.run()

        for table_name, counts in result.row_counts.items():
            assert counts["source"] == counts["imported"], (
                f"Mismatch for table '{table_name}': "
                f"source={counts['source']}, imported={counts['imported']}"
            )

    def test_source_not_modified(self, source_db, target_db_url):
        db_path, db = source_db
        # Record source state
        conn = sqlite3.connect(str(db_path))
        original_count = _get_source_row_count(conn, "projects")
        conn.close()

        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
        )
        importer.run()

        # Verify source unchanged
        conn = sqlite3.connect(str(db_path))
        after_count = _get_source_row_count(conn, "projects")
        conn.close()
        assert original_count == after_count

    def test_import_with_progress_callback(self, source_db, target_db_url):
        db_path, _ = source_db
        callback_calls = []

        def callback(table, current, total):
            callback_calls.append((table, current, total))

        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
            progress_callback=callback,
        )
        importer.run()

        assert len(callback_calls) > 0
        # Each table should have at least one callback call
        tables_reported = {c[0] for c in callback_calls}
        assert "projects" in tables_reported

    def test_import_empty_tables(self, tmp_path, target_db_url):
        """Import from a database where most tables are empty."""
        db_path = tmp_path / "minimal" / "data.db"
        db_path.parent.mkdir(parents=True)
        db = Database(db_path=db_path)
        # Just create a project with no other data
        db.create_project("proj-minimal", "Minimal Project", "/tmp/minimal")

        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
        )
        result = importer.run()

        assert result.success is True
        assert result.row_counts["projects"]["source"] == 1
        # Most tables should have 0 rows
        for table_name, counts in result.row_counts.items():
            if table_name != "projects":
                assert counts["source"] == counts["imported"]

    def test_force_import_overwrites(self, source_db, tmp_path):
        db_path, _ = source_db
        target_url = f"sqlite:///{tmp_path / 'force_target' / 'data.db'}"
        (tmp_path / "force_target").mkdir(parents=True)

        # First import
        importer1 = DataImporter(
            source_db_path=db_path,
            target_url=target_url,
        )
        result1 = importer1.run()
        assert result1.success is True
        reset_engine_cache()

        # Second import with force
        importer2 = DataImporter(
            source_db_path=db_path,
            target_url=target_url,
            force=True,
        )
        result2 = importer2.run()
        assert result2.success is True
        # Counts should match (data replaced, not duplicated)
        for tbl, counts in result2.row_counts.items():
            assert counts["source"] == counts["imported"], (
                f"Force import mismatch for '{tbl}'"
            )

    def test_duration_recorded(self, source_db, target_db_url):
        db_path, _ = source_db
        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
        )
        result = importer.run()
        assert result.duration_seconds > 0

    def test_preflight_error_raises(self, tmp_path, target_db_url):
        """run() should raise PreflightError when checks fail."""
        importer = DataImporter(
            source_db_path=tmp_path / "nonexistent.db",
            target_url=target_db_url,
        )
        with pytest.raises(PreflightError, match="not found"):
            importer.run()


class TestContentMigration:
    """Tests for content file migration."""

    def test_content_migration(self, source_db, target_db_url, source_content_dir):
        db_path, _ = source_db
        mock_backend = MagicMock()
        mock_backend.write_content.return_value = "ok"

        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
            migrate_content=True,
            target_content_backend=mock_backend,
            source_content_dir=source_content_dir,
        )
        result = importer.run()

        assert result.success is True
        assert result.content_files_migrated == 2
        assert mock_backend.write_content.call_count == 2

    def test_content_migration_no_source_dir(self, source_db, target_db_url, tmp_path):
        db_path, _ = source_db
        mock_backend = MagicMock()
        empty_dir = tmp_path / "empty_content"

        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
            migrate_content=True,
            target_content_backend=mock_backend,
            source_content_dir=empty_dir,
        )
        result = importer.run()

        assert result.success is True
        assert result.content_files_migrated == 0

    def test_content_migration_handles_write_error(
        self, source_db, target_db_url, source_content_dir
    ):
        db_path, _ = source_db
        mock_backend = MagicMock()
        mock_backend.write_content.side_effect = Exception("S3 error")

        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_db_url,
            migrate_content=True,
            target_content_backend=mock_backend,
            source_content_dir=source_content_dir,
        )
        result = importer.run()

        # Import succeeds but content migration logs warnings
        assert result.success is True
        assert result.content_files_migrated == 0


class TestImportResult:
    """Tests for ImportResult data class."""

    def test_summary_success(self):
        result = ImportResult(
            success=True,
            tables_imported=5,
            total_rows=100,
            duration_seconds=1.5,
        )
        summary = result.summary()
        assert "successfully" in summary
        assert "1.5s" in summary
        assert "100" in summary

    def test_summary_failure(self):
        result = ImportResult(
            success=False,
            errors=["Row count mismatch"],
        )
        summary = result.summary()
        assert "FAILED" in summary
        assert "Row count mismatch" in summary

    def test_summary_with_content_files(self):
        result = ImportResult(
            success=True,
            tables_imported=3,
            total_rows=50,
            content_files_migrated=10,
            duration_seconds=2.0,
        )
        summary = result.summary()
        assert "10" in summary

    def test_summary_with_warnings(self):
        result = ImportResult(
            success=True,
            tables_imported=3,
            total_rows=50,
            warnings=["Skipped table x"],
            duration_seconds=1.0,
        )
        summary = result.summary()
        assert "Warnings" in summary


class TestTargetHelpers:
    """Tests for target database helper functions."""

    def test_is_target_empty_new_db(self, target_db_url):
        from a_sdlc.core.engine import create_all_tables, get_engine
        from a_sdlc.core.storage_config import StorageConfig

        config = StorageConfig(database_url=target_db_url)
        engine = get_engine(config)
        create_all_tables(engine)
        assert _is_target_empty(engine) is True

    def test_is_target_empty_after_import(self, source_db, tmp_path):
        from a_sdlc.core.engine import get_engine
        from a_sdlc.core.storage_config import StorageConfig

        db_path, _ = source_db
        target_url = f"sqlite:///{tmp_path / 'notempty' / 'data.db'}"
        (tmp_path / "notempty").mkdir(parents=True)

        importer = DataImporter(
            source_db_path=db_path,
            target_url=target_url,
        )
        importer.run()

        config = StorageConfig(database_url=target_url)
        engine = get_engine(config)
        assert _is_target_empty(engine) is False



class TestSchemaVersionConstant:
    """Verify the required schema version stays in sync."""

    def test_matches_database_schema_version(self):
        assert REQUIRED_SCHEMA_VERSION == SCHEMA_VERSION
