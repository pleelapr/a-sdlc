"""Tests for CLI commands."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from a_sdlc import __version__
from a_sdlc.cli import main
from a_sdlc.installer import Installer


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI test runner."""
    return CliRunner()


def test_version(runner: CliRunner) -> None:
    """Test version command."""
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.4.0" in result.output


def test_doctor(runner: CliRunner) -> None:
    """Test doctor command runs without error."""
    result = runner.invoke(main, ["doctor"])
    # May warn about missing config, but shouldn't fail
    assert result.exit_code in (0, 1)
    assert "Python Version" in result.output


class TestDoctorSchemaVersion:
    """Tests for database schema version check in doctor command."""

    def test_doctor_schema_version_pass(self, runner: CliRunner) -> None:
        """Test doctor reports PASS when schema version matches."""
        from unittest.mock import MagicMock

        from a_sdlc.core.database import SCHEMA_VERSION

        mock_db = MagicMock()
        mock_db.db_path = ":memory:"

        with patch("a_sdlc.core.database.Database", return_value=mock_db), \
             patch("sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchone.return_value = (SCHEMA_VERSION,)

            result = runner.invoke(main, ["doctor"])

        assert "Database schema version" in result.output
        assert f"v{SCHEMA_VERSION} (current)" in result.output

    def test_doctor_schema_version_warn(self, runner: CliRunner) -> None:
        """Test doctor reports WARN when schema version is outdated."""
        from unittest.mock import MagicMock

        from a_sdlc.core.database import SCHEMA_VERSION

        mock_db = MagicMock()
        mock_db.db_path = ":memory:"
        old_version = SCHEMA_VERSION - 1

        with patch("a_sdlc.core.database.Database", return_value=mock_db), \
             patch("sqlite3.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_connect.return_value.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchone.return_value = (old_version,)

            result = runner.invoke(main, ["doctor"])

        assert "Database schema version" in result.output
        assert f"v{old_version}" in result.output
        assert f"expected v{SCHEMA_VERSION}" in result.output
        # Rich table may wrap the text across lines, so check parts separately
        assert "a-sdlc install" in result.output
        assert "--upgrade" in result.output

    def test_doctor_schema_version_fail_on_error(self, runner: CliRunner) -> None:
        """Test doctor reports FAIL when database cannot be checked."""
        with patch("a_sdlc.core.database.Database", side_effect=Exception("DB not found")):
            result = runner.invoke(main, ["doctor"])

        assert "Database Accessible" in result.output
        assert "Cannot open database" in result.output
        assert "Database schema version" in result.output
        assert "Skipped" in result.output


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


class TestTemplateVersionMarker:
    """Tests for .version marker file written during install."""

    def test_version_file_created_after_install(self, tmp_path: Path) -> None:
        """Test .version file is created in target_dir after install."""
        installer = Installer(target_dir=tmp_path / "sdlc")
        installer.install(configure_mcp=False)
        version_file = tmp_path / "sdlc" / ".version"
        assert version_file.exists()

    def test_version_file_contains_correct_version(self, tmp_path: Path) -> None:
        """Test .version file contains the current __version__ string."""
        installer = Installer(target_dir=tmp_path / "sdlc")
        installer.install(configure_mcp=False)
        version_file = tmp_path / "sdlc" / ".version"
        assert version_file.read_text() == __version__

    def test_check_template_version_returns_true_when_matching(self, tmp_path: Path) -> None:
        """Test check_template_version() returns True when versions match."""
        installer = Installer(target_dir=tmp_path / "sdlc")
        installer.install(configure_mcp=False)
        up_to_date, installed, current = installer.check_template_version()
        assert up_to_date is True
        assert installed == __version__
        assert current == __version__

    def test_check_template_version_returns_false_when_outdated(self, tmp_path: Path) -> None:
        """Test check_template_version() returns False when versions differ."""
        installer = Installer(target_dir=tmp_path / "sdlc")
        installer.install(configure_mcp=False)
        # Simulate an older version
        version_file = tmp_path / "sdlc" / ".version"
        version_file.write_text("0.0.1")
        up_to_date, installed, current = installer.check_template_version()
        assert up_to_date is False
        assert installed == "0.0.1"
        assert current == __version__

    def test_check_template_version_handles_missing_version_file(self, tmp_path: Path) -> None:
        """Test check_template_version() handles missing .version file gracefully."""
        installer = Installer(target_dir=tmp_path / "sdlc")
        # Don't install — no .version file exists
        (tmp_path / "sdlc").mkdir(parents=True, exist_ok=True)
        up_to_date, installed, current = installer.check_template_version()
        assert up_to_date is False
        assert installed == "unknown"
        assert current == __version__


class TestSetupCommand:
    """Tests for the setup wizard command."""

    # Input to decline all 4 optional components (Serena, monitoring, SonarQube, Playwright)
    DECLINE_ALL_OPTIONAL = "n\nn\nn\nn\n"

    def test_setup_all_prerequisites_met(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test setup succeeds when all prerequisites are met."""
        # Create fake claude.json with asdlc configured
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"mcpServers": {"asdlc": {}}}')

        # Create fake .claude dir and templates dir
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        templates_dir = claude_dir / "commands" / "sdlc"
        templates_dir.mkdir(parents=True)

        with patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")), \
             patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")), \
             patch("a_sdlc.cli.check_claude_code_installed", return_value=(True, str(claude_dir))), \
             patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json):
            mock_installer = mock_installer_cls.return_value
            mock_installer.list_installed.return_value = []
            mock_installer.install.return_value = ["init", "scan", "help"]
            mock_installer.target_dir = templates_dir

            result = runner.invoke(main, ["setup"], input=self.DECLINE_ALL_OPTIONAL)

        assert result.exit_code == 0
        assert "Welcome to a-sdlc Setup Wizard" in result.output
        assert "PASS" in result.output
        assert "Setup Complete" in result.output or "Setup complete" in result.output
        mock_installer.install.assert_called_once_with(force=False)

    def test_setup_missing_uv_warns_but_continues(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test setup warns about missing uv but continues installation."""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"mcpServers": {"asdlc": {}}}')

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        templates_dir = claude_dir / "commands" / "sdlc"
        templates_dir.mkdir(parents=True)

        with patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")), \
             patch("a_sdlc.cli.check_uv_available", return_value=(False, "Not found. Install from https://docs.astral.sh/uv/")), \
             patch("a_sdlc.cli.check_claude_code_installed", return_value=(True, str(claude_dir))), \
             patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json):
            mock_installer = mock_installer_cls.return_value
            mock_installer.list_installed.return_value = []
            mock_installer.install.return_value = ["init", "scan", "help"]
            mock_installer.target_dir = templates_dir

            result = runner.invoke(main, ["setup"], input=self.DECLINE_ALL_OPTIONAL)

        assert result.exit_code == 0
        assert "WARN" in result.output
        assert "uv/uvx not found" in result.output
        # Should still proceed with installation
        mock_installer.install.assert_called_once()

    def test_setup_missing_claude_code_fails(self, runner: CliRunner) -> None:
        """Test setup fails with instructions when Claude Code is missing."""
        with patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")), \
             patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")), \
             patch("a_sdlc.cli.check_claude_code_installed", return_value=(False, "~/.claude not found. Install Claude Code first.")):

            result = runner.invoke(main, ["setup"])

        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "Critical prerequisites not met" in result.output
        assert "Claude Code" in result.output

    def test_setup_delegates_to_installer_install(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test setup delegates template installation to Installer.install()."""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"mcpServers": {"asdlc": {}}}')

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        templates_dir = claude_dir / "commands" / "sdlc"
        templates_dir.mkdir(parents=True)

        with patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")), \
             patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")), \
             patch("a_sdlc.cli.check_claude_code_installed", return_value=(True, str(claude_dir))), \
             patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json):
            mock_installer = mock_installer_cls.return_value
            mock_installer.list_installed.return_value = []
            mock_installer.install.return_value = ["init", "scan", "help", "prd-generate", "prd-split"]
            mock_installer.target_dir = templates_dir

            result = runner.invoke(main, ["setup"], input=self.DECLINE_ALL_OPTIONAL)

        assert result.exit_code == 0
        # Verify Installer was instantiated and install() was called
        mock_installer_cls.assert_called_once()
        mock_installer.install.assert_called_once_with(force=False)
        # Verify the count is displayed
        assert "5" in result.output

    def test_setup_existing_templates_no_overwrite(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test setup with existing templates, user declines overwrite."""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"mcpServers": {"asdlc": {}}}')

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        templates_dir = claude_dir / "commands" / "sdlc"
        templates_dir.mkdir(parents=True)

        with patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")), \
             patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")), \
             patch("a_sdlc.cli.check_claude_code_installed", return_value=(True, str(claude_dir))), \
             patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json):
            mock_installer = mock_installer_cls.return_value
            mock_installer.list_installed.return_value = [
                {"name": "init", "file": "init.md"},
                {"name": "scan", "file": "scan.md"},
            ]
            mock_installer.install.return_value = ["init", "scan"]
            mock_installer.target_dir = templates_dir

            # Answer "n" to overwrite prompt, then decline all optional components
            result = runner.invoke(main, ["setup"], input="n\n" + self.DECLINE_ALL_OPTIONAL)

        assert result.exit_code == 0
        assert "existing skill templates" in result.output
        # force=False since user declined
        mock_installer.install.assert_called_once_with(force=False)

    def test_setup_existing_templates_force_overwrite(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test setup with existing templates, user accepts overwrite."""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"mcpServers": {"asdlc": {}}}')

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        templates_dir = claude_dir / "commands" / "sdlc"
        templates_dir.mkdir(parents=True)

        with patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")), \
             patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")), \
             patch("a_sdlc.cli.check_claude_code_installed", return_value=(True, str(claude_dir))), \
             patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json):
            mock_installer = mock_installer_cls.return_value
            mock_installer.list_installed.return_value = [
                {"name": "init", "file": "init.md"},
                {"name": "scan", "file": "scan.md"},
            ]
            mock_installer.install.return_value = ["init", "scan"]
            mock_installer.target_dir = templates_dir

            # Answer "y" to overwrite prompt, then decline all optional components
            result = runner.invoke(main, ["setup"], input="y\n" + self.DECLINE_ALL_OPTIONAL)

        assert result.exit_code == 0
        # force=True since user accepted
        mock_installer.install.assert_called_once_with(force=True)

    def test_setup_offers_optional_components(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test setup asks about optional components and calls setup when accepted."""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"mcpServers": {"asdlc": {}}}')

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        templates_dir = claude_dir / "commands" / "sdlc"
        templates_dir.mkdir(parents=True)

        with patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")), \
             patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")), \
             patch("a_sdlc.cli.check_claude_code_installed", return_value=(True, str(claude_dir))), \
             patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json), \
             patch("a_sdlc.cli._setup_serena_mcp") as mock_serena:
            mock_installer = mock_installer_cls.return_value
            mock_installer.list_installed.return_value = []
            mock_installer.install.return_value = ["init", "scan", "help"]
            mock_installer.target_dir = templates_dir

            # Accept Serena, decline the rest
            result = runner.invoke(main, ["setup"], input="y\nn\nn\nn\n")

        assert result.exit_code == 0
        assert "Optional integrations" in result.output
        assert "Serena MCP" in result.output
        mock_serena.assert_called_once_with(force=False)


class TestSetupUpgrade:
    """Tests for the --upgrade flag on the setup command."""

    # Input to decline all 4 optional components
    DECLINE_ALL_OPTIONAL = "n\nn\nn\nn\n"

    def _make_setup_context(self, tmp_path):
        """Create common mocks for setup --upgrade tests."""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"mcpServers": {"asdlc": {}}}')
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        templates_dir = claude_dir / "commands" / "sdlc"
        templates_dir.mkdir(parents=True)
        return claude_json, templates_dir

    def test_upgrade_force_installs_templates(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test --upgrade calls installer.install(force=True)."""
        claude_json, templates_dir = self._make_setup_context(tmp_path)

        with patch("a_sdlc.cli.check_python_version", return_value=(True, "3.12.0")), \
             patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/bin/uvx")), \
             patch("a_sdlc.cli.check_claude_code_installed", return_value=(True, str(tmp_path / ".claude"))), \
             patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json), \
             patch("a_sdlc.cli.configure_mcp_server", return_value={"status": "ok"}), \
             patch("a_sdlc.core.database.Database.__init__", return_value=None):
            mock_installer = mock_installer_cls.return_value
            mock_installer.check_template_version.return_value = (False, "0.1.0", "0.2.0")
            mock_installer.install.return_value = ["init", "scan", "help"]
            mock_installer.target_dir = templates_dir

            result = runner.invoke(main, ["setup", "--upgrade"], input=self.DECLINE_ALL_OPTIONAL)

        assert result.exit_code == 0
        mock_installer.install.assert_called_once_with(force=True)

    def test_upgrade_runs_db_migration(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test --upgrade triggers Database init for migration."""
        claude_json, templates_dir = self._make_setup_context(tmp_path)

        with patch("a_sdlc.cli.check_python_version", return_value=(True, "3.12.0")), \
             patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/bin/uvx")), \
             patch("a_sdlc.cli.check_claude_code_installed", return_value=(True, str(tmp_path / ".claude"))), \
             patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json), \
             patch("a_sdlc.cli.configure_mcp_server", return_value={"status": "ok"}), \
             patch("a_sdlc.core.database.Database.__init__", return_value=None) as mock_db_init:
            mock_installer = mock_installer_cls.return_value
            mock_installer.check_template_version.return_value = (False, "0.1.0", "0.2.0")
            mock_installer.install.return_value = ["init", "scan"]
            mock_installer.target_dir = templates_dir

            result = runner.invoke(main, ["setup", "--upgrade"], input=self.DECLINE_ALL_OPTIONAL)

        assert result.exit_code == 0
        mock_db_init.assert_called_once()

    def test_upgrade_refreshes_mcp_config(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test --upgrade calls configure_mcp_server(force=True)."""
        claude_json, templates_dir = self._make_setup_context(tmp_path)

        with patch("a_sdlc.cli.check_python_version", return_value=(True, "3.12.0")), \
             patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/bin/uvx")), \
             patch("a_sdlc.cli.check_claude_code_installed", return_value=(True, str(tmp_path / ".claude"))), \
             patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json), \
             patch("a_sdlc.cli.configure_mcp_server", return_value={"status": "ok"}) as mock_mcp, \
             patch("a_sdlc.core.database.Database.__init__", return_value=None):
            mock_installer = mock_installer_cls.return_value
            mock_installer.check_template_version.return_value = (False, "0.1.0", "0.2.0")
            mock_installer.install.return_value = ["init", "scan"]
            mock_installer.target_dir = templates_dir

            result = runner.invoke(main, ["setup", "--upgrade"], input=self.DECLINE_ALL_OPTIONAL)

        assert result.exit_code == 0
        mock_mcp.assert_called_once_with(force=True)

    def test_upgrade_shows_upgrade_banner(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test --upgrade shows upgrade-specific banner and completion message."""
        claude_json, templates_dir = self._make_setup_context(tmp_path)

        with patch("a_sdlc.cli.check_python_version", return_value=(True, "3.12.0")), \
             patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/bin/uvx")), \
             patch("a_sdlc.cli.check_claude_code_installed", return_value=(True, str(tmp_path / ".claude"))), \
             patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json), \
             patch("a_sdlc.cli.configure_mcp_server", return_value={"status": "ok"}), \
             patch("a_sdlc.core.database.Database.__init__", return_value=None):
            mock_installer = mock_installer_cls.return_value
            mock_installer.check_template_version.return_value = (False, "0.1.0", "0.2.0")
            mock_installer.install.return_value = ["init", "scan"]
            mock_installer.target_dir = templates_dir

            result = runner.invoke(main, ["setup", "--upgrade"], input=self.DECLINE_ALL_OPTIONAL)

        assert result.exit_code == 0
        assert "Upgrading a-sdlc" in result.output
        assert "Upgrade Complete" in result.output

    def test_setup_without_upgrade_is_normal_wizard(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test setup without --upgrade runs the normal wizard flow."""
        claude_json, templates_dir = self._make_setup_context(tmp_path)

        with patch("a_sdlc.cli.check_python_version", return_value=(True, "3.12.0")), \
             patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/bin/uvx")), \
             patch("a_sdlc.cli.check_claude_code_installed", return_value=(True, str(tmp_path / ".claude"))), \
             patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json):
            mock_installer = mock_installer_cls.return_value
            mock_installer.list_installed.return_value = []
            mock_installer.install.return_value = ["init", "scan"]
            mock_installer.target_dir = templates_dir

            result = runner.invoke(main, ["setup"], input=self.DECLINE_ALL_OPTIONAL)

        assert result.exit_code == 0
        assert "Welcome to a-sdlc Setup Wizard" in result.output
        assert "Setup Complete" in result.output
        mock_installer.install.assert_called_once_with(force=False)


class TestDoctorUvCheck:
    """Tests for uv/uvx availability check in doctor command."""

    def test_doctor_uv_pass(self, runner: CliRunner) -> None:
        """Test doctor reports PASS when uv/uvx is available."""
        with patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")):
            result = runner.invoke(main, ["doctor"])

        assert "uv/uvx" in result.output

    def test_doctor_uv_fail(self, runner: CliRunner) -> None:
        """Test doctor reports FAIL with fix instruction when uv/uvx is missing."""
        with patch("a_sdlc.cli.check_uv_available", return_value=(False, "Not found")):
            result = runner.invoke(main, ["doctor"])

        assert "uv/uvx" in result.output
        assert "FAIL" in result.output
        assert "Fix:" in result.output
        assert "https://docs.astral.sh/uv/" in result.output


class TestDoctorMcpServerCheck:
    """Tests for asdlc MCP server configuration check in doctor command."""

    def test_doctor_mcp_server_pass(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test doctor reports PASS when asdlc is configured in ~/.claude.json."""
        settings_file = tmp_path / ".claude.json"
        settings_file.write_text('{"mcpServers": {"asdlc": {"command": "uvx"}}}')

        with patch("a_sdlc.cli.get_claude_settings_path", return_value=settings_file):
            result = runner.invoke(main, ["doctor"])

        assert "asdlc MCP Server" in result.output
        assert "Configured" in result.output

    def test_doctor_mcp_server_warn_missing(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test doctor reports WARN when asdlc is not in ~/.claude.json."""
        settings_file = tmp_path / ".claude.json"
        settings_file.write_text('{"mcpServers": {}}')

        with patch("a_sdlc.cli.get_claude_settings_path", return_value=settings_file):
            result = runner.invoke(main, ["doctor"])

        assert "asdlc MCP Server" in result.output
        assert "Not found" in result.output
        assert "Fix:" in result.output

    def test_doctor_mcp_server_warn_no_file(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test doctor reports WARN when ~/.claude.json doesn't exist."""
        settings_file = tmp_path / "nonexistent.json"

        with patch("a_sdlc.cli.get_claude_settings_path", return_value=settings_file):
            result = runner.invoke(main, ["doctor"])

        assert "asdlc MCP Server" in result.output
        assert "Not found" in result.output


class TestDoctorDatabaseAccessible:
    """Tests for database accessibility check in doctor command."""

    def test_doctor_db_accessible_pass(self, runner: CliRunner) -> None:
        """Test doctor reports PASS when database is accessible."""
        import os
        import tempfile
        from unittest.mock import MagicMock

        # Create a real temp file to represent the database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            mock_db = MagicMock()
            mock_db.db_path = db_path

            with patch("a_sdlc.core.database.Database", return_value=mock_db), \
                 patch("sqlite3.connect") as mock_connect:
                mock_conn = MagicMock()
                mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
                mock_connect.return_value.__exit__ = MagicMock(return_value=False)
                from a_sdlc.core.database import SCHEMA_VERSION
                mock_conn.execute.return_value.fetchone.return_value = (SCHEMA_VERSION,)

                result = runner.invoke(main, ["doctor"])

            assert "Database Accessible" in result.output
        finally:
            os.unlink(db_path)

    def test_doctor_db_accessible_fail_on_error(self, runner: CliRunner) -> None:
        """Test doctor reports FAIL when database cannot be instantiated."""
        with patch("a_sdlc.core.database.Database", side_effect=Exception("Permission denied")):
            result = runner.invoke(main, ["doctor"])

        assert "Database Accessible" in result.output
        assert "Cannot open database" in result.output
        assert "Fix:" in result.output


class TestDoctorTemplateVersion:
    """Tests for template version check in doctor command."""

    def test_doctor_template_version_pass(self, runner: CliRunner) -> None:
        """Test doctor reports PASS when template version is current."""
        with patch("a_sdlc.cli.Installer") as mock_installer_cls:
            mock_installer = mock_installer_cls.return_value
            mock_installer.check_template_version.return_value = (True, "0.1.0", "0.1.0")

            result = runner.invoke(main, ["doctor"])

        assert "Template Version" in result.output
        assert "v0.1.0 (current)" in result.output

    def test_doctor_template_version_warn_outdated(self, runner: CliRunner) -> None:
        """Test doctor reports WARN when templates are outdated."""
        with patch("a_sdlc.cli.Installer") as mock_installer_cls:
            mock_installer = mock_installer_cls.return_value
            mock_installer.check_template_version.return_value = (False, "0.0.9", "0.1.0")

            result = runner.invoke(main, ["doctor"])

        assert "Template Version" in result.output
        assert "v0.0.9 installed" in result.output
        assert "v0.1.0 available" in result.output
        assert "Fix:" in result.output
        assert "a-sdlc install --force" in result.output

    def test_doctor_template_version_warn_on_error(self, runner: CliRunner) -> None:
        """Test doctor reports WARN when template version check fails."""
        with patch("a_sdlc.cli.Installer", side_effect=Exception("no templates")):
            result = runner.invoke(main, ["doctor"])

        assert "Template Version" in result.output
        assert "Cannot check" in result.output
        assert "Fix:" in result.output


class TestDoctorFixInstructions:
    """Tests that all WARN/FAIL checks include actionable fix instructions."""

    def test_doctor_uv_fail_has_fix(self, runner: CliRunner) -> None:
        """Test uv FAIL includes fix instruction with URL."""
        with patch("a_sdlc.cli.check_uv_available", return_value=(False, "Not found")):
            result = runner.invoke(main, ["doctor"])

        assert "uv/uvx" in result.output
        assert "Fix:" in result.output

    def test_doctor_mcp_server_warn_has_fix(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test asdlc MCP Server WARN includes fix instruction."""
        settings_file = tmp_path / ".claude.json"
        settings_file.write_text('{"mcpServers": {}}')

        with patch("a_sdlc.cli.get_claude_settings_path", return_value=settings_file):
            result = runner.invoke(main, ["doctor"])

        assert "asdlc MCP Server" in result.output
        assert "Fix:" in result.output

    def test_doctor_db_fail_has_fix(self, runner: CliRunner) -> None:
        """Test Database Accessible FAIL includes fix instruction."""
        with patch("a_sdlc.core.database.Database", side_effect=Exception("corrupted")):
            result = runner.invoke(main, ["doctor"])

        assert "Database Accessible" in result.output
        assert "Fix:" in result.output

    def test_doctor_template_version_warn_has_fix(self, runner: CliRunner) -> None:
        """Test Template Version WARN includes fix instruction."""
        with patch("a_sdlc.cli.Installer") as mock_installer_cls:
            mock_installer = mock_installer_cls.return_value
            mock_installer.check_template_version.return_value = (False, "0.0.1", "0.1.0")

            result = runner.invoke(main, ["doctor"])

        assert "Template Version" in result.output
        assert "Fix:" in result.output


class TestInstallPlaywright:
    """Tests for Playwright setup via install command."""

    def test_install_with_playwright_calls_setup(self, runner: CliRunner) -> None:
        """Test install with --with-playwright invokes Playwright setup."""
        with patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli._setup_playwright_mcp") as mock_setup:
            mock_installer = mock_installer_cls.return_value
            mock_installer.install.return_value = ["init", "scan", "help"]
            mock_installer.target_dir = Path("/tmp/sdlc")

            result = runner.invoke(main, ["install", "--with-playwright"])

        assert result.exit_code == 0
        mock_setup.assert_called_once_with(force=False)

    def test_install_with_playwright_force(self, runner: CliRunner) -> None:
        """Test install with --with-playwright --force passes force flag."""
        with patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli._setup_playwright_mcp") as mock_setup:
            mock_installer = mock_installer_cls.return_value
            mock_installer.install.return_value = ["init", "scan", "help"]
            mock_installer.target_dir = Path("/tmp/sdlc")

            result = runner.invoke(main, ["install", "--with-playwright", "--force"])

        assert result.exit_code == 0
        mock_setup.assert_called_once_with(force=True)

    def test_install_without_playwright_does_not_call_setup(self, runner: CliRunner) -> None:
        """Test install without --with-playwright does not invoke Playwright setup."""
        with patch("a_sdlc.cli.Installer") as mock_installer_cls, \
             patch("a_sdlc.cli._setup_playwright_mcp") as mock_setup:
            mock_installer = mock_installer_cls.return_value
            mock_installer.install.return_value = ["init", "scan", "help"]
            mock_installer.target_dir = Path("/tmp/sdlc")

            result = runner.invoke(main, ["install"])

        assert result.exit_code == 0
        mock_setup.assert_not_called()


class TestDoctorPlaywright:
    """Tests for Playwright MCP check in doctor command."""

    def test_doctor_shows_playwright(self, runner: CliRunner) -> None:
        """Test doctor command includes Playwright MCP check."""
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code in (0, 1)
        assert "Playwright MCP" in result.output

    def test_doctor_playwright_pass(self, runner: CliRunner) -> None:
        """Test doctor reports PASS when Playwright is ready."""
        with patch("a_sdlc.playwright_setup.verify_setup", return_value={
            "ready": True,
            "configured_in_settings": True,
            "installer_available": True,
            "installer_method": "npx",
        }):
            result = runner.invoke(main, ["doctor"])

        assert "Playwright MCP" in result.output
        assert "npx available" in result.output

    def test_doctor_playwright_warn_no_npx(self, runner: CliRunner) -> None:
        """Test doctor reports WARN when configured but npx missing."""
        with patch("a_sdlc.playwright_setup.verify_setup", return_value={
            "ready": False,
            "configured_in_settings": True,
            "installer_available": False,
            "installer_method": "none",
        }):
            result = runner.invoke(main, ["doctor"])

        assert "Playwright MCP" in result.output
        assert "npx not found" in result.output

    def test_doctor_playwright_warn_not_configured(self, runner: CliRunner) -> None:
        """Test doctor reports WARN when Playwright is not configured."""
        with patch("a_sdlc.playwright_setup.verify_setup", return_value={
            "ready": False,
            "configured_in_settings": False,
            "installer_available": True,
            "installer_method": "npx",
        }):
            result = runner.invoke(main, ["doctor"])

        assert "Playwright MCP" in result.output
        assert "Not configured" in result.output
        assert "--with-playwright" in result.output


class TestDoctorPersonas:
    """Tests for Persona Agents check in doctor command."""

    def test_doctor_shows_persona_check(self, runner: CliRunner) -> None:
        """Test doctor command includes Persona Agents check."""
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code in (0, 1)
        assert "Persona Agents" in result.output

    def test_doctor_personas_pass(self, runner: CliRunner) -> None:
        """Test doctor reports PASS when all 7 personas are deployed."""
        mock_personas = [{"name": f"sdlc-persona-{i}", "file": f"sdlc-persona-{i}.md"} for i in range(7)]
        with patch("a_sdlc.cli.Installer") as mock_installer_cls:
            mock_installer = mock_installer_cls.return_value
            mock_installer.list_installed_personas.return_value = mock_personas
            mock_installer.check_template_version.return_value = (True, "0.1.0", "0.1.0")
            mock_installer.list_installed.return_value = []
            mock_installer.target_dir = Path("/tmp/sdlc")

            result = runner.invoke(main, ["doctor"])

        assert "Persona Agents" in result.output
        assert "7 personas deployed" in result.output

    def test_doctor_personas_warn_partial(self, runner: CliRunner) -> None:
        """Test doctor reports WARN when fewer than 7 personas deployed."""
        mock_personas = [{"name": f"sdlc-persona-{i}", "file": f"sdlc-persona-{i}.md"} for i in range(3)]
        with patch("a_sdlc.cli.Installer") as mock_installer_cls:
            mock_installer = mock_installer_cls.return_value
            mock_installer.list_installed_personas.return_value = mock_personas
            mock_installer.check_template_version.return_value = (True, "0.1.0", "0.1.0")
            mock_installer.list_installed.return_value = []
            mock_installer.target_dir = Path("/tmp/sdlc")

            result = runner.invoke(main, ["doctor"])

        assert "Persona Agents" in result.output
        assert "3/7" in result.output
        assert "Fix:" in result.output

    def test_doctor_personas_warn_none(self, runner: CliRunner) -> None:
        """Test doctor reports WARN when no personas deployed."""
        with patch("a_sdlc.cli.Installer") as mock_installer_cls:
            mock_installer = mock_installer_cls.return_value
            mock_installer.list_installed_personas.return_value = []
            mock_installer.check_template_version.return_value = (True, "0.1.0", "0.1.0")
            mock_installer.list_installed.return_value = []
            mock_installer.target_dir = Path("/tmp/sdlc")

            result = runner.invoke(main, ["doctor"])

        assert "Persona Agents" in result.output
        assert "No personas found" in result.output
        assert "Fix:" in result.output


# ---------------------------------------------------------------------------
# Persona install/uninstall lifecycle
# ---------------------------------------------------------------------------


class TestInstallPersonas:
    """Tests for persona deployment lifecycle."""

    def test_install_deploys_persona_files(self, tmp_path: Path) -> None:
        """Verify install_personas deploys files to target dir."""
        installer = Installer()
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        with patch.object(Installer, "PERSONA_TARGET", persona_target):
            installed = installer.install_personas()
        assert len(installed) >= 7
        for name in installed:
            assert (persona_target / f"{name}.md").exists()

    def test_install_personas_skip_existing_without_force(self, tmp_path: Path) -> None:
        """Existing persona files not overwritten without --force."""
        installer = Installer()
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        # Create a pre-existing file with distinct content
        existing = persona_target / "sdlc-product-manager.md"
        existing.write_text("old content")
        with patch.object(Installer, "PERSONA_TARGET", persona_target):
            installer.install_personas(force=False)
        assert existing.read_text() == "old content"

    def test_install_personas_force_overwrites(self, tmp_path: Path) -> None:
        """Force flag overwrites existing persona files."""
        installer = Installer()
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        existing = persona_target / "sdlc-product-manager.md"
        existing.write_text("old content")
        with patch.object(Installer, "PERSONA_TARGET", persona_target):
            installer.install_personas(force=True)
        assert existing.read_text() != "old content"

    def test_uninstall_personas_only_removes_sdlc_prefix(self, tmp_path: Path) -> None:
        """uninstall_personas only removes sdlc-*.md, not other files."""
        installer = Installer()
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        # Create sdlc persona file and non-sdlc file
        (persona_target / "sdlc-test.md").write_text("sdlc persona")
        (persona_target / "custom-agent.md").write_text("user agent")
        with patch.object(Installer, "PERSONA_TARGET", persona_target):
            count = installer.uninstall_personas()
        assert count == 1
        assert not (persona_target / "sdlc-test.md").exists()
        assert (persona_target / "custom-agent.md").exists()

    def test_uninstall_personas_returns_zero_when_dir_missing(self) -> None:
        """uninstall_personas returns 0 when PERSONA_TARGET does not exist."""
        installer = Installer()
        with patch.object(Installer, "PERSONA_TARGET", Path("/nonexistent/agents")):
            count = installer.uninstall_personas()
        assert count == 0

    def test_list_installed_personas(self, tmp_path: Path) -> None:
        """list_installed_personas returns correct persona list."""
        installer = Installer()
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        with patch.object(Installer, "PERSONA_TARGET", persona_target):
            installer.install_personas()
            personas = installer.list_installed_personas()
        assert len(personas) >= 7
        names = [p["name"] for p in personas]
        assert "sdlc-product-manager" in names

    def test_list_installed_personas_empty_when_dir_missing(self) -> None:
        """list_installed_personas returns empty list when dir does not exist."""
        installer = Installer()
        with patch.object(Installer, "PERSONA_TARGET", Path("/nonexistent/agents")):
            personas = installer.list_installed_personas()
        assert personas == []

    def test_list_installed_personas_ignores_non_sdlc_files(self, tmp_path: Path) -> None:
        """list_installed_personas only returns sdlc-*.md files."""
        installer = Installer()
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        (persona_target / "sdlc-architect.md").write_text("# arch")
        (persona_target / "custom-agent.md").write_text("# custom")
        (persona_target / "readme.md").write_text("# readme")
        with patch.object(Installer, "PERSONA_TARGET", persona_target):
            personas = installer.list_installed_personas()
        assert len(personas) == 1
        assert personas[0]["name"] == "sdlc-architect"

    def test_verify_persona_integrity_pass(self, tmp_path: Path) -> None:
        """verify_persona_integrity returns True when files match source."""
        installer = Installer()
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        with patch.object(Installer, "PERSONA_TARGET", persona_target):
            installer.install_personas(force=True)
            results = installer.verify_persona_integrity()
        assert all(results.values())
        assert len(results) >= 7

    def test_verify_persona_integrity_fail_modified(self, tmp_path: Path) -> None:
        """verify_persona_integrity detects modified files."""
        installer = Installer()
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        with patch.object(Installer, "PERSONA_TARGET", persona_target):
            installer.install_personas(force=True)
            # Modify one file
            modified = persona_target / "sdlc-product-manager.md"
            modified.write_text("tampered content")
            results = installer.verify_persona_integrity()
        assert results["sdlc-product-manager"] is False
        # Other files should still pass
        non_modified = {k: v for k, v in results.items() if k != "sdlc-product-manager"}
        assert all(non_modified.values())

    def test_verify_persona_integrity_fail_missing(self, tmp_path: Path) -> None:
        """verify_persona_integrity detects missing files."""
        installer = Installer()
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        with patch.object(Installer, "PERSONA_TARGET", persona_target):
            installer.install_personas(force=True)
            # Remove one file
            (persona_target / "sdlc-architect.md").unlink()
            results = installer.verify_persona_integrity()
        assert results["sdlc-architect"] is False

    def test_persona_files_have_valid_yaml_frontmatter(self) -> None:
        """All source persona files have valid YAML frontmatter."""
        import yaml

        installer = Installer()
        persona_dir = installer._get_persona_dir()
        persona_files = list(persona_dir.glob("*.md"))
        assert len(persona_files) >= 7, f"Expected 7+ persona files, found {len(persona_files)}"

        required_keys = {"name", "description", "category", "tools", "memory"}
        for pf in persona_files:
            content = pf.read_text()
            # Parse YAML frontmatter (between --- delimiters)
            assert content.startswith("---"), f"{pf.name} missing frontmatter start"
            end_idx = content.index("---", 3)
            frontmatter = yaml.safe_load(content[3:end_idx])
            assert isinstance(frontmatter, dict), f"{pf.name} frontmatter is not a dict"
            missing = required_keys - set(frontmatter.keys())
            assert not missing, f"{pf.name} missing keys: {missing}"
            assert frontmatter["category"] == "sdlc", f"{pf.name} category must be 'sdlc'"

    def test_install_creates_target_dir_if_missing(self, tmp_path: Path) -> None:
        """install_personas creates PERSONA_TARGET directory if it does not exist."""
        installer = Installer()
        persona_target = tmp_path / "new_agents_dir"
        assert not persona_target.exists()
        with patch.object(Installer, "PERSONA_TARGET", persona_target):
            installed = installer.install_personas()
        assert persona_target.exists()
        assert len(installed) >= 7

    def test_install_output_shows_persona_count(self, runner: CliRunner) -> None:
        """CLI install output includes persona deployment count."""
        with patch("a_sdlc.cli.Installer") as mock_installer_cls:
            mock_installer = mock_installer_cls.return_value
            mock_installer.install.return_value = ["init", "scan", "help"]
            mock_installer.list_installed_personas.return_value = [
                {"name": f"sdlc-persona-{i}", "file": f"sdlc-persona-{i}.md"}
                for i in range(7)
            ]
            mock_installer.target_dir = Path("/tmp/sdlc")

            result = runner.invoke(main, ["install"])

        assert result.exit_code == 0
        assert "7 agent(s)" in result.output

    def test_install_list_shows_personas(self, runner: CliRunner) -> None:
        """CLI install --list shows installed personas section."""
        with patch("a_sdlc.cli.Installer") as mock_installer_cls:
            mock_installer = mock_installer_cls.return_value
            mock_installer.list_installed.return_value = [
                {"name": "init", "file": "init.md"},
            ]
            mock_installer.list_installed_personas.return_value = [
                {"name": "sdlc-product-manager", "file": "sdlc-product-manager.md"},
            ]
            mock_installer.target_dir = Path("/tmp/sdlc")

            result = runner.invoke(main, ["install", "--list"])

        assert result.exit_code == 0
        assert "Persona" in result.output
        assert "sdlc-product-manager" in result.output

    def test_install_calls_install_personas_via_install(self, tmp_path: Path) -> None:
        """Installer.install() internally calls install_personas()."""
        installer = Installer(target_dir=tmp_path / "sdlc")
        persona_target = tmp_path / "agents"
        with (
            patch.object(Installer, "PERSONA_TARGET", persona_target),
            patch.object(installer, "install_personas") as mock_personas,
        ):
            mock_personas.return_value = []
            installer.install(configure_mcp=False)
            mock_personas.assert_called_once_with(force=False)

    def test_install_passes_force_to_install_personas(self, tmp_path: Path) -> None:
        """Installer.install(force=True) passes force to install_personas()."""
        installer = Installer(target_dir=tmp_path / "sdlc")
        persona_target = tmp_path / "agents"
        with (
            patch.object(Installer, "PERSONA_TARGET", persona_target),
            patch.object(installer, "install_personas") as mock_personas,
        ):
            mock_personas.return_value = []
            installer.install(force=True, configure_mcp=False)
            mock_personas.assert_called_once_with(force=True)


# ---------------------------------------------------------------------------
# Agent Teams configuration during install
# ---------------------------------------------------------------------------


class TestInstallAgentTeams:
    """Tests for Agent Teams configuration during install."""

    def test_install_enables_agent_teams(self, runner: CliRunner, tmp_path: Path) -> None:
        """install sets CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 in settings.json."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}")

        with (
            patch("a_sdlc.cli.Installer") as MockInstaller,  # noqa: N806
            patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        ):
            mock_inst = MockInstaller.return_value
            mock_inst.install.return_value = ["template1"]
            mock_inst.list_installed_personas.return_value = [{"name": "p1", "file": "p1.md"}]
            mock_inst.target_dir = tmp_path / "sdlc"

            result = runner.invoke(main, ["install"])

        assert result.exit_code == 0
        assert "Agent Teams" in result.output
        assert "Enabled" in result.output
        settings = json.loads(settings_file.read_text())
        assert settings.get("environment", {}).get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS") == "1"

    def test_install_no_agent_teams_flag(self, runner: CliRunner, tmp_path: Path) -> None:
        """--no-agent-teams skips Agent Teams configuration."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{}")

        with (
            patch("a_sdlc.cli.Installer") as MockInstaller,  # noqa: N806
            patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        ):
            mock_inst = MockInstaller.return_value
            mock_inst.install.return_value = ["template1"]
            mock_inst.list_installed_personas.return_value = []
            mock_inst.target_dir = tmp_path / "sdlc"

            result = runner.invoke(main, ["install", "--no-agent-teams"])

        assert result.exit_code == 0
        assert "Skipped" in result.output
        settings = json.loads(settings_file.read_text())
        assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" not in settings.get("environment", {})

    def test_install_agent_teams_preserves_existing_env(self, runner: CliRunner, tmp_path: Path) -> None:
        """Agent Teams config preserves existing environment variables."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({
            "environment": {"MY_EXISTING_VAR": "keep-me"}
        }))

        with (
            patch("a_sdlc.cli.Installer") as MockInstaller,  # noqa: N806
            patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", settings_file),
        ):
            mock_inst = MockInstaller.return_value
            mock_inst.install.return_value = ["template1"]
            mock_inst.list_installed_personas.return_value = []
            mock_inst.target_dir = tmp_path / "sdlc"

            result = runner.invoke(main, ["install"])

        assert result.exit_code == 0
        settings = json.loads(settings_file.read_text())
        assert settings["environment"]["MY_EXISTING_VAR"] == "keep-me"
        assert settings["environment"]["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] == "1"

    def test_install_agent_teams_handles_settings_error(self, runner: CliRunner, tmp_path: Path) -> None:
        """Agent Teams config shows warning when settings.json cannot be written."""
        with (
            patch("a_sdlc.cli.Installer") as MockInstaller,  # noqa: N806
            patch("a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH", tmp_path / "nonexistent_dir" / "settings.json"),
        ):
            mock_inst = MockInstaller.return_value
            mock_inst.install.return_value = ["template1"]
            mock_inst.list_installed_personas.return_value = []
            mock_inst.target_dir = tmp_path / "sdlc"

            result = runner.invoke(main, ["install"])

        assert result.exit_code == 0
        assert "Agent Teams" in result.output


# ---------------------------------------------------------------------------
# Backward compatibility: underscore-prefix exclusion and round-table
# ---------------------------------------------------------------------------


class TestInstallerUnderscorePrefixExclusion:
    """Tests that installer excludes underscore-prefixed files from deployment."""

    def test_underscore_prefixed_file_exists_in_source(self) -> None:
        """Verify _round-table-blocks.md exists in source templates directory."""
        installer = Installer()
        template_dir = installer._get_template_dir()
        blocks_file = template_dir / "_round-table-blocks.md"
        assert blocks_file.exists(), (
            "_round-table-blocks.md must exist in source templates directory"
        )

    def test_install_does_not_deploy_underscore_prefixed_files(self, tmp_path: Path) -> None:
        """Installer.install() must NOT copy files starting with _ to target."""
        installer = Installer(target_dir=tmp_path / "sdlc")
        installer.install(configure_mcp=False)

        target_dir = tmp_path / "sdlc"
        installed_files = [f.name for f in target_dir.iterdir() if f.is_file()]

        # _round-table-blocks.md must not appear in the installed target
        assert "_round-table-blocks.md" not in installed_files, (
            "_round-table-blocks.md was deployed but should be excluded by underscore prefix"
        )

    def test_install_does_not_deploy_any_underscore_prefixed_md(self, tmp_path: Path) -> None:
        """No underscore-prefixed .md files should appear in installed target."""
        installer = Installer(target_dir=tmp_path / "sdlc")
        installer.install(configure_mcp=False)

        target_dir = tmp_path / "sdlc"
        underscore_files = [
            f.name for f in target_dir.glob("_*.md")
        ]
        assert underscore_files == [], (
            f"Underscore-prefixed files deployed but should be excluded: {underscore_files}"
        )

    def test_install_still_deploys_regular_templates(self, tmp_path: Path) -> None:
        """Installer.install() still deploys non-underscore templates correctly."""
        installer = Installer(target_dir=tmp_path / "sdlc")
        installed = installer.install(configure_mcp=False)

        # Should deploy many templates (at least the known ones)
        assert len(installed) >= 10, (
            f"Expected at least 10 templates deployed, got {len(installed)}"
        )

        # Check a few known templates are present
        target_dir = tmp_path / "sdlc"
        for expected in ["init.md", "scan.md", "help.md", "ideate.md", "prd-generate.md"]:
            assert (target_dir / expected).exists(), (
                f"Expected template {expected} not found in target"
            )

    def test_round_table_blocks_not_in_installed_list(self, tmp_path: Path) -> None:
        """_round-table-blocks should not appear in list_installed() results."""
        installer = Installer(target_dir=tmp_path / "sdlc")
        installer.install(configure_mcp=False)

        installed_skills = installer.list_installed()
        installed_names = [s["name"] for s in installed_skills]

        assert "_round-table-blocks" not in installed_names, (
            "_round-table-blocks appeared in list_installed() but should be excluded"
        )


# ---------------------------------------------------------------------------
# Template graceful degradation for round-table persona integration
# ---------------------------------------------------------------------------


class TestTemplateGracefulDegradation:
    """Tests that modified templates contain round-table graceful degradation patterns.

    Templates must gate persona-specific behavior behind a round_table_enabled
    check and reference --solo or --no-roundtable as bypass flags so that
    single-agent mode (pre-persona behavior) is preserved.
    """

    # Full round-table templates: have Section references, full round-table gates
    FULL_ROUNDTABLE_TEMPLATES = [
        "ideate.md",
        "prd-generate.md",
        "prd-architect.md",
        "prd-split.md",
        "sprint-run.md",
        "task-complete.md",
        "test.md",
        "retrospective.md",
    ]

    # Lightweight templates: have persona panel references but lighter integration
    LIGHTWEIGHT_TEMPLATES = [
        "task-start.md",
        "investigate.md",
        "pr-feedback.md",
    ]

    def _read_template(self, filename: str) -> str:
        """Read a template file from the source templates directory."""
        installer = Installer()
        template_dir = installer._get_template_dir()
        template_path = template_dir / filename
        assert template_path.exists(), f"Template {filename} not found in {template_dir}"
        return template_path.read_text()

    def test_full_templates_have_roundtable_enabled_check(self) -> None:
        """All full round-table templates must contain the round_table_enabled variable."""
        for template_name in self.FULL_ROUNDTABLE_TEMPLATES:
            content = self._read_template(template_name)
            assert "round_table_enabled" in content, (
                f"{template_name} missing 'round_table_enabled' check pattern"
            )

    def test_full_templates_reference_bypass_flags(self) -> None:
        """All full round-table templates must reference --solo or --no-roundtable."""
        for template_name in self.FULL_ROUNDTABLE_TEMPLATES:
            content = self._read_template(template_name)
            has_solo = "--solo" in content
            has_no_roundtable = "--no-roundtable" in content
            assert has_solo or has_no_roundtable, (
                f"{template_name} missing bypass flag reference (--solo or --no-roundtable)"
            )

    def test_full_templates_reference_round_table_blocks(self) -> None:
        """All full round-table templates must reference _round-table-blocks.md sections."""
        for template_name in self.FULL_ROUNDTABLE_TEMPLATES:
            content = self._read_template(template_name)
            assert "_round-table-blocks.md" in content, (
                f"{template_name} missing reference to _round-table-blocks.md"
            )

    def test_full_templates_have_section_references(self) -> None:
        """All full round-table templates must reference at least one Section (A, B, or C)."""
        for template_name in self.FULL_ROUNDTABLE_TEMPLATES:
            content = self._read_template(template_name)
            has_section_ref = (
                "Section A" in content
                or "Section B" in content
                or "Section C" in content
            )
            assert has_section_ref, (
                f"{template_name} missing Section A/B/C reference from _round-table-blocks.md"
            )

    def test_lightweight_templates_have_roundtable_enabled_check(self) -> None:
        """Lightweight templates must contain the round_table_enabled variable."""
        for template_name in self.LIGHTWEIGHT_TEMPLATES:
            content = self._read_template(template_name)
            assert "round_table_enabled" in content, (
                f"{template_name} missing 'round_table_enabled' check pattern"
            )

    def test_lightweight_templates_reference_bypass_flags(self) -> None:
        """Lightweight templates must reference --solo as a bypass flag."""
        for template_name in self.LIGHTWEIGHT_TEMPLATES:
            content = self._read_template(template_name)
            assert "--solo" in content, (
                f"{template_name} missing --solo bypass flag reference"
            )

    def test_lightweight_templates_have_persona_panel_reference(self) -> None:
        """Lightweight templates must contain Persona Panel references."""
        for template_name in self.LIGHTWEIGHT_TEMPLATES:
            content = self._read_template(template_name)
            has_persona_panel = (
                "Persona Panel" in content or "persona panel" in content
            )
            assert has_persona_panel, (
                f"{template_name} missing Persona Panel reference"
            )

    def test_lightweight_templates_reference_blocks_file(self) -> None:
        """Lightweight templates must reference _round-table-blocks.md."""
        for template_name in self.LIGHTWEIGHT_TEMPLATES:
            content = self._read_template(template_name)
            assert "_round-table-blocks.md" in content, (
                f"{template_name} missing reference to _round-table-blocks.md"
            )

    def test_all_modified_templates_gate_on_false(self) -> None:
        """All modified templates must have conditional logic for round_table_enabled = false.

        This ensures single-agent mode is explicitly handled (graceful degradation).
        """
        all_templates = self.FULL_ROUNDTABLE_TEMPLATES + self.LIGHTWEIGHT_TEMPLATES
        for template_name in all_templates:
            content = self._read_template(template_name)
            # Templates should reference the false/disabled case explicitly
            has_false_gate = (
                "round_table_enabled = false" in content
                or "round_table_enabled = False" in content
            )
            assert has_false_gate, (
                f"{template_name} missing explicit 'round_table_enabled = false' gate "
                f"for single-agent fallback"
            )

    def test_round_table_blocks_source_exists_and_has_sections(self) -> None:
        """_round-table-blocks.md must exist and define Sections A, B, and C."""
        content = self._read_template("_round-table-blocks.md")
        assert "Section A" in content, "_round-table-blocks.md missing Section A"
        assert "Section B" in content, "_round-table-blocks.md missing Section B"
        assert "Section C" in content, "_round-table-blocks.md missing Section C"

    def test_round_table_blocks_not_a_deployable_skill(self) -> None:
        """_round-table-blocks.md starts with underscore and must not be deployed."""
        installer = Installer()
        template_dir = installer._get_template_dir()
        blocks_file = template_dir / "_round-table-blocks.md"
        assert blocks_file.name.startswith("_"), (
            "_round-table-blocks.md must start with underscore to be excluded from deployment"
        )

    def test_no_templates_are_missing_roundtable_integration(self) -> None:
        """Verify the expected set of 11 templates have round-table integration.

        This test guards against regression where a template might lose its
        persona integration during refactoring.
        """
        all_expected = self.FULL_ROUNDTABLE_TEMPLATES + self.LIGHTWEIGHT_TEMPLATES
        assert len(all_expected) == 11, (
            f"Expected 11 templates with round-table integration, got {len(all_expected)}"
        )
        for template_name in all_expected:
            content = self._read_template(template_name)
            assert "round_table_enabled" in content, (
                f"{template_name} has lost its round-table integration"
            )
