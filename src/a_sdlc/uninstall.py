"""
Uninstall module for removing all a-sdlc components.

Handles:
- Removing MCP server configs from ~/.claude.json and ~/.claude/settings.json
- Removing skill templates from ~/.claude/commands/sdlc/
- Stopping monitoring Docker services
- Removing monitoring files from ~/.a-sdlc/monitoring/
- Optionally removing project data (~/.a-sdlc/)
"""

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from a_sdlc.installer import Installer, get_claude_settings_path
from a_sdlc.mcp_setup import (
    CLAUDE_SETTINGS_PATH,
    load_claude_settings,
    save_claude_settings,
)
from a_sdlc.monitoring_setup import MONITORING_DIR, OTEL_ENV_VARS

# Environment variable keys installed by monitoring setup
LANGFUSE_ENV_KEYS = {"LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_HOST"}
AGENT_TEAMS_ENV_KEY = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
ALL_MANAGED_ENV_KEYS = set(OTEL_ENV_VARS.keys()) | LANGFUSE_ENV_KEYS | {AGENT_TEAMS_ENV_KEY}


@dataclass
class UninstallPlan:
    """Read-only discovery of what would be removed."""

    # MCP servers
    has_asdlc_mcp: bool = False
    has_serena_mcp: bool = False
    has_playwright_mcp: bool = False
    remove_serena: bool = False
    remove_playwright: bool = False

    # Skill templates
    skill_template_dir: Path | None = None
    skill_template_count: int = 0

    # Monitoring hook
    has_monitoring_hook: bool = False
    monitoring_hook_indices: list[int] = field(default_factory=list)

    # Environment variables
    managed_env_keys: list[str] = field(default_factory=list)

    # Monitoring files
    has_monitoring_dir: bool = False
    monitoring_dir: Path = field(default_factory=lambda: MONITORING_DIR)

    # Persona agents
    persona_dir: Path | None = None
    persona_count: int = 0

    # Project data
    has_data_dir: bool = False
    data_dir: Path | None = None

    # Flags
    include_data: bool = False


@dataclass
class UninstallResult:
    """Summary of actions taken during uninstall."""

    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


def build_uninstall_plan(include_data: bool = False) -> UninstallPlan:
    """Survey the system and build a read-only uninstall plan.

    Args:
        include_data: If True, plan includes removal of ~/.a-sdlc/ data directory.

    Returns:
        UninstallPlan describing what would be removed.
    """
    plan = UninstallPlan(include_data=include_data)

    # Check ~/.claude.json for asdlc MCP server
    claude_json_path = get_claude_settings_path()
    if claude_json_path.exists():
        try:
            with open(claude_json_path) as f:
                claude_json = json.load(f)
            plan.has_asdlc_mcp = "asdlc" in claude_json.get("mcpServers", {})
        except (json.JSONDecodeError, OSError):
            pass

    # Check ~/.claude/settings.json for serena, hooks, env
    if CLAUDE_SETTINGS_PATH.exists():
        settings = load_claude_settings()

        plan.has_serena_mcp = "serena" in settings.get("mcpServers", {})
        plan.has_playwright_mcp = "playwright" in settings.get("mcpServers", {})

        # Find monitoring hook indices
        stop_hooks = settings.get("hooks", {}).get("Stop", [])
        for i, entry in enumerate(stop_hooks):
            for hook in entry.get("hooks", []):
                if "langfuse-hook.py" in hook.get("command", ""):
                    plan.monitoring_hook_indices.append(i)
                    break
        plan.has_monitoring_hook = len(plan.monitoring_hook_indices) > 0

        # Find managed env keys
        env = settings.get("environment", {})
        plan.managed_env_keys = [k for k in ALL_MANAGED_ENV_KEYS if k in env]

    # Check skill templates
    installer = Installer()
    if installer.target_dir.exists():
        templates = list(installer.target_dir.glob("*.md"))
        if templates:
            plan.skill_template_dir = installer.target_dir
            plan.skill_template_count = len(templates)

    # Check persona agents
    persona_target = Installer.PERSONA_TARGET
    if persona_target.exists():
        personas = list(persona_target.glob("sdlc-*.md"))
        if personas:
            plan.persona_dir = persona_target
            plan.persona_count = len(personas)

    # Check monitoring directory
    plan.has_monitoring_dir = MONITORING_DIR.exists()

    # Check data directory
    from a_sdlc.core.database import get_data_dir

    data_dir = get_data_dir()
    plan.has_data_dir = data_dir.exists()
    plan.data_dir = data_dir

    return plan


def execute_uninstall(plan: UninstallPlan) -> UninstallResult:
    """Execute the uninstall plan, removing components in safe order.

    Execution order (least destructive first):
    1. Settings cleanup (JSON key removal)
    2. Skill templates
    3. Docker stop (best-effort)
    4. Monitoring files
    5. Project data (only with include_data)

    Args:
        plan: The uninstall plan from build_uninstall_plan().

    Returns:
        UninstallResult with actions taken, warnings, and errors.
    """
    result = UninstallResult()

    # Phase 1: Clean ~/.claude.json (asdlc MCP server)
    _remove_asdlc_mcp(plan, result)

    # Phase 2: Clean ~/.claude/settings.json (serena, hooks, env)
    _remove_settings_entries(plan, result)

    # Phase 3: Remove skill templates
    _remove_skill_templates(plan, result)

    # Phase 3.5: Remove persona agents
    _remove_personas(plan, result)

    # Phase 4: Stop Docker and remove monitoring files
    _remove_monitoring(plan, result)

    # Phase 5: Remove project data (only with --include-data)
    if plan.include_data:
        _remove_data_dir(plan, result)

    return result


def _remove_asdlc_mcp(plan: UninstallPlan, result: UninstallResult) -> None:
    """Remove asdlc MCP server from ~/.claude.json."""
    if not plan.has_asdlc_mcp:
        return

    try:
        settings_path = get_claude_settings_path()
        with open(settings_path) as f:
            settings = json.load(f)

        if "asdlc" in settings.get("mcpServers", {}):
            del settings["mcpServers"]["asdlc"]
            with open(settings_path, "w") as f:
                json.dump(settings, f, indent=2)
            result.actions.append("Removed asdlc MCP server from ~/.claude.json")
    except (json.JSONDecodeError, OSError) as e:
        result.errors.append(f"Failed to update ~/.claude.json: {e}")


def _remove_settings_entries(plan: UninstallPlan, result: UninstallResult) -> None:
    """Remove serena MCP, monitoring hooks, and env vars from settings.json."""
    needs_save = False

    try:
        settings = load_claude_settings()
        if not settings:
            return

        # Remove serena MCP server (only if user opted in)
        if plan.remove_serena and "serena" in settings.get("mcpServers", {}):
            del settings["mcpServers"]["serena"]
            needs_save = True
            result.actions.append("Removed serena MCP server from settings.json")

        # Remove playwright MCP server (only if user opted in)
        if plan.remove_playwright and "playwright" in settings.get("mcpServers", {}):
            del settings["mcpServers"]["playwright"]
            needs_save = True
            result.actions.append("Removed playwright MCP server from settings.json")

        # Remove monitoring hook entries (reverse order to preserve indices)
        if plan.monitoring_hook_indices:
            stop_hooks = settings.get("hooks", {}).get("Stop", [])
            for idx in sorted(plan.monitoring_hook_indices, reverse=True):
                if idx < len(stop_hooks):
                    stop_hooks.pop(idx)
            # Clean up empty structures
            if not stop_hooks:
                settings.get("hooks", {}).pop("Stop", None)
            if not settings.get("hooks"):
                settings.pop("hooks", None)
            needs_save = True
            result.actions.append("Removed monitoring hook from settings.json")

        # Remove managed environment variables
        if plan.managed_env_keys:
            env = settings.get("environment", {})
            removed = []
            for key in plan.managed_env_keys:
                if key in env:
                    del env[key]
                    removed.append(key)
            if not env:
                settings.pop("environment", None)
            if removed:
                needs_save = True
                result.actions.append(
                    f"Removed {len(removed)} environment variable(s) from settings.json"
                )

        if needs_save:
            save_claude_settings(settings)
    except (json.JSONDecodeError, OSError) as e:
        result.errors.append(f"Failed to update settings.json: {e}")


def _remove_skill_templates(plan: UninstallPlan, result: UninstallResult) -> None:
    """Remove skill templates via Installer.uninstall()."""
    if not plan.skill_template_dir or plan.skill_template_count == 0:
        return

    try:
        installer = Installer()
        count = installer.uninstall()
        if count > 0:
            result.actions.append(f"Removed {count} skill template(s)")
    except OSError as e:
        result.errors.append(f"Failed to remove skill templates: {e}")


def _remove_personas(plan: UninstallPlan, result: UninstallResult) -> None:
    """Remove persona agent files via Installer.uninstall_personas()."""
    if not plan.persona_dir or plan.persona_count == 0:
        return

    try:
        installer = Installer()
        count = installer.uninstall_personas()
        if count > 0:
            result.actions.append(f"Removed {count} persona agent(s)")
    except OSError as e:
        result.errors.append(f"Failed to remove persona agents: {e}")


def _remove_monitoring(plan: UninstallPlan, result: UninstallResult) -> None:
    """Stop Docker services and remove monitoring directory."""
    if not plan.has_monitoring_dir:
        return

    # Best-effort Docker stop
    compose_file = MONITORING_DIR / "docker-compose.yaml"
    if compose_file.exists() and shutil.which("docker"):
        try:
            subprocess.run(
                ["docker", "compose", "down"],
                cwd=str(MONITORING_DIR),
                capture_output=True,
                timeout=60,
            )
            result.actions.append("Stopped monitoring Docker services")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            result.warnings.append(
                "Could not stop monitoring Docker services "
                "(docker not available or timed out)"
            )

    # Remove monitoring directory
    try:
        shutil.rmtree(MONITORING_DIR)
        result.actions.append(f"Removed monitoring directory ({MONITORING_DIR})")
    except OSError as e:
        result.errors.append(f"Failed to remove monitoring directory: {e}")


def _remove_data_dir(plan: UninstallPlan, result: UninstallResult) -> None:
    """Remove the entire ~/.a-sdlc/ data directory."""
    if not plan.has_data_dir or not plan.data_dir:
        return

    try:
        shutil.rmtree(plan.data_dir)
        result.actions.append(f"Removed data directory ({plan.data_dir})")
    except OSError as e:
        result.errors.append(f"Failed to remove data directory: {e}")
