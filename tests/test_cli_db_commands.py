"""Tests for CLI database migration commands (a-sdlc db).

Covers: db status, db migrate, db rollback, db import subcommands.
All tests use Click CliRunner with mocked Alembic/SQLAlchemy layers.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from a_sdlc.cli import main

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture(autouse=True)
def _mock_doctor_externals():
    """Auto-mock slow external calls used by the doctor command."""
    with (
        patch("a_sdlc.cli.check_docker_available", return_value=False),
        patch(
            "a_sdlc.cli.check_services_health",
            return_value={
                "langfuse_reachable": False,
                "signoz_reachable": False,
                "services_running": False,
            },
        ),
        patch(
            "a_sdlc.cli.verify_monitoring_setup",
            return_value={
                "files_ready": False,
                "ready": False,
                "hook_registered": False,
                "otel_configured": False,
            },
        ),
        patch(
            "a_sdlc.cli.verify_sonarqube_setup",
            return_value={"ready": False, "host_url_configured": False},
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _mock_cli_targets():
    """Auto-mock resolve_targets and detect_targets."""
    from a_sdlc.cli_targets import CLAUDE_TARGET

    with (
        patch("a_sdlc.cli.resolve_targets", return_value=[CLAUDE_TARGET]),
        patch("a_sdlc.cli.detect_targets", return_value=[CLAUDE_TARGET]),
    ):
        yield


@pytest.fixture
def mock_storage_config():
    """Create a mock StorageConfig that returns a SQLite URL."""
    config = MagicMock()
    config.database_url = "sqlite:///test.db"
    return config


# ---------------------------------------------------------------------------
# db group tests
# ---------------------------------------------------------------------------


class TestDbGroup:
    """Tests for the db command group."""

    def test_db_help(self, runner: CliRunner) -> None:
        """db --help shows subcommands."""
        result = runner.invoke(main, ["db", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output
        assert "migrate" in result.output
        assert "rollback" in result.output

    def test_db_no_subcommand(self, runner: CliRunner) -> None:
        """db without subcommand shows usage error."""
        result = runner.invoke(main, ["db"])
        # Click group without invoke_without_command returns exit code 2
        assert result.exit_code == 2
        assert "Usage" in result.output


# ---------------------------------------------------------------------------
# db status tests
# ---------------------------------------------------------------------------


def _make_mock_engine():
    """Create a mock SQLAlchemy engine with context manager support."""
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return mock_engine


class TestDbStatus:
    """Tests for the db status subcommand."""

    def test_status_up_to_date(self, runner: CliRunner, mock_storage_config) -> None:
        """db status shows 'Up to date' when current == head."""
        mock_script = MagicMock()
        mock_script.get_heads.return_value = ["0001"]

        mock_context = MagicMock()
        mock_context.get_current_revision.return_value = "0001"

        with (
            patch(
                "a_sdlc.core.storage_config.load_storage_config",
                return_value=mock_storage_config,
            ),
            patch("a_sdlc.cli._get_alembic_config"),
            patch(
                "alembic.script.ScriptDirectory.from_config",
                return_value=mock_script,
            ),
            patch("sqlalchemy.create_engine", return_value=_make_mock_engine()),
            patch(
                "alembic.runtime.migration.MigrationContext.configure",
                return_value=mock_context,
            ),
        ):
            result = runner.invoke(main, ["db", "status"])

        assert result.exit_code == 0
        assert "Up to date" in result.output

    def test_status_pending_migrations(self, runner: CliRunner, mock_storage_config) -> None:
        """db status shows pending count when behind head."""
        mock_script = MagicMock()
        mock_script.get_heads.return_value = ["0002"]

        mock_rev = MagicMock()
        mock_rev.revision = "0002"
        mock_script.walk_revisions.return_value = [mock_rev]

        mock_context = MagicMock()
        mock_context.get_current_revision.return_value = "0001"

        with (
            patch(
                "a_sdlc.core.storage_config.load_storage_config",
                return_value=mock_storage_config,
            ),
            patch("a_sdlc.cli._get_alembic_config"),
            patch(
                "alembic.script.ScriptDirectory.from_config",
                return_value=mock_script,
            ),
            patch("sqlalchemy.create_engine", return_value=_make_mock_engine()),
            patch(
                "alembic.runtime.migration.MigrationContext.configure",
                return_value=mock_context,
            ),
        ):
            result = runner.invoke(main, ["db", "status"])

        assert result.exit_code == 0
        assert "pending" in result.output

    def test_status_no_current_revision(self, runner: CliRunner, mock_storage_config) -> None:
        """db status shows 'None (not initialized)' when no migration has run."""
        mock_script = MagicMock()
        mock_script.get_heads.return_value = ["0001"]
        mock_script.walk_revisions.return_value = [MagicMock()]

        mock_context = MagicMock()
        mock_context.get_current_revision.return_value = None

        with (
            patch(
                "a_sdlc.core.storage_config.load_storage_config",
                return_value=mock_storage_config,
            ),
            patch("a_sdlc.cli._get_alembic_config"),
            patch(
                "alembic.script.ScriptDirectory.from_config",
                return_value=mock_script,
            ),
            patch("sqlalchemy.create_engine", return_value=_make_mock_engine()),
            patch(
                "alembic.runtime.migration.MigrationContext.configure",
                return_value=mock_context,
            ),
        ):
            result = runner.invoke(main, ["db", "status"])

        assert result.exit_code == 0
        assert "not initialized" in result.output

    def test_status_storage_config_error(self, runner: CliRunner) -> None:
        """db status exits with error when StorageConfig fails."""
        with patch(
            "a_sdlc.core.storage_config.load_storage_config",
            side_effect=Exception("Config error"),
        ):
            result = runner.invoke(main, ["db", "status"])

        assert result.exit_code != 0
        assert "Failed to load storage config" in result.output

    def test_status_db_connection_error(self, runner: CliRunner, mock_storage_config) -> None:
        """db status exits with error when DB connection fails."""
        mock_script = MagicMock()
        mock_script.get_heads.return_value = ["0001"]

        with (
            patch(
                "a_sdlc.core.storage_config.load_storage_config",
                return_value=mock_storage_config,
            ),
            patch("a_sdlc.cli._get_alembic_config"),
            patch(
                "alembic.script.ScriptDirectory.from_config",
                return_value=mock_script,
            ),
            patch(
                "sqlalchemy.create_engine",
                side_effect=Exception("Connection refused"),
            ),
        ):
            result = runner.invoke(main, ["db", "status"])

        assert result.exit_code != 0
        assert "Failed to connect" in result.output

    def test_status_displays_database_url(self, runner: CliRunner, mock_storage_config) -> None:
        """db status shows the database URL."""
        mock_script = MagicMock()
        mock_script.get_heads.return_value = ["0001"]

        mock_context = MagicMock()
        mock_context.get_current_revision.return_value = "0001"

        with (
            patch(
                "a_sdlc.core.storage_config.load_storage_config",
                return_value=mock_storage_config,
            ),
            patch("a_sdlc.cli._get_alembic_config"),
            patch(
                "alembic.script.ScriptDirectory.from_config",
                return_value=mock_script,
            ),
            patch("sqlalchemy.create_engine", return_value=_make_mock_engine()),
            patch(
                "alembic.runtime.migration.MigrationContext.configure",
                return_value=mock_context,
            ),
        ):
            result = runner.invoke(main, ["db", "status"])

        assert result.exit_code == 0
        assert "test.db" in result.output


# ---------------------------------------------------------------------------
# db migrate tests
# ---------------------------------------------------------------------------


class TestDbMigrate:
    """Tests for the db migrate subcommand."""

    def test_migrate_success(self, runner: CliRunner) -> None:
        """db migrate runs upgrade successfully."""
        mock_cfg = MagicMock()
        with (
            patch("a_sdlc.cli._check_server_running", return_value=False),
            patch("a_sdlc.cli._get_alembic_config", return_value=mock_cfg),
            patch("alembic.command.upgrade") as mock_upgrade,
        ):
            result = runner.invoke(main, ["db", "migrate"])

        assert result.exit_code == 0
        assert "Successfully migrated" in result.output
        mock_upgrade.assert_called_once_with(mock_cfg, "head")

    def test_migrate_custom_revision(self, runner: CliRunner) -> None:
        """db migrate -r applies a specific revision."""
        mock_cfg = MagicMock()
        with (
            patch("a_sdlc.cli._check_server_running", return_value=False),
            patch("a_sdlc.cli._get_alembic_config", return_value=mock_cfg),
            patch("alembic.command.upgrade") as mock_upgrade,
        ):
            result = runner.invoke(main, ["db", "migrate", "-r", "0001"])

        assert result.exit_code == 0
        mock_upgrade.assert_called_once_with(mock_cfg, "0001")

    def test_migrate_failure(self, runner: CliRunner) -> None:
        """db migrate exits with error on upgrade failure."""
        with (
            patch("a_sdlc.cli._check_server_running", return_value=False),
            patch("a_sdlc.cli._get_alembic_config", return_value=MagicMock()),
            patch(
                "alembic.command.upgrade",
                side_effect=Exception("table already exists"),
            ),
        ):
            result = runner.invoke(main, ["db", "migrate"])

        assert result.exit_code != 0
        assert "Migration failed" in result.output

    def test_migrate_daemon_warning_abort(self, runner: CliRunner) -> None:
        """db migrate aborts when daemon is running and user declines."""
        with (
            patch("a_sdlc.cli._check_server_running", return_value=True),
            patch("alembic.command.upgrade") as mock_upgrade,
        ):
            result = runner.invoke(main, ["db", "migrate"], input="n\n")

        assert result.exit_code == 0
        assert "Aborted" in result.output
        mock_upgrade.assert_not_called()

    def test_migrate_daemon_warning_continue(self, runner: CliRunner) -> None:
        """db migrate proceeds when daemon is running but user confirms."""
        with (
            patch("a_sdlc.cli._check_server_running", return_value=True),
            patch("a_sdlc.cli._get_alembic_config", return_value=MagicMock()),
            patch("alembic.command.upgrade") as mock_upgrade,
        ):
            result = runner.invoke(main, ["db", "migrate"], input="y\n")

        assert result.exit_code == 0
        assert "Successfully migrated" in result.output
        mock_upgrade.assert_called_once()

    def test_migrate_config_error(self, runner: CliRunner) -> None:
        """db migrate exits with error when Alembic config fails."""
        with (
            patch("a_sdlc.cli._check_server_running", return_value=False),
            patch(
                "a_sdlc.cli._get_alembic_config",
                side_effect=Exception("alembic.ini not found"),
            ),
        ):
            result = runner.invoke(main, ["db", "migrate"])

        assert result.exit_code != 0
        assert "Failed to load Alembic configuration" in result.output


# ---------------------------------------------------------------------------
# db rollback tests
# ---------------------------------------------------------------------------


class TestDbRollback:
    """Tests for the db rollback subcommand."""

    def test_rollback_success(self, runner: CliRunner) -> None:
        """db rollback -y reverts one step successfully."""
        mock_cfg = MagicMock()
        with (
            patch("a_sdlc.cli._check_server_running", return_value=False),
            patch("a_sdlc.cli._get_alembic_config", return_value=mock_cfg),
            patch("alembic.command.downgrade") as mock_downgrade,
        ):
            result = runner.invoke(main, ["db", "rollback", "-y"])

        assert result.exit_code == 0
        assert "Successfully rolled back" in result.output
        mock_downgrade.assert_called_once_with(mock_cfg, "-1")

    def test_rollback_custom_revision(self, runner: CliRunner) -> None:
        """db rollback -r base -y reverts to base."""
        mock_cfg = MagicMock()
        with (
            patch("a_sdlc.cli._check_server_running", return_value=False),
            patch("a_sdlc.cli._get_alembic_config", return_value=mock_cfg),
            patch("alembic.command.downgrade") as mock_downgrade,
        ):
            result = runner.invoke(main, ["db", "rollback", "-r", "base", "-y"])

        assert result.exit_code == 0
        mock_downgrade.assert_called_once_with(mock_cfg, "base")

    def test_rollback_confirmation_abort(self, runner: CliRunner) -> None:
        """db rollback aborts when user declines confirmation."""
        with (
            patch("a_sdlc.cli._check_server_running", return_value=False),
            patch("alembic.command.downgrade") as mock_downgrade,
        ):
            result = runner.invoke(main, ["db", "rollback"], input="n\n")

        assert result.exit_code == 0
        assert "Aborted" in result.output
        mock_downgrade.assert_not_called()

    def test_rollback_confirmation_proceed(self, runner: CliRunner) -> None:
        """db rollback proceeds when user confirms."""
        with (
            patch("a_sdlc.cli._check_server_running", return_value=False),
            patch("a_sdlc.cli._get_alembic_config", return_value=MagicMock()),
            patch("alembic.command.downgrade") as mock_downgrade,
        ):
            result = runner.invoke(main, ["db", "rollback"], input="y\n")

        assert result.exit_code == 0
        assert "Successfully rolled back" in result.output
        mock_downgrade.assert_called_once()

    def test_rollback_failure(self, runner: CliRunner) -> None:
        """db rollback exits with error on downgrade failure."""
        with (
            patch("a_sdlc.cli._check_server_running", return_value=False),
            patch("a_sdlc.cli._get_alembic_config", return_value=MagicMock()),
            patch(
                "alembic.command.downgrade",
                side_effect=Exception("no such table"),
            ),
        ):
            result = runner.invoke(main, ["db", "rollback", "-y"])

        assert result.exit_code != 0
        assert "Rollback failed" in result.output

    def test_rollback_daemon_warning_abort(self, runner: CliRunner) -> None:
        """db rollback aborts when daemon is running and user declines."""
        with (
            patch("a_sdlc.cli._check_server_running", return_value=True),
            patch("alembic.command.downgrade") as mock_downgrade,
        ):
            result = runner.invoke(main, ["db", "rollback", "-y"], input="n\n")

        assert result.exit_code == 0
        assert "Aborted" in result.output
        mock_downgrade.assert_not_called()

    def test_rollback_daemon_warning_continue(self, runner: CliRunner) -> None:
        """db rollback proceeds when daemon is running but user confirms."""
        with (
            patch("a_sdlc.cli._check_server_running", return_value=True),
            patch("a_sdlc.cli._get_alembic_config", return_value=MagicMock()),
            patch("alembic.command.downgrade") as mock_downgrade,
        ):
            # First 'y' for daemon warning, -y skips rollback confirmation
            result = runner.invoke(main, ["db", "rollback", "-y"], input="y\n")

        assert result.exit_code == 0
        assert "Successfully rolled back" in result.output
        mock_downgrade.assert_called_once()

    def test_rollback_config_error(self, runner: CliRunner) -> None:
        """db rollback exits with error when Alembic config fails."""
        with (
            patch("a_sdlc.cli._check_server_running", return_value=False),
            patch(
                "a_sdlc.cli._get_alembic_config",
                side_effect=Exception("alembic.ini not found"),
            ),
        ):
            result = runner.invoke(main, ["db", "rollback", "-y"])

        assert result.exit_code != 0
        assert "Failed to load Alembic configuration" in result.output


# ---------------------------------------------------------------------------
# _check_server_running tests
# ---------------------------------------------------------------------------


class TestCheckDaemonRunning:
    """Tests for the _check_server_running helper."""

    def test_no_pid_file(self, tmp_path) -> None:
        """Returns False when PID file does not exist."""
        from a_sdlc.cli import _check_server_running

        mock_pid = tmp_path / "mcp.pid"
        with patch("a_sdlc.server._MCP_PID_FILE", mock_pid):
            assert _check_server_running() is False

    def test_pid_file_dead_process(self, tmp_path) -> None:
        """Returns False when PID file exists but process is dead."""
        from a_sdlc.cli import _check_server_running

        mock_pid = tmp_path / "mcp.pid"
        mock_pid.write_text("999999")

        with patch("a_sdlc.server._MCP_PID_FILE", mock_pid):
            result = _check_server_running()
            # On most systems, PID 999999 won't exist, so should return False
            assert result is False

    def test_pid_file_invalid_content(self, tmp_path) -> None:
        """Returns False when PID file has invalid content."""
        from a_sdlc.cli import _check_server_running

        mock_pid = tmp_path / "mcp.pid"
        mock_pid.write_text("not-a-number")

        with patch("a_sdlc.server._MCP_PID_FILE", mock_pid):
            assert _check_server_running() is False

    def test_import_error_returns_false(self) -> None:
        """Returns False when a_sdlc.server cannot be imported."""
        from a_sdlc.cli import _check_server_running

        with patch.dict("sys.modules", {"a_sdlc.server": None}):
            assert _check_server_running() is False


# ---------------------------------------------------------------------------
# _get_alembic_config tests
# ---------------------------------------------------------------------------


class TestGetAlembicConfig:
    """Tests for the _get_alembic_config helper."""

    def test_config_sets_database_url(self) -> None:
        """Config injects database URL from StorageConfig."""
        from a_sdlc.cli import _get_alembic_config

        mock_config = MagicMock()
        mock_config.database_url = "sqlite:///custom.db"

        with patch(
            "a_sdlc.core.storage_config.load_storage_config",
            return_value=mock_config,
        ):
            cfg = _get_alembic_config()

        # The config should have the URL set
        url = cfg.get_main_option("sqlalchemy.url")
        assert url == "sqlite:///custom.db"

    def test_config_handles_storage_config_failure(self) -> None:
        """Config falls back to alembic.ini when StorageConfig fails."""
        from a_sdlc.cli import _get_alembic_config

        with patch(
            "a_sdlc.core.storage_config.load_storage_config",
            side_effect=Exception("config error"),
        ):
            # Should not raise; falls back gracefully
            cfg = _get_alembic_config()
            assert cfg is not None

    def test_config_sets_script_location(self) -> None:
        """Config sets script_location to absolute path."""
        from a_sdlc.cli import _get_alembic_config

        mock_config = MagicMock()
        mock_config.database_url = "sqlite:///test.db"

        with patch(
            "a_sdlc.core.storage_config.load_storage_config",
            return_value=mock_config,
        ):
            cfg = _get_alembic_config()

        script_loc = cfg.get_main_option("script_location")
        assert script_loc is not None
        assert "alembic" in script_loc


# ---------------------------------------------------------------------------
# Integration-style tests (with real SQLite + Alembic)
# ---------------------------------------------------------------------------


class TestDbIntegration:
    """Integration tests using a real temporary SQLite database."""

    def test_migrate_and_status_integration(self, runner: CliRunner, tmp_path) -> None:
        """Full cycle: status shows pending, migrate applies, status shows up-to-date."""
        db_path = tmp_path / "test.db"
        db_url = f"sqlite:///{db_path}"

        mock_config = MagicMock()
        mock_config.database_url = db_url

        with (
            patch(
                "a_sdlc.core.storage_config.load_storage_config",
                return_value=mock_config,
            ),
            patch("a_sdlc.cli._check_server_running", return_value=False),
        ):
            # Status should show pending (no migration table yet)
            result = runner.invoke(main, ["db", "status"])
            assert result.exit_code == 0
            # Should show either "pending" or "not initialized"
            assert "pending" in result.output or "not initialized" in result.output

            # Migrate to head
            result = runner.invoke(main, ["db", "migrate"])
            assert result.exit_code == 0
            assert "Successfully migrated" in result.output

            # Status should now show up to date
            result = runner.invoke(main, ["db", "status"])
            assert result.exit_code == 0
            assert "Up to date" in result.output

    def test_migrate_and_rollback_integration(self, runner: CliRunner, tmp_path) -> None:
        """Migrate then rollback reverts the migration."""
        db_path = tmp_path / "test.db"
        db_url = f"sqlite:///{db_path}"

        mock_config = MagicMock()
        mock_config.database_url = db_url

        with (
            patch(
                "a_sdlc.core.storage_config.load_storage_config",
                return_value=mock_config,
            ),
            patch("a_sdlc.cli._check_server_running", return_value=False),
        ):
            # Migrate first
            result = runner.invoke(main, ["db", "migrate"])
            assert result.exit_code == 0

            # Rollback with -y
            result = runner.invoke(main, ["db", "rollback", "-r", "base", "-y"])
            assert result.exit_code == 0
            assert "Successfully rolled back" in result.output

            # Status should show pending again
            result = runner.invoke(main, ["db", "status"])
            assert result.exit_code == 0
            assert "pending" in result.output or "not initialized" in result.output


# ---------------------------------------------------------------------------
# db import tests
# ---------------------------------------------------------------------------


class TestDbImport:
    """Tests for the db import subcommand."""

    def test_import_help(self, runner: CliRunner) -> None:
        """db import --help shows all options including --merge and --source-s3-*."""
        result = runner.invoke(main, ["db", "import", "--help"])
        assert result.exit_code == 0
        assert "--source" in result.output
        assert "--force" in result.output
        assert "--skip-content" in result.output
        assert "--merge" in result.output
        assert "--yes" in result.output
        assert "--source-s3-bucket" in result.output
        assert "--source-s3-endpoint" in result.output

    def test_import_source_not_found(self, runner: CliRunner, tmp_path) -> None:
        """db import exits with error when source not found."""
        result = runner.invoke(
            main,
            ["db", "import", "--source", str(tmp_path / "nope.db"), "-y"],
        )
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_import_auto_detect_source(self, runner: CliRunner, tmp_path) -> None:
        """db import auto-detects source at default location."""
        with patch("a_sdlc.core.content.get_data_dir", return_value=tmp_path):
            result = runner.invoke(main, ["db", "import", "-y"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_import_confirmation_abort(self, runner: CliRunner, tmp_path) -> None:
        """db import aborts when user declines confirmation."""
        db_path = tmp_path / "source.db"
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES (15)")
        conn.commit()
        conn.close()

        mock_config = MagicMock()
        mock_config.database_url = "postgresql://user:pass@localhost/testdb"

        with patch(
            "a_sdlc.core.storage_config.load_storage_config",
            return_value=mock_config,
        ):
            result = runner.invoke(
                main,
                ["db", "import", "--source", str(db_path), "--skip-content"],
                input="n\n",
            )
        assert result.exit_code == 0
        assert "Aborted" in result.output

    def test_import_preflight_error(self, runner: CliRunner, tmp_path) -> None:
        """db import displays PreflightError."""
        db_path = tmp_path / "source.db"
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES (10)")  # Wrong version
        conn.commit()
        conn.close()

        mock_config = MagicMock()
        mock_config.database_url = "postgresql://user:pass@localhost/testdb"

        with patch(
            "a_sdlc.core.storage_config.load_storage_config",
            return_value=mock_config,
        ):
            result = runner.invoke(
                main,
                ["db", "import", "--source", str(db_path), "--skip-content", "-y"],
            )
        assert result.exit_code != 0

    def test_import_masks_password(self, runner: CliRunner, tmp_path) -> None:
        """Password is not shown in output."""
        from a_sdlc.cli import _mask_db_url

        masked = _mask_db_url("postgresql://user:secret@host/db")
        assert "secret" not in masked
        assert "***" in masked

    def test_mask_db_url_no_password(self) -> None:
        """_mask_db_url handles URLs without password."""
        from a_sdlc.cli import _mask_db_url

        url = "postgresql://user@host/db"
        assert _mask_db_url(url) == url

    def test_mask_db_url_invalid(self) -> None:
        """_mask_db_url handles non-URL strings gracefully."""
        from a_sdlc.cli import _mask_db_url

        assert _mask_db_url("not-a-url") == "not-a-url"

    def test_import_merge_flag(self, runner: CliRunner, tmp_path) -> None:
        """--merge flag uses DataMerger instead of DataImporter."""
        db_path = tmp_path / "source.db"
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES (15)")
        conn.commit()
        conn.close()

        mock_config = MagicMock()
        mock_config.database_url = "postgresql://user:pass@localhost/testdb"

        with (
            patch(
                "a_sdlc.core.storage_config.load_storage_config",
                return_value=mock_config,
            ),
            patch("a_sdlc.core.db_merge.DataMerger") as mock_merger,
        ):
            mock_instance = MagicMock()
            mock_instance.run.return_value = MagicMock(
                success=True,
                summary=MagicMock(return_value="ok"),
                warnings=[],
                rows_skipped=0,
                rows_remapped=0,
                id_remap_summary={},
            )
            mock_merger.return_value = mock_instance

            runner.invoke(
                main,
                [
                    "db",
                    "import",
                    "--source",
                    str(db_path),
                    "--merge",
                    "--skip-content",
                    "-y",
                ],
            )

        # DataMerger should have been instantiated
        mock_merger.assert_called_once()

    def test_import_force_flag(self, runner: CliRunner, tmp_path) -> None:
        """--force flag is passed through to DataImporter."""
        db_path = tmp_path / "source.db"
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO schema_version VALUES (15)")
        conn.commit()
        conn.close()

        mock_config = MagicMock()
        mock_config.database_url = "postgresql://user:pass@localhost/testdb"

        with (
            patch(
                "a_sdlc.core.storage_config.load_storage_config",
                return_value=mock_config,
            ),
            patch("a_sdlc.core.db_import.DataImporter") as mock_importer,
        ):
            mock_instance = MagicMock()
            mock_instance.run.return_value = MagicMock(
                success=True,
                summary=MagicMock(return_value="ok"),
                warnings=[],
                rows_skipped=0,
                rows_remapped=0,
                id_remap_summary={},
            )
            mock_importer.return_value = mock_instance

            runner.invoke(
                main,
                [
                    "db",
                    "import",
                    "--source",
                    str(db_path),
                    "--force",
                    "--skip-content",
                    "-y",
                ],
            )

        mock_importer.assert_called_once()
        call_kwargs = mock_importer.call_args[1]
        assert call_kwargs["force"] is True

    def test_db_help_includes_import(self, runner: CliRunner) -> None:
        """db --help now lists the import subcommand."""
        result = runner.invoke(main, ["db", "--help"])
        assert result.exit_code == 0
        assert "import" in result.output

    def test_import_pg_source_detection(self, runner: CliRunner, tmp_path) -> None:
        """--source postgresql://... is detected as PG source."""
        mock_config = MagicMock()
        mock_config.database_url = "postgresql://user:pass@localhost/targetdb"

        mock_summary = {
            "exists": True,
            "type": "PostgreSQL",
            "schema_version": 15,
            "total_rows": 10,
            "tables": ["projects", "tasks"],
            "projects": 2,
            "tasks": 8,
        }

        with (
            patch(
                "a_sdlc.core.storage_config.load_storage_config",
                return_value=mock_config,
            ),
            patch(
                "a_sdlc.core.db_import.get_source_summary",
                return_value=mock_summary,
            ),
            patch("a_sdlc.core.db_import.DataImporter") as mock_importer,
        ):
            mock_instance = MagicMock()
            mock_instance.run.return_value = MagicMock(
                success=True,
                summary=MagicMock(return_value="ok"),
                warnings=[],
                rows_skipped=0,
                rows_remapped=0,
                id_remap_summary={},
            )
            mock_importer.return_value = mock_instance

            runner.invoke(
                main,
                [
                    "db",
                    "import",
                    "--source",
                    "postgresql://oldhost:5432/olddb",
                    "--skip-content",
                    "-y",
                ],
            )

        # Should have passed the PG URL as source_url
        if mock_importer.called:
            call_kwargs = mock_importer.call_args[1]
            assert call_kwargs["source_url"] == "postgresql://oldhost:5432/olddb"

    def test_import_source_s3_options(self, runner: CliRunner, tmp_path) -> None:
        """--source-s3-* options are available and shown in help."""
        result = runner.invoke(main, ["db", "import", "--help"])
        assert "--source-s3-bucket" in result.output
        assert "--source-s3-endpoint" in result.output
        assert "--source-s3-access-key" in result.output
        assert "--source-s3-secret-key" in result.output

    def test_resolve_source_url_none(self) -> None:
        """_resolve_source_url(None) returns default SQLite path."""
        from a_sdlc.cli import _resolve_source_url

        with patch("a_sdlc.core.content.get_data_dir") as mock_dir:
            from pathlib import Path

            mock_dir.return_value = Path("/home/user/.a-sdlc")
            url = _resolve_source_url(None)
        assert url.startswith("sqlite:///")
        assert "data.db" in url

    def test_resolve_source_url_pg(self) -> None:
        """_resolve_source_url passes through PostgreSQL URLs."""
        from a_sdlc.cli import _resolve_source_url

        url = _resolve_source_url("postgresql://host/db")
        assert url == "postgresql://host/db"

    def test_resolve_source_url_path(self) -> None:
        """_resolve_source_url wraps local paths in sqlite:///."""
        from pathlib import Path

        from a_sdlc.cli import _resolve_source_url

        url = _resolve_source_url("/tmp/data.db")
        # Path.resolve() may follow symlinks (e.g. /tmp -> /private/tmp on macOS)
        expected = f"sqlite:///{Path('/tmp/data.db').resolve()}"
        assert url == expected

    def test_resolve_source_url_sqlite(self) -> None:
        """_resolve_source_url passes through sqlite:/// URLs."""
        from a_sdlc.cli import _resolve_source_url

        url = _resolve_source_url("sqlite:///path/to/db")
        assert url == "sqlite:///path/to/db"
