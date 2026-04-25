"""Data access proxy for MCP tools.

Provides a transparent proxy around the Database class that enforces
an explicit allowlist of permitted operations and logs write activity.
"""

import logging
from typing import Any

_logger = logging.getLogger("a-sdlc-server")

READ_OPS = frozenset({
    "check_agent_permission",
    "compute_agent_performance",
    "get_ac_verifications",
    "get_active_claim",
    "get_agent",
    "get_agent_budget",
    "get_agent_messages",
    "get_agent_performance",
    "get_agent_permissions",
    "get_available_work",
    "get_challenge_rounds",
    "get_challenge_status",
    "get_coverage_stats",
    "get_external_config",
    "get_latest_approved_review",
    "get_next_agent_id",
    "get_next_prd_id",
    "get_next_sprint_id",
    "get_next_task_id",
    "get_next_worktree_id",
    "get_org_overview",
    "get_orphaned_requirements",
    "get_prd",
    "get_project",
    "get_project_by_path",
    "get_project_by_shortname",
    "get_requirement",
    "get_requirement_tasks",
    "get_requirements",
    "get_reviews_for_task",
    "get_sprint",
    "get_sprint_prds",
    "get_sync_mapping",
    "get_sync_mapping_by_external",
    "get_task",
    "get_task_requirements",
    "get_team_composition",
    "get_unverified_acs",
    "get_worktree_by_prd",
    "is_shortname_available",
    "generate_unique_shortname",
    "validate_shortname",
    "list_agents",
    "list_claims_by_agent",
    "list_external_configs",
    "list_prds",
    "list_projects",
    "list_sprints",
    "list_sync_mappings",
    "list_tasks",
    "list_tasks_by_sprint",
    "list_worktrees",
})

WRITE_OPS = frozenset({
    "append_audit_log",
    "assign_prd_to_sprint",
    "claim_task",
    "create_agent",
    "create_agent_budget",
    "create_prd",
    "create_project",
    "create_review",
    "create_sprint",
    "create_sync_mapping",
    "create_task",
    "create_worktree",
    "delete_external_config",
    "delete_prd",
    "delete_sprint",
    "delete_sync_mapping",
    "delete_task",
    "increment_agent_budget",
    "link_task_requirement",
    "record_ac_verification",
    "release_task",
    "retire_agent",
    "send_agent_message",
    "set_external_config",
    "suspend_agent",
    "update_prd",
    "update_project_accessed",
    "update_project_path",
    "update_sprint",
    "update_sync_mapping",
    "update_task",
    "update_worktree",
    "upsert_requirement",
})

_ALLOWED_OPS = READ_OPS | WRITE_OPS


class MCPDataAccess:
    """Transparent proxy that restricts MCP tools to allowed Database methods.

    All attribute access is delegated to the wrapped Database instance,
    but only methods in the allowlist can be called.  Write operations
    are logged at DEBUG level for monitoring.

    Methods are cached on first access to avoid repeated __getattr__
    overhead.
    """

    __slots__ = ("_db", "_method_cache")

    def __init__(self, db: Any) -> None:
        object.__setattr__(self, "_db", db)
        object.__setattr__(self, "_method_cache", {})

    def __getattr__(self, name: str) -> Any:
        # Dunder and private attributes bypass the allowlist
        if name.startswith("_"):
            raise AttributeError(
                f"MCPDataAccess does not expose private attribute '{name}'"
            )

        cache = object.__getattribute__(self, "_method_cache")
        if name in cache:
            return cache[name]

        if name not in _ALLOWED_OPS:
            raise AttributeError(
                f"MCPDataAccess does not allow '{name}' — "
                f"method is not in the MCP allowlist"
            )

        db = object.__getattribute__(self, "_db")
        attr = getattr(db, name)

        if name in WRITE_OPS:
            def _monitored(*args: Any, **kwargs: Any) -> Any:
                _logger.debug(
                    "MCP write: %s(args=%d, kwargs=%s)",
                    name,
                    len(args),
                    list(kwargs.keys()),
                )
                return attr(*args, **kwargs)

            cache[name] = _monitored
            return _monitored

        # Read op — cache raw method
        cache[name] = attr
        return attr

    def __repr__(self) -> str:
        db = object.__getattribute__(self, "_db")
        return f"MCPDataAccess(db={db!r})"
