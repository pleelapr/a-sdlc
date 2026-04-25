"""
Init file generation for a-sdlc projects.

Generates CLAUDE.md, lesson-learn.md, and config.yaml files during project
initialization. Used by both the CLI `a-sdlc init` command and the MCP
`init_project()` tool to ensure identical output regardless of init path.
"""

from importlib import resources
from pathlib import Path

from a_sdlc.cli_targets import CLAUDE_TARGET, CLITarget, detect_targets
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
        raise FileNotFoundError(f"Template not found: {template_name}") from None


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


def generate_gemini_md(
    project_path: Path,
    project_name: str,
    overwrite: bool = False,
) -> dict[str, str]:
    """Generate GEMINI.md in the project root.

    Args:
        project_path: Path to the project root directory.
        project_name: Human-readable project name.
        overwrite: If False, skip if GEMINI.md already exists.

    Returns:
        Dict with 'status' ('created', 'exists', 'skipped') and 'path'.
    """
    gemini_md_path = project_path / "GEMINI.md"

    if gemini_md_path.exists() and not overwrite:
        return {
            "status": "exists",
            "path": str(gemini_md_path),
            "message": "GEMINI.md already exists. Skipped to avoid overwriting.",
        }

    template = _load_template("gemini-md.template.md")

    content = template.replace(
        "{{PROJECT_OVERVIEW}}",
        f"{project_name} — managed with a-sdlc.",
    )
    content = content.replace(
        "{{DEVELOPMENT_COMMANDS}}",
        "<!-- Add your project's development commands here -->",
    )

    gemini_md_path.write_text(content, encoding="utf-8")

    return {
        "status": "created",
        "path": str(gemini_md_path),
        "message": "GEMINI.md created with lesson-learn and correction logging rules.",
    }


def generate_context_file(
    project_path: Path,
    project_name: str,
    target: CLITarget,
    overwrite: bool = False,
) -> dict[str, str]:
    """Generate the appropriate context file for a CLI target.

    Args:
        project_path: Path to the project root directory.
        project_name: Human-readable project name.
        target: CLI target to generate context file for.
        overwrite: If False, skip if file already exists.

    Returns:
        Dict with 'status' and 'path'.
    """
    if target.context_file == "GEMINI.md":
        return generate_gemini_md(project_path, project_name, overwrite)
    return generate_claude_md(project_path, project_name, overwrite)


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


def generate_config_yaml(
    project_path: Path,
    overwrite: bool = False,
) -> dict[str, str]:
    """Generate .sdlc/config.yaml for the project.

    Args:
        project_path: Path to the project root directory.
        overwrite: If False, skip if config.yaml already exists.

    Returns:
        Dict with 'status' ('created', 'exists') and 'path'.
    """
    sdlc_dir = project_path / ".sdlc"
    sdlc_dir.mkdir(parents=True, exist_ok=True)

    config_path = sdlc_dir / "config.yaml"

    if config_path.exists() and not overwrite:
        return {
            "status": "exists",
            "path": str(config_path),
            "message": "config.yaml already exists. Skipped.",
        }

    template = _load_template("config.template.yaml")
    config_path.write_text(template, encoding="utf-8")

    return {
        "status": "created",
        "path": str(config_path),
        "message": "Project config.yaml created.",
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
    targets: list[CLITarget] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Generate all init files for a project.

    Orchestrates generation of context files (CLAUDE.md, GEMINI.md),
    project lesson-learn.md, config.yaml, and global lesson-learn.md.

    Args:
        project_path: Path to the project root directory.
        project_name: Human-readable project name.
        overwrite: If False, skip files that already exist.
        targets: CLI targets to generate context files for.
            If None, auto-detects installed CLIs (falls back to Claude).

    Returns:
        Dict with 'results' list containing status of each file.
    """
    results = []

    # Determine which context files to generate
    if targets is None:
        detected = detect_targets()
        # Fall back to Claude if nothing detected
        targets = detected if detected else [CLAUDE_TARGET]

    for target in targets:
        results.append(generate_context_file(project_path, project_name, target, overwrite))

    results.append(generate_lesson_learn(project_path, overwrite))
    results.append(generate_config_yaml(project_path, overwrite))
    results.append(ensure_global_lesson_learn())

    return {"results": results}
