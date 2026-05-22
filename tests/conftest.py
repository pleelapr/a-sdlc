"""Global test configuration and safety guards.

Provides:
- Safety guards to prevent accidental Claude/Gemini CLI spawning
- Backend parametrization fixtures for integration testing
- Shared fixtures for database and content backend selection
"""

import os
import subprocess

import pytest

from a_sdlc.core.content import ContentManager
from a_sdlc.core.database import Database
from a_sdlc.storage import HybridStorage

_real_popen = subprocess.Popen
_real_run = subprocess.run


class _GuardPopen(_real_popen):
    """Popen subclass that blocks real claude/gemini CLI invocations during tests.

    Inherits from the real Popen so that ``subprocess.Popen[bytes]`` type
    annotations (used by the MCP library) remain valid.
    """

    def __init__(self, cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)):  # noqa: SIM108
            binary = str(cmd[0]) if cmd else ""
        else:
            binary = str(cmd)
        if "claude" in binary.lower() or "gemini" in binary.lower():
            raise RuntimeError(
                f"Test attempted to spawn a real CLI session: {cmd!r}. "
                "Ensure subprocess.Popen is properly mocked."
            )
        super().__init__(cmd, *args, **kwargs)


def _guard_run(cmd, *args, **kwargs):
    """Block real claude/gemini CLI invocations during tests."""
    if isinstance(cmd, (list, tuple)):  # noqa: SIM108
        binary = str(cmd[0]) if cmd else ""
    else:
        binary = str(cmd)
    if "claude" in binary.lower() or "gemini" in binary.lower():
        raise RuntimeError(
            f"Test attempted to spawn a real CLI session: {cmd!r}. "
            "Ensure subprocess.run is properly mocked."
        )
    return _real_run(cmd, *args, **kwargs)


@pytest.fixture(autouse=True, scope="session")
def _block_real_cli_sessions():
    """Global safety guard: prevent any test from spawning real Claude/Gemini sessions."""
    subprocess.Popen = _GuardPopen
    subprocess.run = _guard_run
    yield
    subprocess.Popen = _real_popen
    subprocess.run = _real_run


@pytest.fixture(autouse=True)
def _set_test_database_url(tmp_path, monkeypatch):
    """Provide a default SQLite database URL for tests.

    Production StorageConfig requires A_SDLC_DATABASE_URL.  Tests use SQLite
    via base_path isolation, but CLI tests and others may trigger
    StorageConfig loading.  This fixture ensures a valid URL is always
    available unless the test explicitly sets its own.
    """
    if "A_SDLC_DATABASE_URL" not in os.environ:
        monkeypatch.setenv(
            "A_SDLC_DATABASE_URL",
            f"sqlite:///{tmp_path / 'test.db'}",
        )
    if "A_SDLC_CONTENT_BACKEND" not in os.environ:
        monkeypatch.setenv("A_SDLC_CONTENT_BACKEND", "local")
    yield


@pytest.fixture(autouse=True)
def _reset_storage_singletons():
    """Reset all global singletons after each test to prevent cross-test pollution.

    Multiple module-level singletons persist across tests within a pytest
    session.  Without this fixture, a test that triggers singleton creation
    (e.g. by calling the real ``get_db()`` through an incomplete mock) would
    leak that instance to every subsequent test.
    """
    yield

    # Storage layer
    import a_sdlc.storage as _storage_mod

    _storage_mod._storage = None

    # MCP server data-access proxy and active project
    import a_sdlc.server as _server_mod

    _server_mod._data_access = None
    _server_mod._active_project_id = None

    # Core database singleton
    import a_sdlc.core.database as _db_mod

    _db_mod._db = None

    # Core content manager singleton
    import a_sdlc.core.content as _content_mod

    _content_mod._content_manager = None

    # Storage config singleton
    from a_sdlc.core.storage_config import reset_storage_config

    reset_storage_config()


# =========================================================================
# Backend Parametrization Fixtures
# =========================================================================


def _postgresql_adapter_available() -> bool:
    """Check whether the PostgreSQL storage adapter is importable."""
    try:
        from a_sdlc.core import postgresql_adapter  # noqa: F401
        return True
    except ImportError:
        return False


def _s3_content_adapter_available() -> bool:
    """Check whether the S3 content adapter is importable."""
    try:
        from a_sdlc.core import s3_content  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture(params=["sqlite", "postgresql"])
def db_backend_fixture(request, tmp_path):
    """Parametrized database backend yielding a Database instance.

    - **sqlite**: creates a temporary SQLite database (works today).
    - **postgresql**: skipped until the adapter is implemented (T00234).
    """
    backend = request.param

    if backend == "sqlite":
        db_path = tmp_path / "backend_test.db"
        db = Database(db_path=db_path)
        yield {"backend": backend, "db": db, "tmp_path": tmp_path}

    elif backend == "postgresql":
        if not _postgresql_adapter_available():
            pytest.skip("PostgreSQL adapter not yet implemented (T00234)")
        yield {"backend": backend, "db": None, "tmp_path": tmp_path}


@pytest.fixture(params=["local", "s3"])
def content_backend_fixture(request, tmp_path):
    """Parametrized content backend yielding a ContentManager instance.

    - **local**: creates a temporary filesystem content manager (works today).
    - **s3**: skipped until the S3 adapter is implemented (T00235).
    """
    backend = request.param

    if backend == "local":
        content_path = tmp_path / "content"
        content_mgr = ContentManager(base_path=content_path)
        yield {"backend": backend, "content_mgr": content_mgr, "tmp_path": tmp_path}

    elif backend == "s3":
        if not _s3_content_adapter_available():
            pytest.skip("S3 content adapter not yet implemented (T00235)")
        yield {"backend": backend, "content_mgr": None, "tmp_path": tmp_path}


@pytest.fixture
def hybrid_storage_fixture(tmp_path):
    """Create a fresh HybridStorage instance backed by SQLite + local filesystem.

    Suitable for tests that need the full storage layer without
    backend parametrization.
    """
    storage = HybridStorage(base_path=tmp_path / "hybrid")
    yield storage
