"""Design document MCP tools."""

from typing import Any

import a_sdlc.server as _server

__all__ = [
    "create_design",
    "get_design",
    "update_design",
    "delete_design",
    "list_designs",
]


@_server.mcp.tool()
def create_design(prd_id: str, content: str | None = None) -> dict[str, Any]:
    """Create a design document for a PRD.

    Each PRD can have one design document (ADR-style architecture decision record).
    Creates a DB record and a content file. When `content` is provided,
    writes it through the configured backend (local filesystem or S3).
    Otherwise creates an empty file. Returns file_path for reference.

    Args:
        prd_id: Parent PRD identifier.
        content: Optional design document markdown content. When provided,
            written through the configured content backend (works with S3/Docker).
            When omitted, creates an empty file.

    Returns:
        Created design document details with file_path for reference.
    """
    storage = _server.get_storage()
    pid = _server._get_current_project_id()

    if not pid:
        return {"status": "error", "message": _server.NO_PROJECT_MESSAGE}

    # Validate PRD exists
    prd = storage.get_prd(prd_id)
    if not prd:
        return {"status": "not_found", "message": f"PRD not found: {prd_id}"}

    # Check for existing design
    existing = storage.get_design_by_prd(prd_id)
    if existing:
        return {"status": "error", "message": f"Design already exists for PRD {prd_id}. Use update_design() instead."}

    design = storage.create_design(prd_id=prd_id, project_id=pid)

    result = {
        "status": "created",
        "message": f"Design document created for PRD {prd_id}",
        "design": design,
        "file_path": design.get("file_path"),
    }

    # Write content through backend if provided
    if content is not None:
        storage.content_mgr.write_design(pid, prd_id, content)
        result["content_written"] = True

    return result


@_server.mcp.tool()
def get_design(prd_id: str) -> dict[str, Any]:
    """Get design document for a PRD with full content.

    Args:
        prd_id: PRD identifier.

    Returns:
        Design document with metadata and content.
    """
    storage = _server.get_storage()
    design = storage.get_design_by_prd(prd_id)

    if not design:
        return {"status": "not_found", "message": f"No design document found for PRD: {prd_id}"}

    return {
        "status": "ok",
        "design": design,
    }


@_server.mcp.tool()
def update_design(prd_id: str, content: str) -> dict[str, Any]:
    """Update design document content.

    Writes new content through the configured content backend
    (local filesystem or S3). Supports read-modify-write:
    get_design() -> modify content -> update_design(content=new_content).

    Args:
        prd_id: PRD identifier (design documents have 1:1 relationship with PRDs).
        content: New design document markdown content.

    Returns:
        Update status.
    """
    storage = _server.get_storage()

    design = storage.get_design_by_prd(prd_id)
    if not design:
        return {"status": "not_found", "message": f"No design document found for PRD: {prd_id}"}

    storage.content_mgr.write_design(design["project_id"], prd_id, content)

    return {
        "status": "updated",
        "message": f"Design document updated for PRD {prd_id}",
        "content_written": True,
    }


@_server.mcp.tool()
def delete_design(prd_id: str) -> dict[str, Any]:
    """Delete a design document.

    Args:
        prd_id: PRD identifier.

    Returns:
        Deletion status.
    """
    storage = _server.get_storage()
    deleted = storage.delete_design(prd_id)

    if not deleted:
        return {"status": "not_found", "message": f"No design document found for PRD: {prd_id}"}

    return {
        "status": "deleted",
        "message": f"Design document deleted for PRD {prd_id}",
    }


@_server.mcp.tool()
def list_designs(project_id: str | None = None) -> dict[str, Any]:
    """List design documents for a project.

    Args:
        project_id: Optional project ID. Auto-detects if not provided.

    Returns:
        List of design document summaries (metadata only).
    """
    storage = _server.get_storage()
    pid = project_id or _server._get_current_project_id()

    if not pid:
        return {"status": "error", "message": _server.NO_PROJECT_MESSAGE}

    designs = storage.list_designs(pid)
    return {
        "status": "ok",
        "project_id": pid,
        "count": len(designs),
        "designs": designs,
    }
