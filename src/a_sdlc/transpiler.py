"""
Markdown-to-TOML transpiler for Gemini CLI custom commands.

Converts a-sdlc's canonical markdown skill templates into Gemini CLI's
TOML command format, mapping Claude-specific tool references to generic
instructions while preserving mcp__asdlc__* calls.
"""

import re
from dataclasses import dataclass
from pathlib import Path

# Tool name replacements — applied to template body.
# Longer patterns listed first to avoid partial matches.
TOOL_REPLACEMENTS = {
    "AskUserQuestion": "ask the user for their choice",
    "TaskCreate": "note the following task",
    "TaskUpdate": "update the task status",
    "TodoWrite": "track the following tasks",
    "Write(": "write to the file at (",
    "Edit(": "edit the file at (",
    "Read(": "read the file at (",
}


@dataclass
class TranspiledCommand:
    """Result of transpiling a single markdown template."""

    name: str  # Command name derived from filename (e.g., "prd-list")
    description: str  # Extracted from ## Purpose section
    prompt: str  # Full template body with tool names replaced
    source_path: Path  # Original markdown file path


def _extract_description(content: str) -> str:
    """Extract description from ## Purpose section.

    Takes the first non-empty line after the ## Purpose heading.

    Args:
        content: Full markdown content.

    Returns:
        Description string, or empty string if no ## Purpose found.
    """
    lines = content.split("\n")
    in_purpose = False
    for line in lines:
        if re.match(r"^##\s+Purpose", line):
            in_purpose = True
            continue
        if in_purpose:
            stripped = line.strip()
            if stripped.startswith("#"):
                return ""
            if stripped:
                return stripped
    return ""


def _apply_tool_replacements(content: str) -> str:
    """Replace Claude-specific tool names with generic instructions.

    Preserves mcp__asdlc__* references untouched.

    Args:
        content: Template body text.

    Returns:
        Text with tool names replaced.
    """
    result = content
    for old, new in TOOL_REPLACEMENTS.items():
        result = result.replace(old, new)
    return result


def _escape_toml_multiline(text: str) -> str:
    """Escape text for use inside TOML triple-quoted strings.

    In TOML basic strings (double-quoted), backslashes are escape
    characters. We must escape them first, then handle triple-quote
    sequences to prevent breaking the TOML delimiter.

    Args:
        text: Raw text to escape.

    Returns:
        Escaped text safe for TOML multi-line strings.
    """
    # Escape backslashes first (must come before other escapes)
    text = text.replace("\\", "\\\\")
    # Replace any occurrence of """ with ""\\" to break the sequence
    while '"""' in text:
        text = text.replace('"""', '""\\\"')
    return text


def transpile_template(source: Path) -> TranspiledCommand:
    """Convert a single markdown template to Gemini CLI command data.

    Args:
        source: Path to the markdown template file.

    Returns:
        TranspiledCommand with extracted metadata and converted body.
    """
    content = source.read_text(encoding="utf-8")

    name = source.stem
    description = _extract_description(content)
    prompt = _apply_tool_replacements(content)

    # Append {{args}} for user argument injection
    prompt = prompt.rstrip() + "\n\n{{args}}\n"

    return TranspiledCommand(
        name=name,
        description=description,
        prompt=prompt,
        source_path=source,
    )


def write_toml(command: TranspiledCommand, target_dir: Path) -> Path:
    """Write a TranspiledCommand as a TOML file.

    Args:
        command: Transpiled command data.
        target_dir: Directory to write the TOML file to.

    Returns:
        Path to the written TOML file.
    """
    target_dir.mkdir(parents=True, exist_ok=True)

    escaped_description = command.description.replace('"', '\\"')
    escaped_prompt = _escape_toml_multiline(command.prompt)

    toml_content = f'description = "{escaped_description}"\nprompt = """\n{escaped_prompt}"""\n'

    output_path = target_dir / f"{command.name}.toml"
    output_path.write_text(toml_content, encoding="utf-8")
    return output_path


def transpile_all(source_dir: Path, target_dir: Path) -> list[str]:
    """Transpile all markdown templates in source_dir to TOML in target_dir.

    Skips underscore-prefixed files (internal blocks, not user commands).

    Args:
        source_dir: Directory containing markdown templates.
        target_dir: Directory to write TOML files to.

    Returns:
        List of transpiled command names.
    """
    names = []
    for md_file in sorted(source_dir.glob("*.md")):
        if md_file.name.startswith("_"):
            continue
        command = transpile_template(md_file)
        write_toml(command, target_dir)
        names.append(command.name)
    return names
