"""
a-sdlc Web UI.

Provides a FastAPI + HTMX dashboard for viewing and managing
PRDs, tasks, sprints, and pipeline runs.

Usage:
    a-sdlc ui              # Start web server on http://localhost:3847
    a-sdlc ui --port 8000  # Custom port
    a-sdlc ui stop         # Stop running UI server
"""

import asyncio
import atexit
import contextlib
import logging
import os
import signal
import sys
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import uvicorn
    from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.templating import Jinja2Templates
except ImportError as err:
    raise ImportError(
        "Web UI dependencies not installed. "
        "Install with: pip install 'a-sdlc[ui]'"
    ) from err

from a_sdlc.storage import get_storage  # noqa: E402

# PID file location
PID_FILE = Path.home() / ".a-sdlc" / "ui.pid"


def _get_pid() -> int | None:
    """Read PID from file if it exists."""
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except (ValueError, OSError):
            return None
    return None


def _is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _write_pid() -> None:
    """Write current PID to file."""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def _remove_pid() -> None:
    """Remove PID file."""
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except OSError:
        pass


def _cleanup_stale_pid() -> bool:
    """Check for stale PID and kill if necessary. Returns True if cleanup was needed."""
    pid = _get_pid()
    if pid is None:
        return False

    if _is_process_running(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            # Give it a moment to shut down
            import time
            time.sleep(0.5)

            # Force kill if still running
            if _is_process_running(pid):
                os.kill(pid, signal.SIGKILL)

            _remove_pid()
            return True
        except (OSError, ProcessLookupError):
            pass

    # PID file exists but process is gone - clean up
    _remove_pid()
    return False


def stop_server() -> bool:
    """Stop the running UI server. Returns True if a server was stopped."""
    pid = _get_pid()
    if pid is None:
        return False

    if not _is_process_running(pid):
        _remove_pid()
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        import time
        time.sleep(0.5)

        if _is_process_running(pid):
            os.kill(pid, signal.SIGKILL)

        _remove_pid()
        return True
    except (OSError, ProcessLookupError):
        _remove_pid()
        return False


def _signal_handler(signum: int, frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    _remove_pid()
    sys.exit(0)

# Get templates directory
TEMPLATES_DIR = Path(__file__).parent / "templates"


# =============================================================================
# WebSocket Infrastructure
# =============================================================================


class ConnectionManager:
    """Manages WebSocket connections grouped by execution run ID.

    Each run_id maps to a list of active WebSocket connections.
    When a client connects to /ws/runs/{run_id}, it is added to
    the appropriate list.  On disconnect (or send failure), it is
    removed.  The broadcast method sends a JSON message to every
    connection watching a given run.
    """

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, run_id: str) -> None:
        """Accept a WebSocket connection and register it for a run."""
        await websocket.accept()
        self.active_connections.setdefault(run_id, []).append(websocket)
        logger.debug("WS connected for run %s (total: %d)", run_id, len(self.active_connections[run_id]))

    def disconnect(self, websocket: WebSocket, run_id: str) -> None:
        """Remove a WebSocket connection from a run's connection list."""
        conns = self.active_connections.get(run_id, [])
        if websocket in conns:
            conns.remove(websocket)
        # Clean up empty lists to avoid memory leaks
        if run_id in self.active_connections and not self.active_connections[run_id]:
            del self.active_connections[run_id]
        logger.debug("WS disconnected for run %s", run_id)

    async def broadcast(self, run_id: str, message: dict) -> None:
        """Send a JSON message to all connections watching a run.

        Connections that fail to receive are silently disconnected.
        This prevents one broken connection from blocking others.
        """
        conns = self.active_connections.get(run_id, [])
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        # Remove dead connections
        for ws in dead:
            self.disconnect(ws, run_id)

    @property
    def watched_run_ids(self) -> list[str]:
        """Return run IDs that have at least one active watcher."""
        return [rid for rid, conns in self.active_connections.items() if conns]

    def connection_count(self, run_id: str) -> int:
        """Return the number of active connections for a run."""
        return len(self.active_connections.get(run_id, []))

    @property
    def total_connections(self) -> int:
        """Total number of active WebSocket connections across all runs."""
        return sum(len(conns) for conns in self.active_connections.values())


manager = ConnectionManager()


async def _change_detector() -> None:
    """Background task: poll SQLite for run state changes, push via WebSocket.

    For each run_id with active WebSocket watchers, calls
    storage.get_run_state_hash(run_id) every 1 second.  When the
    hash differs from the previously seen value, broadcasts a
    state-changed message so the client can fetch updated partials.

    Runs until cancelled (via lifespan teardown).
    """
    last_state: dict[str, str] = {}
    while True:
        await asyncio.sleep(1)
        try:
            storage = get_storage()
            for run_id in list(manager.watched_run_ids):
                try:
                    current_hash = storage.get_run_state_hash(run_id)
                except Exception:
                    logger.debug("get_run_state_hash failed for %s", run_id, exc_info=True)
                    continue

                previous_hash = last_state.get(run_id)
                if current_hash != previous_hash:
                    last_state[run_id] = current_hash
                    # Only broadcast if there was a previous state
                    # (skip the initial population to avoid a spurious update)
                    if previous_hash is not None:
                        await manager.broadcast(run_id, {
                            "type": "state_changed",
                            "run_id": run_id,
                            "hash": current_hash,
                        })
                        logger.debug(
                            "State change detected for run %s (hash: %s -> %s)",
                            run_id, previous_hash[:8] if previous_hash else "none",
                            current_hash[:8] if current_hash else "none",
                        )

            # Prune last_state entries for runs no longer being watched
            watched = set(manager.watched_run_ids)
            stale_keys = [k for k in last_state if k not in watched]
            for k in stale_keys:
                del last_state[k]

        except asyncio.CancelledError:
            raise
        except Exception:
            # Log but do not crash the background task
            logger.exception("Error in _change_detector loop")
            await asyncio.sleep(5)  # Back off on unexpected errors


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Application lifespan: start/stop background tasks."""
    task = asyncio.create_task(_change_detector())
    logger.info("Started WebSocket change detector background task")
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    logger.info("Stopped WebSocket change detector background task")


app = FastAPI(title="a-sdlc Dashboard", version="0.1.0", lifespan=lifespan)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _get_current_project(project_id: str | None = None) -> dict[str, Any] | None:
    """Get the specified project or fall back to most recently accessed."""
    storage = get_storage()
    if project_id:
        return storage.get_project(project_id)
    return storage.get_most_recent_project()


def _get_all_projects() -> list[dict[str, Any]]:
    """Get all projects for the project switcher."""
    storage = get_storage()
    return storage.list_projects()


def _get_active_pipeline_count(project_id: str | None) -> int:
    """Count active (running/pending) execution runs for a project.

    Returns 0 if project_id is None or on any storage error.
    """
    if not project_id:
        return 0
    try:
        storage = get_storage()
        runs = storage.list_execution_runs(project_id, status="active")
        return len(runs)
    except Exception:
        return 0


@app.middleware("http")
async def inject_pipeline_count(request: Request, call_next):
    """Inject active pipeline count into request state for nav badge."""
    # Only compute for HTML page requests (skip API/WebSocket)
    if request.url.path.startswith("/ws/") or request.method not in ("GET", "HEAD"):
        return await call_next(request)
    # Extract project ID from query params or URL path
    project_id = request.query_params.get("project")
    if not project_id and "/projects/" in request.url.path:
        parts = request.url.path.split("/projects/")
        if len(parts) > 1:
            project_id = parts[1].split("/")[0]
    request.state.active_pipeline_count = _get_active_pipeline_count(project_id)
    return await call_next(request)


# =============================================================================
# Cross-Project Home
# =============================================================================


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, project: str | None = None):
    """Cross-project home page or redirect for backward compatibility."""
    # Backward compat: /?project=X redirects to /projects/X
    if project:
        return RedirectResponse(url=f"/projects/{project}", status_code=302)

    storage = get_storage()
    projects_with_stats = storage.get_all_projects_with_stats()

    if not projects_with_stats:
        return templates.TemplateResponse(
            "onboarding.html",
            {"request": request}
        )

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "projects": projects_with_stats,
        }
    )


@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_dashboard(request: Request, project_id: str):
    """Per-project dashboard (moved from /)."""
    storage = get_storage()
    all_projects = _get_all_projects()
    current_project = storage.get_project(project_id)

    if not current_project:
        return templates.TemplateResponse(
            "onboarding.html",
            {"request": request}
        )

    # Get stats
    tasks = storage.list_tasks(current_project["id"])
    sprints = storage.list_sprints(current_project["id"])
    prds = storage.list_prds(current_project["id"])

    # Task stats
    task_stats = {"pending": 0, "in_progress": 0, "completed": 0, "blocked": 0}
    for task in tasks:
        status = task["status"]
        if status in task_stats:
            task_stats[status] += 1

    # Active sprint
    active_sprint = next((s for s in sprints if s["status"] == "active"), None)

    # Active run count
    active_runs = storage.list_execution_runs(current_project["id"], status="active")
    active_count = len(active_runs)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "project": current_project,
            "projects": all_projects,
            "tasks": tasks,
            "sprints": sprints,
            "prds": prds,
            "task_stats": task_stats,
            "active_sprint": active_sprint,
            "active_run_count": active_count,
        }
    )


# =============================================================================
# Task Pages
# =============================================================================


@app.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request, project: str | None = None, status: str | None = None, sprint_id: str | None = None):
    """Tasks list page."""
    storage = get_storage()
    all_projects = _get_all_projects()
    current_project = _get_current_project(project)

    if not current_project:
        return templates.TemplateResponse(
            "onboarding.html",
            {"request": request}
        )

    # Get tasks - use sprint-specific method if filtering by sprint
    if sprint_id:
        tasks = storage.list_tasks_by_sprint(current_project["id"], sprint_id, status=status)
    else:
        tasks = storage.list_tasks(current_project["id"], status=status)
    sprints = storage.list_sprints(current_project["id"])

    # Active run count
    active_runs = storage.list_execution_runs(current_project["id"], status="active")
    active_count = len(active_runs)

    return templates.TemplateResponse(
        "tasks.html",
        {
            "request": request,
            "project": current_project,
            "projects": all_projects,
            "tasks": tasks,
            "sprints": sprints,
            "filter_status": status,
            "filter_sprint": sprint_id,
            "active_run_count": active_count,
        }
    )


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str):
    """Task detail page."""
    storage = get_storage()
    task = storage.get_task(task_id)

    if not task:
        return HTMLResponse(content="<h1>Task not found</h1>", status_code=404)

    # Get thread entry count for badge
    thread_entries = storage.list_artifact_threads_by_artifact("task", task_id)
    thread_count = len(thread_entries)

    return templates.TemplateResponse(
        "task_detail.html",
        {"request": request, "task": task, "thread_count": thread_count}
    )


@app.post("/tasks/{task_id}/status")
async def update_task_status(task_id: str, status: str):
    """Update task status (HTMX endpoint)."""
    storage = get_storage()
    task = storage.update_task(task_id, status=status)

    if not task:
        return HTMLResponse(content="Task not found", status_code=404)

    return HTMLResponse(
        content=f'<span class="status-{status}">{status.replace("_", " ").title()}</span>'
    )


@app.put("/tasks/{task_id}/content")
async def update_task_content(task_id: str, request: Request):
    """Update task content (full markdown)."""
    storage = get_storage()
    data = await request.json()
    content = data.get("content", "")

    task = storage.update_task(task_id, content=content)
    if not task:
        return HTMLResponse(content="Task not found", status_code=404)

    return {"success": True}


# =============================================================================
# Sprint Pages
# =============================================================================


@app.get("/sprints", response_class=HTMLResponse)
async def sprints_page(request: Request, project: str | None = None, status: str | None = None):
    """Sprints list page."""
    storage = get_storage()
    all_projects = _get_all_projects()
    current_project = _get_current_project(project)

    if not current_project:
        return templates.TemplateResponse(
            "onboarding.html",
            {"request": request}
        )

    sprints = storage.list_sprints(current_project["id"])

    # Filter by status (Python-side since list_sprints doesn't support it)
    if status:
        sprints = [s for s in sprints if s["status"] == status]

    # Add task counts to each sprint
    for sprint in sprints:
        tasks = storage.list_tasks_by_sprint(current_project["id"], sprint["id"])
        sprint["task_count"] = len(tasks)
        sprint["completed_count"] = sum(1 for t in tasks if t["status"] == "completed")

    # Active run count
    active_runs = storage.list_execution_runs(current_project["id"], status="active")
    active_count = len(active_runs)

    return templates.TemplateResponse(
        "sprints.html",
        {
            "request": request,
            "project": current_project,
            "projects": all_projects,
            "sprints": sprints,
            "filter_status": status,
            "active_run_count": active_count,
        }
    )


@app.get("/sprints/{sprint_id}", response_class=HTMLResponse)
async def sprint_detail(request: Request, sprint_id: str):
    """Sprint detail page."""
    storage = get_storage()
    sprint = storage.get_sprint(sprint_id)

    if not sprint:
        return HTMLResponse(content="<h1>Sprint not found</h1>", status_code=404)

    # Get PRDs in this sprint
    prds = storage.get_sprint_prds(sprint_id)

    # Add task counts to PRDs
    for prd in prds:
        prd_tasks = storage.list_tasks(sprint["project_id"], prd_id=prd["id"])
        prd["task_count"] = len(prd_tasks)

    # Get backlog PRDs (unassigned to any sprint)
    available_prds = storage.list_prds(sprint["project_id"], sprint_id="")

    # Get tasks derived from sprint's PRDs
    tasks = storage.list_tasks_by_sprint(sprint["project_id"], sprint_id)

    # Calculate task stats for progress bar
    task_stats = {"pending": 0, "in_progress": 0, "completed": 0, "blocked": 0}
    for task in tasks:
        s = task["status"]
        if s in task_stats:
            task_stats[s] += 1

    # Get thread entry count for badge
    thread_entries = storage.list_artifact_threads_by_artifact("sprint", sprint_id)
    thread_count = len(thread_entries)

    return templates.TemplateResponse(
        "sprint_detail.html",
        {
            "request": request,
            "sprint": sprint,
            "prds": prds,
            "tasks": tasks,
            "task_stats": task_stats,
            "available_prds": available_prds,
            "thread_count": thread_count,
        }
    )


@app.post("/sprints/{sprint_id}/prds")
async def add_prd_to_sprint(sprint_id: str, request: Request):
    """Add a PRD to this sprint."""
    storage = get_storage()
    form = await request.form()
    prd_id = form.get("prd_id")
    if prd_id:
        storage.assign_prd_to_sprint(prd_id, sprint_id)
    return RedirectResponse(url=f"/sprints/{sprint_id}", status_code=303)


@app.post("/sprints/{sprint_id}/prds/{prd_id}/remove")
async def remove_prd_from_sprint(sprint_id: str, prd_id: str):
    """Remove a PRD from this sprint (unassign to backlog)."""
    storage = get_storage()
    storage.assign_prd_to_sprint(prd_id, None)
    return RedirectResponse(url=f"/sprints/{sprint_id}", status_code=303)


@app.put("/sprints/{sprint_id}/status")
async def update_sprint_status(sprint_id: str, request: Request):
    """Update sprint status."""
    storage = get_storage()
    data = await request.json()
    status = data.get("status", "planned")

    sprint = storage.update_sprint(sprint_id, status=status)
    if not sprint:
        return HTMLResponse(content="Sprint not found", status_code=404)

    return {"success": True}


# =============================================================================
# PRD Pages
# =============================================================================


@app.get("/prds", response_class=HTMLResponse)
async def prds_page(request: Request, project: str | None = None, status: str | None = None, sprint_id: str | None = None):
    """PRDs list page."""
    storage = get_storage()
    all_projects = _get_all_projects()
    current_project = _get_current_project(project)

    if not current_project:
        return templates.TemplateResponse(
            "onboarding.html",
            {"request": request}
        )

    prds = storage.list_prds(current_project["id"], status=status, sprint_id=sprint_id)

    # Check design existence for each PRD
    designs = storage.list_designs(current_project["id"])
    design_prd_ids = {d["prd_id"] for d in designs}
    for prd in prds:
        prd["has_design"] = prd["id"] in design_prd_ids

    sprints = storage.list_sprints(current_project["id"])

    # Active run count
    active_runs = storage.list_execution_runs(current_project["id"], status="active")
    active_count = len(active_runs)

    return templates.TemplateResponse(
        "prds.html",
        {
            "request": request,
            "project": current_project,
            "projects": all_projects,
            "prds": prds,
            "sprints": sprints,
            "filter_status": status,
            "filter_sprint": sprint_id,
            "active_run_count": active_count,
        }
    )


def _generate_dependency_graph(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate Mermaid.js graph from tasks."""
    if not tasks:
        return {'mermaid_code': '', 'has_dependencies': False, 'task_count': 0}

    # Sanitize task IDs for Mermaid (replace hyphens/special chars with underscores)
    def sanitize_id(task_id: str) -> str:
        return task_id.replace('-', '_').replace('.', '_').replace(' ', '_')

    task_map = {t['id']: t for t in tasks}
    id_map = {t['id']: sanitize_id(t['id']) for t in tasks}
    edges = []

    for task in tasks:
        deps = (task.get('data') or {}).get('dependencies', [])
        for dep_id in deps:
            if dep_id in task_map:
                edges.append((dep_id, task['id']))

    lines = ['graph LR']

    # Add nodes with status icons
    status_icons = {'pending': '⏳', 'in_progress': '🔄', 'completed': '✅', 'blocked': '🚫'}
    for task in tasks:
        safe_id = id_map[task['id']]
        title = task['title'][:25].replace('"', "'").replace('[', '(').replace(']', ')')
        if len(task['title']) > 25:
            title += '...'
        icon = status_icons.get(task['status'], '❓')
        lines.append(f'    {safe_id}["{icon} {title}"]')

    # Add edges
    for from_id, to_id in edges:
        lines.append(f'    {id_map[from_id]} --> {id_map[to_id]}')

    # Add click handlers and status classes (use original IDs in URLs)
    for task in tasks:
        safe_id = id_map[task['id']]
        lines.append(f'    click {safe_id} "/tasks/{task["id"]}"')
        lines.append(f'    class {safe_id} status-{task["status"]}')

    # Status color definitions
    lines.extend([
        '    classDef status-pending fill:#d29922,stroke:#d29922,color:#0d1117',
        '    classDef status-in_progress fill:#58a6ff,stroke:#58a6ff,color:#0d1117',
        '    classDef status-completed fill:#3fb950,stroke:#3fb950,color:#0d1117',
        '    classDef status-blocked fill:#f85149,stroke:#f85149,color:#0d1117',
    ])

    return {
        'mermaid_code': '\n'.join(lines),
        'has_dependencies': len(edges) > 0,
        'task_count': len(tasks)
    }


@app.get("/prds/{prd_id}", response_class=HTMLResponse)
async def prd_detail(request: Request, prd_id: str):
    """PRD detail page."""
    storage = get_storage()
    prd = storage.get_prd(prd_id)

    if not prd:
        return HTMLResponse(content="<h1>PRD not found</h1>", status_code=404)

    # Get sprints for the project to populate sprint selector
    sprints = storage.list_sprints(prd["project_id"])

    # Get tasks associated with this PRD
    tasks = storage.list_tasks(prd["project_id"], prd_id=prd_id)

    # Generate dependency graph
    graph_data = _generate_dependency_graph(tasks)

    # Get design document if exists
    design = storage.get_design_by_prd(prd_id)

    # Get thread entry count for badge
    thread_entries = storage.list_artifact_threads_by_artifact("prd", prd_id)
    thread_count = len(thread_entries)

    return templates.TemplateResponse(
        "prd_detail.html",
        {
            "request": request,
            "prd": prd,
            "sprints": sprints,
            "tasks": tasks,
            "graph_data": graph_data,
            "design": design,
            "thread_count": thread_count,
        }
    )


@app.put("/prds/{prd_id}/content")
async def update_prd_content(prd_id: str, request: Request):
    """Update PRD content by writing directly to file."""
    storage = get_storage()
    data = await request.json()
    content = data.get("content", "")

    prd = storage.get_prd(prd_id)
    if not prd:
        return HTMLResponse(content="PRD not found", status_code=404)

    # Write content directly to file
    from pathlib import Path
    if prd.get("file_path"):
        storage._content_mgr.write_content(Path(prd["file_path"]), content)
    else:
        storage._content_mgr.write_prd(prd["project_id"], prd_id, prd["title"], content)

    return {"success": True}


@app.put("/prds/{prd_id}/design")
async def update_design_content(prd_id: str, request: Request):
    """Update design document content by writing directly to file."""
    storage = get_storage()
    data = await request.json()
    content = data.get("content", "")

    # Check if design exists; create if not
    existing = storage.get_design_by_prd(prd_id)
    if existing:
        # Write content directly to file
        from pathlib import Path
        if existing.get("file_path"):
            storage._content_mgr.write_content(Path(existing["file_path"]), content)
        else:
            storage._content_mgr.write_design(existing["project_id"], prd_id, content)
    else:
        prd = storage.get_prd(prd_id)
        if not prd:
            return HTMLResponse(content="PRD not found", status_code=404)
        # Create design (empty file) then write content
        design = storage.create_design(prd_id=prd_id, project_id=prd["project_id"])
        if not design:
            return HTMLResponse(content="Failed to save design", status_code=500)
        from pathlib import Path
        storage._content_mgr.write_content(Path(design["file_path"]), content)

    return {"success": True}


@app.put("/prds/{prd_id}/sprint")
async def update_prd_sprint(prd_id: str, request: Request):
    """Update PRD sprint assignment."""
    storage = get_storage()
    data = await request.json()
    sprint_id = data.get("sprint_id")

    # Convert empty string to None (backlog)
    if sprint_id == "":
        sprint_id = None

    prd = storage.update_prd(prd_id, sprint_id=sprint_id)
    if not prd:
        return HTMLResponse(content="PRD not found", status_code=404)

    return {"success": True}


@app.put("/prds/{prd_id}/status")
async def update_prd_status(prd_id: str, request: Request):
    """Update PRD status."""
    storage = get_storage()
    data = await request.json()
    status = data.get("status", "draft")

    prd = storage.update_prd(prd_id, status=status)
    if not prd:
        return HTMLResponse(content="PRD not found", status_code=404)

    return {"success": True}


# =============================================================================
# Analytics
# =============================================================================


def _parse_timestamp(ts_str: str | None) -> datetime | None:
    """Safely parse an ISO timestamp string to datetime."""
    if not ts_str:
        return None
    try:
        # Handle both with and without timezone
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def _format_duration(hours: float) -> str:
    """Format duration with smart units: <1h -> Xm, <48h -> X.Xh, else -> X.Xd."""
    if hours < 1:
        return f"{max(1, round(hours * 60))}m"
    elif hours < 48:
        return f"{hours:.1f}h"
    else:
        return f"{hours / 24:.1f}d"


def _compute_analytics(project_id: str, days: int = 30) -> dict[str, Any]:
    """Compute analytics metrics for a project over a time window."""
    storage = get_storage()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)
    window_start.isoformat()

    # Get all tasks for the project
    all_tasks = storage.list_tasks(project_id)

    # Status distribution
    status_dist: dict[str, int] = {"pending": 0, "in_progress": 0, "completed": 0, "blocked": 0}
    for t in all_tasks:
        s = t.get("status", "pending")
        if s in status_dist:
            status_dist[s] += 1

    # Priority distribution
    priority_dist: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for t in all_tasks:
        p = t.get("priority", "medium")
        if p in priority_dist:
            priority_dist[p] += 1

    # Completed tasks in window
    completed_in_window = []
    for t in all_tasks:
        if t.get("status") == "completed":
            completed_at = _parse_timestamp(t.get("completed_at"))
            if completed_at and completed_at >= window_start:
                completed_in_window.append(t)

    # Completion trend: daily counts
    completion_trend = []
    day_counts: dict[str, int] = defaultdict(int)
    for t in completed_in_window:
        completed_at = _parse_timestamp(t.get("completed_at"))
        if completed_at:
            day_key = completed_at.strftime("%Y-%m-%d")
            day_counts[day_key] += 1

    # Fill in all days in the window
    for i in range(days):
        d = (window_start + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        completion_trend.append({"date": d, "count": day_counts.get(d, 0)})

    # Lead time and cycle time
    lead_times = []
    cycle_times = []
    for t in completed_in_window:
        completed_at = _parse_timestamp(t.get("completed_at"))
        created_at = _parse_timestamp(t.get("created_at"))
        started_at = _parse_timestamp(t.get("started_at"))

        if completed_at and created_at:
            lead_days = (completed_at - created_at).total_seconds() / 86400
            lead_times.append(lead_days)

        if completed_at and started_at:
            cycle_days = (completed_at - started_at).total_seconds() / 86400
            cycle_times.append(cycle_days)

    total_completed = len(completed_in_window)
    avg_lead_hours = sum(lead_times) / len(lead_times) * 24 if lead_times else 0
    avg_cycle_hours = sum(cycle_times) / len(cycle_times) * 24 if cycle_times else 0
    completion_rate = round(total_completed / len(all_tasks) * 100) if all_tasks else 0

    # Sprint velocity: last 10 completed sprints
    sprints = storage.list_sprints(project_id)
    completed_sprints = [s for s in sprints if s.get("status") == "completed"]
    # Sort by completed_at descending, take last 10
    completed_sprints.sort(
        key=lambda s: s.get("completed_at") or "", reverse=True
    )
    completed_sprints = completed_sprints[:10]
    completed_sprints.reverse()  # oldest first for chart

    sprint_velocity = []
    for s in completed_sprints:
        sprint_tasks = storage.list_tasks_by_sprint(project_id, s["id"])
        total = len(sprint_tasks)
        done = sum(1 for t in sprint_tasks if t.get("status") == "completed")
        sprint_velocity.append({
            "sprint_id": s["id"],
            "sprint_title": s.get("title", s["id"]),
            "completed": done,
            "total": total,
        })

    # Sprint durations: wall-clock time for completed sprints
    sprint_durations = []
    for s in completed_sprints:
        started = _parse_timestamp(s.get("started_at"))
        completed = _parse_timestamp(s.get("completed_at"))
        if started and completed:
            hours = (completed - started).total_seconds() / 3600
            sprint_durations.append({
                "sprint_id": s["id"],
                "title": s.get("title", s["id"]),
                "duration_hours": round(hours, 1),
                "duration_label": _format_duration(hours),
            })

    sprint_avg_hours = (
        sum(d["duration_hours"] for d in sprint_durations) / len(sprint_durations)
        if sprint_durations else 0
    )

    # PRD durations: use real PRD phase timestamps
    all_prds = storage.list_prds(project_id)
    prd_durations = []
    for prd in all_prds:
        if prd.get("status") != "completed":
            continue
        prd_created = _parse_timestamp(prd.get("created_at"))
        prd_completed = _parse_timestamp(prd.get("completed_at"))
        if not prd_created or not prd_completed:
            continue

        total_hours = (prd_completed - prd_created).total_seconds() / 3600

        # Per-phase durations (available when timestamps exist)
        ready_at = _parse_timestamp(prd.get("ready_at"))
        split_at = _parse_timestamp(prd.get("split_at"))

        drafting_hours = (ready_at - prd_created).total_seconds() / 3600 if ready_at else None
        planning_hours = (split_at - ready_at).total_seconds() / 3600 if split_at and ready_at else None
        execution_hours = (prd_completed - split_at).total_seconds() / 3600 if split_at else None

        prd_durations.append({
            "prd_id": prd["id"],
            "title": prd.get("title", prd["id"]),
            "duration_hours": round(total_hours, 1),
            "duration_label": _format_duration(total_hours),
            "drafting_hours": round(drafting_hours, 1) if drafting_hours is not None else None,
            "planning_hours": round(planning_hours, 1) if planning_hours is not None else None,
            "execution_hours": round(execution_hours, 1) if execution_hours is not None else None,
        })

    # Sort by duration descending, take last 10
    prd_durations.sort(key=lambda d: d["duration_hours"])
    prd_durations = prd_durations[:10]

    prd_avg_hours = (
        sum(d["duration_hours"] for d in prd_durations) / len(prd_durations)
        if prd_durations else 0
    )

    return {
        "summary": {
            "total_completed": total_completed,
            "avg_lead_time": _format_duration(avg_lead_hours) if avg_lead_hours else "0m",
            "avg_cycle_time": _format_duration(avg_cycle_hours) if avg_cycle_hours else "0m",
            "completion_rate": completion_rate,
        },
        "task_durations": {
            "avg_lead_time_hours": round(avg_lead_hours, 1),
            "avg_cycle_time_hours": round(avg_cycle_hours, 1),
        },
        "prd_durations": prd_durations,
        "prd_avg_duration": _format_duration(prd_avg_hours) if prd_avg_hours else "N/A",
        "sprint_durations": sprint_durations,
        "sprint_avg_duration": _format_duration(sprint_avg_hours) if sprint_avg_hours else "N/A",
        "completion_trend": completion_trend,
        "sprint_velocity": sprint_velocity,
        "status_distribution": status_dist,
        "priority_distribution": priority_dist,
        "time_window": days,
    }


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, project: str | None = None, days: int = 30):
    """Developer analytics page with Chart.js visualizations."""
    get_storage()
    all_projects = _get_all_projects()
    current_project = _get_current_project(project)

    if not current_project:
        return templates.TemplateResponse(
            "onboarding.html",
            {"request": request}
        )

    # Validate days parameter
    if days not in (7, 14, 30, 90):
        days = 30

    metrics = _compute_analytics(current_project["id"], days)

    return templates.TemplateResponse(
        "analytics.html",
        {
            "request": request,
            "project": current_project,
            "projects": all_projects,
            "metrics": metrics,
            "days": days,
        }
    )


# =============================================================================
# Pipeline Runs
# =============================================================================


def _list_pipeline_runs(status_filter: str | None = None) -> list[dict[str, Any]]:
    """Helper for backward compatibility with tests (uses DB instead of files)."""
    storage = get_storage()
    project = storage.get_most_recent_project()
    if not project:
        return []
    runs = storage.list_execution_runs(project["id"], status=status_filter)
    for run in runs:
        # Compatibility fields expected by tests
        run["pid_alive"] = (
            _is_process_running(run.get("pid")) if run.get("pid") else False
        )
        run["display_status"] = run.get("status", "unknown")
    return runs


def _count_active_runs() -> int:
    """Helper for backward compatibility with tests."""
    storage = get_storage()
    project = storage.get_most_recent_project()
    if not project:
        return 0
    active = storage.list_execution_runs(project["id"], status="active")
    return len(active)


@app.get("/runs", response_class=HTMLResponse)
async def pipeline_runs_page(request: Request, project: str | None = None, status: str | None = None):
    """Pipeline runs list page (FR-001, FR-002, FR-003)."""
    storage = get_storage()
    all_projects = _get_all_projects()
    current_project = _get_current_project(project)

    if not current_project:
        return templates.TemplateResponse(
            "onboarding.html",
            {"request": request}
        )

    runs = storage.list_execution_runs(current_project["id"], status=status)
    active_runs = storage.list_execution_runs(current_project["id"], status="active")
    active_count = len(active_runs)

    # Get sprints for start run modal
    sprints = storage.list_sprints(current_project["id"])

    return templates.TemplateResponse(
        "pipeline_runs.html",
        {
            "request": request,
            "project": current_project,
            "projects": all_projects,
            "runs": runs,
            "active_run_count": active_count,
            "filter_status": status,
            "sprints": sprints,
        }
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail_page(request: Request, run_id: str):
    """Run detail page with kanban board, phase progress, and agent panel."""
    storage = get_storage()
    run = storage.get_execution_run_detail(run_id)

    if not run:
        return HTMLResponse(content="<h1>Run not found</h1>", status_code=404)

    # Determine project context
    current_project = storage.get_project(run["project_id"])
    all_projects = _get_all_projects()

    # Get work queue items and group into kanban columns
    work_items = storage.list_work_queue_items(run_id)
    queue: dict[str, list[dict[str, Any]]] = {
        "pending": [],
        "in_progress": [],
        "completed": [],
        "failed": [],
        "escalated": [],
    }
    for item in work_items:
        status = item.get("status", "pending")
        if status in queue:
            # Calculate elapsed time for active items
            if status == "in_progress" and item.get("started_at"):
                try:
                    start_dt = datetime.fromisoformat(item["started_at"].replace("Z", "+00:00"))
                    delta = datetime.now(timezone.utc) - start_dt
                    item["elapsed_min"] = int(delta.total_seconds() / 60)
                except (ValueError, TypeError):
                    item["elapsed_min"] = 0
            queue[status].append(item)

    # Get thread entries for the activity stream
    thread_entries = storage.get_recent_thread_entries(run_id, limit=30)

    # Active run count for nav
    active_runs = storage.list_execution_runs(current_project["id"], status="active")
    active_count = len(active_runs)

    # Convergence rate: % of challenge artifacts resolved
    challenge_items = [i for i in work_items if i.get("work_type") == "challenge"]
    convergence_rate = 0
    if challenge_items:
        resolved = sum(1 for i in challenge_items if i.get("status") == "completed")
        convergence_rate = int((resolved / len(challenge_items)) * 100)

    # Phase percentage
    phase_order = ["planning", "design", "implementation", "testing", "review"]
    phase_pct = 20
    if run.get("current_phase") in phase_order:
        phase_pct = (phase_order.index(run["current_phase"]) + 1) * 20

    return templates.TemplateResponse(
        "run_detail.html",
        {
            "request": request,
            "project": current_project,
            "projects": all_projects,
            "run": run,
            "queue": queue,
            "entries": thread_entries,
            "artifact_type": "run",  # For thread viewer
            "artifact_id": run_id,
            "active_run_count": active_count,
            "convergence_rate": convergence_rate,
            "phase_pct": phase_pct,
            "allow_comment": True,
        }
    )


@app.post("/runs/launch")
async def start_run(request: Request):
    """Launch a new pipeline run from the UI (FR-023, FR-024, FR-025)."""
    import subprocess
    import sys

    storage = get_storage()
    form = await request.form()
    sprint_id = form.get("sprint_id")
    goal = form.get("goal", "").strip()

    # We need project context - find most recent
    project = storage.get_most_recent_project()
    if not project:
        return HTMLResponse(content="No project found to run in", status_code=400)

    run_id = storage.get_next_run_id(project["id"])

    # Create DB record
    storage.create_execution_run(
        run_id=run_id,
        project_id=project["id"],
        sprint_id=sprint_id if sprint_id else None,
        status="active",
        run_type="sprint" if sprint_id else "objective",
        goal=goal,
        current_phase="planning"
    )

    # Spawn background executor process
    cmd = [
        sys.executable,
        "-m",
        "a_sdlc.executor",
        "--run-id",
        run_id,
    ]
    if sprint_id:
        cmd.extend(["--mode", "sprint", "--sprint-id", sprint_id])
    else:
        cmd.extend(["--mode", "objective", "--description", goal])

    # Detached process
    subprocess.Popen(
        cmd,
        cwd=project["path"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


# =============================================================================
# WebSocket Endpoints
# =============================================================================


@app.websocket("/ws/runs/{run_id}")
async def run_websocket(websocket: WebSocket, run_id: str):
    """WebSocket endpoint for real-time pipeline run updates.

    Clients connect to /ws/runs/{run_id} to receive state change
    notifications for a specific execution run.  The server pushes
    JSON messages of the form {"type": "state_changed", "run_id": ..., "hash": ...}
    whenever the run's state hash changes in the database.

    The client is expected to react by fetching updated HTML partials
    via standard HTMX GET requests.
    """
    await manager.connect(websocket, run_id)
    try:
        while True:
            # Keep the connection alive by reading incoming messages.
            # Clients may send ping/pong or HTMX ws-send messages.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, run_id)
    except Exception:
        manager.disconnect(websocket, run_id)
        logger.debug("WebSocket error for run %s", run_id, exc_info=True)


@app.post("/runs/{run_id}/action")
async def run_action(run_id: str, request: Request, action: str | None = None):
    """Global control actions for a run."""
    storage = get_storage()
    if not action:
        form = await request.form()
        action = form.get("action")

    if action == "pause":
        storage.update_execution_run(run_id, status="paused")
    elif action == "resume":
        storage.update_execution_run(run_id, status="active")
    elif action == "cancel":
        storage.update_execution_run(run_id, status="cancelled")
    elif action == "answer":
        form = await request.form()
        answer = form.get("answer", "").strip()
        if answer:
            storage.update_execution_run(
                run_id,
                clarification_answer=answer,
                status="running"  # Resume the run
            )
            # Log as a user intervention in the thread
            run_data = storage.get_execution_run(run_id)
            if run_data:
                storage.create_artifact_thread_entry(
                    run_id=run_id,
                    project_id=run_data["project_id"],
                    artifact_type="run",
                    artifact_id=run_id,
                    entry_type="user_intervention",
                    content=f"Clarification answer: {answer}",
                    agent_persona="User"
                )

    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@app.post("/runs/items/{item_id}/action")
async def work_item_action(item_id: str, request: Request, action: str | None = None):
    """Control actions for individual work queue items."""
    storage = get_storage()

    # Support action from query param (HTMX) or form data (legacy tests)
    if not action:
        form = await request.form()
        action = form.get("action")

    item = storage.get_work_queue_item(item_id)
    if not item:
        return HTMLResponse(content="Work item not found", status_code=404)

    if action == "start":
        storage.update_work_queue_item(item_id, status="in_progress", started_at=datetime.now(timezone.utc).isoformat())
    elif action == "pause":
        storage.update_work_queue_item(item_id, status="pending")
    elif action == "retry":
        storage.update_work_queue_item(item_id, status="pending", retry_count=(item.get("retry_count") or 0) + 1)
    elif action == "skip":
        storage.update_work_queue_item(item_id, status="skipped")
    elif action == "cancel":
        storage.update_work_queue_item(item_id, status="cancelled")
    elif action in ["approve", "force_approve"]:
        storage.update_work_queue_item(item_id, status="completed", result="manually_approved")
    else:
        return HTMLResponse(content=f"Unknown action: {action}", status_code=400)

    # Re-render card partial
    updated = storage.get_work_queue_item(item_id)
    return templates.TemplateResponse(
        "work_item_card.html",
        {"request": request, "item": updated}
    )


@app.post("/threads/{artifact_type}/{artifact_id}/comment")
async def post_thread_comment(
    request: Request, artifact_type: str, artifact_id: str
):
    """Unified endpoint for posting thread comments (both artifact and run context)."""
    storage = get_storage()

    # Try reading as JSON first, then fall back to Form
    try:
        data = await request.json()
        content = (data.get("content") or "").strip()
    except Exception:
        form = await request.form()
        content = (form.get("content") or "").strip()

    if not content:
        return HTMLResponse(content="Comment cannot be empty", status_code=400)

    # Resolve project and find/create run context
    project_id = _resolve_project_id(storage, artifact_type, artifact_id)
    if not project_id:
        return HTMLResponse(content="Artifact context not found", status_code=404)

    # Use run_id from query if available (e.g. from run detail page)
    run_id = request.query_params.get("run_id")
    if not run_id:
        # Fallback to most recent thread's run_id
        existing = storage.list_artifact_threads_by_artifact(artifact_type, artifact_id)
        if existing:
            run_id = existing[-1]["run_id"]
        else:
            run_id = f"user-{artifact_id}"
            if not storage.get_execution_run(run_id):
                storage.create_execution_run(run_id=run_id, project_id=project_id, status="completed")

    storage.create_artifact_thread_entry(
        run_id=run_id,
        project_id=project_id,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        entry_type="user_intervention",
        content=content,
        agent_persona="User",
    )

    # Re-render viewer partial
    entries = storage.list_artifact_threads_by_artifact(artifact_type, artifact_id)
    return templates.TemplateResponse(
        "partials/thread_viewer.html",
        {
            "request": request,
            "entries": entries,
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
        }
    )


# =============================================================================
# Settings & Integrations
# =============================================================================


def _get_integrations_dict(project_id: str) -> dict[str, Any]:
    """Get integrations as a dict keyed by system name."""
    storage = get_storage()
    configs = storage.list_external_configs(project_id)
    return {c["system"]: c for c in configs}


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, project: str | None = None, message: str | None = None, message_type: str | None = None):
    """Settings page with integrations management."""
    get_storage()
    all_projects = _get_all_projects()
    current_project = _get_current_project(project)

    if not current_project:
        return templates.TemplateResponse(
            "onboarding.html",
            {"request": request}
        )

    integrations = _get_integrations_dict(current_project["id"])

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "project": current_project,
            "projects": all_projects,
            "integrations": integrations,
            "message": message,
            "message_type": message_type,
        }
    )


@app.get("/settings/integrations/{system}/edit", response_class=HTMLResponse)
async def integration_edit_form(request: Request, system: str, project: str | None = None):
    """Get the edit form for an integration (HTMX partial)."""
    storage = get_storage()
    current_project = _get_current_project(project)

    if not current_project:
        return HTMLResponse(content="Project not found", status_code=404)

    # Get existing config if any
    existing = storage.get_external_config(current_project["id"], system)
    config = existing["config"] if existing else None

    return templates.TemplateResponse(
        "partials/integration_form.html",
        {
            "request": request,
            "system": system,
            "project_id": current_project["id"],
            "config": config,
        }
    )


@app.get("/settings/integrations/{system}/cancel", response_class=HTMLResponse)
async def integration_cancel(system: str):
    """Cancel integration form (returns empty content)."""
    return HTMLResponse(content="")


@app.post("/settings/integrations/linear", response_class=HTMLResponse)
async def save_linear_integration(
    request: Request,
    project: str,
    api_key: str = Form(...),
    team_id: str = Form(...),
    default_project: str = Form(""),
):
    """Save Linear integration configuration."""
    storage = get_storage()
    current_project = _get_current_project(project)

    if not current_project:
        return HTMLResponse(content="Project not found", status_code=404)

    config = {
        "api_key": api_key,
        "team_id": team_id,
    }
    if default_project:
        config["default_project"] = default_project

    storage.set_external_config(current_project["id"], "linear", config)

    # Return updated integration card
    integrations = _get_integrations_dict(current_project["id"])
    return templates.TemplateResponse(
        "partials/integration_card.html",
        {
            "request": request,
            "system": "linear",
            "project": current_project,
            "integration": integrations.get("linear"),
        }
    )


@app.post("/settings/integrations/jira", response_class=HTMLResponse)
async def save_jira_integration(
    request: Request,
    project: str,
    base_url: str = Form(...),
    email: str = Form(...),
    api_token: str = Form(...),
    project_key: str = Form(...),
    issue_type: str = Form("Task"),
):
    """Save Jira integration configuration."""
    storage = get_storage()
    current_project = _get_current_project(project)

    if not current_project:
        return HTMLResponse(content="Project not found", status_code=404)

    config = {
        "base_url": base_url.rstrip("/"),
        "email": email,
        "api_token": api_token,
        "project_key": project_key,
        "issue_type": issue_type or "Task",
    }

    storage.set_external_config(current_project["id"], "jira", config)

    # Return updated integration card
    integrations = _get_integrations_dict(current_project["id"])
    return templates.TemplateResponse(
        "partials/integration_card.html",
        {
            "request": request,
            "system": "jira",
            "project": current_project,
            "integration": integrations.get("jira"),
        }
    )


@app.post("/settings/integrations/confluence", response_class=HTMLResponse)
async def save_confluence_integration(
    request: Request,
    project: str,
    base_url: str = Form(...),
    email: str = Form(...),
    api_token: str = Form(...),
    space_key: str = Form(...),
    parent_page_id: str = Form(""),
    page_title_prefix: str = Form(""),
):
    """Save Confluence integration configuration."""
    storage = get_storage()
    current_project = _get_current_project(project)

    if not current_project:
        return HTMLResponse(content="Project not found", status_code=404)

    config = {
        "base_url": base_url.rstrip("/"),
        "email": email,
        "api_token": api_token,
        "space_key": space_key,
    }
    if parent_page_id:
        config["parent_page_id"] = parent_page_id
    if page_title_prefix:
        config["page_title_prefix"] = page_title_prefix

    storage.set_external_config(current_project["id"], "confluence", config)

    # Return updated integration card
    integrations = _get_integrations_dict(current_project["id"])
    return templates.TemplateResponse(
        "partials/integration_card.html",
        {
            "request": request,
            "system": "confluence",
            "project": current_project,
            "integration": integrations.get("confluence"),
        }
    )


@app.post("/settings/integrations/github", response_class=HTMLResponse)
async def save_github_integration(
    request: Request,
    project: str,
    token: str = Form(...),
):
    """Save GitHub integration configuration with token validation."""
    storage = get_storage()
    current_project = _get_current_project(project)

    if not current_project:
        return HTMLResponse(content="Project not found", status_code=404)

    # Validate token before saving
    from a_sdlc.server.github import GitHubClient
    try:
        client = GitHubClient(token)
        client.validate_token()
    except RuntimeError:
        return HTMLResponse(content="Invalid GitHub token. Ensure the token has 'repo' scope.", status_code=400)

    storage.set_external_config(current_project["id"], "github", {"token": token})

    integrations = _get_integrations_dict(current_project["id"])
    return templates.TemplateResponse(
        "partials/integration_card.html",
        {
            "request": request,
            "system": "github",
            "project": current_project,
            "integration": integrations.get("github"),
        }
    )


@app.delete("/settings/integrations/{system}", response_class=HTMLResponse)
async def delete_integration(request: Request, system: str, project: str):
    """Remove an integration configuration."""
    storage = get_storage()
    current_project = _get_current_project(project)

    if not current_project:
        return HTMLResponse(content="Project not found", status_code=404)

    storage.delete_external_config(current_project["id"], system)

    # Return empty integration card (not configured state)
    return templates.TemplateResponse(
        "partials/integration_card.html",
        {
            "request": request,
            "system": system,
            "project": current_project,
            "integration": None,
        }
    )


# =============================================================================
# Thread Viewer (FR-008, FR-009, FR-010, FR-011, FR-012, FR-013, FR-019)
# =============================================================================


@app.get("/threads/{artifact_type}/{artifact_id}", response_class=HTMLResponse)
async def thread_viewer(request: Request, artifact_type: str, artifact_id: str):
    """Thread viewer partial for an artifact (HTMX endpoint).

    Returns the thread_viewer.html partial showing all thread entries
    for the given artifact across all pipeline runs.
    """
    storage = get_storage()
    entries = storage.list_artifact_threads_by_artifact(artifact_type, artifact_id)
    return templates.TemplateResponse(
        "partials/thread_viewer.html",
        {
            "request": request,
            "entries": entries,
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
        }
    )


def _resolve_project_id(
    storage: Any, artifact_type: str, artifact_id: str
) -> str | None:
    """Resolve the project_id for a given artifact type and ID."""
    if artifact_type == "prd":
        prd = storage.get_prd(artifact_id)
        return prd["project_id"] if prd else None
    elif artifact_type == "task":
        task = storage.get_task(artifact_id)
        return task["project_id"] if task else None
    elif artifact_type == "sprint":
        sprint = storage.get_sprint(artifact_id)
        return sprint["project_id"] if sprint else None
    return None


def run_server(host: str = "127.0.0.1", port: int = 3847) -> None:
    """Run the web UI server."""
    # Clean up any stale server
    if _cleanup_stale_pid():
        print("Cleaned up stale UI server process")

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # Write PID file
    _write_pid()

    # Register cleanup on exit
    atexit.register(_remove_pid)

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        _remove_pid()


if __name__ == "__main__":
    run_server()
