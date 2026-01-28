"""
Content directory manager for a-sdlc.

Manages markdown content files that serve as the source of truth
for PRD and task content. The SQLite database stores metadata and
file path references; this module manages the actual content files.

Directory structure:
    ~/.a-sdlc/content/
    └── {project}/
        ├── prds/
        │   └── {prd-id}.md     # Full PRD content (LLM-generated)
        └── tasks/
            └── TASK-001.md     # Full task content (LLM-generated)
"""

import os
import platform
import re
import shutil
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


class ContentManager:
    """Manages markdown content files for PRDs and tasks.

    This class handles:
    - Creating and organizing content directories
    - Reading/writing markdown files
    - Managing content file paths
    """

    def __init__(self, base_path: Path | None = None):
        """Initialize content manager.

        Args:
            base_path: Custom base path (default: ~/.a-sdlc/content/)
        """
        self.base_path = base_path or (get_data_dir() / "content")
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Ensure base content directory exists."""
        self.base_path.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Path Management
    # =========================================================================

    def get_prd_dir(self, project_id: str) -> Path:
        """Get PRD directory for a project."""
        prd_dir = self.base_path / project_id / "prds"
        prd_dir.mkdir(parents=True, exist_ok=True)
        return prd_dir

    def get_task_dir(self, project_id: str) -> Path:
        """Get task directory for a project."""
        task_dir = self.base_path / project_id / "tasks"
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
    # Content Read/Write
    # =========================================================================

    def read_content(self, file_path: Path | str) -> str | None:
        """Read content from markdown file.

        Args:
            file_path: Path to markdown file

        Returns:
            File content as string, or None if file doesn't exist
        """
        path = Path(file_path)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def write_content(self, file_path: Path | str, content: str) -> Path:
        """Write content to markdown file.

        Args:
            file_path: Path to markdown file
            content: Content to write

        Returns:
            Path to the written file
        """
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def delete_content(self, file_path: Path | str) -> bool:
        """Delete a content file.

        Args:
            file_path: Path to file to delete

        Returns:
            True if file was deleted, False if it didn't exist
        """
        path = Path(file_path)
        if path.exists():
            path.unlink()
            return True
        return False

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
    ) -> Path:
        """Write task content to markdown file.

        Args:
            project_id: Project identifier
            task_id: Task identifier
            title: Task title
            description: Task description
            priority: Task priority
            status: Task status
            component: Optional component name
            prd_id: Optional parent PRD ID
            dependencies: Optional list of dependency task IDs
            data: Optional additional data

        Returns:
            Path to the written file
        """
        file_path = self.get_task_path(project_id, task_id)

        # Extract dependencies from data if not provided
        if dependencies is None and data:
            dependencies = data.get("dependencies", [])

        deps_str = ", ".join(dependencies) if dependencies else "None"

        content = f"""# {task_id}: {title}

**Status:** {status}
**Priority:** {priority}
**Component:** {component or 'N/A'}
**PRD:** {prd_id or 'N/A'}
**Dependencies:** {deps_str}

## Description

{description or '_No description_'}
"""

        return self.write_content(file_path, content)

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
        desc_match = re.search(r'## Description\s*\n(.+?)(?:\n##|\Z)', content, re.DOTALL)
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
        if project_dir.exists():
            shutil.rmtree(project_dir)
            return True
        return False

    def list_prd_files(self, project_id: str) -> list[Path]:
        """List all PRD files for a project.

        Args:
            project_id: Project identifier

        Returns:
            List of PRD file paths
        """
        prd_dir = self.base_path / project_id / "prds"
        if not prd_dir.exists():
            return []
        return sorted(prd_dir.glob("*.md"))

    def list_task_files(self, project_id: str) -> list[Path]:
        """List all task files for a project.

        Args:
            project_id: Project identifier

        Returns:
            List of task file paths
        """
        task_dir = self.base_path / project_id / "tasks"
        if not task_dir.exists():
            return []
        return sorted(task_dir.glob("*.md"))


# Global content manager instance
_content_manager: ContentManager | None = None


def get_content_manager() -> ContentManager:
    """Get or create the global content manager instance."""
    global _content_manager
    if _content_manager is None:
        _content_manager = ContentManager()
    return _content_manager
