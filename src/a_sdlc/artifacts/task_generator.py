"""Task generation from PRD with AI assistance."""

import re
from dataclasses import dataclass

from a_sdlc.plugins.base import Task, TaskPriority, TaskStatus


@dataclass
class TaskGenerationContext:
    """Context for task generation."""

    prd_content: str
    prd_sections: dict[str, str]
    requirements: list[tuple[str, str]]
    architecture_components: list[str]
    data_model_entities: list[str]
    workflows: list[str]
    granularity: str


def parse_requirements_from_prd(prd_sections: dict[str, str]) -> list[tuple[str, str]]:
    """Extract requirement IDs and descriptions from PRD.

    Args:
        prd_sections: Dictionary of PRD section names to content.

    Returns:
        List of (requirement_id, description) tuples.

    Examples:
        Input: "- FR-001: OAuth authentication\n- FR-002: Session management"
        Output: [("FR-001", "OAuth authentication"), ("FR-002", "Session management")]
    """
    requirements = []

    for section_name in ["Functional Requirements", "Non-Functional Requirements"]:
        if section_name not in prd_sections:
            continue

        content = prd_sections[section_name]

        # Pattern: "- FR-001: Description" or "1. FR-001: Description"
        pattern = r"[-\d.]\s+([A-Z]+-\d+):\s+(.+?)(?=\n|$)"
        matches = re.findall(pattern, content, re.MULTILINE)
        requirements.extend(matches)

    return requirements


def extract_affected_components(prd_sections: dict[str, str]) -> list[str]:
    """Extract component names from Affected Components section.

    Args:
        prd_sections: Dictionary of PRD section names to content.

    Returns:
        List of component names.
    """
    if "Affected Components" not in prd_sections:
        return []

    content = prd_sections["Affected Components"]

    # Parse bullet points or numbered lists
    pattern = r"[-\d.]\s+([a-z-]+(?:-service|-gateway|-middleware)?)"
    matches = re.findall(pattern, content)

    return matches


def build_ai_prompt_for_task_generation(ctx: TaskGenerationContext) -> str:
    """Build AI prompt for task generation.

    Args:
        ctx: Task generation context with PRD and artifacts.

    Returns:
        Formatted prompt string for AI.
    """
    prompt = f"""
You are an expert technical project manager tasked with breaking down a Product Requirements Document (PRD) into actionable development tasks.

# Context

## PRD Information
- Title: {ctx.prd_sections.get('Overview', 'Not specified')}
- Requirements: {len(ctx.requirements)} functional/non-functional requirements
- Granularity: {ctx.granularity}

## Requirements List
{_format_requirements_for_prompt(ctx.requirements)}

## Architecture Components
Available components from architecture.md:
{_format_list_for_prompt(ctx.architecture_components[:20])}

## Data Model Entities
Available entities from data-model.md:
{_format_list_for_prompt(ctx.data_model_entities[:20])}

## Key Workflows
Existing workflows from key-workflows.md:
{_format_list_for_prompt(ctx.workflows[:10])}

# Task Generation Instructions

Generate developer-ready tasks following these rules:

1. **Task Structure:**
   - Each requirement (FR-XXX, NFR-XXX) should produce 1-3 tasks
   - Granularity level: {ctx.granularity}
     - Coarse: 1-2 high-level tasks per requirement
     - Medium: 2-4 specific implementable tasks per requirement
     - Fine: 4-8 detailed subtasks per requirement

2. **Task Dependencies:**
   - Identify logical dependencies (config before implementation)
   - Consider component dependencies from architecture
   - Order tasks by: setup → core implementation → integration → testing

3. **Component Assignment:**
   - Assign each task to an existing component from architecture
   - If no suitable component exists, suggest "NEW: component-name"

4. **Task Details:**
   Each task MUST include:
   - Unique sequential ID (TASK-001, TASK-002, etc.)
   - Clear, actionable title (verb + object, e.g., "Implement Google OAuth handler")
   - Detailed description (2-3 sentences explaining what and why)
   - Priority (HIGH for critical path, MEDIUM for parallel work, LOW for nice-to-have)
   - Requirement ID linkage (FR-001, NFR-002, etc.)
   - Component assignment
   - Dependencies (list of TASK-XXX IDs)
   - Files to modify (3-5 specific file paths)
   - Implementation steps (3-5 concrete steps)
   - Success criteria (2-4 testable acceptance criteria)

5. **Output Format:**
   Return a JSON array of task objects matching this schema:
   {{
     "id": "TASK-001",
     "title": "Set up OAuth configuration",
     "description": "Configure OAuth providers (Google, GitHub) with client IDs and secrets for authentication system",
     "priority": "high",
     "requirement_id": "FR-001",
     "component": "auth-service",
     "dependencies": [],
     "files_to_modify": ["src/auth/config.py", "config/oauth.yaml"],
     "implementation_steps": [
       "Create oauth.yaml config file with provider schemas",
       "Add OAuth configuration loader to config.py",
       "Add environment variable validation for secrets",
       "Initialize OAuth config in auth service startup"
     ],
     "success_criteria": [
       "Config file loads without errors",
       "All provider settings validated at startup",
       "Environment variables properly sourced"
     ]
   }}

# PRD Content

{ctx.prd_content[:4000]}

# Output

Generate tasks as a JSON array. Start with configuration and setup tasks, then implementation, then testing.
"""

    return prompt


def _format_requirements_for_prompt(requirements: list[tuple[str, str]]) -> str:
    """Format requirements for prompt."""
    if not requirements:
        return "No requirements specified"

    return "\n".join(f"- {req_id}: {desc}" for req_id, desc in requirements)


def _format_list_for_prompt(items: list[str]) -> str:
    """Format list items for prompt."""
    if not items:
        return "Not available"

    return "\n".join(f"- {item}" for item in items)


def infer_task_dependencies(
    tasks: list[Task], component_deps: dict[str, list[str]]
) -> list[Task]:
    """Infer task dependencies based on component relationships.

    Args:
        tasks: List of generated tasks.
        component_deps: Dictionary mapping components to their dependencies.

    Returns:
        Tasks with updated dependencies.
    """
    # Group tasks by component
    tasks_by_component: dict[str, list[Task]] = {}
    for task in tasks:
        if task.component not in tasks_by_component:
            tasks_by_component[task.component] = []
        tasks_by_component[task.component].append(task)

    # Add dependencies based on component relationships
    for task in tasks:
        component = task.component
        if component and component in component_deps:
            for dep_component in component_deps[component]:
                if dep_component in tasks_by_component:
                    # Add dependency to first task of dependent component
                    dep_task = tasks_by_component[dep_component][0]
                    if dep_task.id not in task.dependencies:
                        task.dependencies.append(dep_task.id)

    return tasks


def validate_task_structure(task: Task) -> list[str]:
    """Validate task has all required fields.

    Args:
        task: Task to validate.

    Returns:
        List of validation error messages (empty if valid).
    """
    errors = []

    if not task.title:
        errors.append("Task title is required")

    if not task.description:
        errors.append("Task description is required")

    if not task.component:
        errors.append("Task must be assigned to a component")

    if not task.requirement_id:
        errors.append("Task must be linked to a requirement")

    if not task.implementation_steps:
        errors.append("Task must include implementation steps")

    if not task.success_criteria:
        errors.append("Task must include success criteria")

    return errors
