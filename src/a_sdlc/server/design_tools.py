"""Design document MCP tools."""

from typing import Any

import a_sdlc.server as _server

__all__ = [
    "create_design",
    "get_design",
    "delete_design",
    "list_designs",
]


@_server.mcp.tool()
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
    storage = _server.get_storage()
    pid = _server._get_current_project_id()

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
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    designs = storage.list_designs(pid)
    return {
        "status": "ok",
        "project_id": pid,
        "count": len(designs),
        "designs": designs,
    }
