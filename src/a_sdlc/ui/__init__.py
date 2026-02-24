"""
a-sdlc Web UI.

Provides a FastAPI + HTMX dashboard for viewing and managing
PRDs, tasks, and sprints.

Usage:
    a-sdlc ui              # Start web server on http://localhost:3847
    a-sdlc ui --port 8000  # Custom port
    a-sdlc ui stop         # Stop running UI server
"""

import atexit
import os
import signal
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, Form, Request
    from fastapi.responses import HTMLResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    import uvicorn
except ImportError:
    raise ImportError(
        "Web UI dependencies not installed. "
        "Install with: pip install 'a-sdlc[ui]'"
    )

from a_sdlc.storage import get_storage

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

app = FastAPI(title="a-sdlc Dashboard", version="0.1.0")
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
        }
    )


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str):
    """Task detail page."""
    storage = get_storage()
    task = storage.get_task(task_id)

    if not task:
        return HTMLResponse(content="<h1>Task not found</h1>", status_code=404)

    return templates.TemplateResponse(
        "task_detail.html",
        {"request": request, "task": task}
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

    return templates.TemplateResponse(
        "sprints.html",
        {
            "request": request,
            "project": current_project,
            "projects": all_projects,
            "sprints": sprints,
            "filter_status": status,
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

    return templates.TemplateResponse(
        "sprint_detail.html",
        {"request": request, "sprint": sprint, "prds": prds, "tasks": tasks, "task_stats": task_stats, "available_prds": available_prds}
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

    return templates.TemplateResponse(
        "prd_detail.html",
        {"request": request, "prd": prd, "sprints": sprints, "tasks": tasks, "graph_data": graph_data, "design": design}
    )


@app.put("/prds/{prd_id}/content")
async def update_prd_content(prd_id: str, request: Request):
    """Update PRD content."""
    storage = get_storage()
    data = await request.json()
    content = data.get("content", "")

    prd = storage.update_prd(prd_id, content=content)
    if not prd:
        return HTMLResponse(content="PRD not found", status_code=404)

    return {"success": True}


@app.put("/prds/{prd_id}/design")
async def update_design_content(prd_id: str, request: Request):
    """Update design document content."""
    storage = get_storage()
    data = await request.json()
    content = data.get("content", "")

    # Check if design exists; create if not
    existing = storage.get_design_by_prd(prd_id)
    if existing:
        design = storage.update_design(prd_id, content=content)
    else:
        prd = storage.get_prd(prd_id)
        if not prd:
            return HTMLResponse(content="PRD not found", status_code=404)
        design = storage.create_design(prd_id=prd_id, project_id=prd["project_id"], content=content)

    if not design:
        return HTMLResponse(content="Failed to save design", status_code=500)

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
    window_start_iso = window_start.isoformat()

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
    storage = get_storage()
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
    storage = get_storage()
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


def run_server(host: str = "127.0.0.1", port: int = 3847) -> None:
    """Run the web UI server."""
    # Clean up any stale server
    if _cleanup_stale_pid():
        print(f"Cleaned up stale UI server process")

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
