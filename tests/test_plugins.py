"""Tests for plugin system."""

from a_sdlc.plugins.base import Task, TaskPriority, TaskStatus


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


def test_task_from_dict_backward_compatibility() -> None:
    """Test Task deserialization with old format (plain string implementation_steps)."""
    data = {
        "id": "TASK-001",
        "title": "Test Task",
        "description": "A test task",
        "status": "pending",
        "priority": "medium",
        "implementation_steps": ["Step 1", "Step 2", "Step 3"],  # Old format: plain strings
        "created_at": "2025-01-21T12:00:00",
        "updated_at": "2025-01-21T12:00:00",
    }

    task = Task.from_dict(data)

    assert task.id == "TASK-001"
    assert len(task.implementation_steps) == 3
    # Should be converted to ImplementationStep objects
    assert task.implementation_steps[0].title == "Step 1"
    assert task.implementation_steps[0].description == ""


def test_task_from_dict_rich_implementation_steps() -> None:
    """Test Task deserialization with new format (rich implementation_steps)."""
    data = {
        "id": "TASK-001",
        "title": "Test Task",
        "description": "A test task",
        "status": "pending",
        "implementation_steps": [
            {
                "title": "Create config dataclass",
                "description": "Define configuration structure",
                "code_hint": "@dataclass\nclass Config:\n    pass",
                "test_expectation": "Config instantiates without errors",
            },
            {
                "title": "Add loader",
                "description": "Load from environment",
            },
        ],
        "goal": "Set up OAuth configuration",
        "prd_ref": "auth-feature.md",
        "key_requirements": ["Support Google OAuth", "Support GitHub OAuth"],
        "technical_notes": ["Use existing patterns", "Follow ConfigLoader"],
        "deliverables": ["OAuth config class", "Loader function"],
        "exclusions": ["UI changes", "Token refresh"],
        "scope_constraint": "Only modify auth module",
        "created_at": "2025-01-21T12:00:00",
        "updated_at": "2025-01-21T12:00:00",
    }

    task = Task.from_dict(data)

    assert task.id == "TASK-001"
    assert len(task.implementation_steps) == 2
    assert task.implementation_steps[0].title == "Create config dataclass"
    assert task.implementation_steps[0].code_hint == "@dataclass\nclass Config:\n    pass"
    assert task.implementation_steps[0].test_expectation == "Config instantiates without errors"
    assert task.implementation_steps[1].code_hint is None  # Optional field not provided

    # New fields
    assert task.goal == "Set up OAuth configuration"
    assert task.prd_ref == "auth-feature.md"
    assert len(task.key_requirements) == 2
    assert len(task.technical_notes) == 2
    assert len(task.deliverables) == 2
    assert len(task.exclusions) == 2
    assert task.scope_constraint == "Only modify auth module"


def test_task_to_dict_with_new_fields() -> None:
    """Test Task serialization includes new fields."""
    from a_sdlc.plugins.base import ImplementationStep

    task = Task(
        id="TASK-001",
        title="Test Task",
        description="A test task",
        goal="Achieve something",
        prd_ref="feature.md",
        key_requirements=["Req 1", "Req 2"],
        technical_notes=["Note 1"],
        deliverables=["Output 1"],
        exclusions=["Not this"],
        scope_constraint="Only modify X",
        implementation_steps=[
            ImplementationStep(
                title="Step 1",
                description="Do step 1",
                code_hint="def foo():\n    pass",
                test_expectation="Test passes",
            )
        ],
    )

    data = task.to_dict()

    assert data["goal"] == "Achieve something"
    assert data["prd_ref"] == "feature.md"
    assert data["key_requirements"] == ["Req 1", "Req 2"]
    assert data["technical_notes"] == ["Note 1"]
    assert data["deliverables"] == ["Output 1"]
    assert data["exclusions"] == ["Not this"]
    assert data["scope_constraint"] == "Only modify X"
    assert len(data["implementation_steps"]) == 1
    assert data["implementation_steps"][0]["title"] == "Step 1"
    assert data["implementation_steps"][0]["code_hint"] == "def foo():\n    pass"


