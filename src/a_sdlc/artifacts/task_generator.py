"""Task generation from PRD with AI assistance."""

import re
from dataclasses import dataclass

from a_sdlc.plugins.base import Task


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
    # Extract PRD filename for reference
    prd_ref = ctx.prd_sections.get("_filename", "source-prd.md")

    prompt = f"""
You are an expert technical project manager tasked with breaking down a Product Requirements Document (PRD) into actionable development tasks.

# Context

## PRD Information
- Title: {ctx.prd_sections.get('Overview', 'Not specified')}
- Requirements: {len(ctx.requirements)} functional/non-functional requirements
- Granularity: {ctx.granularity}
- PRD Reference: {prd_ref}

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
   Each task MUST include ALL of the following fields:
   - Unique sequential ID (TASK-001, TASK-002, etc.)
   - Clear, actionable title (verb + object, e.g., "Implement Google OAuth handler")
   - Goal: Clear statement of what this task accomplishes (distinct from description)
   - Description: Brief summary for list views (1-2 sentences)
   - Priority (HIGH for critical path, MEDIUM for parallel work, LOW for nice-to-have)
   - Requirement ID linkage (FR-001, NFR-002, etc.)
   - PRD reference: "{prd_ref}"
   - Component assignment
   - Dependencies (list of TASK-XXX IDs)
   - Files to modify (3-5 specific file paths)
   - Key requirements (2-4 specific requirements from the PRD this task addresses)
   - Technical notes (2-4 implementation hints, existing patterns to follow, etc.)
   - Deliverables (2-4 concrete outputs this task will produce)
   - Exclusions (2-3 things explicitly NOT in scope for this task)
   - Implementation steps with rich structure (3-5 steps, each with title, description, optional code_hint and test_expectation)
   - Success criteria (2-4 testable acceptance criteria)
   - Scope constraint: "Implement only the changes described above. Do not modify unrelated components."

5. **Output Format:**
   Return a JSON array of task objects matching this EXACT schema:
   {{
     "id": "TASK-001",
     "title": "Set up OAuth configuration",
     "goal": "Configure OAuth 2.0 provider settings to enable third-party authentication",
     "description": "Configure OAuth providers with client IDs and secrets for authentication system",
     "priority": "high",
     "requirement_id": "FR-001",
     "prd_ref": "{prd_ref}",
     "component": "auth-service",
     "dependencies": [],
     "files_to_modify": ["src/auth/config.py", "config/oauth.yaml"],
     "key_requirements": [
       "Support Google and GitHub OAuth providers",
       "Store client secrets securely in environment variables"
     ],
     "technical_notes": [
       "Use existing ConfigLoader pattern from src/config/loader.py",
       "OAuth callback URL format: /auth/callback/{{provider}}"
     ],
     "deliverables": [
       "OAuth configuration dataclass in src/auth/config.py",
       "Provider-specific configuration loading",
       "Environment variable validation"
     ],
     "exclusions": [
       "OAuth flow implementation (separate task)",
       "UI login button changes (separate task)",
       "Token refresh logic (separate task)"
     ],
     "implementation_steps": [
       {{
         "title": "Create OAuth config dataclass",
         "description": "Define configuration structure for OAuth providers",
         "code_hint": "@dataclass\\nclass OAuthConfig:\\n    provider: str\\n    client_id: str\\n    client_secret: str",
         "test_expectation": "Config instantiates without errors"
       }},
       {{
         "title": "Add config loader",
         "description": "Load OAuth settings from environment variables",
         "code_hint": "def load_oauth_config() -> OAuthConfig:\\n    return OAuthConfig(...)",
         "test_expectation": "Missing env var raises ConfigError"
       }},
       {{
         "title": "Initialize in service startup",
         "description": "Call config loader during auth service initialization",
         "test_expectation": "Service starts with valid config"
       }}
     ],
     "success_criteria": [
       "OAuth config loads for Google provider",
       "OAuth config loads for GitHub provider",
       "Missing client_secret raises clear ConfigError",
       "All provider settings validated at startup"
     ],
     "scope_constraint": "Implement only the changes described above. Do not modify unrelated components."
   }}

# PRD Content

{ctx.prd_content[:4000]}

# Output

Generate tasks as a JSON array. Start with configuration and setup tasks, then implementation, then testing.
IMPORTANT: Include ALL fields shown in the schema above for EVERY task.
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

    if not task.goal:
        errors.append("Task goal is required (distinct from description)")

    if not task.component:
        errors.append("Task must be assigned to a component")

    if not task.requirement_id:
        errors.append("Task must be linked to a requirement")

    if not task.implementation_steps:
        errors.append("Task must include implementation steps")

    if not task.success_criteria:
        errors.append("Task must include success criteria")

    if not task.deliverables:
        errors.append("Task must include deliverables (what will be produced)")

    if not task.exclusions:
        errors.append("Task must include exclusions (what is NOT in scope)")

    return errors
