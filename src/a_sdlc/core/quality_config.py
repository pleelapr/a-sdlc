"""
Quality and challenge configuration layer for a-sdlc.

Provides layered configuration for quality gates and the challenge system
with safe defaults that ensure backward compatibility.

Global config (~/.config/a-sdlc/config.yaml) defines defaults (all off).
Project config (.sdlc/config.yaml) can override to enable quality features.

Configuration keys under the 'quality' section:
    enabled: bool                    - Master toggle (default: False)
    ac_gate: bool                    - Require AC verification (default: True)
    behavioral_test_required: bool   - Require behavioral tests (default: True)
    coverage_warnings: bool          - Emit coverage warnings (default: True)
    min_coverage_pct: int            - Minimum coverage percentage (default: 80)
    max_remediation_passes: int      - Max remediation iterations (default: 2)
    challenge:                       - Challenge subsystem configuration
        enabled: bool                - Challenge toggle (default: True)
        gate: str                    - Gate mode: 'hard' or 'soft' (default: 'hard')
        max_rounds: int              - Max challenge rounds (default: 3)
        gates: dict                  - Per-lifecycle-point toggles

The master toggle ``enabled`` defaults to False so that projects without
explicit configuration see zero behavioural change (NFR-005 / AC-007).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from a_sdlc.core.git_config import (
    GLOBAL_CONFIG_FILE,
    PROJECT_CONFIG_DIR,
    PROJECT_CONFIG_FILE,
    _deep_merge,
    _load_yaml,
)

# Default gates for each lifecycle point
_DEFAULT_CHALLENGE_GATES: dict[str, bool] = {
    "prd": True,
    "design": True,
    "split": True,
    "implementation": True,
}

# Default challenge settings
_CHALLENGE_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "gate": "hard",
    "max_rounds": 3,
    "gates": _DEFAULT_CHALLENGE_GATES.copy(),
}

# Default quality settings -- master toggle OFF for backward compatibility
_QUALITY_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "ac_gate": True,
    "behavioral_test_required": True,
    "coverage_warnings": True,
    "min_coverage_pct": 80,
    "max_remediation_passes": 2,
    "challenge": _CHALLENGE_DEFAULTS.copy(),
}


@dataclass(frozen=True)
class ChallengeConfig:
    """Immutable challenge configuration.

    Controls the challenge system that allows agents to challenge
    artifacts (PRDs, designs, task splits, implementations) before
    they are accepted.

    When ``enabled`` is False, no challenges are triggered at any
    lifecycle point regardless of per-gate settings (AC-018).
    """

    enabled: bool = True
    gate: str = "hard"
    max_rounds: int = 3
    gates: dict[str, bool] = field(
        default_factory=lambda: {
            "prd": True,
            "design": True,
            "split": True,
            "implementation": True,
        }
    )

    def is_gate_active(self, lifecycle_point: str) -> bool:
        """Check whether challenges are active for a lifecycle point.

        Returns False when the master ``enabled`` toggle is off,
        regardless of per-gate settings (AC-018).

        Args:
            lifecycle_point: One of 'prd', 'design', 'split', 'implementation'.

        Returns:
            True if challenges should be triggered for this lifecycle point.
        """
        if not self.enabled:
            return False
        return self.gates.get(lifecycle_point, False)

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration to a dictionary.

        Returns:
            Dictionary of configuration values.
        """
        return {
            "enabled": self.enabled,
            "gate": self.gate,
            "max_rounds": self.max_rounds,
            "gates": dict(self.gates),
        }


@dataclass(frozen=True)
class QualityConfig:
    """Immutable quality configuration.

    The master toggle ``enabled`` defaults to False so that projects without
    explicit configuration see zero behavioural change (NFR-005 / AC-007).
    All other fields carry sensible defaults that take effect once quality
    is enabled.
    """

    enabled: bool = False
    ac_gate: bool = True
    behavioral_test_required: bool = True
    coverage_warnings: bool = True
    min_coverage_pct: int = 80
    max_remediation_passes: int = 2
    challenge: ChallengeConfig = field(default_factory=ChallengeConfig)

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration to a dictionary.

        Returns:
            Dictionary of configuration values including nested challenge config.
        """
        return {
            "enabled": self.enabled,
            "ac_gate": self.ac_gate,
            "behavioral_test_required": self.behavioral_test_required,
            "coverage_warnings": self.coverage_warnings,
            "min_coverage_pct": self.min_coverage_pct,
            "max_remediation_passes": self.max_remediation_passes,
            "challenge": self.challenge.to_dict(),
        }


def _build_challenge_config(raw: dict[str, Any]) -> ChallengeConfig:
    """Build a ChallengeConfig from a raw dictionary, merging with defaults.

    Args:
        raw: Raw dictionary from the YAML config challenge section.

    Returns:
        ChallengeConfig with merged settings.
    """
    merged = _deep_merge(_CHALLENGE_DEFAULTS, raw)

    # Ensure gates is a dict and merge with defaults
    raw_gates = merged.get("gates", {})
    if not isinstance(raw_gates, dict):
        raw_gates = {}
    gates = _deep_merge(_DEFAULT_CHALLENGE_GATES, raw_gates)

    return ChallengeConfig(
        enabled=bool(merged.get("enabled", True)),
        gate=str(merged.get("gate", "hard")),
        max_rounds=int(merged.get("max_rounds", 3)),
        gates=gates,
    )


def load_quality_config(project_dir: Path | None = None) -> QualityConfig:
    """Load quality configuration with layered merging.

    Priority (highest to lowest):
    1. Project config (.sdlc/config.yaml quality section)
    2. Global config (~/.config/a-sdlc/config.yaml quality section)
    3. Built-in defaults (enabled=False)

    When the quality section is absent from all config files, returns
    a QualityConfig with enabled=False, ensuring zero behaviour change
    for projects that have not opted in (NFR-005 / AC-007).

    Args:
        project_dir: Project directory. Defaults to current working directory.

    Returns:
        QualityConfig with merged settings.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    # Load global config
    global_config = _load_yaml(GLOBAL_CONFIG_FILE)
    global_quality = global_config.get("quality", {})
    if not isinstance(global_quality, dict):
        global_quality = {}

    # Load project config
    project_config_path = project_dir / PROJECT_CONFIG_DIR / PROJECT_CONFIG_FILE
    project_config = _load_yaml(project_config_path)
    project_quality = project_config.get("quality", {})
    if not isinstance(project_quality, dict):
        project_quality = {}

    # Merge: defaults < global < project
    merged = _deep_merge(_QUALITY_DEFAULTS, global_quality)
    merged = _deep_merge(merged, project_quality)

    # Build nested ChallengeConfig
    raw_challenge = merged.get("challenge", {})
    if not isinstance(raw_challenge, dict):
        raw_challenge = {}
    challenge = _build_challenge_config(raw_challenge)

    return QualityConfig(
        enabled=bool(merged.get("enabled", False)),
        ac_gate=bool(merged.get("ac_gate", True)),
        behavioral_test_required=bool(merged.get("behavioral_test_required", True)),
        coverage_warnings=bool(merged.get("coverage_warnings", True)),
        min_coverage_pct=int(merged.get("min_coverage_pct", 80)),
        max_remediation_passes=int(merged.get("max_remediation_passes", 2)),
        challenge=challenge,
    )
