"""Tests for CLI target registry."""

from pathlib import Path
from unittest.mock import patch

import pytest

from a_sdlc.cli_targets import (
    ALL_TARGETS,
    CLAUDE_TARGET,
    GEMINI_TARGET,
    CLITarget,
    detect_targets,
    resolve_targets,
)


class TestCLITarget:
    """Tests for CLITarget dataclass."""

    def test_claude_target_name(self):
        assert CLAUDE_TARGET.name == "claude"

    def test_claude_target_display_name(self):
        assert CLAUDE_TARGET.display_name == "Claude Code"

    def test_claude_target_home_dir(self):
        assert CLAUDE_TARGET.home_dir == Path.home() / ".claude"

    def test_claude_target_mcp_config_path(self):
        assert CLAUDE_TARGET.mcp_config_path == Path.home() / ".claude.json"

    def test_claude_target_settings_path(self):
        assert CLAUDE_TARGET.settings_path == Path.home() / ".claude" / "settings.json"

    def test_claude_target_commands_dir(self):
        assert CLAUDE_TARGET.commands_dir == Path.home() / ".claude" / "commands" / "sdlc"

    def test_claude_target_agents_dir(self):
        assert CLAUDE_TARGET.agents_dir == Path.home() / ".claude" / "agents"

    def test_claude_target_context_file(self):
        assert CLAUDE_TARGET.context_file == "CLAUDE.md"

    def test_gemini_target_name(self):
        assert GEMINI_TARGET.name == "gemini"

    def test_gemini_target_display_name(self):
        assert GEMINI_TARGET.display_name == "Gemini CLI"

    def test_gemini_target_home_dir(self):
        assert GEMINI_TARGET.home_dir == Path.home() / ".gemini"

    def test_gemini_target_mcp_config_path(self):
        assert GEMINI_TARGET.mcp_config_path == Path.home() / ".gemini" / "settings.json"

    def test_gemini_target_settings_path(self):
        assert GEMINI_TARGET.settings_path == Path.home() / ".gemini" / "settings.json"

    def test_gemini_target_commands_dir(self):
        assert GEMINI_TARGET.commands_dir == Path.home() / ".gemini" / "commands" / "sdlc"

    def test_gemini_target_agents_dir_is_none(self):
        assert GEMINI_TARGET.agents_dir is None

    def test_gemini_target_context_file(self):
        assert GEMINI_TARGET.context_file == "GEMINI.md"

    def test_all_targets_contains_both(self):
        assert len(ALL_TARGETS) == 2
        assert CLAUDE_TARGET in ALL_TARGETS
        assert GEMINI_TARGET in ALL_TARGETS

    def test_cli_target_is_frozen(self):
        with pytest.raises(AttributeError):
            CLAUDE_TARGET.name = "modified"


class TestDetectTargets:
    """Tests for detect_targets()."""

    def test_detect_only_claude(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()

        claude = CLITarget(
            name="claude", display_name="Claude Code",
            home_dir=claude_dir,
            mcp_config_path=tmp_path / ".claude.json",
            settings_path=claude_dir / "settings.json",
            commands_dir=claude_dir / "commands" / "sdlc",
            agents_dir=claude_dir / "agents",
            context_file="CLAUDE.md",
        )
        gemini = CLITarget(
            name="gemini", display_name="Gemini CLI",
            home_dir=tmp_path / ".gemini",
            mcp_config_path=tmp_path / ".gemini" / "settings.json",
            settings_path=tmp_path / ".gemini" / "settings.json",
            commands_dir=tmp_path / ".gemini" / "commands" / "sdlc",
            agents_dir=None,
            context_file="GEMINI.md",
        )

        with patch("a_sdlc.cli_targets.ALL_TARGETS", [claude, gemini]):
            targets = detect_targets()
            assert len(targets) == 1
            assert targets[0].name == "claude"

    def test_detect_both(self, tmp_path):
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir()

        claude = CLITarget(
            name="claude", display_name="Claude Code",
            home_dir=claude_dir,
            mcp_config_path=tmp_path / ".claude.json",
            settings_path=claude_dir / "settings.json",
            commands_dir=claude_dir / "commands" / "sdlc",
            agents_dir=claude_dir / "agents",
            context_file="CLAUDE.md",
        )
        gemini = CLITarget(
            name="gemini", display_name="Gemini CLI",
            home_dir=gemini_dir,
            mcp_config_path=gemini_dir / "settings.json",
            settings_path=gemini_dir / "settings.json",
            commands_dir=gemini_dir / "commands" / "sdlc",
            agents_dir=None,
            context_file="GEMINI.md",
        )

        with patch("a_sdlc.cli_targets.ALL_TARGETS", [claude, gemini]):
            targets = detect_targets()
            assert len(targets) == 2

    def test_detect_neither(self, tmp_path):
        claude = CLITarget(
            name="claude", display_name="Claude Code",
            home_dir=tmp_path / ".claude",
            mcp_config_path=tmp_path / ".claude.json",
            settings_path=tmp_path / ".claude" / "settings.json",
            commands_dir=tmp_path / ".claude" / "commands" / "sdlc",
            agents_dir=tmp_path / ".claude" / "agents",
            context_file="CLAUDE.md",
        )
        gemini = CLITarget(
            name="gemini", display_name="Gemini CLI",
            home_dir=tmp_path / ".gemini",
            mcp_config_path=tmp_path / ".gemini" / "settings.json",
            settings_path=tmp_path / ".gemini" / "settings.json",
            commands_dir=tmp_path / ".gemini" / "commands" / "sdlc",
            agents_dir=None,
            context_file="GEMINI.md",
        )

        with patch("a_sdlc.cli_targets.ALL_TARGETS", [claude, gemini]):
            targets = detect_targets()
            assert len(targets) == 0


class TestResolveTargets:
    """Tests for resolve_targets()."""

    def test_resolve_claude(self):
        targets = resolve_targets("claude")
        assert len(targets) == 1
        assert targets[0].name == "claude"

    def test_resolve_gemini(self):
        targets = resolve_targets("gemini")
        assert len(targets) == 1
        assert targets[0].name == "gemini"

    def test_resolve_auto_delegates_to_detect(self):
        with patch("a_sdlc.cli_targets.detect_targets", return_value=[CLAUDE_TARGET]) as mock:
            targets = resolve_targets("auto")
            mock.assert_called_once()
            assert targets == [CLAUDE_TARGET]

    def test_resolve_none_delegates_to_detect(self):
        with patch("a_sdlc.cli_targets.detect_targets", return_value=[CLAUDE_TARGET]) as mock:
            targets = resolve_targets(None)
            mock.assert_called_once()
            assert targets == [CLAUDE_TARGET]

    def test_resolve_invalid_raises(self):
        with pytest.raises(ValueError, match="Unknown target"):
            resolve_targets("invalid")

    def test_resolve_invalid_shows_valid_options(self):
        with pytest.raises(ValueError, match="claude"):
            resolve_targets("invalid")
