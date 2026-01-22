"""
Serena MCP installation and configuration.

Handles:
- Installing Serena MCP server via pip/pipx/uv
- Updating ~/.claude/settings.json with Serena configuration
- Verifying Serena installation
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import TypedDict


class SerenaConfig(TypedDict):
    """Configuration for Serena MCP server."""

    command: str
    args: list[str]
    env: dict[str, str]


CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

DEFAULT_SERENA_CONFIG: SerenaConfig = {
    "command": "uvx",
    "args": ["--from", "serena-agent", "serena"],
    "env": {"SERENA_LOG_LEVEL": "WARNING"},
}

# Alternative configurations for different installation methods
SERENA_CONFIGS: dict[str, SerenaConfig] = {
    "uvx": DEFAULT_SERENA_CONFIG,
    "pipx": {
        "command": "pipx",
        "args": ["run", "serena-agent"],
        "env": {"SERENA_LOG_LEVEL": "WARNING"},
    },
}


def check_tool_available(tool: str) -> bool:
    """Check if a command-line tool is available.

    Args:
        tool: Name of the tool to check (e.g., 'uvx', 'pipx', 'pip')

    Returns:
        True if tool is available, False otherwise.
    """
    return shutil.which(tool) is not None


def get_available_installer() -> str | None:
    """Determine which package installer is available.

    Checks in order of preference: uvx, pipx

    Returns:
        Name of available installer, or None if none found.
    """
    for tool in ["uvx", "pipx"]:
        if check_tool_available(tool):
            return tool
    return None


def check_serena_installed() -> tuple[bool, str | None]:
    """Check if Serena is available and which installer to use.

    Returns:
        Tuple of (is_installed, installer_method)
    """
    # Check if uvx can run serena
    if check_tool_available("uvx"):
        try:
            result = subprocess.run(
                ["uvx", "--from", "serena-agent", "serena", "--help"],
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0:
                return True, "uvx"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # Check if pipx can run serena
    if check_tool_available("pipx"):
        try:
            result = subprocess.run(
                ["pipx", "run", "serena-agent", "--help"],
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0:
                return True, "pipx"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return False, None


def install_serena(method: str | None = None) -> tuple[bool, str]:
    """Install Serena MCP server.

    Args:
        method: Preferred installation method ('uvx' or 'pipx').
                If None, auto-detects available method.

    Returns:
        Tuple of (success, message)
    """
    if method is None:
        method = get_available_installer()

    if method is None:
        return False, (
            "No package installer found. Please install one of:\n"
            "  - uv: https://docs.astral.sh/uv/\n"
            "  - pipx: https://pypa.github.io/pipx/"
        )

    # Serena is installed on-demand via uvx/pipx, so we just verify the tools are available
    if method == "uvx":
        if not check_tool_available("uvx"):
            return False, "uvx not found. Install uv first: https://docs.astral.sh/uv/"
        return True, "Serena will be run via uvx (on-demand installation)"

    if method == "pipx":
        if not check_tool_available("pipx"):
            return False, "pipx not found. Install pipx first: pip install pipx"
        return True, "Serena will be run via pipx (on-demand installation)"

    return False, f"Unknown installation method: {method}"


def load_claude_settings() -> dict:
    """Load existing Claude Code settings.

    Returns:
        Settings dict (empty dict if file doesn't exist)
    """
    if not CLAUDE_SETTINGS_PATH.exists():
        return {}

    try:
        with open(CLAUDE_SETTINGS_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_claude_settings(settings: dict) -> None:
    """Save Claude Code settings.

    Args:
        settings: Settings dict to save
    """
    CLAUDE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(CLAUDE_SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def check_serena_in_settings() -> bool:
    """Check if Serena is configured in Claude Code settings.

    Returns:
        True if Serena is configured, False otherwise.
    """
    settings = load_claude_settings()
    return "serena" in settings.get("mcpServers", {})


def update_claude_settings(method: str = "uvx", force: bool = False) -> tuple[bool, str]:
    """Add Serena to Claude Code MCP servers configuration.

    Args:
        method: Installation method to use ('uvx' or 'pipx')
        force: If True, overwrite existing Serena config

    Returns:
        Tuple of (success, message)
    """
    settings = load_claude_settings()

    # Initialize mcpServers if not present
    if "mcpServers" not in settings:
        settings["mcpServers"] = {}

    # Check if already configured
    if "serena" in settings["mcpServers"] and not force:
        return True, "Serena already configured in Claude Code settings"

    # Get config for the specified method
    config = SERENA_CONFIGS.get(method, DEFAULT_SERENA_CONFIG)

    # Add Serena configuration
    settings["mcpServers"]["serena"] = config

    # Save settings
    try:
        save_claude_settings(settings)
        return True, f"Serena configured in {CLAUDE_SETTINGS_PATH}"
    except OSError as e:
        return False, f"Failed to save settings: {e}"


def verify_setup() -> dict[str, bool | str]:
    """Verify Serena is properly configured.

    Returns:
        Dict with verification results
    """
    results: dict[str, bool | str] = {}

    # Check installer availability
    installer = get_available_installer()
    results["installer_available"] = installer is not None
    results["installer_method"] = installer or "none"

    # Check if configured in settings
    results["configured_in_settings"] = check_serena_in_settings()

    # Check settings file path
    results["settings_file"] = str(CLAUDE_SETTINGS_PATH)
    results["settings_exists"] = CLAUDE_SETTINGS_PATH.exists()

    # Overall status
    results["ready"] = bool(
        results["installer_available"] and results["configured_in_settings"]
    )

    return results


def setup_serena(force: bool = False) -> tuple[bool, str, dict]:
    """Complete Serena setup: install and configure.

    Args:
        force: If True, force reinstall even if already configured

    Returns:
        Tuple of (success, message, verification_results)
    """
    messages = []

    # Check if already set up
    if not force:
        verification = verify_setup()
        if verification["ready"]:
            return True, "Serena is already set up and ready to use", verification

    # Find installer
    installer = get_available_installer()
    if not installer:
        return False, (
            "No package installer available.\n\n"
            "Please install one of the following:\n"
            "  - uv (recommended): https://docs.astral.sh/uv/\n"
            "  - pipx: pip install pipx"
        ), {}

    # Install Serena
    success, msg = install_serena(installer)
    if not success:
        return False, msg, {}
    messages.append(msg)

    # Configure Claude Code settings
    success, msg = update_claude_settings(method=installer, force=force)
    if not success:
        return False, msg, {}
    messages.append(msg)

    # Verify setup
    verification = verify_setup()

    return True, "\n".join(messages), verification


def get_serena_status_message() -> str:
    """Get a human-readable status message about Serena setup.

    Returns:
        Status message string
    """
    verification = verify_setup()

    if verification["ready"]:
        return (
            f"Serena MCP: Configured\n"
            f"  Method: {verification['installer_method']}\n"
            f"  Settings: {verification['settings_file']}"
        )

    issues = []
    if not verification["installer_available"]:
        issues.append("No package installer (uvx/pipx) found")
    if not verification["configured_in_settings"]:
        issues.append("Not configured in Claude Code settings")

    return (
        "Serena MCP: Not ready\n"
        f"  Issues: {', '.join(issues)}\n"
        "  Run: a-sdlc setup-mcp"
    )
