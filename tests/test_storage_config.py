"""Tests for database and content backend configuration layer.

Covers SDLC-T00233 / P0040: StorageConfig dataclass, load_storage_config()
function, environment variable precedence, validation, and lazy singleton.

Breaking changes tested here:
- database_url is REQUIRED (no default SQLite fallback)
- Default content_backend is "s3" (not "local")
- __post_init__ raises StorageConfigError if database_url is empty
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from a_sdlc.core.storage_config import (
    StorageConfig,
    StorageConfigError,
    _read_env_overrides,
    get_storage_config,
    load_storage_config,
    reset_storage_config,
    validate_storage_config,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure singleton is reset before and after each test."""
    reset_storage_config()
    yield
    reset_storage_config()


@pytest.fixture()
def clean_env(monkeypatch):
    """Remove all A_SDLC_ storage env vars for a clean baseline."""
    for var in (
        "A_SDLC_DATABASE_URL",
        "A_SDLC_CONTENT_BACKEND",
        "A_SDLC_S3_BUCKET",
        "A_SDLC_S3_ENDPOINT",
        "A_SDLC_S3_ACCESS_KEY",
        "A_SDLC_S3_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


# =============================================================================
# StorageConfig dataclass
# =============================================================================


class TestStorageConfig:
    """Test StorageConfig dataclass behavior."""

    def test_defaults_raises_without_database_url(self):
        """Creating StorageConfig() with no args raises StorageConfigError."""
        with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
            StorageConfig()

    def test_empty_database_url_raises(self):
        """Empty database_url raises StorageConfigError in __post_init__."""
        with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
            StorageConfig(database_url="")

    def test_default_content_backend_is_s3(self):
        """Default content_backend is 's3' when database_url is provided."""
        config = StorageConfig(database_url="postgresql://host/db")
        assert config.content_backend == "s3"

    def test_frozen_dataclass(self):
        """Config is immutable (frozen dataclass)."""
        config = StorageConfig(database_url="sqlite:///test.db")
        with pytest.raises(AttributeError):
            config.content_backend = "local"  # type: ignore[misc]

    def test_custom_values(self):
        """All fields can be set via constructor."""
        config = StorageConfig(
            database_url="postgresql://user:pass@host:5432/db",
            content_backend="s3",
            s3_bucket="my-bucket",
            s3_endpoint="https://minio.example.com",
            s3_access_key="AKID",
            s3_secret_key="SECRET",
        )
        assert config.database_url == "postgresql://user:pass@host:5432/db"
        assert config.content_backend == "s3"
        assert config.s3_bucket == "my-bucket"
        assert config.s3_endpoint == "https://minio.example.com"
        assert config.s3_access_key == "AKID"
        assert config.s3_secret_key == "SECRET"

    def test_to_dict_masks_secrets(self):
        """Serialization masks s3 credentials."""
        config = StorageConfig(
            database_url="sqlite:///test.db",
            content_backend="s3",
            s3_bucket="bucket",
            s3_access_key="AKID",
            s3_secret_key="SECRET",
        )
        d = config.to_dict()
        assert d["s3_access_key"] == "***"
        assert d["s3_secret_key"] == "***"
        assert d["database_url"] == "sqlite:///test.db"
        assert d["content_backend"] == "s3"
        assert d["s3_bucket"] == "bucket"

    def test_to_dict_none_secrets(self):
        """Serialization returns None for unset credentials."""
        config = StorageConfig(database_url="sqlite:///test.db")
        d = config.to_dict()
        assert d["s3_access_key"] is None
        assert d["s3_secret_key"] is None

    def test_is_sqlite(self):
        """is_sqlite returns True for SQLite URLs."""
        config = StorageConfig(database_url="sqlite:///path/to/db.sqlite")
        assert config.is_sqlite is True
        assert config.is_postgresql is False

    def test_is_postgresql(self):
        """is_postgresql returns True for PostgreSQL URLs."""
        config = StorageConfig(database_url="postgresql://localhost/mydb")
        assert config.is_postgresql is True
        assert config.is_sqlite is False

    def test_is_postgresql_with_postgres_scheme(self):
        """is_postgresql returns True for postgres:// scheme (alias)."""
        config = StorageConfig(database_url="postgres://localhost/mydb")
        assert config.is_postgresql is True

    def test_is_s3(self):
        """is_s3 returns True when content_backend is 's3'."""
        config = StorageConfig(
            database_url="sqlite:///test.db",
            content_backend="s3",
        )
        assert config.is_s3 is True

    def test_is_not_s3(self):
        """is_s3 returns False when content_backend is explicitly 'local'."""
        config = StorageConfig(
            database_url="sqlite:///test.db",
            content_backend="local",
        )
        assert config.is_s3 is False

    def test_default_s3_fields_are_none(self):
        """S3 optional fields default to None when only database_url is given."""
        config = StorageConfig(database_url="sqlite:///test.db")
        assert config.s3_bucket is None
        assert config.s3_endpoint is None
        assert config.s3_access_key is None
        assert config.s3_secret_key is None


# =============================================================================
# validate_storage_config
# =============================================================================


class TestValidateStorageConfig:
    """Test storage config validation."""

    def test_sqlite_rejected_in_production(self):
        """SQLite URLs are rejected by validation — PostgreSQL is required."""
        config = StorageConfig(
            database_url="sqlite:///test.db",
            content_backend="local",
        )
        with pytest.raises(StorageConfigError, match="PostgreSQL is required"):
            validate_storage_config(config)

    def test_valid_postgresql_local(self):
        """PostgreSQL + local is valid."""
        config = StorageConfig(
            database_url="postgresql://user:pass@host:5432/db",
            content_backend="local",
        )
        validate_storage_config(config)  # should not raise

    def test_valid_s3_with_bucket(self):
        """S3 backend with bucket is valid."""
        config = StorageConfig(
            database_url="postgresql://user:pass@host:5432/db",
            content_backend="s3",
            s3_bucket="my-bucket",
        )
        validate_storage_config(config)  # should not raise

    def test_sqlite_raises_storage_config_error(self):
        """SQLite URLs raise StorageConfigError with actionable message."""
        config = StorageConfig(
            database_url="sqlite:///test.db",
            content_backend="local",
        )
        with pytest.raises(StorageConfigError, match="PostgreSQL is required"):
            validate_storage_config(config)

    def test_invalid_content_backend(self):
        """Invalid content_backend raises StorageConfigError."""
        config = StorageConfig(
            database_url="postgresql://user:pass@host:5432/db",
            content_backend="gcs",
        )
        with pytest.raises(StorageConfigError, match="Invalid content_backend 'gcs'"):
            validate_storage_config(config)

    def test_invalid_database_url_scheme(self):
        """Invalid database URL scheme raises StorageConfigError."""
        config = StorageConfig(
            database_url="mysql://host/db",
            content_backend="local",
        )
        with pytest.raises(StorageConfigError, match="Invalid database URL scheme 'mysql'"):
            validate_storage_config(config)

    def test_s3_without_bucket_raises(self):
        """S3 backend without bucket raises StorageConfigError."""
        config = StorageConfig(
            database_url="postgresql://user:pass@host:5432/db",
            content_backend="s3",
            s3_bucket=None,
        )
        with pytest.raises(StorageConfigError, match="s3_bucket is required"):
            validate_storage_config(config)

    def test_s3_with_empty_bucket_raises(self):
        """S3 backend with empty bucket string raises StorageConfigError."""
        # Empty string is normalised to None by load_storage_config,
        # but direct construction can pass empty string.
        config = StorageConfig(
            database_url="postgresql://user:pass@host:5432/db",
            content_backend="s3",
            s3_bucket="",
        )
        with pytest.raises(StorageConfigError, match="s3_bucket is required"):
            validate_storage_config(config)

    def test_error_includes_exception_details(self):
        """StorageConfigError messages include actionable details."""
        config = StorageConfig(
            database_url="postgresql://user:pass@host:5432/db",
            content_backend="ftp",
        )
        with pytest.raises(StorageConfigError) as exc_info:
            validate_storage_config(config)
        # Verify the error message contains useful context
        assert "ftp" in str(exc_info.value)
        assert "local" in str(exc_info.value) or "s3" in str(exc_info.value)


# =============================================================================
# _read_env_overrides
# =============================================================================


class TestReadEnvOverrides:
    """Test environment variable reading."""

    def test_no_env_vars_set(self, clean_env):
        """No overrides when environment is clean."""
        overrides = _read_env_overrides()
        assert overrides == {}

    def test_database_url_from_env(self, clean_env):
        """A_SDLC_DATABASE_URL is mapped to database_url."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://host/db")
        overrides = _read_env_overrides()
        assert overrides["database_url"] == "postgresql://host/db"

    def test_all_env_vars(self, clean_env):
        """All supported env vars are mapped to their fields."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://host/db")
        clean_env.setenv("A_SDLC_CONTENT_BACKEND", "s3")
        clean_env.setenv("A_SDLC_S3_BUCKET", "my-bucket")
        clean_env.setenv("A_SDLC_S3_ENDPOINT", "https://s3.example.com")
        clean_env.setenv("A_SDLC_S3_ACCESS_KEY", "AKID")
        clean_env.setenv("A_SDLC_S3_SECRET_KEY", "SECRET")

        overrides = _read_env_overrides()
        assert overrides == {
            "database_url": "postgresql://host/db",
            "content_backend": "s3",
            "s3_bucket": "my-bucket",
            "s3_endpoint": "https://s3.example.com",
            "s3_access_key": "AKID",
            "s3_secret_key": "SECRET",
        }

    def test_partial_env_vars(self, clean_env):
        """Only set env vars appear in overrides."""
        clean_env.setenv("A_SDLC_S3_BUCKET", "my-bucket")
        overrides = _read_env_overrides()
        assert overrides == {"s3_bucket": "my-bucket"}
        assert "database_url" not in overrides


# =============================================================================
# load_storage_config -- defaults / absent config
# =============================================================================


class TestLoadStorageConfigDefaults:
    """Test loading storage config when storage section is absent."""

    def test_no_config_files_raises_without_database_url(self, clean_env):
        """Without any config files or env vars, raises StorageConfigError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
                load_storage_config(Path(tmpdir))

    def test_config_yaml_without_storage_section_raises(self, clean_env):
        """A config.yaml with no storage section raises StorageConfigError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({"testing": {"commands": {"unit": "pytest"}}})
            )

            with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
                load_storage_config(project_dir)

    def test_database_url_from_env_succeeds(self, clean_env):
        """When database_url is provided via env var, config loads successfully."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://host/db")
        clean_env.setenv("A_SDLC_S3_BUCKET", "test-bucket")

        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_storage_config(Path(tmpdir))
            assert config.database_url == "postgresql://host/db"
            assert config.content_backend == "s3"  # default
            assert config.s3_bucket == "test-bucket"


# =============================================================================
# load_storage_config -- project config overrides
# =============================================================================


class TestLoadStorageConfigProjectOverrides:
    """Test project config overrides."""

    def test_project_overrides_database_url(self, clean_env):
        """Project config can set database_url."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "postgresql://localhost:5432/mydb",
                        "s3_bucket": "test-bucket",
                    }
                })
            )

            config = load_storage_config(project_dir)
            assert config.database_url == "postgresql://localhost:5432/mydb"
            assert config.content_backend == "s3"  # default is now "s3"

    def test_project_overrides_all_fields(self, clean_env):
        """Project config can set all storage fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "postgresql://host/db",
                        "content_backend": "s3",
                        "s3_bucket": "my-bucket",
                        "s3_endpoint": "https://minio.local",
                        "s3_access_key": "AKID",
                        "s3_secret_key": "SECRET",
                    }
                })
            )

            config = load_storage_config(project_dir)
            assert config.database_url == "postgresql://host/db"
            assert config.content_backend == "s3"
            assert config.s3_bucket == "my-bucket"
            assert config.s3_endpoint == "https://minio.local"
            assert config.s3_access_key == "AKID"
            assert config.s3_secret_key == "SECRET"

    def test_partial_project_config_without_database_url_raises(self, clean_env):
        """Partial project config without database_url raises StorageConfigError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "content_backend": "s3",
                        "s3_bucket": "bucket",
                    }
                })
            )

            with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
                load_storage_config(project_dir)

    def test_partial_project_config_merges_with_defaults(self, clean_env):
        """Only provided project fields override, others stay at defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "postgresql://host/db",
                        "content_backend": "s3",
                        "s3_bucket": "bucket",
                    }
                })
            )

            config = load_storage_config(project_dir)
            assert config.database_url == "postgresql://host/db"
            assert config.content_backend == "s3"
            assert config.s3_bucket == "bucket"
            assert config.s3_endpoint is None  # default


# =============================================================================
# load_storage_config -- environment variable precedence
# =============================================================================


class TestLoadStorageConfigEnvPrecedence:
    """Test that environment variables override YAML config."""

    def test_env_overrides_project_config(self, clean_env):
        """Environment variables take precedence over project config."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://env-host/envdb")
        clean_env.setenv("A_SDLC_S3_BUCKET", "env-bucket")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "postgresql://yaml-host/yamldb",
                        "s3_bucket": "yaml-bucket",
                    }
                })
            )

            config = load_storage_config(project_dir)
            assert config.database_url == "postgresql://env-host/envdb"

    def test_env_overrides_global_config(self, clean_env, tmp_path, monkeypatch):
        """Environment variables take precedence over global config."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://env-host/envdb")
        clean_env.setenv("A_SDLC_S3_BUCKET", "env-bucket")

        global_config_dir = tmp_path / "global_config"
        global_config_dir.mkdir()
        global_config_file = global_config_dir / "config.yaml"
        global_config_file.write_text(
            yaml.dump({
                "storage": {
                    "database_url": "postgresql://global-host/globaldb",
                    "s3_bucket": "global-bucket",
                }
            })
        )
        monkeypatch.setattr(
            "a_sdlc.core.storage_config.GLOBAL_CONFIG_FILE",
            global_config_file,
        )

        with tempfile.TemporaryDirectory() as project_dir:
            config = load_storage_config(Path(project_dir))
            assert config.s3_bucket == "env-bucket"
            assert config.database_url == "postgresql://env-host/envdb"

    def test_env_overrides_content_backend(self, clean_env):
        """A_SDLC_CONTENT_BACKEND overrides YAML content_backend."""
        clean_env.setenv("A_SDLC_CONTENT_BACKEND", "s3")
        clean_env.setenv("A_SDLC_S3_BUCKET", "env-bucket")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "postgresql://host/db",
                        "content_backend": "local",
                    }
                })
            )

            config = load_storage_config(project_dir)
            assert config.content_backend == "s3"

    def test_partial_env_overrides(self, clean_env):
        """Only set env vars override; YAML values preserved for the rest."""
        clean_env.setenv("A_SDLC_S3_BUCKET", "env-bucket")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "postgresql://host/db",
                        "content_backend": "s3",
                        "s3_bucket": "yaml-bucket",
                        "s3_endpoint": "https://yaml-endpoint.com",
                    }
                })
            )

            config = load_storage_config(project_dir)
            assert config.s3_bucket == "env-bucket"  # env wins
            assert config.s3_endpoint == "https://yaml-endpoint.com"  # yaml preserved
            assert config.content_backend == "s3"  # yaml preserved


# =============================================================================
# load_storage_config -- layered merge (defaults < global < project)
# =============================================================================


class TestLoadStorageConfigLayeredMerge:
    """Test layered merging: defaults < global < project."""

    def test_global_config_overrides_defaults(self, clean_env, tmp_path, monkeypatch):
        """Global config overrides built-in defaults."""
        global_config_dir = tmp_path / "global_config"
        global_config_dir.mkdir()
        global_config_file = global_config_dir / "config.yaml"
        global_config_file.write_text(
            yaml.dump({
                "storage": {
                    "database_url": "postgresql://global-host/globaldb",
                    "s3_bucket": "global-bucket",
                }
            })
        )
        monkeypatch.setattr(
            "a_sdlc.core.storage_config.GLOBAL_CONFIG_FILE",
            global_config_file,
        )

        with tempfile.TemporaryDirectory() as project_dir:
            config = load_storage_config(Path(project_dir))
            assert config.database_url == "postgresql://global-host/globaldb"
            assert config.content_backend == "s3"  # default is now "s3"

    def test_project_overrides_global(self, clean_env, tmp_path, monkeypatch):
        """Project config takes precedence over global config."""
        # Global: database_url=postgres, s3_bucket=global-bucket
        global_config_dir = tmp_path / "global_config"
        global_config_dir.mkdir()
        global_config_file = global_config_dir / "config.yaml"
        global_config_file.write_text(
            yaml.dump({
                "storage": {
                    "database_url": "postgresql://global-host/globaldb",
                    "s3_bucket": "global-bucket",
                }
            })
        )
        monkeypatch.setattr(
            "a_sdlc.core.storage_config.GLOBAL_CONFIG_FILE",
            global_config_file,
        )

        # Project: database_url=postgresql (overrides global)
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        sdlc_dir = project_dir / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text(
            yaml.dump({
                "storage": {
                    "database_url": "postgresql://project-host/projectdb",
                }
            })
        )

        config = load_storage_config(project_dir)
        assert config.database_url == "postgresql://project-host/projectdb"  # project wins
        assert config.s3_bucket == "global-bucket"  # global preserved


# =============================================================================
# load_storage_config -- validation integration
# =============================================================================


class TestLoadStorageConfigValidation:
    """Test that load_storage_config validates when requested."""

    def test_invalid_config_raises_with_validate(self, clean_env):
        """Invalid config raises StorageConfigError when validate=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "mysql://host/db",
                    }
                })
            )

            with pytest.raises(StorageConfigError, match="Invalid database URL scheme"):
                load_storage_config(project_dir, validate=True)

    def test_invalid_config_returns_with_no_validate(self, clean_env):
        """Invalid config is returned without error when validate=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "mysql://host/db",
                    }
                })
            )

            config = load_storage_config(project_dir, validate=False)
            assert config.database_url == "mysql://host/db"

    def test_s3_missing_bucket_raises(self, clean_env):
        """S3 backend without bucket raises during validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "postgresql://host/db",
                        "content_backend": "s3",
                    }
                })
            )

            with pytest.raises(StorageConfigError, match="s3_bucket is required"):
                load_storage_config(project_dir)

    def test_no_database_url_raises_before_validation(self, clean_env):
        """Missing database_url raises in __post_init__ even with validate=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
                load_storage_config(Path(tmpdir), validate=False)


# =============================================================================
# load_storage_config -- error handling
# =============================================================================


class TestLoadStorageConfigErrorHandling:
    """Test robustness with missing or malformed config files."""

    def test_missing_config_file_raises(self, clean_env):
        """Missing config file with no database_url raises StorageConfigError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
                load_storage_config(Path(tmpdir))

    def test_missing_config_file_with_env_database_url(self, clean_env):
        """Missing config file succeeds when database_url is in env."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://host/db")
        clean_env.setenv("A_SDLC_S3_BUCKET", "test-bucket")

        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_storage_config(Path(tmpdir))
            assert config.database_url == "postgresql://host/db"
            assert config.content_backend == "s3"  # default

    def test_malformed_yaml_raises(self, clean_env):
        """Malformed YAML files are treated as empty, no database_url raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text("{{invalid yaml")

            with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
                load_storage_config(project_dir)

    def test_malformed_yaml_with_env_database_url(self, clean_env):
        """Malformed YAML succeeds when database_url is provided via env."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://host/db")
        clean_env.setenv("A_SDLC_S3_BUCKET", "test-bucket")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text("{{invalid yaml")

            config = load_storage_config(project_dir)
            assert config.database_url == "postgresql://host/db"

    def test_non_dict_storage_section_raises(self, clean_env):
        """Non-dict storage section is treated as empty, no database_url raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({"storage": "not_a_dict"})
            )

            with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
                load_storage_config(project_dir)

    def test_storage_section_is_list_raises(self, clean_env):
        """List storage section is treated as empty, no database_url raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({"storage": ["item1", "item2"]})
            )

            with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
                load_storage_config(project_dir)

    def test_preserves_other_config_sections(self, clean_env):
        """Loading storage config does not interfere with other config sections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            config_data = {
                "testing": {"commands": {"unit": "pytest"}},
                "git": {"auto_pr": True},
                "storage": {
                    "database_url": "postgresql://host/db",
                    "s3_bucket": "test-bucket",
                },
            }
            (sdlc_dir / "config.yaml").write_text(yaml.dump(config_data))

            config = load_storage_config(project_dir)
            assert config.database_url == "postgresql://host/db"

            # Original file should still have other sections
            raw = yaml.safe_load((sdlc_dir / "config.yaml").read_text())
            assert raw["testing"]["commands"]["unit"] == "pytest"
            assert raw["git"]["auto_pr"] is True


# =============================================================================
# PostgreSQL URL parsing
# =============================================================================


class TestPostgreSQLUrlParsing:
    """Test PostgreSQL URL handling and validation."""

    def test_postgresql_scheme(self, clean_env):
        """postgresql:// scheme is accepted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "postgresql://user:pass@host:5432/dbname",
                        "s3_bucket": "test-bucket",
                    }
                })
            )

            config = load_storage_config(project_dir)
            assert config.database_url == "postgresql://user:pass@host:5432/dbname"
            assert config.is_postgresql is True
            assert config.is_sqlite is False

    def test_postgres_scheme_alias(self, clean_env):
        """postgres:// scheme (alias) is accepted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "postgres://user:pass@host:5432/dbname",
                        "s3_bucket": "test-bucket",
                    }
                })
            )

            config = load_storage_config(project_dir)
            assert config.database_url == "postgres://user:pass@host:5432/dbname"
            assert config.is_postgresql is True

    def test_unsupported_scheme_rejected(self, clean_env):
        """Unsupported database schemes are rejected during validation."""
        config = StorageConfig(database_url="mysql://host/db")
        with pytest.raises(StorageConfigError, match="Invalid database URL scheme 'mysql'"):
            validate_storage_config(config)


# =============================================================================
# S3 credential loading
# =============================================================================


class TestS3CredentialLoading:
    """Test S3 credential loading from env and YAML."""

    def test_s3_from_yaml(self, clean_env):
        """S3 credentials loaded from YAML config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "postgresql://host/db",
                        "content_backend": "s3",
                        "s3_bucket": "yaml-bucket",
                        "s3_endpoint": "https://s3.yaml.com",
                        "s3_access_key": "YAML_AKID",
                        "s3_secret_key": "YAML_SECRET",
                    }
                })
            )

            config = load_storage_config(project_dir)
            assert config.s3_bucket == "yaml-bucket"
            assert config.s3_endpoint == "https://s3.yaml.com"
            assert config.s3_access_key == "YAML_AKID"
            assert config.s3_secret_key == "YAML_SECRET"

    def test_s3_from_env(self, clean_env):
        """S3 credentials loaded from environment variables."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://host/db")
        clean_env.setenv("A_SDLC_CONTENT_BACKEND", "s3")
        clean_env.setenv("A_SDLC_S3_BUCKET", "env-bucket")
        clean_env.setenv("A_SDLC_S3_ENDPOINT", "https://s3.env.com")
        clean_env.setenv("A_SDLC_S3_ACCESS_KEY", "ENV_AKID")
        clean_env.setenv("A_SDLC_S3_SECRET_KEY", "ENV_SECRET")

        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_storage_config(Path(tmpdir))
            assert config.content_backend == "s3"
            assert config.s3_bucket == "env-bucket"
            assert config.s3_endpoint == "https://s3.env.com"
            assert config.s3_access_key == "ENV_AKID"
            assert config.s3_secret_key == "ENV_SECRET"

    def test_s3_env_overrides_yaml(self, clean_env):
        """Env vars for S3 override YAML values."""
        clean_env.setenv("A_SDLC_S3_ACCESS_KEY", "ENV_AKID")
        clean_env.setenv("A_SDLC_S3_SECRET_KEY", "ENV_SECRET")

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "postgresql://host/db",
                        "content_backend": "s3",
                        "s3_bucket": "yaml-bucket",
                        "s3_access_key": "YAML_AKID",
                        "s3_secret_key": "YAML_SECRET",
                    }
                })
            )

            config = load_storage_config(project_dir)
            assert config.s3_access_key == "ENV_AKID"  # env wins
            assert config.s3_secret_key == "ENV_SECRET"  # env wins
            assert config.s3_bucket == "yaml-bucket"  # yaml preserved


# =============================================================================
# get_storage_config -- lazy singleton
# =============================================================================


class TestGetStorageConfig:
    """Test the lazy singleton factory."""

    def test_returns_config(self, clean_env):
        """get_storage_config returns a StorageConfig."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://host/db")
        clean_env.setenv("A_SDLC_S3_BUCKET", "test-bucket")

        with tempfile.TemporaryDirectory() as tmpdir:
            config = get_storage_config(Path(tmpdir))
            assert isinstance(config, StorageConfig)

    def test_caches_result(self, clean_env):
        """Second call returns the same instance."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://host/db")
        clean_env.setenv("A_SDLC_S3_BUCKET", "test-bucket")

        with tempfile.TemporaryDirectory() as tmpdir:
            config1 = get_storage_config(Path(tmpdir))
            config2 = get_storage_config(Path(tmpdir))
            assert config1 is config2

    def test_force_reload(self, clean_env):
        """force_reload=True creates a new instance."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://host/db")
        clean_env.setenv("A_SDLC_S3_BUCKET", "test-bucket")

        with tempfile.TemporaryDirectory() as tmpdir:
            config1 = get_storage_config(Path(tmpdir))
            config2 = get_storage_config(Path(tmpdir), force_reload=True)
            # New instance (may be equal but not identical)
            assert config1 is not config2

    def test_reset_clears_cache(self, clean_env):
        """reset_storage_config clears the cached instance."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://host/db")
        clean_env.setenv("A_SDLC_S3_BUCKET", "test-bucket")

        with tempfile.TemporaryDirectory() as tmpdir:
            config1 = get_storage_config(Path(tmpdir))
            reset_storage_config()
            config2 = get_storage_config(Path(tmpdir))
            assert config1 is not config2

    def test_raises_without_database_url(self, clean_env):
        """get_storage_config raises StorageConfigError when no database_url."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
                get_storage_config(Path(tmpdir))


# =============================================================================
# Backward compatibility (breaking changes)
# =============================================================================


class TestRequiredDatabaseUrl:
    """Test that database_url is now required -- no silent SQLite fallback."""

    def test_no_config_yaml_at_all_raises(self, clean_env):
        """A project with no config.yaml and no env var raises StorageConfigError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
                load_storage_config(Path(tmpdir))

    def test_config_yaml_without_storage_section_raises(self, clean_env):
        """A config.yaml with no storage section raises StorageConfigError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "git": {"auto_pr": True},
                    "testing": {"commands": {"unit": "pytest"}},
                })
            )

            with pytest.raises(StorageConfigError, match="A_SDLC_DATABASE_URL is required"):
                load_storage_config(project_dir)

    def test_default_content_backend_is_s3(self, clean_env):
        """Default content_backend is 's3', not 'local'."""
        clean_env.setenv("A_SDLC_DATABASE_URL", "postgresql://host/db")
        clean_env.setenv("A_SDLC_S3_BUCKET", "test-bucket")

        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_storage_config(Path(tmpdir))
            assert config.content_backend == "s3"

    def test_explicit_local_backend_still_works(self, clean_env):
        """Explicitly setting content_backend to 'local' still works."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({
                    "storage": {
                        "database_url": "postgresql://host/db",
                        "content_backend": "local",
                    }
                })
            )

            config = load_storage_config(project_dir)
            assert config.content_backend == "local"
            assert config.is_s3 is False
