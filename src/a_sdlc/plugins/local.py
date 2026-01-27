"""
Local file-based task storage plugin.

Stores tasks as individual Markdown files in .sdlc/tasks/,
providing human-readable task tracking without external dependencies.
"""

import json
from datetime import datetime
from pathlib import Path

from a_sdlc.plugins.base import (
    Task, TaskPlugin, TaskStatus, Sprint, SprintStatus,
    ExternalSprintMapping, SyncStatus
)


class LocalPlugin(TaskPlugin):
    """File-based task storage in .sdlc/tasks/.

    Tasks are stored as Markdown files with YAML frontmatter for
    metadata. This provides:
    - Human-readable task files
    - Git-trackable history
    - No external dependencies
    """

    DEFAULT_PATH = ".sdlc/tasks"
    DEFAULT_SPRINT_PATH = ".sdlc/sprints"

    def __init__(self, config: dict) -> None:
        """Initialize local plugin.

        Args:
            config: Configuration dict. Supports:
                - path: Custom path for task storage (default: .sdlc/tasks)
                - sprint_path: Custom path for sprint storage (default: .sdlc/sprints)
        """
        super().__init__(config)
        self.base_path = Path(config.get("path", self.DEFAULT_PATH))
        self.active_path = self.base_path / "active"
        self.completed_path = self.base_path / "completed"
        self.index_file = self.base_path / "index.json"

        # Sprint storage paths
        self.sprint_base_path = Path(config.get("sprint_path", self.DEFAULT_SPRINT_PATH))
        self.sprint_active_path = self.sprint_base_path / "active"
        self.sprint_completed_path = self.sprint_base_path / "completed"
        self.sprint_index_file = self.sprint_base_path / "index.json"
        self.sprint_mappings_file = self.sprint_base_path / "mappings.json"

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
**PRD:** {task.prd_ref or 'N/A'}
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

    # Sprint storage methods

    def _ensure_sprint_dirs(self) -> None:
        """Ensure sprint directories exist."""
        self.sprint_active_path.mkdir(parents=True, exist_ok=True)
        self.sprint_completed_path.mkdir(parents=True, exist_ok=True)

    def _load_sprint_index(self) -> dict:
        """Load sprint index from file."""
        if self.sprint_index_file.exists():
            with open(self.sprint_index_file) as f:
                return json.load(f)
        return {"sprints": {}, "counter": 0}

    def _save_sprint_index(self, index: dict) -> None:
        """Save sprint index to file."""
        self._ensure_sprint_dirs()
        with open(self.sprint_index_file, "w") as f:
            json.dump(index, f, indent=2)

    def _get_sprint_path(self, sprint_id: str, status: SprintStatus) -> Path:
        """Get file path for a sprint based on its status."""
        if status == SprintStatus.COMPLETED:
            return self.sprint_completed_path / f"{sprint_id}.json"
        return self.sprint_active_path / f"{sprint_id}.json"

    def _generate_sprint_id(self) -> str:
        """Generate a new unique sprint ID."""
        index = self._load_sprint_index()
        counter = index.get("counter", 0) + 1
        index["counter"] = counter
        self._save_sprint_index(index)
        return f"SPRINT-{counter:03d}"

    def create_sprint(self, sprint: Sprint) -> str:
        """Create a new sprint.

        If sprint.id is not set, generates a new ID.
        """
        self._ensure_sprint_dirs()

        # Generate ID if not provided
        if not sprint.id or sprint.id == "":
            sprint.id = self._generate_sprint_id()

        # Update index
        index = self._load_sprint_index()
        index["sprints"][sprint.id] = {
            "status": sprint.status.value,
            "name": sprint.name,
            "created_at": sprint.created_at.isoformat(),
        }
        self._save_sprint_index(index)

        # Write sprint file
        sprint_path = self._get_sprint_path(sprint.id, sprint.status)
        with open(sprint_path, "w") as f:
            json.dump(sprint.to_dict(), f, indent=2)

        return sprint.id

    def get_sprint(self, sprint_id: str) -> Sprint | None:
        """Retrieve a sprint by ID."""
        # Check active first
        json_path = self.sprint_active_path / f"{sprint_id}.json"
        if json_path.exists():
            with open(json_path) as f:
                return Sprint.from_dict(json.load(f))

        # Check completed
        json_path = self.sprint_completed_path / f"{sprint_id}.json"
        if json_path.exists():
            with open(json_path) as f:
                return Sprint.from_dict(json.load(f))

        return None

    def list_sprints(self, status: SprintStatus | None = None) -> list[Sprint]:
        """List sprints, optionally filtered by status."""
        self._ensure_sprint_dirs()
        sprints = []

        # Collect from active directory
        if status is None or status != SprintStatus.COMPLETED:
            for json_file in self.sprint_active_path.glob("*.json"):
                with open(json_file) as f:
                    sprint = Sprint.from_dict(json.load(f))
                    if status is None or sprint.status == status:
                        sprints.append(sprint)

        # Collect from completed directory
        if status is None or status == SprintStatus.COMPLETED:
            for json_file in self.sprint_completed_path.glob("*.json"):
                with open(json_file) as f:
                    sprint = Sprint.from_dict(json.load(f))
                    sprints.append(sprint)

        # Sort by ID
        sprints.sort(key=lambda s: s.id)
        return sprints

    def update_sprint(self, sprint_id: str, updates: dict) -> None:
        """Update fields on a sprint."""
        sprint = self.get_sprint(sprint_id)
        if sprint is None:
            raise KeyError(f"Sprint not found: {sprint_id}")

        old_status = sprint.status

        # Apply updates
        for key, value in updates.items():
            if key == "status":
                sprint.status = SprintStatus(value) if isinstance(value, str) else value
            elif key == "start_date":
                if isinstance(value, str):
                    sprint.start_date = datetime.fromisoformat(value)
                else:
                    sprint.start_date = value
            elif key == "end_date":
                if isinstance(value, str):
                    sprint.end_date = datetime.fromisoformat(value)
                else:
                    sprint.end_date = value
            elif key == "completed_at":
                if isinstance(value, str):
                    sprint.completed_at = datetime.fromisoformat(value)
                else:
                    sprint.completed_at = value
            elif hasattr(sprint, key):
                setattr(sprint, key, value)

        # Handle status change (move between directories)
        if old_status != sprint.status:
            old_path = self._get_sprint_path(sprint_id, old_status)
            new_path = self._get_sprint_path(sprint_id, sprint.status)

            if old_path.exists():
                old_path.unlink()

            # Write to new location
            with open(new_path, "w") as f:
                json.dump(sprint.to_dict(), f, indent=2)
        else:
            # Update in place
            sprint_path = self._get_sprint_path(sprint_id, sprint.status)
            with open(sprint_path, "w") as f:
                json.dump(sprint.to_dict(), f, indent=2)

        # Update index
        index = self._load_sprint_index()
        if sprint_id in index["sprints"]:
            index["sprints"][sprint_id]["status"] = sprint.status.value
            self._save_sprint_index(index)

    def complete_sprint(self, sprint_id: str) -> None:
        """Mark a sprint as completed."""
        sprint = self.get_sprint(sprint_id)
        if sprint is None:
            raise KeyError(f"Sprint not found: {sprint_id}")

        self.update_sprint(sprint_id, {
            "status": SprintStatus.COMPLETED.value,
            "completed_at": datetime.now().isoformat(),
        })

    def get_active_sprint(self) -> Sprint | None:
        """Get the currently active sprint, if any.

        Returns:
            The active sprint, or None if no sprint is active.
        """
        active_sprints = self.list_sprints(SprintStatus.ACTIVE)
        return active_sprints[0] if active_sprints else None

    def add_task_to_sprint(self, sprint_id: str, task_id: str) -> None:
        """Add a task to a sprint."""
        sprint = self.get_sprint(sprint_id)
        if sprint is None:
            raise KeyError(f"Sprint not found: {sprint_id}")

        if task_id not in sprint.task_ids:
            sprint.task_ids.append(task_id)
            self.update_sprint(sprint_id, {"task_ids": sprint.task_ids})

        # Also update the task's sprint_id
        task = self.get_task(task_id)
        if task:
            self.update_task(task_id, {"sprint_id": sprint_id})

    def remove_task_from_sprint(self, sprint_id: str, task_id: str) -> None:
        """Remove a task from a sprint."""
        sprint = self.get_sprint(sprint_id)
        if sprint is None:
            raise KeyError(f"Sprint not found: {sprint_id}")

        if task_id in sprint.task_ids:
            sprint.task_ids.remove(task_id)
            self.update_sprint(sprint_id, {"task_ids": sprint.task_ids})

        # Also clear the task's sprint_id
        task = self.get_task(task_id)
        if task:
            self.update_task(task_id, {"sprint_id": None})

    def get_sprint_tasks(self, sprint_id: str) -> list[Task]:
        """Get all tasks in a sprint."""
        sprint = self.get_sprint(sprint_id)
        if sprint is None:
            raise KeyError(f"Sprint not found: {sprint_id}")

        tasks = []
        for task_id in sprint.task_ids:
            task = self.get_task(task_id)
            if task:
                tasks.append(task)

        return tasks

    # ─────────────────────────────────────────────────────────────────────────
    # Sprint Mapping Methods (External System Sync)
    # ─────────────────────────────────────────────────────────────────────────

    def _load_sprint_mappings(self) -> dict:
        """Load sprint mappings from file."""
        if self.sprint_mappings_file.exists():
            with open(self.sprint_mappings_file) as f:
                return json.load(f)
        return {}

    def _save_sprint_mappings(self, mappings: dict) -> None:
        """Save sprint mappings to file."""
        self._ensure_sprint_dirs()
        with open(self.sprint_mappings_file, "w") as f:
            json.dump(mappings, f, indent=2)

    def save_sprint_mapping(self, mapping: ExternalSprintMapping) -> None:
        """Save or update a sprint mapping.

        Args:
            mapping: ExternalSprintMapping to save
        """
        mappings = self._load_sprint_mappings()
        mappings[mapping.local_sprint_id] = mapping.to_dict()
        self._save_sprint_mappings(mappings)

        # Also update the sprint's external fields
        sprint = self.get_sprint(mapping.local_sprint_id)
        if sprint:
            self.update_sprint(mapping.local_sprint_id, {
                "external_id": mapping.external_sprint_id,
                "external_system": mapping.external_system,
            })

    def get_sprint_mapping(self, sprint_id: str) -> ExternalSprintMapping | None:
        """Get mapping for a sprint.

        Args:
            sprint_id: Local sprint ID

        Returns:
            ExternalSprintMapping if exists, None otherwise
        """
        mappings = self._load_sprint_mappings()
        if sprint_id in mappings:
            return ExternalSprintMapping.from_dict(mappings[sprint_id])
        return None

    def list_sprint_mappings(self) -> list[ExternalSprintMapping]:
        """List all sprint mappings.

        Returns:
            List of all ExternalSprintMapping objects
        """
        mappings = self._load_sprint_mappings()
        return [ExternalSprintMapping.from_dict(m) for m in mappings.values()]

    def delete_sprint_mapping(self, sprint_id: str) -> None:
        """Delete a sprint mapping (unlink from external system).

        Args:
            sprint_id: Local sprint ID to unlink

        Raises:
            KeyError: If mapping doesn't exist
        """
        mappings = self._load_sprint_mappings()
        if sprint_id not in mappings:
            raise KeyError(f"No mapping found for sprint: {sprint_id}")

        del mappings[sprint_id]
        self._save_sprint_mappings(mappings)

        # Also clear the sprint's external fields
        sprint = self.get_sprint(sprint_id)
        if sprint:
            self.update_sprint(sprint_id, {
                "external_id": None,
                "external_url": None,
                "external_system": None,
            })

    def update_sprint_mapping_status(
        self,
        sprint_id: str,
        sync_status: SyncStatus,
        last_synced_at: datetime | None = None
    ) -> None:
        """Update the sync status of a sprint mapping.

        Args:
            sprint_id: Local sprint ID
            sync_status: New sync status
            last_synced_at: Timestamp of last sync (defaults to now)
        """
        mapping = self.get_sprint_mapping(sprint_id)
        if mapping is None:
            raise KeyError(f"No mapping found for sprint: {sprint_id}")

        mapping.sync_status = sync_status
        mapping.last_synced_at = last_synced_at or datetime.now()
        self.save_sprint_mapping(mapping)

    def get_sprints_by_external_system(self, system: str) -> list[Sprint]:
        """Get all sprints linked to a specific external system.

        Args:
            system: External system name ("linear" or "jira")

        Returns:
            List of sprints linked to that system
        """
        all_sprints = self.list_sprints()
        return [s for s in all_sprints if s.external_system == system]

    def find_sprint_by_external_id(self, external_id: str) -> Sprint | None:
        """Find a sprint by its external system ID.

        Args:
            external_id: External sprint/cycle ID

        Returns:
            Sprint if found, None otherwise
        """
        all_sprints = self.list_sprints()
        for sprint in all_sprints:
            if sprint.external_id == external_id:
                return sprint
        return None
