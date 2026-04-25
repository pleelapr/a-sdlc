"""Challenge system helper functions.

Extracted from server/__init__.py to reduce module size.
Contains challenge checklists, stale loop detection, and config loading.
"""

from __future__ import annotations

from typing import Any

CHALLENGE_CHECKLISTS: dict[str, list[str]] = {
    "prd": [
        "Are all requirements testable and unambiguous?",
        "Are there missing edge cases or error scenarios?",
        "Do NFRs have measurable acceptance criteria?",
        "Are there implicit assumptions not stated?",
        "Is the scope clearly bounded (what's excluded)?",
        "Are there conflicting requirements?",
        "Are integration points with existing systems identified?",
    ],
    "design": [
        "Does the design address all PRD requirements?",
        "Are there single points of failure?",
        "Is the migration strategy backward-compatible?",
        "Are error handling paths complete?",
        "Are performance implications analyzed?",
        "Does the design follow existing codebase patterns?",
    ],
    "split": [
        "Does every requirement have at least one linked task?",
        "Are task dependencies correctly identified?",
        "Are behavioral requirements assigned to tasks with test deliverables?",
        "Is the task granularity appropriate (not too coarse, not too fine)?",
        "Are there circular dependencies in the task graph?",
        "Are integration tasks identified for cross-component work?",
    ],
    "task": [
        "Does the implementation satisfy all linked acceptance criteria?",
        "Are edge cases handled in the code?",
        "Do tests verify behavioral requirements with actual assertions?",
        "Is error handling complete with exception details?",
        "Are there regressions in existing functionality?",
        "Does the code follow project patterns and conventions?",
    ],
}

VALID_ARTIFACT_TYPES = frozenset(CHALLENGE_CHECKLISTS.keys())

# Default challenge configuration when no quality config is available
CHALLENGE_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "max_rounds": 5,
}


def load_challenge_config() -> dict[str, Any]:
    """Load challenge configuration from project config.yaml.

    Falls back to defaults if no config is found or the section is missing.

    Returns:
        Dict with 'enabled' and 'max_rounds' keys.
    """
    try:
        from a_sdlc.core.config_loader import load_section

        challenge_section = load_section("challenge")
        return {
            "enabled": challenge_section.get("enabled", CHALLENGE_DEFAULTS["enabled"]),
            "max_rounds": int(
                challenge_section.get("max_rounds", CHALLENGE_DEFAULTS["max_rounds"])
            ),
        }
    except Exception:
        return dict(CHALLENGE_DEFAULTS)


def detect_stale_loop(
    current_objections: list[dict[str, Any]],
    previous_objections: list[dict[str, Any]] | None,
) -> tuple[bool, float]:
    """Detect if current objections substantially overlap with previous round.

    Compares the 'description' field of objection dicts.  When overlap
    exceeds 80%, the challenge is considered stale and should auto-terminate.

    Args:
        current_objections: Objections from the current round.
        previous_objections: Objections from the previous round (may be None).

    Returns:
        Tuple of (is_stale, overlap_pct).
    """
    if not previous_objections:
        return False, 0.0
    current_descs = {o.get("description", "") for o in current_objections}
    prev_descs = {o.get("description", "") for o in previous_objections}
    if not current_descs:
        return False, 0.0
    overlap = len(current_descs & prev_descs) / max(len(current_descs), 1)
    return overlap > 0.8, overlap


def compute_round_status(verdict: dict[str, Any] | None) -> str:
    """Derive round status from a verdict dict.

    Args:
        verdict: Dict with 'resolved', 'escalated', 'accepted' lists.

    Returns:
        Status string: 'resolved', 'escalated', or 'in_progress'.
    """
    if not verdict:
        return "in_progress"
    escalated = verdict.get("escalated", [])
    if escalated:
        return "escalated"
    resolved = verdict.get("resolved", [])
    accepted = verdict.get("accepted", [])
    total_handled = len(resolved) + len(accepted)
    if total_handled > 0:
        return "resolved"
    return "in_progress"
