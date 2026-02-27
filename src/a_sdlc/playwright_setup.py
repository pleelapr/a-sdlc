"""
Playwright MCP installation and configuration.

Handles:
- Checking npx availability for running Playwright MCP server
- Updating ~/.claude/settings.json with Playwright configuration
- Verifying Playwright MCP installation
"""

import shutil
from typing import TypedDict

from a_sdlc.mcp_setup import (
    CLAUDE_SETTINGS_PATH,
    load_claude_settings,
    save_claude_settings,
)


class PlaywrightConfig(TypedDict):
    """Configuration for Playwright MCP server."""

    command: str
    args: list[str]


DEFAULT_PLAYWRIGHT_CONFIG: PlaywrightConfig = {
    "command": "npx",
    "args": ["@anthropic/mcp-playwright"],
}

PLAYWRIGHT_CONFIGS: dict[str, PlaywrightConfig] = {
    "npx": DEFAULT_PLAYWRIGHT_CONFIG,
}


def check_tool_available(tool: str) -> bool:
    """Check if a command-line tool is available.

    Args:
        tool: Name of the tool to check (e.g., 'npx', 'node')

    Returns:
        True if tool is available, False otherwise.
    """
    return shutil.which(tool) is not None


def get_available_installer() -> str | None:
    """Determine which package runner is available for Playwright.

    Checks for npx (shipped with Node.js/npm).

    Returns:
        Name of available runner, or None if none found.
    """
    if check_tool_available("npx"):
        return "npx"
    return None


def install_playwright(method: str | None = None) -> tuple[bool, str]:
    """Prepare Playwright MCP server for execution.

    Playwright MCP is run on-demand via npx, so this verifies npx is available.

    Args:
        method: Preferred runner method ('npx').
                If None, auto-detects available method.

    Returns:
        Tuple of (success, message)
    """
    if method is None:
        method = get_available_installer()

    if method is None:
        return False, (
            "npx not found. Please install Node.js:\n"
            "  - https://nodejs.org/\n"
            "  - Or via nvm: https://github.com/nvm-sh/nvm"
        )

    if method == "npx":
        if not check_tool_available("npx"):
            return False, (
                "npx not found. Install Node.js first: https://nodejs.org/"
            )
        return True, "Playwright MCP will be run via npx (on-demand installation)"

    return False, f"Unknown installation method: {method}"


def check_playwright_in_settings() -> bool:
    """Check if Playwright is configured in Claude Code settings.

    Returns:
        True if Playwright is configured, False otherwise.
    """
    settings = load_claude_settings()
    return "playwright" in settings.get("mcpServers", {})


def update_claude_settings(
    method: str = "npx", force: bool = False
) -> tuple[bool, str]:
    """Add Playwright to Claude Code MCP servers configuration.

    Args:
        method: Runner method to use ('npx')
        force: If True, overwrite existing Playwright config

    Returns:
        Tuple of (success, message)
    """
    settings = load_claude_settings()

    # Initialize mcpServers if not present
    if "mcpServers" not in settings:
        settings["mcpServers"] = {}

    # Check if already configured
    if "playwright" in settings["mcpServers"] and not force:
        return True, "Playwright already configured in Claude Code settings"

    # Get config for the specified method
    config = PLAYWRIGHT_CONFIGS.get(method, DEFAULT_PLAYWRIGHT_CONFIG)

    # Add Playwright configuration
    settings["mcpServers"]["playwright"] = config

    # Save settings
    try:
        save_claude_settings(settings)
        return True, f"Playwright configured in {CLAUDE_SETTINGS_PATH}"
    except OSError as e:
        return False, f"Failed to save settings: {e}"


def verify_setup() -> dict[str, bool | str]:
    """Verify Playwright MCP is properly configured.

    Returns:
        Dict with verification results
    """
    results: dict[str, bool | str] = {}

    # Check npx availability
    installer = get_available_installer()
    results["installer_available"] = installer is not None
    results["installer_method"] = installer or "none"

    # Check if configured in settings
    results["configured_in_settings"] = check_playwright_in_settings()

    # Check settings file path
    results["settings_file"] = str(CLAUDE_SETTINGS_PATH)
    results["settings_exists"] = CLAUDE_SETTINGS_PATH.exists()

    # Overall status
    results["ready"] = bool(
        results["installer_available"] and results["configured_in_settings"]
    )

    return results


def setup_playwright(force: bool = False) -> tuple[bool, str, dict]:
    """Complete Playwright MCP setup: check prerequisites and configure.

    Args:
        force: If True, force reconfigure even if already set up

    Returns:
        Tuple of (success, message, verification_results)
    """
    messages = []

    # Check if already set up
    if not force:
        verification = verify_setup()
        if verification["ready"]:
            return (
                True,
                "Playwright MCP is already set up and ready to use",
                verification,
            )

    # Find installer
    installer = get_available_installer()
    if not installer:
        return False, (
            "npx not available.\n\n"
            "Please install Node.js:\n"
            "  - https://nodejs.org/ (recommended)\n"
            "  - Or via nvm: https://github.com/nvm-sh/nvm"
        ), {}

    # Install Playwright
    success, msg = install_playwright(installer)
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


def get_playwright_status_message() -> str:
    """Get a human-readable status message about Playwright MCP setup.

    Returns:
        Status message string
    """
    verification = verify_setup()

    if verification["ready"]:
        return (
            f"Playwright MCP: Configured\n"
            f"  Method: {verification['installer_method']}\n"
            f"  Settings: {verification['settings_file']}"
        )

    issues = []
    if not verification["installer_available"]:
        issues.append("npx not found (install Node.js)")
    if not verification["configured_in_settings"]:
        issues.append("Not configured in Claude Code settings")

    return (
        "Playwright MCP: Not ready\n"
        f"  Issues: {', '.join(issues)}\n"
        "  Run: a-sdlc setup-playwright"
    )
