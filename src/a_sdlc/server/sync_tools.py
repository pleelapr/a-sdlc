"""External sync and integration MCP tools."""

from __future__ import annotations

from typing import Any

import a_sdlc.server as _server

__all__ = [
    "manage_integration",
    "import_from_linear",
    "import_from_jira",
    "manage_sync_mapping",
    "sync_sprint",
    "list_sync_mappings",
    "sync_prd",
]


@_server.mcp.tool()
def manage_integration(
    action: str,
    system: str = "",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Manage external integrations: configure, list, or remove.

    Actions:
    - configure: Set up an integration. Requires system, config.
    - list: List all configured integrations for the current project.
    - remove: Remove an integration. Requires system.

    Args:
        action: One of "configure", "list", "remove".
        system: Integration system — "linear", "jira", "confluence", or "github".
        config: System-specific configuration dict (configure only).
            Linear: {api_key, team_id, default_project?}
            Jira: {base_url, email, api_token, project_key, issue_type?}
            Confluence: {base_url, email, api_token, space_key, parent_page_id?, page_title_prefix?}
            GitHub: {token, scope?} — scope "global" stores token in ~/.config/a-sdlc/
    """
    valid_actions = ("configure", "list", "remove")
    if action not in valid_actions:
        return {
            "status": "error",
            "message": f"Invalid action '{action}'. Must be one of: {', '.join(valid_actions)}",
        }

    if action == "configure":
        if config is None:
            config = {}
        valid_systems = ("linear", "jira", "confluence", "github")
        if system not in valid_systems:
            return {
                "status": "error",
                "message": f"Unknown system '{system}'. Must be one of: {', '.join(valid_systems)}",
            }

        # GitHub special case: supports global scope and token validation
        if system == "github":
            from a_sdlc.server.github import GitHubClient, save_global_github_config

            token = config.get("token")
            if not token:
                return {"status": "error", "message": "GitHub config requires 'token'."}

            try:
                client = GitHubClient(token)
                user = client.validate_token()
            except RuntimeError as e:
                return {"status": "error", "message": str(e)}

            if config.get("scope") == "global":
                save_global_github_config({"token": token})
                return {
                    "status": "configured",
                    "message": f"GitHub integration configured globally (authenticated as @{user['login']})",
                    "system": "github",
                    "scope": "global",
                    "user": user["login"],
                }

            db = _server.get_db()
            project_id = _server._get_current_project_id()
            if not project_id:
                return {"status": "error", "message": "No project context. Run /sdlc:init first."}

            db.set_external_config(project_id, "github", {"token": token})
            return {
                "status": "configured",
                "message": f"GitHub integration configured for {project_id} (authenticated as @{user['login']})",
                "system": "github",
                "scope": "project",
                "user": user["login"],
            }

        # Standard integrations (linear, jira, confluence)
        db = _server.get_db()
        project_id = _server._get_current_project_id()

        if not project_id:
            return {"status": "error", "message": "No project context. Run /sdlc:init first."}

        # Normalize base_url if present
        stored_config = dict(config)
        if "base_url" in stored_config:
            stored_config["base_url"] = stored_config["base_url"].rstrip("/")

        db.set_external_config(project_id, system, stored_config)

        return {
            "status": "configured",
            "message": f"{system.title()} integration configured for {project_id}",
            "system": system,
        }

    elif action == "list":
        db = _server.get_db()
        project_id = _server._get_current_project_id()

        if not project_id:
            return {"status": "error", "message": "No project context. Run /sdlc:init first."}

        configs = db.list_external_configs(project_id)

        integrations = []
        for cfg_entry in configs:
            # Mask sensitive data
            cfg = cfg_entry.get("config", {})
            masked_config = {
                k: ("***" if k in ["api_key", "api_token", "token"] else v)
                for k, v in cfg.items()
            }
            integrations.append({
                "system": cfg_entry["system"],
                "config": masked_config,
                "created_at": cfg_entry["created_at"],
                "updated_at": cfg_entry["updated_at"],
            })

        return {
            "status": "ok",
            "project_id": project_id,
            "integrations": integrations,
            "count": len(integrations),
        }

    else:  # remove
        db = _server.get_db()
        project_id = _server._get_current_project_id()

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


@_server.mcp.tool()
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
    db = _server.get_db()
    project_id = _server._get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    # Check Linear is configured
    config = db.get_external_config(project_id, "linear")
    if not config:
        return {
            "status": "error",
            "message": "Linear not configured. Use configure_integration(system='linear', config={...}) first.",
        }

    # If active flag is set, import active cycle
    if active:
        try:
            sync = _server._get_sync_service()
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
        sync = _server._get_sync_service()
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


@_server.mcp.tool()
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
    db = _server.get_db()
    project_id = _server._get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    config = db.get_external_config(project_id, "jira")
    if not config:
        return {
            "status": "error",
            "message": "Jira not configured. Use configure_integration(system='jira', config={...}) first.",
        }

    # If active flag is set with board_id, import active sprint
    if active and board_id and not sprint_id:
        try:
            sync = _server._get_sync_service()
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
        sync = _server._get_sync_service()
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


@_server.mcp.tool()
def manage_sync_mapping(
    action: str,
    entity_type: str,
    entity_id: str,
    system: str | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Link or unlink a local entity (sprint or PRD) to/from an external system.

    Args:
        action: "link" to create mapping, "unlink" to remove mapping.
        entity_type: "sprint" or "prd".
        entity_id: Local sprint or PRD identifier.
        system: External system ('linear' or 'jira'). Required for "link".
        external_id: External sprint/cycle/issue ID. Required for "link".

    Returns:
        Link/unlink status.
    """
    if action not in ("link", "unlink"):
        return {
            "status": "error",
            "message": f"Invalid action '{action}'. Must be 'link' or 'unlink'.",
        }

    if entity_type not in ("sprint", "prd"):
        return {
            "status": "error",
            "message": f"Invalid entity_type '{entity_type}'. Must be 'sprint' or 'prd'.",
        }

    project_id = _server._get_current_project_id()
    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    if action == "link":
        if not system:
            return {"status": "error", "message": "system is required for 'link' action."}
        if not external_id:
            return {"status": "error", "message": "external_id is required for 'link' action."}
        if system not in ["linear", "jira"]:
            return {"status": "error", "message": f"Unknown system: {system}. Use 'linear' or 'jira'."}

        try:
            sync = _server._get_sync_service()
            if entity_type == "sprint":
                sync.link_sprint(project_id, entity_id, system, external_id)
            else:
                sync.link_prd(project_id, entity_id, system, external_id)

            return {
                "status": "linked",
                "message": f"{entity_type.title()} {entity_id} linked to {system} {external_id}",
                f"{entity_type}_id": entity_id,
                "system": system,
                "external_id": external_id,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    else:  # action == "unlink"
        try:
            sync = _server._get_sync_service()
            if entity_type == "sprint":
                unlinked = sync.unlink_sprint(entity_id)
            else:
                unlinked = sync.unlink_prd(entity_id)

            if unlinked:
                return {
                    "status": "unlinked",
                    "message": f"{entity_type.title()} {entity_id} unlinked from external system",
                    f"{entity_type}_id": entity_id,
                }
            else:
                return {
                    "status": "not_linked",
                    "message": f"{entity_type.title()} {entity_id} was not linked to any external system",
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}


@_server.mcp.tool()
def sync_sprint(
    sprint_id: str,
    direction: str = "bidirectional",
    strategy: str = "local-wins",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync between local sprint and external system.

    Args:
        sprint_id: Local sprint identifier.
        direction: Sync direction — "bidirectional" (default), "push", or "pull".
        strategy: Conflict resolution for bidirectional ('local-wins' or 'external-wins').
        dry_run: If True, only report what would change (bidirectional only).

    Returns:
        Sync results.
    """
    if direction not in ("bidirectional", "push", "pull"):
        return {
            "status": "error",
            "message": f"Invalid direction '{direction}'. Must be 'bidirectional', 'push', or 'pull'.",
        }

    project_id = _server._get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    if direction == "bidirectional":
        if strategy not in ["local-wins", "external-wins"]:
            return {
                "status": "error",
                "message": "Strategy must be 'local-wins' or 'external-wins'.",
            }

        try:
            sync = _server._get_sync_service()
            result = sync.bidirectional_sync(project_id, sprint_id, strategy, dry_run)
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # Push or pull
    db = _server.get_db()
    linear_mapping = db.get_sync_mapping("sprint", sprint_id, "linear")
    jira_mapping = db.get_sync_mapping("sprint", sprint_id, "jira")

    if not linear_mapping and not jira_mapping:
        return {
            "status": "error",
            "message": f"Sprint {sprint_id} is not linked to any external system. Use manage_sync_mapping first.",
        }

    try:
        sync = _server._get_sync_service()

        if direction == "pull":
            if linear_mapping:
                result = sync.sync_sprint_from_linear(project_id, sprint_id)
            else:
                result = sync.sync_sprint_from_jira(project_id, sprint_id)
            msg = "Pulled changes from external system"
        else:  # push
            if linear_mapping:
                result = sync.sync_sprint_to_linear(project_id, sprint_id)
            else:
                result = sync.sync_sprint_to_jira(project_id, sprint_id)
            msg = "Pushed changes to external system"

        return {
            "status": "synced",
            "message": msg,
            **result,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@_server.mcp.tool()
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
    db = _server.get_db()

    mappings = db.list_sync_mappings(entity_type, external_system)

    return {
        "status": "ok",
        "count": len(mappings),
        "mappings": mappings,
    }



@_server.mcp.tool()
def sync_prd(
    prd_id: str,
    direction: str = "bidirectional",
    strategy: str = "local-wins",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync between local PRD and external issue.

    Args:
        prd_id: Local PRD identifier.
        direction: Sync direction — "bidirectional" (default), "push", or "pull".
        strategy: Conflict resolution for bidirectional ('local-wins' or 'external-wins').
        dry_run: If True, only report what would change (bidirectional only).

    Returns:
        Sync results.
    """
    if direction not in ("bidirectional", "push", "pull"):
        return {
            "status": "error",
            "message": f"Invalid direction '{direction}'. Must be 'bidirectional', 'push', or 'pull'.",
        }

    project_id = _server._get_current_project_id()

    if not project_id:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    if direction == "bidirectional":
        if strategy not in ["local-wins", "external-wins"]:
            return {
                "status": "error",
                "message": "Strategy must be 'local-wins' or 'external-wins'.",
            }

        try:
            sync = _server._get_sync_service()
            result = sync.bidirectional_sync_prd(project_id, prd_id, strategy, dry_run)
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # Push or pull
    db = _server.get_db()
    linear_mapping = db.get_sync_mapping("prd", prd_id, "linear")
    jira_mapping = db.get_sync_mapping("prd", prd_id, "jira")

    if not linear_mapping and not jira_mapping:
        return {
            "status": "error",
            "message": f"PRD {prd_id} is not linked to any external system. Use manage_sync_mapping first.",
        }

    try:
        sync = _server._get_sync_service()

        if direction == "pull":
            if jira_mapping:
                result = sync.sync_prd_from_jira(project_id, prd_id)
            else:
                return {"status": "error", "message": "Linear PRD sync not yet implemented"}
            msg = "Pulled changes from external system"
        else:  # push
            if jira_mapping:
                result = sync.sync_prd_to_jira(project_id, prd_id)
            else:
                return {"status": "error", "message": "Linear PRD sync not yet implemented"}
            msg = "Pushed changes to external system"

        return {
            "status": "synced",
            "message": msg,
            **result,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
