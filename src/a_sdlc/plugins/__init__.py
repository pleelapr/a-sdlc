"""
Plugin system for a-sdlc task storage backends.

Provides:
- Base plugin interface
- Plugin discovery and loading
- Plugin manager for configuration
"""

from pathlib import Path

import yaml

from a_sdlc.plugins.base import TaskPlugin


class PluginManager:
    """Manages task storage plugins."""

    CONFIG_FILE = Path.home() / ".config" / "a-sdlc" / "config.yaml"

    def __init__(self) -> None:
        """Initialize plugin manager."""
        self._plugins: dict[str, type[TaskPlugin]] = {}
        self._config: dict = {}
        self._load_builtin_plugins()
        self._load_config()

    def _load_builtin_plugins(self) -> None:
        """Register built-in plugins."""
        from a_sdlc.plugins.linear import LinearPlugin
        from a_sdlc.plugins.local import LocalPlugin

        self._plugins["local"] = LocalPlugin
        self._plugins["linear"] = LinearPlugin

    def _load_config(self) -> None:
        """Load configuration from file."""
        if self.CONFIG_FILE.exists():
            with open(self.CONFIG_FILE) as f:
                self._config = yaml.safe_load(f) or {}
        else:
            self._config = {}

    def _save_config(self) -> None:
        """Save configuration to file."""
        self.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(self.CONFIG_FILE, "w") as f:
            yaml.dump(self._config, f, default_flow_style=False)

    def list_plugins(self) -> list[str]:
        """List available plugin names."""
        return list(self._plugins.keys())

    def get_enabled_plugin(self) -> str:
        """Get the currently enabled plugin name."""
        return self._config.get("plugins", {}).get("tasks", {}).get("provider", "local")

    def enable_plugin(self, name: str) -> None:
        """Enable a plugin by name.

        Args:
            name: Plugin name to enable.

        Raises:
            ValueError: If plugin doesn't exist.
        """
        if name not in self._plugins:
            raise ValueError(f"Unknown plugin: {name}. Available: {', '.join(self._plugins.keys())}")

        if "plugins" not in self._config:
            self._config["plugins"] = {}
        if "tasks" not in self._config["plugins"]:
            self._config["plugins"]["tasks"] = {}

        self._config["plugins"]["tasks"]["provider"] = name
        self._save_config()

    def configure_plugin(self, name: str, config: dict) -> None:
        """Configure a plugin.

        Args:
            name: Plugin name to configure.
            config: Plugin-specific configuration dict.
        """
        if "plugins" not in self._config:
            self._config["plugins"] = {}
        if "tasks" not in self._config["plugins"]:
            self._config["plugins"]["tasks"] = {}

        self._config["plugins"]["tasks"][name] = config
        self._save_config()

    def get_plugin_config(self, name: str) -> dict:
        """Get configuration for a specific plugin.

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
