"""
a-sdlc MCP Server.

Provides MCP tools for managing SDLC artifacts (PRDs, tasks, sprints)
through Claude Code integration.

Architecture: Hybrid storage (PostgreSQL + S3)
- PostgreSQL database: Metadata and file path references (fast queries)
- S3/MinIO: Source of truth for content (Markdown files)

Usage:
    a-sdlc serve              # Start combined MCP + UI server
    docker compose up -d      # Recommended deployment

Tool implementations are split across submodules (project_tools, prd_tools,
task_tools, etc.).  Each submodule uses ``import a_sdlc.server as _server``
and accesses ``_server.mcp``, ``_server.get_db()`` etc. via module-attribute
lookup at call time.  This means existing ``@patch("a_sdlc.server.get_db")``
patterns in tests continue to work unchanged.
"""

import asyncio
import atexit
import contextlib
import functools
import json
import logging
import os
import time

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]  # Windows
import re
import signal
import socket
import subprocess  # noqa: F401 — kept for test patching (worktree_tools tests)
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from a_sdlc.core.content import (  # noqa: F401 — kept for test mocking compatibility
    get_content_manager as get_content_manager,
)
from a_sdlc.core.git_config import (  # noqa: F401 — re-exported for submodules
    get_effective_config_summary as get_effective_config_summary,
)
from a_sdlc.core.git_config import (
    load_git_safety_config as load_git_safety_config,
)
from a_sdlc.core.git_config import (
    save_git_safety_config as save_git_safety_config,
)
from a_sdlc.core.quality_config import (  # noqa: F401 — re-exported for submodules
    load_quality_config as load_quality_config,
)
from a_sdlc.core.review_config import (  # noqa: F401 — re-exported for submodules
    load_review_config as load_review_config,
)
from a_sdlc.server.challenge import (  # noqa: F401 — re-exported for test patching
    load_challenge_config as _load_challenge_config,
)
from a_sdlc.server.data_access import MCPDataAccess
from a_sdlc.server.quality_helpers import (  # noqa: F401 — re-exported for test patching
    load_quality_config_safe as _load_quality_config_safe,
)
from a_sdlc.storage import (  # noqa: F401 — re-exported for submodules
    get_storage as get_storage,
)

_logger = logging.getLogger("a-sdlc-server")


def _migrate_local_content_to_s3(storage) -> None:
    """Upload local filesystem content to S3 if it's missing from the bucket.

    When switching from local to S3 content backend, existing markdown files
    may still live on the local filesystem.  This function scans the local
    content directory and uploads any files that don't yet exist in S3.

    Runs once at server startup when S3 is configured.  Errors are logged
    but do not prevent the server from starting.
    """
    content_dir = storage.base_path / "content"
    if not content_dir.is_dir():
        return

    cm = storage.content_mgr
    backend = cm._backend

    # Only migrate when we have an S3 backend
    from a_sdlc.core.content import S3ContentBackend

    if not isinstance(backend, S3ContentBackend):
        return

    migrated = 0
    skipped = 0
    try:
        for md_file in content_dir.rglob("*.md"):
            try:
                if backend.exists(str(md_file)):
                    skipped += 1
                    continue
                content = md_file.read_text(encoding="utf-8")
                backend.write_content(str(md_file), content)
                migrated += 1
            except Exception:
                _logger.debug("Failed to migrate %s to S3", md_file, exc_info=True)
    except Exception:
        _logger.warning("Local→S3 content migration scan failed", exc_info=True)

    if migrated > 0:
        _logger.info(
            "Migrated %d local content files to S3 (%d already existed)",
            migrated,
            skipped,
        )


def _init_storage_backend() -> None:
    """Initialize the storage backend with configurable database and content backends.

    Loads ``StorageConfig`` from environment variables and config files, passes
    it to ``HybridStorage``, and logs which backend is active.  When PostgreSQL
    is configured, runs Alembic auto-migration (``upgrade head``) to apply any
    pending schema changes.

    Called once at server startup.
    """
    from a_sdlc.core.storage_config import get_storage_config

    config = get_storage_config()

    # Initialize the global storage singleton with the loaded config
    from a_sdlc.storage import init_storage

    storage = init_storage(config=config)

    # Log backend selection
    _logger.info("Using postgresql backend (url=%s)", _mask_url(config.database_url))
    _run_auto_migration(config)

    _logger.info("Using s3 content backend (bucket=%s)", config.s3_bucket)
    _migrate_local_content_to_s3(storage)


def _mask_url(url: str) -> str:
    """Mask password in a database URL for safe logging.

    Args:
        url: Database connection URL.

    Returns:
        URL with the password portion replaced by ``***``.
    """
    from urllib.parse import urlparse, urlunparse

    try:
        parsed = urlparse(url)
        if parsed.password:
            netloc = f"{parsed.username}:***@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    return url


def _run_auto_migration(config) -> None:
    """Run Alembic auto-migration when PostgreSQL is configured.

    Executes ``alembic upgrade head`` to apply any pending migrations.
    Failures are logged but do not prevent server startup.

    Args:
        config: ``StorageConfig`` instance with the database URL.
    """
    try:
        from alembic.config import Config as AlembicConfig

        from alembic import command as alembic_command

        # Locate alembic.ini relative to the package root
        package_root = Path(__file__).resolve().parent.parent.parent
        alembic_ini = package_root / "alembic.ini"
        if not alembic_ini.exists():
            _logger.debug(
                "alembic.ini not found at %s; skipping auto-migration", alembic_ini
            )
            return

        alembic_cfg = AlembicConfig(str(alembic_ini))
        alembic_cfg.set_main_option("sqlalchemy.url", config.database_url)

        _logger.info("Running auto-migration (alembic upgrade head)")
        alembic_command.upgrade(alembic_cfg, "head")
        _logger.info("Auto-migration completed successfully")
    except ImportError:
        _logger.debug("Alembic not installed; skipping auto-migration")
    except Exception:
        _logger.exception("Auto-migration failed; server will start with existing schema")


_data_access: MCPDataAccess | None = None

# In-memory active project set by switch_project().
# Checked first by _get_current_project_id() so that Docker/cloud
# environments (where cwd doesn't match any project path) can resolve
# project context after a switch_project() call.
_active_project_id: str | None = None


# =============================================================================
# Structured JSON Logging
# =============================================================================


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter.

    Outputs one JSON object per line with fields:
    - ts: ISO-8601 timestamp with milliseconds
    - level: Log level name (INFO, ERROR, etc.)
    - event: Log event / message
    - Additional fields from ``extra`` dict on the log record

    Example output::

        {"ts": "2026-05-20T10:30:00.123", "level": "INFO", "event": "server_starting"}
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a single JSON line."""
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        # Merge structured fields from extra (set via logger.info(..., extra={...}))
        for key in ("tool", "duration_ms", "status", "error_type", "error_message"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        # Include exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            entry["error_type"] = record.exc_info[0].__name__
            entry["error_message"] = str(record.exc_info[1])
            entry["traceback"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def instrument_tool(fn):
    """Decorator that instruments an MCP tool handler with structured logging.

    Logs ``tool_call_start`` when the tool is invoked, ``tool_call_end`` on
    success (with duration_ms), and ``tool_call_error`` on exception (with
    exception details).  Also records events on the ``ServerHealth`` singleton
    for the ring-buffer observable via ``/health?events=true``.

    Works with both sync and async tool handlers.
    """
    tool_name = fn.__name__

    @functools.wraps(fn)
    def _sync_wrapper(*args, **kwargs):
        _logger.info(
            "tool_call_start",
            extra={"tool": tool_name, "status": "started"},
        )
        health = ServerHealth()
        health.record_event("tool_call_start", tool_name)
        t0 = time.monotonic()
        try:
            result = fn(*args, **kwargs)
            elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
            _logger.info(
                "tool_call_end",
                extra={
                    "tool": tool_name,
                    "duration_ms": elapsed_ms,
                    "status": "ok",
                },
            )
            health.record_event("tool_call_end", f"{tool_name} ok {elapsed_ms}ms")
            return result
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
            _logger.error(
                "tool_call_error",
                extra={
                    "tool": tool_name,
                    "duration_ms": elapsed_ms,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            health.record_event("tool_call_error", f"{tool_name}: {exc}")
            health.record_error(exc)
            raise

    @functools.wraps(fn)
    async def _async_wrapper(*args, **kwargs):
        _logger.info(
            "tool_call_start",
            extra={"tool": tool_name, "status": "started"},
        )
        health = ServerHealth()
        health.record_event("tool_call_start", tool_name)
        t0 = time.monotonic()
        try:
            result = await fn(*args, **kwargs)
            elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
            _logger.info(
                "tool_call_end",
                extra={
                    "tool": tool_name,
                    "duration_ms": elapsed_ms,
                    "status": "ok",
                },
            )
            health.record_event("tool_call_end", f"{tool_name} ok {elapsed_ms}ms")
            return result
        except Exception as exc:
            elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
            _logger.error(
                "tool_call_error",
                extra={
                    "tool": tool_name,
                    "duration_ms": elapsed_ms,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            health.record_event("tool_call_error", f"{tool_name}: {exc}")
            health.record_error(exc)
            raise

    if asyncio.iscoroutinefunction(fn):
        return _async_wrapper
    return _sync_wrapper


def get_db():
    """Get database access proxy for MCP tools.

    Uses the database backend from HybridStorage, which respects
    StorageConfig (PostgreSQL when ``A_SDLC_DATABASE_URL`` is set,
    the configured backend).  This ensures MCP tools read from the same
    database that the rest of the system writes to.
    """
    global _data_access
    if _data_access is None:
        _data_access = MCPDataAccess(get_storage().db)
    return _data_access


# In-memory sprint quality waivers: sprint_id -> {reason, waived_at, sprint_id}
# Waivers persist for the lifetime of the MCP server process (FR-037).
_sprint_waivers: dict[str, dict[str, Any]] = {}

# Initialize FastMCP server
# stateless_http=True avoids in-memory session tracking, which prevents
# "Session not found" 404s after container/process restarts.
mcp: FastMCP = FastMCP(
    name="asdlc",
    instructions="SDLC management tools for PRDs, tasks, and sprints",
    stateless_http=True,
)


# =============================================================================
# Helper functions (accessed by submodules via _server.xxx())
# =============================================================================


def _get_current_project_id() -> str | None:
    """Resolve the current project context.

    Resolution order:
    1. In-memory active project (set by ``switch_project()``)
    2. Auto-detect from working directory (``os.getcwd()``)

    This ensures Docker/cloud environments where cwd is ``/`` can still
    resolve project context after a ``switch_project()`` call.
    """
    global _active_project_id

    # 1. Explicit switch takes priority
    if _active_project_id is not None:
        db = get_db()
        project = db.get_project(_active_project_id)
        if project:
            db.update_project_accessed(_active_project_id)
            return _active_project_id
        # Stale reference — clear it
        _active_project_id = None

    # 2. Auto-detect from working directory
    cwd = os.getcwd()
    db = get_db()
    project = db.get_project_by_path(cwd)
    if project:
        db.update_project_accessed(project["id"])
        return project["id"]
    return None


def _slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug.strip("-")


def _get_sync_service():
    """Get sync service instance."""
    from a_sdlc.server.sync import ExternalSyncService

    return ExternalSyncService(get_db(), get_storage().content_mgr)


# =============================================================================
# Health Endpoint (custom Starlette route for HTTP transports)
# =============================================================================

from a_sdlc.server.health import ServerHealth  # noqa: E402


@mcp.custom_route("/health", methods=["GET"], name="health")
async def _health_endpoint(request):
    """Return server health as JSON.

    Available on HTTP transports (streamable-http, SSE).
    Optional ``?events=true`` query param includes the full ring buffer.
    """
    from starlette.responses import JSONResponse

    include_events = request.query_params.get("events", "").lower() == "true"
    health = ServerHealth()
    payload = health.get_health(include_events=include_events)
    return JSONResponse(payload)


# =============================================================================
# Submodule Tool Registration
# =============================================================================
# Wildcard imports trigger @_server.mcp.tool() registration in each submodule.
# ``mcp`` and ``get_db`` MUST be defined above before these imports execute.

from .challenge_tools import *  # noqa: E402, F403, F401

# Explicit re-exports for test patching and _auto_parse_requirements
from .challenge_tools import (  # noqa: E402, F401
    _detect_stale_loop as _detect_stale_loop,
)
from .design_tools import *  # noqa: E402, F403, F401
from .github_tools import *  # noqa: E402, F403, F401
from .prd_tools import *  # noqa: E402, F403, F401
from .project_tools import *  # noqa: E402, F403, F401
from .quality_tools import *  # noqa: E402, F403, F401
from .quality_tools import classify_depth as classify_depth  # noqa: E402, F401
from .review_tools import *  # noqa: E402, F403, F401
from .sprint_tools import *  # noqa: E402, F403, F401
from .sync_tools import *  # noqa: E402, F403, F401
from .task_tools import *  # noqa: E402, F403, F401
from .worktree_tools import *  # noqa: E402, F403, F401


# _auto_parse_requirements is defined AFTER wildcard imports because it
# references classify_depth() which is imported from quality_tools above.
def _auto_parse_requirements(db: Any, prd_id: str, content: str) -> None:
    """Parse requirements from PRD markdown content and upsert into DB.

    Scans for lines matching requirement patterns:
    - **FR-NNN**: Summary text (functional)
    - **NFR-NNN**: Summary text (non-functional)
    - **AC-NNN**: Summary text (acceptance criteria)

    Includes depth classification (structural/behavioral/integration) using
    the same classify_depth() logic as the parse_requirements MCP tool.

    Args:
        db: Database instance.
        prd_id: PRD identifier.
        content: Raw markdown content of the PRD file.
    """
    pattern = re.compile(
        r"\*\*((FR|NFR|AC)-(\d{3}))\*\*[:\s]+(.+)",
        re.IGNORECASE,
    )
    type_map = {
        "FR": "functional",
        "NFR": "non-functional",
        "AC": "ac",
    }
    for match in pattern.finditer(content):
        req_number = match.group(1).upper()
        prefix = match.group(2).upper()
        summary = match.group(4).strip()
        req_type = type_map.get(prefix, "functional")
        req_id = f"{prd_id}:{req_number}"
        depth = classify_depth(summary)
        db.upsert_requirement(
            id=req_id,
            prd_id=prd_id,
            req_type=req_type,
            req_number=req_number,
            summary=summary,
            depth=depth,
        )


# =============================================================================
# Server Lifecycle
# =============================================================================

class PortConflictError(Exception):
    """Raised when a required port is already in use by another process."""

    def __init__(self, port: int, pid: int | None = None):
        self.port = port
        self.pid = pid
        if pid:
            msg = (
                f"Port {port} is already in use by PID {pid}. "
                f"Stop that process or use --mcp-port/--ui-port to choose a different port."
            )
        else:
            msg = (
                f"Port {port} is already in use. "
                f"Stop the process using that port or use --mcp-port/--ui-port to choose a different port."
            )
        super().__init__(msg)


def _is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _get_port_pid(port: int) -> int | None:
    """Try to identify the PID of the process using a given port.

    Uses ``lsof`` on macOS/Linux.  Returns None if the PID cannot be
    determined (e.g. on Windows or if lsof is not available).
    """
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # lsof may return multiple PIDs (one per line); take the first
            first_line = result.stdout.strip().split("\n")[0]
            return int(first_line.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return None


def _cleanup_stale_mcp_pid() -> bool:
    """Remove stale PID file if the recorded process is no longer running.

    Returns True if a stale PID file was cleaned up, False otherwise.
    """
    if not _MCP_PID_FILE.exists():
        return False
    try:
        pid = int(_MCP_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        # Corrupt PID file — remove it
        with contextlib.suppress(OSError):
            _MCP_PID_FILE.unlink()
        return True

    try:
        os.kill(pid, 0)
        return False  # Process is alive — not stale
    except OSError:
        # Process is dead — stale PID file
        with contextlib.suppress(OSError):
            _MCP_PID_FILE.unlink()
        _logger.info("Cleaned up stale PID file (dead PID: %d)", pid)
        return True


def _check_port_availability(mcp_port: int, ui_port: int) -> None:
    """Check that both MCP and UI ports are available before binding.

    Raises PortConflictError with actionable information if a port is in use.
    """
    for port, label in [(mcp_port, "MCP"), (ui_port, "UI")]:
        if _is_port_in_use(port):
            pid = _get_port_pid(port)
            _logger.error(
                "Port %d (%s) is already in use (pid=%s)",
                port,
                label,
                pid or "unknown",
            )
            raise PortConflictError(port, pid)


def _open_browser_when_ready(port: int, timeout: float = 5.0) -> None:
    """Poll until the UI port is ready, then open the browser.

    Runs in a daemon thread so it doesn't block the server.
    """
    import time
    import webbrowser

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if _is_port_in_use(port):
            webbrowser.open(f"http://127.0.0.1:{port}")
            return
        time.sleep(0.3)


def _signal_handler(signum: int, frame) -> None:
    """Handle termination signals by cleaning up and exiting."""
    _logger.info("Received signal %d, shutting down", signum)
    _mcp_remove_pid()
    sys.exit(0)


_MCP_PID_FILE = Path.home() / ".a-sdlc" / "mcp.pid"

# File descriptor kept open to hold the flock for process lifetime (FR-008)
_mcp_pid_fd: int | None = None


def _mcp_acquire_pid() -> bool:
    """Try to acquire the MCP PID file atomically using flock.

    Combines the check-if-running and write-PID steps into a single atomic
    operation, eliminating the TOCTOU race condition between the old
    ``_mcp_is_running()`` and ``_mcp_write_pid()`` functions.

    The file descriptor is kept open for the lifetime of the process so that
    the advisory lock is held until exit.  The OS releases the lock
    automatically when the process terminates.

    Returns:
        True if the PID file was acquired (we are the singleton).
        False if another live process already holds it.
    """
    global _mcp_pid_fd
    _MCP_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(_MCP_PID_FILE), os.O_CREAT | os.O_RDWR)
    if fcntl:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            # Another process holds the lock — it's alive
            os.close(fd)
            return False

    # Lock acquired — check if existing PID in file is still alive
    content = os.read(fd, 64).decode().strip()
    if content:
        try:
            pid = int(content)
            os.kill(pid, 0)
            # Process is alive but we got the lock — shouldn't normally happen,
            # but treat as "already running" for safety
            os.close(fd)
            return False
        except (ValueError, OSError):
            pass  # Stale PID — overwrite it

    # Write our PID
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    # Keep fd open so the lock is held for the process lifetime
    _mcp_pid_fd = fd
    return True


def _mcp_remove_pid() -> None:
    """Remove the MCP PID file and release the flock if held."""
    global _mcp_pid_fd
    if _mcp_pid_fd is not None:
        with contextlib.suppress(OSError):
            os.close(_mcp_pid_fd)
        _mcp_pid_fd = None
    with contextlib.suppress(OSError):
        _MCP_PID_FILE.unlink()


def run_server(
    mcp_port: int = 8765,
    ui_port: int = 3847,
    host: str = "0.0.0.0",
) -> None:
    """Run both MCP (streamable-http) and UI (FastAPI/uvicorn) in a single process.

    This is the primary server entry-point.  Both servers share the same
    asyncio event loop, the same HybridStorage instance, and a single PID
    lock file.

    Args:
        mcp_port: Port for the MCP streamable-http endpoint (default 8765).
        ui_port: Port for the web UI dashboard (default 3847).
        host: Bind address for both servers (default "0.0.0.0").
    """
    import threading

    # Configure file logging
    log_dir = Path.home() / ".a-sdlc"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "server.log", maxBytes=1_000_000, backupCount=3
    )
    handler.setFormatter(JsonFormatter())
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)

    # Clean up stale PID file from a previous crash before acquiring
    _cleanup_stale_mcp_pid()

    # Singleton enforcement via PID lock
    if not _mcp_acquire_pid():
        _logger.info(
            "Another combined server is already running; exiting (pid=%d)",
            os.getpid(),
        )
        sys.exit(0)
    atexit.register(_mcp_remove_pid)

    # Check port availability before binding — provides actionable errors
    try:
        _check_port_availability(mcp_port, ui_port)
    except PortConflictError as exc:
        _mcp_remove_pid()
        _logger.error("Port conflict: %s", exc)
        raise SystemExit(
            f"Error: {exc}"
        ) from exc

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Initialize storage backend (loads config, logs backend, runs migration)
    _init_storage_backend()

    # Import UI dependencies -- fail loudly if not installed
    try:
        import uvicorn

        from a_sdlc.ui import create_app
    except ImportError as exc:
        _logger.error(
            "UI dependencies not installed, cannot run combined server: %s", exc
        )
        raise SystemExit(1) from exc

    ui_app = create_app()

    _logger.info(
        "Combined server starting (mcp_port=%d, ui_port=%d, host=%s, pid=%d)",
        mcp_port,
        ui_port,
        host,
        os.getpid(),
    )

    # Get the MCP ASGI app directly instead of calling mcp.run() which
    # starts its own event loop via anyio.run(). This lets us run both
    # servers as coroutines in a single asyncio event loop.
    mcp_app = mcp.streamable_http_app()

    mcp_config = uvicorn.Config(
        mcp_app,
        host=host,
        port=mcp_port,
        log_level="info",
        timeout_keep_alive=120,
    )
    mcp_server = uvicorn.Server(mcp_config)

    ui_config = uvicorn.Config(
        ui_app,
        host=host,
        port=ui_port,
        log_level="info",
        timeout_keep_alive=120,
    )
    ui_server = uvicorn.Server(ui_config)

    async def _run_both() -> None:
        """Run MCP and UI servers concurrently in a single event loop."""
        # Auto-open browser unless opt-out is set
        if not os.environ.get("A_SDLC_NO_BROWSER"):
            threading.Thread(
                target=_open_browser_when_ready,
                args=(ui_port,),
                daemon=True,
            ).start()

        # Run both servers as asyncio tasks
        mcp_task = asyncio.create_task(mcp_server.serve())
        ui_task = asyncio.create_task(ui_server.serve())

        # Wait for either server to finish (crash or shutdown)
        finished, pending = await asyncio.wait(
            [mcp_task, ui_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Log which server stopped first
        for task in finished:
            if task is mcp_task:
                _logger.info("MCP server stopped")
            else:
                _logger.info("UI server stopped")

        # Initiate graceful shutdown of the other server
        for task in pending:
            if task is mcp_task:
                mcp_server.should_exit = True
            else:
                ui_server.should_exit = True
            with contextlib.suppress(asyncio.CancelledError):
                await task

    try:
        asyncio.run(_run_both())
    except (KeyboardInterrupt, SystemExit):
        _logger.info("Combined server interrupted (pid=%d)", os.getpid())
    except Exception:
        _logger.exception("Combined server crashed")
        sys.exit(1)
    finally:
        _logger.info("Combined server shutting down (pid=%d)", os.getpid())


if __name__ == "__main__":
    run_server()

# Backward compatibility alias for existing imports
run_combined_server = run_server
