"""Tests for task generation from PRD."""

import pytest

from a_sdlc.artifacts.task_generator import (
    extract_affected_components,
    parse_requirements_from_prd,
    validate_task_structure,
)
from a_sdlc.plugins.base import Task, TaskPriority, TaskStatus


class TestRequirementParsing:
    """Test requirement extraction from PRD."""

    def test_parse_functional_requirements(self):
        """Test parsing functional requirements."""
        sections = {
            "Functional Requirements": """
- FR-001: OAuth authentication with Google and GitHub
- FR-002: Session management with JWT tokens
- FR-003: Password reset functionality
"""
        }

        requirements = parse_requirements_from_prd(sections)

        assert len(requirements) == 3
        assert requirements[0] == (
            "FR-001",
            "OAuth authentication with Google and GitHub",
        )
        assert requirements[1] == ("FR-002", "Session management with JWT tokens")
        assert requirements[2] == ("FR-003", "Password reset functionality")

    def test_parse_non_functional_requirements(self):
        """Test parsing non-functional requirements."""
        sections = {
            "Non-Functional Requirements": """
1. NFR-001: Login completes in <200ms
2. NFR-002: 99.9% uptime SLA
"""
        }

        requirements = parse_requirements_from_prd(sections)

        assert len(requirements) == 2
        assert requirements[0][0] == "NFR-001"
        assert requirements[1][0] == "NFR-002"

    def test_parse_mixed_requirements(self):
        """Test parsing both functional and non-functional."""
        sections = {
            "Functional Requirements": "- FR-001: Feature A",
            "Non-Functional Requirements": "- NFR-001: Performance B",
        }

        requirements = parse_requirements_from_prd(sections)

        assert len(requirements) == 2
        assert requirements[0] == ("FR-001", "Feature A")
        assert requirements[1] == ("NFR-001", "Performance B")

    def test_parse_empty_sections(self):
        """Test parsing with no requirements."""
        sections = {"Overview": "Just an overview"}

        requirements = parse_requirements_from_prd(sections)

        assert len(requirements) == 0


class TestComponentExtraction:
    """Test component extraction from PRD."""

    def test_extract_affected_components(self):
        """Test extracting component list."""
        sections = {
            "Affected Components": """
- auth-service
- api-gateway
- session-middleware
"""
        }

        components = extract_affected_components(sections)

        assert "auth-service" in components
        assert "api-gateway" in components
        assert "session-middleware" in components

    def test_extract_components_numbered_list(self):
        """Test extracting from numbered list."""
        sections = {
            "Affected Components": """
1. user-service
2. payment-gateway
3. notification-service
"""
        }

        components = extract_affected_components(sections)

        assert "user-service" in components
        assert "payment-gateway" in components
        assert "notification-service" in components

    def test_extract_no_components(self):
        """Test when no components section exists."""
        sections = {"Overview": "Just an overview"}

        components = extract_affected_components(sections)

        assert len(components) == 0


class TestTaskValidation:
    """Test task structure validation."""

    def test_valid_task(self):
        """Test validation passes for complete task."""
        task = Task(
            id="TASK-001",
            title="Implement OAuth",
            description="Add OAuth authentication",
            status=TaskStatus.PENDING,
            priority=TaskPriority.HIGH,
            requirement_id="FR-001",
            component="auth-service",
            dependencies=[],
            files_to_modify=["src/auth/oauth.py"],
            implementation_steps=["Step 1", "Step 2"],
            success_criteria=["Criterion 1"],
        )

        errors = validate_task_structure(task)

        assert len(errors) == 0

    def test_missing_title(self):
        """Test validation fails for missing title."""
        task = Task(
            id="TASK-001",
            title="",
            description="Description",
            requirement_id="FR-001",
            component="auth-service",
            implementation_steps=["Step"],
            success_criteria=["Criterion"],
        )

        errors = validate_task_structure(task)

        assert len(errors) > 0
        assert "title" in errors[0].lower()

    def test_missing_description(self):
        """Test validation fails for missing description."""
        task = Task(
            id="TASK-001",
            title="Title",
            description="",
            requirement_id="FR-001",
            component="auth-service",
            implementation_steps=["Step"],
            success_criteria=["Criterion"],
        )

        errors = validate_task_structure(task)

        assert len(errors) > 0
        assert "description" in errors[0].lower()

    def test_missing_component(self):
        """Test validation fails for missing component."""
        task = Task(
            id="TASK-001",
            title="Title",
            description="Description",
            requirement_id="FR-001",
            component="",
            implementation_steps=["Step"],
            success_criteria=["Criterion"],
        )

        errors = validate_task_structure(task)

        assert len(errors) > 0
        assert "component" in errors[0].lower()

    def test_missing_requirement_id(self):
        """Test validation fails for missing requirement_id."""
        task = Task(
            id="TASK-001",
            title="Title",
            description="Description",
            requirement_id="",
            component="auth-service",
            implementation_steps=["Step"],
            success_criteria=["Criterion"],
        )

        errors = validate_task_structure(task)

        assert len(errors) > 0
        assert "requirement" in errors[0].lower()

    def test_missing_implementation_steps(self):
        """Test validation fails for missing implementation steps."""
        task = Task(
            id="TASK-001",
            title="Title",
            description="Description",
            requirement_id="FR-001",
            component="auth-service",
            implementation_steps=[],
            success_criteria=["Criterion"],
        )

        errors = validate_task_structure(task)

        assert len(errors) > 0
        assert "implementation" in errors[0].lower()

    def test_missing_success_criteria(self):
        """Test validation fails for missing success criteria."""
        task = Task(
            id="TASK-001",
            title="Title",
            description="Description",
            requirement_id="FR-001",
            component="auth-service",
            implementation_steps=["Step"],
            success_criteria=[],
        )

        errors = validate_task_structure(task)

        assert len(errors) > 0
        assert "success" in errors[0].lower() or "criteria" in errors[0].lower()

    def test_multiple_validation_errors(self):
        """Test multiple validation errors are reported."""
        task = Task(
            id="TASK-001",
            title="",
            description="",
            requirement_id="",
            component="",
            implementation_steps=[],
            success_criteria=[],
        )

        errors = validate_task_structure(task)

        # Should have multiple errors
        assert len(errors) >= 4
