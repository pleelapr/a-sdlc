"""
a-sdlc Web UI.

Provides a FastAPI + HTMX dashboard for viewing and managing
PRDs, tasks, and sprints.

Usage:
    a-sdlc ui              # Start web server on http://localhost:3847
    a-sdlc ui --port 8000  # Custom port
"""

from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    import uvicorn
except ImportError:
    raise ImportError(
        "Web UI dependencies not installed. "
        "Install with: pip install 'a-sdlc[ui]'"
    )

from a_sdlc.server.database import get_db

# Get templates directory
TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="a-sdlc Dashboard", version="0.1.0")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _get_current_project(project_id: str | None = None) -> dict[str, Any] | None:
    """Get the specified project or fall back to most recently accessed."""
    db = get_db()
    if project_id:
        return db.get_project(project_id)
    return db.get_most_recent_project()


def _get_all_projects() -> list[dict[str, Any]]:
    """Get all projects for the project switcher."""
    db = get_db()
    return db.list_projects()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, project: str | None = None):
    """Main dashboard showing project overview."""
    db = get_db()
    all_projects = _get_all_projects()
    current_project = _get_current_project(project)

    if not current_project:
        return templates.TemplateResponse(
            "no_project.html",
            {"request": request, "projects": all_projects}
        )

    # Get stats
    tasks = db.list_tasks(current_project["id"])
    sprints = db.list_sprints(current_project["id"])
    prds = db.list_prds(current_project["id"])

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


@app.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request, project: str | None = None, status: str | None = None, sprint_id: str | None = None):
    """Tasks list page."""
    db = get_db()
    all_projects = _get_all_projects()
    current_project = _get_current_project(project)

    if not current_project:
        return templates.TemplateResponse(
            "no_project.html",
            {"request": request, "projects": all_projects}
        )

    # Get tasks - use sprint-specific method if filtering by sprint
    if sprint_id:
        tasks = db.list_tasks_by_sprint(current_project["id"], sprint_id, status=status)
    else:
        tasks = db.list_tasks(current_project["id"], status=status)
    sprints = db.list_sprints(current_project["id"])

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
    db = get_db()
    task = db.get_task(task_id)

    if not task:
        return HTMLResponse(content="<h1>Task not found</h1>", status_code=404)

    return templates.TemplateResponse(
        "task_detail.html",
        {"request": request, "task": task}
    )


@app.post("/tasks/{task_id}/status")
async def update_task_status(task_id: str, status: str):
    """Update task status (HTMX endpoint)."""
    db = get_db()
    task = db.update_task(task_id, status=status)

    if not task:
        return HTMLResponse(content="Task not found", status_code=404)

    return HTMLResponse(
        content=f'<span class="status-{status}">{status.replace("_", " ").title()}</span>'
    )


@app.put("/tasks/{task_id}/description")
async def update_task_description(task_id: str, request: Request):
    """Update task description."""
    db = get_db()
    data = await request.json()
    description = data.get("description", "")

    task = db.update_task(task_id, description=description)
    if not task:
        return HTMLResponse(content="Task not found", status_code=404)

    return {"success": True}


@app.get("/sprints", response_class=HTMLResponse)
async def sprints_page(request: Request, project: str | None = None):
    """Sprints list page."""
    db = get_db()
    all_projects = _get_all_projects()
    current_project = _get_current_project(project)

    if not current_project:
        return templates.TemplateResponse(
            "no_project.html",
            {"request": request, "projects": all_projects}
        )

    sprints = db.list_sprints(current_project["id"])

    # Add task counts to each sprint
    for sprint in sprints:
        tasks = db.list_tasks_by_sprint(current_project["id"], sprint["id"])
        sprint["task_count"] = len(tasks)
        sprint["completed_count"] = sum(1 for t in tasks if t["status"] == "completed")

    return templates.TemplateResponse(
        "sprints.html",
        {"request": request, "project": current_project, "projects": all_projects, "sprints": sprints}
    )


@app.get("/sprints/{sprint_id}", response_class=HTMLResponse)
async def sprint_detail(request: Request, sprint_id: str):
    """Sprint detail page."""
    db = get_db()
    sprint = db.get_sprint(sprint_id)

    if not sprint:
        return HTMLResponse(content="<h1>Sprint not found</h1>", status_code=404)

    # Get PRDs in this sprint
    prds = db.get_sprint_prds(sprint_id)

    # Add task counts to PRDs
    for prd in prds:
        prd_tasks = db.list_tasks(sprint["project_id"], prd_id=prd["id"])
        prd["task_count"] = len(prd_tasks)

    # Get tasks derived from sprint's PRDs
    tasks = db.list_tasks_by_sprint(sprint["project_id"], sprint_id)

    return templates.TemplateResponse(
        "sprint_detail.html",
        {"request": request, "sprint": sprint, "prds": prds, "tasks": tasks}
    )


@app.put("/sprints/{sprint_id}/status")
async def update_sprint_status(sprint_id: str, request: Request):
    """Update sprint status."""
    db = get_db()
    data = await request.json()
    status = data.get("status", "planned")

    sprint = db.update_sprint(sprint_id, status=status)
    if not sprint:
        return HTMLResponse(content="Sprint not found", status_code=404)

    return {"success": True}


@app.get("/prds", response_class=HTMLResponse)
async def prds_page(request: Request, project: str | None = None):
    """PRDs list page."""
    db = get_db()
    all_projects = _get_all_projects()
    current_project = _get_current_project(project)

    if not current_project:
        return templates.TemplateResponse(
            "no_project.html",
            {"request": request, "projects": all_projects}
        )

    prds = db.list_prds(current_project["id"])

    return templates.TemplateResponse(
        "prds.html",
        {"request": request, "project": current_project, "projects": all_projects, "prds": prds}
    )


@app.get("/prds/{prd_id}", response_class=HTMLResponse)
async def prd_detail(request: Request, prd_id: str):
    """PRD detail page."""
    db = get_db()
    prd = db.get_prd(prd_id)

    if not prd:
        return HTMLResponse(content="<h1>PRD not found</h1>", status_code=404)

    # Get sprints for the project to populate sprint selector
    sprints = db.list_sprints(prd["project_id"])

    return templates.TemplateResponse(
        "prd_detail.html",
        {"request": request, "prd": prd, "sprints": sprints}
    )


@app.put("/prds/{prd_id}/content")
async def update_prd_content(prd_id: str, request: Request):
    """Update PRD content."""
    db = get_db()
    data = await request.json()
    content = data.get("content", "")

    prd = db.update_prd(prd_id, content=content)
    if not prd:
        return HTMLResponse(content="PRD not found", status_code=404)

    return {"success": True}


@app.put("/prds/{prd_id}/sprint")
async def update_prd_sprint(prd_id: str, request: Request):
    """Update PRD sprint assignment."""
    db = get_db()
    data = await request.json()
    sprint_id = data.get("sprint_id")

    # Convert empty string to None (backlog)
    if sprint_id == "":
        sprint_id = None

    prd = db.update_prd(prd_id, sprint_id=sprint_id)
    if not prd:
        return HTMLResponse(content="PRD not found", status_code=404)

    return {"success": True}


@app.put("/prds/{prd_id}/status")
async def update_prd_status(prd_id: str, request: Request):
    """Update PRD status."""
    db = get_db()
    data = await request.json()
    status = data.get("status", "draft")

    prd = db.update_prd(prd_id, status=status)
    if not prd:
        return HTMLResponse(content="PRD not found", status_code=404)

    return {"success": True}


def run_server(host: str = "127.0.0.1", port: int = 3847) -> None:
    """Run the web UI server."""
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()
