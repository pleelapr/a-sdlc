"""Tests for extracted challenge helper functions.

Tests cover CHALLENGE_CHECKLISTS, detect_stale_loop, compute_round_status,
and load_challenge_config from the server/challenge.py module.
"""

from __future__ import annotations

from unittest.mock import patch

from a_sdlc.server.challenge import (
    CHALLENGE_CHECKLISTS,
    CHALLENGE_DEFAULTS,
    VALID_ARTIFACT_TYPES,
    compute_round_status,
    detect_stale_loop,
    load_challenge_config,
)


class TestChallengeChecklists:
    def test_all_artifact_types_present(self):
        assert "prd" in CHALLENGE_CHECKLISTS
        assert "design" in CHALLENGE_CHECKLISTS
        assert "split" in CHALLENGE_CHECKLISTS
        assert "task" in CHALLENGE_CHECKLISTS

    def test_valid_artifact_types_matches(self):
        assert frozenset(CHALLENGE_CHECKLISTS.keys()) == VALID_ARTIFACT_TYPES

    def test_each_checklist_is_non_empty(self):
        for artifact_type, checklist in CHALLENGE_CHECKLISTS.items():
            assert len(checklist) > 0, f"{artifact_type} has empty checklist"


class TestDetectStaleLoop:
    def test_no_previous_objections(self):
        is_stale, pct = detect_stale_loop(
            [{"description": "issue A"}], None
        )
        assert is_stale is False
        assert pct == 0.0

    def test_no_overlap(self):
        is_stale, pct = detect_stale_loop(
            [{"description": "issue A"}],
            [{"description": "issue B"}],
        )
        assert is_stale is False
        assert pct == 0.0

    def test_full_overlap_is_stale(self):
        objs = [{"description": "issue A"}, {"description": "issue B"}]
        is_stale, pct = detect_stale_loop(objs, objs)
        assert is_stale is True
        assert pct == 1.0

    def test_partial_overlap_below_threshold(self):
        current = [
            {"description": "issue A"},
            {"description": "issue B"},
            {"description": "issue C"},
            {"description": "issue D"},
            {"description": "issue E"},
        ]
        previous = [{"description": "issue A"}]
        is_stale, pct = detect_stale_loop(current, previous)
        assert is_stale is False

    def test_empty_current_not_stale(self):
        is_stale, pct = detect_stale_loop(
            [], [{"description": "issue A"}]
        )
        assert is_stale is False


class TestComputeRoundStatus:
    def test_none_verdict(self):
        assert compute_round_status(None) == "in_progress"

    def test_escalated(self):
        assert compute_round_status({"escalated": ["issue"]}) == "escalated"

    def test_resolved(self):
        assert compute_round_status({"resolved": ["fix"]}) == "resolved"

    def test_accepted(self):
        assert compute_round_status({"accepted": ["ok"]}) == "resolved"

    def test_empty_lists(self):
        assert compute_round_status({"resolved": [], "escalated": [], "accepted": []}) == "in_progress"


class TestLoadChallengeConfig:
    def test_defaults_when_no_config(self):
        with patch("a_sdlc.core.config_loader.load_section", return_value={}):
            config = load_challenge_config()
        assert config["enabled"] == CHALLENGE_DEFAULTS["enabled"]
        assert config["max_rounds"] == CHALLENGE_DEFAULTS["max_rounds"]

    def test_overrides_from_config(self):
        with patch(
            "a_sdlc.core.config_loader.load_section",
            return_value={"enabled": False, "max_rounds": 10},
        ):
            config = load_challenge_config()
        assert config["enabled"] is False
        assert config["max_rounds"] == 10

    def test_fallback_on_exception(self):
        with patch(
            "a_sdlc.core.config_loader.load_section",
            side_effect=RuntimeError("broken"),
        ):
            config = load_challenge_config()
        assert config == dict(CHALLENGE_DEFAULTS)
