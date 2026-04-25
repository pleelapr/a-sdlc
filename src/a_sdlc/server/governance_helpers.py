"""Governance system helper functions.

Extracted from server/__init__.py to reduce module size.
Contains routing config and governance health config loading.
"""

from __future__ import annotations

from typing import Any


def load_routing_config() -> dict[str, Any]:
    """Load routing configuration from .sdlc/config.yaml.

    Returns the ``routing`` section with ``component_map`` and other settings.
    Falls back to empty dict when config is absent (backward compatible).
    """
    try:
        from a_sdlc.core.config_loader import load_section

        return load_section("routing")
    except Exception:
        return {}


_GOVERNANCE_HEALTH_DEFAULTS: dict[str, Any] = {
    "stalled_timeout_min": 30,
    "error_rate_threshold_pct": 30,
    "quality_threshold": 40,
    "action": "alert",
}


def load_governance_health_config() -> dict[str, Any]:
    """Load governance health thresholds from .sdlc/config.yaml.

    Returns the ``governance.health`` section with thresholds.
    Provides sensible defaults when config is absent (REM-013).
    """
    try:
        from a_sdlc.core.config_loader import load_section

        governance = load_section("governance")
        health = governance.get("health", {})
        if not isinstance(health, dict):
            return dict(_GOVERNANCE_HEALTH_DEFAULTS)
        # Merge with defaults so missing keys get sensible values
        merged = dict(_GOVERNANCE_HEALTH_DEFAULTS)
        merged.update(health)
        return merged
    except Exception:
        return dict(_GOVERNANCE_HEALTH_DEFAULTS)
