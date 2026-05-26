"""
Content directory manager for a-sdlc.

Manages markdown content files that serve as the source of truth
for PRD, task, and design document content. The database
stores metadata and file path references; this module manages the actual
content files via the configured backend (S3 or local filesystem).

Directory structure (local backend):
    ~/.a-sdlc/content/
    └── {project}/
        ├── prds/
        │   └── {prd-id}.md     # Full PRD content (LLM-generated)
        ├── tasks/
        │   └── TASK-001.md     # Full task content (LLM-generated)
        └── designs/
            └── {prd-id}.md     # Design document content (1:1 with PRD)

S3 key structure (s3 backend):
    {project_id}/prds/{prd-id}.md
    {project_id}/tasks/{task-id}.md
    {project_id}/designs/{prd-id}.md
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
from abc import ABC, abstractmethod
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


# ============================================================================
# Content Backend Abstraction
# ============================================================================


class ContentBackend(ABC):
    """Abstract base class for content storage backends.

    Defines the minimal interface that all content backends must implement.
    ContentManager delegates low-level read/write/delete/list operations
    to a backend instance, allowing pluggable storage (local filesystem,
    S3, etc.) without changing higher-level logic.
    """

    @abstractmethod
    def read_content(self, file_path: str) -> str | None:
        """Read content from the given path.

        Args:
            file_path: Canonical file path (absolute for local, key-style for S3).

        Returns:
            File content as a UTF-8 string, or None if the object does not exist.
        """

    @abstractmethod
    def write_content(self, file_path: str, content: str) -> str:
        """Write content to the given path, creating parent directories/prefixes as needed.

        Args:
            file_path: Canonical file path.
            content: UTF-8 string content to write.

        Returns:
            The canonical path that was written (same as *file_path*).
        """

    @abstractmethod
    def delete_content(self, file_path: str) -> bool:
        """Delete the object at the given path.

        Args:
            file_path: Canonical file path.

        Returns:
            True if the object was deleted, False if it did not exist.
        """

    @abstractmethod
    def list_content(self, directory: str, suffix: str = ".md") -> list[str]:
        """List object paths under *directory* that end with *suffix*.

        Args:
            directory: Directory path (or S3 prefix) to list.
            suffix: File suffix filter (default ``".md"``).

        Returns:
            Sorted list of matching file paths (strings).
        """

    @abstractmethod
    def list_content_recursive(self, prefix: str, suffix: str = ".md") -> list[str]:
        """List all objects recursively under *prefix* matching *suffix*.

        Unlike :meth:`list_content`, this includes nested subdirectories.

        Args:
            prefix: Directory path (or S3 prefix) to search under.
            suffix: File suffix filter (default ``".md"``).

        Returns:
            Sorted list of matching file paths (strings).
        """

    @abstractmethod
    def exists(self, file_path: str) -> bool:
        """Check whether an object exists at the given path.

        Args:
            file_path: Canonical file path.

        Returns:
            True if the object exists, False otherwise.
        """


class LocalContentBackend(ContentBackend):
    """Content backend backed by the local filesystem.

    Wraps ``pathlib.Path.read_text`` / ``write_text`` / ``unlink`` to
    preserve the exact behaviour of the original ``ContentManager``.
    """

    def read_content(self, file_path: str) -> str | None:
        path = Path(file_path)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def write_content(self, file_path: str, content: str) -> str:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)

    def delete_content(self, file_path: str) -> bool:
        path = Path(file_path)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_content(self, directory: str, suffix: str = ".md") -> list[str]:
        dir_path = Path(directory)
        if not dir_path.exists():
            return []
        pattern = f"*{suffix}" if suffix else "*"
        return sorted(str(p) for p in dir_path.glob(pattern))

    def list_content_recursive(self, prefix: str, suffix: str = ".md") -> list[str]:
        dir_path = Path(prefix) if prefix else Path(".")
        if not dir_path.exists():
            return []
        pattern = f"*{suffix}" if suffix else "*"
        return sorted(str(p) for p in dir_path.rglob(pattern) if p.is_file())

    def exists(self, file_path: str) -> bool:
        return Path(file_path).exists()


class S3ContentBackend(ContentBackend):
    """Content backend backed by an S3-compatible object store.

    Uses ``boto3.client('s3')`` for all operations.  Absolute local-style
    paths are converted to relative S3 keys via *base_path* stripping so
    that ``ContentManager`` can remain path-centric.

    Args:
        bucket: S3 bucket name.
        endpoint_url: Optional S3-compatible endpoint (e.g. MinIO).
        access_key: Optional AWS access key ID.
        secret_key: Optional AWS secret access key.
        base_path: The local base path prefix to strip when converting
            absolute paths to S3 keys.  For example, if *base_path* is
            ``/home/user/.a-sdlc/content`` and the file_path is
            ``/home/user/.a-sdlc/content/proj/prds/P0001.md``, the S3
            key becomes ``proj/prds/P0001.md``.
    """

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        base_path: str | Path | None = None,
    ) -> None:
        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for S3ContentBackend. Install it with: pip install 'a-sdlc[s3]'"
            ) from exc

        self._bucket = bucket
        self._base_path = str(base_path).rstrip("/") + "/" if base_path else ""

        kwargs: dict[str, Any] = {}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if access_key:
            kwargs["aws_access_key_id"] = access_key
        if secret_key:
            kwargs["aws_secret_access_key"] = secret_key

        self._client = boto3.client("s3", **kwargs)

    # -- path helpers --------------------------------------------------------

    def _to_key(self, file_path: str) -> str:
        """Convert an absolute (or relative) file path to an S3 key.

        Strips *base_path* prefix and any leading slashes so keys are
        always relative.
        """
        path_str = str(file_path)
        if self._base_path and path_str.startswith(self._base_path):
            path_str = path_str[len(self._base_path) :]
        return path_str.lstrip("/")

    def _dir_to_prefix(self, directory: str) -> str:
        """Convert a directory path to an S3 prefix (ending with ``/``)."""
        key = self._to_key(directory)
        if key and not key.endswith("/"):
            key += "/"
        return key

    # -- ContentBackend interface --------------------------------------------

    def read_content(self, file_path: str) -> str | None:
        key = self._to_key(file_path)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read().decode("utf-8")
        except self._client.exceptions.NoSuchKey:
            return None

    def write_content(self, file_path: str, content: str) -> str:
        key = self._to_key(file_path)
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
        )
        return str(file_path)

    def delete_content(self, file_path: str) -> bool:
        key = self._to_key(file_path)
        # Check existence first (S3 delete is idempotent)
        if not self.exists(file_path):
            return False
        self._client.delete_object(Bucket=self._bucket, Key=key)
        return True

    def list_content(self, directory: str, suffix: str = ".md") -> list[str]:
        prefix = self._dir_to_prefix(directory)
        results: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if suffix and not key.endswith(suffix):
                    continue
                # Only direct children (no nested subdirectories)
                relative = key[len(prefix) :]
                if "/" not in relative:
                    results.append(key)
        return sorted(results)

    def list_content_recursive(self, prefix: str, suffix: str = ".md") -> list[str]:
        s3_prefix = self._to_key(prefix) if prefix else ""
        if s3_prefix and not s3_prefix.endswith("/"):
            s3_prefix += "/"
        results: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        kwargs: dict[str, Any] = {"Bucket": self._bucket, "Prefix": s3_prefix}
        for page in paginator.paginate(**kwargs):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not suffix or key.endswith(suffix):
                    results.append(key)
        return sorted(results)

    def exists(self, file_path: str) -> bool:
        key = self._to_key(file_path)
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except self._client.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] == "404":
                return False
            raise


# ============================================================================
# Content Manager
# ============================================================================


class ContentManager:
    """Manages markdown content files for PRDs, tasks, and design documents.

    This class handles:
    - Creating and organizing content directories
    - Reading/writing markdown files
    - Managing content file paths

    The low-level I/O is delegated to a ``ContentBackend`` instance.
    Production callers must supply an ``S3ContentBackend``; the
    ``LocalContentBackend`` fallback exists only for test isolation.
    """

    def __init__(
        self,
        base_path: Path | None = None,
        backend: ContentBackend | None = None,
    ):
        """Initialize content manager.

        Args:
            base_path: Custom base path (default: ~/.a-sdlc/content/).
            backend: Storage backend to use. Production callers must provide
                an ``S3ContentBackend``. Defaults to ``LocalContentBackend``
                for backward compatibility and test isolation.
        """
        self.base_path = base_path or (get_data_dir() / "content")
        self._backend = backend or LocalContentBackend()
        self._ensure_dirs()

    @property
    def backend(self) -> ContentBackend:
        """Return the active content backend."""
        return self._backend

    def _ensure_dirs(self) -> None:
        """Ensure base content directory exists (local backend only)."""
        if isinstance(self._backend, LocalContentBackend):
            self.base_path.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Path Management
    # =========================================================================

    def get_prd_dir(self, project_id: str) -> Path:
        """Get PRD directory for a project."""
        prd_dir = self.base_path / project_id / "prds"
        if isinstance(self._backend, LocalContentBackend):
            prd_dir.mkdir(parents=True, exist_ok=True)
        return prd_dir

    def get_task_dir(self, project_id: str) -> Path:
        """Get task directory for a project."""
        task_dir = self.base_path / project_id / "tasks"
        if isinstance(self._backend, LocalContentBackend):
            task_dir.mkdir(parents=True, exist_ok=True)
        return task_dir

    def get_prd_path(self, project_id: str, prd_id: str) -> Path:
        """Get path for PRD markdown file.

        Args:
            project_id: Project identifier
            prd_id: PRD identifier

        Returns:
            Path to PRD markdown file
        """
        return self.get_prd_dir(project_id) / f"{prd_id}.md"

    def get_task_path(self, project_id: str, task_id: str) -> Path:
        """Get path for task markdown file.

        Args:
            project_id: Project identifier
            task_id: Task identifier

        Returns:
            Path to task markdown file
        """
        return self.get_task_dir(project_id) / f"{task_id}.md"

    # =========================================================================
    # Content Read/Write (delegated to backend)
    # =========================================================================

    def read_content(self, file_path: Path | str) -> str | None:
        """Read content from markdown file.

        Args:
            file_path: Path to markdown file

        Returns:
            File content as string, or None if file doesn't exist
        """
        return self._backend.read_content(str(file_path))

    def write_content(self, file_path: Path | str, content: str) -> Path:
        """Write content to markdown file.

        Args:
            file_path: Path to markdown file
            content: Content to write

        Returns:
            Path to the written file
        """
        self._backend.write_content(str(file_path), content)
        return Path(file_path)

    def delete_content(self, file_path: Path | str) -> bool:
        """Delete a content file.

        Args:
            file_path: Path to file to delete

        Returns:
            True if file was deleted, False if it didn't exist
        """
        return self._backend.delete_content(str(file_path))

    # =========================================================================
    # PRD Content Operations
    # =========================================================================

    def write_prd(
        self,
        project_id: str,
        prd_id: str,
        title: str,
        content: str,
    ) -> Path:
        """Write PRD content to markdown file.

        Args:
            project_id: Project identifier
            prd_id: PRD identifier
            title: PRD title (included in file header)
            content: PRD markdown content

        Returns:
            Path to the written file
        """
        file_path = self.get_prd_path(project_id, prd_id)

        # Format with title header if content doesn't already have one
        if content.strip() and not content.strip().startswith("#"):
            full_content = f"# {title}\n\n{content}"
        elif not content.strip():
            full_content = f"# {title}\n\n"
        else:
            full_content = content

        return self.write_content(file_path, full_content)

    def read_prd(self, project_id: str, prd_id: str) -> str | None:
        """Read PRD content from markdown file.

        Args:
            project_id: Project identifier
            prd_id: PRD identifier

        Returns:
            PRD content as string, or None if not found
        """
        file_path = self.get_prd_path(project_id, prd_id)
        return self.read_content(file_path)

    def delete_prd(self, project_id: str, prd_id: str) -> bool:
        """Delete PRD content file.

        Args:
            project_id: Project identifier
            prd_id: PRD identifier

        Returns:
            True if deleted, False if not found
        """
        file_path = self.get_prd_path(project_id, prd_id)
        return self.delete_content(file_path)

    # =========================================================================
    # Task Content Operations
    # =========================================================================

    def write_task(
        self,
        project_id: str,
        task_id: str,
        title: str,
        description: str = "",
        priority: str = "medium",
        status: str = "pending",
        component: str | None = None,
        prd_id: str | None = None,
        dependencies: list[str] | None = None,
        data: dict[str, Any] | None = None,
        skip_if_exists: bool = False,
    ) -> Path:
        """Write task content to markdown file.

        If the description contains rich markdown content (e.g., from multi-agent
        workflow), it will be used as-is. Otherwise, a simple template is generated.

        Args:
            project_id: Project identifier
            task_id: Task identifier
            title: Task title
            description: Task description (can be full markdown content)
            priority: Task priority
            status: Task status
            component: Optional component name
            prd_id: Optional parent PRD ID
            dependencies: Optional list of dependency task IDs
            data: Optional additional data
            skip_if_exists: If True, skip writing if file already exists

        Returns:
            Path to the written file
        """
        file_path = self.get_task_path(project_id, task_id)

        # Skip if file exists and skip_if_exists is True
        if skip_if_exists and self._backend.exists(str(file_path)):
            return file_path

        # Check if description is rich content (contains markdown headers)
        # Rich content from Content Generation Agent will have ## headers
        is_rich_content = description and (
            "\n## " in description
            or description.strip().startswith("## ")
            or description.strip().startswith("# ")
        )

        if is_rich_content:
            # Use the rich content as-is, ensuring proper header
            if description.strip().startswith(f"# {task_id}:"):
                content = description
            elif description.strip().startswith("#"):
                # Has a header but not the standard task ID format
                content = description
            else:
                # Add standard task header
                content = f"# {task_id}: {title}\n\n{description}"
        else:
            # Generate simple template content
            # Extract dependencies from data if not provided
            if dependencies is None and data:
                dependencies = data.get("dependencies", [])

            deps_str = ", ".join(dependencies) if dependencies else "None"

            # Build optional traceability sections
            traces_section = ""
            if data and data.get("traces_to"):
                traces_items = "\n".join(f"- **{t}**" for t in data["traces_to"])
                traces_section = f"\n\n### Traces To\n\n{traces_items}"

            design_section = ""
            if data and data.get("design_compliance"):
                design_items = "\n".join(f"- **{d}**" for d in data["design_compliance"])
                design_section = f"\n\n### Design Compliance\n\n{design_items}"

            content = f"""# {task_id}: {title}

**Status:** {status}
**Priority:** {priority}
**Component:** {component or "N/A"}
**PRD:** {prd_id or "N/A"}
**Dependencies:** {deps_str}

## Description

{description or "_No description_"}
{traces_section}{design_section}"""

        return self.write_content(file_path, content)

    def write_task_content(
        self,
        project_id: str,
        task_id: str,
        content: str,
    ) -> Path:
        """Write raw task content directly to markdown file.

        Use this for multi-agent workflows where the Content Generation Agent
        produces the full task markdown content following the template.

        Args:
            project_id: Project identifier
            task_id: Task identifier
            content: Full markdown content for the task

        Returns:
            Path to the written file
        """
        file_path = self.get_task_path(project_id, task_id)
        return self.write_content(file_path, content)

    def task_file_exists(self, project_id: str, task_id: str) -> bool:
        """Check if a task content file exists.

        Args:
            project_id: Project identifier
            task_id: Task identifier

        Returns:
            True if the task file exists
        """
        file_path = self.get_task_path(project_id, task_id)
        return self._backend.exists(str(file_path))

    def read_task(self, project_id: str, task_id: str) -> str | None:
        """Read task content from markdown file.

        Args:
            project_id: Project identifier
            task_id: Task identifier

        Returns:
            Task content as string, or None if not found
        """
        file_path = self.get_task_path(project_id, task_id)
        return self.read_content(file_path)

    def delete_task(self, project_id: str, task_id: str) -> bool:
        """Delete task content file.

        Args:
            project_id: Project identifier
            task_id: Task identifier

        Returns:
            True if deleted, False if not found
        """
        file_path = self.get_task_path(project_id, task_id)
        return self.delete_content(file_path)

    def parse_task_content(self, content: str) -> dict[str, Any]:
        """Parse task markdown content to extract metadata.

        This is useful for extracting task data from manually edited files.

        Args:
            content: Markdown content of task file

        Returns:
            Dict with extracted task data (description, dependencies, etc.)
        """
        result: dict[str, Any] = {}

        # Extract description section
        desc_match = re.search(r"## Description\s*\n(.+?)(?:\n##|\Z)", content, re.DOTALL)
        if desc_match:
            desc = desc_match.group(1).strip()
            if desc != "_No description_":
                result["description"] = desc

        # Extract metadata from header
        lines = content.split("\n")
        for line in lines:
            if line.startswith("**Status:**"):
                result["status"] = line.split(":", 1)[1].strip().strip("*")
            elif line.startswith("**Priority:**"):
                result["priority"] = line.split(":", 1)[1].strip().strip("*")
            elif line.startswith("**Component:**"):
                component = line.split(":", 1)[1].strip().strip("*")
                if component != "N/A":
                    result["component"] = component
            elif line.startswith("**PRD:**"):
                prd_id = line.split(":", 1)[1].strip().strip("*")
                if prd_id != "N/A":
                    result["prd_id"] = prd_id
            elif line.startswith("**Dependencies:**"):
                deps_str = line.split(":", 1)[1].strip().strip("*")
                if deps_str != "None":
                    deps = [d.strip() for d in deps_str.split(",") if d.strip()]
                    if deps:
                        result["dependencies"] = deps

        return result

    # =========================================================================
    # Design Document Content Operations
    # =========================================================================

    def get_design_dir(self, project_id: str) -> Path:
        """Get design document directory for a project.

        Args:
            project_id: Project identifier

        Returns:
            Path to design documents directory
        """
        design_dir = self.base_path / project_id / "designs"
        if isinstance(self._backend, LocalContentBackend):
            design_dir.mkdir(parents=True, exist_ok=True)
        return design_dir

    def get_design_path(self, project_id: str, prd_id: str) -> Path:
        """Get path for design document markdown file.

        Design documents have a 1:1 relationship with PRDs,
        so the prd_id is used as the filename.

        Args:
            project_id: Project identifier
            prd_id: PRD identifier (used as filename)

        Returns:
            Path to design document markdown file
        """
        return self.get_design_dir(project_id) / f"{prd_id}.md"

    def write_design(self, project_id: str, prd_id: str, content: str) -> Path:
        """Write design document content to markdown file.

        Args:
            project_id: Project identifier
            prd_id: PRD identifier (used as filename)
            content: Design document markdown content

        Returns:
            Path to the written file
        """
        file_path = self.get_design_path(project_id, prd_id)
        return self.write_content(file_path, content)

    def read_design(self, project_id: str, prd_id: str) -> str | None:
        """Read design document content from markdown file.

        Args:
            project_id: Project identifier
            prd_id: PRD identifier

        Returns:
            Design document content as string, or None if not found
        """
        file_path = self.get_design_path(project_id, prd_id)
        return self.read_content(file_path)

    def delete_design(self, project_id: str, prd_id: str) -> bool:
        """Delete design document content file.

        Args:
            project_id: Project identifier
            prd_id: PRD identifier

        Returns:
            True if deleted, False if not found
        """
        file_path = self.get_design_path(project_id, prd_id)
        return self.delete_content(file_path)

    # =========================================================================
    # Project Operations
    # =========================================================================

    def delete_project_content(self, project_id: str) -> bool:
        """Delete all content files for a project.

        Args:
            project_id: Project identifier

        Returns:
            True if any content was deleted
        """
        project_dir = self.base_path / project_id
        if isinstance(self._backend, LocalContentBackend):
            if project_dir.exists():
                shutil.rmtree(project_dir)
                return True
            return False
        else:
            # For non-local backends, delete all known content subdirectories
            deleted_any = False
            for subdir in ("prds", "tasks", "designs"):
                dir_path = str(project_dir / subdir)
                for file_path in self._backend.list_content(dir_path, suffix=".md"):
                    self._backend.delete_content(file_path)
                    deleted_any = True
            return deleted_any

    def list_prd_files(self, project_id: str) -> list[Path]:
        """List all PRD files for a project.

        Args:
            project_id: Project identifier

        Returns:
            List of PRD file paths
        """
        prd_dir = self.base_path / project_id / "prds"
        paths = self._backend.list_content(str(prd_dir), suffix=".md")
        return sorted(Path(p) for p in paths)

    def list_task_files(self, project_id: str) -> list[Path]:
        """List all task files for a project.

        Args:
            project_id: Project identifier

        Returns:
            List of task file paths
        """
        task_dir = self.base_path / project_id / "tasks"
        paths = self._backend.list_content(str(task_dir), suffix=".md")
        return sorted(Path(p) for p in paths)

    def list_design_files(self, project_id: str) -> list[Path]:
        """List all design files for a project.

        Args:
            project_id: Project identifier

        Returns:
            List of design file paths
        """
        design_dir = self.base_path / project_id / "designs"
        paths = self._backend.list_content(str(design_dir), suffix=".md")
        return sorted(Path(p) for p in paths)


# Global content manager instance
_content_manager: ContentManager | None = None


def get_content_manager() -> ContentManager:
    """Get or create the global content manager instance."""
    global _content_manager
    if _content_manager is None:
        _content_manager = ContentManager()
    return _content_manager
