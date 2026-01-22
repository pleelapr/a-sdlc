"""
Base interface for task storage plugins.

All task storage backends must implement the TaskPlugin interface
to ensure consistent behavior across different storage mechanisms.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TaskStatus(Enum):
    """Status of a task in the SDLC workflow."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Priority level for tasks."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class Task:
    """Represents a task in the SDLC workflow.

    Tasks are generated from requirements and tracked through
    completion. They can be stored locally or synced to external
    systems like Linear.
    """
    id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    dependencies: list[str] = field(default_factory=list)
    requirement_id: str | None = None
    component: str | None = None
    files_to_modify: list[str] = field(default_factory=list)
    implementation_steps: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    external_id: str | None = None  # ID in external system (e.g., Linear)
    external_url: str | None = None  # URL in external system

    def to_dict(self) -> dict:
        """Convert task to dictionary representation."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "dependencies": self.dependencies,
            "requirement_id": self.requirement_id,
            "component": self.component,
            "files_to_modify": self.files_to_modify,
            "implementation_steps": self.implementation_steps,
            "success_criteria": self.success_criteria,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "external_id": self.external_id,
            "external_url": self.external_url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """Create task from dictionary representation."""
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            status=TaskStatus(data.get("status", "pending")),
            priority=TaskPriority(data.get("priority", "medium")),
            dependencies=data.get("dependencies", []),
            requirement_id=data.get("requirement_id"),
            component=data.get("component"),
            files_to_modify=data.get("files_to_modify", []),
            implementation_steps=data.get("implementation_steps", []),
            success_criteria=data.get("success_criteria", []),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            external_id=data.get("external_id"),
            external_url=data.get("external_url"),
        )


class TaskPlugin(ABC):
    """Base interface for task storage plugins.

    Plugins handle the storage and retrieval of tasks, whether
    that's local file storage or external issue trackers.
    """

    def __init__(self, config: dict) -> None:
        """Initialize plugin with configuration.

        Args:
            config: Plugin-specific configuration dict.
        """
        self.config = config

    @abstractmethod
    def create_task(self, task: Task) -> str:
        """Create a new task.

        Args:
            task: Task to create.

        Returns:
            Task ID (may differ from task.id if external system assigns ID).
        """
        pass

    @abstractmethod
    def get_task(self, task_id: str) -> Task | None:
        """Retrieve a task by ID.

        Args:
            task_id: ID of task to retrieve.

        Returns:
            Task if found, None otherwise.
        """
        pass

    @abstractmethod
    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        """List tasks, optionally filtered by status.

        Args:
            status: Filter by this status. If None, returns all tasks.

        Returns:
            List of tasks matching criteria.
        """
        pass

    @abstractmethod
    def update_task(self, task_id: str, updates: dict) -> None:
        """Update fields on a task.

        Args:
            task_id: ID of task to update.
            updates: Dict of field names to new values.

        Raises:
            KeyError: If task doesn't exist.
        """
        pass

    @abstractmethod
    def complete_task(self, task_id: str) -> None:
        """Mark a task as completed.

        Sets status to COMPLETED and records completion timestamp.

        Args:
            task_id: ID of task to complete.

        Raises:
            KeyError: If task doesn't exist.
        """
        pass

    @abstractmethod
    def delete_task(self, task_id: str) -> None:
        """Delete a task.

        Args:
            task_id: ID of task to delete.

        Raises:
            KeyError: If task doesn't exist.
        """
        pass

    def start_task(self, task_id: str) -> None:
        """Mark a task as in progress.

        Args:
            task_id: ID of task to start.
        """
        self.update_task(task_id, {"status": TaskStatus.IN_PROGRESS.value})

    def block_task(self, task_id: str, reason: str | None = None) -> None:
        """Mark a task as blocked.

        Args:
            task_id: ID of task to block.
            reason: Optional reason for blocking.
        """
        updates = {"status": TaskStatus.BLOCKED.value}
        if reason:
            updates["blocked_reason"] = reason
        self.update_task(task_id, updates)

    def get_active_task(self) -> Task | None:
        """Get the currently in-progress task, if any.

        Returns:
            The active task, or None if no task is in progress.
        """
        in_progress = self.list_tasks(TaskStatus.IN_PROGRESS)
        return in_progress[0] if in_progress else None
