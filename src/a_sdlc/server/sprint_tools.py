"""Sprint MCP tools."""
from typing import Any

import a_sdlc.server as _server

__all__ = [
    "list_sprints",
    "get_sprint",
    "create_sprint",
    "update_sprint",
    "complete_sprint",
    "delete_sprint",
    "manage_sprint_prds",
    "get_sprint_prds",
    "get_sprint_tasks",
]


@_server.mcp.tool()
def list_sprints(project_id: str | None = None) -> dict[str, Any]:
    """List sprints for a project.

    Args:
        project_id: Optional project ID. Auto-detects if not provided.

    Returns:
        List of sprint summaries.
    """
    db = _server.get_db()
    pid = project_id or _server._get_current_project_id()

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


@_server.mcp.tool()
def get_sprint(sprint_id: str) -> dict[str, Any]:
    """Get sprint details with PRD and task summary.

    Args:
        sprint_id: Sprint identifier.

    Returns:
        Sprint details including PRDs and task counts.
    """
    db = _server.get_db()
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


@_server.mcp.tool()
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
    db = _server.get_db()
    pid = project_id or _server._get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    sprint_id = db.get_next_sprint_id(pid)
    sprint = db.create_sprint(sprint_id, pid, title, goal)

    return {
        "status": "created",
        "message": f"Sprint created: {sprint_id}",
        "sprint": sprint,
    }


@_server.mcp.tool()
def update_sprint(
    sprint_id: str,
    title: str | None = None,
    goal: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Update sprint metadata (DB only).

    For completing a sprint with quality gate checks, use complete_sprint() instead.

    Args:
        sprint_id: Sprint identifier.
        title: New title (optional).
        goal: New goal (optional).
        status: New status (optional). Use "active" to start a sprint.
            Cannot set "completed" — use complete_sprint() for quality gates.

    Returns:
        Updated sprint details.
    """
    if status == "completed":
        return {
            "status": "error",
            "message": "Use complete_sprint() to complete a sprint (quality gate checks apply).",
        }

    db = _server.get_db()

    db_kwargs: dict[str, Any] = {}
    if title is not None:
        db_kwargs["title"] = title
    if goal is not None:
        db_kwargs["goal"] = goal
    if status is not None:
        db_kwargs["status"] = status

    if not db_kwargs:
        return {"status": "error", "message": "No fields to update"}

    sprint = db.update_sprint(sprint_id, **db_kwargs)

    if not sprint:
        return {"status": "not_found", "message": f"Sprint not found: {sprint_id}"}

    return {
        "status": "updated",
        "message": f"Sprint updated: {sprint_id}",
        "sprint": sprint,
    }


@_server.mcp.tool()
def complete_sprint(sprint_id: str, force: bool = False) -> dict[str, Any]:
    """Complete a sprint.

    When quality tracking is enabled, checks for unresolved gaps (orphaned
    requirements, unverified ACs, scope-drift tasks) before allowing
    completion. If gaps exist, returns a blocked status unless ``force``
    is True or the sprint has an active quality waiver.

    Args:
        sprint_id: Sprint identifier.
        force: If True, skip quality gap check and complete the sprint.

    Returns:
        Updated sprint details with final statistics, or blocked status
        with gap details when quality gates prevent completion.
    """
    db = _server.get_db()
    sprint = db.get_sprint(sprint_id)

    if not sprint:
        return {"status": "not_found", "message": f"Sprint not found: {sprint_id}"}

    # Quality gap gate (FR-037 / AC-023)
    if not force:
        try:
            quality_config = _server.load_quality_config()
            if quality_config.enabled:
                # Check for active waiver first
                waiver = _server._sprint_waivers.get(sprint_id)
                if not waiver:
                    # Run quality report to detect gaps
                    report = _server.get_quality_report("sprint", sprint_id=sprint_id)
                    if report.get("status") == "ok" and not report.get("pass", True):
                        gaps = {
                            "orphaned_requirements": report["aggregate"]["orphaned_requirements"],
                            "unverified_acs": (
                                report["aggregate"]["total_acs"]
                                - report["aggregate"]["verified_acs"]
                            ),
                            "unlinked_tasks": report["scope_drift"]["unlinked_count"],
                        }
                        has_gaps = any(v > 0 for v in gaps.values())
                        if has_gaps:
                            return {
                                "status": "blocked",
                                "reason": "unresolved_gaps",
                                "message": (
                                    f"Cannot complete {sprint_id}: quality gaps detected. "
                                    "Resolve gaps or use waive_sprint_quality() to proceed."
                                ),
                                "gaps": gaps,
                                "sprint_id": sprint_id,
                            }
        except Exception:
            # Config loading failure should not block completion (fail-open)
            pass

    # Get final task stats (derived via PRDs)
    tasks = db.list_tasks_by_sprint(sprint["project_id"], sprint_id)
    completed = sum(1 for t in tasks if t["status"] == "completed")
    total = len(tasks)

    # Get PRD stats
    prds = db.get_sprint_prds(sprint_id)

    # Auto-complete PRDs where all tasks are done
    completed_prds = []
    for prd in prds:
        if prd["status"] == "split":
            prd_tasks = db.list_tasks(prd["project_id"], prd_id=prd["id"])
            if prd_tasks and all(t["status"] == "completed" for t in prd_tasks):
                db.update_prd(prd["id"], status="completed")
                completed_prds.append(prd["id"])

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
            "prds_completed": completed_prds,
        },
    }


@_server.mcp.tool()
def delete_sprint(sprint_id: str) -> dict[str, Any]:
    """Delete a sprint.

    PRDs assigned to this sprint are unlinked (not deleted).
    Tasks under those PRDs are preserved.

    Args:
        sprint_id: Sprint identifier.

    Returns:
        Deletion status.
    """
    db = _server.get_db()

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


@_server.mcp.tool()
def manage_sprint_prds(
    action: str,
    prd_id: str,
    sprint_id: str | None = None,
) -> dict[str, Any]:
    """Add or remove a PRD from a sprint.

    When a PRD is assigned to a sprint, all tasks under that PRD
    are considered part of the sprint.

    Args:
        action: "add" to assign PRD to sprint, "remove" to move PRD to backlog.
        prd_id: PRD identifier.
        sprint_id: Sprint identifier (required for "add", ignored for "remove").

    Returns:
        Updated PRD details.
    """
    if action not in ("add", "remove"):
        return {
            "status": "error",
            "message": f"Invalid action '{action}'. Must be 'add' or 'remove'.",
        }

    db = _server.get_db()

    if action == "add":
        if not sprint_id:
            return {"status": "error", "message": "sprint_id is required for 'add' action."}

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

    else:  # action == "remove"
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


@_server.mcp.tool()
def get_sprint_prds(sprint_id: str) -> dict[str, Any]:
    """Get all PRDs assigned to a sprint.

    Args:
        sprint_id: Sprint identifier.

    Returns:
        List of PRDs in the sprint.
    """
    db = _server.get_db()
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


@_server.mcp.tool()
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
    db = _server.get_db()
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

