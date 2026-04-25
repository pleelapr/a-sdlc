"""
a-sdlc MCP Server.

Provides MCP tools for managing SDLC artifacts (PRDs, tasks, sprints)
through Claude Code integration.

Architecture: Hybrid storage
- SQLite database: Metadata and file path references (fast queries)
- Markdown files: Source of truth for content (LLM-generated, git-friendly)

Usage:
    a-sdlc serve              # Start MCP server with stdio transport
    uvx a-sdlc serve          # Run via uvx (Claude Code config)

Tool implementations are split across submodules (project_tools, prd_tools,
task_tools, etc.).  Each submodule uses ``import a_sdlc.server as _server``
and accesses ``_server.mcp``, ``_server.get_db()`` etc. via module-attribute
lookup at call time.  This means existing ``@patch("a_sdlc.server.get_db")``
patterns in tests continue to work unchanged.
"""

import atexit
import contextlib
import logging
import os
import re
import signal
import socket
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from a_sdlc.core.content import (  # noqa: F401 — re-exported for submodules
    get_content_manager as get_content_manager,
)
from a_sdlc.core.database import get_db as _get_raw_db
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
from a_sdlc.server.governance_helpers import (  # noqa: F401 — re-exported for submodules
    load_governance_health_config as _load_governance_health_config,
)
from a_sdlc.server.governance_helpers import (  # noqa: F401
    load_routing_config as _load_routing_config,
)
from a_sdlc.server.quality_helpers import (  # noqa: F401 — re-exported for test patching
    load_quality_config_safe as _load_quality_config_safe,
)
from a_sdlc.storage import (  # noqa: F401 — re-exported for submodules
    get_storage as get_storage,
)

_logger = logging.getLogger("a-sdlc-server")

_data_access: MCPDataAccess | None = None


def get_db():
    """Get database access proxy for MCP tools."""
    global _data_access
    if _data_access is None:
        _data_access = MCPDataAccess(_get_raw_db())
    return _data_access


# Module-level variable to track UI server process
_ui_process: subprocess.Popen | None = None

# In-memory sprint quality waivers: sprint_id -> {reason, waived_at, sprint_id}
# Waivers persist for the lifetime of the MCP server process (FR-037).
_sprint_waivers: dict[str, dict[str, Any]] = {}

# Initialize FastMCP server
mcp = FastMCP(
    name="asdlc",
    instructions="SDLC management tools for PRDs, tasks, and sprints",
)


# =============================================================================
# Helper functions (accessed by submodules via _server.xxx())
# =============================================================================


def _get_current_project_id() -> str | None:
    """Auto-detect current project from working directory."""
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

    return ExternalSyncService(get_db(), get_content_manager())


# =============================================================================
# Submodule Tool Registration
# =============================================================================
# Wildcard imports trigger @_server.mcp.tool() registration in each submodule.
# ``mcp`` and ``get_db`` MUST be defined above before these imports execute.

from .agent_tools import *  # noqa: E402, F403, F401
from .challenge_tools import *  # noqa: E402, F403, F401

# Explicit re-exports for test patching and _auto_parse_requirements
from .challenge_tools import (  # noqa: E402, F401
    _detect_stale_loop as _detect_stale_loop,
)
from .design_tools import *  # noqa: E402, F403, F401
from .execution_tools import *  # noqa: E402, F403, F401
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

UI_PORT = 3847
_UI_PID_FILE = Path.home() / ".a-sdlc" / "ui.pid"


def _is_port_in_use(port: int) -> bool:
    """Check if a port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _find_executable(name: str) -> str | None:
    """Find an executable, checking common locations if not in PATH."""
    import shutil

    # Try PATH first
    path = shutil.which(name)
    if path:
        return path

    # Check common locations not in PATH
    home = Path.home()
    common_paths = [
        home / ".local" / "bin" / name,  # uv tools location
        Path("/opt/homebrew/bin") / name,  # macOS Homebrew
        Path("/usr/local/bin") / name,  # Common Unix location
    ]

    for p in common_paths:
        if p.exists() and os.access(p, os.X_OK):
            return str(p)

    return None


def _open_browser_when_ready(port: int, timeout: float = 5.0) -> None:
    """Poll until the UI port is ready, then open the browser.

    Runs in a daemon thread so it doesn't block the MCP server.
    """
    import time
    import webbrowser

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if _is_port_in_use(port):
            webbrowser.open(f"http://127.0.0.1:{port}")
            return
        time.sleep(0.3)


def _cleanup_stale_ui() -> None:
    """Remove stale UI PID file if the process is dead."""
    if not _UI_PID_FILE.exists():
        return
    try:
        pid = int(_UI_PID_FILE.read_text().strip())
        os.kill(pid, 0)  # Check if alive
        # Process exists — but if it's not on our port, the PID file is stale
        if not _is_port_in_use(UI_PORT):
            _UI_PID_FILE.unlink(missing_ok=True)
    except (ValueError, OSError, ProcessLookupError):
        # Process dead — clean up PID file
        _UI_PID_FILE.unlink(missing_ok=True)


def _start_ui_server() -> subprocess.Popen | None:
    """Start the UI server in the background if not already running.

    Returns None if UI is already running or if dependencies are not available.
    The UI server lifecycle is tied to the MCP server - it will be terminated
    when the MCP server exits.

    Auto-opens the browser when the UI is ready unless A_SDLC_NO_BROWSER=1.
    """
    import threading

    global _ui_process

    # Clean up stale UI process from a previous crashed session
    _cleanup_stale_ui()

    already_running = _is_port_in_use(UI_PORT)
    if already_running:
        _logger.info("UI already running on port %d, skipping startup", UI_PORT)
        return None

    # Check if UI dependencies are available
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        # UI dependencies not installed, skip UI startup
        return None

    # Open a log file for UI stderr so crashes are diagnosable
    log_dir = Path.home() / ".a-sdlc"
    log_dir.mkdir(parents=True, exist_ok=True)
    ui_log = open(log_dir / "ui.log", "a")  # noqa: SIM115

    # Find the a-sdlc executable
    asdlc_path = _find_executable("a-sdlc")
    if asdlc_path:
        _ui_process = subprocess.Popen(
            [asdlc_path, "ui"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=ui_log,
        )
    else:
        # Try uvx as fallback
        uvx_path = _find_executable("uvx")
        if uvx_path:
            _ui_process = subprocess.Popen(
                [uvx_path, "a-sdlc", "ui"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=ui_log,
            )

    # Write UI PID for orphan detection
    if _ui_process is not None:
        _logger.info("Launched UI server (pid=%d, port=%d)", _ui_process.pid, UI_PORT)
        _UI_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _UI_PID_FILE.write_text(str(_ui_process.pid))
    else:
        _logger.warning("Failed to start UI server: no executable found")

    # Auto-open browser if we started the UI and opt-out is not set
    if _ui_process is not None and not os.environ.get("A_SDLC_NO_BROWSER"):
        t = threading.Thread(
            target=_open_browser_when_ready,
            args=(UI_PORT,),
            daemon=True,
        )
        t.start()

    return _ui_process


def _stop_ui_server() -> None:
    """Stop the UI server if it was started by this MCP server."""
    global _ui_process
    if _ui_process is not None:
        _logger.info("Stopping UI server (pid=%d)", _ui_process.pid)
        _ui_process.terminate()
        try:
            _ui_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ui_process.kill()
        _ui_process = None
        _UI_PID_FILE.unlink(missing_ok=True)


def _signal_handler(signum: int, frame) -> None:
    """Handle termination signals by cleaning up and exiting."""
    _logger.info("Received signal %d, shutting down", signum)
    _stop_ui_server()
    _mcp_remove_pid()
    sys.exit(0)


_MCP_PID_FILE = Path.home() / ".a-sdlc" / "mcp.pid"


def _mcp_is_running() -> bool:
    """Check if another MCP server instance is already running."""
    if _MCP_PID_FILE.exists():
        try:
            pid = int(_MCP_PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return True
        except (ValueError, OSError, ProcessLookupError):
            # Stale PID file — remove it
            with contextlib.suppress(OSError):
                _MCP_PID_FILE.unlink()
    return False


def _mcp_write_pid() -> None:
    """Write the current process PID to the MCP PID file."""
    _MCP_PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MCP_PID_FILE.write_text(str(os.getpid()))


def _mcp_remove_pid() -> None:
    """Remove the MCP PID file if it exists."""
    try:
        if _MCP_PID_FILE.exists():
            _MCP_PID_FILE.unlink()
    except OSError:
        pass


def run_server(transport: str = "stdio") -> None:
    """Run the MCP server.

    For stdio transport, every client (Claude Code session) needs its own
    server process connected via stdin/stdout pipes — no singleton check.

    For streamable-http transport, enforces a singleton so multiple clients
    share one endpoint.

    Child processes spawned by sprint-run set ``A_SDLC_CHILD=1`` and
    always bypass the singleton check.

    Args:
        transport: Transport type ('stdio' or 'streamable-http').
    """
    # Configure file logging (safe for stdio — never touches stdout/stderr)
    log_dir = Path.home() / ".a-sdlc"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "server.log", maxBytes=1_000_000, backupCount=3
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)

    is_child = os.environ.get("A_SDLC_CHILD") == "1"

    if not is_child and transport != "stdio":
        # Singleton only for HTTP transport — stdio is inherently per-session
        if _mcp_is_running():
            sys.exit(0)
        _mcp_write_pid()
        atexit.register(_mcp_remove_pid)

    if not is_child:
        # Start UI server in background (only for primary instance)
        _start_ui_server()

    # Register cleanup — only when actually running, not on import
    atexit.register(_stop_ui_server)
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Run MCP server
    try:
        _logger.info(
            "MCP server starting (transport=%s, pid=%d)", transport, os.getpid()
        )
        mcp.run(transport=transport)
    except Exception:
        _logger.exception("MCP server crashed")
        _stop_ui_server()
        sys.exit(1)
    finally:
        _logger.info("MCP server shutting down (pid=%d)", os.getpid())


if __name__ == "__main__":
    run_server()
