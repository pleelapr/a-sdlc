"""Project management MCP tools."""

import os
from pathlib import Path
from typing import Any

import a_sdlc.server as _server

__all__ = [
    "get_context",
    "list_projects",
    "init_project",
    "switch_project",
    "relocate_project",
]


@_server.mcp.tool()
def get_context() -> dict[str, Any]:
    """Get current project context and summary.

    Returns the active project with task/sprint statistics.
    Auto-detects project from current working directory.
    """
    db = _server.get_db()
    project_id = _server._get_current_project_id()

    if not project_id:
        return {
            "status": "no_project",
            "message": "No project found for current directory. Run /sdlc:init first.",
            "cwd": os.getcwd(),
        }

    project = db.get_project(project_id)

    # Ensure .sdlc/config.yaml exists (auto-create with defaults if missing)
    project_path = Path(project["path"])
    config_path = project_path / ".sdlc" / "config.yaml"
    if not config_path.exists():
        from a_sdlc.core.init_files import generate_config_yaml

        generate_config_yaml(project_path)

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


@_server.mcp.tool()
def list_projects() -> list[dict[str, Any]]:
    """List all known projects.

    Returns projects ordered by last accessed time with shortname for each.
    """
    db = _server.get_db()
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


@_server.mcp.tool()
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
    db = _server.get_db()
    cwd = os.getcwd()

    # Check if already exists
    existing = db.get_project_by_path(cwd)
    if existing:
        project_path = Path(cwd)
        has_claude_md = (project_path / "CLAUDE.md").exists()
        has_lesson_learn = (project_path / ".sdlc" / "lesson-learn.md").exists()
        has_sdlc_dir = (project_path / ".sdlc").exists()
        has_config_yaml = (project_path / ".sdlc" / "config.yaml").exists()

        return {
            "status": "exists",
            "message": f"Project already initialized: {existing['name']}",
            "project": existing,
            "init_files": {
                "claude_md": has_claude_md,
                "lesson_learn": has_lesson_learn,
                "sdlc_dir": has_sdlc_dir,
                "config_yaml": has_config_yaml,
            },
        }

    # Generate project ID from folder name
    folder_name = Path(cwd).name
    project_id = _server._slugify(folder_name)
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


@_server.mcp.tool()
def switch_project(project_id: str) -> dict[str, Any]:
    """Switch to a different project context.

    Args:
        project_id: ID of the project to switch to.

    Returns:
        Project details if found.
    """
    db = _server.get_db()
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


@_server.mcp.tool()
def relocate_project(shortname: str) -> dict[str, Any]:
    """Re-link an existing project to the current directory.

    Use this when you've moved a repository to a new location and want to
    reconnect it to its existing project data (PRDs, tasks, sprints).

    Args:
        shortname: The 4-character project shortname to relocate.

    Returns:
        Updated project details.
    """
    db = _server.get_db()
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
