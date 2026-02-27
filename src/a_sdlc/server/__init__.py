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
"""

import atexit
import contextlib
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from a_sdlc.core.content import get_content_manager
from a_sdlc.core.database import get_db
from a_sdlc.core.git_config import (
    get_effective_config_summary,
    load_git_safety_config,
    save_git_safety_config,
)
from a_sdlc.storage import get_storage

# Module-level variable to track UI server process
_ui_process: subprocess.Popen | None = None

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

    # Detect artifacts in .sdlc/artifacts/
    artifact_names = [
        "architecture",
        "codebase-summary",
        "data-model",
        "directory-structure",
        "key-workflows",
    ]
    artifacts_dir = Path(project["path"]) / ".sdlc" / "artifacts"
    available_artifacts = []
    if artifacts_dir.is_dir():
        for name in artifact_names:
            if (artifacts_dir / f"{name}.md").is_file():
                available_artifacts.append(name)

    artifact_count = len(available_artifacts)
    if artifact_count == 0:
        scan_status = "not_scanned"
    elif artifact_count == len(artifact_names):
        scan_status = "complete"
    else:
        scan_status = "partial"

    return {
        "status": "ok",
        "project": {
            "id": project["id"],
            "shortname": project["shortname"],
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
        "artifacts": {
            "available": available_artifacts,
            "scan_status": scan_status,
        },
    }


@mcp.tool()
def list_projects() -> list[dict[str, Any]]:
    """List all known projects.

    Returns projects ordered by last accessed time with shortname for each.
    """
    db = get_db()
    projects = db.list_projects()
    return [
        {
            "id": p["id"],
            "shortname": p["shortname"],
            "name": p["name"],
            "path": p["path"],
            "last_accessed": p["last_accessed"],
        }
        for p in projects
    ]


@mcp.tool()
def init_project(
    name: str | None = None,
    shortname: str | None = None,
) -> dict[str, Any]:
    """Initialize a project for the current directory.

    Args:
        name: Optional project name. Defaults to folder name.
        shortname: Optional 4-character uppercase project key (e.g., "PCRA").
                  Must be exactly 4 uppercase letters (A-Z).
                  If not provided, auto-generates from project name.

    Returns:
        Created project details including shortname.
        All entity IDs will use this shortname (e.g., PCRA-T00001, PCRA-S0001).
    """
    db = get_db()
    cwd = os.getcwd()

    # Check if already exists
    existing = db.get_project_by_path(cwd)
    if existing:
        project_path = Path(cwd)
        has_claude_md = (project_path / "CLAUDE.md").exists()
        has_lesson_learn = (project_path / ".sdlc" / "lesson-learn.md").exists()
        has_sdlc_dir = (project_path / ".sdlc").exists()

        return {
            "status": "exists",
            "message": f"Project already initialized: {existing['name']}",
            "project": existing,
            "init_files": {
                "claude_md": has_claude_md,
                "lesson_learn": has_lesson_learn,
                "sdlc_dir": has_sdlc_dir,
            },
        }

    # Generate project ID from folder name
    folder_name = Path(cwd).name
    project_id = _slugify(folder_name)
    project_name = name or folder_name

    # Validate shortname if provided
    if shortname is not None:
        is_valid, error_msg = db.validate_shortname(shortname)
        if not is_valid:
            return {
                "status": "error",
                "message": f"Invalid shortname: {error_msg}",
            }
        if not db.is_shortname_available(shortname):
            return {
                "status": "error",
                "message": f"Shortname '{shortname}' is already in use by another project.",
            }
    else:
        # Generate suggestion for user awareness
        shortname = db.generate_unique_shortname(project_name)

    try:
        project = db.create_project(project_id, project_name, cwd, shortname)
    except ValueError as e:
        return {
            "status": "error",
            "message": str(e),
        }

    # Generate CLAUDE.md, lesson-learn.md, and global lesson-learn.md
    from a_sdlc.core.init_files import generate_init_files

    init_results = generate_init_files(Path(cwd), project_name)

    return {
        "status": "created",
        "message": f"Project '{project_name}' initialized with shortname '{shortname}'.",
        "project": project,
        "id_format_examples": {
            "task": f"{shortname}-T00001",
            "sprint": f"{shortname}-S0001",
            "prd": f"{shortname}-P0001",
        },
        "init_files": init_results["results"],
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


@mcp.tool()
def relocate_project(shortname: str) -> dict[str, Any]:
    """Re-link an existing project to the current directory.

    Use this when you've moved a repository to a new location and want to
    reconnect it to its existing project data (PRDs, tasks, sprints).

    Args:
        shortname: The 4-character project shortname to relocate.

    Returns:
        Updated project details.
    """
    db = get_db()
    cwd = os.getcwd()

    # Find project by shortname
    project = db.get_project_by_shortname(shortname)
    if not project:
        return {
            "status": "not_found",
            "message": f"No project found with shortname '{shortname}'.",
        }

    # Check if current directory is already linked to a different project
    existing = db.get_project_by_path(cwd)
    if existing and existing["id"] != project["id"]:
        return {
            "status": "error",
            "message": f"Current directory is already linked to project '{existing['name']}' ({existing['shortname']}).",
        }

    # Update the project path
    try:
        updated = db.update_project_path(project["id"], cwd)
    except ValueError as e:
        return {
            "status": "error",
            "message": str(e),
        }

    if not updated:
        return {
            "status": "error",
            "message": "Failed to update project path.",
        }

    return {
        "status": "relocated",
        "message": f"Project '{project['name']}' ({shortname}) relocated to {cwd}",
        "project": updated,
        "old_path": project["path"],
        "new_path": cwd,
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
        List of PRD summaries (metadata only, no content).
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
                "file_path": p.get("file_path"),
                "updated_at": p["updated_at"],
            }
            for p in prds
        ],
    }


@mcp.tool()
def get_prd(prd_id: str) -> dict[str, Any]:
    """Get full PRD with content.

    Args:
        prd_id: PRD identifier.

    Returns:
        Full PRD including content from markdown file.
    """
    db = get_db()
    content_mgr = get_content_manager()

    prd = db.get_prd(prd_id)
    if not prd:
        return {"status": "not_found", "message": f"PRD not found: {prd_id}"}

    # Read content from file
    content = None
    if prd.get("file_path"):
        content = content_mgr.read_content(Path(prd["file_path"]))
    else:
        # Try to find by project_id and prd_id
        content = content_mgr.read_prd(prd["project_id"], prd_id)

    prd_with_content = dict(prd)
    prd_with_content["content"] = content

    return {
        "status": "ok",
        "prd": prd_with_content,
    }


@mcp.tool()
def create_prd(
    title: str,
    project_id: str | None = None,
    status: str = "draft",
    source: str | None = None,
    sprint_id: str | None = None,
) -> dict[str, Any]:
    """Create a new PRD (metadata + skeleton file).

    Creates a DB record and an empty skeleton file. Returns the file_path
    so the caller can write content directly using the Write tool.

    Args:
        title: PRD title.
        project_id: Optional project ID. Auto-detects if not provided.
        status: PRD status (draft, ready, split, completed).
        source: Optional source reference (e.g., 'jira:PROJ-123').
        sprint_id: Optional sprint to assign this PRD to.

    Returns:
        Created PRD details with ID and file_path for content writing.
    """
    db = get_db()
    content_mgr = get_content_manager()
    pid = project_id or _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    # Generate PRD ID using shortname format
    prd_id = db.get_next_prd_id(pid)

    # Write skeleton file (just title header)
    file_path = content_mgr.write_prd(pid, prd_id, title, "")

    # Register in database
    prd = db.create_prd(
        prd_id=prd_id,
        project_id=pid,
        title=title,
        file_path=str(file_path),
        status=status,
        source=source,
        sprint_id=sprint_id,
    )

    return {
        "status": "created",
        "message": f"PRD created: {prd_id}",
        "prd": dict(prd),
        "file_path": str(file_path),
    }


@mcp.tool()
def update_prd(
    prd_id: str,
    title: str | None = None,
    status: str | None = None,
    version: str | None = None,
    sprint_id: str | None = None,
) -> dict[str, Any]:
    """Update PRD metadata (DB only, no file operations).

    For content changes, edit the file directly using the Edit tool.
    Use get_prd() to obtain the file_path.

    Args:
        prd_id: PRD identifier.
        title: New title (optional).
        status: New status (optional).
        version: New version (optional).
        sprint_id: New sprint assignment (optional). Use empty string to unassign.

    Returns:
        Updated PRD details.
    """
    db = get_db()

    prd = db.get_prd(prd_id)
    if not prd:
        return {"status": "not_found", "message": f"PRD not found: {prd_id}"}

    # Build update kwargs for database
    db_kwargs = {}
    if title is not None:
        db_kwargs["title"] = title
    if status is not None:
        db_kwargs["status"] = status
    if version is not None:
        db_kwargs["version"] = version
    if sprint_id is not None:
        # Empty string means unassign from sprint
        db_kwargs["sprint_id"] = sprint_id if sprint_id else None

    if not db_kwargs:
        return {"status": "error", "message": "No fields to update"}

    updated_prd = db.update_prd(prd_id, **db_kwargs)

    return {
        "status": "updated",
        "message": f"PRD updated: {prd_id}",
        "prd": updated_prd,
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
    content_mgr = get_content_manager()

    prd = db.get_prd(prd_id)
    if not prd:
        return {"status": "not_found", "message": f"PRD not found: {prd_id}"}

    # Delete content file
    content_mgr.delete_prd(prd["project_id"], prd_id)

    # Delete any sync mappings for this PRD
    db.delete_sync_mapping("prd", prd_id, "linear")
    db.delete_sync_mapping("prd", prd_id, "jira")

    # Delete from database
    db.delete_prd(prd_id)

    return {
        "status": "deleted",
        "message": f"PRD deleted: {prd_id}",
    }


# =============================================================================
# Design Document Operations
# =============================================================================


@mcp.tool()
def create_design(prd_id: str) -> dict[str, Any]:
    """Create a design document for a PRD (skeleton file).

    Each PRD can have one design document (ADR-style architecture decision record).
    Creates a DB record and empty file. Returns file_path so the caller can
    write content directly using the Write tool.

    Args:
        prd_id: Parent PRD identifier.

    Returns:
        Created design document details with file_path for content writing.
    """
    storage = get_storage()
    pid = _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    # Validate PRD exists
    prd = storage.get_prd(prd_id)
    if not prd:
        return {"status": "not_found", "message": f"PRD not found: {prd_id}"}

    # Check for existing design
    existing = storage.get_design_by_prd(prd_id)
    if existing:
        return {"status": "error", "message": f"Design already exists for PRD {prd_id}. Edit the file directly instead."}

    design = storage.create_design(prd_id=prd_id, project_id=pid)
    return {
        "status": "created",
        "message": f"Design document created for PRD {prd_id}",
        "design": design,
        "file_path": design.get("file_path"),
    }


@mcp.tool()
def get_design(prd_id: str) -> dict[str, Any]:
    """Get design document for a PRD with full content.

    Args:
        prd_id: PRD identifier.

    Returns:
        Design document with metadata and content.
    """
    storage = get_storage()
    design = storage.get_design_by_prd(prd_id)

    if not design:
        return {"status": "not_found", "message": f"No design document found for PRD: {prd_id}"}

    return {
        "status": "ok",
        "design": design,
    }


@mcp.tool()
def delete_design(prd_id: str) -> dict[str, Any]:
    """Delete a design document.

    Args:
        prd_id: PRD identifier.

    Returns:
        Deletion status.
    """
    storage = get_storage()
    deleted = storage.delete_design(prd_id)

    if not deleted:
        return {"status": "not_found", "message": f"No design document found for PRD: {prd_id}"}

    return {
        "status": "deleted",
        "message": f"Design document deleted for PRD {prd_id}",
    }


@mcp.tool()
def list_designs(project_id: str | None = None) -> dict[str, Any]:
    """List design documents for a project.

    Args:
        project_id: Optional project ID. Auto-detects if not provided.

    Returns:
        List of design document summaries (metadata only).
    """
    storage = get_storage()
    pid = project_id or _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    designs = storage.list_designs(pid)
    return {
        "status": "ok",
        "project_id": pid,
        "count": len(designs),
        "designs": designs,
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
        List of task summaries (metadata only).

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
                "file_path": t.get("file_path"),
                "updated_at": t["updated_at"],
            }
            for t in tasks
        ],
    }


@mcp.tool()
def get_task(task_id: str) -> dict[str, Any]:
    """Get full task details with content.

    Args:
        task_id: Task identifier.

    Returns:
        Full task including description from markdown file.
    """
    db = get_db()
    content_mgr = get_content_manager()

    task = db.get_task(task_id)
    if not task:
        return {"status": "not_found", "message": f"Task not found: {task_id}"}

    # Read content from file
    content = None
    if task.get("file_path"):
        content = content_mgr.read_content(Path(task["file_path"]))
    else:
        content = content_mgr.read_task(task["project_id"], task_id)

    task_with_content = dict(task)
    task_with_content["content"] = content

    # Parse content for description and data
    if content:
        parsed = content_mgr.parse_task_content(content)
        task_with_content["description"] = parsed.get("description", "")
        if "dependencies" in parsed:
            task_with_content["data"] = {"dependencies": parsed["dependencies"]}

    # Derive sprint_id from PRD (tasks inherit sprint from their parent PRD)
    sprint_id = None
    if task.get("prd_id"):
        prd = db.get_prd(task["prd_id"])
        if prd:
            sprint_id = prd.get("sprint_id")
    task_with_content["sprint_id"] = sprint_id

    return {
        "status": "ok",
        "task": task_with_content,
    }


@mcp.tool()
def create_task(
    title: str,
    project_id: str | None = None,
    prd_id: str | None = None,
    priority: str = "medium",
    component: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new task (metadata + skeleton file).

    Creates a DB record and a skeleton task file. Returns the file_path
    so the caller can write content directly using the Write tool.

    Args:
        title: Task title.
        project_id: Optional project ID. Auto-detects if not provided.
        prd_id: Optional parent PRD. Task inherits sprint from PRD.
        priority: Task priority (low, medium, high, critical).
        component: Optional component/module name.
        data: Optional additional structured data (including dependencies).

    Returns:
        Created task details with file_path for content writing.

    Note:
        Tasks no longer have direct sprint_id. To assign a task to a sprint,
        set its prd_id to a PRD that belongs to that sprint.
    """
    db = get_db()
    content_mgr = get_content_manager()
    pid = project_id or _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    task_id = db.get_next_task_id(pid)

    # Write skeleton file
    file_path = content_mgr.write_task(
        project_id=pid,
        task_id=task_id,
        title=title,
        description="",
        priority=priority,
        status="pending",
        component=component,
        prd_id=prd_id,
        data=data,
    )

    # Register in database
    task = db.create_task(
        task_id=task_id,
        project_id=pid,
        title=title,
        file_path=str(file_path),
        prd_id=prd_id,
        priority=priority,
        component=component,
    )

    return {
        "status": "created",
        "message": f"Task created: {task_id}",
        "task": dict(task),
        "file_path": str(file_path),
    }


@mcp.tool()
def update_task(
    task_id: str,
    title: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    component: str | None = None,
    prd_id: str | None = None,
) -> dict[str, Any]:
    """Update task metadata (DB only, no file operations).

    For content/description changes, edit the file directly using the Edit tool.
    Use get_task() to obtain the file_path.

    Args:
        task_id: Task identifier.
        title: New title (optional).
        status: New status (optional).
        priority: New priority (optional).
        component: New component (optional).
        prd_id: New parent PRD (optional). Use empty string to unassign.

    Returns:
        Updated task details.

    Note:
        To change a task's sprint, update its parent PRD's sprint_id
        or move the task to a different PRD.
    """
    db = get_db()

    task = db.get_task(task_id)
    if not task:
        return {"status": "not_found", "message": f"Task not found: {task_id}"}

    # Build update kwargs for database
    db_kwargs = {}
    if title is not None:
        db_kwargs["title"] = title
    if status is not None:
        db_kwargs["status"] = status
    if priority is not None:
        db_kwargs["priority"] = priority
    if component is not None:
        db_kwargs["component"] = component
    if prd_id is not None:
        # Empty string means unassign from PRD
        db_kwargs["prd_id"] = prd_id if prd_id else None

    if not db_kwargs:
        return {"status": "error", "message": "No fields to update"}

    updated_task = db.update_task(task_id, **db_kwargs)

    return {
        "status": "updated",
        "message": f"Task updated: {task_id}",
        "task": updated_task,
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
        reason: Optional blocking reason (stored in task file, not DB).

    Returns:
        Updated task details.
    """
    return update_task(task_id, status="blocked")


@mcp.tool()
def delete_task(task_id: str) -> dict[str, Any]:
    """Delete a task.

    Args:
        task_id: Task identifier.

    Returns:
        Deletion status.
    """
    db = get_db()
    content_mgr = get_content_manager()

    task = db.get_task(task_id)
    if not task:
        return {"status": "not_found", "message": f"Task not found: {task_id}"}

    # Delete content file
    content_mgr.delete_task(task["project_id"], task_id)

    # Delete any sync mappings for this task
    db.delete_sync_mapping("task", task_id, "linear")
    db.delete_sync_mapping("task", task_id, "jira")

    # Delete from database
    db.delete_task(task_id)

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

    Creates skeleton files for each task. Returns file_path for each task
    so the caller can write content directly using the Write tool.

    Supports two workflows:
    1. Simple: Provide title + metadata, tool creates skeleton files
    2. Multi-agent: Provide task_id for pre-written files (Content Generation Agent
       writes files first, then this tool persists to DB)

    Args:
        prd_id: The PRD to split.
        task_specs: List of task specifications. Each spec should contain:
            - title (required): Task title
            - priority (optional): low, medium, high, critical (default: medium)
            - component (optional): Component/module name
            - dependencies (optional): List of task IDs this task depends on
            - traces_to (optional): List of PRD requirement IDs (e.g., ["FR-001", "AC-002"])
            - design_compliance (optional): List of design decision IDs (e.g., ["DD-1"])
            - task_id (optional): Pre-specified task ID for multi-agent workflow.
              If provided and file exists, uses existing file instead of generating.

    Returns:
        Created task IDs, file_paths, and status.

    Example (simple workflow):
        split_prd(
            prd_id="feature-auth",
            task_specs=[
                {"title": "Set up OAuth config", "priority": "high", "component": "auth"},
                {"title": "Implement login flow", "priority": "high", "component": "auth"},
            ]
        )

    Example (multi-agent workflow - files pre-written):
        split_prd(
            prd_id="feature-auth",
            task_specs=[
                {"task_id": "AUTH-T00001", "title": "Set up OAuth config", "priority": "high"},
                {"task_id": "AUTH-T00002", "title": "Implement login flow", "priority": "high"},
            ]
        )
    """
    db = get_db()
    content_mgr = get_content_manager()
    pid = _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    # Verify PRD exists
    prd = db.get_prd(prd_id)
    if not prd:
        return {"status": "error", "message": f"PRD not found: {prd_id}"}

    if not task_specs:
        return {"status": "error", "message": "No task specifications provided"}

    # Get project shortname for ID formatting
    project = db.get_project(pid)
    shortname = project["shortname"] if project else "UNKN"

    # Helper to resolve shorthand dependency references to full task IDs
    def resolve_dep_id(dep: str | int) -> str:
        dep_str = str(dep).strip()

        # Already a full ID with correct format (e.g., "CWAI-T00001")
        if re.match(r'^[A-Z]{4}-T\d{5}$', dep_str):
            return dep_str

        # Extract task number from various formats:
        # "1", "task-1", "TASK-001", "task-001", "T00001"
        match = re.search(r'(\d+)$', dep_str)
        if match:
            num = int(match.group(1))
            return f"{shortname}-T{num:05d}"

        # Can't resolve, return as-is
        return dep_str

    created_tasks = []
    files_reused = 0
    try:
        for spec in task_specs:
            if not spec.get("title"):
                return {"status": "error", "message": "Each task spec must have a 'title'"}

            # Use pre-specified task_id if provided, otherwise auto-generate
            task_id = spec.get("task_id") or db.get_next_task_id(pid)

            # Build data dict for dependencies, traces, and design compliance
            raw_data = {}
            if spec.get("dependencies"):
                resolved_deps = [resolve_dep_id(d) for d in spec["dependencies"]]
                raw_data["dependencies"] = resolved_deps
            if spec.get("traces_to"):
                raw_data["traces_to"] = spec["traces_to"]
            if spec.get("design_compliance"):
                raw_data["design_compliance"] = spec["design_compliance"]
            data = raw_data if raw_data else None

            # Check if file was pre-written (multi-agent workflow)
            file_path = content_mgr.get_task_path(pid, task_id)
            file_existed = file_path.exists()

            if file_existed:
                # File was pre-written by Content Generation Agent
                files_reused += 1
            else:
                # Write skeleton file (caller writes content via Write tool)
                file_path = content_mgr.write_task(
                    project_id=pid,
                    task_id=task_id,
                    title=spec["title"],
                    description="",
                    priority=spec.get("priority", "medium"),
                    status="pending",
                    component=spec.get("component"),
                    prd_id=prd_id,
                    data=data,
                )

            # Register in database
            task = db.create_task(
                task_id=task_id,
                project_id=pid,
                title=spec["title"],
                file_path=str(file_path),
                prd_id=prd_id,
                priority=spec.get("priority", "medium"),
                component=spec.get("component"),
            )

            created_tasks.append({
                "id": task["id"],
                "title": task["title"],
                "priority": task["priority"],
                "component": task.get("component"),
                "file_path": str(file_path),
                "file_reused": file_existed,
            })

        # Update PRD status to "split"
        db.update_prd(prd_id, status="split")

        result = {
            "status": "success",
            "message": f"Created {len(created_tasks)} tasks from PRD '{prd_id}'",
            "prd_id": prd_id,
            "prd_status": "split",
            "tasks_created": len(created_tasks),
            "tasks": created_tasks,
        }

        # Add note if files were reused (multi-agent workflow)
        if files_reused > 0:
            result["files_reused"] = files_reused
            result["note"] = f"{files_reused} task file(s) were pre-written and reused"

        return result
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
def delete_sprint(sprint_id: str) -> dict[str, Any]:
    """Delete a sprint.

    PRDs assigned to this sprint are unlinked (not deleted).
    Tasks under those PRDs are preserved.

    Args:
        sprint_id: Sprint identifier.

    Returns:
        Deletion status.
    """
    db = get_db()

    sprint = db.get_sprint(sprint_id)
    if not sprint:
        return {"status": "not_found", "message": f"Sprint not found: {sprint_id}"}

    # Get stats before deletion
    prds = db.get_sprint_prds(sprint_id)
    prd_count = len(prds)

    # Unlink PRDs from sprint (set sprint_id to NULL)
    for prd in prds:
        db.assign_prd_to_sprint(prd["id"], None)

    # Delete any sync mappings
    db.delete_sync_mapping("sprint", sprint_id, "linear")
    db.delete_sync_mapping("sprint", sprint_id, "jira")

    # Delete from database
    db.delete_sprint(sprint_id)

    return {
        "status": "deleted",
        "message": f"Sprint deleted: {sprint_id}",
        "unlinked_prds": prd_count,
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
def get_sprint_tasks(
    sprint_id: str,
    status: str | None = None,
    group_by_prd: bool = False,
) -> dict[str, Any]:
    """Get all tasks for a sprint (derived from sprint's PRDs).

    This returns all tasks whose parent PRD is assigned to the sprint.

    Args:
        sprint_id: Sprint identifier.
        status: Optional status filter.
        group_by_prd: If True, return tasks grouped by PRD instead of flat list.

    Returns:
        List of tasks in the sprint. When group_by_prd is True, returns
        prd_groups with tasks nested under each PRD.
    """
    db = get_db()
    sprint = db.get_sprint(sprint_id)

    if not sprint:
        return {"status": "not_found", "message": f"Sprint not found: {sprint_id}"}

    tasks = db.list_tasks_by_sprint(sprint["project_id"], sprint_id, status)

    if group_by_prd:
        # Group tasks by PRD
        prds = db.get_sprint_prds(sprint_id)
        prd_map = {p["id"]: p for p in prds}

        groups: dict[str, list[dict[str, Any]]] = {}
        for t in tasks:
            prd_id = t.get("prd_id", "unassigned")
            if prd_id not in groups:
                groups[prd_id] = []
            groups[prd_id].append({
                "id": t["id"],
                "title": t["title"],
                "status": t["status"],
                "priority": t["priority"],
                "prd_id": prd_id,
            })

        prd_groups = []
        for prd_id, prd_tasks in groups.items():
            prd_info = prd_map.get(prd_id, {})
            prd_groups.append({
                "prd_id": prd_id,
                "prd_title": prd_info.get("title", "Unknown PRD"),
                "prd_status": prd_info.get("status", "unknown"),
                "tasks": prd_tasks,
            })

        return {
            "status": "ok",
            "sprint_id": sprint_id,
            "filters": {"status": status, "group_by_prd": True},
            "count": len(tasks),
            "prd_groups": prd_groups,
        }

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


# Alias for backward compatibility
add_tasks_to_sprint = add_prd_to_sprint
remove_tasks_from_sprint = remove_prd_from_sprint


# =============================================================================
# Git Safety Configuration Tools
# =============================================================================


@mcp.tool()
def configure_git_safety(
    auto_commit: bool | None = None,
    auto_pr: bool | None = None,
    auto_merge: bool | None = None,
    worktree_enabled: bool | None = None,
    scope: str = "project",
) -> dict[str, Any]:
    """Configure git safety settings for agent operations.

    Controls which git operations agents are allowed to perform.
    Global config provides defaults (all off); project config can override.

    Destructive operations (force push, branch deletion) always require
    explicit user confirmation regardless of these settings.

    Args:
        auto_commit: Allow agent to commit changes automatically.
        auto_pr: Allow agent to create pull requests.
        auto_merge: Allow agent to merge branches.
        worktree_enabled: Use git worktree isolation for PRD execution.
        scope: Where to save — "global" or "project" (default: project).

    Returns:
        Updated effective configuration with sources.
    """
    if scope not in ("global", "project"):
        return {
            "status": "error",
            "message": f"Invalid scope: {scope}. Use 'global' or 'project'.",
        }

    # Build settings dict from provided arguments only
    settings: dict[str, bool] = {}
    if auto_commit is not None:
        settings["auto_commit"] = auto_commit
    if auto_pr is not None:
        settings["auto_pr"] = auto_pr
    if auto_merge is not None:
        settings["auto_merge"] = auto_merge
    if worktree_enabled is not None:
        settings["worktree_enabled"] = worktree_enabled

    if not settings:
        # No settings provided — return current config
        summary = get_effective_config_summary()
        return {
            "status": "ok",
            "message": "Current git safety configuration (no changes made).",
            "config": summary,
        }

    try:
        config_path = save_git_safety_config(
            settings=settings,
            target=scope,  # type: ignore[arg-type]
        )
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    summary = get_effective_config_summary()
    return {
        "status": "configured",
        "message": f"Git safety settings saved to {scope} config ({config_path}).",
        "config": summary,
    }


@mcp.tool()
def get_git_safety_config() -> dict[str, Any]:
    """Get the current effective git safety configuration.

    Shows the merged result of global defaults + project overrides,
    along with the source of each setting.

    Returns:
        Effective configuration with sources.
    """
    summary = get_effective_config_summary()
    return {
        "status": "ok",
        "config": summary,
    }


# =============================================================================
# PRD Worktree Isolation Tools
# =============================================================================



def _ensure_gitignore_entry(repo_root: Path, entry: str) -> None:
    """Ensure an entry exists in .gitignore."""
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if entry not in content.splitlines():
            with open(gitignore, "a") as f:
                if not content.endswith("\n"):
                    f.write("\n")
                f.write(f"{entry}\n")
    else:
        gitignore.write_text(f"{entry}\n")


@mcp.tool()
def setup_prd_worktree(
    prd_id: str,
    sprint_id: str,
    base_branch: str | None = None,
    port_offset: int = 0,
) -> dict[str, Any]:
    """Set up an isolated git worktree for a PRD's tasks.

    Creates a git worktree with its own branch for isolated PRD execution.
    Writes environment overrides for Docker namespace isolation.

    Args:
        prd_id: PRD identifier (e.g., PROJ-P0001).
        sprint_id: Sprint identifier for branch naming.
        base_branch: Branch to base worktree on. Defaults to current HEAD.
        port_offset: Port offset for Docker service isolation (0, 100, 200...).

    Returns:
        Worktree details including path, branch name, and environment config.
    """
    repo_root = Path(os.getcwd())

    # Check git safety config — worktree_enabled must be true
    git_config = load_git_safety_config(repo_root)
    if not git_config.is_operation_allowed("worktree_enabled"):
        return {
            "status": "disabled",
            "message": (
                "Worktree isolation is disabled by git safety configuration. "
                "Enable it with: configure_git_safety(worktree_enabled=True)"
            ),
        }

    worktree_dir = repo_root / ".worktrees"
    worktree_path = worktree_dir / prd_id
    branch_name = f"sprint/{sprint_id}/{prd_id}"

    # Get project context and DB
    db = get_db()
    project_id = _get_current_project_id()
    project = db.get_project(project_id) if project_id else None
    shortname = project["shortname"].lower() if project else "proj"

    # Check if worktree already exists in DB
    existing = db.get_worktree_by_prd(prd_id)
    if existing and Path(existing["path"]).exists():
        return {
            "status": "exists",
            "message": f"Worktree for {prd_id} already exists",
            "worktree": existing,
        }

    # Ensure .worktrees/ is in .gitignore
    _ensure_gitignore_entry(repo_root, ".worktrees/")

    # Create branch from base
    base = base_branch or "HEAD"
    try:
        subprocess.run(
            ["git", "branch", branch_name, base],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        # Branch may already exist (resume scenario)
        if "already exists" not in e.stderr:
            return {
                "status": "error",
                "message": f"Failed to create branch: {e.stderr.strip()}",
            }

    # Create worktree
    try:
        subprocess.run(
            ["git", "worktree", "add", str(worktree_path), branch_name],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "message": f"Failed to create worktree: {e.stderr.strip()}",
        }

    # Ensure worktree directory exists (git worktree add creates it,
    # but we ensure it for robustness)
    worktree_path.mkdir(parents=True, exist_ok=True)

    # Write .env.prd-override in worktree
    compose_name = f"{shortname}-{prd_id.lower()}"
    env_content = (
        f"COMPOSE_PROJECT_NAME={compose_name}\n"
        f"A_SDLC_PORT_OFFSET={port_offset}\n"
        f"A_SDLC_PRD_ID={prd_id}\n"
    )
    env_path = worktree_path / ".env.prd-override"
    env_path.write_text(env_content)

    # Record worktree in database
    worktree_id = db.get_next_worktree_id(project_id) if project_id else prd_id
    db.create_worktree(
        worktree_id=worktree_id,
        project_id=project_id or "",
        prd_id=prd_id,
        branch_name=branch_name,
        path=str(worktree_path),
        sprint_id=sprint_id,
        status="active",
    )

    return {
        "status": "created",
        "message": f"Worktree created for {prd_id}",
        "worktree": {
            "id": worktree_id,
            "prd_id": prd_id,
            "branch": branch_name,
            "path": str(worktree_path),
            "port_offset": port_offset,
            "compose_name": compose_name,
            "env_file": str(env_path),
        },
    }


@mcp.tool()
def cleanup_prd_worktree(
    prd_id: str,
    remove_branch: bool = False,
    confirm_branch_delete: bool = False,
    docker_cleanup: bool = True,
) -> dict[str, Any]:
    """Clean up a PRD's git worktree and optionally its Docker resources.

    Looks up worktree state from the database. If no DB record exists but
    an orphaned worktree directory is found on disk, cleans it up anyway.

    Branch deletion is a destructive operation and always requires explicit
    confirmation via confirm_branch_delete=True, regardless of git safety
    configuration.

    Args:
        prd_id: PRD identifier.
        remove_branch: If True, also delete the worktree's branch.
        confirm_branch_delete: Must be True to actually delete the branch.
            Required as a safety measure for destructive operations.
        docker_cleanup: If True, run docker compose down for the PRD's namespace.

    Returns:
        Cleanup status.
    """
    repo_root = Path(os.getcwd())
    db = get_db()
    worktree_info = db.get_worktree_by_prd(prd_id)

    # Fallback: detect orphan worktree on disk when DB has no record
    if not worktree_info:
        orphan_path = repo_root / ".worktrees" / prd_id
        if orphan_path.exists():
            return _cleanup_orphan_worktree(repo_root, orphan_path, prd_id)
        return {
            "status": "not_found",
            "message": f"No worktree found for {prd_id}",
        }

    worktree_path = Path(worktree_info["path"])
    branch_name = worktree_info["branch_name"]

    # Branch deletion requires explicit confirmation (destructive operation)
    if remove_branch and not confirm_branch_delete:
        return {
            "status": "confirmation_required",
            "message": (
                f"Branch deletion is a destructive operation that always requires "
                f"explicit confirmation. To delete branch '{branch_name}', "
                f"call again with confirm_branch_delete=True."
            ),
            "branch": branch_name,
        }

    errors = []

    # Docker cleanup (compose_name not stored in DB -- derive from project)
    compose_name = ""
    project_id = worktree_info.get("project_id")
    if project_id:
        project = db.get_project(project_id)
        if project:
            compose_name = f"{project['shortname'].lower()}-{prd_id.lower()}"

    if docker_cleanup and compose_name:
        try:
            subprocess.run(
                ["docker", "compose", "-p", compose_name, "down", "-v"],
                cwd=str(worktree_path) if worktree_path.exists() else str(repo_root),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            errors.append(f"Docker cleanup warning: {e}")

    # Remove worktree directory via git
    if worktree_path.exists():
        try:
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_path), "--force"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            errors.append(f"Worktree removal warning: {e.stderr.strip()}")

    # Prune stale worktree references
    try:
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        errors.append(f"Worktree prune warning: {e.stderr.strip()}")

    # Remove branch if requested AND confirmed
    if remove_branch and confirm_branch_delete:
        try:
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            errors.append(f"Branch deletion warning: {e.stderr.strip()}")

    # Update worktree status in database
    db.update_worktree(worktree_info["id"], status="abandoned")

    result: dict[str, Any] = {
        "status": "cleaned",
        "message": f"Worktree for {prd_id} cleaned up",
        "branch_removed": remove_branch and confirm_branch_delete,
        "docker_cleaned": docker_cleanup,
    }
    if errors:
        result["warnings"] = errors

    return result


def _cleanup_orphan_worktree(
    repo_root: Path,
    orphan_path: Path,
    prd_id: str,
) -> dict[str, Any]:
    """Clean up an orphaned worktree directory that has no database record.

    This handles the edge case where a worktree exists on disk (e.g. from
    a previous run, manual creation, or DB reset) but has no corresponding
    database entry.

    Args:
        repo_root: Repository root path.
        orphan_path: Path to the orphaned worktree directory.
        prd_id: PRD identifier.

    Returns:
        Cleanup result dict.
    """
    errors: list[str] = []

    # Try git worktree remove first
    try:
        subprocess.run(
            ["git", "worktree", "remove", str(orphan_path), "--force"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        errors.append(f"Worktree removal warning: {e.stderr.strip()}")
        # Fall back to manual directory removal if git worktree remove fails
        try:
            shutil.rmtree(str(orphan_path))
        except OSError as rm_err:
            errors.append(f"Manual removal warning: {rm_err}")

    # Prune stale worktree references
    try:
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        errors.append(f"Worktree prune warning: {e.stderr.strip()}")

    result: dict[str, Any] = {
        "status": "cleaned",
        "message": f"Orphaned worktree for {prd_id} cleaned up (no DB record found)",
        "orphan": True,
        "branch_removed": False,
        "docker_cleaned": False,
    }
    if errors:
        result["warnings"] = errors

    return result


@mcp.tool()
def create_prd_pr(
    prd_id: str,
    sprint_id: str,
    base_branch: str | None = None,
    title: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """Create a pull request for a PRD's worktree branch.

    Pushes the PRD branch to remote and creates a PR via gh CLI.

    Args:
        prd_id: PRD identifier.
        sprint_id: Sprint identifier (for branch name lookup).
        base_branch: Target branch for the PR. Defaults to repo default branch.
        title: PR title. Auto-generated from PRD metadata if not provided.
        body: PR body. Auto-generated if not provided.

    Returns:
        PR URL and details.
    """
    repo_root = Path(os.getcwd())

    # Check git safety config — auto_pr must be enabled
    git_config = load_git_safety_config(repo_root)
    if not git_config.is_operation_allowed("auto_pr"):
        return {
            "status": "disabled",
            "message": (
                "Automatic PR creation is disabled by git safety configuration. "
                "Enable it with: configure_git_safety(auto_pr=True)"
            ),
        }

    db = get_db()
    worktree_info = db.get_worktree_by_prd(prd_id)

    if not worktree_info:
        return {
            "status": "not_found",
            "message": f"No worktree found for {prd_id}. Run setup_prd_worktree first.",
        }

    branch_name = worktree_info["branch_name"]

    # Get PRD metadata for auto-generated title/body
    prd = db.get_prd(prd_id)
    prd_title = prd["title"] if prd else prd_id

    pr_title = title or f"[{sprint_id}] {prd_title}"
    pr_body = body or (
        f"## Summary\n\n"
        f"Implementation for PRD **{prd_id}**: {prd_title}\n\n"
        f"Sprint: {sprint_id}\n"
        f"Branch: `{branch_name}`\n"
    )

    # Push branch to remote
    try:
        subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "message": f"Failed to push branch: {e.stderr.strip()}",
        }

    # Create PR via gh CLI
    gh_cmd = ["gh", "pr", "create", "--title", pr_title, "--body", pr_body, "--head", branch_name]
    if base_branch:
        gh_cmd.extend(["--base", base_branch])

    try:
        result = subprocess.run(
            gh_cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        pr_url = result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "message": f"Failed to create PR: {e.stderr.strip()}",
        }

    # Store PR URL in database (keep status as "active" — status changes via complete_prd_worktree)
    db.update_worktree(worktree_info["id"], pr_url=pr_url)

    return {
        "status": "created",
        "message": f"PR created for {prd_id}",
        "pr_url": pr_url,
        "branch": branch_name,
        "title": pr_title,
    }


@mcp.tool()
def list_worktrees(
    project_id: str | None = None,
    status: str | None = None,
    sprint_id: str | None = None,
) -> dict[str, Any]:
    """List tracked worktrees with optional filters.

    Returns all worktrees for the current project with their state,
    associated PRD/sprint, branch name, and path.

    Args:
        project_id: Optional project ID. Auto-detects if not provided.
        status: Filter by worktree status (active, completed, abandoned).
        sprint_id: Filter by sprint ID.

    Returns:
        List of worktree summaries.
    """
    db = get_db()
    pid = project_id or _get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    worktrees = db.list_worktrees(pid, status=status, sprint_id=sprint_id)
    return {
        "status": "ok",
        "project_id": pid,
        "filters": {
            "status": status,
            "sprint_id": sprint_id,
        },
        "count": len(worktrees),
        "worktrees": [
            {
                "id": w["id"],
                "prd_id": w["prd_id"],
                "sprint_id": w.get("sprint_id"),
                "branch_name": w["branch_name"],
                "path": w["path"],
                "status": w["status"],
                "created_at": w["created_at"],
                "cleaned_at": w.get("cleaned_at"),
            }
            for w in worktrees
        ],
    }


@mcp.tool()
def complete_prd_worktree(
    prd_id: str,
    action: str,
    base_branch: str | None = None,
    pr_title: str | None = None,
    pr_body: str | None = None,
    confirm_discard: bool = False,
) -> dict[str, Any]:
    """Complete a PRD worktree by applying a chosen action.

    After all tasks for a PRD pass review, use this tool to finalize
    the worktree. Four actions are available:

    - **merge**: Merge the worktree branch into the base branch locally.
      Requires auto_merge to be enabled in git safety config.
      Worktree is cleaned up after merge.
    - **pr**: Create a pull request for the worktree branch.
      Requires auto_pr to be enabled in git safety config.
      Worktree is kept (not cleaned up) so the branch stays available.
    - **keep**: Keep the worktree and branch as-is for manual handling.
      No cleanup is performed.
    - **discard**: Remove the worktree and branch entirely.
      Requires confirm_discard=True as a safety measure.
      Worktree is cleaned up and branch is deleted.

    Args:
        prd_id: PRD identifier.
        action: Completion action — one of "merge", "pr", "keep", "discard".
        base_branch: Target branch for merge/PR. Defaults to repo default branch.
        pr_title: Custom PR title (for "pr" action). Auto-generated if not provided.
        pr_body: Custom PR body (for "pr" action). Auto-generated if not provided.
        confirm_discard: Must be True to execute "discard" action. Safety measure.

    Returns:
        Completion result with action taken and any relevant details.
    """
    valid_actions = ("merge", "pr", "keep", "discard")
    if action not in valid_actions:
        return {
            "status": "error",
            "message": (
                f"Invalid action: '{action}'. "
                f"Valid actions: {', '.join(valid_actions)}"
            ),
        }

    repo_root = Path(os.getcwd())
    db = get_db()
    worktree_info = db.get_worktree_by_prd(prd_id)

    if not worktree_info:
        return {
            "status": "not_found",
            "message": f"No active worktree found for {prd_id}.",
        }

    branch_name = worktree_info["branch_name"]
    sprint_id = worktree_info.get("sprint_id", "")

    git_config = load_git_safety_config(repo_root)

    # --- action: keep ---
    if action == "keep":
        return {
            "status": "kept",
            "message": f"Worktree for {prd_id} kept as-is. Branch: {branch_name}",
            "worktree_id": worktree_info["id"],
            "branch": branch_name,
            "path": worktree_info["path"],
        }

    # --- action: discard ---
    if action == "discard":
        if not confirm_discard:
            return {
                "status": "confirmation_required",
                "message": (
                    f"Discard is a destructive operation. It will remove the worktree "
                    f"and delete branch '{branch_name}'. "
                    f"Call again with confirm_discard=True to proceed."
                ),
                "branch": branch_name,
            }
        # Delegate to cleanup_prd_worktree with branch removal
        return cleanup_prd_worktree(
            prd_id=prd_id,
            remove_branch=True,
            confirm_branch_delete=True,
            docker_cleanup=True,
        )

    # --- action: pr ---
    if action == "pr":
        if not git_config.is_operation_allowed("auto_pr"):
            return {
                "status": "disabled",
                "message": (
                    "Automatic PR creation is disabled by git safety configuration. "
                    "Enable it with: configure_git_safety(auto_pr=True)"
                ),
            }
        # Delegate to create_prd_pr
        return create_prd_pr(
            prd_id=prd_id,
            sprint_id=sprint_id,
            base_branch=base_branch,
            title=pr_title,
            body=pr_body,
        )

    # --- action: merge ---
    if action == "merge":
        if not git_config.is_operation_allowed("auto_merge"):
            return {
                "status": "disabled",
                "message": (
                    "Automatic merge is disabled by git safety configuration. "
                    "Enable it with: configure_git_safety(auto_merge=True)"
                ),
            }

        # Determine base branch
        target_branch = base_branch
        if not target_branch:
            try:
                result = subprocess.run(
                    ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    # e.g., "refs/remotes/origin/main" -> "main"
                    target_branch = result.stdout.strip().split("/")[-1]
            except Exception:
                pass
            if not target_branch:
                target_branch = "main"

        # Merge the worktree branch into target
        try:
            subprocess.run(
                ["git", "merge", branch_name, "--no-ff",
                 "-m", f"Merge {prd_id} ({branch_name}) into {target_branch}"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            return {
                "status": "error",
                "message": f"Merge failed: {e.stderr.strip()}",
            }

        # Cleanup worktree after successful merge (no branch removal —
        # branch is merged, can be deleted separately if desired)
        cleanup_result = cleanup_prd_worktree(
            prd_id=prd_id,
            remove_branch=False,
            docker_cleanup=True,
        )

        return {
            "status": "merged",
            "message": f"Branch {branch_name} merged into {target_branch}. Worktree cleaned up.",
            "worktree_id": worktree_info["id"],
            "branch": branch_name,
            "target_branch": target_branch,
            "cleanup": cleanup_result,
        }

    # Should not reach here due to validation above, but satisfy type checker
    return {"status": "error", "message": "Unexpected action."}


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
def configure_github(token: str, scope: str = "project") -> dict[str, Any]:
    """Configure GitHub integration for the current project or globally.

    Stores a GitHub token for PR feedback retrieval. The token is validated
    before storing.

    Args:
        token: GitHub personal access token or fine-grained token with 'repo' scope.
        scope: Where to store the token — 'project' (default) or 'global' (~/.config/a-sdlc/).

    Returns:
        Configuration status with authenticated username.
    """
    from a_sdlc.server.github import GitHubClient, save_global_github_config

    # Validate token before storing
    try:
        client = GitHubClient(token)
        user = client.validate_token()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    if scope == "global":
        save_global_github_config({"token": token})
        return {
            "status": "configured",
            "message": f"GitHub integration configured globally (authenticated as @{user['login']})",
            "system": "github",
            "scope": "global",
            "user": user["login"],
        }

    # Project scope
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    config = {"token": token}
    db.set_external_config(project_id, "github", config)

    return {
        "status": "configured",
        "message": f"GitHub integration configured for {project_id} (authenticated as @{user['login']})",
        "system": "github",
        "scope": "project",
        "user": user["login"],
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
            k: ("***" if k in ["api_key", "api_token", "token"] else v)
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
        system: External system name ('linear', 'jira', 'confluence', or 'github').

    Returns:
        Removal status.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    if system not in ["linear", "jira", "confluence", "github"]:
        return {"status": "error", "message": f"Unknown system: {system}. Use 'linear', 'jira', 'confluence', or 'github'."}

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
# GitHub PR Feedback
# =============================================================================


@mcp.tool()
def get_pr_feedback(
    unresolved_only: bool = False,
    reviewer: str | None = None,
) -> dict[str, Any]:
    """Fetch PR review comments for the current branch.

    Detects the GitHub repo and branch from git, finds the open PR,
    and retrieves all review comments (line-level, review summaries,
    and general conversation).

    Token resolution: project config → global config (~/.config/a-sdlc/) → GITHUB_TOKEN env var.

    Args:
        unresolved_only: If True, only return unresolved review threads.
        reviewer: Filter comments by this GitHub username.

    Returns:
        Structured dict with PR info and categorized comments.
    """
    from a_sdlc.server.github import GitHubClient, detect_git_info, load_global_github_config

    db = get_db()
    project_id = _get_current_project_id()

    # Resolve token: project config → global config → env var
    token = None
    if project_id:
        config = db.get_external_config(project_id, "github")
        if config:
            token = config["config"].get("token")

    if not token:
        global_cfg = load_global_github_config()
        if global_cfg:
            token = global_cfg.get("token")

    if not token:
        token = os.environ.get("GITHUB_TOKEN")

    if not token:
        return {
            "status": "error",
            "message": (
                "No GitHub token found. Either:\n"
                "1. Configure per-project: use configure_github tool\n"
                "2. Configure globally: a-sdlc connect github --global\n"
                "3. Set GITHUB_TOKEN environment variable"
            ),
        }

    # Detect repo info from git
    try:
        owner, repo, branch = detect_git_info()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    client = GitHubClient(token)

    # Find PR for current branch
    try:
        pr = client.get_pr_for_branch(owner, repo, branch)
    except httpx.HTTPStatusError as e:
        return {
            "status": "error",
            "message": f"GitHub API error: {e.response.status_code} — {e.response.text[:200]}",
        }

    if not pr:
        return {
            "status": "no_pr",
            "message": f"No open PR found for branch '{branch}' in {owner}/{repo}.",
            "branch": branch,
            "repo": f"{owner}/{repo}",
        }

    pr_number = pr["number"]

    # Fetch all comment types
    try:
        reviews = client.get_reviews(owner, repo, pr_number)
        review_comments = client.get_review_comments(owner, repo, pr_number)
        issue_comments = client.get_issue_comments(owner, repo, pr_number)
    except httpx.HTTPStatusError as e:
        return {
            "status": "error",
            "message": f"Failed to fetch comments: {e.response.status_code}",
        }

    # Get resolved thread IDs if filtering
    resolved_ids: set[str] = set()
    if unresolved_only:
        # GraphQL may fail with limited token scopes; continue without filtering
        with contextlib.suppress(Exception):
            resolved_ids = client.get_resolved_thread_ids(owner, repo, pr_number)

    # Process review comments (line-level)
    processed_review_comments = []
    for c in review_comments:
        comment_id = str(c["id"])

        # Filter resolved
        if unresolved_only and comment_id in resolved_ids:
            continue

        # Filter by reviewer
        if reviewer and c.get("user", {}).get("login") != reviewer:
            continue

        processed_review_comments.append({
            "id": comment_id,
            "type": "review_comment",
            "author": c.get("user", {}).get("login", "unknown"),
            "body": c.get("body", ""),
            "path": c.get("path", ""),
            "line": c.get("original_line") or c.get("line"),
            "side": c.get("side", "RIGHT"),
            "diff_hunk": c.get("diff_hunk", ""),
            "created_at": c.get("created_at", ""),
            "updated_at": c.get("updated_at", ""),
            "in_reply_to_id": c.get("in_reply_to_id"),
            "html_url": c.get("html_url", ""),
        })

    # Process review summaries
    processed_reviews = []
    for r in reviews:
        if reviewer and r.get("user", {}).get("login") != reviewer:
            continue

        # Skip empty review summaries (just approvals with no body)
        body = r.get("body", "").strip()
        state = r.get("state", "")

        processed_reviews.append({
            "id": str(r["id"]),
            "type": "review",
            "author": r.get("user", {}).get("login", "unknown"),
            "body": body,
            "state": state,
            "created_at": r.get("submitted_at", ""),
            "html_url": r.get("html_url", ""),
        })

    # Process general conversation comments
    processed_issue_comments = []
    for c in issue_comments:
        if reviewer and c.get("user", {}).get("login") != reviewer:
            continue

        processed_issue_comments.append({
            "id": str(c["id"]),
            "type": "issue_comment",
            "author": c.get("user", {}).get("login", "unknown"),
            "body": c.get("body", ""),
            "created_at": c.get("created_at", ""),
            "updated_at": c.get("updated_at", ""),
            "html_url": c.get("html_url", ""),
        })

    total = (
        len(processed_review_comments)
        + len(processed_reviews)
        + len(processed_issue_comments)
    )

    return {
        "status": "ok",
        "pr": {
            "number": pr_number,
            "title": pr.get("title", ""),
            "author": pr.get("user", {}).get("login", "unknown"),
            "html_url": pr.get("html_url", ""),
            "state": pr.get("state", ""),
            "branch": branch,
            "base": pr.get("base", {}).get("ref", ""),
        },
        "repo": f"{owner}/{repo}",
        "filters": {
            "unresolved_only": unresolved_only,
            "reviewer": reviewer,
        },
        "summary": {
            "total_comments": total,
            "review_comments": len(processed_review_comments),
            "reviews": len(processed_reviews),
            "issue_comments": len(processed_issue_comments),
        },
        "reviews": processed_reviews,
        "review_comments": processed_review_comments,
        "issue_comments": processed_issue_comments,
    }


# =============================================================================
# External Sync Operations
# =============================================================================


def _get_sync_service():
    """Get sync service instance."""
    from a_sdlc.server.sync import ExternalSyncService
    return ExternalSyncService(get_db(), get_content_manager())


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

            # Handle already_exists status
            if result.get("status") == "already_exists":
                return {
                    "status": "already_exists",
                    "message": f"Sprint already imported as {result['existing_sprint']['id']}",
                    "existing_sprint_id": result["existing_sprint"]["id"],
                    "existing_sprint_title": result["existing_sprint"]["title"],
                    "external_id": result["external_id"],
                    "last_synced": result["mapping"].get("last_synced"),
                    "options": [
                        "use_existing: Use the existing sprint",
                        "sync: Re-sync with /sdlc:sprint-sync",
                        "reimport: Unlink first with /sdlc:sprint-unlink, then reimport",
                        "cancel: Cancel the import",
                    ],
                }

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

        # Handle already_exists status
        if result.get("status") == "already_exists":
            return {
                "status": "already_exists",
                "message": f"Sprint already imported as {result['existing_sprint']['id']}",
                "existing_sprint_id": result["existing_sprint"]["id"],
                "existing_sprint_title": result["existing_sprint"]["title"],
                "external_id": result["external_id"],
                "last_synced": result["mapping"].get("last_synced"),
                "options": [
                    "use_existing: Use the existing sprint",
                    "sync: Re-sync with /sdlc:sprint-sync",
                    "reimport: Unlink first with /sdlc:sprint-unlink, then reimport",
                    "cancel: Cancel the import",
                ],
            }

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

            # Handle already_exists status
            if result.get("status") == "already_exists":
                return {
                    "status": "already_exists",
                    "message": f"Sprint already imported as {result['existing_sprint']['id']}",
                    "existing_sprint_id": result["existing_sprint"]["id"],
                    "existing_sprint_title": result["existing_sprint"]["title"],
                    "external_id": result["external_id"],
                    "last_synced": result["mapping"].get("last_synced"),
                    "options": [
                        "use_existing: Use the existing sprint",
                        "sync: Re-sync with /sdlc:sprint-sync",
                        "reimport: Unlink first with /sdlc:sprint-unlink, then reimport",
                        "cancel: Cancel the import",
                    ],
                }

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

        # Handle already_exists status
        if result.get("status") == "already_exists":
            return {
                "status": "already_exists",
                "message": f"Sprint already imported as {result['existing_sprint']['id']}",
                "existing_sprint_id": result["existing_sprint"]["id"],
                "existing_sprint_title": result["existing_sprint"]["title"],
                "external_id": result["external_id"],
                "last_synced": result["mapping"].get("last_synced"),
                "options": [
                    "use_existing: Use the existing sprint",
                    "sync: Re-sync with /sdlc:sprint-sync",
                    "reimport: Unlink first with /sdlc:sprint-unlink, then reimport",
                    "cancel: Cancel the import",
                ],
            }

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
        sync.link_sprint(project_id, sprint_id, system, external_id)

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
            "message": "Pulled changes from external system",
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
            "message": "Pushed changes to external system",
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
        entity_type: Filter by type ('sprint', 'prd', or 'task').
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
# PRD Sync Operations
# =============================================================================


@mcp.tool()
def link_prd(
    prd_id: str,
    system: str,
    external_id: str,
) -> dict[str, Any]:
    """Link a local PRD to an external system issue.

    Args:
        prd_id: Local PRD identifier.
        system: External system ('linear' or 'jira').
        external_id: External issue ID/key (e.g., 'PROJ-123').

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
        sync.link_prd(project_id, prd_id, system, external_id)

        return {
            "status": "linked",
            "message": f"PRD {prd_id} linked to {system} {external_id}",
            "prd_id": prd_id,
            "system": system,
            "external_id": external_id,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def unlink_prd(prd_id: str) -> dict[str, Any]:
    """Remove external system link from a PRD.

    Args:
        prd_id: Local PRD identifier.

    Returns:
        Unlink status.
    """
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    try:
        sync = _get_sync_service()
        unlinked = sync.unlink_prd(prd_id)

        if unlinked:
            return {
                "status": "unlinked",
                "message": f"PRD {prd_id} unlinked from external system",
                "prd_id": prd_id,
            }
        else:
            return {
                "status": "not_linked",
                "message": f"PRD {prd_id} was not linked to any external system",
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def sync_prd(
    prd_id: str,
    strategy: str = "local-wins",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Bidirectional sync between local PRD and external issue.

    Args:
        prd_id: Local PRD identifier.
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
        result = sync.bidirectional_sync_prd(project_id, prd_id, strategy, dry_run)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def sync_prd_from(prd_id: str) -> dict[str, Any]:
    """Pull changes from external issue to local PRD.

    Args:
        prd_id: Local PRD identifier.

    Returns:
        Sync results.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    linear_mapping = db.get_sync_mapping("prd", prd_id, "linear")
    jira_mapping = db.get_sync_mapping("prd", prd_id, "jira")

    if not linear_mapping and not jira_mapping:
        return {
            "status": "error",
            "message": f"PRD {prd_id} is not linked to any external system. Use link_prd first.",
        }

    try:
        sync = _get_sync_service()

        if jira_mapping:
            result = sync.sync_prd_from_jira(project_id, prd_id)
        else:
            return {"status": "error", "message": "Linear PRD sync not yet implemented"}

        return {
            "status": "synced",
            "message": "Pulled changes from external system",
            **result,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def sync_prd_to(prd_id: str) -> dict[str, Any]:
    """Push local PRD changes to external issue.

    Args:
        prd_id: Local PRD identifier.

    Returns:
        Sync results.
    """
    db = get_db()
    project_id = _get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    linear_mapping = db.get_sync_mapping("prd", prd_id, "linear")
    jira_mapping = db.get_sync_mapping("prd", prd_id, "jira")

    if not linear_mapping and not jira_mapping:
        return {
            "status": "error",
            "message": f"PRD {prd_id} is not linked to any external system. Use link_prd first.",
        }

    try:
        sync = _get_sync_service()

        if jira_mapping:
            result = sync.sync_prd_to_jira(project_id, prd_id)
        else:
            return {"status": "error", "message": "Linear PRD sync not yet implemented"}

        return {
            "status": "synced",
            "message": "Pushed changes to external system",
            **result,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# =============================================================================
# Quality Tools
# =============================================================================

VALID_CONTEXT_TYPES = {"task", "prd", "sprint", "pr", "ad-hoc"}
VALID_CORRECTION_CATEGORIES = {
    "testing",
    "code-quality",
    "task-completeness",
    "integration",
    "documentation",
    "architecture",
    "security",
    "performance",
    "process",
}


@mcp.tool()
def log_correction(
    context_type: str, context_id: str, category: str, description: str
) -> dict:
    """Log a correction to .sdlc/corrections.log.

    Records fixes, mistakes, and improvements made during any workflow step
    (task work, PRD updates, sprint execution, PR feedback, ad-hoc fixes).

    Args:
        context_type: One of: task, prd, sprint, pr, ad-hoc
        context_id: Entity ID (e.g., PROJ-T00001, PROJ-P0001, PR #42, or "none" for ad-hoc)
        category: One of: testing, code-quality, task-completeness, integration,
                  documentation, architecture, security, performance, process
        description: What was corrected and why
    """
    if context_type not in VALID_CONTEXT_TYPES:
        return {
            "status": "error",
            "message": f"Invalid context_type '{context_type}'. Must be one of: {', '.join(sorted(VALID_CONTEXT_TYPES))}",
        }

    if category not in VALID_CORRECTION_CATEGORIES:
        return {
            "status": "error",
            "message": f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CORRECTION_CATEGORIES))}",
        }

    if not description or not description.strip():
        return {
            "status": "error",
            "message": "Description must not be empty.",
        }

    # Resolve project path: prefer DB project, fallback to cwd
    project_path = None
    try:
        db = get_db()
        project_id = _get_current_project_id()
        if project_id:
            project = db.get_project(project_id)
            if project:
                project_path = project["path"]
    except Exception:
        pass

    if not project_path:
        project_path = os.getcwd()

    sdlc_dir = Path(project_path) / ".sdlc"
    sdlc_dir.mkdir(parents=True, exist_ok=True)
    log_file = sdlc_dir / "corrections.log"

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry_line = f"{timestamp} | {context_type}:{context_id} | {category} | {description.strip()}\n"

    try:
        with open(log_file, "a") as f:
            f.write(entry_line)
    except Exception as e:
        return {"status": "error", "message": f"Failed to write corrections.log: {e}"}

    return {
        "status": "logged",
        "entry": {
            "timestamp": timestamp,
            "context": f"{context_type}:{context_id}",
            "category": category,
            "description": description.strip(),
        },
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


def _start_ui_server() -> subprocess.Popen | None:
    """Start the UI server in the background if not already running.

    Returns None if UI is already running or if dependencies are not available.
    The UI server lifecycle is tied to the MCP server - it will be terminated
    when the MCP server exits.

    Auto-opens the browser when the UI is ready unless A_SDLC_NO_BROWSER=1.
    """
    import threading

    global _ui_process

    already_running = _is_port_in_use(UI_PORT)
    if already_running:
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
    else:
        # Try uvx as fallback
        uvx_path = _find_executable("uvx")
        if uvx_path:
            _ui_process = subprocess.Popen(
                [uvx_path, "a-sdlc", "ui"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

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
