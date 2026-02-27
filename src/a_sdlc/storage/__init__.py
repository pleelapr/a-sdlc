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

    def get_prd(self, prd_id: str) -> dict[str, Any] | None:
        """Get PRD by ID with content."""
        prd = self._db.get_prd(prd_id)
        if not prd:
            return None

        # Read content from file
        content = None
        if prd.get("file_path"):
            content = self._content_mgr.read_content(Path(prd["file_path"]))
        elif prd.get("project_id"):
            content = self._content_mgr.read_prd(prd["project_id"], prd_id)

        prd_with_content = dict(prd)
        prd_with_content["content"] = content or ""
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

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get task by ID with content."""
        task = self._db.get_task(task_id)
        if not task:
            return None

        # Read content from file
        content = None
        if task.get("file_path"):
            content = self._content_mgr.read_content(Path(task["file_path"]))
        elif task.get("project_id"):
            content = self._content_mgr.read_task(task["project_id"], task_id)

        task_with_content = dict(task)

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
