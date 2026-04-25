"""Tests for quality and challenge configuration layer.

Covers SDLC-T00171 / P0029: QualityConfig, ChallengeConfig dataclasses,
load_quality_config() function, backward compatibility guarantees,
and centralized config_loader utilities.
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from a_sdlc.core.config_loader import load_project_config, load_section
from a_sdlc.core.quality_config import (
    ChallengeConfig,
    QualityConfig,
    _build_challenge_config,
    load_quality_config,
)

# =============================================================================
# ChallengeConfig dataclass
# =============================================================================


class TestChallengeConfig:
    """Test ChallengeConfig dataclass behavior."""

    def test_defaults(self):
        """Default ChallengeConfig has expected values."""
        config = ChallengeConfig()
        assert config.enabled is True
        assert config.gate == "hard"
        assert config.max_rounds == 3
        assert config.gates == {
            "prd": True,
            "design": True,
            "split": True,
            "implementation": True,
        }

    def test_frozen_dataclass(self):
        """Config is immutable (frozen dataclass)."""
        config = ChallengeConfig()
        with pytest.raises(AttributeError):
            config.enabled = False  # type: ignore[misc]

    def test_custom_values(self):
        """All fields can be set via constructor."""
        config = ChallengeConfig(
            enabled=False,
            gate="soft",
            max_rounds=5,
            gates={"prd": False, "design": True, "split": False, "implementation": True},
        )
        assert config.enabled is False
        assert config.gate == "soft"
        assert config.max_rounds == 5
        assert config.gates["prd"] is False
        assert config.gates["design"] is True

    def test_to_dict(self):
        """Serialization produces expected keys and values."""
        config = ChallengeConfig(enabled=False, gate="soft", max_rounds=5)
        d = config.to_dict()
        assert d["enabled"] is False
        assert d["gate"] == "soft"
        assert d["max_rounds"] == 5
        assert isinstance(d["gates"], dict)
        assert len(d["gates"]) == 4

    def test_is_gate_active_when_enabled(self):
        """is_gate_active returns per-gate value when master toggle is on."""
        config = ChallengeConfig(
            enabled=True,
            gates={"prd": True, "design": False, "split": True, "implementation": True},
        )
        assert config.is_gate_active("prd") is True
        assert config.is_gate_active("design") is False
        assert config.is_gate_active("split") is True

    def test_is_gate_active_when_disabled(self):
        """is_gate_active returns False for all gates when master toggle is off (AC-018)."""
        config = ChallengeConfig(enabled=False)
        assert config.is_gate_active("prd") is False
        assert config.is_gate_active("design") is False
        assert config.is_gate_active("split") is False
        assert config.is_gate_active("implementation") is False

    def test_is_gate_active_unknown_lifecycle_point(self):
        """is_gate_active returns False for unknown lifecycle points."""
        config = ChallengeConfig(enabled=True)
        assert config.is_gate_active("unknown") is False


# =============================================================================
# QualityConfig dataclass
# =============================================================================


class TestQualityConfig:
    """Test QualityConfig dataclass behavior."""

    def test_defaults(self):
        """Default QualityConfig has expected values matching PRD spec."""
        config = QualityConfig()
        assert config.enabled is False
        assert config.ac_gate is True
        assert config.behavioral_test_required is True
        assert config.coverage_warnings is True
        assert config.min_coverage_pct == 80
        assert config.max_remediation_passes == 2
        assert isinstance(config.challenge, ChallengeConfig)
        assert config.challenge.enabled is True

    def test_frozen_dataclass(self):
        """Config is immutable (frozen dataclass)."""
        config = QualityConfig()
        with pytest.raises(AttributeError):
            config.enabled = True  # type: ignore[misc]

    def test_custom_values(self):
        """All fields can be set via constructor."""
        config = QualityConfig(
            enabled=True,
            ac_gate=False,
            behavioral_test_required=False,
            coverage_warnings=False,
            min_coverage_pct=90,
            max_remediation_passes=5,
            challenge=ChallengeConfig(enabled=False),
        )
        assert config.enabled is True
        assert config.ac_gate is False
        assert config.behavioral_test_required is False
        assert config.coverage_warnings is False
        assert config.min_coverage_pct == 90
        assert config.max_remediation_passes == 5
        assert config.challenge.enabled is False

    def test_to_dict(self):
        """Serialization produces expected keys and values including nested challenge."""
        config = QualityConfig(enabled=True, min_coverage_pct=90)
        d = config.to_dict()
        assert d["enabled"] is True
        assert d["ac_gate"] is True
        assert d["behavioral_test_required"] is True
        assert d["coverage_warnings"] is True
        assert d["min_coverage_pct"] == 90
        assert d["max_remediation_passes"] == 2
        assert isinstance(d["challenge"], dict)
        assert d["challenge"]["enabled"] is True
        assert d["challenge"]["gate"] == "hard"

    def test_nested_challenge_default_factory(self):
        """Each QualityConfig instance gets its own ChallengeConfig."""
        c1 = QualityConfig()
        c2 = QualityConfig()
        assert c1.challenge is not c2.challenge
        assert c1.challenge.gates is not c2.challenge.gates


# =============================================================================
# _build_challenge_config helper
# =============================================================================


class TestBuildChallengeConfig:
    """Test the _build_challenge_config helper."""

    def test_empty_dict_returns_defaults(self):
        """Empty dict should produce default ChallengeConfig."""
        config = _build_challenge_config({})
        assert config.enabled is True
        assert config.gate == "hard"
        assert config.max_rounds == 3
        assert config.gates == {
            "prd": True,
            "design": True,
            "split": True,
            "implementation": True,
        }

    def test_partial_override(self):
        """Partial dict should merge with defaults."""
        config = _build_challenge_config({"max_rounds": 5, "gate": "soft"})
        assert config.max_rounds == 5
        assert config.gate == "soft"
        assert config.enabled is True  # default

    def test_partial_gates_override(self):
        """Overriding some gates should merge with default gates."""
        config = _build_challenge_config({"gates": {"prd": False}})
        assert config.gates["prd"] is False
        assert config.gates["design"] is True  # default preserved
        assert config.gates["split"] is True  # default preserved

    def test_non_dict_gates_ignored(self):
        """Non-dict gates value should fall back to defaults."""
        config = _build_challenge_config({"gates": "invalid"})
        assert config.gates == {
            "prd": True,
            "design": True,
            "split": True,
            "implementation": True,
        }


# =============================================================================
# load_quality_config -- defaults / absent config
# =============================================================================


class TestLoadQualityConfigDefaults:
    """Test loading quality config when quality section is absent (AC-007)."""

    def test_defaults_when_no_config_files(self):
        """Without any config files, quality is disabled with safe defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_quality_config(Path(tmpdir))
            assert config.enabled is False
            assert config.ac_gate is True
            assert config.behavioral_test_required is True
            assert config.coverage_warnings is True
            assert config.min_coverage_pct == 80
            assert config.max_remediation_passes == 2
            assert config.challenge.enabled is True
            assert config.challenge.gate == "hard"

    def test_config_yaml_without_quality_section(self):
        """A config.yaml with no quality section returns defaults (AC-007)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({"testing": {"commands": {"unit": "pytest"}}})
            )

            config = load_quality_config(project_dir)
            assert config.enabled is False
            assert config.ac_gate is True

    def test_explicit_enabled_false(self):
        """Explicit enabled: false returns disabled config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({"quality": {"enabled": False}}))

            config = load_quality_config(project_dir)
            assert config.enabled is False


# =============================================================================
# load_quality_config -- enabled with overrides
# =============================================================================


class TestLoadQualityConfigEnabled:
    """Test loading quality config when quality is enabled."""

    def test_enabled_with_all_overrides(self):
        """Full config overrides all defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump(
                    {
                        "quality": {
                            "enabled": True,
                            "ac_gate": False,
                            "behavioral_test_required": False,
                            "coverage_warnings": False,
                            "min_coverage_pct": 95,
                            "max_remediation_passes": 5,
                            "challenge": {
                                "enabled": False,
                                "gate": "soft",
                                "max_rounds": 7,
                                "gates": {
                                    "prd": False,
                                    "design": False,
                                    "split": True,
                                    "implementation": True,
                                },
                            },
                        }
                    }
                )
            )

            config = load_quality_config(project_dir)
            assert config.enabled is True
            assert config.ac_gate is False
            assert config.behavioral_test_required is False
            assert config.coverage_warnings is False
            assert config.min_coverage_pct == 95
            assert config.max_remediation_passes == 5
            assert config.challenge.enabled is False
            assert config.challenge.gate == "soft"
            assert config.challenge.max_rounds == 7
            assert config.challenge.gates["prd"] is False
            assert config.challenge.gates["design"] is False
            assert config.challenge.gates["split"] is True

    def test_partial_config_uses_defaults_for_rest(self):
        """Only provided fields override, others stay at defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump(
                    {
                        "quality": {
                            "enabled": True,
                            "min_coverage_pct": 90,
                        }
                    }
                )
            )

            config = load_quality_config(project_dir)
            assert config.enabled is True
            assert config.min_coverage_pct == 90
            assert config.ac_gate is True  # default
            assert config.behavioral_test_required is True  # default
            assert config.max_remediation_passes == 2  # default
            assert config.challenge.enabled is True  # default
            assert config.challenge.max_rounds == 3  # default

    def test_partial_challenge_config(self):
        """Partial challenge section merges with defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump(
                    {
                        "quality": {
                            "enabled": True,
                            "challenge": {
                                "max_rounds": 5,
                            },
                        }
                    }
                )
            )

            config = load_quality_config(project_dir)
            assert config.challenge.max_rounds == 5
            assert config.challenge.enabled is True  # default
            assert config.challenge.gate == "hard"  # default
            assert config.challenge.gate == "hard"  # default


# =============================================================================
# load_quality_config -- challenge.enabled=false (AC-018)
# =============================================================================


class TestChallengeDisabled:
    """Test that challenge.enabled=false disables all challenge gates (AC-018)."""

    def test_challenge_disabled_no_gates_active(self):
        """When challenge.enabled=false, no lifecycle gates should be active."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump(
                    {
                        "quality": {
                            "enabled": True,
                            "challenge": {
                                "enabled": False,
                            },
                        }
                    }
                )
            )

            config = load_quality_config(project_dir)
            assert config.challenge.enabled is False
            # All gates should report inactive via is_gate_active
            assert config.challenge.is_gate_active("prd") is False
            assert config.challenge.is_gate_active("design") is False
            assert config.challenge.is_gate_active("split") is False
            assert config.challenge.is_gate_active("implementation") is False


# =============================================================================
# load_quality_config -- layered merge
# =============================================================================


class TestLoadQualityConfigLayeredMerge:
    """Test layered merging: defaults < global < project."""

    def test_global_config_overrides_defaults(self, tmp_path, monkeypatch):
        """Global config overrides built-in defaults."""
        global_config_dir = tmp_path / "global_config"
        global_config_dir.mkdir()
        global_config_file = global_config_dir / "config.yaml"
        global_config_file.write_text(
            yaml.dump({"quality": {"enabled": True, "min_coverage_pct": 70}})
        )

        monkeypatch.setattr(
            "a_sdlc.core.quality_config.GLOBAL_CONFIG_FILE",
            global_config_file,
        )

        with tempfile.TemporaryDirectory() as project_dir:
            config = load_quality_config(Path(project_dir))
            assert config.enabled is True
            assert config.min_coverage_pct == 70
            assert config.ac_gate is True  # still default

    def test_project_overrides_global(self, tmp_path, monkeypatch):
        """Project config takes precedence over global config."""
        # Global: min_coverage_pct=70, ac_gate=False
        global_config_dir = tmp_path / "global_config"
        global_config_dir.mkdir()
        global_config_file = global_config_dir / "config.yaml"
        global_config_file.write_text(
            yaml.dump(
                {
                    "quality": {
                        "enabled": True,
                        "min_coverage_pct": 70,
                        "ac_gate": False,
                    }
                }
            )
        )
        monkeypatch.setattr(
            "a_sdlc.core.quality_config.GLOBAL_CONFIG_FILE",
            global_config_file,
        )

        # Project: min_coverage_pct=95 (override global)
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        sdlc_dir = project_dir / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text(yaml.dump({"quality": {"min_coverage_pct": 95}}))

        config = load_quality_config(project_dir)
        assert config.min_coverage_pct == 95  # project override wins
        assert config.ac_gate is False  # global value kept
        assert config.enabled is True  # global value kept


# =============================================================================
# load_quality_config -- error handling
# =============================================================================


class TestLoadQualityConfigErrorHandling:
    """Test robustness with missing or malformed config files."""

    def test_missing_config_file(self):
        """Missing config file returns safe defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_quality_config(Path(tmpdir))
            assert config.enabled is False
            assert config.ac_gate is True
            assert config.min_coverage_pct == 80

    def test_malformed_yaml(self):
        """Malformed YAML files are treated as empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text("{{invalid yaml")

            config = load_quality_config(project_dir)
            assert config.enabled is False
            assert config.ac_gate is True

    def test_non_dict_quality_section(self):
        """Non-dict quality section is treated as empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({"quality": "not_a_dict"}))

            config = load_quality_config(project_dir)
            assert config.enabled is False
            assert config.ac_gate is True
            assert config.min_coverage_pct == 80

    def test_non_dict_challenge_section(self):
        """Non-dict challenge section falls back to defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump({"quality": {"enabled": True, "challenge": "invalid"}})
            )

            config = load_quality_config(project_dir)
            assert config.enabled is True
            assert config.challenge.enabled is True
            assert config.challenge.gate == "hard"
            assert config.challenge.max_rounds == 3


# =============================================================================
# Backward compatibility (NFR-005 / AC-007)
# =============================================================================


class TestBackwardsCompatibility:
    """Test that projects without quality config see zero behavioural change."""

    def test_no_config_yaml_at_all(self):
        """A project with no config.yaml has quality disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_quality_config(Path(tmpdir))
            assert config.enabled is False
            assert config.ac_gate is True
            assert config.behavioral_test_required is True
            assert config.coverage_warnings is True
            assert config.min_coverage_pct == 80
            assert config.max_remediation_passes == 2
            assert config.challenge.enabled is True

    def test_config_yaml_without_quality_section(self):
        """A config.yaml with no quality section has quality disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(
                yaml.dump(
                    {
                        "git": {"auto_pr": True},
                        "testing": {"commands": {"unit": "pytest"}},
                    }
                )
            )

            config = load_quality_config(project_dir)
            assert config.enabled is False

    def test_preserves_other_config_sections(self):
        """Loading quality config does not interfere with other config sections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            config_data = {
                "testing": {"commands": {"unit": "pytest"}},
                "git": {"auto_pr": True},
                "quality": {"enabled": True},
            }
            (sdlc_dir / "config.yaml").write_text(yaml.dump(config_data))

            config = load_quality_config(project_dir)
            assert config.enabled is True

            # Original file should still have other sections
            raw = yaml.safe_load((sdlc_dir / "config.yaml").read_text())
            assert raw["testing"]["commands"]["unit"] == "pytest"
            assert raw["git"]["auto_pr"] is True


# =============================================================================
# Centralized config_loader (Phase 3)
# =============================================================================


class TestLoadProjectConfig:
    def test_missing_file_returns_empty(self, tmp_path):
        result = load_project_config(tmp_path)
        assert result == {}

    def test_valid_config(self, tmp_path):
        sdlc_dir = tmp_path / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text(
            yaml.dump({"quality": {"enabled": True}, "routing": {"poll_interval": 10}})
        )
        result = load_project_config(tmp_path)
        assert result["quality"]["enabled"] is True
        assert result["routing"]["poll_interval"] == 10


class TestLoadSection:
    def test_returns_dict_for_valid_section(self, tmp_path):
        sdlc_dir = tmp_path / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text(
            yaml.dump({"routing": {"component_map": {"backend": "senior"}}})
        )
        result = load_section("routing", tmp_path)
        assert isinstance(result, dict)
        assert result["component_map"]["backend"] == "senior"

    def test_missing_section_returns_empty(self, tmp_path):
        sdlc_dir = tmp_path / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text(yaml.dump({"quality": {"enabled": True}}))
        result = load_section("routing", tmp_path)
        assert result == {}

    def test_non_dict_section_returns_empty(self, tmp_path):
        sdlc_dir = tmp_path / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text(yaml.dump({"routing": "invalid"}))
        result = load_section("routing", tmp_path)
        assert result == {}

    def test_missing_file_returns_empty(self, tmp_path):
        result = load_section("governance", tmp_path)
        assert result == {}
