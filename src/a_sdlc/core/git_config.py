"""
Git safety configuration layer for a-sdlc.

Provides layered configuration for git operations with safe defaults.
Global config (~/.config/a-sdlc/config.yaml) defines defaults (all off).
Project config (.sdlc/config.yaml) can override to enable specific operations.

Configuration keys under the 'git' section:
    auto_commit: bool      - Allow agent to commit changes (default: False)
    auto_pr: bool          - Allow agent to create PRs (default: False)
    auto_merge: bool       - Allow agent to merge branches (default: False)
    worktree_enabled: bool - Use worktree isolation for PRD execution (default: False)

Destructive operations (force push, branch deletion) always require
runtime user confirmation, regardless of configuration.
"""

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml


def get_config_dir() -> Path:
    """Get platform-specific configuration directory.

    Returns:
        Path: %LOCALAPPDATA%/a-sdlc on Windows, ~/.config/a-sdlc on macOS/Linux
    """
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "a-sdlc"
    else:
        return Path.home() / ".config" / "a-sdlc"


# Shared config paths (same as PluginManager and github.py)
GLOBAL_CONFIG_DIR = get_config_dir()
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.yaml"
PROJECT_CONFIG_DIR = ".sdlc"
PROJECT_CONFIG_FILE = "config.yaml"

# Default git safety settings — all dangerous operations OFF
_GIT_DEFAULTS: dict[str, bool] = {
    "auto_commit": False,
    "auto_pr": False,
    "auto_merge": False,
    "worktree_enabled": False,
}

# Operations that always require user confirmation, regardless of config
ALWAYS_CONFIRM_OPERATIONS = frozenset({
    "force_push",
    "branch_delete",
})


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


@dataclass(frozen=True)
class GitSafetyConfig:
    """Immutable git safety configuration.

    All fields default to False (safe mode) so that projects without
    explicit configuration have all dangerous operations disabled.
    """

    auto_commit: bool = False
    auto_pr: bool = False
    auto_merge: bool = False
    worktree_enabled: bool = False

    def is_operation_allowed(self, operation: str) -> bool:
        """Check if a git operation is allowed by this configuration.

        Destructive operations (force_push, branch_delete) always return
        False here — they require separate runtime user confirmation.

        Args:
            operation: Operation name. One of 'auto_commit', 'auto_pr',
                      'auto_merge', 'worktree_enabled', 'force_push',
                      'branch_delete'.

        Returns:
            True if the operation is allowed by configuration.
        """
        if operation in ALWAYS_CONFIRM_OPERATIONS:
            return False
        return getattr(self, operation, False)

    def to_dict(self) -> dict[str, bool]:
        """Serialize configuration to a dictionary.

        Returns:
            Dictionary of configuration values.
        """
        return {
            "auto_commit": self.auto_commit,
            "auto_pr": self.auto_pr,
            "auto_merge": self.auto_merge,
            "worktree_enabled": self.worktree_enabled,
        }

    def requires_confirmation(self, operation: str) -> bool:
        """Check if an operation always requires runtime user confirmation.

        Args:
            operation: Operation name.

        Returns:
            True if the operation requires user confirmation regardless of config.
        """
        return operation in ALWAYS_CONFIRM_OPERATIONS


def _load_yaml(path: Path) -> dict:
    """Safely load a YAML file, returning empty dict on failure.

    Args:
        path: Path to YAML file.

    Returns:
        Parsed YAML content or empty dict.
    """
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _save_yaml(path: Path, data: dict) -> None:
    """Save a dictionary as YAML, creating directories as needed.

    Args:
        path: Path to write.
        data: Dictionary to serialize.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)


def load_git_safety_config(project_dir: Path | None = None) -> GitSafetyConfig:
    """Load git safety configuration with layered merging.

    Priority (highest to lowest):
    1. Project config (.sdlc/config.yaml git section)
    2. Global config (~/.config/a-sdlc/config.yaml git section)
    3. Built-in defaults (all operations disabled)

    Args:
        project_dir: Project directory. Defaults to current working directory.

    Returns:
        GitSafetyConfig with merged settings.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    # Load global config
    global_config = _load_yaml(GLOBAL_CONFIG_FILE)
    global_git = global_config.get("git", {})
    if not isinstance(global_git, dict):
        global_git = {}

    # Load project config
    project_config_path = project_dir / PROJECT_CONFIG_DIR / PROJECT_CONFIG_FILE
    project_config = _load_yaml(project_config_path)
    project_git = project_config.get("git", {})
    if not isinstance(project_git, dict):
        project_git = {}

    # Merge: defaults < global < project
    merged = _deep_merge(_GIT_DEFAULTS, global_git)
    merged = _deep_merge(merged, project_git)

    # Only keep recognized keys, ensure boolean types
    return GitSafetyConfig(
        auto_commit=bool(merged.get("auto_commit", False)),
        auto_pr=bool(merged.get("auto_pr", False)),
        auto_merge=bool(merged.get("auto_merge", False)),
        worktree_enabled=bool(merged.get("worktree_enabled", False)),
    )


def save_git_safety_config(
    settings: dict[str, bool],
    target: Literal["global", "project"] = "project",
    project_dir: Path | None = None,
) -> Path:
    """Save git safety settings to the specified config file.

    Merges the git section into the existing YAML configuration,
    preserving other sections (plugins, testing, review, etc.).

    Args:
        settings: Dictionary of git safety settings to save.
                 Only recognized keys (auto_commit, auto_pr, auto_merge,
                 worktree_enabled) are persisted.
        target: Where to save — "global" or "project".
        project_dir: Project directory (for project target). Defaults to cwd.

    Returns:
        Path to the written config file.

    Raises:
        ValueError: If settings contains unrecognized keys.
    """
    recognized_keys = {"auto_commit", "auto_pr", "auto_merge", "worktree_enabled"}
    unknown_keys = set(settings.keys()) - recognized_keys
    if unknown_keys:
        raise ValueError(
            f"Unrecognized git safety keys: {', '.join(sorted(unknown_keys))}. "
            f"Valid keys: {', '.join(sorted(recognized_keys))}"
        )

    if project_dir is None:
        project_dir = Path.cwd()

    if target == "global":
        config_path = GLOBAL_CONFIG_FILE
    else:
        config_path = project_dir / PROJECT_CONFIG_DIR / PROJECT_CONFIG_FILE

    # Load existing config and merge git section
    existing = _load_yaml(config_path)
    existing_git = existing.get("git", {})
    if not isinstance(existing_git, dict):
        existing_git = {}

    # Apply only the provided settings (partial update)
    for key, value in settings.items():
        existing_git[key] = bool(value)

    existing["git"] = existing_git
    _save_yaml(config_path, existing)
    return config_path


def get_effective_config_summary(project_dir: Path | None = None) -> dict[str, Any]:
    """Get a summary showing the effective configuration and its sources.

    Useful for debugging which settings come from global vs project config.

    Args:
        project_dir: Project directory. Defaults to current working directory.

    Returns:
        Dictionary with effective values and their sources.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    global_config = _load_yaml(GLOBAL_CONFIG_FILE)
    global_git = global_config.get("git", {})
    if not isinstance(global_git, dict):
        global_git = {}

    project_config_path = project_dir / PROJECT_CONFIG_DIR / PROJECT_CONFIG_FILE
    project_config = _load_yaml(project_config_path)
    project_git = project_config.get("git", {})
    if not isinstance(project_git, dict):
        project_git = {}

    effective = load_git_safety_config(project_dir)

    summary: dict[str, Any] = {
        "effective": effective.to_dict(),
        "sources": {},
        "always_require_confirmation": sorted(ALWAYS_CONFIRM_OPERATIONS),
    }

    for key in ("auto_commit", "auto_pr", "auto_merge", "worktree_enabled"):
        if key in project_git:
            summary["sources"][key] = "project"
        elif key in global_git:
            summary["sources"][key] = "global"
        else:
            summary["sources"][key] = "default"

    return summary
