"""
Storage adapter for a-sdlc.

This module provides backward-compatible storage interface by wrapping:
- SessionDatabase (PostgreSQL via SQLModel): Metadata and file path references
- ContentManager: Markdown content files (S3 backend)

The HybridStorage class provides the same interface as the old FileStorage
to minimize changes in CLI and UI code.

Backend selection:
    When *base_path* is provided (test isolation), always use SQLite + local
    regardless of configuration.  Otherwise:
    - Instantiate ``SessionDatabase`` with the configured PostgreSQL URL.
    - Instantiate ``S3ContentBackend`` with the configured S3 bucket.
"""

import contextlib
import logging
import os
import platform
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_data_dir() -> Path:
    """Get platform-specific data directory.

    Respects the ``A_SDLC_DATA_DIR`` environment variable when set (e.g. in
    Docker containers where ``/data`` is mounted).  Falls back to the
    platform default: ``~/.a-sdlc/`` on macOS/Linux,
    ``%LOCALAPPDATA%/a-sdlc/`` on Windows.

    Returns:
        Path to the a-sdlc data directory.
    """
    env_dir = os.environ.get("A_SDLC_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "a-sdlc"
    else:
        return Path.home() / ".a-sdlc"


# Lazy imports to avoid circular dependencies
def _get_database_class():
    from a_sdlc.core.database import Database
    return Database


def _get_session_database_class():
    from a_sdlc.core.session_database import SessionDatabase
    return SessionDatabase


def _get_content_manager_class():
    from a_sdlc.core.content import ContentManager
    return ContentManager


def _get_s3_content_backend_class():
    from a_sdlc.core.content import S3ContentBackend
    return S3ContentBackend


def _get_storage_config():
    from a_sdlc.core.storage_config import get_storage_config
    return get_storage_config()


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
        config: Any = None,
    ):
        """Initialize hybrid storage.

        Args:
            db: Deprecated — raises ``ValueError``. Use *base_path* or *config*.
            content_mgr: Deprecated — raises ``ValueError``. Use *base_path* or *config*.
            base_path: Custom base path for test isolation (creates new instances).
                When provided, always uses SQLite + local filesystem regardless
                of *config*.
            config: Optional ``StorageConfig`` instance. When omitted the
                global singleton from ``get_storage_config()`` is used.
                Ignored when *base_path* is provided.
        """
        if base_path is not None:
            # Test isolation mode: always SQLite + local filesystem
            Database = _get_database_class()  # noqa: N806
            ContentManager = _get_content_manager_class()  # noqa: N806
            self._base_path = Path(base_path)
            self._base_path.mkdir(parents=True, exist_ok=True)
            self._db = Database(db_path=self._base_path / "data.db")
            self._content_mgr = ContentManager(base_path=self._base_path / "content")
            # Ensure templates directory exists
            self.templates_dir.mkdir(parents=True, exist_ok=True)
        elif db is not None or content_mgr is not None:
            raise ValueError(
                "Passing db= or content_mgr= directly is no longer supported. "
                "Use base_path= for test isolation or config= for production."
            )
        else:
            # Auto-select backends from config
            self._base_path = get_data_dir()
            self._init_from_config(config)

    def _init_from_config(self, config: Any = None) -> None:
        """Initialize database and content backends from StorageConfig.

        Production requires PostgreSQL + S3.  Raises if configuration is
        missing or invalid.

        Args:
            config: Optional ``StorageConfig``. When ``None``, the global
                singleton from ``get_storage_config()`` is loaded.

        Raises:
            StorageConfigError: If database is not PostgreSQL or content
                backend is not S3.
        """
        from a_sdlc.core.storage_config import StorageConfigError

        if config is None:
            config = _get_storage_config()

        # -- Database backend ---------------------------------------------------
        if config.is_postgresql:
            SessionDatabase = _get_session_database_class()  # noqa: N806
            self._db = SessionDatabase(config=config)
            logger.info("Using SessionDatabase (PostgreSQL)")
        else:
            raise StorageConfigError(
                f"PostgreSQL is required. Got: {config.database_url}. "
                "Set A_SDLC_DATABASE_URL to a PostgreSQL URL or use Docker Compose."
            )

        # -- Content backend ----------------------------------------------------
        if config.is_s3 and config.s3_bucket:
            ContentManager = _get_content_manager_class()  # noqa: N806
            S3ContentBackend = _get_s3_content_backend_class()  # noqa: N806
            content_base = self._base_path / "content"
            backend = S3ContentBackend(
                bucket=config.s3_bucket,
                endpoint_url=config.s3_endpoint,
                access_key=config.s3_access_key,
                secret_key=config.s3_secret_key,
                base_path=content_base,
            )
            self._content_mgr = ContentManager(
                base_path=content_base,
                backend=backend,
            )
            logger.info("Using S3ContentBackend (bucket=%s)", config.s3_bucket)
        else:
            raise StorageConfigError(
                "S3 content backend is required. "
                "Set A_SDLC_CONTENT_BACKEND=s3 and A_SDLC_S3_BUCKET, "
                "or use Docker Compose."
            )

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
        shortname: str | None = None,
    ) -> dict[str, Any]:
        """Create a new project.

        Args:
            project_id: Unique project identifier (slug)
            name: Display name
            shortname: 4-character uppercase project key (auto-generated if not provided)
        """
        return self._db.create_project(project_id, name, shortname)

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Get project by ID."""
        return self._db.get_project(project_id)

    def get_project_by_shortname(self, shortname: str) -> dict[str, Any] | None:
        """Get project by shortname."""
        return self._db.get_project_by_shortname(shortname)

    def resolve_project_by_cwd(
        self, start: "Path | str | None" = None
    ) -> dict[str, Any] | None:
        """Resolve the project for a working directory via its local marker.

        Walks up from *start* (default cwd) to the nearest ``.sdlc/project.json``
        (see :mod:`a_sdlc.core.project_marker`) and returns that project, or
        ``None`` when no marker is found or the referenced project is unknown.
        Replaces the removed path-based lookup so the database stores no
        device-specific paths.
        """
        from a_sdlc.core.project_marker import find_marker

        marker = find_marker(start)
        if not marker:
            return None
        return self._db.get_project(marker["id"])

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
        # Step 1: Write skeleton file (just title header, no real content yet)
        file_path = self._content_mgr.write_prd(project_id, prd_id, title, "")

        try:
            # Step 2: Register in database
            prd = self._db.create_prd(
                prd_id=prd_id,
                project_id=project_id,
                title=title,
                file_path=str(file_path),
                status=status,
                source=source,
                sprint_id=sprint_id,
            )
        except Exception:
            # Compensate: remove orphaned skeleton file
            # Safe because agent hasn't written real content yet
            with contextlib.suppress(OSError):
                file_path.unlink()
            raise

        if prd is None:
            return {"file_path": str(file_path)}
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
            # Read content from file — prefer environment-correct path over stored file_path
            # (stored file_path may reference a different machine, e.g. local Mac path in Docker)
            content = None
            if prd.get("project_id"):
                content = self._content_mgr.read_prd(prd["project_id"], prd_id)
            if content is None and prd.get("file_path"):
                content = self._content_mgr.read_content(Path(prd["file_path"]))
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

        # DB first (source of truth for existence)
        if not self._db.delete_prd(prd_id):
            return False

        # Then file (best-effort cleanup — orphaned files caught by doctor --repair)
        try:
            self._content_mgr.delete_prd(prd["project_id"], prd_id)
        except OSError as e:
            logger.warning("Failed to delete PRD content file for %s: %s", prd_id, e)

        return True

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
        # Step 1: Write skeleton file (no real content yet)
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

        try:
            # Step 2: Register in database
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
        except Exception:
            # Compensate: remove orphaned skeleton file
            # Safe because agent hasn't written real content yet
            with contextlib.suppress(OSError):
                file_path.unlink()
            raise

        if task is None:
            return {"file_path": str(file_path)}
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
            # Read content — prefer environment-correct path over stored file_path
            content = None
            if task.get("project_id"):
                content = self._content_mgr.read_task(task["project_id"], task_id)
            if content is None and task.get("file_path"):
                content = self._content_mgr.read_content(Path(task["file_path"]))

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
            if task.get("project_id"):
                content = self._content_mgr.read_task(task["project_id"], task["id"])
            if content is None and task.get("file_path"):
                content = self._content_mgr.read_content(Path(task["file_path"]))

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
            if task.get("project_id"):
                content = self._content_mgr.read_task(task["project_id"], task["id"])
            if content is None and task.get("file_path"):
                content = self._content_mgr.read_content(Path(task["file_path"]))

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

        # DB first (source of truth for existence)
        if not self._db.delete_task(task_id):
            return False

        # Then file (best-effort cleanup — orphaned files caught by doctor --repair)
        try:
            self._content_mgr.delete_task(task["project_id"], task_id)
        except OSError as e:
            logger.warning("Failed to delete task content file for %s: %s", task_id, e)

        return True

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
        # Step 1: Write empty file (no real content yet)
        file_path = self._content_mgr.write_design(project_id, prd_id, "")

        try:
            # Step 2: Create DB record (design_id = prd_id for 1:1 relationship)
            design = self._db.create_design(
                design_id=prd_id,
                prd_id=prd_id,
                project_id=project_id,
                file_path=str(file_path),
            )
        except Exception:
            # Compensate: remove orphaned skeleton file
            # Safe because agent hasn't written real content yet
            with contextlib.suppress(OSError):
                file_path.unlink()
            raise

        if design is None:
            return {"file_path": str(file_path)}
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

        # Read content from file (try environment-correct path first, fall back to stored file_path)
        content = None
        if design.get("project_id"):
            content = self._content_mgr.read_design(design["project_id"], prd_id)
        if content is None and design.get("file_path"):
            content = self._content_mgr.read_content(Path(design["file_path"]))

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

        # DB first (source of truth for existence)
        if not self._db.delete_design(prd_id):
            return False

        # Then file (best-effort cleanup — orphaned files caught by doctor --repair)
        try:
            self._content_mgr.delete_design(design["project_id"], prd_id)
        except OSError as e:
            logger.warning("Failed to delete design content file for %s: %s", prd_id, e)

        return True

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

    # =========================================================================
    # Consistency Check & Repair Operations
    # =========================================================================

    def consistency_check(self, project_id: str) -> dict[str, Any]:
        """Detect inconsistencies between content files and the database.

        Compares file IDs extracted from ``~/.a-sdlc/content/{project_id}/``
        against DB records for PRDs, tasks, and designs.

        Args:
            project_id: Project identifier to check.

        Returns:
            Dict with keys:
                orphaned_files  – list of dicts ``{"entity_type", "id", "file_path"}``
                    for files that have no matching DB record.
                phantom_records – list of dicts ``{"entity_type", "id"}``
                    for DB records whose content file is missing.
                total_entities  – total number of unique entity IDs found
                    across both sources.
        """
        orphaned_files: list[dict[str, str]] = []
        phantom_records: list[dict[str, str]] = []
        all_ids: set[str] = set()

        entity_types = [
            ("prd", self._content_mgr.list_prd_files, self._db.list_prds),
            ("task", self._content_mgr.list_task_files, self._db.list_tasks),
            ("design", self._content_mgr.list_design_files, self._db.list_designs),
        ]

        for entity_type, list_files_fn, list_db_fn in entity_types:
            # File IDs: extract stem (filename without .md)
            file_paths = list_files_fn(project_id)
            file_ids = {p.stem: p for p in file_paths}

            # DB IDs
            db_records = list_db_fn(project_id)
            db_ids = {r["id"] for r in db_records}

            all_ids.update(file_ids.keys())
            all_ids.update(db_ids)

            # Orphaned files: file exists but no DB record
            for fid, fpath in file_ids.items():
                if fid not in db_ids:
                    orphaned_files.append({
                        "entity_type": entity_type,
                        "id": fid,
                        "file_path": str(fpath),
                    })

            # Phantom records: DB record exists but no file
            for did in db_ids:
                if did not in file_ids:
                    phantom_records.append({
                        "entity_type": entity_type,
                        "id": did,
                    })

        return {
            "orphaned_files": orphaned_files,
            "phantom_records": phantom_records,
            "total_entities": len(all_ids),
        }

    def repair_consistency(
        self,
        project_id: str,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Repair inconsistencies between content files and the database.

        - **Orphaned files** (file exists, no DB record): deleted.
        - **Phantom records** (DB record, no file): DB record deleted.

        Args:
            project_id: Project identifier to repair.
            dry_run: If ``True`` (default), report what *would* be done
                without making changes.

        Returns:
            Dict with keys:
                repaired_orphans  – number of orphaned files removed.
                repaired_phantoms – number of phantom DB records removed.
                dry_run           – echo of the dry_run flag.
        """
        check = self.consistency_check(project_id)
        repaired_orphans = 0
        repaired_phantoms = 0

        # Repair orphaned files
        for orphan in check["orphaned_files"]:
            if dry_run:
                repaired_orphans += 1
            else:
                try:
                    Path(orphan["file_path"]).unlink()
                    repaired_orphans += 1
                except OSError as e:
                    logger.warning(
                        "Failed to delete orphaned file %s: %s",
                        orphan["file_path"], e,
                    )

        # Repair phantom records
        delete_fns = {
            "prd": self._db.delete_prd,
            "task": self._db.delete_task,
            "design": self._db.delete_design,
        }

        for phantom in check["phantom_records"]:
            delete_fn = delete_fns.get(phantom["entity_type"])
            if delete_fn is None:
                continue
            if dry_run:
                repaired_phantoms += 1
            else:
                try:
                    if delete_fn(phantom["id"]):
                        repaired_phantoms += 1
                except Exception as e:
                    logger.warning(
                        "Failed to delete phantom %s record %s: %s",
                        phantom["entity_type"], phantom["id"], e,
                    )

        return {
            "repaired_orphans": repaired_orphans,
            "repaired_phantoms": repaired_phantoms,
            "dry_run": dry_run,
        }


# Backward compatibility aliases
FileStorage = HybridStorage


# Global storage instance
_storage: HybridStorage | None = None


def init_storage(
    config: Any = None,
    base_path: "Path | None" = None,
) -> HybridStorage:
    """Initialize the global storage singleton.

    Must be called before ``get_storage()``.  Safe to call multiple times —
    subsequent calls return the existing instance.

    Args:
        config: Optional ``StorageConfig``.  When ``None``, loaded from
            environment / config files via ``get_storage_config()``.
        base_path: When provided, creates a test-isolation instance
            (SQLite + local filesystem) regardless of *config*.

    Returns:
        The initialized ``HybridStorage`` instance.
    """
    global _storage
    if _storage is not None:
        return _storage
    if base_path is not None:
        _storage = HybridStorage(base_path=base_path)
    elif config is not None:
        _storage = HybridStorage(config=config)
    else:
        from a_sdlc.core.storage_config import get_storage_config

        _storage = HybridStorage(config=get_storage_config())
    return _storage


def get_storage() -> HybridStorage:
    """Get the global storage instance.

    Raises ``RuntimeError`` if ``init_storage()`` has not been called.
    The MCP server calls ``init_storage()`` at startup via
    ``_init_storage_backend()``.  CLI commands call ``init_storage()``
    before accessing storage.
    """
    if _storage is None:
        raise RuntimeError(
            "Storage not initialized. "
            "Server must call init_storage() at startup. "
            "Set A_SDLC_DATABASE_URL and use Docker Compose."
        )
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
    "init_storage",
    "get_storage",
    "get_data_dir",
    "ensure_templates",
    "get_template_path",
]
