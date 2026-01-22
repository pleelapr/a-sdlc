"""
Local file-based task storage plugin.

Stores tasks as individual Markdown files in .sdlc/tasks/,
providing human-readable task tracking without external dependencies.
"""

import json
from datetime import datetime
from pathlib import Path

from a_sdlc.plugins.base import Task, TaskPlugin, TaskStatus


class LocalPlugin(TaskPlugin):
    """File-based task storage in .sdlc/tasks/.

    Tasks are stored as Markdown files with YAML frontmatter for
    metadata. This provides:
    - Human-readable task files
    - Git-trackable history
    - No external dependencies
    """

    DEFAULT_PATH = ".sdlc/tasks"

    def __init__(self, config: dict) -> None:
        """Initialize local plugin.

        Args:
            config: Configuration dict. Supports:
                - path: Custom path for task storage (default: .sdlc/tasks)
        """
        super().__init__(config)
        self.base_path = Path(config.get("path", self.DEFAULT_PATH))
        self.active_path = self.base_path / "active"
        self.completed_path = self.base_path / "completed"
        self.index_file = self.base_path / "index.json"

    def _ensure_dirs(self) -> None:
        """Ensure task directories exist."""
        self.active_path.mkdir(parents=True, exist_ok=True)
        self.completed_path.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> dict:
        """Load task index from file."""
        if self.index_file.exists():
            with open(self.index_file) as f:
                return json.load(f)
        return {"tasks": {}, "counter": 0}

    def _save_index(self, index: dict) -> None:
        """Save task index to file."""
        self._ensure_dirs()
        with open(self.index_file, "w") as f:
            json.dump(index, f, indent=2)

    def _get_task_path(self, task_id: str, status: TaskStatus) -> Path:
        """Get file path for a task based on its status."""
        if status == TaskStatus.COMPLETED:
            return self.completed_path / f"{task_id}.md"
        return self.active_path / f"{task_id}.md"

    def _task_to_markdown(self, task: Task) -> str:
        """Convert task to Markdown format with frontmatter."""
        # Build dependencies list
        deps_str = ""
        if task.dependencies:
            deps_str = ", ".join(task.dependencies)

        # Build file list
        files_str = ""
        if task.files_to_modify:
            files_str = "\n".join(f"- `{f}`" for f in task.files_to_modify)

        # Build implementation steps
        steps_str = ""
        if task.implementation_steps:
            steps_str = "\n".join(f"{i+1}. {step}" for i, step in enumerate(task.implementation_steps))

        # Build success criteria
        criteria_str = ""
        if task.success_criteria:
            criteria_str = "\n".join(f"- [ ] {c}" for c in task.success_criteria)

        content = f"""# {task.id}: {task.title}

**Status:** {task.status.value}
**Priority:** {task.priority.value}
**Requirement:** {task.requirement_id or 'N/A'}
**Component:** {task.component or 'N/A'}
**Dependencies:** {deps_str or 'None'}

## Description

{task.description}

## Files to Modify

{files_str or '_No files specified_'}

## Implementation Steps

{steps_str or '_No steps defined_'}

## Success Criteria

{criteria_str or '_No criteria defined_'}

---
**Created:** {task.created_at.isoformat()}
**Updated:** {task.updated_at.isoformat()}
"""

        if task.completed_at:
            content += f"**Completed:** {task.completed_at.isoformat()}\n"

        return content

    def _generate_task_id(self) -> str:
        """Generate a new unique task ID."""
        index = self._load_index()
        counter = index.get("counter", 0) + 1
        index["counter"] = counter
        self._save_index(index)
        return f"TASK-{counter:03d}"

    def create_task(self, task: Task) -> str:
        """Create a new task.

        If task.id is not set, generates a new ID.
        """
        self._ensure_dirs()

        # Generate ID if not provided
        if not task.id or task.id == "":
            task.id = self._generate_task_id()

        # Update index
        index = self._load_index()
        index["tasks"][task.id] = {
            "status": task.status.value,
            "title": task.title,
            "created_at": task.created_at.isoformat(),
        }
        self._save_index(index)

        # Write task file
        task_path = self._get_task_path(task.id, task.status)
        task_path.write_text(self._task_to_markdown(task))

        # Also save JSON for easy parsing
        json_path = task_path.with_suffix(".json")
        with open(json_path, "w") as f:
            json.dump(task.to_dict(), f, indent=2)

        return task.id

    def get_task(self, task_id: str) -> Task | None:
        """Retrieve a task by ID."""
        # Check active first
        json_path = self.active_path / f"{task_id}.json"
        if json_path.exists():
            with open(json_path) as f:
                return Task.from_dict(json.load(f))

        # Check completed
        json_path = self.completed_path / f"{task_id}.json"
        if json_path.exists():
            with open(json_path) as f:
                return Task.from_dict(json.load(f))

        return None

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        """List tasks, optionally filtered by status."""
        self._ensure_dirs()
        tasks = []

        # Collect from active directory
        if status is None or status != TaskStatus.COMPLETED:
            for json_file in self.active_path.glob("*.json"):
                with open(json_file) as f:
                    task = Task.from_dict(json.load(f))
                    if status is None or task.status == status:
                        tasks.append(task)

        # Collect from completed directory
        if status is None or status == TaskStatus.COMPLETED:
            for json_file in self.completed_path.glob("*.json"):
                with open(json_file) as f:
                    task = Task.from_dict(json.load(f))
                    tasks.append(task)

        # Sort by ID
        tasks.sort(key=lambda t: t.id)
        return tasks

    def update_task(self, task_id: str, updates: dict) -> None:
        """Update fields on a task."""
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")

        old_status = task.status

        # Apply updates
        for key, value in updates.items():
            if key == "status":
                task.status = TaskStatus(value) if isinstance(value, str) else value
            elif key == "priority":
                from a_sdlc.plugins.base import TaskPriority
                task.priority = TaskPriority(value) if isinstance(value, str) else value
            elif key == "completed_at":
                # Convert ISO string to datetime if needed
                if isinstance(value, str):
                    task.completed_at = datetime.fromisoformat(value)
                else:
                    task.completed_at = value
            elif hasattr(task, key):
                setattr(task, key, value)

        task.updated_at = datetime.now()

        # Handle status change (move between directories)
        if old_status != task.status:
            old_path = self._get_task_path(task_id, old_status)
            new_path = self._get_task_path(task_id, task.status)

            if old_path.exists():
                old_path.unlink()
            old_json = old_path.with_suffix(".json")
            if old_json.exists():
                old_json.unlink()

            # Write to new location
            new_path.write_text(self._task_to_markdown(task))
            with open(new_path.with_suffix(".json"), "w") as f:
                json.dump(task.to_dict(), f, indent=2)
        else:
            # Update in place
            task_path = self._get_task_path(task_id, task.status)
            task_path.write_text(self._task_to_markdown(task))
            with open(task_path.with_suffix(".json"), "w") as f:
                json.dump(task.to_dict(), f, indent=2)

        # Update index
        index = self._load_index()
        if task_id in index["tasks"]:
            index["tasks"][task_id]["status"] = task.status.value
            self._save_index(index)

    def complete_task(self, task_id: str) -> None:
        """Mark a task as completed."""
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")

        self.update_task(task_id, {
            "status": TaskStatus.COMPLETED.value,
            "completed_at": datetime.now().isoformat(),
        })

    def delete_task(self, task_id: str) -> None:
        """Delete a task."""
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")

        # Remove files
        task_path = self._get_task_path(task_id, task.status)
        if task_path.exists():
            task_path.unlink()
        json_path = task_path.with_suffix(".json")
        if json_path.exists():
            json_path.unlink()

        # Update index
        index = self._load_index()
        if task_id in index["tasks"]:
            del index["tasks"][task_id]
            self._save_index(index)
