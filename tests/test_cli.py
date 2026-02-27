"""Tests for CLI commands."""

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
    assert "0.2.0" in result.output


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
