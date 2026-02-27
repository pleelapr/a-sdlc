"""Tests for Playwright MCP setup module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from a_sdlc.playwright_setup import (
    DEFAULT_PLAYWRIGHT_CONFIG,
    PLAYWRIGHT_CONFIGS,
    check_playwright_in_settings,
    check_tool_available,
    get_available_installer,
    get_playwright_status_message,
    install_playwright,
    setup_playwright,
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
    assert check_tool_available("ls") is True or check_tool_available("cat") is True


def test_check_tool_available_nonexistent():
    """Test checking for a non-existent tool."""
    assert check_tool_available("nonexistent_tool_xyz_123") is False


def test_get_available_installer_npx():
    """Test installer detection when npx is available."""
    with patch("a_sdlc.playwright_setup.check_tool_available") as mock_check:
        mock_check.side_effect = lambda tool: tool == "npx"
        assert get_available_installer() == "npx"


def test_get_available_installer_none():
    """Test installer detection when npx is not available."""
    with patch("a_sdlc.playwright_setup.check_tool_available") as mock_check:
        mock_check.return_value = False
        assert get_available_installer() is None


def test_install_playwright_npx():
    """Test install with npx available."""
    with (
        patch("a_sdlc.playwright_setup.check_tool_available", return_value=True),
        patch("a_sdlc.playwright_setup.get_available_installer", return_value="npx"),
    ):
        success, msg = install_playwright()
        assert success is True
        assert "npx" in msg


def test_install_playwright_no_installer():
    """Test install with no installer available."""
    with (
        patch("a_sdlc.playwright_setup.check_tool_available", return_value=False),
        patch("a_sdlc.playwright_setup.get_available_installer", return_value=None),
    ):
        success, msg = install_playwright()
        assert success is False
        assert "npx not found" in msg


def test_install_playwright_explicit_npx():
    """Test install with explicit npx method."""
    with patch("a_sdlc.playwright_setup.check_tool_available", return_value=True):
        success, msg = install_playwright(method="npx")
        assert success is True
        assert "npx" in msg


def test_install_playwright_explicit_npx_not_available():
    """Test install with explicit npx method but npx not available."""
    with patch("a_sdlc.playwright_setup.check_tool_available", return_value=False):
        success, msg = install_playwright(method="npx")
        assert success is False
        assert "npx not found" in msg


def test_install_playwright_unknown_method():
    """Test install with an unknown method."""
    success, msg = install_playwright(method="yarn")
    assert success is False
    assert "Unknown installation method" in msg


def test_load_settings_nonexistent(tmp_path: Path):
    """Test loading settings from nonexistent file."""
    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", tmp_path / "nonexistent.json"):
        from a_sdlc.mcp_setup import load_claude_settings

        settings = load_claude_settings()
        assert settings == {}


def test_check_playwright_in_settings_not_configured(tmp_path: Path):
    """Test checking for Playwright when not configured."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"mcpServers": {}}')

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        assert check_playwright_in_settings() is False


def test_check_playwright_in_settings_configured(tmp_path: Path):
    """Test checking for Playwright when configured."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"mcpServers": {"playwright": {}}}')

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        assert check_playwright_in_settings() is True


def test_update_claude_settings_new_config(tmp_path: Path):
    """Test adding Playwright to empty settings."""
    settings_file = tmp_path / ".claude" / "settings.json"

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        success, message = update_claude_settings(method="npx")

        assert success is True
        assert settings_file.exists()

        loaded = json.loads(settings_file.read_text())
        assert "playwright" in loaded["mcpServers"]
        assert loaded["mcpServers"]["playwright"] == PLAYWRIGHT_CONFIGS["npx"]


def test_update_claude_settings_existing_config(tmp_path: Path):
    """Test updating settings that already have Playwright."""
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text('{"mcpServers": {"playwright": {"old": "config"}}}')

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        # Without force, should not overwrite
        success, message = update_claude_settings(method="npx", force=False)
        assert success is True
        assert "already configured" in message

        loaded = json.loads(settings_file.read_text())
        assert loaded["mcpServers"]["playwright"] == {"old": "config"}

        # With force, should overwrite
        success, message = update_claude_settings(method="npx", force=True)
        assert success is True

        loaded = json.loads(settings_file.read_text())
        assert loaded["mcpServers"]["playwright"] == PLAYWRIGHT_CONFIGS["npx"]


def test_update_claude_settings_preserves_other_servers(tmp_path: Path):
    """Test that update preserves other MCP servers."""
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text('{"mcpServers": {"other": {"command": "other"}}}')

    with patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file):
        success, _ = update_claude_settings(method="npx")
        assert success is True

        loaded = json.loads(settings_file.read_text())
        assert "playwright" in loaded["mcpServers"]
        assert "other" in loaded["mcpServers"]
        assert loaded["mcpServers"]["other"] == {"command": "other"}


def test_verify_setup_not_configured(tmp_path: Path):
    """Test verification when nothing is set up."""
    settings_file = tmp_path / "settings.json"

    with (
        patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        patch("a_sdlc.playwright_setup.check_tool_available", return_value=False),
    ):
        result = verify_setup()

        assert result["installer_available"] is False
        assert result["configured_in_settings"] is False
        assert result["ready"] is False


def test_verify_setup_fully_configured(tmp_path: Path):
    """Test verification when fully set up."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"mcpServers": {"playwright": {}}}')

    with (
        patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        patch("a_sdlc.playwright_setup.check_tool_available", return_value=True),
        patch("a_sdlc.playwright_setup.get_available_installer", return_value="npx"),
    ):
        result = verify_setup()

        assert result["installer_available"] is True
        assert result["configured_in_settings"] is True
        assert result["ready"] is True


def test_verify_setup_npx_available_but_not_configured(tmp_path: Path):
    """Test verification when npx is available but not configured."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"mcpServers": {}}')

    with (
        patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        patch("a_sdlc.playwright_setup.check_tool_available", return_value=True),
        patch("a_sdlc.playwright_setup.get_available_installer", return_value="npx"),
    ):
        result = verify_setup()

        assert result["installer_available"] is True
        assert result["configured_in_settings"] is False
        assert result["ready"] is False


def test_get_status_message_ready(tmp_path: Path):
    """Test status message when Playwright is fully configured."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"mcpServers": {"playwright": {}}}')

    with (
        patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        patch("a_sdlc.playwright_setup.check_tool_available", return_value=True),
        patch("a_sdlc.playwright_setup.get_available_installer", return_value="npx"),
    ):
        msg = get_playwright_status_message()
        assert "Configured" in msg
        assert "npx" in msg


def test_get_status_message_not_ready(tmp_path: Path):
    """Test status message when Playwright is not set up."""
    settings_file = tmp_path / "settings.json"

    with (
        patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        patch("a_sdlc.playwright_setup.check_tool_available", return_value=False),
    ):
        msg = get_playwright_status_message()
        assert "Not ready" in msg
        assert "npx not found" in msg
        assert "Not configured" in msg


def test_playwright_config_structure():
    """Test that Playwright configs have the expected structure."""
    for _method, config in PLAYWRIGHT_CONFIGS.items():
        assert "command" in config
        assert "args" in config
        assert isinstance(config["args"], list)


def test_default_playwright_config():
    """Test the default Playwright configuration."""
    assert DEFAULT_PLAYWRIGHT_CONFIG["command"] == "npx"
    assert "@anthropic/mcp-playwright" in DEFAULT_PLAYWRIGHT_CONFIG["args"]


def test_setup_playwright_already_ready(tmp_path: Path):
    """Test setup when already configured."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"mcpServers": {"playwright": {}}}')

    with (
        patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        patch("a_sdlc.playwright_setup.check_tool_available", return_value=True),
        patch("a_sdlc.playwright_setup.get_available_installer", return_value="npx"),
    ):
        success, msg, verification = setup_playwright()
        assert success is True
        assert "already set up" in msg
        assert verification["ready"] is True


def test_setup_playwright_no_npx(tmp_path: Path):
    """Test setup when npx is not available."""
    settings_file = tmp_path / "settings.json"

    with (
        patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        patch("a_sdlc.playwright_setup.check_tool_available", return_value=False),
        patch("a_sdlc.playwright_setup.get_available_installer", return_value=None),
    ):
        success, msg, verification = setup_playwright()
        assert success is False
        assert "npx not available" in msg
        assert verification == {}


def test_setup_playwright_fresh_install(tmp_path: Path):
    """Test fresh setup with npx available."""
    settings_file = tmp_path / ".claude" / "settings.json"

    with (
        patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        patch("a_sdlc.playwright_setup.check_tool_available", return_value=True),
        patch("a_sdlc.playwright_setup.get_available_installer", return_value="npx"),
    ):
        success, msg, verification = setup_playwright(force=True)
        assert success is True
        assert "npx" in msg
        assert verification["ready"] is True


def test_setup_playwright_force_reconfigure(tmp_path: Path):
    """Test forced reconfiguration."""
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text('{"mcpServers": {"playwright": {"old": "config"}}}')

    with (
        patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        patch("a_sdlc.playwright_setup.check_tool_available", return_value=True),
        patch("a_sdlc.playwright_setup.get_available_installer", return_value="npx"),
    ):
        success, msg, verification = setup_playwright(force=True)
        assert success is True

        loaded = json.loads(settings_file.read_text())
        assert loaded["mcpServers"]["playwright"] == PLAYWRIGHT_CONFIGS["npx"]
