"""
Init file generation for a-sdlc projects.

Generates CLAUDE.md and lesson-learn.md files during project initialization.
Used by both the CLI `a-sdlc init` command and the MCP `init_project()` tool
to ensure identical output regardless of init path.
"""

from importlib import resources
from pathlib import Path

from a_sdlc.core.content import get_data_dir


def _load_template(template_name: str) -> str:
    """Load a bundled artifact template.

    Args:
        template_name: Name of template file in artifact_templates/

    Returns:
        Template content as string.
    """
    try:
        ref = resources.files("a_sdlc").joinpath("artifact_templates", template_name)
        return ref.read_text(encoding="utf-8")
    except (TypeError, AttributeError, FileNotFoundError):
        # Fallback for development
        fallback = Path(__file__).parent.parent / "artifact_templates" / template_name
        if fallback.exists():
            return fallback.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Template not found: {template_name}")


def generate_claude_md(
    project_path: Path,
    project_name: str,
    overwrite: bool = False,
) -> dict[str, str]:
    """Generate CLAUDE.md in the project root.

    Args:
        project_path: Path to the project root directory.
        project_name: Human-readable project name.
        overwrite: If False, skip if CLAUDE.md already exists.

    Returns:
        Dict with 'status' ('created', 'exists', 'skipped') and 'path'.
    """
    claude_md_path = project_path / "CLAUDE.md"

    if claude_md_path.exists() and not overwrite:
        return {
            "status": "exists",
            "path": str(claude_md_path),
            "message": "CLAUDE.md already exists. Skipped to avoid overwriting.",
        }

    template = _load_template("claude-md.template.md")

    # Replace placeholders with project-specific values
    content = template.replace(
        "{{PROJECT_OVERVIEW}}",
        f"{project_name} — managed with a-sdlc.",
    )
    content = content.replace(
        "{{DEVELOPMENT_COMMANDS}}",
        "<!-- Add your project's development commands here -->",
    )

    claude_md_path.write_text(content, encoding="utf-8")

    return {
        "status": "created",
        "path": str(claude_md_path),
        "message": "CLAUDE.md created with lesson-learn and correction logging rules.",
    }


def generate_lesson_learn(
    project_path: Path,
    overwrite: bool = False,
) -> dict[str, str]:
    """Generate .sdlc/lesson-learn.md for the project.

    Args:
        project_path: Path to the project root directory.
        overwrite: If False, skip if lesson-learn.md already exists.

    Returns:
        Dict with 'status' ('created', 'exists') and 'path'.
    """
    sdlc_dir = project_path / ".sdlc"
    sdlc_dir.mkdir(parents=True, exist_ok=True)

    lesson_path = sdlc_dir / "lesson-learn.md"

    if lesson_path.exists() and not overwrite:
        return {
            "status": "exists",
            "path": str(lesson_path),
            "message": "lesson-learn.md already exists. Skipped.",
        }

    template = _load_template("lesson-learn.template.md")
    lesson_path.write_text(template, encoding="utf-8")

    return {
        "status": "created",
        "path": str(lesson_path),
        "message": "Project lesson-learn.md created.",
    }


def ensure_global_lesson_learn() -> dict[str, str]:
    """Ensure global lesson-learn.md exists at ~/.a-sdlc/lesson-learn.md.

    Creates the file only if it doesn't already exist.

    Returns:
        Dict with 'status' ('created', 'exists') and 'path'.
    """
    global_dir = get_data_dir()
    global_dir.mkdir(parents=True, exist_ok=True)

    global_path = global_dir / "lesson-learn.md"

    if global_path.exists():
        return {
            "status": "exists",
            "path": str(global_path),
            "message": "Global lesson-learn.md already exists.",
        }

    template = _load_template("lesson-learn.template.md")
    global_path.write_text(template, encoding="utf-8")

    return {
        "status": "created",
        "path": str(global_path),
        "message": "Global lesson-learn.md created.",
    }


def generate_init_files(
    project_path: Path,
    project_name: str,
    overwrite: bool = False,
) -> dict[str, list[dict[str, str]]]:
    """Generate all init files for a project.

    Orchestrates generation of CLAUDE.md, project lesson-learn.md,
    and global lesson-learn.md.

    Args:
        project_path: Path to the project root directory.
        project_name: Human-readable project name.
        overwrite: If False, skip files that already exist.

    Returns:
        Dict with 'results' list containing status of each file.
    """
    results = []

    results.append(generate_claude_md(project_path, project_name, overwrite))
    results.append(generate_lesson_learn(project_path, overwrite))
    results.append(ensure_global_lesson_learn())

    return {"results": results}
