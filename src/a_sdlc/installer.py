"""
Installer module for deploying skill templates to Claude Code.

Handles:
- Copying skill templates to ~/.claude/commands/sdlc/
- Template versioning and updates
- Integrity verification
- MCP server configuration
- Prerequisite checking for setup wizard
"""

import json
import shutil
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from a_sdlc import __version__


def check_python_version() -> tuple[bool, str]:
    """Check if Python version meets minimum requirement (>= 3.10).

    Returns:
        Tuple of (passed, message) where passed is True if Python >= 3.10.
    """
    version = sys.version_info
    if version >= (3, 10):
        return True, f"Python {version.major}.{version.minor}.{version.micro}"
    return False, f"Python {version.major}.{version.minor} (requires >= 3.10)"


def check_uv_available() -> tuple[bool, str]:
    """Check if uv/uvx is available on PATH.

    Returns:
        Tuple of (passed, message) where passed is True if uvx is found.
    """
    uvx_path = shutil.which("uvx")
    if uvx_path:
        return True, uvx_path
    return False, "Not found. Install from https://docs.astral.sh/uv/"


def check_claude_code_installed() -> tuple[bool, str]:
    """Check if Claude Code is installed by verifying ~/.claude directory.

    Returns:
        Tuple of (passed, message) where passed is True if ~/.claude exists.
    """
    claude_dir = Path.home() / ".claude"
    if claude_dir.exists():
        return True, str(claude_dir)
    return False, "~/.claude not found. Install Claude Code first."


def get_claude_settings_path() -> Path:
    """Get path to Claude Code settings file.

    Returns:
        Path to ~/.claude.json (where Claude CLI stores MCP servers)
    """
    return Path.home() / ".claude.json"


def configure_mcp_server(force: bool = False) -> dict[str, Any]:
    """Configure a-sdlc MCP server in Claude Code settings.

    Args:
        force: If True, overwrite existing configuration.

    Returns:
        Dict with status and message.
    """
    settings_path = get_claude_settings_path()

    # Read existing settings or create empty
    if settings_path.exists():
        with open(settings_path) as f:
            settings = json.load(f)
    else:
        # ~/.claude.json should exist if Claude CLI is installed
        settings = {}

    # Initialize mcpServers if needed
    if "mcpServers" not in settings:
        settings["mcpServers"] = {}

    # Check if already configured (check both old and new names)
    if "asdlc" in settings["mcpServers"] and not force:
        return {
            "status": "exists",
            "message": "asdlc MCP server already configured",
            "config": settings["mcpServers"]["asdlc"],
        }

    # Remove old a-sdlc config if present (migration)
    if "a-sdlc" in settings["mcpServers"]:
        del settings["mcpServers"]["a-sdlc"]

    # Configure asdlc MCP server (matches Claude CLI format)
    settings["mcpServers"]["asdlc"] = {
        "type": "stdio",
        "command": "uvx",
        "args": ["a-sdlc", "serve"],
        "env": {},
    }

    # Write settings
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    return {
        "status": "configured",
        "message": "asdlc MCP server configured in Claude Code settings",
        "settings_path": str(settings_path),
    }


class Installer:
    """Deploys a-sdlc skill templates to Claude Code configuration."""

    DEFAULT_TARGET = Path.home() / ".claude" / "commands" / "sdlc"
    PERSONA_TARGET = Path.home() / ".claude" / "agents"

    def __init__(self, target_dir: Path | None = None) -> None:
        """Initialize installer with target directory.

        Args:
            target_dir: Custom target directory. Defaults to ~/.claude/commands/sdlc/
        """
        self.target_dir = target_dir or self.DEFAULT_TARGET

    def install(self, force: bool = False, configure_mcp: bool = True) -> list[str]:
        """Install all skill templates to target directory.

        Args:
            force: If True, overwrite existing templates.
            configure_mcp: If True, also configure MCP server in Claude Code settings.

        Returns:
            List of installed template names.

        Raises:
            FileExistsError: If templates exist and force=False.
        """
        # Create target directory
        self.target_dir.mkdir(parents=True, exist_ok=True)

        # Get template source directory
        template_dir = self._get_template_dir()

        installed = []
        for template_file in template_dir.glob("*.md"):
            # Skip underscore-prefixed files (internal blocks, not user skills)
            if template_file.name.startswith("_"):
                continue
            target_file = self.target_dir / template_file.name

            if target_file.exists() and not force:
                # Skip existing files unless force=True
                installed.append(template_file.stem)
                continue

            shutil.copy2(template_file, target_file)
            installed.append(template_file.stem)

        # Deploy persona agent files
        self.install_personas(force=force)

        # Write version marker
        version_file = self.target_dir / ".version"
        version_file.write_text(__version__)

        # Configure MCP server
        if configure_mcp:
            configure_mcp_server(force=force)

        return installed

    def list_installed(self) -> list[dict]:
        """List all installed skill templates.

        Returns:
            List of dicts with 'name' and 'file' keys.
        """
        if not self.target_dir.exists():
            return []

        skills = []
        for template_file in sorted(self.target_dir.glob("*.md")):
            skills.append({
                "name": template_file.stem,
                "file": template_file.name,
            })

        return skills

    def uninstall(self) -> int:
        """Remove all installed skill templates.

        Returns:
            Number of templates removed.
        """
        if not self.target_dir.exists():
            return 0

        count = 0
        for template_file in self.target_dir.glob("*.md"):
            template_file.unlink()
            count += 1

        # Remove directory if empty
        if self.target_dir.exists() and not any(self.target_dir.iterdir()):
            self.target_dir.rmdir()

        return count

    def _get_template_dir(self) -> Path:
        """Get the path to bundled template files.

        Returns:
            Path to templates directory.
        """
        # Use importlib.resources for Python 3.9+
        try:
            with resources.files("a_sdlc").joinpath("templates") as template_path:
                return Path(template_path)
        except (TypeError, AttributeError):
            # Fallback for development
            return Path(__file__).parent / "templates"

    def _get_persona_dir(self) -> Path:
        """Get the path to bundled persona files.

        Returns:
            Path to personas directory.
        """
        try:
            with resources.files("a_sdlc").joinpath("personas") as persona_path:
                return Path(persona_path)
        except (TypeError, AttributeError):
            # Fallback for development
            return Path(__file__).parent / "personas"

    def install_personas(self, force: bool = False) -> list[str]:
        """Deploy persona agent files to ~/.claude/agents/.

        Args:
            force: If True, overwrite existing persona files.

        Returns:
            List of installed persona names.
        """
        self.PERSONA_TARGET.mkdir(parents=True, exist_ok=True)
        persona_dir = self._get_persona_dir()
        installed = []
        for persona_file in persona_dir.glob("*.md"):
            target_file = self.PERSONA_TARGET / persona_file.name
            if target_file.exists() and not force:
                installed.append(persona_file.stem)
                continue
            shutil.copy2(persona_file, target_file)
            installed.append(persona_file.stem)
        return installed

    def uninstall_personas(self) -> int:
        """Remove only sdlc-prefixed persona files from ~/.claude/agents/.

        CRITICAL: Only removes sdlc-*.md files — never touches other agent files.

        Returns:
            Number of persona files removed.
        """
        if not self.PERSONA_TARGET.exists():
            return 0
        count = 0
        for persona_file in self.PERSONA_TARGET.glob("sdlc-*.md"):
            persona_file.unlink()
            count += 1
        return count

    def list_installed_personas(self) -> list[dict]:
        """List deployed persona agent files matching sdlc-* pattern.

        Returns:
            List of dicts with 'name' and 'file' keys.
        """
        if not self.PERSONA_TARGET.exists():
            return []
        personas = []
        for persona_file in sorted(self.PERSONA_TARGET.glob("sdlc-*.md")):
            personas.append({
                "name": persona_file.stem,
                "file": persona_file.name,
            })
        return personas

    def verify_persona_integrity(self) -> dict[str, bool]:
        """Verify installed personas match source versions.

        Returns:
            Dict mapping persona name to verification status.
        """
        persona_dir = self._get_persona_dir()
        results = {}
        for persona_file in persona_dir.glob("*.md"):
            target_file = self.PERSONA_TARGET / persona_file.name
            name = persona_file.stem
            if not target_file.exists():
                results[name] = False
                continue
            source_content = persona_file.read_text(encoding="utf-8")
            target_content = target_file.read_text(encoding="utf-8")
            results[name] = source_content == target_content
        return results

    def verify_integrity(self) -> dict[str, bool]:
        """Verify installed templates match source versions.

        Returns:
            Dict mapping template name to verification status.
        """
        template_dir = self._get_template_dir()
        results = {}

        for template_file in template_dir.glob("*.md"):
            target_file = self.target_dir / template_file.name
            name = template_file.stem

            if not target_file.exists():
                results[name] = False
                continue

            # Simple content comparison
            source_content = template_file.read_text(encoding="utf-8")
            target_content = target_file.read_text(encoding="utf-8")
            results[name] = source_content == target_content

        return results

    def check_template_version(self) -> tuple[bool, str, str]:
        """Check if installed templates match current package version.

        Returns:
            Tuple of (up_to_date, installed_version, current_version).
        """
        version_file = self.target_dir / ".version"
        if not version_file.exists():
            return False, "unknown", __version__
        installed = version_file.read_text().strip()
        return installed == __version__, installed, __version__
