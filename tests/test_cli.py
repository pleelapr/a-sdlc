"""Tests for CLI commands."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from a_sdlc import __version__
from a_sdlc.cli import main
from a_sdlc.cli_targets import CLAUDE_TARGET, GEMINI_TARGET, CLITarget
from a_sdlc.installer import Installer


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture(autouse=True)
def _mock_doctor_externals():
    """Auto-mock slow external calls used by the doctor command.

    The doctor command checks Docker, monitoring services (HTTP to localhost
    ports 13000/8080 with 5s timeouts each), SonarQube, and Playwright.
    Without mocking, each doctor test waits ~15s for these timeouts.
    """
    with (
        patch("a_sdlc.cli.check_docker_available", return_value=False),
        patch(
            "a_sdlc.cli.check_services_health",
            return_value={
                "langfuse_reachable": False,
                "langfuse_url": "http://localhost:13000 (not reachable)",
                "signoz_reachable": False,
                "signoz_url": "http://localhost:8080 (not reachable)",
                "services_running": False,
            },
        ),
        patch(
            "a_sdlc.cli.verify_monitoring_setup",
            return_value={
                "files_ready": False,
                "settings_ready": False,
                "ready": False,
                "hook_registered": False,
                "otel_configured": False,
            },
        ),
        patch(
            "a_sdlc.cli.verify_sonarqube_setup",
            return_value={
                "ready": False,
                "host_url_configured": False,
            },
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _mock_cli_targets():
    """Auto-mock resolve_targets and detect_targets to return Claude target by default.

    The install command calls resolve_targets() and setup/doctor call
    detect_targets(), both of which check for directories on disk.
    This fixture ensures all existing tests continue to work without
    modification. Tests that need specific target behavior can override
    these by patching explicitly (inner patch wins over fixture).
    """
    with (
        patch("a_sdlc.cli.resolve_targets", return_value=[CLAUDE_TARGET]),
        patch("a_sdlc.cli.detect_targets", return_value=[CLAUDE_TARGET]),
    ):
        yield


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

        with (
            patch("a_sdlc.core.database.Database", return_value=mock_db),
            patch("sqlite3.connect") as mock_connect,
        ):
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

        with (
            patch("a_sdlc.core.database.Database", return_value=mock_db),
            patch("sqlite3.connect") as mock_connect,
        ):
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

        with (
            patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")),
            patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json),
        ):
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

        with (
            patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")),
            patch(
                "a_sdlc.cli.check_uv_available",
                return_value=(False, "Not found. Install from https://docs.astral.sh/uv/"),
            ),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json),
        ):
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

    def test_setup_missing_cli_targets_fails(self, runner: CliRunner) -> None:
        """Test setup fails with instructions when no CLI targets are found."""
        with (
            patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")),
            patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")),
            patch("a_sdlc.cli.detect_targets", return_value=[]),
        ):
            result = runner.invoke(main, ["setup"])

        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "Critical prerequisites not met" in result.output
        assert "CLI Targets" in result.output

    def test_setup_delegates_to_installer_install(self, runner: CliRunner, tmp_path: Path) -> None:
        """Test setup delegates template installation to Installer.install()."""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"mcpServers": {"asdlc": {}}}')

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        templates_dir = claude_dir / "commands" / "sdlc"
        templates_dir.mkdir(parents=True)

        with (
            patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")),
            patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json),
        ):
            mock_installer = mock_installer_cls.return_value
            mock_installer.list_installed.return_value = []
            mock_installer.install.return_value = [
                "init",
                "scan",
                "help",
                "prd-generate",
                "prd-split",
            ]
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

        with (
            patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")),
            patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json),
        ):
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

    def test_setup_existing_templates_force_overwrite(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test setup with existing templates, user accepts overwrite."""
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text('{"mcpServers": {"asdlc": {}}}')

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        templates_dir = claude_dir / "commands" / "sdlc"
        templates_dir.mkdir(parents=True)

        with (
            patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")),
            patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json),
        ):
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

        with (
            patch("a_sdlc.cli.check_python_version", return_value=(True, "Python 3.12.0")),
            patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/local/bin/uvx")),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json),
            patch("a_sdlc.cli._setup_serena_mcp") as mock_serena,
        ):
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

        with (
            patch("a_sdlc.cli.check_python_version", return_value=(True, "3.12.0")),
            patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/bin/uvx")),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json),
            patch("a_sdlc.cli.configure_mcp_server", return_value={"status": "ok"}),
            patch("a_sdlc.core.database.Database.__init__", return_value=None),
        ):
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

        with (
            patch("a_sdlc.cli.check_python_version", return_value=(True, "3.12.0")),
            patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/bin/uvx")),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json),
            patch("a_sdlc.cli.configure_mcp_server", return_value={"status": "ok"}),
            patch("a_sdlc.core.database.Database.__init__", return_value=None) as mock_db_init,
        ):
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

        with (
            patch("a_sdlc.cli.check_python_version", return_value=(True, "3.12.0")),
            patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/bin/uvx")),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json),
            patch("a_sdlc.cli.configure_mcp_server", return_value={"status": "ok"}) as mock_mcp,
            patch("a_sdlc.core.database.Database.__init__", return_value=None),
        ):
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

        with (
            patch("a_sdlc.cli.check_python_version", return_value=(True, "3.12.0")),
            patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/bin/uvx")),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json),
            patch("a_sdlc.cli.configure_mcp_server", return_value={"status": "ok"}),
            patch("a_sdlc.core.database.Database.__init__", return_value=None),
        ):
            mock_installer = mock_installer_cls.return_value
            mock_installer.check_template_version.return_value = (False, "0.1.0", "0.2.0")
            mock_installer.install.return_value = ["init", "scan"]
            mock_installer.target_dir = templates_dir

            result = runner.invoke(main, ["setup", "--upgrade"], input=self.DECLINE_ALL_OPTIONAL)

        assert result.exit_code == 0
        assert "Upgrading a-sdlc" in result.output
        assert "Upgrade Complete" in result.output

    def test_setup_without_upgrade_is_normal_wizard(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test setup without --upgrade runs the normal wizard flow."""
        claude_json, templates_dir = self._make_setup_context(tmp_path)

        with (
            patch("a_sdlc.cli.check_python_version", return_value=(True, "3.12.0")),
            patch("a_sdlc.cli.check_uv_available", return_value=(True, "/usr/bin/uvx")),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli.get_claude_settings_path", return_value=claude_json),
        ):
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

            with (
                patch("a_sdlc.core.database.Database", return_value=mock_db),
                patch("sqlite3.connect") as mock_connect,
            ):
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
        with (
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli._setup_playwright_mcp") as mock_setup,
        ):
            mock_installer = mock_installer_cls.return_value
            mock_installer.install.return_value = ["init", "scan", "help"]
            mock_installer.target_dir = Path("/tmp/sdlc")

            result = runner.invoke(main, ["install", "--with-playwright"])

        assert result.exit_code == 0
        mock_setup.assert_called_once_with(force=False)

    def test_install_with_playwright_force(self, runner: CliRunner) -> None:
        """Test install with --with-playwright --force passes force flag."""
        with (
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli._setup_playwright_mcp") as mock_setup,
        ):
            mock_installer = mock_installer_cls.return_value
            mock_installer.install.return_value = ["init", "scan", "help"]
            mock_installer.target_dir = Path("/tmp/sdlc")

            result = runner.invoke(main, ["install", "--with-playwright", "--force"])

        assert result.exit_code == 0
        mock_setup.assert_called_once_with(force=True)

    def test_install_without_playwright_does_not_call_setup(self, runner: CliRunner) -> None:
        """Test install without --with-playwright does not invoke Playwright setup."""
        with (
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli._setup_playwright_mcp") as mock_setup,
        ):
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
        with patch(
            "a_sdlc.playwright_setup.verify_setup",
            return_value={
                "ready": True,
                "configured_in_settings": True,
                "installer_available": True,
                "installer_method": "npx",
            },
        ):
            result = runner.invoke(main, ["doctor"])

        assert "Playwright MCP" in result.output
        assert "npx available" in result.output

    def test_doctor_playwright_warn_no_npx(self, runner: CliRunner) -> None:
        """Test doctor reports WARN when configured but npx missing."""
        with patch(
            "a_sdlc.playwright_setup.verify_setup",
            return_value={
                "ready": False,
                "configured_in_settings": True,
                "installer_available": False,
                "installer_method": "none",
            },
        ):
            result = runner.invoke(main, ["doctor"])

        assert "Playwright MCP" in result.output
        assert "npx not found" in result.output

    def test_doctor_playwright_warn_not_configured(self, runner: CliRunner) -> None:
        """Test doctor reports WARN when Playwright is not configured."""
        with patch(
            "a_sdlc.playwright_setup.verify_setup",
            return_value={
                "ready": False,
                "configured_in_settings": False,
                "installer_available": True,
                "installer_method": "npx",
            },
        ):
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
        mock_personas = [
            {"name": f"sdlc-persona-{i}", "file": f"sdlc-persona-{i}.md"} for i in range(7)
        ]
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
        mock_personas = [
            {"name": f"sdlc-persona-{i}", "file": f"sdlc-persona-{i}.md"} for i in range(3)
        ]
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

    @staticmethod
    def _make_target(agents_dir: Path) -> CLITarget:
        """Create a CLITarget with a custom agents_dir for testing."""
        return CLITarget(
            name=CLAUDE_TARGET.name,
            display_name=CLAUDE_TARGET.display_name,
            home_dir=CLAUDE_TARGET.home_dir,
            mcp_config_path=CLAUDE_TARGET.mcp_config_path,
            settings_path=CLAUDE_TARGET.settings_path,
            commands_dir=CLAUDE_TARGET.commands_dir,
            agents_dir=agents_dir,
            context_file=CLAUDE_TARGET.context_file,
        )

    @staticmethod
    def _make_target_no_agents() -> CLITarget:
        """Create a CLITarget with agents_dir=None for testing fallback."""
        return CLITarget(
            name=CLAUDE_TARGET.name,
            display_name=CLAUDE_TARGET.display_name,
            home_dir=CLAUDE_TARGET.home_dir,
            mcp_config_path=CLAUDE_TARGET.mcp_config_path,
            settings_path=CLAUDE_TARGET.settings_path,
            commands_dir=CLAUDE_TARGET.commands_dir,
            agents_dir=None,
            context_file=CLAUDE_TARGET.context_file,
        )

    def test_install_deploys_persona_files(self, tmp_path: Path) -> None:
        """Verify install_personas deploys files to target dir."""
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        target = self._make_target(persona_target)
        installer = Installer(target=target)
        installed = installer.install_personas()
        assert len(installed) >= 7
        for name in installed:
            assert (persona_target / f"{name}.md").exists()

    def test_install_personas_skip_existing_without_force(self, tmp_path: Path) -> None:
        """Existing persona files not overwritten without --force."""
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        target = self._make_target(persona_target)
        installer = Installer(target=target)
        # Create a pre-existing file with distinct content
        existing = persona_target / "sdlc-product-manager.md"
        existing.write_text("old content")
        installer.install_personas(force=False)
        assert existing.read_text() == "old content"

    def test_install_personas_force_overwrites(self, tmp_path: Path) -> None:
        """Force flag overwrites existing persona files."""
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        target = self._make_target(persona_target)
        installer = Installer(target=target)
        existing = persona_target / "sdlc-product-manager.md"
        existing.write_text("old content")
        installer.install_personas(force=True)
        assert existing.read_text() != "old content"

    def test_uninstall_personas_only_removes_sdlc_prefix(self, tmp_path: Path) -> None:
        """uninstall_personas only removes sdlc-*.md, not other files."""
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        target = self._make_target(persona_target)
        installer = Installer(target=target)
        # Create sdlc persona file and non-sdlc file
        (persona_target / "sdlc-test.md").write_text("sdlc persona")
        (persona_target / "custom-agent.md").write_text("user agent")
        count = installer.uninstall_personas()
        assert count == 1
        assert not (persona_target / "sdlc-test.md").exists()
        assert (persona_target / "custom-agent.md").exists()

    def test_uninstall_personas_returns_zero_when_dir_missing(self) -> None:
        """uninstall_personas returns 0 when agents_dir does not exist."""
        target = self._make_target(Path("/nonexistent/agents"))
        installer = Installer(target=target)
        count = installer.uninstall_personas()
        assert count == 0

    def test_list_installed_personas(self, tmp_path: Path) -> None:
        """list_installed_personas returns correct persona list."""
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        target = self._make_target(persona_target)
        installer = Installer(target=target)
        installer.install_personas()
        personas = installer.list_installed_personas()
        assert len(personas) >= 7
        names = [p["name"] for p in personas]
        assert "sdlc-product-manager" in names

    def test_list_installed_personas_empty_when_dir_missing(self) -> None:
        """list_installed_personas returns empty list when dir does not exist."""
        target = self._make_target(Path("/nonexistent/agents"))
        installer = Installer(target=target)
        personas = installer.list_installed_personas()
        assert personas == []

    def test_list_installed_personas_ignores_non_sdlc_files(self, tmp_path: Path) -> None:
        """list_installed_personas only returns sdlc-*.md files."""
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        target = self._make_target(persona_target)
        installer = Installer(target=target)
        (persona_target / "sdlc-architect.md").write_text("# arch")
        (persona_target / "custom-agent.md").write_text("# custom")
        (persona_target / "readme.md").write_text("# readme")
        personas = installer.list_installed_personas()
        assert len(personas) == 1
        assert personas[0]["name"] == "sdlc-architect"

    def test_verify_persona_integrity_pass(self, tmp_path: Path) -> None:
        """verify_persona_integrity returns True when files match source."""
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        target = self._make_target(persona_target)
        installer = Installer(target=target)
        installer.install_personas(force=True)
        results = installer.verify_persona_integrity()
        assert all(results.values())
        assert len(results) >= 7

    def test_verify_persona_integrity_fail_modified(self, tmp_path: Path) -> None:
        """verify_persona_integrity detects modified files."""
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        target = self._make_target(persona_target)
        installer = Installer(target=target)
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
        persona_target = tmp_path / "agents"
        persona_target.mkdir()
        target = self._make_target(persona_target)
        installer = Installer(target=target)
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
        """install_personas creates agents_dir directory if it does not exist."""
        persona_target = tmp_path / "new_agents_dir"
        assert not persona_target.exists()
        target = self._make_target(persona_target)
        installer = Installer(target=target)
        installed = installer.install_personas()
        assert persona_target.exists()
        assert len(installed) >= 7

    def test_install_output_shows_persona_count(self, runner: CliRunner) -> None:
        """CLI install output includes persona deployment count."""
        with patch("a_sdlc.cli.Installer") as mock_installer_cls:
            mock_installer = mock_installer_cls.return_value
            mock_installer.install.return_value = ["init", "scan", "help"]
            mock_installer.list_installed_personas.return_value = [
                {"name": f"sdlc-persona-{i}", "file": f"sdlc-persona-{i}.md"} for i in range(7)
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

    def test_install_agent_teams_preserves_existing_env(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Agent Teams config preserves existing environment variables."""
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(json.dumps({"environment": {"MY_EXISTING_VAR": "keep-me"}}))

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

    def test_install_agent_teams_handles_settings_error(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Agent Teams config shows warning when settings.json cannot be written."""
        with (
            patch("a_sdlc.cli.Installer") as MockInstaller,  # noqa: N806
            patch(
                "a_sdlc.mcp_setup.CLAUDE_SETTINGS_PATH",
                tmp_path / "nonexistent_dir" / "settings.json",
            ),
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
        underscore_files = [f.name for f in target_dir.glob("_*.md")]
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
        return template_path.read_text(encoding="utf-8")

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
                "Section A" in content or "Section B" in content or "Section C" in content
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
            assert "--solo" in content, f"{template_name} missing --solo bypass flag reference"

    def test_lightweight_templates_have_persona_panel_reference(self) -> None:
        """Lightweight templates must contain Persona Panel references."""
        for template_name in self.LIGHTWEIGHT_TEMPLATES:
            content = self._read_template(template_name)
            has_persona_panel = "Persona Panel" in content or "persona panel" in content
            assert has_persona_panel, f"{template_name} missing Persona Panel reference"

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
                "round_table_enabled = false" in content or "round_table_enabled = False" in content
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


class TestBuildExtensionCommand:
    """Tests for the build-extension CLI command."""

    def test_build_extension_exists(self, runner: CliRunner) -> None:
        """Command is registered and shows help."""
        result = runner.invoke(main, ["build-extension", "--help"])
        assert result.exit_code == 0
        assert "Gemini CLI extension" in result.output

    def test_build_extension_default_output(self, runner: CliRunner, tmp_path: Path) -> None:
        """Command calls build_extension_dir with resolved default path."""
        with patch("a_sdlc.gemini_extension.build_extension_dir") as mock_build:
            mock_build.return_value = tmp_path
            # Create expected structure
            (tmp_path / "commands" / "sdlc").mkdir(parents=True)
            (tmp_path / "commands" / "sdlc" / "init.toml").touch()
            (tmp_path / "commands" / "sdlc" / "prd-generate.toml").touch()
            (tmp_path / "gemini-extension.json").touch()

            result = runner.invoke(main, ["build-extension"])
            assert result.exit_code == 0
            assert "Extension built successfully" in result.output
            assert "2 TOML files" in result.output

    def test_build_extension_custom_output(self, runner: CliRunner, tmp_path: Path) -> None:
        """--output option controls output directory."""
        custom_dir = tmp_path / "custom-ext"
        with patch("a_sdlc.gemini_extension.build_extension_dir") as mock_build:
            mock_build.return_value = custom_dir
            custom_dir.mkdir(parents=True)
            (custom_dir / "commands" / "sdlc").mkdir(parents=True)
            (custom_dir / "gemini-extension.json").touch()

            result = runner.invoke(main, ["build-extension", "--output", str(custom_dir)])
            assert result.exit_code == 0
            mock_build.assert_called_once()
            call_arg = mock_build.call_args[0][0]
            assert str(custom_dir) in str(call_arg)

    def test_build_extension_shows_install_instruction(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Output includes gemini extensions install command."""
        with patch("a_sdlc.gemini_extension.build_extension_dir") as mock_build:
            mock_build.return_value = tmp_path
            (tmp_path / "commands" / "sdlc").mkdir(parents=True)
            (tmp_path / "gemini-extension.json").touch()

            result = runner.invoke(main, ["build-extension"])
            assert result.exit_code == 0
            assert "gemini extensions install" in result.output

    def test_build_extension_handles_error(self, runner: CliRunner) -> None:
        """Command handles errors gracefully."""
        with patch(
            "a_sdlc.gemini_extension.build_extension_dir", side_effect=RuntimeError("test error")
        ):
            result = runner.invoke(main, ["build-extension"])
            assert result.exit_code != 0
            assert "Error building extension" in result.output


# ---------------------------------------------------------------------------
# Multi-CLI target integration
# ---------------------------------------------------------------------------


class TestCLITargetIntegration:
    """Tests for --target CLI option on install and uninstall commands."""

    @pytest.fixture(autouse=True)
    def auto_mock_doctor(self):
        """Mock slow checks for all tests in this class."""
        with (
            patch("a_sdlc.cli.verify_setup", return_value={"ready": False}),
            patch("a_sdlc.cli.check_docker_available", return_value=False),
            patch("a_sdlc.cli.verify_monitoring_setup", return_value={}),
            patch("a_sdlc.cli.verify_sonarqube_setup", return_value={}),
        ):
            yield

    def test_install_target_claude(self, runner: CliRunner) -> None:
        """Test install --target claude resolves to Claude target."""
        with (
            patch("a_sdlc.cli.resolve_targets", return_value=[CLAUDE_TARGET]) as mock_resolve,
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
        ):
            mock_inst = mock_installer_cls.return_value
            mock_inst.install.return_value = ["init.md"]
            mock_inst.list_installed_personas.return_value = []
            result = runner.invoke(main, ["install", "--target", "claude"])
            assert result.exit_code == 0
            mock_resolve.assert_called_once_with("claude")

    def test_install_target_gemini(self, runner: CliRunner) -> None:
        """Test install --target gemini resolves to Gemini target."""
        with (
            patch("a_sdlc.cli.resolve_targets", return_value=[GEMINI_TARGET]) as mock_resolve,
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
        ):
            mock_inst = mock_installer_cls.return_value
            mock_inst.install.return_value = ["init.toml"]
            mock_inst.list_installed_personas.return_value = []
            result = runner.invoke(main, ["install", "--target", "gemini"])
            assert result.exit_code == 0
            mock_resolve.assert_called_once_with("gemini")

    def test_install_target_auto_default(self, runner: CliRunner) -> None:
        """Test install without --target defaults to auto."""
        with (
            patch("a_sdlc.cli.resolve_targets", return_value=[CLAUDE_TARGET]) as mock_resolve,
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
        ):
            mock_inst = mock_installer_cls.return_value
            mock_inst.install.return_value = ["init.md"]
            mock_inst.list_installed_personas.return_value = []
            result = runner.invoke(main, ["install"])
            assert result.exit_code == 0
            mock_resolve.assert_called_once_with("auto")

    def test_install_no_targets_detected(self, runner: CliRunner) -> None:
        """Test install exits with error when no targets detected."""
        with patch("a_sdlc.cli.resolve_targets", return_value=[]):
            result = runner.invoke(main, ["install"])
            assert result.exit_code != 0
            assert "No supported CLI" in result.output

    def test_install_shows_target_names(self, runner: CliRunner) -> None:
        """Test install output includes target display names."""
        with (
            patch("a_sdlc.cli.resolve_targets", return_value=[CLAUDE_TARGET, GEMINI_TARGET]),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
        ):
            mock_inst = mock_installer_cls.return_value
            mock_inst.install.return_value = ["init.md"]
            mock_inst.list_installed_personas.return_value = []
            result = runner.invoke(main, ["install"])
            assert result.exit_code == 0
            assert "Claude Code" in result.output
            assert "Gemini CLI" in result.output

    def test_uninstall_target_option(self, runner: CliRunner) -> None:
        """Test uninstall --target claude passes targets to build_uninstall_plan."""
        from a_sdlc.uninstall import UninstallPlan, UninstallResult

        with (
            patch("a_sdlc.cli.resolve_targets", return_value=[CLAUDE_TARGET]),
            patch("a_sdlc.uninstall.build_uninstall_plan") as mock_plan,
            patch("a_sdlc.uninstall.execute_uninstall") as mock_exec,
        ):
            mock_plan.return_value = UninstallPlan(
                has_asdlc_mcp=False,
                has_serena_mcp=False,
                has_playwright_mcp=False,
                skill_template_count=0,
                persona_count=0,
                has_data_dir=False,
            )
            mock_exec.return_value = UninstallResult(actions=[], warnings=[], errors=[])
            result = runner.invoke(main, ["uninstall", "--target", "claude", "-y"])
            assert result.exit_code == 0

    def test_doctor_shows_cli_targets(self, runner: CliRunner) -> None:
        """Test doctor command includes CLI Targets check."""
        with (
            patch("a_sdlc.cli.detect_targets", return_value=[CLAUDE_TARGET]),
            patch("a_sdlc.cli.Installer") as mock_installer_cls,
            patch("a_sdlc.cli.get_plugin_manager") as mock_pm,
            patch("a_sdlc.cli.get_claude_settings_path", return_value=Path("/tmp/fake.json")),
            patch("a_sdlc.playwright_setup.verify_setup", return_value={"ready": False}),
        ):
            mock_inst = mock_installer_cls.return_value
            mock_inst.check_template_version.return_value = (True, "0.6.0", "0.6.0")
            mock_inst.list_installed_personas.return_value = []
            mock_pm.return_value.list_plugins.return_value = []
            result = runner.invoke(main, ["doctor"])
            assert "CLI Targets" in result.output


class TestQualityCommands:
    """Tests for the quality command group."""

    def test_quality_group_exists(self, runner: CliRunner) -> None:
        """Test that the quality command group is registered."""
        result = runner.invoke(main, ["quality", "--help"])
        assert result.exit_code == 0
        assert "coverage" in result.output
        assert "verify" in result.output
        assert "gaps" in result.output

    def test_quality_coverage_no_project(self, runner: CliRunner) -> None:
        """Test coverage subcommand with no project."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_cls.return_value.get_most_recent_project.return_value = None
            result = runner.invoke(main, ["quality", "coverage"])
            assert result.exit_code == 0
            assert "No project found" in result.output

    def test_quality_coverage_with_prd(self, runner: CliRunner) -> None:
        """Test coverage subcommand with a specific PRD."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_storage = mock_cls.return_value
            mock_storage.get_most_recent_project.return_value = {"id": "PROJ"}
            mock_storage.get_coverage_stats.return_value = {
                "total": 10,
                "linked": 8,
                "orphaned": 2,
                "by_type": {},
            }
            result = runner.invoke(main, ["quality", "coverage", "PROJ-P0001"])
            assert result.exit_code == 0
            assert "Requirement Coverage" in result.output
            assert "PROJ-P0001" in result.output

    def test_quality_coverage_all_prds(self, runner: CliRunner) -> None:
        """Test coverage subcommand listing all PRDs."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_storage = mock_cls.return_value
            mock_storage.get_most_recent_project.return_value = {"id": "PROJ"}
            mock_storage.list_prds.return_value = [
                {"id": "PROJ-P0001"},
                {"id": "PROJ-P0002"},
            ]
            mock_storage.get_coverage_stats.return_value = {
                "total": 5,
                "linked": 5,
                "orphaned": 0,
                "by_type": {},
            }
            result = runner.invoke(main, ["quality", "coverage"])
            assert result.exit_code == 0
            assert "PROJ-P0001" in result.output
            assert "PROJ-P0002" in result.output

    def test_quality_verify_no_project(self, runner: CliRunner) -> None:
        """Test verify subcommand with no project."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_cls.return_value.get_most_recent_project.return_value = None
            result = runner.invoke(main, ["quality", "verify"])
            assert result.exit_code == 0
            assert "No project found" in result.output

    def test_quality_verify_with_prd(self, runner: CliRunner) -> None:
        """Test verify subcommand shows AC verification table."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_storage = mock_cls.return_value
            mock_storage.get_most_recent_project.return_value = {"id": "PROJ"}
            mock_storage.get_requirements.return_value = [
                {
                    "id": "REQ-001",
                    "summary": "User can login",
                    "depth": "behavioral",
                    "req_number": "AC-001",
                },
            ]
            mock_storage.get_requirement_tasks.return_value = [{"id": "T001"}]
            mock_storage.get_ac_verifications.return_value = [
                {"requirement_id": "REQ-001", "evidence_type": "test"},
            ]
            result = runner.invoke(main, ["quality", "verify", "PROJ-P0001"])
            assert result.exit_code == 0
            assert "AC Verification Status" in result.output
            assert "REQ-001" in result.output
            assert "Verified" in result.output

    def test_quality_gaps_no_project(self, runner: CliRunner) -> None:
        """Test gaps subcommand with no project."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_cls.return_value.get_most_recent_project.return_value = None
            result = runner.invoke(main, ["quality", "gaps"])
            assert result.exit_code == 0
            assert "No project found" in result.output

    def test_quality_gaps_pass(self, runner: CliRunner) -> None:
        """Test gaps subcommand returns PASS when fully covered."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_storage = mock_cls.return_value
            mock_storage.get_most_recent_project.return_value = {"id": "PROJ"}
            mock_storage.list_sprints.return_value = [
                {"id": "PROJ-S0001", "status": "active"},
            ]
            mock_storage.get_sprint_prds.return_value = [{"id": "PROJ-P0001"}]
            mock_storage.get_coverage_stats.return_value = {
                "total": 5,
                "linked": 5,
                "orphaned": 0,
            }
            mock_storage.get_orphaned_requirements.return_value = []
            mock_storage.get_requirements.return_value = []
            result = runner.invoke(main, ["quality", "gaps"])
            assert result.exit_code == 0
            assert "PASS" in result.output

    def test_quality_gaps_fail(self, runner: CliRunner) -> None:
        """Test gaps subcommand returns FAIL when orphaned requirements exist."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_storage = mock_cls.return_value
            mock_storage.get_most_recent_project.return_value = {"id": "PROJ"}
            mock_storage.list_sprints.return_value = [
                {"id": "PROJ-S0001", "status": "active"},
            ]
            mock_storage.get_sprint_prds.return_value = [{"id": "PROJ-P0001"}]
            mock_storage.get_coverage_stats.return_value = {
                "total": 5,
                "linked": 3,
                "orphaned": 2,
            }
            mock_storage.get_orphaned_requirements.return_value = [
                {"id": "R1", "req_number": "FR-001", "summary": "Missing", "prd_id": "PROJ-P0001"},
            ]
            mock_storage.get_requirements.return_value = []
            result = runner.invoke(main, ["quality", "gaps"])
            assert result.exit_code == 0
            assert "FAIL" in result.output
            assert "Orphaned" in result.output

    def test_quality_reclassify(self, runner: CliRunner) -> None:
        """Test reclassify subcommand updates depth."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_storage = mock_cls.return_value
            mock_storage.get_requirement.return_value = {
                "id": "REQ-001",
                "prd_id": "P001",
                "req_type": "FR",
                "req_number": "FR-001",
                "summary": "Test req",
                "depth": "structural",
            }
            result = runner.invoke(
                main, ["quality", "reclassify", "REQ-001", "--depth", "behavioral"]
            )
            assert result.exit_code == 0
            assert "structural -> behavioral" in result.output
            mock_storage.upsert_requirement.assert_called_once()

    def test_quality_reclassify_not_found(self, runner: CliRunner) -> None:
        """Test reclassify when requirement does not exist."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_cls.return_value.get_requirement.return_value = None
            result = runner.invoke(
                main, ["quality", "reclassify", "NOPE", "--depth", "behavioral"]
            )
            assert result.exit_code == 0
            assert "not found" in result.output

    def test_quality_skip_challenge(self, runner: CliRunner) -> None:
        """Test skip-challenge records audit log entry."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_storage = mock_cls.return_value
            mock_storage.get_most_recent_project.return_value = {"id": "PROJ"}
            mock_storage.update_challenge_round.return_value = {"status": "skipped"}
            result = runner.invoke(
                main,
                ["quality", "skip-challenge", "prd:PROJ-P0001:1", "--reason", "time"],
            )
            assert result.exit_code == 0
            assert "skipped" in result.output
            mock_storage.append_audit_log.assert_called_once()
            call_kwargs = mock_storage.append_audit_log.call_args
            assert call_kwargs[0][1] == "challenge_skipped"

    def test_quality_skip_challenge_bad_id(self, runner: CliRunner) -> None:
        """Test skip-challenge with malformed ID."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_cls.return_value.get_most_recent_project.return_value = {"id": "PROJ"}
            result = runner.invoke(
                main,
                ["quality", "skip-challenge", "bad-id", "--reason", "test"],
            )
            assert result.exit_code == 0
            assert "Invalid challenge ID" in result.output

    def test_quality_resolve_escalation(self, runner: CliRunner) -> None:
        """Test resolve-escalation updates round and logs."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_storage = mock_cls.return_value
            mock_storage.get_most_recent_project.return_value = {"id": "PROJ"}
            mock_storage.update_challenge_round.return_value = {"status": "resolved"}
            result = runner.invoke(
                main,
                [
                    "quality",
                    "resolve-escalation",
                    "prd:PROJ-P0001:1",
                    "--resolution",
                    "accepted",
                ],
            )
            assert result.exit_code == 0
            assert "resolved" in result.output
            mock_storage.append_audit_log.assert_called_once()

    def test_quality_waive(self, runner: CliRunner) -> None:
        """Test waive records audit log with reason."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_storage = mock_cls.return_value
            mock_storage.get_most_recent_project.return_value = {"id": "PROJ"}
            mock_storage.get_requirement.return_value = {
                "id": "REQ-001",
                "req_number": "FR-001",
                "summary": "Test",
            }
            result = runner.invoke(
                main,
                ["quality", "waive", "REQ-001", "--reason", "deferred"],
            )
            assert result.exit_code == 0
            assert "waived" in result.output
            mock_storage.append_audit_log.assert_called_once()
            call_args = mock_storage.append_audit_log.call_args
            assert call_args[1]["details"]["reason"] == "deferred"

    def test_quality_waive_not_found(self, runner: CliRunner) -> None:
        """Test waive when requirement does not exist."""
        with patch("a_sdlc.storage.HybridStorage") as mock_cls:
            mock_storage = mock_cls.return_value
            mock_storage.get_most_recent_project.return_value = {"id": "PROJ"}
            mock_storage.get_requirement.return_value = None
            result = runner.invoke(
                main,
                ["quality", "waive", "NOPE", "--reason", "test"],
            )
            assert result.exit_code == 0
            assert "not found" in result.output
