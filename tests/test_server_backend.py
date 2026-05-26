"""Tests for MCP server configurable backend initialization.

Verifies that the server correctly loads StorageConfig at startup, selects
the appropriate database and content backends, logs backend selection, and
runs auto-migration for PostgreSQL configurations.
"""

import contextlib
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# _mask_url
# ---------------------------------------------------------------------------


class TestMaskUrl:
    """Tests for _mask_url() which hides passwords in database URLs for logging."""

    def test_mask_password_in_postgresql_url(self):
        from a_sdlc.server import _mask_url

        url = "postgresql://user:secret@host:5432/dbname"
        masked = _mask_url(url)
        assert "secret" not in masked
        assert "***" in masked
        assert "user" in masked
        assert "host" in masked

    def test_no_password_returns_unchanged(self):
        from a_sdlc.server import _mask_url

        url = "sqlite:///path/to/data.db"
        assert _mask_url(url) == url

    def test_password_without_port(self):
        from a_sdlc.server import _mask_url

        url = "postgresql://user:secret@host/dbname"
        masked = _mask_url(url)
        assert "secret" not in masked
        assert "***" in masked

    def test_empty_url(self):
        from a_sdlc.server import _mask_url

        assert _mask_url("") == ""


# ---------------------------------------------------------------------------
# _init_storage_backend
# ---------------------------------------------------------------------------


class TestInitStorageBackend:
    """Tests for _init_storage_backend() server startup initialization."""

    @pytest.fixture(autouse=True)
    def _reset_storage(self):
        """Reset the storage singleton before and after each test."""
        import a_sdlc.storage as _storage_mod

        original = _storage_mod._storage
        _storage_mod._storage = None
        yield
        _storage_mod._storage = original

    def test_sqlite_default_backend(self):
        """SQLite config is rejected by _init_storage_backend."""
        from a_sdlc.core.storage_config import StorageConfig, StorageConfigError
        from a_sdlc.server import _init_storage_backend

        mock_config = MagicMock(spec=StorageConfig)
        mock_config.is_postgresql = False
        mock_config.database_url = "sqlite:///test/data.db"
        with patch("a_sdlc.core.storage_config.get_storage_config", return_value=mock_config), \
             pytest.raises(StorageConfigError, match="PostgreSQL is required"):
            _init_storage_backend()

    def test_postgresql_backend_triggers_migration(self):
        """PostgreSQL config triggers auto-migration."""
        from a_sdlc.core.storage_config import StorageConfig
        from a_sdlc.server import _init_storage_backend

        mock_config = MagicMock(spec=StorageConfig)
        mock_config.is_postgresql = True
        mock_config.is_s3 = True
        mock_config.s3_bucket = "test-bucket"
        mock_config.database_url = "postgresql://user:***@localhost:5432/asdlc"
        mock_storage = MagicMock()
        with patch("a_sdlc.core.storage_config.get_storage_config", return_value=mock_config), \
             patch("a_sdlc.storage.init_storage", return_value=mock_storage) as mock_init, \
             patch("a_sdlc.server._run_auto_migration") as mock_migrate, \
             patch("a_sdlc.server._migrate_local_content_to_s3"):
            _init_storage_backend()
            mock_init.assert_called_once_with(config=mock_config)
            mock_migrate.assert_called_once_with(mock_config)

    def test_s3_content_backend_logged(self, caplog):
        """S3 content backend is logged when configured."""
        from a_sdlc.core.storage_config import StorageConfig
        from a_sdlc.server import _init_storage_backend

        mock_config = MagicMock(spec=StorageConfig)
        mock_config.is_postgresql = True
        mock_config.is_s3 = True
        mock_config.s3_bucket = "my-bucket"
        mock_config.database_url = "postgresql://user:***@localhost:5432/asdlc"
        mock_storage = MagicMock()
        with patch("a_sdlc.core.storage_config.get_storage_config", return_value=mock_config), \
             patch("a_sdlc.storage.init_storage", return_value=mock_storage), \
             patch("a_sdlc.server._run_auto_migration"), \
             patch("a_sdlc.server._migrate_local_content_to_s3") as mock_s3_migrate:
            with caplog.at_level(logging.INFO):
                _init_storage_backend()
            mock_s3_migrate.assert_called_once_with(mock_storage)
            assert "s3 content backend" in caplog.text.lower()

    @patch("a_sdlc.server._run_auto_migration")
    @patch(
        "a_sdlc.core.storage_config.get_storage_config",
        side_effect=Exception("config load error"),
    )
    def test_config_load_failure_raises(
        self, mock_get_config, mock_migration
    ):
        """When StorageConfig fails to load, the error propagates."""
        from a_sdlc.server import _init_storage_backend

        with pytest.raises(Exception, match="config load error"):
            _init_storage_backend()

        mock_migration.assert_not_called()

    def test_does_not_reinitialize_existing_storage(self):
        """Does not reinitialize when storage already exists."""
        from a_sdlc.core.storage_config import StorageConfig
        from a_sdlc.server import _init_storage_backend

        mock_config = MagicMock(spec=StorageConfig)
        mock_config.is_postgresql = True
        mock_config.is_s3 = True
        mock_config.s3_bucket = "test-bucket"
        mock_config.database_url = "postgresql://user:***@localhost:5432/asdlc"
        existing_storage = MagicMock()
        with patch("a_sdlc.core.storage_config.get_storage_config", return_value=mock_config), \
             patch("a_sdlc.storage.init_storage", return_value=existing_storage), \
             patch("a_sdlc.server._run_auto_migration"), \
             patch("a_sdlc.server._migrate_local_content_to_s3"):
            _init_storage_backend()
            # init_storage is idempotent -- returns existing if already set

    def test_passes_config_to_hybrid_storage(self):
        """Config from get_storage_config is passed to init_storage."""
        from a_sdlc.core.storage_config import StorageConfig
        from a_sdlc.server import _init_storage_backend

        mock_config = MagicMock(spec=StorageConfig)
        mock_config.is_postgresql = True
        mock_config.is_s3 = True
        mock_config.s3_bucket = "test-bucket"
        mock_config.database_url = "postgresql://user:***@localhost:5432/asdlc"
        mock_storage = MagicMock()
        with patch("a_sdlc.core.storage_config.get_storage_config", return_value=mock_config), \
             patch("a_sdlc.storage.init_storage", return_value=mock_storage) as mock_init, \
             patch("a_sdlc.server._run_auto_migration"), \
             patch("a_sdlc.server._migrate_local_content_to_s3"):
            _init_storage_backend()
            mock_init.assert_called_once_with(config=mock_config)


# ---------------------------------------------------------------------------
# _run_auto_migration
# ---------------------------------------------------------------------------


class TestRunAutoMigration:
    """Tests for _run_auto_migration() Alembic auto-migration at startup."""

    @patch("alembic.command.upgrade")
    @patch("alembic.config.Config")
    def test_successful_migration(self, mock_alembic_config, mock_upgrade, caplog):
        """When alembic.ini exists and migration succeeds, logs success."""
        from a_sdlc.server import _run_auto_migration

        mock_cfg_instance = MagicMock()
        mock_alembic_config.return_value = mock_cfg_instance

        config = MagicMock()
        config.database_url = "postgresql://user:pass@localhost/db"

        with (
            patch.object(Path, "exists", return_value=True),
            caplog.at_level(logging.INFO),
        ):
            _run_auto_migration(config)

        mock_upgrade.assert_called_once_with(mock_cfg_instance, "head")
        assert "Auto-migration completed successfully" in caplog.text

    @patch("alembic.command.upgrade", side_effect=Exception("migration error"))
    @patch("alembic.config.Config")
    def test_migration_failure_logged_not_fatal(
        self, mock_alembic_config, mock_upgrade, caplog
    ):
        """When migration fails, logs error but does not raise."""
        from a_sdlc.server import _run_auto_migration

        mock_alembic_config.return_value = MagicMock()

        config = MagicMock()
        config.database_url = "postgresql://user:pass@localhost/db"

        with (
            patch.object(Path, "exists", return_value=True),
            caplog.at_level(logging.ERROR, logger="a-sdlc-server"),
        ):
            _run_auto_migration(config)

        assert "Auto-migration failed" in caplog.text

    @patch("alembic.command.upgrade")
    @patch("alembic.config.Config")
    def test_migration_sets_database_url(self, mock_alembic_config, mock_upgrade):
        """Auto-migration sets the database URL on the Alembic config."""
        from a_sdlc.server import _run_auto_migration

        mock_cfg_instance = MagicMock()
        mock_alembic_config.return_value = mock_cfg_instance

        config = MagicMock()
        config.database_url = "postgresql://user:pass@localhost/db"

        with patch.object(Path, "exists", return_value=True):
            _run_auto_migration(config)

        mock_cfg_instance.set_main_option.assert_called_once_with(
            "sqlalchemy.url", "postgresql://user:pass@localhost/db"
        )


# ---------------------------------------------------------------------------
# Integration: run_combined_server calls _init_storage_backend
# ---------------------------------------------------------------------------


class TestRunServerIntegration:
    """Verify that run_combined_server() calls _init_storage_backend."""

    @patch("a_sdlc.server.mcp")
    @patch("a_sdlc.server._init_storage_backend")
    @patch("a_sdlc.server._mcp_acquire_pid", return_value=True)
    @patch("a_sdlc.server._cleanup_stale_mcp_pid")
    @patch("a_sdlc.server._check_port_availability")
    @patch("a_sdlc.server.asyncio.run")
    def test_run_combined_server_calls_init_storage(
        self,
        mock_asyncio_run,
        mock_check_ports,
        mock_cleanup,
        mock_pid,
        mock_init_storage,
        mock_mcp,
    ):
        """run_combined_server() calls _init_storage_backend() before starting."""
        from a_sdlc.server import run_combined_server

        # uvicorn and create_app are imported inside run_combined_server
        # so we patch them at their original module location
        with (
            patch.dict("sys.modules", {"uvicorn": MagicMock()}),
            patch("a_sdlc.ui.create_app", return_value=MagicMock()),
            contextlib.suppress(SystemExit, ImportError, Exception),
        ):
            run_combined_server(mcp_port=19999, ui_port=19998)

        mock_init_storage.assert_called_once()
