"""
a-sdlc MCP Server.

Provides MCP tools for managing SDLC artifacts (PRDs, tasks, sprints)
through Claude Code integration.

Usage:
    a-sdlc serve              # Start MCP server with stdio transport
    uvx a-sdlc serve          # Run via uvx (Claude Code config)
"""

import atexit
import json
import os
import re
import signal
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# Module-level variable to track UI server process
_ui_process: subprocess.Popen | None = None

from a_sdlc.server.database import Database, get_db

# Initialize FastMCP server
mcp = FastMCP(
    name="asdlc",
    instructions="SDLC management tools for PRDs, tasks, and sprints",
)


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


# =============================================================================
# Context & Navigation Tools
# =============================================================================


@mcp.tool()
def get_context() -> dict[str, Any]:
    """Get current project context and summary.

    Returns the active project with task/sprint statistics.
    Auto-detects project from current working directory.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {
            "status": "no_project",
            "message": "No project found for current directory. Run /sdlc:init first.",
            "cwd": os.getcwd(),
        }

    project = db.get_project(project_id)
    tasks = db.list_tasks(project_id)
    sprints = db.list_sprints(project_id)
    prds = db.list_prds(project_id)

    # Calculate statistics
    task_stats = {}
    for task in tasks:
        status = task["status"]
        task_stats[status] = task_stats.get(status, 0) + 1

    active_sprint = next((s for s in sprints if s["status"] == "active"), None)

    return {
        "status": "ok",
        "project": {
            "id": project["id"],
            "name": project["name"],
            "path": project["path"],
        },
        "statistics": {
            "total_prds": len(prds),
            "total_tasks": len(tasks),
            "total_sprints": len(sprints),
            "tasks_by_status": task_stats,
        },
        "active_sprint": {
            "id": active_sprint["id"],
            "title": active_sprint["title"],
        } if active_sprint else None,
    }


@mcp.tool()
def list_projects() -> list[dict[str, Any]]:
    """List all known projects.

    Returns projects ordered by last accessed time.
    """
    db = get_db()
    projects = db.list_projects()
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "path": p["path"],
            "last_accessed": p["last_accessed"],
        }
        for p in projects
    ]


@mcp.tool()
def init_project(name: str | None = None) -> dict[str, Any]:
    """Initialize a project for the current directory.

    Args:
        name: Optional project name. Defaults to folder name.

    Returns:
        Created project details.
    """
    db = get_db()
    cwd = os.getcwd()

    # Check if already exists
    existing = db.get_project_by_path(cwd)
    if existing:
        return {
            "status": "exists",
            "message": f"Project already initialized: {existing['name']}",
            "project": existing,
        }

    # Generate project ID from folder name
    folder_name = Path(cwd).name
    project_id = _slugify(folder_name)
    project_name = name or folder_name

    project = db.create_project(project_id, project_name, cwd)

    return {
        "status": "created",
        "message": f"Project '{project_name}' initialized.",
        "project": project,
    }


@mcp.tool()
def switch_project(project_id: str) -> dict[str, Any]:
    """Switch to a different project context.

    Args:
        project_id: ID of the project to switch to.

    Returns:
        Project details if found.
    """
    db = get_db()
    project = db.get_project(project_id)

    if not project:
        return {
            "status": "not_found",
            "message": f"Project not found: {project_id}",
        }

    db.update_project_accessed(project_id)
    return {
        "status": "ok",
        "message": f"Switched to project: {project['name']}",
        "project": project,
    }


# =============================================================================
# PRD Operations
# =============================================================================


@mcp.tool()
def list_prds(
    project_id: str | None = None,
    sprint_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List PRDs for a project.

    Args:
        project_id: Optional project ID. Auto-detects if not provided.
        sprint_id: Filter by sprint. Use empty string for backlog PRDs.
        status: Filter by PRD status (draft, ready, split).

    Returns:
        List of PRD summaries.
    """
    db = get_db()
    pid = project_id or _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    prds = db.list_prds(pid, sprint_id=sprint_id, status=status)
    return {
        "status": "ok",
        "project_id": pid,
        "filters": {
            "sprint_id": sprint_id,
            "status": status,
        },
        "count": len(prds),
        "prds": [
            {
                "id": p["id"],
                "title": p["title"],
                "status": p["status"],
                "version": p["version"],
                "sprint_id": p.get("sprint_id"),
                "updated_at": p["updated_at"],
            }
            for p in prds
        ],
    }


@mcp.tool()
def get_prd(prd_id: str) -> dict[str, Any]:
    """Get full PRD content.

    Args:
        prd_id: PRD identifier.

    Returns:
        Full PRD including content.
    """
    db = get_db()
    prd = db.get_prd(prd_id)

    if not prd:
        return {"status": "not_found", "message": f"PRD not found: {prd_id}"}

    return {
        "status": "ok",
        "prd": prd,
    }


@mcp.tool()
def create_prd(
    title: str,
    content: str,
    project_id: str | None = None,
    status: str = "draft",
    source: str | None = None,
    sprint_id: str | None = None,
) -> dict[str, Any]:
    """Create a new PRD.

    Args:
        title: PRD title.
        content: Full markdown content.
        project_id: Optional project ID. Auto-detects if not provided.
        status: PRD status (draft, ready, split, completed).
        source: Optional source reference (e.g., 'jira:PROJ-123').
        sprint_id: Optional sprint to assign this PRD to.

    Returns:
        Created PRD details.
    """
    db = get_db()
    pid = project_id or _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    # Prefix prd_id with project_id for global uniqueness
    prd_id = f"{pid}-{_slugify(title)}"
    prd = db.create_prd(prd_id, pid, title, content, status, source, sprint_id)

    return {
        "status": "created",
        "message": f"PRD created: {prd_id}",
        "prd": prd,
    }


@mcp.tool()
def update_prd(
    prd_id: str,
    title: str | None = None,
    content: str | None = None,
    status: str | None = None,
    version: str | None = None,
    sprint_id: str | None = None,
) -> dict[str, Any]:
    """Update an existing PRD.

    Args:
        prd_id: PRD identifier.
        title: New title (optional).
        content: New content (optional).
        status: New status (optional).
        version: New version (optional).
        sprint_id: New sprint assignment (optional). Use empty string to unassign.

    Returns:
        Updated PRD details.
    """
    db = get_db()

    # Build update kwargs
    kwargs = {}
    if title is not None:
        kwargs["title"] = title
    if content is not None:
        kwargs["content"] = content
    if status is not None:
        kwargs["status"] = status
    if version is not None:
        kwargs["version"] = version
    if sprint_id is not None:
        # Empty string means unassign from sprint
        kwargs["sprint_id"] = sprint_id if sprint_id else None

    if not kwargs:
        return {"status": "error", "message": "No fields to update"}

    prd = db.update_prd(prd_id, **kwargs)

    if not prd:
        return {"status": "not_found", "message": f"PRD not found: {prd_id}"}

    return {
        "status": "updated",
        "message": f"PRD updated: {prd_id}",
        "prd": prd,
    }


@mcp.tool()
def delete_prd(prd_id: str) -> dict[str, Any]:
    """Delete a PRD.

    Args:
        prd_id: PRD identifier.

    Returns:
        Deletion status.
    """
    db = get_db()
    deleted = db.delete_prd(prd_id)

    if not deleted:
        return {"status": "not_found", "message": f"PRD not found: {prd_id}"}

    return {
        "status": "deleted",
        "message": f"PRD deleted: {prd_id}",
    }


# =============================================================================
# Task Operations
# =============================================================================


@mcp.tool()
def list_tasks(
    project_id: str | None = None,
    status: str | None = None,
    prd_id: str | None = None,
    sprint_id: str | None = None,
) -> dict[str, Any]:
    """List tasks with optional filters.

    Args:
        project_id: Optional project ID. Auto-detects if not provided.
        status: Filter by status (pending, in_progress, completed, blocked).
        prd_id: Filter by parent PRD.
        sprint_id: Filter by sprint (derived from PRD's sprint assignment).

    Returns:
        List of task summaries.

    Note:
        Tasks no longer have direct sprint_id. Sprint membership is
        derived from the parent PRD's sprint assignment.
    """
    db = get_db()
    pid = project_id or _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    tasks = db.list_tasks(pid, status=status, prd_id=prd_id, sprint_id=sprint_id)

    return {
        "status": "ok",
        "project_id": pid,
        "filters": {
            "status": status,
            "prd_id": prd_id,
            "sprint_id": sprint_id,
        },
        "count": len(tasks),
        "tasks": [
            {
                "id": t["id"],
                "title": t["title"],
                "status": t["status"],
                "priority": t["priority"],
                "component": t["component"],
                "prd_id": t.get("prd_id"),
                "updated_at": t["updated_at"],
            }
            for t in tasks
        ],
    }


@mcp.tool()
def get_task(task_id: str) -> dict[str, Any]:
    """Get full task details.

    Args:
        task_id: Task identifier.

    Returns:
        Full task including description and data.
    """
    db = get_db()
    task = db.get_task(task_id)

    if not task:
        return {"status": "not_found", "message": f"Task not found: {task_id}"}

    return {
        "status": "ok",
        "task": task,
    }


@mcp.tool()
def create_task(
    title: str,
    description: str = "",
    project_id: str | None = None,
    prd_id: str | None = None,
    priority: str = "medium",
    component: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new task.

    Args:
        title: Task title.
        description: Task description.
        project_id: Optional project ID. Auto-detects if not provided.
        prd_id: Optional parent PRD. Task inherits sprint from PRD.
        priority: Task priority (low, medium, high, critical).
        component: Optional component/module name.
        data: Optional additional structured data.

    Returns:
        Created task details.

    Note:
        Tasks no longer have direct sprint_id. To assign a task to a sprint,
        set its prd_id to a PRD that belongs to that sprint.
    """
    db = get_db()
    pid = project_id or _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    task_id = db.get_next_task_id(pid)
    task = db.create_task(
        task_id=task_id,
        project_id=pid,
        title=title,
        description=description,
        prd_id=prd_id,
        priority=priority,
        component=component,
        data=data,
    )

    return {
        "status": "created",
        "message": f"Task created: {task_id}",
        "task": task,
    }


@mcp.tool()
def update_task(
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    component: str | None = None,
    prd_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update an existing task.

    Args:
        task_id: Task identifier.
        title: New title (optional).
        description: New description (optional).
        status: New status (optional).
        priority: New priority (optional).
        component: New component (optional).
        prd_id: New parent PRD (optional). Use empty string to unassign.
        data: New structured data (optional).

    Returns:
        Updated task details.

    Note:
        To change a task's sprint, update its parent PRD's sprint_id
        or move the task to a different PRD.
    """
    db = get_db()

    # Build update kwargs
    kwargs = {}
    if title is not None:
        kwargs["title"] = title
    if description is not None:
        kwargs["description"] = description
    if status is not None:
        kwargs["status"] = status
    if priority is not None:
        kwargs["priority"] = priority
    if component is not None:
        kwargs["component"] = component
    if prd_id is not None:
        # Empty string means unassign from PRD
        kwargs["prd_id"] = prd_id if prd_id else None
    if data is not None:
        kwargs["data"] = data

    if not kwargs:
        return {"status": "error", "message": "No fields to update"}

    task = db.update_task(task_id, **kwargs)

    if not task:
        return {"status": "not_found", "message": f"Task not found: {task_id}"}

    return {
        "status": "updated",
        "message": f"Task updated: {task_id}",
        "task": task,
    }


@mcp.tool()
def start_task(task_id: str) -> dict[str, Any]:
    """Mark a task as in progress.

    Args:
        task_id: Task identifier.

    Returns:
        Updated task details.
    """
    return update_task(task_id, status="in_progress")


@mcp.tool()
def complete_task(task_id: str) -> dict[str, Any]:
    """Mark a task as completed.

    Args:
        task_id: Task identifier.

    Returns:
        Updated task details.
    """
    return update_task(task_id, status="completed")


@mcp.tool()
def block_task(task_id: str, reason: str | None = None) -> dict[str, Any]:
    """Mark a task as blocked.

    Args:
        task_id: Task identifier.
        reason: Optional blocking reason.

    Returns:
        Updated task details.
    """
    db = get_db()
    task = db.get_task(task_id)

    if not task:
        return {"status": "not_found", "message": f"Task not found: {task_id}"}

    # Update data with block reason
    data = task.get("data") or {}
    if reason:
        data["block_reason"] = reason

    return update_task(task_id, status="blocked", data=data)


@mcp.tool()
def delete_task(task_id: str) -> dict[str, Any]:
    """Delete a task.

    Args:
        task_id: Task identifier.

    Returns:
        Deletion status.
    """
    db = get_db()
    deleted = db.delete_task(task_id)

    if not deleted:
        return {"status": "not_found", "message": f"Task not found: {task_id}"}

    return {
        "status": "deleted",
        "message": f"Task deleted: {task_id}",
    }


@mcp.tool()
def split_prd(
    prd_id: str,
    task_specs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Split a PRD into tasks atomically.

    Creates all tasks in a single operation to ensure persistence even if
    the agent session is interrupted. This is the recommended way to create
    tasks from a PRD breakdown.

    Args:
        prd_id: The PRD to split.
        task_specs: List of task specifications. Each spec should contain:
            - title (required): Task title
            - description (optional): Task description
            - priority (optional): low, medium, high, critical (default: medium)
            - component (optional): Component/module name
            - dependencies (optional): List of task IDs this task depends on

    Returns:
        Created task IDs and status.

    Example:
        split_prd(
            prd_id="feature-auth",
            task_specs=[
                {"title": "Set up OAuth config", "priority": "high", "component": "auth"},
                {"title": "Implement login flow", "priority": "high", "component": "auth"},
                {"title": "Add logout endpoint", "priority": "medium", "component": "auth"},
            ]
        )
    """
    db = get_db()
    pid = _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    # Verify PRD exists
    prd = db.get_prd(prd_id)
    if not prd:
        return {"status": "error", "message": f"PRD not found: {prd_id}"}

    if not task_specs:
        return {"status": "error", "message": "No task specifications provided"}

    # Helper to resolve shorthand dependency references to full task IDs
    def resolve_dep_id(dep: str | int) -> str:
        dep_str = str(dep).strip()

        # Already a full ID (contains project prefix)
        if dep_str.startswith(pid):
            return dep_str

        # Extract task number from various formats:
        # "1", "task-1", "TASK-001", "task-001"
        match = re.search(r'(\d+)$', dep_str)
        if match:
            num = int(match.group(1))
            return f"{pid}-TASK-{num:03d}"

        # Can't resolve, return as-is
        return dep_str

    created_tasks = []
    try:
        for spec in task_specs:
            if not spec.get("title"):
                return {"status": "error", "message": "Each task spec must have a 'title'"}

            task_id = db.get_next_task_id(pid)

            # Build data dict if dependencies provided, resolving shorthand IDs
            data = None
            if spec.get("dependencies"):
                resolved_deps = [resolve_dep_id(d) for d in spec["dependencies"]]
                data = {"dependencies": resolved_deps}

            task = db.create_task(
                task_id=task_id,
                project_id=pid,
                title=spec["title"],
                description=spec.get("description", ""),
                prd_id=prd_id,
                priority=spec.get("priority", "medium"),
                component=spec.get("component"),
                data=data,
            )
            created_tasks.append({
                "id": task["id"],
                "title": task["title"],
                "priority": task["priority"],
                "component": task.get("component"),
            })

        # Update PRD status to "split"
        db.update_prd(prd_id, status="split")

        return {
            "status": "success",
            "message": f"Created {len(created_tasks)} tasks from PRD '{prd_id}'",
            "prd_id": prd_id,
            "prd_status": "split",
            "tasks_created": len(created_tasks),
            "tasks": created_tasks,
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to create tasks: {str(e)}"}


# =============================================================================
# Sprint Operations
# =============================================================================


@mcp.tool()
def list_sprints(project_id: str | None = None) -> dict[str, Any]:
    """List sprints for a project.

    Args:
        project_id: Optional project ID. Auto-detects if not provided.

    Returns:
        List of sprint summaries.
    """
    db = get_db()
    pid = project_id or _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    sprints = db.list_sprints(pid)

    return {
        "status": "ok",
        "project_id": pid,
        "count": len(sprints),
        "sprints": [
            {
                "id": s["id"],
                "title": s["title"],
                "status": s["status"],
                "created_at": s["created_at"],
                "started_at": s["started_at"],
                "completed_at": s["completed_at"],
            }
            for s in sprints
        ],
    }


@mcp.tool()
def get_sprint(sprint_id: str) -> dict[str, Any]:
    """Get sprint details with PRD and task summary.

    Args:
        sprint_id: Sprint identifier.

    Returns:
        Sprint details including PRDs and task counts.
    """
    db = get_db()
    sprint = db.get_sprint(sprint_id)

    if not sprint:
        return {"status": "not_found", "message": f"Sprint not found: {sprint_id}"}

    # Get PRDs in this sprint
    prds = db.get_sprint_prds(sprint_id)

    # Get derived tasks
    tasks = db.list_tasks_by_sprint(sprint["project_id"], sprint_id)

    return {
        "status": "ok",
        "sprint": sprint,
        "prds": [
            {
                "id": p["id"],
                "title": p["title"],
                "status": p["status"],
            }
            for p in prds
        ],
        "tasks": [
            {
                "id": t["id"],
                "title": t["title"],
                "status": t["status"],
                "priority": t["priority"],
                "prd_id": t.get("prd_id"),
            }
            for t in tasks
        ],
    }


@mcp.tool()
def create_sprint(
    title: str,
    goal: str = "",
    project_id: str | None = None,
) -> dict[str, Any]:
    """Create a new sprint.

    Args:
        title: Sprint title.
        goal: Sprint goal/objective.
        project_id: Optional project ID. Auto-detects if not provided.

    Returns:
        Created sprint details.
    """
    db = get_db()
    pid = project_id or _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    sprint_id = db.get_next_sprint_id(pid)
    sprint = db.create_sprint(sprint_id, pid, title, goal)

    return {
        "status": "created",
        "message": f"Sprint created: {sprint_id}",
        "sprint": sprint,
    }


@mcp.tool()
def start_sprint(sprint_id: str) -> dict[str, Any]:
    """Start a sprint (mark as active).

    Args:
        sprint_id: Sprint identifier.

    Returns:
        Updated sprint details.
    """
    db = get_db()
    sprint = db.update_sprint(sprint_id, status="active")

    if not sprint:
        return {"status": "not_found", "message": f"Sprint not found: {sprint_id}"}

    return {
        "status": "started",
        "message": f"Sprint started: {sprint_id}",
        "sprint": sprint,
    }


@mcp.tool()
def complete_sprint(sprint_id: str) -> dict[str, Any]:
    """Complete a sprint.

    Args:
        sprint_id: Sprint identifier.

    Returns:
        Updated sprint details with final statistics.
    """
    db = get_db()
    sprint = db.get_sprint(sprint_id)

    if not sprint:
        return {"status": "not_found", "message": f"Sprint not found: {sprint_id}"}

    # Get final task stats (derived via PRDs)
    tasks = db.list_tasks_by_sprint(sprint["project_id"], sprint_id)
    completed = sum(1 for t in tasks if t["status"] == "completed")
    total = len(tasks)

    # Get PRD stats
    prds = db.get_sprint_prds(sprint_id)

    sprint = db.update_sprint(sprint_id, status="completed")

    return {
        "status": "completed",
        "message": f"Sprint completed: {sprint_id}",
        "sprint": sprint,
        "statistics": {
            "total_prds": len(prds),
            "total_tasks": total,
            "completed_tasks": completed,
            "completion_rate": f"{(completed / total * 100):.0f}%" if total > 0 else "N/A",
        },
    }


@mcp.tool()
def add_prd_to_sprint(sprint_id: str, prd_id: str) -> dict[str, Any]:
    """Assign a PRD to a sprint.

    When a PRD is assigned to a sprint, all tasks under that PRD
    are considered part of the sprint.

    Args:
        sprint_id: Sprint identifier.
        prd_id: PRD identifier.

    Returns:
        Updated PRD details.
    """
    db = get_db()
    sprint = db.get_sprint(sprint_id)

    if not sprint:
        return {"status": "not_found", "message": f"Sprint not found: {sprint_id}"}

    prd = db.get_prd(prd_id)
    if not prd:
        return {"status": "not_found", "message": f"PRD not found: {prd_id}"}

    updated_prd = db.assign_prd_to_sprint(prd_id, sprint_id)

    return {
        "status": "ok",
        "message": f"Assigned PRD {prd_id} to sprint {sprint_id}",
        "prd": updated_prd,
    }


@mcp.tool()
def remove_prd_from_sprint(prd_id: str) -> dict[str, Any]:
    """Remove a PRD from its current sprint (move to backlog).

    Args:
        prd_id: PRD identifier.

    Returns:
        Updated PRD details.
    """
    db = get_db()
    prd = db.get_prd(prd_id)

    if not prd:
        return {"status": "not_found", "message": f"PRD not found: {prd_id}"}

    if not prd.get("sprint_id"):
        return {
            "status": "ok",
            "message": f"PRD {prd_id} is not assigned to any sprint",
            "prd": prd,
        }

    updated_prd = db.assign_prd_to_sprint(prd_id, None)

    return {
        "status": "ok",
        "message": f"Removed PRD {prd_id} from sprint (moved to backlog)",
        "prd": updated_prd,
    }


@mcp.tool()
def get_sprint_prds(sprint_id: str) -> dict[str, Any]:
    """Get all PRDs assigned to a sprint.

    Args:
        sprint_id: Sprint identifier.

    Returns:
        List of PRDs in the sprint.
    """
    db = get_db()
    sprint = db.get_sprint(sprint_id)

    if not sprint:
        return {"status": "not_found", "message": f"Sprint not found: {sprint_id}"}

    prds = db.get_sprint_prds(sprint_id)

    return {
        "status": "ok",
        "sprint_id": sprint_id,
        "count": len(prds),
        "prds": [
            {
                "id": p["id"],
                "title": p["title"],
                "status": p["status"],
                "version": p["version"],
            }
            for p in prds
        ],
    }


@mcp.tool()
def get_sprint_tasks(sprint_id: str, status: str | None = None) -> dict[str, Any]:
    """Get all tasks for a sprint (derived from sprint's PRDs).

    This returns all tasks whose parent PRD is assigned to the sprint.

    Args:
        sprint_id: Sprint identifier.
        status: Optional status filter.

    Returns:
        List of tasks in the sprint.
    """
    db = get_db()
    sprint = db.get_sprint(sprint_id)

    if not sprint:
        return {"status": "not_found", "message": f"Sprint not found: {sprint_id}"}

    tasks = db.list_tasks_by_sprint(sprint["project_id"], sprint_id, status)

    return {
        "status": "ok",
        "sprint_id": sprint_id,
        "filters": {"status": status},
        "count": len(tasks),
        "tasks": [
            {
                "id": t["id"],
                "title": t["title"],
                "status": t["status"],
                "priority": t["priority"],
                "prd_id": t.get("prd_id"),
            }
            for t in tasks
        ],
    }


# =============================================================================
# External Integration Configuration
# =============================================================================


@mcp.tool()
def configure_linear(
    api_key: str,
    team_id: str,
    default_project: str | None = None,
) -> dict[str, Any]:
    """Configure Linear integration for the current project.

    Args:
        api_key: Linear API key (from Settings > API).
        team_id: Team identifier (e.g., 'ENG').
        default_project: Optional default project for new issues.

    Returns:
        Configuration status.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    config = {
        "api_key": api_key,
        "team_id": team_id,
        "default_project": default_project,
    }

    db.set_external_config(project_id, "linear", config)

    return {
        "status": "configured",
        "message": f"Linear integration configured for {project_id}",
        "system": "linear",
        "team_id": team_id,
    }


@mcp.tool()
def configure_jira(
    base_url: str,
    email: str,
    api_token: str,
    project_key: str,
    issue_type: str = "Task",
) -> dict[str, Any]:
    """Configure Jira integration for the current project.

    Args:
        base_url: Jira site URL (e.g., https://company.atlassian.net).
        email: Atlassian account email.
        api_token: API token from Atlassian account settings.
        project_key: Jira project key (e.g., 'PROJ').
        issue_type: Default issue type (default: 'Task').

    Returns:
        Configuration status.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    config = {
        "base_url": base_url.rstrip("/"),
        "email": email,
        "api_token": api_token,
        "project_key": project_key,
        "issue_type": issue_type,
    }

    db.set_external_config(project_id, "jira", config)

    return {
        "status": "configured",
        "message": f"Jira integration configured for {project_id}",
        "system": "jira",
        "project_key": project_key,
    }


@mcp.tool()
def configure_confluence(
    base_url: str,
    email: str,
    api_token: str,
    space_key: str,
    parent_page_id: str | None = None,
    page_title_prefix: str = "[SDLC]",
) -> dict[str, Any]:
    """Configure Confluence integration for the current project.

    Args:
        base_url: Atlassian site URL (e.g., https://company.atlassian.net).
        email: Atlassian account email.
        api_token: API token from Atlassian account settings.
        space_key: Confluence space key (e.g., 'PROJ').
        parent_page_id: Optional parent page ID for SDLC documentation.
        page_title_prefix: Prefix for created pages (default: '[SDLC]').

    Returns:
        Configuration status.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    config = {
        "base_url": base_url.rstrip("/"),
        "email": email,
        "api_token": api_token,
        "space_key": space_key,
        "parent_page_id": parent_page_id,
        "page_title_prefix": page_title_prefix,
    }

    db.set_external_config(project_id, "confluence", config)

    return {
        "status": "configured",
        "message": f"Confluence integration configured for {project_id}",
        "system": "confluence",
        "space_key": space_key,
    }


@mcp.tool()
def get_integrations() -> dict[str, Any]:
    """List configured external integrations for the current project.

    Returns:
        List of configured integrations with their status.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    configs = db.list_external_configs(project_id)

    integrations = []
    for config in configs:
        # Mask sensitive data
        cfg = config.get("config", {})
        masked_config = {
            k: ("***" if k in ["api_key", "api_token"] else v)
            for k, v in cfg.items()
        }
        integrations.append({
            "system": config["system"],
            "config": masked_config,
            "created_at": config["created_at"],
            "updated_at": config["updated_at"],
        })

    return {
        "status": "ok",
        "project_id": project_id,
        "integrations": integrations,
        "count": len(integrations),
    }


@mcp.tool()
def remove_integration(system: str) -> dict[str, Any]:
    """Remove external system integration from the current project.

    Args:
        system: External system name ('linear', 'jira', or 'confluence').

    Returns:
        Removal status.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    if system not in ["linear", "jira", "confluence"]:
        return {"status": "error", "message": f"Unknown system: {system}. Use 'linear', 'jira', or 'confluence'."}

    deleted = db.delete_external_config(project_id, system)

    if not deleted:
        return {
            "status": "not_found",
            "message": f"{system.title()} integration not configured for this project.",
        }

    return {
        "status": "removed",
        "message": f"{system.title()} integration removed from {project_id}",
        "system": system,
    }


# =============================================================================
# External Sync Operations
# =============================================================================


def _get_sync_service():
    """Get sync service instance."""
    from a_sdlc.server.sync import ExternalSyncService
    return ExternalSyncService(get_db())


@mcp.tool()
def import_from_linear(
    cycle_id: str | None = None,
    status: str | None = None,
    active: bool = False,
) -> dict[str, Any]:
    """Import a Linear cycle as a local sprint with PRDs.

    Either provide a specific cycle_id to import, use active=True
    to import the currently active cycle, or use status to list
    available cycles first.

    Args:
        cycle_id: Specific Linear cycle ID to import.
        status: Filter cycles by status ('active', 'upcoming', 'completed').
                If provided without cycle_id and active=False, lists available cycles.
        active: If True, import the currently active cycle (ignores cycle_id).

    Returns:
        Import result or list of available cycles.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    # Check Linear is configured
    config = db.get_external_config(project_id, "linear")
    if not config:
        return {
            "status": "error",
            "message": "Linear not configured. Use configure_linear tool first.",
        }

    # If active flag is set, import active cycle
    if active:
        try:
            sync = _get_sync_service()
            result = sync.import_linear_active_cycle(project_id)

            return {
                "status": "imported",
                "message": f"Imported active cycle as sprint {result['sprint']['id']}",
                "sprint_id": result["sprint"]["id"],
                "sprint_title": result["sprint"]["title"],
                "prds_imported": result["prds_count"],
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    if not cycle_id:
        # List available cycles
        try:
            from a_sdlc.server.sync import LinearClient
            cfg = config["config"]
            client = LinearClient(cfg["api_key"], cfg["team_id"])
            cycles = client.list_cycles(status)

            return {
                "status": "ok",
                "message": "Available cycles (provide cycle_id to import, or use active=True):",
                "cycles": [
                    {
                        "id": c["id"],
                        "name": c.get("name", f"Cycle {c.get('number', '')}"),
                        "progress": c.get("progress", 0),
                        "issues_count": len(c.get("issues", {}).get("nodes", [])),
                    }
                    for c in cycles
                ],
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to list cycles: {e}"}

    # Import specific cycle
    try:
        sync = _get_sync_service()
        result = sync.import_linear_cycle(project_id, cycle_id)

        return {
            "status": "imported",
            "message": f"Imported cycle as sprint {result['sprint']['id']}",
            "sprint_id": result["sprint"]["id"],
            "sprint_title": result["sprint"]["title"],
            "prds_imported": result["prds_count"],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def import_from_jira(
    sprint_id: str | None = None,
    board_id: str | None = None,
    state: str | None = None,
    active: bool = False,
) -> dict[str, Any]:
    """Import a Jira sprint as a local sprint with PRDs.

    Either provide a specific sprint_id to import, use board_id with
    active=True to import the currently active sprint, or use board_id
    and state to list available sprints first.

    Args:
        sprint_id: Specific Jira sprint ID to import (overrides active flag).
        board_id: Jira board ID (required for listing or active sprint).
        state: Filter sprints by state ('active', 'future', 'closed').
        active: If True and board_id provided, import the active sprint.

    Returns:
        Import result or list of available sprints.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    config = db.get_external_config(project_id, "jira")
    if not config:
        return {
            "status": "error",
            "message": "Jira not configured. Use configure_jira tool first.",
        }

    # If active flag is set with board_id, import active sprint
    if active and board_id and not sprint_id:
        try:
            sync = _get_sync_service()
            result = sync.import_jira_active_sprint(project_id, board_id)

            return {
                "status": "imported",
                "message": f"Imported active sprint as {result['sprint']['id']}",
                "sprint_id": result["sprint"]["id"],
                "sprint_title": result["sprint"]["title"],
                "prds_imported": result["prds_count"],
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    if not sprint_id:
        if not board_id:
            return {
                "status": "error",
                "message": "Provide sprint_id to import, board_id with active=True, or board_id to list sprints.",
            }

        # List available sprints
        try:
            from a_sdlc.server.sync import JiraClient
            cfg = config["config"]
            client = JiraClient(
                cfg["base_url"], cfg["email"], cfg["api_token"], cfg["project_key"]
            )
            sprints = client.list_sprints(board_id, state)

            return {
                "status": "ok",
                "message": "Available sprints (provide sprint_id to import, or use active=True):",
                "sprints": [
                    {
                        "id": s["id"],
                        "name": s.get("name", ""),
                        "state": s.get("state", ""),
                        "goal": s.get("goal", ""),
                    }
                    for s in sprints
                ],
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to list sprints: {e}"}

    # Import specific sprint
    try:
        sync = _get_sync_service()
        result = sync.import_jira_sprint(project_id, sprint_id, board_id)

        return {
            "status": "imported",
            "message": f"Imported sprint as {result['sprint']['id']}",
            "sprint_id": result["sprint"]["id"],
            "sprint_title": result["sprint"]["title"],
            "prds_imported": result["prds_count"],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def link_sprint(
    sprint_id: str,
    system: str,
    external_id: str,
) -> dict[str, Any]:
    """Link a local sprint to an external system sprint/cycle.

    Args:
        sprint_id: Local sprint identifier.
        system: External system ('linear' or 'jira').
        external_id: External sprint/cycle ID.

    Returns:
        Link status.
    """
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    if system not in ["linear", "jira"]:
        return {"status": "error", "message": f"Unknown system: {system}. Use 'linear' or 'jira'."}

    try:
        sync = _get_sync_service()
        mapping = sync.link_sprint(project_id, sprint_id, system, external_id)

        return {
            "status": "linked",
            "message": f"Sprint {sprint_id} linked to {system} {external_id}",
            "sprint_id": sprint_id,
            "system": system,
            "external_id": external_id,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def unlink_sprint(sprint_id: str) -> dict[str, Any]:
    """Remove external system link from a sprint.

    Args:
        sprint_id: Local sprint identifier.

    Returns:
        Unlink status.
    """
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    try:
        sync = _get_sync_service()
        unlinked = sync.unlink_sprint(sprint_id)

        if unlinked:
            return {
                "status": "unlinked",
                "message": f"Sprint {sprint_id} unlinked from external system",
                "sprint_id": sprint_id,
            }
        else:
            return {
                "status": "not_linked",
                "message": f"Sprint {sprint_id} was not linked to any external system",
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def sync_sprint(
    sprint_id: str,
    strategy: str = "local-wins",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Bidirectional sync between local sprint and external system.

    Args:
        sprint_id: Local sprint identifier.
        strategy: Conflict resolution ('local-wins' or 'external-wins').
        dry_run: If True, only report what would change.

    Returns:
        Sync results.
    """
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    if strategy not in ["local-wins", "external-wins"]:
        return {
            "status": "error",
            "message": "Strategy must be 'local-wins' or 'external-wins'.",
        }

    try:
        sync = _get_sync_service()
        result = sync.bidirectional_sync(project_id, sprint_id, strategy, dry_run)

        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def sync_sprint_from(sprint_id: str) -> dict[str, Any]:
    """Pull changes from external system to local sprint.

    Args:
        sprint_id: Local sprint identifier.

    Returns:
        Sync results with tasks updated/created.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    # Determine which system
    linear_mapping = db.get_sync_mapping("sprint", sprint_id, "linear")
    jira_mapping = db.get_sync_mapping("sprint", sprint_id, "jira")

    if not linear_mapping and not jira_mapping:
        return {
            "status": "error",
            "message": f"Sprint {sprint_id} is not linked to any external system. Use link_sprint first.",
        }

    try:
        sync = _get_sync_service()

        if linear_mapping:
            result = sync.sync_sprint_from_linear(project_id, sprint_id)
        else:
            result = sync.sync_sprint_from_jira(project_id, sprint_id)

        return {
            "status": "synced",
            "message": f"Pulled changes from external system",
            **result,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def sync_sprint_to(sprint_id: str) -> dict[str, Any]:
    """Push local changes to external system.

    Args:
        sprint_id: Local sprint identifier.

    Returns:
        Sync results with tasks updated/created.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    # Determine which system
    linear_mapping = db.get_sync_mapping("sprint", sprint_id, "linear")
    jira_mapping = db.get_sync_mapping("sprint", sprint_id, "jira")

    if not linear_mapping and not jira_mapping:
        return {
            "status": "error",
            "message": f"Sprint {sprint_id} is not linked to any external system. Use link_sprint first.",
        }

    try:
        sync = _get_sync_service()

        if linear_mapping:
            result = sync.sync_sprint_to_linear(project_id, sprint_id)
        else:
            result = sync.sync_sprint_to_jira(project_id, sprint_id)

        return {
            "status": "synced",
            "message": f"Pushed changes to external system",
            **result,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def list_sync_mappings(
    entity_type: str | None = None,
    external_system: str | None = None,
) -> dict[str, Any]:
    """List all sync mappings for external systems.

    Args:
        entity_type: Filter by type ('sprint' or 'task').
        external_system: Filter by system ('linear' or 'jira').

    Returns:
        List of sync mappings.
    """
    db = get_db()

    mappings = db.list_sync_mappings(entity_type, external_system)

    return {
        "status": "ok",
        "count": len(mappings),
        "mappings": mappings,
    }


# =============================================================================
# Server Entry Point
# =============================================================================

UI_PORT = 3847


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


def _start_ui_server() -> subprocess.Popen | None:
    """Start the UI server in the background if not already running.

    Returns None if UI is already running or if dependencies are not available.
    The UI server lifecycle is tied to the MCP server - it will be terminated
    when the MCP server exits.
    """
    global _ui_process

    if _is_port_in_use(UI_PORT):
        # UI already running
        return None

    # Check if UI dependencies are available
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        # UI dependencies not installed, skip UI startup
        return None

    # Find the a-sdlc executable
    asdlc_path = _find_executable("a-sdlc")
    if asdlc_path:
        _ui_process = subprocess.Popen(
            [asdlc_path, "ui"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _ui_process

    # Try uvx as fallback
    uvx_path = _find_executable("uvx")
    if uvx_path:
        _ui_process = subprocess.Popen(
            [uvx_path, "a-sdlc", "ui"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return _ui_process

    return None


def _stop_ui_server() -> None:
    """Stop the UI server if it was started by this MCP server."""
    global _ui_process
    if _ui_process is not None:
        _ui_process.terminate()
        try:
            _ui_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _ui_process.kill()
        _ui_process = None


def _signal_handler(signum: int, frame) -> None:
    """Handle termination signals by stopping UI server and exiting."""
    _stop_ui_server()
    sys.exit(0)


# Register cleanup handler to stop UI server when MCP server exits
atexit.register(_stop_ui_server)

# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


def run_server(transport: str = "stdio") -> None:
    """Run the MCP server.

    Args:
        transport: Transport type ('stdio' or 'streamable-http').
    """
    # Start UI server in background (for human access)
    _start_ui_server()

    # Run MCP server
    mcp.run(transport=transport)


if __name__ == "__main__":
    run_server()
