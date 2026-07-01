"""Tests for HybridStorage backend selection logic (SDLC-T00236).

Validates that HybridStorage correctly selects database and content backends
based on StorageConfig, while preserving backward compatibility and test
isolation via base_path.
"""

from unittest.mock import MagicMock, patch

import pytest

from a_sdlc.core.content import ContentManager, LocalContentBackend
from a_sdlc.core.storage_config import StorageConfig, StorageConfigError
from a_sdlc.storage import HybridStorage

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture()
def tmp_base(tmp_path):
    """Provide a temporary base path for test isolation."""
    return tmp_path / "test-storage"


# =============================================================================
# Default / backward-compatible behavior
# =============================================================================


class TestDefaultBackendSelection:
    """HybridStorage() with no config returns SQLite + local (backward compat)."""

    def test_no_args_uses_sqlite_database(self, tmp_base):
        """Default HybridStorage with base_path uses SQLite Database class."""
        storage = HybridStorage(base_path=tmp_base)
        from a_sdlc.core.database import Database

        assert isinstance(storage.db, Database)

    def test_no_args_uses_local_content(self, tmp_base):
        """Default HybridStorage with base_path uses local ContentManager."""
        storage = HybridStorage(base_path=tmp_base)
        assert isinstance(storage.content_mgr, ContentManager)
        assert isinstance(storage.content_mgr.backend, LocalContentBackend)

    def test_base_path_creates_directories(self, tmp_base):
        """base_path mode creates required directory structure."""
        storage = HybridStorage(base_path=tmp_base)
        assert storage.base_path.exists()
        assert storage.templates_dir.exists()

    def test_explicit_db_and_content_mgr_raises(self, tmp_base):
        """Passing db= or content_mgr= directly raises ValueError."""
        mock_db = MagicMock()
        mock_cm = MagicMock()
        with pytest.raises(ValueError, match="no longer supported"):
            HybridStorage(db=mock_db, content_mgr=mock_cm)


# =============================================================================
# base_path test isolation: always SQLite + local
# =============================================================================


class TestBasepathForcesLocal:
    """When base_path is provided, ALWAYS use SQLite + local regardless of config."""

    def test_base_path_ignores_postgresql_config(self, tmp_base):
        """Even with a PostgreSQL config, base_path forces SQLite."""
        pg_config = StorageConfig(
            database_url="postgresql://user:pass@host:5432/db",
        )
        storage = HybridStorage(base_path=tmp_base, config=pg_config)
        from a_sdlc.core.database import Database

        assert isinstance(storage.db, Database)

    def test_base_path_ignores_s3_config(self, tmp_base):
        """Even with an S3 config, base_path forces local content backend."""
        s3_config = StorageConfig(
            database_url="postgresql://user:pass@host:5432/db",
            content_backend="s3",
            s3_bucket="my-bucket",
        )
        storage = HybridStorage(base_path=tmp_base, config=s3_config)
        assert isinstance(storage.content_mgr, ContentManager)
        assert isinstance(storage.content_mgr.backend, LocalContentBackend)


# =============================================================================
# PostgreSQL backend selection
# =============================================================================


class TestPostgresqlBackendSelection:
    """config.is_postgresql triggers SessionDatabase instantiation."""

    @patch("a_sdlc.storage._get_session_database_class")
    @patch("boto3.client")
    def test_postgresql_config_uses_session_database(
        self, mock_boto3, mock_get_sdb
    ):
        """When config.database_url starts with postgresql://, use SessionDatabase."""
        mock_sdb_cls = MagicMock()
        mock_get_sdb.return_value = mock_sdb_cls
        pg_config = StorageConfig(
            database_url="postgresql://user:pass@localhost:5432/test",
            content_backend="s3",
            s3_bucket="test-bucket",
        )
        storage = HybridStorage(config=pg_config)
        mock_sdb_cls.assert_called_once_with(config=pg_config)
        assert storage._db is mock_sdb_cls.return_value

    @patch("a_sdlc.storage._get_session_database_class")
    @patch("boto3.client")
    def test_postgres_scheme_also_works(
        self, mock_boto3, mock_get_sdb
    ):
        """postgres:// scheme (alias) should also trigger SessionDatabase."""
        mock_sdb_cls = MagicMock()
        mock_get_sdb.return_value = mock_sdb_cls
        pg_config = StorageConfig(
            database_url="postgres://user:pass@localhost:5432/test",
            content_backend="s3",
            s3_bucket="test-bucket",
        )
        storage = HybridStorage(config=pg_config)
        assert storage._db is mock_sdb_cls.return_value


# =============================================================================
# SQLite backend selection (now rejected in production mode)
# =============================================================================


class TestSqliteBackendSelection:
    """SQLite database URL is rejected when no base_path is provided."""

    def test_sqlite_config_uses_legacy_database(self):
        """SQLite config without base_path is rejected in production mode."""
        sqlite_config = StorageConfig(
            database_url="sqlite:///path/to/data.db",
        )
        with pytest.raises(StorageConfigError, match="PostgreSQL is required"):
            HybridStorage(config=sqlite_config)


# =============================================================================
# S3 content backend selection
# =============================================================================


class TestS3ContentBackendSelection:
    """config.is_s3 + s3_bucket triggers S3ContentBackend instantiation."""

    @patch("a_sdlc.storage._get_session_database_class")
    @patch("boto3.client")
    def test_s3_config_uses_s3_backend(self, mock_boto3, mock_get_sdb):
        """When config.content_backend='s3' and s3_bucket is set, use S3."""
        from a_sdlc.core.content import S3ContentBackend

        mock_get_sdb.return_value = MagicMock()
        s3_config = StorageConfig(
            database_url="postgresql://user:pass@localhost:5432/test",
            content_backend="s3",
            s3_bucket="test-bucket",
            s3_endpoint="http://localhost:9000",
        )
        storage = HybridStorage(config=s3_config)
        assert isinstance(storage._content_mgr, ContentManager)
        assert isinstance(storage._content_mgr._backend, S3ContentBackend)


# =============================================================================
# Local content backend (now rejected in production mode)
# =============================================================================


class TestLocalContentBackendSelection:
    """Local content backend without S3 is rejected in production mode."""

    @patch("a_sdlc.storage._get_session_database_class")
    def test_local_content_uses_local_backend(self, mock_get_sdb):
        """Local content backend without S3 is rejected in production mode."""
        mock_get_sdb.return_value = MagicMock()
        local_config = StorageConfig(
            database_url="postgresql://user:pass@localhost:5432/test",
            content_backend="local",
        )
        with pytest.raises(StorageConfigError, match="S3 content backend is required"):
            HybridStorage(config=local_config)


# =============================================================================
# Config loading fallback
# =============================================================================


class TestConfigFallback:
    """When no config is passed and get_storage_config() fails, error propagates."""

    @patch("a_sdlc.storage._get_storage_config", side_effect=Exception("config error"))
    def test_config_failure_raises(self, mock_get_cfg):
        """If StorageConfig loading fails, the error propagates."""
        with pytest.raises(Exception, match="config error"):
            HybridStorage()

    def test_no_config_loads_from_singleton(self):
        """Creating HybridStorage without config raises when env has SQLite."""
        with pytest.raises(StorageConfigError, match="PostgreSQL is required"):
            HybridStorage()


# =============================================================================
# Public API preservation
# =============================================================================


class TestPublicApiPreservation:
    """HybridStorage public API remains unchanged after backend selection refactor."""

    def test_properties_exist(self, tmp_base):
        """All expected properties exist on the instance."""
        storage = HybridStorage(base_path=tmp_base)
        assert hasattr(storage, "db")
        assert hasattr(storage, "content_mgr")
        assert hasattr(storage, "base_path")
        assert hasattr(storage, "templates_dir")

    def test_crud_methods_exist(self, tmp_base):
        """CRUD methods are still present after constructor changes."""
        storage = HybridStorage(base_path=tmp_base)
        # Spot check a representative set of methods
        assert callable(getattr(storage, "create_project", None))
        assert callable(getattr(storage, "get_prd", None))
        assert callable(getattr(storage, "create_task", None))
        assert callable(getattr(storage, "list_tasks", None))
        assert callable(getattr(storage, "create_sprint", None))
        assert callable(getattr(storage, "get_sprint", None))
        assert callable(getattr(storage, "consistency_check", None))

    def test_backward_compat_alias(self):
        """FileStorage alias still exists for backward compatibility."""
        from a_sdlc.storage import FileStorage

        assert FileStorage is HybridStorage

    def test_get_storage_function(self):
        """get_storage() function is still exported."""
        from a_sdlc.storage import get_storage

        assert callable(get_storage)

    def test_functional_crud_with_base_path(self, tmp_base):
        """End-to-end CRUD operations work with test-isolated storage."""
        storage = HybridStorage(base_path=tmp_base)

        # Create project
        project = storage.create_project("test-proj", "Test Project")
        assert project is not None
        assert project["id"] == "test-proj"

        # Create PRD
        prd = storage.create_prd("TEST-P0001", "test-proj", "Test PRD")
        assert prd is not None
        assert "file_path" in prd

        # Create task
        task = storage.create_task(
            "TEST-T00001", "test-proj", "Test Task", prd_id="TEST-P0001"
        )
        assert task is not None
        assert "file_path" in task

        # List tasks
        tasks = storage.list_tasks("test-proj")
        assert len(tasks) == 1


# =============================================================================
# Combined backend selection
# =============================================================================


class TestCombinedBackendSelection:
    """Test combining PostgreSQL database with S3 content backend."""

    @patch("a_sdlc.storage._get_s3_content_backend_class")
    @patch("a_sdlc.storage._get_content_manager_class")
    @patch("a_sdlc.storage._get_session_database_class")
    def test_postgresql_plus_s3(
        self, mock_sdb_cls, mock_cm_cls, mock_s3_cls
    ):
        """PostgreSQL + S3 config instantiates both specialized backends."""
        combined_config = StorageConfig(
            database_url="postgresql://user:pass@host:5432/db",
            content_backend="s3",
            s3_bucket="prod-bucket",
        )

        mock_session_db = MagicMock()
        mock_sdb_cls.return_value = MagicMock(return_value=mock_session_db)

        mock_s3_backend = MagicMock()
        mock_s3_cls.return_value = MagicMock(return_value=mock_s3_backend)

        mock_cm_instance = MagicMock(spec=ContentManager)
        mock_cm_cls.return_value = MagicMock(return_value=mock_cm_instance)

        storage = HybridStorage(config=combined_config)

        assert storage.db is mock_session_db
        assert storage.content_mgr is mock_cm_instance
        mock_sdb_cls.return_value.assert_called_once_with(config=combined_config)
        mock_s3_cls.return_value.assert_called_once()
