"""Centralized project config loading for a-sdlc.

Provides a single entry point for loading sections from ``.sdlc/config.yaml``,
eliminating duplicated config loading patterns across modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from a_sdlc.core.git_config import PROJECT_CONFIG_DIR, PROJECT_CONFIG_FILE, _load_yaml


def load_project_config(project_dir: Path | None = None) -> dict[str, Any]:
    """Load the full ``.sdlc/config.yaml`` with safe defaults.

    Args:
        project_dir: Project root directory. Defaults to current working directory.

    Returns:
        Parsed config dict, or empty dict if file is missing/invalid.
    """
    if project_dir is None:
        project_dir = Path.cwd()
    config_path = project_dir / PROJECT_CONFIG_DIR / PROJECT_CONFIG_FILE
    return _load_yaml(config_path) or {}


def load_section(section: str, project_dir: Path | None = None) -> dict[str, Any]:
    """Load a specific section from project config.

    Args:
        section: Config section key (e.g. ``"routing"``, ``"governance"``, ``"daemon"``).
        project_dir: Project root directory. Defaults to current working directory.

    Returns:
        Section dict, or empty dict if section is missing or not a dict.
    """
    config = load_project_config(project_dir)
    result = config.get(section, {})
    return result if isinstance(result, dict) else {}
