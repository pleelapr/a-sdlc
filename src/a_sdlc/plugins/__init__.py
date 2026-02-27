"""
Plugin system for a-sdlc task storage backends.

Provides:
- Base plugin interface
- Plugin discovery and loading
- Plugin manager for configuration

Configuration is loaded from two locations (project config takes precedence):
1. Project config: .sdlc/config.yaml (in current directory)
2. Global config: ~/.config/a-sdlc/config.yaml (user-wide defaults)
"""

from pathlib import Path
from typing import Literal

import yaml

from a_sdlc.core.git_config import get_config_dir
from a_sdlc.plugins.base import TaskPlugin


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries, with override taking precedence.

    Args:
        base: Base dictionary (lower priority).
        override: Override dictionary (higher priority).

    Returns:
        Merged dictionary.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class PluginManager:
    """Manages task storage plugins.

    Configuration is loaded from two locations:
    - Project config: .sdlc/config.yaml (takes precedence)
    - Global config: ~/.config/a-sdlc/config.yaml (fallback)

    When saving, you can choose the target location.
    """

    GLOBAL_CONFIG_FILE = get_config_dir() / "config.yaml"
    PROJECT_CONFIG_DIR = ".sdlc"
    PROJECT_CONFIG_FILE = "config.yaml"

    def __init__(self, project_dir: Path | None = None) -> None:
        """Initialize plugin manager.

        Args:
            project_dir: Project directory to look for .sdlc/config.yaml.
                        If None, uses current working directory.
        """
        self._plugins: dict[str, type[TaskPlugin]] = {}
        self._global_config: dict = {}
        self._project_config: dict = {}
        self._project_dir = project_dir or Path.cwd()
        self._load_builtin_plugins()
        self._load_config()

    @property
    def project_config_path(self) -> Path:
        """Get path to project config file."""
        return self._project_dir / self.PROJECT_CONFIG_DIR / self.PROJECT_CONFIG_FILE

    @property
    def _config(self) -> dict:
        """Get merged configuration (project overrides global)."""
        return _deep_merge(self._global_config, self._project_config)

    def _load_builtin_plugins(self) -> None:
        """Register built-in plugins."""
        from a_sdlc.plugins.jira import JiraPlugin
        from a_sdlc.plugins.linear import LinearPlugin
        from a_sdlc.plugins.local import LocalPlugin

        self._plugins["local"] = LocalPlugin
        self._plugins["linear"] = LinearPlugin
        self._plugins["jira"] = JiraPlugin

    def _load_config(self) -> None:
        """Load configuration from both global and project files."""
        # Load global config
        if self.GLOBAL_CONFIG_FILE.exists():
            with open(self.GLOBAL_CONFIG_FILE) as f:
                self._global_config = yaml.safe_load(f) or {}
        else:
            self._global_config = {}

        # Load project config
        if self.project_config_path.exists():
            with open(self.project_config_path) as f:
                self._project_config = yaml.safe_load(f) or {}
        else:
            self._project_config = {}

    def _save_config(
        self,
        target: Literal["global", "project"] = "project",
        config_updates: dict | None = None,
    ) -> None:
        """Save configuration to specified location.

        Args:
            target: Where to save - "global" or "project".
            config_updates: Specific updates to apply. If None, saves current config.
        """
        if target == "global":
            config_file = self.GLOBAL_CONFIG_FILE
            current_config = self._global_config
        else:
            config_file = self.project_config_path
            current_config = self._project_config

        # Apply updates if provided
        if config_updates:
            current_config = _deep_merge(current_config, config_updates)
            if target == "global":
                self._global_config = current_config
            else:
                self._project_config = current_config

        # Ensure directory exists and save
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, "w") as f:
            yaml.dump(current_config, f, default_flow_style=False)

    def list_plugins(self) -> list[str]:
        """List available plugin names."""
        return list(self._plugins.keys())

    def get_enabled_plugin(self) -> str:
        """Get the currently enabled plugin name."""
        return self._config.get("plugins", {}).get("tasks", {}).get("provider", "local")

    def enable_plugin(
        self,
        name: str,
        target: Literal["global", "project"] = "project",
    ) -> None:
        """Enable a plugin by name.

        Args:
            name: Plugin name to enable.
            target: Where to save - "global" or "project" (default: project).

        Raises:
            ValueError: If plugin doesn't exist.
        """
        if name not in self._plugins:
            raise ValueError(f"Unknown plugin: {name}. Available: {', '.join(self._plugins.keys())}")

        config_updates = {"plugins": {"tasks": {"provider": name}}}
        self._save_config(target=target, config_updates=config_updates)

    def configure_plugin(
        self,
        name: str,
        config: dict,
        target: Literal["global", "project"] = "project",
    ) -> None:
        """Configure a plugin.

        Args:
            name: Plugin name to configure.
            config: Plugin-specific configuration dict.
            target: Where to save - "global" or "project" (default: project).
        """
        config_updates = {"plugins": {"tasks": {name: config}}}
        self._save_config(target=target, config_updates=config_updates)

    def get_plugin_config(self, name: str) -> dict:
        """Get configuration for a specific plugin.

        Merges global and project configs, with project taking precedence.

        Args:
            name: Plugin name.

        Returns:
            Plugin configuration dict.
        """
        return self._config.get("plugins", {}).get("tasks", {}).get(name, {})

    def get_plugin(self, name: str | None = None) -> TaskPlugin:
        """Get an instantiated plugin.

        Args:
            name: Plugin name. If None, uses enabled plugin.

        Returns:
            Instantiated TaskPlugin.

        Raises:
            ValueError: If plugin doesn't exist.
        """
        if name is None:
            name = self.get_enabled_plugin()

        if name not in self._plugins:
            raise ValueError(f"Unknown plugin: {name}")

        plugin_class = self._plugins[name]
        config = self.get_plugin_config(name)

        return plugin_class(config)


# Global plugin manager instance
_plugin_manager: PluginManager | None = None


def get_plugin_manager() -> PluginManager:
    """Get the global plugin manager instance."""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager


__all__ = ["TaskPlugin", "PluginManager", "get_plugin_manager"]
