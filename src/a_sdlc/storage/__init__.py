"""
Storage adapter for a-sdlc.

This module provides backward-compatible storage interface by wrapping:
- Database (SQLite): Metadata and file path references
- ContentManager: Markdown content files

The HybridStorage class provides the same interface as the old FileStorage
to minimize changes in CLI and UI code.
"""

import os
import platform
from pathlib import Path
from typing import Any


def get_data_dir() -> Path:
    """Get platform-specific data directory.

    Returns:
        Path: ~/.a-sdlc/ on macOS/Linux, %LOCALAPPDATA%/a-sdlc/ on Windows
    """
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "a-sdlc"
    else:
        return Path.home() / ".a-sdlc"


# Lazy imports to avoid circular dependencies
def _get_database_class():
    from a_sdlc.core.database import Database
    return Database


def _get_content_manager_class():
    from a_sdlc.core.content import ContentManager
    return ContentManager


def _get_db_instance():
    from a_sdlc.core.database import get_db
    return get_db()


def _get_content_manager_instance():
    from a_sdlc.core.content import get_content_manager
    return get_content_manager()


class HybridStorage:
    """Hybrid storage adapter combining Database and ContentManager.

    Provides backward-compatible interface for CLI and UI while using
    the new hybrid storage architecture internally.
    """

    def __init__(
        self,
        db: Any = None,
        content_mgr: Any = None,
        base_path: "Path | None" = None,
    ):
        """Initialize hybrid storage.

        Args:
            db: Database instance (default: global instance)
            content_mgr: ContentManager instance (default: global instance)
            base_path: Custom base path for test isolation (creates new instances)
        """
        if base_path is not None:
            # Create custom instances for test isolation
            Database = _get_database_class()  # noqa: N806
            ContentManager = _get_content_manager_class()  # noqa: N806
            self._base_path = Path(base_path)
            self._base_path.mkdir(parents=True, exist_ok=True)
            self._db = Database(db_path=self._base_path / "data.db")
            self._content_mgr = ContentManager(base_path=self._base_path / "content")
            # Ensure templates directory exists
            self.templates_dir.mkdir(parents=True, exist_ok=True)
        else:
            self._base_path = get_data_dir()
            self._db = db or _get_db_instance()
            self._content_mgr = content_mgr or _get_content_manager_instance()

    @property
    def db(self):
        """Get the underlying Database instance."""
        return self._db

    @property
    def content_mgr(self):
        """Get the underlying ContentManager instance."""
        return self._content_mgr

    @property
    def base_path(self) -> Path:
        """Get base data directory."""
        return self._base_path

    @property
    def templates_dir(self) -> Path:
        """Get templates directory."""
        return self.base_path / "templates"

    # =========================================================================
    # Project Operations
    # =========================================================================

    def create_project(
        self,
        project_id: str,
        name: str,
        path: str,
        shortname: str | None = None,
    ) -> dict[str, Any]:
        """Create a new project.

        Args:
            project_id: Unique project identifier (slug)
            name: Display name
            path: Filesystem path to project root
            shortname: 4-character uppercase project key (auto-generated if not provided)
        """
        return self._db.create_project(project_id, name, path, shortname)

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Get project by ID."""
        return self._db.get_project(project_id)

    def get_project_by_path(self, path: str) -> dict[str, Any] | None:
        """Get project by filesystem path."""
        return self._db.get_project_by_path(path)

    def get_project_by_shortname(self, shortname: str) -> dict[str, Any] | None:
        """Get project by shortname."""
        return self._db.get_project_by_shortname(shortname)

    def update_project_path(self, project_id: str, new_path: str) -> dict[str, Any] | None:
        """Update project filesystem path (for relocating projects)."""
        return self._db.update_project_path(project_id, new_path)

    def list_projects(self) -> list[dict[str, Any]]:
        """List all projects."""
        return self._db.list_projects()

    def get_most_recent_project(self) -> dict[str, Any] | None:
        """Get most recently accessed project."""
        return self._db.get_most_recent_project()

    def get_all_projects_with_stats(self) -> list[dict[str, Any]]:
        """Get all projects with aggregated task/PRD/sprint counts."""
        return self._db.get_all_projects_with_stats()

    def update_project_accessed(self, project_id: str) -> None:
        """Update project's last_accessed timestamp."""
        self._db.update_project_accessed(project_id)

    def delete_project(self, project_id: str) -> bool:
        """Delete a project and all associated data."""
        # Delete content files first
        self._content_mgr.delete_project_content(project_id)
        # Then delete from database
        return self._db.delete_project(project_id)

    # =========================================================================
    # PRD Operations
    # =========================================================================

    def create_prd(
        self,
        prd_id: str,
        project_id: str,
        title: str,
        status: str = "draft",
        source: str | None = None,
        sprint_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new PRD with skeleton file."""
        # Write skeleton file (just title header)
        file_path = self._content_mgr.write_prd(project_id, prd_id, title, "")

        # Register in database
        prd = self._db.create_prd(
            prd_id=prd_id,
            project_id=project_id,
            title=title,
            file_path=str(file_path),
            status=status,
            source=source,
            sprint_id=sprint_id,
        )

        prd_result = dict(prd)
        prd_result["file_path"] = str(file_path)
        return prd_result

    def get_prd(self, prd_id: str, include_content: bool = True) -> dict[str, Any] | None:
        """Get PRD by ID, optionally with content.

        Args:
            prd_id: PRD identifier.
            include_content: If True (default), read and include file content.
                If False, return metadata + file_path only (saves tokens).
        """
        prd = self._db.get_prd(prd_id)
        if not prd:
            return None

        prd_with_content = dict(prd)

        if include_content:
            # Read content from file
            content = None
            if prd.get("file_path"):
                content = self._content_mgr.read_content(Path(prd["file_path"]))
            elif prd.get("project_id"):
                content = self._content_mgr.read_prd(prd["project_id"], prd_id)
            prd_with_content["content"] = content or ""
        else:
            prd_with_content["content"] = ""

        return prd_with_content

    def list_prds(
        self,
        project_id: str,
        sprint_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List PRDs for a project."""
        return self._db.list_prds(project_id, sprint_id=sprint_id, status=status)

    def update_prd(self, prd_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update PRD metadata (DB only, no file operations).

        Content changes should be made by editing the file directly.
        """
        prd = self._db.get_prd(prd_id)
        if not prd:
            return None

        # Remove content if accidentally passed — it's no longer handled here
        kwargs.pop("content", None)

        updated = self._db.update_prd(prd_id, **kwargs)
        if updated:
            # Read content from file for response
            content = self._content_mgr.read_prd(updated["project_id"], prd_id)
            updated_with_content = dict(updated)
            updated_with_content["content"] = content or ""
            return updated_with_content
        return None

    def delete_prd(self, prd_id: str) -> bool:
        """Delete a PRD."""
        prd = self._db.get_prd(prd_id)
        if not prd:
            return False

        # Delete content file
        self._content_mgr.delete_prd(prd["project_id"], prd_id)

        # Delete from database
        return self._db.delete_prd(prd_id)

    # =========================================================================
    # Task Operations
    # =========================================================================

    def create_task(
        self,
        task_id: str,
        project_id: str,
        title: str,
        status: str = "pending",
        priority: str = "medium",
        prd_id: str | None = None,
        component: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new task with skeleton file."""
        # Write skeleton file
        file_path = self._content_mgr.write_task(
            project_id=project_id,
            task_id=task_id,
            title=title,
            description="",
            priority=priority,
            status=status,
            component=component,
            prd_id=prd_id,
            data=data,
        )

        # Register in database
        task = self._db.create_task(
            task_id=task_id,
            project_id=project_id,
            title=title,
            file_path=str(file_path),
            status=status,
            priority=priority,
            prd_id=prd_id,
            component=component,
        )

        task_result = dict(task)
        task_result["file_path"] = str(file_path)
        return task_result

    def get_task(self, task_id: str, include_content: bool = True) -> dict[str, Any] | None:
        """Get task by ID, optionally with content.

        Args:
            task_id: Task identifier.
            include_content: If True (default), read and include file content.
                If False, return metadata + file_path only (saves tokens).
        """
        task = self._db.get_task(task_id)
        if not task:
            return None

        task_with_content = dict(task)

        if include_content:
            # Read content from file
            content = None
            if task.get("file_path"):
                content = self._content_mgr.read_content(Path(task["file_path"]))
            elif task.get("project_id"):
                content = self._content_mgr.read_task(task["project_id"], task_id)

            # Add full raw content (like PRD handling)
            task_with_content["content"] = content or ""

            # Parse content for description and data (kept for backward compatibility)
            if content:
                parsed = self._content_mgr.parse_task_content(content)
                task_with_content["description"] = parsed.get("description", "")
                if "dependencies" in parsed:
                    task_with_content["data"] = {"dependencies": parsed["dependencies"]}
                else:
                    task_with_content["data"] = None
            else:
                task_with_content["description"] = ""
                task_with_content["data"] = None
        else:
            task_with_content["content"] = ""
            task_with_content["description"] = ""
            task_with_content["data"] = None

        # Derive sprint_id from PRD (tasks inherit sprint from their parent PRD)
        sprint_id = None
        if task.get("prd_id"):
            prd = self._db.get_prd(task["prd_id"])
            if prd:
                sprint_id = prd.get("sprint_id")
        task_with_content["sprint_id"] = sprint_id

        return task_with_content

    def list_tasks(
        self,
        project_id: str,
        status: str | None = None,
        prd_id: str | None = None,
        sprint_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List tasks with optional filters."""
        tasks = self._db.list_tasks(project_id, status=status, prd_id=prd_id, sprint_id=sprint_id)

        # Enrich tasks with dependencies from content files
        for task in tasks:
            content = None
            if task.get("file_path"):
                content = self._content_mgr.read_content(Path(task["file_path"]))
            elif task.get("project_id"):
                content = self._content_mgr.read_task(task["project_id"], task["id"])

            if content:
                parsed = self._content_mgr.parse_task_content(content)
                if "dependencies" in parsed:
                    task["data"] = {"dependencies": parsed["dependencies"]}
                else:
                    task["data"] = None
            else:
                task["data"] = None

        return tasks

    def list_tasks_by_sprint(
        self,
        project_id: str,
        sprint_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List tasks for a sprint."""
        tasks = self._db.list_tasks_by_sprint(project_id, sprint_id, status=status)
        # Normalize column name: derived_sprint_id -> sprint_id
        for task in tasks:
            if "derived_sprint_id" in task:
                task["sprint_id"] = task.pop("derived_sprint_id")

            # Enrich with dependencies from content files
            content = None
            if task.get("file_path"):
                content = self._content_mgr.read_content(Path(task["file_path"]))
            elif task.get("project_id"):
                content = self._content_mgr.read_task(task["project_id"], task["id"])

            if content:
                parsed = self._content_mgr.parse_task_content(content)
                if "dependencies" in parsed:
                    task["data"] = {"dependencies": parsed["dependencies"]}
                else:
                    task["data"] = None
            else:
                task["data"] = None

        return tasks

    def update_task(self, task_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update task metadata (DB only, no file operations).

        Content changes should be made by editing the file directly.
        """
        task = self._db.get_task(task_id)
        if not task:
            return None

        # Remove content/description/data if accidentally passed — no longer handled here
        kwargs.pop("content", None)
        kwargs.pop("description", None)
        kwargs.pop("data", None)

        updated = self._db.update_task(task_id, **kwargs)
        if updated:
            return self.get_task(task_id)
        return None

    def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        task = self._db.get_task(task_id)
        if not task:
            return False

        # Delete content file
        self._content_mgr.delete_task(task["project_id"], task_id)

        # Delete from database
        return self._db.delete_task(task_id)

    def get_next_task_id(self, project_id: str) -> str:
        """Generate next task ID."""
        return self._db.get_next_task_id(project_id)

    def get_next_prd_id(self, project_id: str) -> str:
        """Generate next PRD ID."""
        return self._db.get_next_prd_id(project_id)

    # =========================================================================
    # Design Document Operations
    # =========================================================================

    def create_design(
        self,
        prd_id: str,
        project_id: str,
    ) -> dict[str, Any]:
        """Create a new design document with empty file.

        Follows file-first persistence: writes empty file before DB record.
        Design documents have a 1:1 relationship with PRDs.

        Args:
            prd_id: Parent PRD ID (also used as design ID)
            project_id: Parent project ID

        Returns:
            Dict with metadata and file_path for content writing
        """
        # Write empty file
        file_path = self._content_mgr.write_design(project_id, prd_id, "")

        # Create DB record (design_id = prd_id for 1:1 relationship)
        design = self._db.create_design(
            design_id=prd_id,
            prd_id=prd_id,
            project_id=project_id,
            file_path=str(file_path),
        )

        design_result = dict(design)
        design_result["file_path"] = str(file_path)
        return design_result

    def get_design_by_prd(self, prd_id: str) -> dict[str, Any] | None:
        """Get design document by parent PRD ID with content.

        Args:
            prd_id: PRD identifier

        Returns:
            Combined dict with metadata and content, or None if not found
        """
        design = self._db.get_design_by_prd(prd_id)
        if not design:
            return None

        # Read content from file
        content = None
        if design.get("file_path"):
            content = self._content_mgr.read_content(Path(design["file_path"]))
        elif design.get("project_id"):
            content = self._content_mgr.read_design(design["project_id"], prd_id)

        design_with_content = dict(design)
        design_with_content["content"] = content or ""
        return design_with_content

    def list_designs(self, project_id: str) -> list[dict[str, Any]]:
        """List design documents for a project (metadata only).

        Args:
            project_id: Project identifier

        Returns:
            List of design metadata dicts (no content)
        """
        return self._db.list_designs(project_id)

    def delete_design(self, prd_id: str) -> bool:
        """Delete a design document.

        Args:
            prd_id: PRD identifier (design_id = prd_id)

        Returns:
            True if deleted, False if not found
        """
        design = self._db.get_design_by_prd(prd_id)
        if not design:
            return False

        # Delete content file first
        self._content_mgr.delete_design(design["project_id"], prd_id)

        # Delete from database
        return self._db.delete_design(prd_id)

    # =========================================================================
    # Sprint Operations
    # =========================================================================

    def create_sprint(
        self,
        sprint_id: str,
        project_id: str,
        title: str,
        goal: str = "",
        status: str = "planned",
    ) -> dict[str, Any]:
        """Create a new sprint."""
        return self._db.create_sprint(sprint_id, project_id, title, goal, status)

    def get_sprint(self, sprint_id: str) -> dict[str, Any] | None:
        """Get sprint by ID with summary."""
        return self._db.get_sprint(sprint_id)

    def list_sprints(self, project_id: str) -> list[dict[str, Any]]:
        """List all sprints for a project."""
        return self._db.list_sprints(project_id)

    def update_sprint(self, sprint_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update sprint fields."""
        return self._db.update_sprint(sprint_id, **kwargs)

    def delete_sprint(self, sprint_id: str) -> bool:
        """Delete a sprint."""
        return self._db.delete_sprint(sprint_id)

    def get_sprint_prds(self, sprint_id: str) -> list[dict[str, Any]]:
        """Get all PRDs in a sprint."""
        return self._db.get_sprint_prds(sprint_id)

    def assign_prd_to_sprint(self, prd_id: str, sprint_id: str | None) -> dict[str, Any] | None:
        """Assign PRD to sprint."""
        return self._db.assign_prd_to_sprint(prd_id, sprint_id)

    def get_next_sprint_id(self, project_id: str) -> str:
        """Generate next sprint ID."""
        return self._db.get_next_sprint_id(project_id)

    # =========================================================================
    # Sync Mapping Operations
    # =========================================================================

    def create_sync_mapping(
        self,
        entity_type: str,
        local_id: str,
        external_system: str,
        external_id: str,
    ) -> dict[str, Any]:
        """Create sync mapping."""
        return self._db.create_sync_mapping(entity_type, local_id, external_system, external_id)

    def get_sync_mapping(
        self, entity_type: str, local_id: str, external_system: str
    ) -> dict[str, Any] | None:
        """Get sync mapping."""
        return self._db.get_sync_mapping(entity_type, local_id, external_system)

    def get_sync_mapping_by_external(
        self, entity_type: str, external_system: str, external_id: str
    ) -> dict[str, Any] | None:
        """Get sync mapping by external ID."""
        return self._db.get_sync_mapping_by_external(entity_type, external_system, external_id)

    def list_sync_mappings(
        self, entity_type: str | None = None, external_system: str | None = None
    ) -> list[dict[str, Any]]:
        """List sync mappings."""
        return self._db.list_sync_mappings(entity_type, external_system)

    def update_sync_mapping(
        self, entity_type: str, local_id: str, external_system: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        """Update sync mapping."""
        return self._db.update_sync_mapping(entity_type, local_id, external_system, **kwargs)

    def delete_sync_mapping(
        self, entity_type: str, local_id: str, external_system: str
    ) -> bool:
        """Delete sync mapping."""
        return self._db.delete_sync_mapping(entity_type, local_id, external_system)

    # =========================================================================
    # External Config Operations
    # =========================================================================

    def get_external_config(self, project_id: str, system: str) -> dict[str, Any] | None:
        """Get external config."""
        return self._db.get_external_config(project_id, system)

    def set_external_config(
        self, project_id: str, system: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Set external config."""
        return self._db.set_external_config(project_id, system, config)

    def delete_external_config(self, project_id: str, system: str) -> bool:
        """Delete external config."""
        return self._db.delete_external_config(project_id, system)

    def list_external_configs(self, project_id: str) -> list[dict[str, Any]]:
        """List external configs."""
        return self._db.list_external_configs(project_id)

    # =========================================================================
    # Agent Operations
    # =========================================================================

    def create_agent(
        self,
        agent_id: str,
        project_id: str,
        persona_type: str,
        display_name: str,
        status: str = "active",
        permissions_profile: str | None = None,
        approved_by: str | None = None,
    ) -> dict[str, Any]:
        """Create a new agent record."""
        return self._db.create_agent(
            agent_id, project_id, persona_type, display_name,
            status, permissions_profile, approved_by,
        )

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Get an agent by ID."""
        return self._db.get_agent(agent_id)

    def list_agents(
        self, project_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List agents for a project, optionally filtered by status."""
        return self._db.list_agents(project_id, status)

    def update_agent(self, agent_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update agent fields dynamically."""
        return self._db.update_agent(agent_id, **kwargs)

    def update_agent_status(
        self, agent_id: str, status: str, reason: str | None = None
    ) -> dict[str, Any] | None:
        """Update agent status (active/suspended/retired)."""
        return self._db.update_agent_status(agent_id, status, reason)

    def delete_agent(self, agent_id: str) -> bool:
        """Soft-delete an agent by setting status to 'retired'."""
        return self._db.delete_agent(agent_id)

    def get_next_agent_id(self, project_id: str) -> str:
        """Generate next agent ID for a project."""
        return self._db.get_next_agent_id(project_id)

    # =========================================================================
    # Agent Permission Operations
    # =========================================================================

    def set_agent_permission(
        self,
        agent_id: str,
        permission_type: str,
        permission_value: str,
        allowed: int = 1,
    ) -> dict[str, Any]:
        """Set or update a permission for an agent."""
        return self._db.set_agent_permission(
            agent_id, permission_type, permission_value, allowed,
        )

    def check_agent_permission(
        self, agent_id: str, permission_type: str, permission_value: str
    ) -> bool:
        """Check if agent has a specific permission."""
        return self._db.check_agent_permission(agent_id, permission_type, permission_value)

    def get_agent_permissions(self, agent_id: str) -> list[dict[str, Any]]:
        """Get all permissions for an agent."""
        return self._db.get_agent_permissions(agent_id)

    # =========================================================================
    # Agent Budget Operations
    # =========================================================================

    def create_agent_budget(
        self,
        agent_id: str,
        run_id: str | None = None,
        token_limit: int | None = None,
        cost_limit_cents: int | None = None,
        alert_threshold_pct: int = 90,
    ) -> dict[str, Any]:
        """Create a budget record for an agent."""
        return self._db.create_agent_budget(
            agent_id, run_id, token_limit, cost_limit_cents, alert_threshold_pct,
        )

    def get_agent_budget(
        self, agent_id: str, run_id: str | None = None
    ) -> dict[str, Any] | None:
        """Get budget for an agent, optionally filtered by run."""
        return self._db.get_agent_budget(agent_id, run_id)

    def update_agent_budget(
        self,
        budget_id: int,
        token_used_delta: int = 0,
        cost_used_delta: int = 0,
    ) -> dict[str, Any] | None:
        """Update budget usage with delta values."""
        return self._db.update_agent_budget(budget_id, token_used_delta, cost_used_delta)

    def increment_agent_budget(
        self,
        agent_id: str,
        tokens_delta: int = 0,
        cost_delta_cents: int = 0,
        run_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Atomically increment an agent's budget usage counters (REM-004)."""
        return self._db.increment_agent_budget(
            agent_id, tokens_delta, cost_delta_cents, run_id,
        )

    # =========================================================================
    # Execution Run Operations
    # =========================================================================

    def create_execution_run(
        self,
        run_id: str,
        project_id: str,
        sprint_id: str | None = None,
        status: str = "pending",
        governance_config: str | None = None,
        total_budget_cents: int | None = None,
        agent_count: int = 0,
    ) -> dict[str, Any]:
        """Create an execution run record."""
        return self._db.create_execution_run(
            run_id, project_id, sprint_id, status,
            governance_config, total_budget_cents, agent_count,
        )

    def get_execution_run(self, run_id: str) -> dict[str, Any] | None:
        """Get an execution run by ID."""
        return self._db.get_execution_run(run_id)

    def update_execution_run(self, run_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update execution run fields dynamically."""
        return self._db.update_execution_run(run_id, **kwargs)

    def get_next_run_id(self, project_id: str) -> str:
        """Generate next execution run ID for a project."""
        return self._db.get_next_run_id(project_id)

    def list_execution_runs(
        self,
        project_id: str,
        run_type: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List execution runs for a project."""
        return self._db.list_execution_runs(project_id, run_type=run_type, status=status)

    def get_execution_run_detail(self, run_id: str) -> dict[str, Any] | None:
        """Get an execution run by ID with summary stats."""
        return self._db.get_execution_run_detail(run_id)

    def count_work_items_by_status(self, run_id: str) -> dict[str, int]:
        """Count work items by status for a run."""
        return self._db.count_work_items_by_status(run_id)

    def count_thread_entries(self, run_id: str) -> int:
        """Count total thread entries for a run."""
        return self._db.count_thread_entries(run_id)

    def get_recent_thread_entries(self, run_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent thread entries across all artifacts for a run."""
        return self._db.get_recent_thread_entries(run_id, limit=limit)

    def create_work_queue_item(
        self,
        item_id: str,
        run_id: str,
        project_id: str,
        work_type: str,
        artifact_type: str | None = None,
        artifact_id: str | None = None,
        status: str = "pending",
        priority: int = 0,
        depends_on: str | None = None,
        assigned_agent_id: str | None = None,
        config: str | None = None,
    ) -> dict[str, Any]:
        """Create a work queue item."""
        return self._db.create_work_queue_item(
            item_id, run_id, project_id, work_type,
            artifact_type=artifact_type, artifact_id=artifact_id,
            status=status, priority=priority, depends_on=depends_on,
            assigned_agent_id=assigned_agent_id, config=config,
        )

    def list_work_queue_items(
        self, run_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List work queue items for a run."""
        return self._db.list_work_queue_items(run_id, status=status)

    def get_work_queue_item(self, item_id: str) -> dict[str, Any] | None:
        """Get a single work queue item by ID."""
        return self._db.get_work_queue_item(item_id)

    def update_work_queue_item(
        self, item_id: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        """Update work queue item fields dynamically."""
        return self._db.update_work_queue_item(item_id, **kwargs)

    def create_artifact_thread_entry(
        self,
        run_id: str,
        project_id: str,
        artifact_type: str,
        artifact_id: str,
        entry_type: str,
        agent_id: str | None = None,
        agent_persona: str | None = None,
        round_number: int = 1,
        content: str | None = None,
        parent_thread_id: int | None = None,
    ) -> dict[str, Any]:
        """Create an artifact thread entry."""
        return self._db.create_artifact_thread_entry(
            run_id, project_id, artifact_type, artifact_id, entry_type,
            agent_id=agent_id, agent_persona=agent_persona,
            round_number=round_number, content=content,
            parent_thread_id=parent_thread_id,
        )

    def list_artifact_threads(
        self,
        run_id: str,
        artifact_type: str | None = None,
        artifact_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List artifact thread entries for a run."""
        return self._db.list_artifact_threads(
            run_id, artifact_type=artifact_type, artifact_id=artifact_id
        )

    def list_artifact_threads_by_artifact(
        self,
        artifact_type: str,
        artifact_id: str,
    ) -> list[dict[str, Any]]:
        """List artifact thread entries for a specific artifact across all runs."""
        return self._db.list_artifact_threads_by_artifact(
            artifact_type, artifact_id
        )

    def get_run_state_hash(self, run_id: str) -> str:
        """Get a hash representing the current state of a run."""
        return self._db.get_run_state_hash(run_id)

    # =========================================================================
    # Work Queue Advanced Operations
    # =========================================================================

    def get_next_work_item_id(self, project_id: str) -> str:
        """Generate next work item ID for a project."""
        return self._db.get_next_work_item_id(project_id)

    def create_work_item(
        self,
        run_id: str,
        project_id: str,
        work_type: str,
        artifact_type: str | None = None,
        artifact_id: str | None = None,
        status: str = "pending",
        priority: int = 0,
        depends_on: "list[str] | str | None" = None,
        config: "dict[str, Any] | str | None" = None,
        retry_count: int = 0,
    ) -> dict[str, Any]:
        """Create a work queue item with auto-generated ID."""
        return self._db.create_work_item(
            run_id, project_id, work_type,
            artifact_type=artifact_type, artifact_id=artifact_id,
            status=status, priority=priority, depends_on=depends_on,
            config=config, retry_count=retry_count,
        )

    def get_work_item(self, item_id: str) -> dict[str, Any] | None:
        """Get a single work queue item with deserialized JSON fields."""
        return self._db.get_work_item(item_id)

    def get_work_items(
        self, run_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List work queue items with deserialized JSON fields."""
        return self._db.get_work_items(run_id, status=status)

    def update_work_item(
        self, item_id: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        """Update work queue item with JSON serialization and auto-timestamps."""
        return self._db.update_work_item(item_id, **kwargs)

    def get_dispatchable_items(
        self, run_id: str, max_concurrent: int = 3
    ) -> list[dict[str, Any]]:
        """Get work items that are ready to be dispatched."""
        return self._db.get_dispatchable_items(run_id, max_concurrent)

    def increment_retry_count(self, item_id: str) -> dict[str, Any] | None:
        """Atomically increment retry count for a work item."""
        return self._db.increment_retry_count(item_id)

    def pause_work_item(self, item_id: str) -> dict[str, Any]:
        """Pause a work item (pending/in_progress -> paused)."""
        return self._db.pause_work_item(item_id)

    def cancel_work_item(self, item_id: str) -> dict[str, Any]:
        """Cancel a work item (non-terminal -> cancelled)."""
        return self._db.cancel_work_item(item_id)

    def skip_work_item(
        self, item_id: str, reason: str | None = None
    ) -> dict[str, Any]:
        """Skip a work item (pending/blocked -> skipped)."""
        return self._db.skip_work_item(item_id, reason)

    def force_approve_work_item(self, item_id: str) -> dict[str, Any]:
        """Force-approve a work item (any -> completed + force_approved)."""
        return self._db.force_approve_work_item(item_id)

    def retry_work_item(self, item_id: str) -> dict[str, Any]:
        """Retry a work item (failed/blocked -> pending, increment retry)."""
        return self._db.retry_work_item(item_id)

    def answer_work_item(self, item_id: str, answer: str) -> dict[str, Any]:
        """Answer a question work item (question -> completed + answer)."""
        return self._db.answer_work_item(item_id, answer)

    def get_hierarchical_thread(
        self,
        artifact_type: str,
        artifact_id: str,
        run_id: str,
    ) -> list[dict[str, Any]]:
        """Get thread entries across sprint/PRD/task hierarchy."""
        return self._db.get_hierarchical_thread(artifact_type, artifact_id, run_id)

    # =========================================================================
    # Audit Log Operations
    # =========================================================================

    def append_audit_log(
        self,
        project_id: str,
        action_type: str,
        outcome: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        target_entity: str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """Append an entry to the audit log."""
        return self._db.append_audit_log(
            project_id, action_type, outcome,
            agent_id, run_id, target_entity, details,
        )

    def get_audit_log(
        self,
        project_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        action_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get audit log entries with optional filters."""
        return self._db.get_audit_log(project_id, agent_id, run_id, action_type, limit)

    # =========================================================================
    # Task Claim Operations
    # =========================================================================

    def claim_task(self, task_id: str, agent_id: str) -> dict[str, Any]:
        """Atomically claim a task for an agent."""
        return self._db.claim_task(task_id, agent_id)

    def release_task(
        self, task_id: str, agent_id: str, reason: str = "manual"
    ) -> dict[str, Any] | None:
        """Release a task claim, resetting the task to pending."""
        return self._db.release_task(task_id, agent_id, reason)

    def get_active_claim(self, task_id: str) -> dict[str, Any] | None:
        """Get the active claim for a task."""
        return self._db.get_active_claim(task_id)

    def list_claims_by_agent(self, agent_id: str) -> list[dict[str, Any]]:
        """List all claims for an agent."""
        return self._db.list_claims_by_agent(agent_id)

    def detect_stale_claims(self, timeout_minutes: int = 30) -> list[dict[str, Any]]:
        """Detect active claims that have exceeded the timeout threshold."""
        return self._db.detect_stale_claims(timeout_minutes)

    def get_available_work(
        self,
        project_id: str,
        agent_id: str,
        sprint_id: str | None = None,
        component_map: dict[str, list[str]] | None = None,
    ) -> list[dict[str, Any]]:
        """Get available (unclaimed, pending) tasks for an agent."""
        return self._db.get_available_work(
            project_id, agent_id, sprint_id, component_map
        )

    # =========================================================================
    # Agent Message Operations
    # =========================================================================

    def send_agent_message(
        self,
        from_agent_id: str,
        to_agent_id: str,
        message_type: str,
        content: str,
        related_task_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a message from one agent to another."""
        return self._db.send_agent_message(
            from_agent_id, to_agent_id, message_type, content, related_task_id,
        )

    def get_agent_messages(
        self,
        agent_id: str,
        unread_only: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get messages sent to an agent."""
        return self._db.get_agent_messages(agent_id, unread_only, limit)

    def mark_message_read(self, message_id: int) -> dict[str, Any] | None:
        """Mark a message as read."""
        return self._db.mark_message_read(message_id)

    # =========================================================================
    # Agent Team Operations
    # =========================================================================

    def create_agent_team(
        self,
        name: str,
        project_id: str,
        lead_agent_id: str | None = None,
        sprint_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new agent team."""
        return self._db.create_agent_team(name, project_id, lead_agent_id, sprint_id)

    def assign_agent_to_team(
        self, agent_id: str, team_id: int
    ) -> dict[str, Any] | None:
        """Assign an agent to a team."""
        return self._db.assign_agent_to_team(agent_id, team_id)

    def get_team_composition(
        self, team_id: int, sprint_id: str | None = None
    ) -> dict[str, Any]:
        """Get team details with all member agents."""
        return self._db.get_team_composition(team_id, sprint_id)

    def list_agent_teams(
        self, project_id: str, sprint_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List all teams in a project."""
        return self._db.list_agent_teams(project_id, sprint_id)

    # =========================================================================
    # Agent Performance Operations
    # =========================================================================

    def record_agent_performance(
        self,
        agent_id: str,
        sprint_id: str | None = None,
        tasks_completed: int = 0,
        tasks_failed: int = 0,
        avg_quality_score: float | None = None,
        avg_completion_time_min: float | None = None,
        corrections_count: int = 0,
        review_pass_rate: float | None = None,
    ) -> dict[str, Any]:
        """Upsert agent performance record."""
        return self._db.record_agent_performance(
            agent_id, sprint_id, tasks_completed, tasks_failed,
            avg_quality_score, avg_completion_time_min,
            corrections_count, review_pass_rate,
        )

    def get_agent_performance(
        self, agent_id: str, sprint_id: str | None = None
    ) -> dict[str, Any] | None:
        """Get performance record for an agent."""
        return self._db.get_agent_performance(agent_id, sprint_id)

    def compute_agent_performance(self, agent_id: str) -> dict[str, Any]:
        """Compute aggregated performance metrics across all sprints."""
        return self._db.compute_agent_performance(agent_id)

    def update_agent_performance_score(
        self, agent_id: str, new_score: float
    ) -> dict[str, Any] | None:
        """Update the rolling performance_score on the agents table."""
        return self._db.update_agent_performance_score(agent_id, new_score)

    # =========================================================================
    # Health & Org Operations
    # =========================================================================

    def detect_health_issues(
        self,
        project_id: str,
        stalled_timeout_min: int = 30,
        error_rate_threshold_pct: int = 30,
        quality_threshold: int = 40,
    ) -> list[dict[str, Any]]:
        """Detect agents with health issues."""
        return self._db.detect_health_issues(
            project_id, stalled_timeout_min, error_rate_threshold_pct, quality_threshold,
        )

    def suspend_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Suspend an agent."""
        return self._db.suspend_agent(agent_id)

    def retire_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Retire an agent (preserves all data)."""
        return self._db.retire_agent(agent_id)

    def get_org_overview(self, project_id: str) -> dict[str, Any]:
        """Get organizational overview with agent stats, teams, and performance."""
        return self._db.get_org_overview(project_id)

    # =========================================================================
    # Quality & Traceability Operations
    # =========================================================================

    def upsert_requirement(
        self,
        id: str,
        prd_id: str,
        req_type: str,
        req_number: str,
        summary: str,
        depth: str = "structural",
    ) -> dict[str, Any]:
        """Insert or replace a requirement record."""
        return self._db.upsert_requirement(id, prd_id, req_type, req_number, summary, depth)

    def get_requirement(self, requirement_id: str) -> dict[str, Any] | None:
        """Get a single requirement by ID."""
        return self._db.get_requirement(requirement_id)

    def get_requirements(
        self, prd_id: str, req_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all requirements for a PRD, optionally filtered by type."""
        return self._db.get_requirements(prd_id, req_type)

    def delete_requirements(self, prd_id: str) -> int:
        """Delete all requirements for a PRD."""
        return self._db.delete_requirements(prd_id)

    def link_task_requirement(self, requirement_id: str, task_id: str) -> dict[str, Any]:
        """Link a task to a requirement."""
        return self._db.link_task_requirement(requirement_id, task_id)

    def get_task_requirements(self, task_id: str) -> list[dict[str, Any]]:
        """Get all requirements linked to a task, with verification status."""
        return self._db.get_task_requirements(task_id)

    def get_requirement_tasks(self, requirement_id: str) -> list[dict[str, Any]]:
        """Get all tasks linked to a requirement."""
        return self._db.get_requirement_tasks(requirement_id)

    def get_orphaned_requirements(self, prd_id: str) -> list[dict[str, Any]]:
        """Get requirements with zero linked tasks."""
        return self._db.get_orphaned_requirements(prd_id)

    def get_coverage_stats(self, prd_id: str) -> dict[str, Any]:
        """Compute requirement coverage statistics for a PRD."""
        return self._db.get_coverage_stats(prd_id)

    def record_ac_verification(
        self,
        requirement_id: str,
        task_id: str,
        verified_by: str,
        evidence_type: str,
        evidence: str,
    ) -> dict[str, Any]:
        """Record acceptance-criteria verification evidence."""
        return self._db.record_ac_verification(
            requirement_id, task_id, verified_by, evidence_type, evidence,
        )

    def get_ac_verifications(self, task_id: str) -> list[dict[str, Any]]:
        """Get all AC verifications for a task."""
        return self._db.get_ac_verifications(task_id)

    def get_unverified_acs(self, task_id: str) -> list[dict[str, Any]]:
        """Get AC requirements linked to a task but not yet verified."""
        return self._db.get_unverified_acs(task_id)

    def create_challenge_round(
        self,
        artifact_type: str,
        artifact_id: str,
        round_number: int,
        objections: str,
        challenger_context: str | None = None,
    ) -> dict[str, Any]:
        """Create a new challenge round for an artifact."""
        return self._db.create_challenge_round(
            artifact_type, artifact_id, round_number, objections, challenger_context,
        )

    def update_challenge_round(
        self,
        artifact_type: str,
        artifact_id: str,
        round_number: int,
        responses: str | None = None,
        verdict: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        """Update specific fields of a challenge round."""
        return self._db.update_challenge_round(
            artifact_type, artifact_id, round_number, responses, verdict, status,
        )

    def get_challenge_rounds(
        self, artifact_type: str, artifact_id: str
    ) -> list[dict[str, Any]]:
        """Get all challenge rounds for an artifact."""
        return self._db.get_challenge_rounds(artifact_type, artifact_id)

    def get_challenge_status(
        self, artifact_type: str, artifact_id: str
    ) -> dict[str, Any]:
        """Get summary status of challenge rounds for an artifact."""
        return self._db.get_challenge_status(artifact_type, artifact_id)


# Backward compatibility aliases
FileStorage = HybridStorage


# Global storage instance
_storage: HybridStorage | None = None


def get_storage() -> HybridStorage:
    """Get or create the global storage instance."""
    global _storage
    if _storage is None:
        _storage = HybridStorage()
    return _storage


def ensure_templates() -> list[str]:
    """Copy default templates to user directory if they don't exist.

    Returns:
        List of template files that were created.
    """
    import shutil

    storage = get_storage()
    templates_dir = storage.templates_dir
    templates_dir.mkdir(parents=True, exist_ok=True)

    created = []

    # Find the artifact_templates directory in the package
    package_dir = Path(__file__).parent.parent
    artifact_templates = package_dir / "artifact_templates"

    if artifact_templates.exists():
        templates_to_copy = [
            "task.template.md",
            "prd.template.md",
        ]

        for template_name in templates_to_copy:
            src = artifact_templates / template_name
            dest = templates_dir / template_name

            if src.exists() and not dest.exists():
                shutil.copy(src, dest)
                created.append(template_name)

    return created


def get_template_path(template_name: str) -> Path | None:
    """Get path to a template file.

    Looks in user's templates directory first, then falls back to package defaults.

    Args:
        template_name: Name of the template file

    Returns:
        Path to template file, or None if not found.
    """
    storage = get_storage()

    # Check user templates first
    user_template = storage.templates_dir / template_name
    if user_template.exists():
        return user_template

    # Fall back to package templates
    package_dir = Path(__file__).parent.parent
    package_template = package_dir / "artifact_templates" / template_name
    if package_template.exists():
        return package_template

    return None


__all__ = [
    "HybridStorage",
    "FileStorage",  # Backward compatibility alias
    "get_storage",
    "get_data_dir",
    "ensure_templates",
    "get_template_path",
]
