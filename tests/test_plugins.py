"""Tests for plugin system."""

import pytest
from pathlib import Path
import tempfile
import json

from a_sdlc.plugins.base import Task, TaskStatus, TaskPriority
from a_sdlc.plugins.local import LocalPlugin


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def local_plugin(temp_dir: Path) -> LocalPlugin:
    """Create LocalPlugin with temp directory."""
    return LocalPlugin({"path": str(temp_dir / "tasks")})


def test_task_dataclass() -> None:
    """Test Task dataclass creation."""
    task = Task(
        id="TASK-001",
        title="Test Task",
        description="A test task",
        status=TaskStatus.PENDING,
        priority=TaskPriority.HIGH,
    )

    assert task.id == "TASK-001"
    assert task.title == "Test Task"
    assert task.status == TaskStatus.PENDING
    assert task.priority == TaskPriority.HIGH


def test_task_to_dict() -> None:
    """Test Task serialization."""
    task = Task(
        id="TASK-001",
        title="Test Task",
        description="A test task",
    )

    data = task.to_dict()

    assert data["id"] == "TASK-001"
    assert data["title"] == "Test Task"
    assert data["status"] == "pending"
    assert data["priority"] == "medium"


def test_task_from_dict() -> None:
    """Test Task deserialization."""
    data = {
        "id": "TASK-001",
        "title": "Test Task",
        "description": "A test task",
        "status": "in_progress",
        "priority": "high",
        "created_at": "2025-01-21T12:00:00",
        "updated_at": "2025-01-21T12:00:00",
    }

    task = Task.from_dict(data)

    assert task.id == "TASK-001"
    assert task.status == TaskStatus.IN_PROGRESS
    assert task.priority == TaskPriority.HIGH


def test_local_plugin_create_task(local_plugin: LocalPlugin) -> None:
    """Test creating a task with LocalPlugin."""
    task = Task(
        id="",  # Auto-generate
        title="Test Task",
        description="A test task",
    )

    task_id = local_plugin.create_task(task)

    assert task_id == "TASK-001"
    assert (local_plugin.active_path / "TASK-001.md").exists()
    assert (local_plugin.active_path / "TASK-001.json").exists()


def test_local_plugin_get_task(local_plugin: LocalPlugin) -> None:
    """Test retrieving a task."""
    task = Task(
        id="",
        title="Test Task",
        description="A test task",
    )

    task_id = local_plugin.create_task(task)
    retrieved = local_plugin.get_task(task_id)

    assert retrieved is not None
    assert retrieved.id == task_id
    assert retrieved.title == "Test Task"


def test_local_plugin_list_tasks(local_plugin: LocalPlugin) -> None:
    """Test listing tasks."""
    # Create multiple tasks
    for i in range(3):
        task = Task(
            id="",
            title=f"Task {i}",
            description=f"Description {i}",
        )
        local_plugin.create_task(task)

    tasks = local_plugin.list_tasks()

    assert len(tasks) == 3


def test_local_plugin_list_tasks_by_status(local_plugin: LocalPlugin) -> None:
    """Test listing tasks filtered by status."""
    # Create pending task
    task1 = Task(id="", title="Pending", description="", status=TaskStatus.PENDING)
    local_plugin.create_task(task1)

    # Create and complete another task
    task2 = Task(id="", title="To Complete", description="")
    task_id = local_plugin.create_task(task2)
    local_plugin.complete_task(task_id)

    pending = local_plugin.list_tasks(TaskStatus.PENDING)
    completed = local_plugin.list_tasks(TaskStatus.COMPLETED)

    assert len(pending) == 1
    assert len(completed) == 1


def test_local_plugin_complete_task(local_plugin: LocalPlugin) -> None:
    """Test completing a task."""
    task = Task(id="", title="Test", description="")
    task_id = local_plugin.create_task(task)

    local_plugin.complete_task(task_id)

    # Should be in completed directory now
    assert (local_plugin.completed_path / f"{task_id}.md").exists()
    assert not (local_plugin.active_path / f"{task_id}.md").exists()

    retrieved = local_plugin.get_task(task_id)
    assert retrieved is not None
    assert retrieved.status == TaskStatus.COMPLETED
    assert retrieved.completed_at is not None


def test_local_plugin_update_task(local_plugin: LocalPlugin) -> None:
    """Test updating a task."""
    task = Task(id="", title="Original", description="")
    task_id = local_plugin.create_task(task)

    local_plugin.update_task(task_id, {"title": "Updated"})

    retrieved = local_plugin.get_task(task_id)
    assert retrieved is not None
    assert retrieved.title == "Updated"


def test_local_plugin_delete_task(local_plugin: LocalPlugin) -> None:
    """Test deleting a task."""
    task = Task(id="", title="To Delete", description="")
    task_id = local_plugin.create_task(task)

    local_plugin.delete_task(task_id)

    assert local_plugin.get_task(task_id) is None
    assert not (local_plugin.active_path / f"{task_id}.md").exists()
