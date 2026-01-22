"""Tests for CLI commands."""

import pytest
from click.testing import CliRunner

from a_sdlc.cli import main


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI test runner."""
    return CliRunner()


def test_version(runner: CliRunner) -> None:
    """Test version command."""
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_doctor(runner: CliRunner) -> None:
    """Test doctor command runs without error."""
    result = runner.invoke(main, ["doctor"])
    # May warn about missing config, but shouldn't fail
    assert result.exit_code in (0, 1)
    assert "Python Version" in result.output


def test_plugins_list(runner: CliRunner) -> None:
    """Test plugins list command."""
    result = runner.invoke(main, ["plugins", "list"])
    assert result.exit_code == 0
    assert "local" in result.output
    assert "linear" in result.output


def test_install_list_empty(runner: CliRunner) -> None:
    """Test install --list with no skills installed."""
    result = runner.invoke(main, ["install", "--list"])
    # Should succeed even if nothing installed
    assert result.exit_code == 0
