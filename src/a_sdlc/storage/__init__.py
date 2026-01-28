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
            Database = _get_database_class()
            ContentManager = _get_content_manager_class()
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
        content: str = "",
        status: str = "draft",
        source: str | None = None,
        sprint_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new PRD."""
        # Write content file
        file_path = self._content_mgr.write_prd(project_id, prd_id, title, content)

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

        # Add content to response for backward compatibility
        prd_with_content = dict(prd)
        prd_with_content["content"] = content
        return prd_with_content

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
        """Update PRD fields."""
        prd = self._db.get_prd(prd_id)
        if not prd:
            return None

        # Handle content update
        if "content" in kwargs:
            content = kwargs.pop("content")
            title = kwargs.get("title", prd["title"])
            file_path = self._content_mgr.write_prd(
                prd["project_id"], prd_id, title, content
            )
            kwargs["file_path"] = str(file_path)
        elif "title" in kwargs:
            # Update file with new title
            existing_content = self._content_mgr.read_prd(prd["project_id"], prd_id) or ""
            file_path = self._content_mgr.write_prd(
                prd["project_id"], prd_id, kwargs["title"], existing_content
            )
            kwargs["file_path"] = str(file_path)

        updated = self._db.update_prd(prd_id, **kwargs)
        if updated:
            # Add content to response
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
        description: str = "",
        status: str = "pending",
        priority: str = "medium",
        prd_id: str | None = None,
        component: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new task."""
        # Write content file
        file_path = self._content_mgr.write_task(
            project_id=project_id,
            task_id=task_id,
            title=title,
            description=description,
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

        # Add description and data to response for backward compatibility
        task_with_content = dict(task)
        task_with_content["description"] = description
        task_with_content["data"] = data
        return task_with_content

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
        """Update task fields."""
        task = self._db.get_task(task_id)
        if not task:
            return None

        # Handle full content update (like PRD handling)
        content = kwargs.pop("content", None)
        if content is not None:
            # Write raw content directly to file (preserves all custom formatting)
            file_path = self._content_mgr.get_task_path(task["project_id"], task_id)
            self._content_mgr.write_content(file_path, content)
            kwargs["file_path"] = str(file_path)
            # Update database and return
            updated = self._db.update_task(task_id, **kwargs)
            if updated:
                return self.get_task(task_id)
            return None

        # Handle description and data updates via content file (legacy/field-based updates)
        description = kwargs.pop("description", None)
        data = kwargs.pop("data", None)

        if description is not None or data is not None or any(
            k in kwargs for k in ["title", "priority", "status", "component", "prd_id"]
        ):
            # Read existing content
            existing_content = self._content_mgr.read_task(task["project_id"], task_id)
            existing_data = {}
            if existing_content:
                existing_data = self._content_mgr.parse_task_content(existing_content)

            # Merge updates
            new_title = kwargs.get("title", task["title"])
            new_description = description if description is not None else existing_data.get("description", "")
            new_priority = kwargs.get("priority", task["priority"])
            new_status = kwargs.get("status", task["status"])
            new_component = kwargs.get("component", task["component"])
            new_prd_id = kwargs.get("prd_id", task.get("prd_id"))
            if new_prd_id == "":
                new_prd_id = None

            merged_data = data if data is not None else {}
            if "dependencies" not in merged_data and "dependencies" in existing_data:
                merged_data["dependencies"] = existing_data["dependencies"]

            file_path = self._content_mgr.write_task(
                project_id=task["project_id"],
                task_id=task_id,
                title=new_title,
                description=new_description,
                priority=new_priority,
                status=new_status,
                component=new_component,
                prd_id=new_prd_id,
                data=merged_data if merged_data else None,
            )
            kwargs["file_path"] = str(file_path)

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
