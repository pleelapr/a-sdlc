"""
Database and content backend configuration layer for a-sdlc.

Provides layered configuration for database connection strings and content
backend selection (S3-compatible storage).  Docker with PostgreSQL + S3/MinIO
is the only supported production deployment.

Configuration hierarchy (highest priority first):
1. Environment variables (A_SDLC_DATABASE_URL, A_SDLC_S3_*, etc.)
2. Project config (.sdlc/config.yaml storage section)
3. Global config (~/.config/a-sdlc/config.yaml storage section)

Configuration keys under the 'storage' section:
    database_url: str           - PostgreSQL connection URL (required)
    content_backend: str        - Content storage backend: 's3' (default) or 'local' (test only)
    s3_bucket: str | None       - S3 bucket name (required for production)
    s3_endpoint: str | None     - S3-compatible endpoint URL (for MinIO, etc.)
    s3_access_key: str | None   - S3 access key ID
    s3_secret_key: str | None   - S3 secret access key

Environment variables:
    A_SDLC_DATABASE_URL   - Overrides database_url
    A_SDLC_CONTENT_BACKEND - Overrides content_backend
    A_SDLC_S3_BUCKET      - Overrides s3_bucket
    A_SDLC_S3_ENDPOINT    - Overrides s3_endpoint
    A_SDLC_S3_ACCESS_KEY  - Overrides s3_access_key
    A_SDLC_S3_SECRET_KEY  - Overrides s3_secret_key
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from a_sdlc.core.git_config import (
    GLOBAL_CONFIG_FILE,
    PROJECT_CONFIG_DIR,
    PROJECT_CONFIG_FILE,
    _deep_merge,
    _load_yaml,
)

logger = logging.getLogger(__name__)

# Valid content backends
_VALID_CONTENT_BACKENDS = frozenset({"local", "s3"})

# Valid database URL schemes
_VALID_DB_SCHEMES = frozenset({"sqlite", "postgresql", "postgres"})

# Environment variable to config field mapping
_ENV_VAR_MAP: dict[str, str] = {
    "A_SDLC_DATABASE_URL": "database_url",
    "A_SDLC_CONTENT_BACKEND": "content_backend",
    "A_SDLC_S3_BUCKET": "s3_bucket",
    "A_SDLC_S3_ENDPOINT": "s3_endpoint",
    "A_SDLC_S3_ACCESS_KEY": "s3_access_key",
    "A_SDLC_S3_SECRET_KEY": "s3_secret_key",
}


# Default storage settings — production requires explicit PostgreSQL + S3
_STORAGE_DEFAULTS: dict[str, Any] = {
    "content_backend": "s3",
    "s3_bucket": None,
    "s3_endpoint": None,
    "s3_access_key": None,
    "s3_secret_key": None,
}


@dataclass(frozen=True)
class StorageConfig:
    """Immutable storage configuration.

    Controls the database connection and content storage backend.
    Production deployments require an explicit PostgreSQL ``database_url``
    and S3-compatible ``content_backend``.

    When ``content_backend`` is ``'s3'``, the ``s3_bucket`` field is required.
    """

    database_url: str = ""
    content_backend: str = "s3"
    s3_bucket: str | None = None
    s3_endpoint: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    def __post_init__(self) -> None:
        """Validate configuration — database_url is required in production."""
        if not self.database_url:
            raise StorageConfigError(
                "A_SDLC_DATABASE_URL is required. "
                "Use Docker Compose or set the environment variable."
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration to a dictionary.

        Sensitive fields (s3_access_key, s3_secret_key) are masked.

        Returns:
            Dictionary of configuration values with secrets masked.
        """
        return {
            "database_url": self.database_url,
            "content_backend": self.content_backend,
            "s3_bucket": self.s3_bucket,
            "s3_endpoint": self.s3_endpoint,
            "s3_access_key": "***" if self.s3_access_key else None,
            "s3_secret_key": "***" if self.s3_secret_key else None,
        }

    @property
    def is_sqlite(self) -> bool:
        """Check if the database URL points to a SQLite database.

        Returns:
            True if the database URL uses the sqlite scheme.
        """
        return self.database_url.startswith("sqlite:///")

    @property
    def is_postgresql(self) -> bool:
        """Check if the database URL points to a PostgreSQL database.

        Returns:
            True if the database URL uses the postgresql or postgres scheme.
        """
        return self.database_url.startswith(("postgresql://", "postgres://"))

    @property
    def is_s3(self) -> bool:
        """Check if the content backend is S3.

        Returns:
            True if the content_backend is 's3'.
        """
        return self.content_backend == "s3"


class StorageConfigError(Exception):
    """Raised when storage configuration is invalid."""


def validate_storage_config(config: StorageConfig) -> None:
    """Validate a StorageConfig for consistency and completeness.

    Production deployments require PostgreSQL.  SQLite URLs are rejected
    unless running through test ``base_path`` isolation (which bypasses
    this validation).

    Args:
        config: The StorageConfig to validate.

    Raises:
        StorageConfigError: If the configuration is invalid, with details
            about what is wrong.
    """
    # Validate content_backend
    if config.content_backend not in _VALID_CONTENT_BACKENDS:
        raise StorageConfigError(
            f"Invalid content_backend '{config.content_backend}'. "
            f"Must be one of: {', '.join(sorted(_VALID_CONTENT_BACKENDS))}"
        )

    # Validate database_url scheme
    try:
        parsed = urlparse(config.database_url)
        scheme = parsed.scheme.lower()
        if scheme not in _VALID_DB_SCHEMES:
            raise StorageConfigError(
                f"Invalid database URL scheme '{scheme}'. "
                f"Must be one of: {', '.join(sorted(_VALID_DB_SCHEMES))}"
            )
        # Reject SQLite — PostgreSQL is required for production
        if scheme == "sqlite":
            raise StorageConfigError(
                f"PostgreSQL is required. Got: {config.database_url}. "
                "Set A_SDLC_DATABASE_URL to a PostgreSQL URL or use Docker Compose."
            )
    except Exception as exc:
        if isinstance(exc, StorageConfigError):
            raise
        raise StorageConfigError(
            f"Failed to parse database URL '{config.database_url}': {exc}"
        ) from exc

    # Validate S3 configuration when content_backend is 's3'
    if config.content_backend == "s3" and not config.s3_bucket:
        raise StorageConfigError(
            "s3_bucket is required when content_backend is 's3'. "
            "Set A_SDLC_S3_BUCKET environment variable or add "
            "storage.s3_bucket to config.yaml."
        )


def _read_env_overrides() -> dict[str, str]:
    """Read storage configuration from environment variables.

    Returns:
        Dictionary of config field names to their environment variable values.
        Only includes variables that are actually set.
    """
    overrides: dict[str, str] = {}
    for env_var, field_name in _ENV_VAR_MAP.items():
        value = os.environ.get(env_var)
        if value is not None:
            overrides[field_name] = value
    return overrides


def load_storage_config(
    project_dir: Path | None = None,
    *,
    validate: bool = True,
) -> StorageConfig:
    """Load storage configuration with layered merging.

    Priority (highest to lowest):
    1. Environment variables (A_SDLC_DATABASE_URL, A_SDLC_S3_*, etc.)
    2. Project config (.sdlc/config.yaml storage section)
    3. Global config (~/.config/a-sdlc/config.yaml storage section)

    Args:
        project_dir: Project directory. Defaults to current working directory.
        validate: Whether to validate the resulting config. Defaults to True.

    Returns:
        StorageConfig with merged settings.

    Raises:
        StorageConfigError: If validate=True and the configuration is invalid,
            with details about the specific validation failure.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    # Load global config
    global_config = _load_yaml(GLOBAL_CONFIG_FILE)
    global_storage = global_config.get("storage", {})
    if not isinstance(global_storage, dict):
        global_storage = {}

    # Load project config
    project_config_path = project_dir / PROJECT_CONFIG_DIR / PROJECT_CONFIG_FILE
    project_config = _load_yaml(project_config_path)
    project_storage = project_config.get("storage", {})
    if not isinstance(project_storage, dict):
        project_storage = {}

    # Merge: defaults < global < project
    merged = _deep_merge(_STORAGE_DEFAULTS, global_storage)
    merged = _deep_merge(merged, project_storage)

    # Apply environment variable overrides (highest priority)
    env_overrides = _read_env_overrides()
    merged.update(env_overrides)

    # Build config
    config = StorageConfig(
        database_url=str(merged.get("database_url", "")),
        content_backend=str(merged.get("content_backend", "s3")),
        s3_bucket=merged.get("s3_bucket") or None,
        s3_endpoint=merged.get("s3_endpoint") or None,
        s3_access_key=merged.get("s3_access_key") or None,
        s3_secret_key=merged.get("s3_secret_key") or None,
    )

    if validate:
        try:
            validate_storage_config(config)
        except StorageConfigError as exc:
            logger.error("Storage configuration validation failed: %s", exc)
            raise

    return config


# ============================================================================
# Lazy singleton
# ============================================================================

_singleton_lock = threading.Lock()
_singleton_instance: StorageConfig | None = None


def get_storage_config(
    project_dir: Path | None = None,
    *,
    force_reload: bool = False,
) -> StorageConfig:
    """Get the storage configuration singleton.

    Uses a lazy initialization pattern with thread-safe locking.
    The configuration is loaded once and cached for subsequent calls.
    Use ``force_reload=True`` to invalidate the cache and reload.

    Args:
        project_dir: Project directory. Defaults to current working directory.
        force_reload: If True, discard the cached instance and reload
            from config files and environment. Defaults to False.

    Returns:
        Cached StorageConfig instance.

    Raises:
        StorageConfigError: If the configuration is invalid, with details
            about the specific validation failure.
    """
    global _singleton_instance

    if _singleton_instance is not None and not force_reload:
        return _singleton_instance

    with _singleton_lock:
        # Double-check after acquiring lock
        if _singleton_instance is not None and not force_reload:
            return _singleton_instance

        _singleton_instance = load_storage_config(project_dir)
        return _singleton_instance


def reset_storage_config() -> None:
    """Reset the storage configuration singleton.

    Intended for use in tests to ensure a clean state between test cases.
    """
    global _singleton_instance
    with _singleton_lock:
        _singleton_instance = None
