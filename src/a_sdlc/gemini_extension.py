"""
Gemini CLI extension builder.

Generates a complete Gemini CLI extension directory including
gemini-extension.json manifest, transpiled TOML commands, and
GEMINI.md context file.
"""

import json
from importlib import resources
from pathlib import Path

from a_sdlc import __version__
from a_sdlc.transpiler import transpile_all


def generate_manifest() -> dict:
    """Generate gemini-extension.json content.

    Returns:
        Dict with extension manifest fields.
    """
    return {
        "name": "a-sdlc",
        "version": __version__,
        "description": "SDLC management tools for PRDs, tasks, and sprints",
        "mcpServers": {
            "asdlc": {
                "command": "uvx",
                "args": ["a-sdlc", "serve"],
            }
        },
        "contextFileName": "GEMINI.md",
    }


def _get_template_dir() -> Path:
    """Get the path to bundled skill template files."""
    try:
        return Path(str(resources.files("a_sdlc").joinpath("templates")))
    except (TypeError, AttributeError):
        return Path(__file__).parent / "templates"


def _get_gemini_md_template() -> str:
    """Load the GEMINI.md template content."""
    try:
        ref = resources.files("a_sdlc").joinpath("artifact_templates", "gemini-md.template.md")
        return ref.read_text(encoding="utf-8")
    except (TypeError, AttributeError, FileNotFoundError):
        fallback = Path(__file__).parent / "artifact_templates" / "gemini-md.template.md"
        return fallback.read_text(encoding="utf-8")


def build_extension_dir(output_dir: Path) -> Path:
    """Generate a complete Gemini CLI extension directory.

    Creates:
        output_dir/
        ├── gemini-extension.json   # Extension manifest
        ├── commands/sdlc/          # Transpiled TOML commands
        └── GEMINI.md               # Context file

    Args:
        output_dir: Directory to create the extension in.

    Returns:
        Path to the output directory.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Transpile all templates to commands/sdlc/
    commands_dir = output_dir / "commands" / "sdlc"
    template_dir = _get_template_dir()
    transpile_all(template_dir, commands_dir)

    # Step 2: Write GEMINI.md context file
    gemini_md_content = _get_gemini_md_template()
    gemini_md_content = gemini_md_content.replace(
        "{{PROJECT_OVERVIEW}}",
        "This project is managed with a-sdlc for SDLC management.",
    )
    gemini_md_content = gemini_md_content.replace(
        "{{DEVELOPMENT_COMMANDS}}",
        "See the project's README for development commands.",
    )
    (output_dir / "GEMINI.md").write_text(gemini_md_content, encoding="utf-8")

    # Step 3: Generate gemini-extension.json
    manifest = generate_manifest()
    manifest_path = output_dir / "gemini-extension.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return output_dir
