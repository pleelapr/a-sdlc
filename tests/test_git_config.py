"""Tests for git safety configuration layer."""

import tempfile
from pathlib import Path

import pytest
import yaml

from a_sdlc.core.git_config import (
    ALWAYS_CONFIRM_OPERATIONS,
    GitSafetyConfig,
    _deep_merge,
    get_effective_config_summary,
    load_git_safety_config,
    save_git_safety_config,
)

# =============================================================================
# GitSafetyConfig dataclass
# =============================================================================


class TestGitSafetyConfig:
    """Test GitSafetyConfig dataclass behavior."""

    def test_defaults_all_false(self):
        """Default config has all operations disabled."""
        config = GitSafetyConfig()
        assert config.auto_commit is False
        assert config.auto_pr is False
        assert config.auto_merge is False
        assert config.worktree_enabled is False

    def test_to_dict(self):
        """Serialization produces expected keys and values."""
        config = GitSafetyConfig(auto_pr=True, worktree_enabled=True)
        d = config.to_dict()
        assert d == {
            "auto_commit": False,
            "auto_pr": True,
            "auto_merge": False,
            "worktree_enabled": True,
        }

    def test_is_operation_allowed_enabled(self):
        """Allowed operations return True when enabled."""
        config = GitSafetyConfig(auto_commit=True, auto_pr=True, auto_merge=True, worktree_enabled=True)
        assert config.is_operation_allowed("auto_commit") is True
        assert config.is_operation_allowed("auto_pr") is True
        assert config.is_operation_allowed("auto_merge") is True
        assert config.is_operation_allowed("worktree_enabled") is True

    def test_is_operation_allowed_disabled(self):
        """Disabled operations return False."""
        config = GitSafetyConfig()
        assert config.is_operation_allowed("auto_commit") is False
        assert config.is_operation_allowed("auto_pr") is False
        assert config.is_operation_allowed("auto_merge") is False
        assert config.is_operation_allowed("worktree_enabled") is False

    def test_destructive_operations_always_blocked(self):
        """Force push and branch delete always return False even with all enabled."""
        config = GitSafetyConfig(auto_pr=True, auto_merge=True, worktree_enabled=True)
        assert config.is_operation_allowed("force_push") is False
        assert config.is_operation_allowed("branch_delete") is False

    def test_unknown_operation_returns_false(self):
        """Unknown operation names return False."""
        config = GitSafetyConfig(auto_pr=True)
        assert config.is_operation_allowed("unknown_op") is False

    def test_requires_confirmation_destructive(self):
        """Destructive operations always require confirmation."""
        config = GitSafetyConfig()
        assert config.requires_confirmation("force_push") is True
        assert config.requires_confirmation("branch_delete") is True

    def test_requires_confirmation_normal_ops(self):
        """Normal operations do not require confirmation."""
        config = GitSafetyConfig()
        assert config.requires_confirmation("auto_commit") is False
        assert config.requires_confirmation("auto_pr") is False
        assert config.requires_confirmation("auto_merge") is False
        assert config.requires_confirmation("worktree_enabled") is False

    def test_frozen_dataclass(self):
        """Config is immutable (frozen dataclass)."""
        config = GitSafetyConfig()
        with pytest.raises(AttributeError):
            config.auto_pr = True  # type: ignore[misc]


# =============================================================================
# ALWAYS_CONFIRM_OPERATIONS constant
# =============================================================================


class TestAlwaysConfirmOperations:
    """Test the ALWAYS_CONFIRM_OPERATIONS constant."""

    def test_contains_expected_operations(self):
        assert "force_push" in ALWAYS_CONFIRM_OPERATIONS
        assert "branch_delete" in ALWAYS_CONFIRM_OPERATIONS

    def test_is_frozenset(self):
        assert isinstance(ALWAYS_CONFIRM_OPERATIONS, frozenset)


# =============================================================================
# _deep_merge
# =============================================================================


class TestDeepMerge:
    """Test the _deep_merge helper function."""

    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        assert _deep_merge(base, override) == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"git": {"auto_pr": False, "auto_merge": False}}
        override = {"git": {"auto_pr": True}}
        result = _deep_merge(base, override)
        assert result == {"git": {"auto_pr": True, "auto_merge": False}}

    def test_does_not_mutate_inputs(self):
        base = {"a": {"b": 1}}
        override = {"a": {"c": 2}}
        _deep_merge(base, override)
        assert base == {"a": {"b": 1}}
        assert override == {"a": {"c": 2}}

    def test_override_replaces_non_dict(self):
        base = {"a": "string"}
        override = {"a": {"nested": True}}
        assert _deep_merge(base, override) == {"a": {"nested": True}}

    def test_empty_base(self):
        assert _deep_merge({}, {"a": 1}) == {"a": 1}

    def test_empty_override(self):
        assert _deep_merge({"a": 1}, {}) == {"a": 1}


# =============================================================================
# load_git_safety_config
# =============================================================================


class TestLoadGitSafetyConfig:
    """Test loading layered git safety configuration."""

    def test_defaults_when_no_config_files(self):
        """Without any config files, all operations are disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_git_safety_config(Path(tmpdir))
            assert config.auto_commit is False
            assert config.auto_pr is False
            assert config.auto_merge is False
            assert config.worktree_enabled is False

    def test_project_config_overrides_defaults(self):
        """Project config can enable specific operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            config_path = sdlc_dir / "config.yaml"
            config_path.write_text(yaml.dump({
                "git": {
                    "auto_pr": True,
                    "worktree_enabled": True,
                }
            }))

            config = load_git_safety_config(project_dir)
            assert config.auto_pr is True
            assert config.auto_merge is False  # not overridden
            assert config.worktree_enabled is True

    def test_global_config_overrides_defaults(self, tmp_path, monkeypatch):
        """Global config overrides built-in defaults."""
        global_config_dir = tmp_path / "global_config"
        global_config_dir.mkdir()
        global_config_file = global_config_dir / "config.yaml"
        global_config_file.write_text(yaml.dump({
            "git": {"auto_merge": True}
        }))

        monkeypatch.setattr(
            "a_sdlc.core.git_config.GLOBAL_CONFIG_FILE",
            global_config_file,
        )

        with tempfile.TemporaryDirectory() as project_dir:
            config = load_git_safety_config(Path(project_dir))
            assert config.auto_merge is True
            assert config.auto_pr is False  # still default

    def test_project_overrides_global(self, tmp_path, monkeypatch):
        """Project config takes precedence over global config."""
        # Global: auto_pr=True, auto_merge=True
        global_config_dir = tmp_path / "global_config"
        global_config_dir.mkdir()
        global_config_file = global_config_dir / "config.yaml"
        global_config_file.write_text(yaml.dump({
            "git": {"auto_pr": True, "auto_merge": True}
        }))
        monkeypatch.setattr(
            "a_sdlc.core.git_config.GLOBAL_CONFIG_FILE",
            global_config_file,
        )

        # Project: auto_pr=False (override global)
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        sdlc_dir = project_dir / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text(yaml.dump({
            "git": {"auto_pr": False}
        }))

        config = load_git_safety_config(project_dir)
        assert config.auto_pr is False  # project override wins
        assert config.auto_merge is True  # global value kept

    def test_handles_malformed_yaml(self):
        """Malformed YAML files are treated as empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text("{{invalid yaml")

            config = load_git_safety_config(project_dir)
            assert config.auto_pr is False

    def test_handles_non_dict_git_section(self):
        """Non-dict git section is treated as empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "git": "not_a_dict"
            }))

            config = load_git_safety_config(project_dir)
            assert config.auto_pr is False

    def test_preserves_other_config_sections(self):
        """Loading git config does not interfere with other config sections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            config_data = {
                "testing": {"commands": {"unit": "pytest"}},
                "git": {"auto_pr": True},
            }
            (sdlc_dir / "config.yaml").write_text(yaml.dump(config_data))

            config = load_git_safety_config(project_dir)
            assert config.auto_pr is True

            # Original file should still have testing section
            raw = yaml.safe_load((sdlc_dir / "config.yaml").read_text())
            assert raw["testing"]["commands"]["unit"] == "pytest"

    def test_boolean_coercion(self):
        """Non-boolean values are coerced to bool."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "git": {
                    "auto_pr": 1,
                    "auto_merge": 0,
                    "worktree_enabled": "yes",
                }
            }))

            config = load_git_safety_config(project_dir)
            assert config.auto_pr is True
            assert config.auto_merge is False
            assert config.worktree_enabled is True


# =============================================================================
# save_git_safety_config
# =============================================================================


class TestSaveGitSafetyConfig:
    """Test saving git safety configuration."""

    def test_save_to_project(self):
        """Saves git section to project config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / ".sdlc").mkdir()

            config_path = save_git_safety_config(
                {"auto_pr": True},
                target="project",
                project_dir=project_dir,
            )

            assert config_path.exists()
            raw = yaml.safe_load(config_path.read_text())
            assert raw["git"]["auto_pr"] is True

    def test_save_to_global(self, tmp_path, monkeypatch):
        """Saves git section to global config."""
        global_config_file = tmp_path / "config.yaml"
        monkeypatch.setattr(
            "a_sdlc.core.git_config.GLOBAL_CONFIG_FILE",
            global_config_file,
        )

        config_path = save_git_safety_config(
            {"auto_merge": True},
            target="global",
        )

        assert config_path == global_config_file
        raw = yaml.safe_load(config_path.read_text())
        assert raw["git"]["auto_merge"] is True

    def test_preserves_existing_config(self):
        """Saving git config preserves other sections."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "testing": {"commands": {"unit": "pytest"}},
                "review": {"max_rounds": 3},
            }))

            save_git_safety_config(
                {"auto_pr": True},
                target="project",
                project_dir=project_dir,
            )

            raw = yaml.safe_load((sdlc_dir / "config.yaml").read_text())
            assert raw["testing"]["commands"]["unit"] == "pytest"
            assert raw["review"]["max_rounds"] == 3
            assert raw["git"]["auto_pr"] is True

    def test_partial_update(self):
        """Only provided keys are updated, existing git values preserved."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "git": {"auto_pr": True, "auto_merge": False},
            }))

            save_git_safety_config(
                {"worktree_enabled": True},
                target="project",
                project_dir=project_dir,
            )

            raw = yaml.safe_load((sdlc_dir / "config.yaml").read_text())
            assert raw["git"]["auto_pr"] is True  # preserved
            assert raw["git"]["auto_merge"] is False  # preserved
            assert raw["git"]["worktree_enabled"] is True  # added

    def test_rejects_unknown_keys(self):
        """Raises ValueError for unrecognized keys."""
        with tempfile.TemporaryDirectory() as tmpdir, pytest.raises(
            ValueError, match="Unrecognized git safety keys"
        ):
            save_git_safety_config(
                {"auto_pr": True, "unknown_key": True},
                target="project",
                project_dir=Path(tmpdir),
            )

    def test_creates_directories(self):
        """Creates parent directories if they don't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "deep" / "nested"
            # .sdlc dir does not exist yet
            config_path = save_git_safety_config(
                {"auto_pr": True},
                target="project",
                project_dir=project_dir,
            )
            assert config_path.exists()


# =============================================================================
# get_effective_config_summary
# =============================================================================


class TestGetEffectiveConfigSummary:
    """Test the config summary with source tracking."""

    def test_all_defaults(self):
        """All values show 'default' source when no config files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = get_effective_config_summary(Path(tmpdir))

            assert summary["effective"]["auto_commit"] is False
            assert summary["effective"]["auto_pr"] is False
            assert summary["effective"]["auto_merge"] is False
            assert summary["effective"]["worktree_enabled"] is False

            assert summary["sources"]["auto_commit"] == "default"
            assert summary["sources"]["auto_pr"] == "default"
            assert summary["sources"]["auto_merge"] == "default"
            assert summary["sources"]["worktree_enabled"] == "default"

    def test_project_source_tracking(self):
        """Values from project config show 'project' source."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "git": {"auto_pr": True}
            }))

            summary = get_effective_config_summary(project_dir)
            assert summary["sources"]["auto_pr"] == "project"
            assert summary["sources"]["auto_merge"] == "default"

    def test_global_source_tracking(self, tmp_path, monkeypatch):
        """Values from global config show 'global' source."""
        global_config_file = tmp_path / "config.yaml"
        global_config_file.write_text(yaml.dump({
            "git": {"auto_merge": True}
        }))
        monkeypatch.setattr(
            "a_sdlc.core.git_config.GLOBAL_CONFIG_FILE",
            global_config_file,
        )

        with tempfile.TemporaryDirectory() as project_dir:
            summary = get_effective_config_summary(Path(project_dir))
            assert summary["sources"]["auto_merge"] == "global"
            assert summary["sources"]["auto_pr"] == "default"

    def test_always_confirm_operations_listed(self):
        """Summary includes the list of always-confirm operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            summary = get_effective_config_summary(Path(tmpdir))
            assert "force_push" in summary["always_require_confirmation"]
            assert "branch_delete" in summary["always_require_confirmation"]


# =============================================================================
# Backwards compatibility / NFR-003
# =============================================================================


class TestBackwardsCompatibility:
    """Test that projects without git config continue to work (all ops default off)."""

    def test_no_config_yaml_at_all(self):
        """A project with no config.yaml has all git operations disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_git_safety_config(Path(tmpdir))
            assert config.auto_commit is False
            assert config.auto_pr is False
            assert config.auto_merge is False
            assert config.worktree_enabled is False

    def test_config_yaml_without_git_section(self):
        """A config.yaml with no git section has all git operations disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "testing": {"commands": {"unit": "pytest"}},
            }))

            config = load_git_safety_config(project_dir)
            assert config.auto_commit is False
            assert config.auto_pr is False
            assert config.auto_merge is False
            assert config.worktree_enabled is False

    def test_existing_config_without_auto_commit(self):
        """Config files from before auto_commit was added still work (defaults to False)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            # Old config without auto_commit key
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "git": {
                    "auto_pr": True,
                    "auto_merge": False,
                    "worktree_enabled": True,
                }
            }))

            config = load_git_safety_config(project_dir)
            assert config.auto_commit is False  # defaults to False
            assert config.auto_pr is True
            assert config.worktree_enabled is True


# =============================================================================
# auto_commit specific tests
# =============================================================================


class TestAutoCommit:
    """Test auto_commit field behavior across the configuration system."""

    def test_auto_commit_enabled(self):
        """auto_commit=True allows the operation."""
        config = GitSafetyConfig(auto_commit=True)
        assert config.auto_commit is True
        assert config.is_operation_allowed("auto_commit") is True
        assert config.to_dict()["auto_commit"] is True

    def test_auto_commit_project_override(self):
        """Project config can enable auto_commit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "git": {"auto_commit": True}
            }))

            config = load_git_safety_config(project_dir)
            assert config.auto_commit is True
            assert config.auto_pr is False  # other defaults unchanged

    def test_save_auto_commit(self):
        """auto_commit can be saved and loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / ".sdlc").mkdir()

            save_git_safety_config(
                {"auto_commit": True},
                target="project",
                project_dir=project_dir,
            )

            config = load_git_safety_config(project_dir)
            assert config.auto_commit is True

    def test_auto_commit_in_summary(self):
        """auto_commit appears in effective config summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            sdlc_dir = project_dir / ".sdlc"
            sdlc_dir.mkdir()
            (sdlc_dir / "config.yaml").write_text(yaml.dump({
                "git": {"auto_commit": True}
            }))

            summary = get_effective_config_summary(project_dir)
            assert summary["effective"]["auto_commit"] is True
            assert summary["sources"]["auto_commit"] == "project"
