"""PRD MCP tools."""

import re
from pathlib import Path
from typing import Any

import a_sdlc.server as _server

__all__ = ["list_prds", "get_prd", "create_prd", "update_prd", "delete_prd", "split_prd"]


@_server.mcp.tool()
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
    db = _server.get_db()
    pid = project_id or _server._get_current_project_id()

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


@_server.mcp.tool()
def get_prd(prd_id: str, include_content: bool = True) -> dict[str, Any]:
    """Get PRD details, optionally with file content.

    Args:
        prd_id: PRD identifier.
        include_content: If True (default), include full markdown content.
            Set to False to get metadata + file_path only (saves tokens).

    Returns:
        PRD metadata and optionally content from markdown file.
    """
    db = _server.get_db()
    content_mgr = _server.get_content_manager()

    prd = db.get_prd(prd_id)
    if not prd:
        return {"status": "not_found", "message": f"PRD not found: {prd_id}"}

    prd_with_content = dict(prd)

    if include_content:
        # Read content from file
        content = None
        if prd.get("file_path"):
            content = content_mgr.read_content(Path(prd["file_path"]))
        else:
            # Try to find by project_id and prd_id
            content = content_mgr.read_prd(prd["project_id"], prd_id)
        prd_with_content["content"] = content
    else:
        prd_with_content["content"] = ""

    return {
        "status": "ok",
        "prd": prd_with_content,
    }


@_server.mcp.tool()
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
    db = _server.get_db()
    content_mgr = _server.get_content_manager()
    pid = project_id or _server._get_current_project_id()

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


@_server.mcp.tool()
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
    db = _server.get_db()

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


@_server.mcp.tool()
def delete_prd(prd_id: str) -> dict[str, Any]:
    """Delete a PRD.

    Args:
        prd_id: PRD identifier.

    Returns:
        Deletion status.
    """
    db = _server.get_db()
    content_mgr = _server.get_content_manager()

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


@_server.mcp.tool()
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
    db = _server.get_db()
    content_mgr = _server.get_content_manager()
    pid = _server._get_current_project_id()

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
            result["note"] = (
                f"{files_reused} task file(s) were pre-written and reused"
            )

        # --- Auto-linkage: link tasks to requirements via traces_to ---
        has_traces = any(spec.get("traces_to") for spec in task_specs)
        if has_traces:
            # Ensure requirements are parsed for this PRD
            existing_reqs = db.get_requirements(prd_id)
            if not existing_reqs:
                # Auto-parse requirements from PRD content
                prd_data = db.get_prd(prd_id)
                prd_file = (
                    prd_data.get("file_path", "") if prd_data else ""
                )
                if prd_file and Path(prd_file).exists():
                    prd_content = Path(prd_file).read_text(
                        encoding="utf-8"
                    )
                    _server._auto_parse_requirements(db, prd_id, prd_content)
                    existing_reqs = db.get_requirements(prd_id)

            # Build a lookup: req_number -> requirement ID
            req_lookup: dict[str, str] = {}
            for req in existing_reqs:
                req_lookup[req["req_number"]] = req["id"]

            # Link each task to its traced requirements
            link_count = 0
            link_errors: list[str] = []
            for i, spec in enumerate(task_specs):
                traces = spec.get("traces_to")
                if not traces:
                    continue
                task_id_for_link = created_tasks[i]["id"]
                for ref in traces:
                    # Resolve: try req_number lookup, then full ID
                    req_id = req_lookup.get(ref) or f"{prd_id}:{ref}"
                    existing_req = db.get_requirement(req_id)
                    if existing_req:
                        db.link_task_requirement(req_id, task_id_for_link)
                        link_count += 1
                    else:
                        link_errors.append(
                            f"{task_id_for_link}:{ref}"
                        )

            result["linkage"] = {
                "linked": link_count,
                "errors": link_errors,
            }

            # Compute coverage stats
            coverage = db.get_coverage_stats(prd_id)
            total = coverage.get("total", 0)
            linked = coverage.get("linked", 0)
            orphaned_reqs = db.get_orphaned_requirements(prd_id)
            linkage_pct = (
                (linked / total * 100) if total > 0 else 100.0
            )
            result["coverage"] = {
                "total": total,
                "linked": linked,
                "orphaned": [
                    r["req_number"] for r in orphaned_reqs
                ],
                "linkage_pct": round(linkage_pct, 1),
            }

            # Cross-PRD integration recommendations
            prd_ref_pattern = re.compile(r"[A-Z]{2,6}-P\d{4}")
            recommendations: list[dict[str, str]] = []
            for req in existing_reqs:
                summary = req.get("summary", "")
                matches = prd_ref_pattern.findall(summary)
                for ref_prd in matches:
                    if ref_prd != prd_id:
                        recommendations.append(
                            {
                                "requirement": req["req_number"],
                                "references_prd": ref_prd,
                                "recommendation": (
                                    f"Requirement {req['req_number']} "
                                    f"references {ref_prd}. Consider "
                                    f"cross-PRD dependency coordination."
                                ),
                            }
                        )
            if recommendations:
                result["integration_recommendations"] = (
                    recommendations
                )

        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create tasks: {str(e)}",
        }
