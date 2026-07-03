"""Task MCP tools."""
from pathlib import Path
from typing import Any

import a_sdlc.server as _server

__all__ = [
    "list_tasks",
    "get_task",
    "create_task",
    "update_task",
    "delete_task",
]


@_server.mcp.tool()
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
    db = _server.get_db()
    pid = project_id or _server._get_current_project_id()

    if not pid:
        return {"status": "error", "message": _server.NO_PROJECT_MESSAGE}

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


@_server.mcp.tool()
def get_task(task_id: str, include_content: bool = True) -> dict[str, Any]:
    """Get task details, optionally with file content.

    Args:
        task_id: Task identifier.
        include_content: If True (default), include full markdown content.
            Set to False to get metadata + file_path only (saves tokens).

    Returns:
        Task metadata and optionally content from markdown file.
    """
    db = _server.get_db()
    content_mgr = _server.get_storage().content_mgr

    task = db.get_task(task_id)
    if not task:
        return {"status": "not_found", "message": f"Task not found: {task_id}"}

    task_with_content = dict(task)

    if include_content:
        # Read content from file
        content = None
        if task.get("file_path"):
            content = content_mgr.read_content(Path(task["file_path"]))
        else:
            content = content_mgr.read_task(task["project_id"], task_id)

        task_with_content["content"] = content

        # Parse content for description and data
        if content:
            parsed = content_mgr.parse_task_content(content)
            task_with_content["description"] = parsed.get("description", "")
            if "dependencies" in parsed:
                task_with_content["data"] = {"dependencies": parsed["dependencies"]}
    else:
        task_with_content["content"] = ""
        task_with_content["description"] = ""
        task_with_content["data"] = None

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


@_server.mcp.tool()
def create_task(
    title: str,
    project_id: str | None = None,
    prd_id: str | None = None,
    priority: str = "medium",
    component: str | None = None,
    data: dict[str, Any] | None = None,
    content: str | None = None,
) -> dict[str, Any]:
    """Create a new task (metadata + content file).

    Creates a DB record and a content file. When `content` is provided,
    writes it through the configured backend (local filesystem or S3).
    Otherwise creates a skeleton file. Returns file_path for reference.

    Args:
        title: Task title.
        project_id: Optional project ID. Auto-detects if not provided.
        prd_id: Optional parent PRD. Task inherits sprint from PRD.
        priority: Task priority (low, medium, high, critical).
        component: Optional component/module name.
        data: Optional additional structured data (including dependencies).
        content: Optional task markdown content. When provided, written
            through the configured content backend (works with S3/Docker).
            When omitted, creates a skeleton file.

    Returns:
        Created task details with file_path for reference.

    Note:
        Tasks no longer have direct sprint_id. To assign a task to a sprint,
        set its prd_id to a PRD that belongs to that sprint.
    """
    db = _server.get_db()
    content_mgr = _server.get_storage().content_mgr
    pid = project_id or _server._get_current_project_id()

    if not pid:
        return {"status": "error", "message": _server.NO_PROJECT_MESSAGE}

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

    result = {
        "status": "created",
        "message": f"Task created: {task_id}",
        "task": dict(task),
        "file_path": str(file_path),
    }

    # Write content through backend if provided
    if content is not None:
        content_mgr.write_task_content(pid, task_id, content)
        result["content_written"] = True

    return result


@_server.mcp.tool()
def update_task(
    task_id: str,
    title: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    component: str | None = None,
    prd_id: str | None = None,
    content: str | None = None,
) -> dict[str, Any]:
    """Update task metadata and/or content.

    Updates metadata fields in the database and optionally writes new content
    through the configured content backend (local filesystem or S3).

    Args:
        task_id: Task identifier.
        title: New title (optional).
        status: New status (optional).
        priority: New priority (optional).
        component: New component (optional).
        prd_id: New parent PRD (optional). Use empty string to unassign.
        content: New task markdown content (optional). When provided, written
            through the configured content backend. Supports read-modify-write:
            get_task() -> modify content -> update_task(content=new_content).

    Returns:
        Updated task details.

    Note:
        To change a task's sprint, update its parent PRD's sprint_id
        or move the task to a different PRD.
    """
    db = _server.get_db()

    task = db.get_task(task_id)
    if not task:
        return {"status": "not_found", "message": f"Task not found: {task_id}"}

    # Hard gate: review enforcement
    if status == "completed":
        review_config = _server.load_review_config()
        if review_config.enabled:
            latest = db.get_latest_approved_review(task_id)
            if not latest:
                return {
                    "status": "error",
                    "message": f"Cannot complete {task_id}: no approved review evidence. "
                    "Submit review via submit_review(reviewer_type='self'|'subagent') first, "
                    "or disable review in .sdlc/config.yaml.",
                }

    # AC verification gate
    if status == "completed":
        try:
            quality_config = _server.load_quality_config()
            if quality_config.enabled and quality_config.ac_gate:
                unverified = db.get_unverified_acs(task_id)
                if unverified:
                    return {
                        "status": "blocked",
                        "reason": "unverified_acceptance_criteria",
                        "message": f"Cannot complete {task_id}: {len(unverified)} unverified acceptance criteria.",
                        "unverified": [
                            {"ac_id": ac["id"], "summary": ac["summary"], "depth": ac["depth"]}
                            for ac in unverified
                        ],
                    }
        except Exception:
            # Config loading failure should not block task completion (fail-open)
            pass

    # Write content through backend if provided
    content_written = False
    if content is not None:
        content_mgr = _server.get_storage().content_mgr
        content_mgr.write_task_content(task["project_id"], task_id, content)
        content_written = True

    # Build update kwargs for database
    db_kwargs: dict[str, str | None] = {}
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

    if not db_kwargs and not content_written:
        return {"status": "error", "message": "No fields to update"}

    updated_task = db.update_task(task_id, **db_kwargs) if db_kwargs else task

    # REM-003: Audit log when task is marked completed
    if status == "completed":
        project_id = _server._get_current_project_id()
        if project_id:
            db.append_audit_log(
                project_id,
                "task_completed",
                "success",
                target_entity=task_id,
            )

    result = {
        "status": "updated",
        "message": f"Task updated: {task_id}",
        "task": updated_task,
    }
    if content_written:
        result["content_written"] = True

    return result



@_server.mcp.tool()
def delete_task(task_id: str) -> dict[str, Any]:
    """Delete a task.

    Args:
        task_id: Task identifier.

    Returns:
        Deletion status.
    """
    db = _server.get_db()
    content_mgr = _server.get_storage().content_mgr

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
