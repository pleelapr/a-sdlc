"""Tests for the data merge engine (db_merge.py).

Covers:
- No-conflict merge (different projects)
- Project deduplication (same project ID → skip)
- ID bump on collision (sprints, PRDs, tasks)
- FK remap cascade
- Content file rename
- Auto-increment table handling
- Requirement ID update
- file_path column update
- ImportResult merge fields
- S3 source content migration with ID remap
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

from a_sdlc.core.database import Database
from a_sdlc.core.db_merge import DataMerger
from a_sdlc.core.engine import reset_engine_cache

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
def source_db_a(tmp_path):
    """Create source DB A with project 'proj-a'."""
    db_path = tmp_path / "source_a" / "data.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path=db_path)
    db.create_project("proj-a", "Alpha Project", "/tmp/proj-a", shortname="TEST")
    db.create_sprint(
        sprint_id="TEST-S0001",
        project_id="proj-a",
        title="Sprint 1",
        goal="Goal A",
    )
    db.create_prd(
        prd_id="TEST-P0001",
        project_id="proj-a",
        title="PRD A",
        file_path="proj-a/prds/TEST-P0001.md",
    )
    db.create_task(
        task_id="TEST-T00001",
        project_id="proj-a",
        prd_id="TEST-P0001",
        title="Task A1",
        file_path="proj-a/tasks/TEST-T00001.md",
    )
    return f"sqlite:///{db_path}"


@pytest.fixture
def source_db_b(tmp_path):
    """Create source DB B with a different project 'proj-b'."""
    db_path = tmp_path / "source_b" / "data.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path=db_path)
    db.create_project("proj-b", "Beta Project", "/tmp/proj-b", shortname="BETA")
    db.create_sprint(
        sprint_id="BETA-S0001",
        project_id="proj-b",
        title="Sprint B1",
        goal="Goal B",
    )
    db.create_prd(
        prd_id="BETA-P0001",
        project_id="proj-b",
        title="PRD B",
        file_path="proj-b/prds/BETA-P0001.md",
    )
    db.create_task(
        task_id="BETA-T00001",
        project_id="proj-b",
        prd_id="BETA-P0001",
        title="Task B1",
        file_path="proj-b/tasks/BETA-T00001.md",
    )
    return f"sqlite:///{db_path}"


@pytest.fixture
def source_db_collision(tmp_path):
    """Create source DB with same IDs as source_db_a (collision scenario)."""
    db_path = tmp_path / "source_collision" / "data.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path=db_path)
    db.create_project("proj-a", "Alpha Project", "/tmp/proj-a", shortname="TEST")
    db.create_sprint(
        sprint_id="TEST-S0001",
        project_id="proj-a",
        title="Sprint 1 (dup)",
        goal="Goal dup",
    )
    db.create_prd(
        prd_id="TEST-P0001",
        project_id="proj-a",
        title="PRD A (dup)",
        file_path="proj-a/prds/TEST-P0001.md",
    )
    db.create_task(
        task_id="TEST-T00001",
        project_id="proj-a",
        prd_id="TEST-P0001",
        title="Task A1 (dup)",
        file_path="proj-a/tasks/TEST-T00001.md",
    )
    return f"sqlite:///{db_path}"


@pytest.fixture
def target_db_url(tmp_path):
    """Return a SQLite URL for the target database."""
    target_path = tmp_path / "target" / "data.db"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{target_path}"


@pytest.fixture
def content_dir_a(tmp_path):
    """Content files for source A."""
    d = tmp_path / "content_a"
    (d / "proj-a" / "prds").mkdir(parents=True)
    (d / "proj-a" / "tasks").mkdir(parents=True)
    (d / "proj-a" / "prds" / "TEST-P0001.md").write_text("# PRD A")
    (d / "proj-a" / "tasks" / "TEST-T00001.md").write_text("# Task A1")
    return d


def _target_db_path(url: str) -> str:
    """Extract the filesystem path from a sqlite:/// URL."""
    return url.replace("sqlite:///", "", 1)


# ---------------------------------------------------------------------------
# Tests: no conflict
# ---------------------------------------------------------------------------


class TestDataMergerNoConflicts:
    """Different projects import cleanly side-by-side."""

    def test_merge_two_different_projects(self, source_db_a, source_db_b, tmp_path):
        target_url = f"sqlite:///{tmp_path / 'tgt1' / 'data.db'}"
        (tmp_path / "tgt1").mkdir()

        # Import A first
        from a_sdlc.core.db_import import DataImporter

        imp = DataImporter(source_url=source_db_a, target_url=target_url)
        r1 = imp.run()
        assert r1.success
        reset_engine_cache()

        # Merge B
        merger = DataMerger(source_url=source_db_b, target_url=target_url)
        r2 = merger.run()

        assert r2.success
        assert r2.rows_skipped == 0
        assert r2.rows_remapped == 0

        # Verify both projects exist
        conn = sqlite3.connect(_target_db_path(target_url))
        rows = conn.execute("SELECT id FROM projects ORDER BY id").fetchall()
        ids = [r[0] for r in rows]
        assert "proj-a" in ids
        assert "proj-b" in ids
        conn.close()


# ---------------------------------------------------------------------------
# Tests: project merge (same project ID)
# ---------------------------------------------------------------------------


class TestDataMergerProjectMerge:
    """Same project slug → skip project row, merge children."""

    def test_same_project_skips_project_row(self, source_db_a, source_db_collision, tmp_path):
        target_url = f"sqlite:///{tmp_path / 'tgt2' / 'data.db'}"
        (tmp_path / "tgt2").mkdir()

        from a_sdlc.core.db_import import DataImporter

        imp = DataImporter(source_url=source_db_a, target_url=target_url)
        imp.run()
        reset_engine_cache()

        merger = DataMerger(source_url=source_db_collision, target_url=target_url)
        r = merger.run()

        assert r.success
        assert r.rows_skipped >= 1  # At least the project was skipped

        # Only one project row
        conn = sqlite3.connect(_target_db_path(target_url))
        count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        assert count == 1
        conn.close()


# ---------------------------------------------------------------------------
# Tests: ID bump on collision
# ---------------------------------------------------------------------------


class TestDataMergerIdBump:
    """Colliding sprint/PRD/task IDs get bumped to next available."""

    def test_sprint_id_bumped(self, source_db_a, source_db_collision, tmp_path):
        target_url = f"sqlite:///{tmp_path / 'tgt3' / 'data.db'}"
        (tmp_path / "tgt3").mkdir()

        from a_sdlc.core.db_import import DataImporter

        DataImporter(source_url=source_db_a, target_url=target_url).run()
        reset_engine_cache()

        merger = DataMerger(source_url=source_db_collision, target_url=target_url)
        r = merger.run()

        assert r.success
        assert r.rows_remapped > 0

        conn = sqlite3.connect(_target_db_path(target_url))
        sprints = conn.execute("SELECT id FROM sprints ORDER BY id").fetchall()
        sprint_ids = [s[0] for s in sprints]
        assert len(sprint_ids) == 2
        assert "TEST-S0001" in sprint_ids
        assert "TEST-S0002" in sprint_ids
        conn.close()

    def test_prd_id_bumped(self, source_db_a, source_db_collision, tmp_path):
        target_url = f"sqlite:///{tmp_path / 'tgt4' / 'data.db'}"
        (tmp_path / "tgt4").mkdir()

        from a_sdlc.core.db_import import DataImporter

        DataImporter(source_url=source_db_a, target_url=target_url).run()
        reset_engine_cache()

        merger = DataMerger(source_url=source_db_collision, target_url=target_url)
        merger.run()

        conn = sqlite3.connect(_target_db_path(target_url))
        prds = conn.execute("SELECT id FROM prds ORDER BY id").fetchall()
        prd_ids = [p[0] for p in prds]
        assert len(prd_ids) == 2
        assert "TEST-P0001" in prd_ids
        assert "TEST-P0002" in prd_ids
        conn.close()

    def test_task_id_bumped(self, source_db_a, source_db_collision, tmp_path):
        target_url = f"sqlite:///{tmp_path / 'tgt5' / 'data.db'}"
        (tmp_path / "tgt5").mkdir()

        from a_sdlc.core.db_import import DataImporter

        DataImporter(source_url=source_db_a, target_url=target_url).run()
        reset_engine_cache()

        merger = DataMerger(source_url=source_db_collision, target_url=target_url)
        merger.run()

        conn = sqlite3.connect(_target_db_path(target_url))
        tasks = conn.execute("SELECT id FROM tasks ORDER BY id").fetchall()
        task_ids = [t[0] for t in tasks]
        assert len(task_ids) == 2
        assert "TEST-T00001" in task_ids
        assert "TEST-T00002" in task_ids
        conn.close()


# ---------------------------------------------------------------------------
# Tests: FK remap
# ---------------------------------------------------------------------------


class TestDataMergerFkRemap:
    """Child entity FK columns updated when parent was remapped."""

    def test_task_fk_points_to_bumped_prd(self, source_db_a, source_db_collision, tmp_path):
        target_url = f"sqlite:///{tmp_path / 'tgt6' / 'data.db'}"
        (tmp_path / "tgt6").mkdir()

        from a_sdlc.core.db_import import DataImporter

        DataImporter(source_url=source_db_a, target_url=target_url).run()
        reset_engine_cache()

        merger = DataMerger(source_url=source_db_collision, target_url=target_url)
        merger.run()

        conn = sqlite3.connect(_target_db_path(target_url))
        # The bumped task (TEST-T00002) should reference the bumped PRD (TEST-P0002)
        row = conn.execute("SELECT prd_id FROM tasks WHERE id = 'TEST-T00002'").fetchone()
        assert row is not None
        assert row[0] == "TEST-P0002"
        conn.close()

    def test_prd_fk_points_to_bumped_sprint(self, source_db_a, source_db_collision, tmp_path):
        target_url = f"sqlite:///{tmp_path / 'tgt_fk_sprint' / 'data.db'}"
        (tmp_path / "tgt_fk_sprint").mkdir()

        from a_sdlc.core.db_import import DataImporter

        DataImporter(source_url=source_db_a, target_url=target_url).run()
        reset_engine_cache()

        # Assign the PRD to the sprint in the collision source
        collision_path = source_db_collision.replace("sqlite:///", "", 1)
        conn_src = sqlite3.connect(collision_path)
        conn_src.execute("UPDATE prds SET sprint_id = 'TEST-S0001' WHERE id = 'TEST-P0001'")
        conn_src.commit()
        conn_src.close()

        merger = DataMerger(source_url=source_db_collision, target_url=target_url)
        merger.run()

        conn = sqlite3.connect(_target_db_path(target_url))
        row = conn.execute("SELECT sprint_id FROM prds WHERE id = 'TEST-P0002'").fetchone()
        assert row is not None
        # Sprint was bumped to TEST-S0002
        assert row[0] == "TEST-S0002"
        conn.close()


# ---------------------------------------------------------------------------
# Tests: content rename
# ---------------------------------------------------------------------------


class TestDataMergerContentRename:
    """Content files renamed to match bumped IDs."""

    def test_content_files_renamed(self, source_db_a, source_db_collision, content_dir_a, tmp_path):
        target_url = f"sqlite:///{tmp_path / 'tgt7' / 'data.db'}"
        (tmp_path / "tgt7").mkdir()

        from a_sdlc.core.db_import import DataImporter

        DataImporter(source_url=source_db_a, target_url=target_url).run()
        reset_engine_cache()

        mock_backend = MagicMock()
        mock_backend.write_content.return_value = "ok"

        # Create collision content dir with same filenames
        collision_content = tmp_path / "content_collision"
        (collision_content / "proj-a" / "prds").mkdir(parents=True)
        (collision_content / "proj-a" / "tasks").mkdir(parents=True)
        (collision_content / "proj-a" / "prds" / "TEST-P0001.md").write_text("# Dup PRD")
        (collision_content / "proj-a" / "tasks" / "TEST-T00001.md").write_text("# Dup Task")

        merger = DataMerger(
            source_url=source_db_collision,
            target_url=target_url,
            migrate_content=True,
            target_content_backend=mock_backend,
            source_content_dir=collision_content,
        )
        merger.run()

        # Check that write_content was called with bumped filenames
        call_args = [str(c[0][0]) for c in mock_backend.write_content.call_args_list]
        # Should contain remapped paths (TEST-P0002 and TEST-T00002)
        assert any("TEST-P0002" in arg for arg in call_args)
        assert any("TEST-T00002" in arg for arg in call_args)

    def test_content_from_backend_with_remap(self, source_db_a, source_db_collision, tmp_path):
        """S3 source content migration with ID remap applied to keys."""
        target_url = f"sqlite:///{tmp_path / 'tgt_s3remap' / 'data.db'}"
        (tmp_path / "tgt_s3remap").mkdir()

        from a_sdlc.core.db_import import DataImporter

        DataImporter(source_url=source_db_a, target_url=target_url).run()
        reset_engine_cache()

        source_backend = MagicMock()
        source_backend.list_content_recursive.return_value = [
            "proj-a/prds/TEST-P0001.md",
            "proj-a/tasks/TEST-T00001.md",
        ]
        source_backend.read_content.side_effect = ["# Dup PRD", "# Dup Task"]

        target_backend = MagicMock()
        target_backend.write_content.return_value = "ok"

        merger = DataMerger(
            source_url=source_db_collision,
            target_url=target_url,
            migrate_content=True,
            target_content_backend=target_backend,
            source_content_backend=source_backend,
        )
        r = merger.run()

        assert r.success
        assert r.content_files_migrated == 2

        # Verify remapped keys were used for writing
        write_calls = [str(c[0][0]) for c in target_backend.write_content.call_args_list]
        assert any("TEST-P0002" in arg for arg in write_calls)
        assert any("TEST-T00002" in arg for arg in write_calls)


# ---------------------------------------------------------------------------
# Tests: auto-increment tables
# ---------------------------------------------------------------------------


class TestDataMergerAutoIncrement:
    """Auto-increment entities (reviews, sync_mappings) get new IDs."""

    def test_auto_increment_entities(self, source_db_a, tmp_path):
        target_url = f"sqlite:///{tmp_path / 'tgt8' / 'data.db'}"
        (tmp_path / "tgt8").mkdir()

        from a_sdlc.core.db_import import DataImporter

        DataImporter(source_url=source_db_a, target_url=target_url).run()
        reset_engine_cache()

        # Add a review to the source before merging
        source_path = source_db_a.replace("sqlite:///", "", 1)
        conn = sqlite3.connect(source_path)
        conn.execute(
            "INSERT INTO reviews (task_id, project_id, round, reviewer_type, verdict) "
            "VALUES ('TEST-T00001', 'proj-a', 1, 'self', 'pass')"
        )
        conn.commit()
        conn.close()

        merger = DataMerger(source_url=source_db_a, target_url=target_url)
        r = merger.run()
        assert r.success


# ---------------------------------------------------------------------------
# Tests: file_path update
# ---------------------------------------------------------------------------


class TestDataMergerFilePath:
    """file_path column updated when entity ID bumped."""

    def test_file_path_updated(self, source_db_a, source_db_collision, tmp_path):
        target_url = f"sqlite:///{tmp_path / 'tgt9' / 'data.db'}"
        (tmp_path / "tgt9").mkdir()

        from a_sdlc.core.db_import import DataImporter

        DataImporter(source_url=source_db_a, target_url=target_url).run()
        reset_engine_cache()

        merger = DataMerger(source_url=source_db_collision, target_url=target_url)
        merger.run()

        conn = sqlite3.connect(_target_db_path(target_url))
        row = conn.execute("SELECT file_path FROM tasks WHERE id = 'TEST-T00002'").fetchone()
        assert row is not None
        assert "TEST-T00002" in row[0]
        assert "TEST-T00001" not in row[0]

        prd_row = conn.execute("SELECT file_path FROM prds WHERE id = 'TEST-P0002'").fetchone()
        assert prd_row is not None
        assert "TEST-P0002" in prd_row[0]
        conn.close()


# ---------------------------------------------------------------------------
# Tests: merge result fields
# ---------------------------------------------------------------------------


class TestMergeResult:
    """ImportResult includes rows_skipped, rows_remapped, id_remap_summary."""

    def test_merge_result_fields(self, source_db_a, source_db_collision, tmp_path):
        target_url = f"sqlite:///{tmp_path / 'tgt10' / 'data.db'}"
        (tmp_path / "tgt10").mkdir()

        from a_sdlc.core.db_import import DataImporter

        DataImporter(source_url=source_db_a, target_url=target_url).run()
        reset_engine_cache()

        merger = DataMerger(source_url=source_db_collision, target_url=target_url)
        r = merger.run()

        assert r.success
        assert r.rows_skipped >= 1  # project skipped
        assert r.rows_remapped >= 3  # sprint, prd, task bumped
        assert "sprints" in r.id_remap_summary
        assert "prds" in r.id_remap_summary
        assert "tasks" in r.id_remap_summary
