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
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Any

from a_sdlc import __version__
from a_sdlc.cli_targets import CLAUDE_TARGET, CLITarget
from a_sdlc.transpiler import transpile_all

# Default port for HTTP transport (matches server default)
DEFAULT_MCP_PORT = 8765


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
    """Get path to Claude Code MCP config file.

    Returns:
        Path to ~/.claude.json (Claude Code's user-level MCP config).
    """
    return Path.home() / ".claude.json"


def _build_mcp_config(
    port: int = DEFAULT_MCP_PORT,
    url: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Build MCP server configuration payload (HTTP only).

    Args:
        port: Port for HTTP transport (default 8765).
        url: Explicit MCP server URL. Overrides port when provided.
             Use for Docker or cloud instances (e.g., "http://my-host:19765/mcp").
        auth_token: Bearer token for server authentication. When provided,
             adds an Authorization header to the MCP client config.

    Returns:
        Dict with MCP server configuration.
    """
    config: dict[str, Any] = {
        "type": "http",
        "url": url or f"http://localhost:{port}/mcp",
    }
    if auth_token:
        config["headers"] = {"Authorization": f"Bearer {auth_token}"}
    return config


def _configure_via_cli(
    config: dict[str, Any],
    scope: str = "user",
) -> bool:
    """Try to configure MCP server via ``claude mcp add-json``.

    Returns True on success, False if the CLI is not available.
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return False
    try:
        subprocess.run(
            [claude_bin, "mcp", "add-json", "asdlc", json.dumps(config), "-s", scope],
            check=True,
            capture_output=True,
            timeout=15,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


def configure_mcp_server(
    force: bool = False,
    target: CLITarget | None = None,
    port: int = DEFAULT_MCP_PORT,
    url: str | None = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Configure a-sdlc MCP server in CLI settings (HTTP transport only).

    Uses ``claude mcp add-json`` when the Claude CLI is available (preferred),
    falling back to direct file editing for non-Claude targets or when the
    CLI is not installed.

    Args:
        force: If True, overwrite existing configuration.
        target: CLI target to configure for. Defaults to Claude Code.
        port: Port for HTTP transport (default 8765).
        url: Explicit MCP server URL (overrides port). For Docker/cloud instances.
        auth_token: Bearer token for server authentication.

    Returns:
        Dict with status and message.
    """
    effective_target = target or CLAUDE_TARGET
    settings_path = effective_target.mcp_config_path
    mcp_config = _build_mcp_config(port=port, url=url, auth_token=auth_token)

    # --- Check if already configured (skip when force=True) ----------
    if not force:
        try:
            if settings_path.exists():
                with open(settings_path) as f:
                    settings = json.load(f)
                if "asdlc" in settings.get("mcpServers", {}):
                    return {
                        "status": "exists",
                        "message": "asdlc MCP server already configured",
                        "config": settings["mcpServers"]["asdlc"],
                    }
        except (json.JSONDecodeError, OSError):
            pass  # Proceed to configure

    # --- Preferred path: use ``claude mcp add-json`` for Claude targets ---
    # Skip CLI path when auth_token is set to avoid leaking the secret in
    # process arguments (visible via ``ps aux``).  Fall through to the
    # direct file-write path instead.
    if (
        effective_target.name == "claude"
        and not auth_token
        and _configure_via_cli(mcp_config)
    ):
        return {
            "status": "configured",
            "message": "asdlc MCP server configured via claude CLI",
            "transport": "http",
        }

    # --- Fallback: direct file editing ---------------------------------
    if settings_path.exists():
        with open(settings_path) as f:
            settings = json.load(f)
    else:
        settings = {}

    if "mcpServers" not in settings:
        settings["mcpServers"] = {}

    # Remove old a-sdlc config if present (migration)
    if "a-sdlc" in settings["mcpServers"]:
        del settings["mcpServers"]["a-sdlc"]

    settings["mcpServers"]["asdlc"] = mcp_config

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    return {
        "status": "configured",
        "message": f"asdlc MCP server configured in {settings_path}",
        "settings_path": str(settings_path),
        "transport": "http",
    }


class Installer:
    """Deploys a-sdlc skill templates to Claude Code configuration."""

    DEFAULT_TARGET = Path.home() / ".claude" / "commands" / "sdlc"
    PERSONA_TARGET = Path.home() / ".claude" / "agents"

    def __init__(self, target: CLITarget | None = None, target_dir: Path | None = None) -> None:
        """Initialize installer with target CLI configuration.

        Args:
            target: CLI target configuration. Defaults to CLAUDE_TARGET.
            target_dir: Custom target directory override.
        """
        self.target = target or CLAUDE_TARGET
        self.target_dir = target_dir or self.target.commands_dir

    def install(
        self,
        force: bool = False,
        configure_mcp: bool = True,
        port: int = DEFAULT_MCP_PORT,
        url: str | None = None,
        auth_token: str | None = None,
    ) -> list[str]:
        """Install all skill templates to target directory.

        Args:
            force: If True, overwrite existing templates.
            configure_mcp: If True, also configure MCP server in Claude Code settings.
            port: Port for HTTP transport (default 8765).
            url: Explicit MCP server URL (overrides port). For Docker/cloud instances.
            auth_token: Bearer token for server authentication.

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
        if self.target.name == "gemini":
            # Transpile markdown to TOML for Gemini CLI
            installed = transpile_all(template_dir, self.target_dir)
        else:
            # Copy markdown files for Claude Code
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

        # Deploy persona agent files (skip if target has no agents_dir)
        if self.target.agents_dir is not None:
            self.install_personas(force=force)

        # Write version marker
        version_file = self.target_dir / ".version"
        version_file.write_text(__version__)

        # Configure MCP server
        if configure_mcp:
            configure_mcp_server(
                force=force, target=self.target, port=port, url=url,
                auth_token=auth_token,
            )

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
            with resources.as_file(resources.files("a_sdlc").joinpath("templates")) as template_path:
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
            with resources.as_file(resources.files("a_sdlc").joinpath("personas")) as persona_path:
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
        persona_target = self.target.agents_dir or self.PERSONA_TARGET
        persona_target.mkdir(parents=True, exist_ok=True)
        persona_dir = self._get_persona_dir()
        installed = []
        for persona_file in persona_dir.glob("*.md"):
            target_file = persona_target / persona_file.name
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
        persona_target = self.target.agents_dir or self.PERSONA_TARGET
        if not persona_target.exists():
            return 0
        count = 0
        for persona_file in persona_target.glob("sdlc-*.md"):
            persona_file.unlink()
            count += 1
        return count

    def list_installed_personas(self) -> list[dict]:
        """List deployed persona agent files matching sdlc-* pattern.

        Returns:
            List of dicts with 'name' and 'file' keys.
        """
        persona_target = self.target.agents_dir or self.PERSONA_TARGET
        if not persona_target.exists():
            return []
        personas = []
        for persona_file in sorted(persona_target.glob("sdlc-*.md")):
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
        persona_target = self.target.agents_dir or self.PERSONA_TARGET
        results = {}
        for persona_file in persona_dir.glob("*.md"):
            target_file = persona_target / persona_file.name
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
