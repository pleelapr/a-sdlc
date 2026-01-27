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


class SprintStatus(Enum):
    """Status of a sprint in the SDLC workflow."""
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"


class SyncStatus(Enum):
    """Sync status for external system integration."""
    SYNCED = "synced"
    PENDING = "pending"
    CONFLICT = "conflict"
    ERROR = "error"


@dataclass
class ExternalSprintMapping:
    """Maps a local sprint to an external system sprint/cycle.

    Used for bidirectional sync between a-sdlc sprints and
    external issue trackers like Linear (cycles) or Jira (sprints).
    """
    local_sprint_id: str          # SPRINT-001
    external_system: str          # "linear" or "jira"
    external_sprint_id: str       # Linear cycle ID or Jira sprint ID
    external_sprint_name: str     # Name in external system
    sync_status: SyncStatus = SyncStatus.PENDING
    last_synced_at: datetime | None = None

    def to_dict(self) -> dict:
        """Convert mapping to dictionary representation."""
        return {
            "local_sprint_id": self.local_sprint_id,
            "external_system": self.external_system,
            "external_sprint_id": self.external_sprint_id,
            "external_sprint_name": self.external_sprint_name,
            "sync_status": self.sync_status.value,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExternalSprintMapping":
        """Create mapping from dictionary representation."""
        return cls(
            local_sprint_id=data["local_sprint_id"],
            external_system=data["external_system"],
            external_sprint_id=data["external_sprint_id"],
            external_sprint_name=data["external_sprint_name"],
            sync_status=SyncStatus(data.get("sync_status", "pending")),
            last_synced_at=datetime.fromisoformat(data["last_synced_at"]) if data.get("last_synced_at") else None,
        )



@dataclass
class ImplementationStep:
    """A single implementation step with optional code hint and test expectation.

    Supports rich implementation step structure for detailed task guidance.
    """
    title: str
    description: str = ""
    code_hint: str | None = None
    test_expectation: str | None = None

    def to_dict(self) -> dict:
        """Convert step to dictionary representation."""
        result = {
            "title": self.title,
            "description": self.description,
        }
        if self.code_hint:
            result["code_hint"] = self.code_hint
        if self.test_expectation:
            result["test_expectation"] = self.test_expectation
        return result

    @classmethod
    def from_dict(cls, data: dict | str) -> "ImplementationStep":
        """Create step from dictionary or plain string (backward compatibility)."""
        if isinstance(data, str):
            # Backward compatibility: plain string becomes title
            return cls(title=data, description="")
        return cls(
            title=data.get("title", ""),
            description=data.get("description", ""),
            code_hint=data.get("code_hint"),
            test_expectation=data.get("test_expectation"),
        )

@dataclass
class Task:
    """Represents a task in the SDLC workflow.

    Tasks are generated from requirements and tracked through
    completion. They can be stored locally or synced to external
    systems like Linear.

    Note:
        Tasks no longer have direct sprint_id. Sprint membership is
        derived from the parent PRD's sprint_id assignment.
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
    implementation_steps: list[ImplementationStep] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    external_id: str | None = None  # ID in external system (e.g., Linear)
    external_url: str | None = None  # URL in external system

    # New fields for comprehensive task definition
    goal: str | None = None  # Clear statement of task purpose
    prd_ref: str | None = None  # Reference to source PRD file (also prd_id)
    key_requirements: list[str] = field(default_factory=list)  # Requirements from PRD
    technical_notes: list[str] = field(default_factory=list)  # Implementation hints
    deliverables: list[str] = field(default_factory=list)  # What will be produced
    exclusions: list[str] = field(default_factory=list)  # What is NOT in scope
    scope_constraint: str | None = None  # Standard reminder text

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
            "implementation_steps": [
                step.to_dict() if isinstance(step, ImplementationStep) else step
                for step in self.implementation_steps
            ],
            "success_criteria": self.success_criteria,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "external_id": self.external_id,
            "external_url": self.external_url,
            # New fields
            "goal": self.goal,
            "prd_ref": self.prd_ref,
            "key_requirements": self.key_requirements,
            "technical_notes": self.technical_notes,
            "deliverables": self.deliverables,
            "exclusions": self.exclusions,
            "scope_constraint": self.scope_constraint,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """Create task from dictionary representation.

        Supports backward compatibility for:
        - Plain string implementation_steps (converted to ImplementationStep)
        - Missing new fields (default to None/empty list)
        - Legacy sprint_id field (ignored, sprint derived from PRD)
        """
        # Parse implementation_steps with backward compatibility
        raw_steps = data.get("implementation_steps", [])
        implementation_steps = [
            ImplementationStep.from_dict(step) for step in raw_steps
        ]

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
            implementation_steps=implementation_steps,
            success_criteria=data.get("success_criteria", []),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            external_id=data.get("external_id"),
            external_url=data.get("external_url"),
            # New fields with backward-compatible defaults
            goal=data.get("goal"),
            prd_ref=data.get("prd_ref"),
            key_requirements=data.get("key_requirements", []),
            technical_notes=data.get("technical_notes", []),
            deliverables=data.get("deliverables", []),
            exclusions=data.get("exclusions", []),
            scope_constraint=data.get("scope_constraint"),
        )


@dataclass
class Sprint:
    """Represents a sprint in the SDLC workflow.

    Sprints group PRDs for execution planning and
    provide iteration-based progress tracking.

    Note:
        Tasks are no longer directly assigned to sprints.
        Sprint membership is derived from PRD assignment.
    """
    id: str
    name: str
    status: SprintStatus = SprintStatus.PLANNED
    goal: str = ""
    start_date: datetime | None = None
    end_date: datetime | None = None
    prd_ids: list[str] = field(default_factory=list)  # PRDs in this sprint
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    # External system integration fields
    external_id: str | None = None       # External sprint/cycle ID
    external_url: str | None = None      # URL to external sprint
    external_system: str | None = None   # "linear" or "jira"

    def to_dict(self) -> dict:
        """Convert sprint to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "goal": self.goal,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "prd_ids": self.prd_ids,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "external_id": self.external_id,
            "external_url": self.external_url,
            "external_system": self.external_system,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Sprint":
        """Create sprint from dictionary representation.

        Supports backward compatibility for legacy task_ids field.
        """
        return cls(
            id=data["id"],
            name=data["name"],
            status=SprintStatus(data.get("status", "planned")),
            goal=data.get("goal", ""),
            start_date=datetime.fromisoformat(data["start_date"]) if data.get("start_date") else None,
            end_date=datetime.fromisoformat(data["end_date"]) if data.get("end_date") else None,
            prd_ids=data.get("prd_ids", data.get("task_ids", [])),  # Backward compat
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            external_id=data.get("external_id"),
            external_url=data.get("external_url"),
            external_system=data.get("external_system"),
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
