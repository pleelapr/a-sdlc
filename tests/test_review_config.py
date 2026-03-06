"""Tests for review configuration layer."""

import tempfile
from pathlib import Path

import pytest
import yaml

from a_sdlc.core.review_config import (
    ReviewConfig,
    _normalise_bool_field,
    load_review_config,
)

# =============================================================================
# ReviewConfig dataclass
# =============================================================================


class TestReviewConfig:
    """Test ReviewConfig dataclass behavior."""

    def test_defaults(self):
        """Default config has enabled=False, all others at sensible defaults."""
        config = ReviewConfig()
        assert config.enabled is False
        assert config.self_review is True
        assert config.subagent_review is True
        assert config.max_rounds == 3
        assert config.evidence_required is True

    def test_to_dict(self):
        """Serialization produces expected keys and values."""
        config = ReviewConfig(enabled=True, max_rounds=5)
        d = config.to_dict()
        assert d == {
            "enabled": True,
            "self_review": True,
            "subagent_review": True,
            "max_rounds": 5,
            "evidence_required": True,
        }

    def test_frozen_dataclass(self):
        """Config is immutable (frozen dataclass)."""
        config = ReviewConfig()
        with pytest.raises(AttributeError):
            config.enabled = True  # type: ignore[misc]

    def test_custom_values(self):
        """All fields can be set via constructor."""
        config = ReviewConfig(
            enabled=True,
            self_review=False,
            subagent_review=False,
            max_rounds=10,
            evidence_required=False,
        )
        assert config.enabled is True
        assert config.self_review is False
        assert config.subagent_review is False
        assert config.max_rounds == 10
        assert config.evidence_required is False


# =============================================================================
# _normalise_bool_field
# =============================================================================


class TestNormaliseBoolField:
    """Test the nested/flat boolean normalisation helper."""

    def test_flat_true(self):
        assert _normalise_bool_field(True) is True

    def test_flat_false(self):
        assert _normalise_bool_field(False) is False

    def test_nested_enabled_true(self):
        assert _normalise_bool_field({"enabled": True}) is True

    def test_nested_enabled_false(self):
        assert _normalise_bool_field({"enabled": False}) is False

    def test_nested_missing_enabled(self):
        """Nested dict without 'enabled' key defaults to False."""
        assert _normalise_bool_field({"other": "value"}) is False

    def test_truthy_int(self):
        assert _normalise_bool_field(1) is True

    def test_falsy_int(self):
        assert _normalise_bool_field(0) is False

    def test_truthy_string(self):
        assert _normalise_bool_field("yes") is True

    def test_empty_string(self):
        assert _normalise_bool_field("") is False


# =============================================================================
# load_review_config — defaults / absent config
# =============================================================================


class TestLoadReviewConfigDefaults:
    """Test loading review config when review section is absent."""

    def test_defaults_when_no_config_files(self):
        """Without any config files, review is disabled with safe defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_review_config(Path(tmpdir))
            assert config.enabled is False
            assert config.self_review is True
            assert config.subagent_review is True
            assert config.max_rounds == 3
            assert config.evidence_required is True

    def test_config_yaml_without_review_section(self):
        """A config.yaml with no review section returns defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "testing": {"commands": {"unit": "pytest"}},
            }))

            config = load_review_config(project_dir)
            assert config.enabled is False
            assert config.self_review is True
            assert config.subagent_review is True
            assert config.max_rounds == 3
            assert config.evidence_required is True

    def test_explicit_enabled_false(self):
        """Explicit enabled: false returns disabled config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "review": {"enabled": False}
            }))

            config = load_review_config(project_dir)
            assert config.enabled is False


# =============================================================================
# load_review_config — enabled with overrides
# =============================================================================


class TestLoadReviewConfigEnabled:
    """Test loading review config when review is enabled."""

    def test_enabled_with_all_overrides(self):
        """Full flat config overrides all defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "review": {
                    "enabled": True,
                    "self_review": False,
                    "subagent_review": False,
                    "max_rounds": 5,
                    "evidence_required": False,
                }
            }))

            config = load_review_config(project_dir)
            assert config.enabled is True
            assert config.self_review is False
            assert config.subagent_review is False
            assert config.max_rounds == 5
            assert config.evidence_required is False

    def test_partial_config_uses_defaults_for_rest(self):
        """Only provided fields override, others stay at defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "review": {
                    "enabled": True,
                    "max_rounds": 7,
                }
            }))

            config = load_review_config(project_dir)
            assert config.enabled is True
            assert config.self_review is True  # default
            assert config.subagent_review is True  # default
            assert config.max_rounds == 7
            assert config.evidence_required is True  # default


# =============================================================================
# load_review_config — nested format support
# =============================================================================


class TestLoadReviewConfigNestedFormat:
    """Test loading review config with nested {enabled: bool} sub-sections."""

    def test_nested_self_review_enabled(self):
        """Nested self_review: {enabled: true} is correctly parsed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "review": {
                    "enabled": True,
                    "self_review": {"enabled": True},
                    "subagent_review": {"enabled": False},
                }
            }))

            config = load_review_config(project_dir)
            assert config.enabled is True
            assert config.self_review is True
            assert config.subagent_review is False

    def test_nested_evidence_required(self):
        """Nested evidence_required: {enabled: false} is correctly parsed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "review": {
                    "enabled": True,
                    "evidence_required": {"enabled": False},
                }
            }))

            config = load_review_config(project_dir)
            assert config.evidence_required is False

    def test_full_nested_template_format(self):
        """Config matching the init.md template format works correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "review": {
                    "self_review": {"enabled": True},
                    "subagent_review": {"enabled": True},
                    "max_rounds": 3,
                    "evidence_required": True,
                }
            }))

            config = load_review_config(project_dir)
            # enabled not set, defaults to False
            assert config.enabled is False
            assert config.self_review is True
            assert config.subagent_review is True
            assert config.max_rounds == 3
            assert config.evidence_required is True


# =============================================================================
# load_review_config — flat format support
# =============================================================================


class TestLoadReviewConfigFlatFormat:
    """Test loading review config with flat boolean values."""

    def test_flat_self_review_true(self):
        """Flat self_review: true is correctly parsed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "review": {
                    "enabled": True,
                    "self_review": True,
                }
            }))

            config = load_review_config(project_dir)
            assert config.self_review is True

    def test_flat_self_review_false(self):
        """Flat self_review: false is correctly parsed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "review": {
                    "enabled": True,
                    "self_review": False,
                }
            }))

            config = load_review_config(project_dir)
            assert config.self_review is False


# =============================================================================
# load_review_config — layered merge
# =============================================================================


class TestLoadReviewConfigLayeredMerge:
    """Test layered merging: defaults < global < project."""

    def test_global_config_overrides_defaults(self, tmp_path, monkeypatch):
        """Global config overrides built-in defaults."""
        global_config_dir = tmp_path / "global_config"
        global_config_dir.mkdir()
        global_config_file = global_config_dir / "config.yaml"
        global_config_file.write_text(yaml.dump({
            "review": {"enabled": True, "max_rounds": 5}
        }))

        monkeypatch.setattr(
            "a_sdlc.core.review_config.GLOBAL_CONFIG_FILE",
            global_config_file,
        )

        with tempfile.TemporaryDirectory() as project_dir:
            config = load_review_config(Path(project_dir))
            assert config.enabled is True
            assert config.max_rounds == 5
            assert config.self_review is True  # still default

    def test_project_overrides_global(self, tmp_path, monkeypatch):
        """Project config takes precedence over global config."""
        # Global: max_rounds=5, self_review=False
        global_config_dir = tmp_path / "global_config"
        global_config_dir.mkdir()
        global_config_file = global_config_dir / "config.yaml"
        global_config_file.write_text(yaml.dump({
            "review": {"enabled": True, "max_rounds": 5, "self_review": False}
        }))
        monkeypatch.setattr(
            "a_sdlc.core.review_config.GLOBAL_CONFIG_FILE",
            global_config_file,
        )

        # Project: max_rounds=2 (override global)
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        sdlc_dir = project_dir / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text(yaml.dump({
            "review": {"max_rounds": 2}
        }))

        config = load_review_config(project_dir)
        assert config.max_rounds == 2  # project override wins
        assert config.self_review is False  # global value kept
        assert config.enabled is True  # global value kept


# =============================================================================
# load_review_config — error handling
# =============================================================================


class TestLoadReviewConfigErrorHandling:
    """Test robustness with missing or malformed config files."""

    def test_missing_config_file(self):
        """Missing config file returns safe defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_review_config(Path(tmpdir))
            assert config.enabled is False
            assert config.self_review is True
            assert config.max_rounds == 3

    def test_malformed_yaml(self):
        """Malformed YAML files are treated as empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text("{{invalid yaml")

            config = load_review_config(project_dir)
            assert config.enabled is False
            assert config.self_review is True

    def test_non_dict_review_section(self):
        """Non-dict review section is treated as empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "review": "not_a_dict"
            }))

            config = load_review_config(project_dir)
            assert config.enabled is False
            assert config.self_review is True
            assert config.max_rounds == 3

    def test_review_section_is_list(self):
        """List review section is treated as empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "review": ["item1", "item2"]
            }))

            config = load_review_config(project_dir)
            assert config.enabled is False


# =============================================================================
# Backward compatibility / NFR-003
# =============================================================================


class TestBackwardsCompatibility:
    """Test that projects without review config see zero behavioural change."""

    def test_no_config_yaml_at_all(self):
        """A project with no config.yaml has review disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_review_config(Path(tmpdir))
            assert config.enabled is False
            assert config.self_review is True
            assert config.subagent_review is True
            assert config.max_rounds == 3
            assert config.evidence_required is True

    def test_config_yaml_without_review_section(self):
        """A config.yaml with no review section has review disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "git": {"auto_pr": True},
                "testing": {"commands": {"unit": "pytest"}},
            }))

            config = load_review_config(project_dir)
            assert config.enabled is False
            assert config.self_review is True
            assert config.subagent_review is True
            assert config.max_rounds == 3
            assert config.evidence_required is True

    def test_preserves_other_config_sections(self):
        """Loading review config does not interfere with other config sections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            config_data = {
                "testing": {"commands": {"unit": "pytest"}},
                "git": {"auto_pr": True},
                "review": {"enabled": True},
            }
            (sdlc_dir / "config.yaml").write_text(yaml.dump(config_data))

            config = load_review_config(project_dir)
            assert config.enabled is True

            # Original file should still have other sections
            raw = yaml.safe_load((sdlc_dir / "config.yaml").read_text())
            assert raw["testing"]["commands"]["unit"] == "pytest"
            assert raw["git"]["auto_pr"] is True
