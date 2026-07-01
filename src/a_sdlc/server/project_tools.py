"""Project management MCP tools."""

import os
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError

import a_sdlc.server as _server

__all__ = [
    "get_context",
    "list_projects",
    "init_project",
    "create_project",
    "switch_project",
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

    # Resolve the on-disk project root from the local marker (walked up from
    # cwd). None in remote deployments where the repo is not mounted server-side.
    from a_sdlc.core.project_marker import find_marker

    marker = find_marker(os.getcwd())
    project_root = (
        Path(marker["root"]) if marker and marker.get("id") == project_id else None
    )

    # Ensure .sdlc/config.yaml exists (auto-create with defaults if missing),
    # but only when the repository is present on this host.
    if project_root is not None:
        config_path = project_root / ".sdlc" / "config.yaml"
        if not config_path.exists():
            from a_sdlc.core.init_files import generate_config_yaml

            generate_config_yaml(project_root)

    tasks = db.list_tasks(project_id)
    sprints = db.list_sprints(project_id)
    prds = db.list_prds(project_id)

    # Calculate statistics
    task_stats: dict[str, int] = {}
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
    available_artifacts = []
    artifacts_dir = (
        project_root / ".sdlc" / "artifacts" if project_root is not None else None
    )
    if artifacts_dir is not None and artifacts_dir.is_dir():
        for name in artifact_names:
            # Dual-extension transition (DD-7): .html is canonical, but
            # legacy .md artifacts still count as scanned.
            if (artifacts_dir / f"{name}.html").is_file() or (
                artifacts_dir / f"{name}.md"
            ).is_file():
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
            "root": str(project_root) if project_root is not None else None,
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

    from a_sdlc.core.init_files import generate_init_files
    from a_sdlc.core.project_marker import find_marker

    def _init_files_status(project_path: Path) -> dict[str, bool]:
        return {
            "claude_md": (project_path / "CLAUDE.md").exists(),
            "lesson_learn": (project_path / ".sdlc" / "lesson-learn.md").exists(),
            "sdlc_dir": (project_path / ".sdlc").exists(),
            "config_yaml": (project_path / ".sdlc" / "config.yaml").exists(),
            "project_marker": (project_path / ".sdlc" / "project.json").exists(),
        }

    # Already linked to a project via a local .sdlc/project.json marker?
    marker = find_marker(cwd)
    if marker:
        existing = db.get_project(marker["id"])
        if existing:
            _server._active_project_id = existing["id"]
            return {
                "status": "exists",
                "message": f"Project already initialized: {existing['name']}",
                "project": existing,
                "init_files": _init_files_status(Path(marker["root"])),
            }

    # Derive project ID from folder name
    folder_name = Path(cwd).name
    project_id = _server._slugify(folder_name)
    project_name = name or folder_name

    # Re-link an existing project (same id) that this checkout has no marker for
    # — e.g. a fresh clone on another machine. Writes the marker, no new DB row.
    existing_by_id = db.get_project(project_id)
    if existing_by_id:
        init_results = generate_init_files(
            Path(cwd),
            existing_by_id["name"],
            project_id=project_id,
            shortname=existing_by_id["shortname"],
        )
        _server._active_project_id = project_id
        return {
            "status": "linked",
            "message": (
                f"Linked current directory to existing project "
                f"'{existing_by_id['name']}' ({existing_by_id['shortname']})."
            ),
            "project": existing_by_id,
            "init_files": init_results["results"],
        }

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
        project = db.create_project(project_id, project_name, shortname)
    except ValueError as e:
        return {
            "status": "error",
            "message": str(e),
        }

    # Generate CLAUDE.md, lesson-learn.md, config.yaml, and the local marker
    init_results = generate_init_files(
        Path(cwd),
        project_name,
        project_id=project_id,
        shortname=shortname,
    )

    # Make this the active project for subsequent tool calls.
    _server._active_project_id = project_id

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
def create_project(
    name: str,
    shortname: str | None = None,
) -> dict[str, Any]:
    """Create a project without relying on the server's working directory.

    Use this in remote/centralized deployments where the MCP server runs on a
    different host than the client (Docker, cloud). Project identity comes from
    the arguments rather than ``os.getcwd()``, so it works even when the server
    cwd is ``/``. Unlike ``init_project``, this writes NO files on the server;
    the init file contents are returned for the client to create locally. The
    returned ``init_files`` include ``.sdlc/project.json`` -- the marker the
    client writes so its checkout resolves back to this project.

    Args:
        name: Human-readable project name.
        shortname: Optional 4-character uppercase project key (e.g. "PCRA").
                  Must be exactly 4 uppercase letters (A-Z). Auto-generated
                  from ``name`` when omitted. The project id is derived from
                  the shortname, so it does not depend on any directory name.

    Returns:
        Created project details, id-format examples, and ``init_files`` -- a
        list of {path, scope, content, description} specs the client should
        write into its local repository.
    """
    db = _server.get_db()

    # Validate provided shortname, or auto-generate one.
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
        shortname = db.generate_unique_shortname(name)

    # Derive the project id from the shortname so identity is independent of
    # the server's working directory.
    project_id = shortname.lower()
    if db.get_project(project_id):
        return {
            "status": "error",
            "message": f"Project id '{project_id}' already exists.",
        }

    try:
        project = db.create_project(project_id, name, shortname)
    except ValueError as e:
        return {
            "status": "error",
            "message": str(e),
        }
    except IntegrityError:
        # The pre-checks above are not atomic: a concurrent create_project
        # call can pass them and still collide on the id/shortname unique
        # constraints at commit time. Map that to a controlled conflict
        # result instead of an unhandled internal error.
        return {
            "status": "error",
            "message": (
                f"Project '{shortname}' conflicts with an existing project "
                "(id or shortname already in use)."
            ),
        }

    # Make this the active project so subsequent tool calls resolve context
    # without requiring a separate switch_project() (cwd won't match remotely).
    _server._active_project_id = project_id

    from a_sdlc.core.init_files import render_init_files

    init_files = render_init_files(name, project_id=project_id, shortname=shortname)

    return {
        "status": "created",
        "message": f"Project '{name}' created with shortname '{shortname}'.",
        "project": project,
        "id_format_examples": {
            "task": f"{shortname}-T00001",
            "sprint": f"{shortname}-S0001",
            "prd": f"{shortname}-P0001",
        },
        "init_files": init_files,
        "init_instructions": (
            "These files were NOT written on the server. Create each entry in "
            "your local repository at its 'path' (relative to the project root; "
            "'~'-prefixed paths are user-global). Skip any file that already "
            "exists so local edits are preserved. If your CLI uses a context "
            "file other than CLAUDE.md (e.g. GEMINI.md), rename accordingly."
        ),
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

    # Set in-memory active project so subsequent tool calls resolve context
    # even when cwd doesn't match the project path (e.g. Docker, cloud).
    _server._active_project_id = project_id

    return {
        "status": "ok",
        "message": f"Switched to project: {project['name']}",
        "project": project,
    }
