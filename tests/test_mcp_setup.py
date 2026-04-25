"""Tests for MCP setup module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from a_sdlc.mcp_setup import (
    DEFAULT_SERENA_CONFIG,
    SERENA_CONFIGS,
    check_serena_in_settings,
    check_tool_available,
    get_available_installer,
    load_claude_settings,
    load_settings,
    save_claude_settings,
    save_settings,
    update_claude_settings,
    verify_setup,
)


@pytest.fixture
def temp_settings_file(tmp_path: Path):
    """Create a temporary settings file path."""
    settings_file = tmp_path / ".claude" / "settings.json"
    return settings_file


def test_check_tool_available_existing():
    """Test checking for an existing tool."""
    # 'ls' or 'cat' should exist on any Unix-like system running these tests
    assert check_tool_available("ls") is True or check_tool_available("cat") is True


def test_check_tool_available_nonexistent():
    """Test checking for a non-existent tool."""
    assert check_tool_available("nonexistent_tool_xyz_123") is False


def test_get_available_installer_uvx():
    """Test installer detection when uvx is available."""
    with patch("a_sdlc.mcp_setup.check_tool_available") as mock_check:
        mock_check.side_effect = lambda tool: tool == "uvx"
        assert get_available_installer() == "uvx"


def test_get_available_installer_pipx():
    """Test installer detection when only pipx is available."""
    with patch("a_sdlc.mcp_setup.check_tool_available") as mock_check:
        mock_check.side_effect = lambda tool: tool == "pipx"
        assert get_available_installer() == "pipx"


def test_get_available_installer_none():
    """Test installer detection when neither is available."""
    with patch("a_sdlc.mcp_setup.check_tool_available") as mock_check:
        mock_check.return_value = False
        assert get_available_installer() is None


def test_load_claude_settings_nonexistent(tmp_path: Path):
    """Test loading settings from nonexistent file."""
    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", tmp_path / "nonexistent.json"):
        settings = load_claude_settings()
        assert settings == {}


def test_load_claude_settings_existing(tmp_path: Path):
    """Test loading existing settings."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"mcpServers": {"test": {}}}')

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        settings = load_claude_settings()
        assert "mcpServers" in settings
        assert "test" in settings["mcpServers"]


def test_load_claude_settings_invalid_json(tmp_path: Path):
    """Test loading invalid JSON settings file."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("not valid json")

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        settings = load_claude_settings()
        assert settings == {}


def test_save_claude_settings(tmp_path: Path):
    """Test saving settings to file."""
    settings_file = tmp_path / ".claude" / "settings.json"

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        test_settings = {"mcpServers": {"test": {"command": "test"}}}
        save_claude_settings(test_settings)

        assert settings_file.exists()
        loaded = json.loads(settings_file.read_text())
        assert loaded == test_settings


def test_check_serena_in_settings_not_configured(tmp_path: Path):
    """Test checking for Serena when not configured."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"mcpServers": {}}')

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        assert check_serena_in_settings() is False


def test_check_serena_in_settings_configured(tmp_path: Path):
    """Test checking for Serena when configured."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"mcpServers": {"serena": {}}}')

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        assert check_serena_in_settings() is True


def test_update_claude_settings_new_config(tmp_path: Path):
    """Test adding Serena to empty settings."""
    settings_file = tmp_path / ".claude" / "settings.json"

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        success, message = update_claude_settings(method="uvx")

        assert success is True
        assert settings_file.exists()

        loaded = json.loads(settings_file.read_text())
        assert "serena" in loaded["mcpServers"]
        assert loaded["mcpServers"]["serena"] == SERENA_CONFIGS["uvx"]


def test_update_claude_settings_existing_config(tmp_path: Path):
    """Test updating settings that already have Serena."""
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text('{"mcpServers": {"serena": {"old": "config"}}}')

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        # Without force, should not overwrite
        success, message = update_claude_settings(method="uvx", force=False)
        assert success is True
        assert "already configured" in message

        loaded = json.loads(settings_file.read_text())
        assert loaded["mcpServers"]["serena"] == {"old": "config"}

        # With force, should overwrite
        success, message = update_claude_settings(method="uvx", force=True)
        assert success is True

        loaded = json.loads(settings_file.read_text())
        assert loaded["mcpServers"]["serena"] == SERENA_CONFIGS["uvx"]


def test_update_claude_settings_preserves_other_servers(tmp_path: Path):
    """Test that update preserves other MCP servers."""
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text('{"mcpServers": {"other": {"command": "other"}}}')

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        success, _ = update_claude_settings(method="uvx")
        assert success is True

        loaded = json.loads(settings_file.read_text())
        assert "serena" in loaded["mcpServers"]
        assert "other" in loaded["mcpServers"]
        assert loaded["mcpServers"]["other"] == {"command": "other"}


def test_verify_setup_not_configured(tmp_path: Path):
    """Test verification when nothing is set up."""
    settings_file = tmp_path / "settings.json"

    with (
        patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        patch("a_sdlc.mcp_setup.check_tool_available", return_value=False),
    ):
        result = verify_setup()

        assert result["installer_available"] is False
        assert result["configured_in_settings"] is False
        assert result["ready"] is False


def test_verify_setup_fully_configured(tmp_path: Path):
    """Test verification when fully set up."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"mcpServers": {"serena": {}}}')

    with (
        patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        patch("a_sdlc.mcp_setup.check_tool_available", return_value=True),
        patch("a_sdlc.mcp_setup.get_available_installer", return_value="uvx"),
    ):
        result = verify_setup()

        assert result["installer_available"] is True
        assert result["configured_in_settings"] is True
        assert result["ready"] is True


def test_serena_config_structure():
    """Test that Serena configs have the expected structure."""
    for _method, config in SERENA_CONFIGS.items():
        assert "command" in config
        assert "args" in config
        assert "env" in config
        assert isinstance(config["args"], list)
        assert isinstance(config["env"], dict)


def test_default_serena_config():
    """Test the default Serena configuration."""
    assert DEFAULT_SERENA_CONFIG["command"] == "uvx"
    assert "serena-agent" in DEFAULT_SERENA_CONFIG["args"]
    assert "SERENA_LOG_LEVEL" in DEFAULT_SERENA_CONFIG["env"]


class TestGenericSettings:
    """Tests for generic load_settings/save_settings functions."""

    def test_load_settings_nonexistent(self, tmp_path):
        """Test loading from non-existent path returns empty dict."""
        result = load_settings(tmp_path / "nonexistent.json")
        assert result == {}

    def test_load_settings_valid_json(self, tmp_path):
        """Test loading valid JSON file."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text('{"key": "value"}')
        result = load_settings(settings_file)
        assert result == {"key": "value"}

    def test_load_settings_invalid_json(self, tmp_path):
        """Test loading invalid JSON returns empty dict."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("not json")
        result = load_settings(settings_file)
        assert result == {}

    def test_save_settings_creates_parents(self, tmp_path):
        """Test save creates parent directories."""
        settings_file = tmp_path / "deep" / "nested" / "settings.json"
        save_settings({"test": True}, settings_file)
        assert settings_file.exists()
        loaded = json.loads(settings_file.read_text())
        assert loaded == {"test": True}

    def test_save_settings_indent(self, tmp_path):
        """Test save uses 2-space indent."""
        settings_file = tmp_path / "settings.json"
        save_settings({"a": 1}, settings_file)
        content = settings_file.read_text()
        assert "  " in content  # 2-space indent

    def test_save_then_load_roundtrip(self, tmp_path):
        """Test save/load roundtrip preserves data."""
        settings_file = tmp_path / "settings.json"
        original = {"mcpServers": {"asdlc": {"command": "uvx"}}}
        save_settings(original, settings_file)
        loaded = load_settings(settings_file)
        assert loaded == original

    def test_claude_wrappers_still_work(self, tmp_path):
        """Test that load/save_claude_settings still work as wrappers."""
        settings_file = tmp_path / "settings.json"
        with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
            save_claude_settings({"test": "data"})
            result = load_claude_settings()
            assert result == {"test": "data"}
