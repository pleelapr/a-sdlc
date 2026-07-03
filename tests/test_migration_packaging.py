"""Tests that Alembic migrations are packaged and runnable from the package.

These guard the fix for the bug where migrations lived at the repo root
(``alembic/``) and never shipped in the wheel/Docker image, so startup
auto-migration silently skipped on every deploy. They assert the scripts are
importable as package resources and that the shared ``alembic_config`` helpers
resolve, run, stamp, and report against them correctly.
"""

from __future__ import annotations

import importlib.resources

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

import a_sdlc.core.models  # noqa: F401  -- populate SQLModel.metadata
from a_sdlc.core.alembic_config import (
    MIGRATIONS_DIR,
    MigrationSetupError,
    build_alembic_config,
    detect_stamp_revision,
    get_revision_info,
    run_upgrade_head,
)

# ---------------------------------------------------------------------------
# Packaging: migration files must be present as package resources
# ---------------------------------------------------------------------------


class TestMigrationsPackaged:
    """Migration scripts ship inside the a_sdlc package (not the repo root)."""

    def test_env_and_scripts_are_package_resources(self):
        base = importlib.resources.files("a_sdlc")
        for rel in (
            "migrations/env.py",
            "migrations/script.py.mako",
            "migrations/versions/0001_baseline_v15.py",
            "migrations/versions/0002_projects_path_nullable.py",
            "migrations/versions/0003_drop_projects_path.py",
        ):
            assert base.joinpath(rel).is_file(), f"missing packaged resource: {rel}"

    def test_migrations_dir_points_inside_package(self):
        assert MIGRATIONS_DIR.name == "migrations"
        assert MIGRATIONS_DIR.parent.name == "a_sdlc"
        assert (MIGRATIONS_DIR / "env.py").is_file()


# ---------------------------------------------------------------------------
# build_alembic_config
# ---------------------------------------------------------------------------


class TestBuildAlembicConfig:
    def test_sets_packaged_script_location(self, tmp_path):
        url = f"sqlite:///{tmp_path / 'x.db'}"
        cfg = build_alembic_config(url)
        loc = cfg.get_main_option("script_location")
        assert loc is not None
        # normalize separators for the assertion
        assert loc.replace("\\", "/").endswith("a_sdlc/migrations")
        assert cfg.get_main_option("sqlalchemy.url") == url

    def test_raises_when_migrations_missing(self, monkeypatch, tmp_path):
        import a_sdlc.core.alembic_config as mod

        monkeypatch.setattr(mod, "MIGRATIONS_DIR", tmp_path / "nope")
        with pytest.raises(MigrationSetupError, match="not found"):
            mod.build_alembic_config("sqlite:///whatever.db")

    def test_raises_on_empty_url(self):
        with pytest.raises(MigrationSetupError, match="No database URL"):
            build_alembic_config("")


# ---------------------------------------------------------------------------
# End-to-end upgrade from the packaged scripts
# ---------------------------------------------------------------------------


class TestUpgradeFromPackage:
    def test_upgrade_head_creates_full_schema(self, tmp_path, caplog):
        url = f"sqlite:///{tmp_path / 'e2e.db'}"
        cfg = build_alembic_config(url)
        command.upgrade(cfg, "head")

        insp = inspect(create_engine(url))
        tables = set(insp.get_table_names())
        assert "alembic_version" in tables
        assert len(tables) == 16  # 15 v15 tables + alembic_version

        info = get_revision_info(url)
        assert info["current"] == info["head"] == "0003"
        assert info["pending"] == 0


# ---------------------------------------------------------------------------
# detect_stamp_revision matrix
# ---------------------------------------------------------------------------


class TestDetectStampRevision:
    def test_empty_database_returns_none(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
        with engine.connect() as conn:
            assert detect_stamp_revision(conn) is None

    def test_create_all_current_models_returns_0003(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'ca.db'}")
        SQLModel.metadata.create_all(engine)
        with engine.connect() as conn:
            assert detect_stamp_revision(conn) == "0003"

    def test_projects_path_not_null_returns_0001(self, tmp_path):
        from sqlalchemy import text

        engine = create_engine(f"sqlite:///{tmp_path / 'v1.db'}")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE projects (id TEXT PRIMARY KEY, path TEXT NOT NULL)"))
        with engine.connect() as conn:
            assert detect_stamp_revision(conn) == "0001"

    def test_projects_path_nullable_returns_0002(self, tmp_path):
        from sqlalchemy import text

        engine = create_engine(f"sqlite:///{tmp_path / 'v2.db'}")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE projects (id TEXT PRIMARY KEY, path TEXT)"))
        with engine.connect() as conn:
            assert detect_stamp_revision(conn) == "0002"


# ---------------------------------------------------------------------------
# run_upgrade_head: stamp-if-needed then upgrade
# ---------------------------------------------------------------------------


class TestRunUpgradeHead:
    def test_fresh_database_applies_all(self, tmp_path):
        import logging

        log = logging.getLogger("test")
        url = f"sqlite:///{tmp_path / 'fresh.db'}"
        run_upgrade_head(url, logger=log)
        assert get_revision_info(url)["current"] == "0003"

    def test_create_all_schema_is_stamped_not_recreated(self, tmp_path, caplog):
        import logging

        url = f"sqlite:///{tmp_path / 'stamp.db'}"
        engine = create_engine(url)
        SQLModel.metadata.create_all(engine)
        engine.dispose()

        with caplog.at_level(logging.WARNING):
            run_upgrade_head(url, logger=logging.getLogger("test"))

        assert "stamping baseline 0003" in caplog.text.lower()
        assert get_revision_info(url)["current"] == "0003"


# ---------------------------------------------------------------------------
# Regression: percent-encoded URLs and pending-count arithmetic
# ---------------------------------------------------------------------------


class TestConfigRobustness:
    def test_percent_encoded_url_does_not_crash(self):
        """Managed Postgres URLs often have percent-encoded passwords (p%40ss).

        Alembic's Config uses ConfigParser interpolation, which treats "%" as a
        sigil; without escaping, build_alembic_config would raise ValueError and
        crash-loop startup. The URL must round-trip unchanged for env.py.
        """
        url = "postgresql://user:p%40ss%2Fword@host:5432/db"
        cfg = build_alembic_config(url)
        assert cfg.get_main_option("sqlalchemy.url") == url

    def test_get_revision_info_counts_pending_below_head(self, tmp_path):
        """get_revision_info must report the correct pending count when the DB
        is behind head (the reversed walk_revisions range raised CommandError)."""
        url = f"sqlite:///{tmp_path / 'behind.db'}"
        cfg = build_alembic_config(url)
        command.upgrade(cfg, "0001")
        info = get_revision_info(url)
        assert info == {"current": "0001", "head": "0003", "pending": 2}

        command.upgrade(cfg, "0002")
        assert get_revision_info(url)["pending"] == 1

    def test_get_revision_info_pending_from_unstamped(self, tmp_path):
        """An unstamped DB (current is None) counts all revisions as pending."""
        url = f"sqlite:///{tmp_path / 'unstamped.db'}"
        info = get_revision_info(url)
        assert info["current"] is None
        assert info["pending"] == 3
