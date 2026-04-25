"""
Review configuration layer for a-sdlc.

Provides layered configuration for code review behaviour with safe defaults.
Global config (~/.config/a-sdlc/config.yaml) defines defaults (all off).
Project config (.sdlc/config.yaml) can override to enable review features.

Configuration keys under the 'review' section:
    enabled: bool            - Master toggle for review system (default: False)
    self_review: bool        - Implementing agent must call submit_review(reviewer_type='self') (default: True)
    subagent_review: bool    - Orchestrator dispatches fresh reviewer (default: True)
    max_rounds: int          - Self-heal loop limit before escalation (default: 3)
    evidence_required: bool  - Require evidence for completion (default: True)

The config template in init.md generates a NESTED format where boolean
sub-sections use ``{enabled: true/false}``.  The loader handles both:
    - Flat:   ``self_review: true``
    - Nested: ``self_review: {enabled: true}``
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from a_sdlc.core.git_config import (
    GLOBAL_CONFIG_FILE,
    PROJECT_CONFIG_DIR,
    PROJECT_CONFIG_FILE,
    _deep_merge,
    _load_yaml,
)

# Default review settings — master toggle OFF for backward compatibility
_REVIEW_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "self_review": True,
    "subagent_review": True,
    "max_rounds": 3,
    "evidence_required": True,
}


@dataclass(frozen=True)
class ReviewConfig:
    """Immutable review configuration.

    The master toggle ``enabled`` defaults to False so that projects without
    explicit configuration see zero behavioural change.  All other fields
    carry sensible defaults that take effect once review is enabled.
    """

    enabled: bool = False
    self_review: bool = True
    subagent_review: bool = True
    max_rounds: int = 3
    evidence_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration to a dictionary.

        Returns:
            Dictionary of configuration values.
        """
        return {
            "enabled": self.enabled,
            "self_review": self.self_review,
            "subagent_review": self.subagent_review,
            "max_rounds": self.max_rounds,
            "evidence_required": self.evidence_required,
        }


def _normalise_bool_field(value: Any) -> bool:
    """Extract a boolean from either a plain value or a ``{enabled: ...}`` dict.

    Handles both flat (``self_review: true``) and nested
    (``self_review: {enabled: true}``) formats produced by the config
    template.

    Args:
        value: Raw value from the YAML config.

    Returns:
        Boolean interpretation of the value.
    """
    if isinstance(value, dict):
        return bool(value.get("enabled", False))
    return bool(value)


def load_review_config(project_dir: Path | None = None) -> ReviewConfig:
    """Load review configuration with layered merging.

    Priority (highest to lowest):
    1. Project config (.sdlc/config.yaml review section)
    2. Global config (~/.config/a-sdlc/config.yaml review section)
    3. Built-in defaults (enabled=False)

    Args:
        project_dir: Project directory. Defaults to current working directory.

    Returns:
        ReviewConfig with merged settings.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    # Load global config
    global_config = _load_yaml(GLOBAL_CONFIG_FILE)
    global_review = global_config.get("review", {})
    if not isinstance(global_review, dict):
        global_review = {}

    # Load project config
    project_config_path = project_dir / PROJECT_CONFIG_DIR / PROJECT_CONFIG_FILE
    project_config = _load_yaml(project_config_path)
    project_review = project_config.get("review", {})
    if not isinstance(project_review, dict):
        project_review = {}

    # Merge: defaults < global < project
    merged = _deep_merge(_REVIEW_DEFAULTS, global_review)
    merged = _deep_merge(merged, project_review)

    # Build config, handling both flat and nested boolean formats
    return ReviewConfig(
        enabled=bool(merged.get("enabled", False)),
        self_review=_normalise_bool_field(merged.get("self_review", True)),
        subagent_review=_normalise_bool_field(merged.get("subagent_review", True)),
        max_rounds=int(merged.get("max_rounds", 3)),
        evidence_required=_normalise_bool_field(merged.get("evidence_required", True)),
    )
