"""
Init file generation for a-sdlc projects.

Generates CLAUDE.md, lesson-learn.md, and config.yaml files during project
initialization. Used by both the CLI `a-sdlc init` command and the MCP
`init_project()` tool to ensure identical output regardless of init path.
"""

import re
from importlib import resources
from pathlib import Path

import yaml

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
        ref = resources.files("a_sdlc").joinpath("artifact_templates").joinpath(template_name)
        return ref.read_text(encoding="utf-8")
    except (TypeError, AttributeError, FileNotFoundError):
        # Fallback for development
        fallback = Path(__file__).parent.parent / "artifact_templates" / template_name
        if fallback.exists():
            return fallback.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Template not found: {template_name}") from None


_TOP_LEVEL_KEY_RE = re.compile(r"^[a-z][a-z_]*:")


def _extract_template_sections(template_text: str) -> dict[str, str]:
    """Parse template YAML text into sections keyed by top-level key name.

    Each section includes any preceding comment lines, the key line itself,
    and all nested content until the next top-level key or EOF.

    Args:
        template_text: Raw YAML template text with comments.

    Returns:
        Ordered dict mapping top-level key names to their full text blocks.
    """
    lines = template_text.split("\n")
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_start: int = 0
    # Track where leading comments for the *next* section begin
    comment_start: int | None = None

    for i, line in enumerate(lines):
        if _TOP_LEVEL_KEY_RE.match(line):
            key_name = line.split(":")[0]
            # Finalize previous section
            if current_key is not None:
                # End previous section just before the comment block of this key
                end = comment_start if comment_start is not None else i
                sections[current_key] = "\n".join(lines[current_start:end]).rstrip("\n")
            current_key = key_name
            # Include preceding comments in this section
            current_start = comment_start if comment_start is not None else i
            comment_start = None
        elif line.startswith("#") or line.strip() == "":
            # Potential leading comment/blank for the next section
            if comment_start is None:
                comment_start = i
        else:
            # Indented content — belongs to the current section
            comment_start = None

    # Finalize last section
    if current_key is not None:
        sections[current_key] = "\n".join(lines[current_start:]).rstrip("\n")

    # Strip leading blank lines from each section (keep comments)
    for key in sections:
        sections[key] = sections[key].lstrip("\n")

    return sections


def _render_context_content(template_name: str, project_name: str) -> str:
    """Render a context-file template with project-specific placeholders.

    Shared by the file-writing generators and the content-only renderers so
    both paths produce byte-identical output.
    """
    content = _load_template(template_name)
    content = content.replace(
        "{{PROJECT_OVERVIEW}}",
        f"{project_name} — managed with a-sdlc.",
    )
    content = content.replace(
        "{{DEVELOPMENT_COMMANDS}}",
        "<!-- Add your project's development commands here -->",
    )
    return content


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

    content = _render_context_content("claude-md.template.md", project_name)
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

    content = _render_context_content("gemini-md.template.md", project_name)
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
    """Generate or upgrade .sdlc/config.yaml for the project.

    When the config file already exists and ``overwrite`` is False, the
    function checks for top-level sections present in the template but
    missing from the existing file.  Missing sections are appended
    (text-based, preserving comments) and status ``"updated"`` is returned.

    Args:
        project_path: Path to the project root directory.
        overwrite: If True, replace entire file with the template.

    Returns:
        Dict with 'status' ('created', 'updated', 'exists') and 'path'.
    """
    sdlc_dir = project_path / ".sdlc"
    sdlc_dir.mkdir(parents=True, exist_ok=True)

    config_path = sdlc_dir / "config.yaml"

    if config_path.exists() and not overwrite:
        # --- upgrade path: append missing sections ---
        existing_text = config_path.read_text(encoding="utf-8")
        existing_keys = set((yaml.safe_load(existing_text) or {}).keys())

        template_text = _load_template("config.template.yaml")
        template_sections = _extract_template_sections(template_text)

        missing = [k for k in template_sections if k not in existing_keys]

        if not missing:
            return {
                "status": "exists",
                "path": str(config_path),
                "message": "config.yaml already exists. Skipped.",
            }

        # Append missing sections with a separator
        parts = [existing_text.rstrip("\n")]
        parts.append("")
        parts.append(
            f"# ── Added by a-sdlc upgrade ({', '.join(missing)}) ──"
        )
        for key in missing:
            parts.append("")
            parts.append(template_sections[key])

        parts.append("")  # trailing newline
        config_path.write_text("\n".join(parts), encoding="utf-8")

        return {
            "status": "updated",
            "path": str(config_path),
            "message": f"config.yaml upgraded — added sections: {', '.join(missing)}",
            "added_sections": missing,
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


def render_init_files(
    project_name: str,
    targets: list[CLITarget] | None = None,
) -> list[dict[str, str]]:
    """Render init file contents without writing anything to disk.

    Used by the ``create_project()`` MCP tool in remote/centralized
    deployments, where the server cannot (and should not) write into the
    client's repository. The returned specs let the MCP client create each
    file in the right place on its own machine.

    Args:
        project_name: Human-readable project name.
        targets: CLI targets to render context files for. Defaults to Claude
            only, since the server cannot detect the client's installed CLIs.

    Returns:
        A list of file specs, each a dict with:
            - ``path``: target path (relative to the project root, or a
              ``~``-prefixed user-global path for ``scope="global"``)
            - ``scope``: ``"project"`` or ``"global"``
            - ``content``: full file contents to write
            - ``description``: human-readable purpose
    """
    if targets is None:
        targets = [CLAUDE_TARGET]

    files: list[dict[str, str]] = []

    for target in targets:
        template_name = (
            "gemini-md.template.md"
            if target.context_file == "GEMINI.md"
            else "claude-md.template.md"
        )
        files.append({
            "path": target.context_file,
            "scope": "project",
            "content": _render_context_content(template_name, project_name),
            "description": f"{target.display_name} context file (project root)",
        })

    files.append({
        "path": ".sdlc/lesson-learn.md",
        "scope": "project",
        "content": _load_template("lesson-learn.template.md"),
        "description": "Project-specific lessons and rules",
    })
    files.append({
        "path": ".sdlc/config.yaml",
        "scope": "project",
        "content": _load_template("config.template.yaml"),
        "description": "Project configuration",
    })
    files.append({
        "path": "~/.a-sdlc/lesson-learn.md",
        "scope": "global",
        "content": _load_template("lesson-learn.template.md"),
        "description": "Global cross-project lessons (create only if absent)",
    })

    return files
