"""Tests for uninstall module."""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from a_sdlc.cli_targets import CLITarget
from a_sdlc.uninstall import (
    UninstallPlan,
    UninstallResult,
    _remove_asdlc_mcp,
    _remove_data_dir,
    _remove_monitoring,
    _remove_personas,
    _remove_settings_entries,
    _remove_skill_templates,
    build_uninstall_plan,
    execute_uninstall,
)


def _make_target(tmp_path: Path, name: str = "claude") -> CLITarget:
    """Create a CLITarget pointing at tmp_path for isolated testing."""
    return CLITarget(
        name=name,
        display_name="Claude Code" if name == "claude" else "Gemini CLI",
        home_dir=tmp_path / f".{name}",
        mcp_config_path=tmp_path / f"{name}.json",
        settings_path=tmp_path / f"{name}-settings.json",
        commands_dir=tmp_path / "commands" / "sdlc",
        agents_dir=tmp_path / "agents",
        context_file="CLAUDE.md" if name == "claude" else "GEMINI.md",
    )

# ---------------------------------------------------------------------------
# UninstallPlan / UninstallResult dataclasses
# ---------------------------------------------------------------------------


def test_uninstall_plan_defaults():
    """Plan has sane defaults."""
    plan = UninstallPlan()
    assert plan.has_asdlc_mcp is False
    assert plan.has_serena_mcp is False
    assert plan.has_playwright_mcp is False
    assert plan.remove_serena is False
    assert plan.remove_playwright is False
    assert plan.skill_template_count == 0
    assert plan.has_monitoring_hook is False
    assert plan.monitoring_hook_indices == []
    assert plan.managed_env_keys == []
    assert plan.has_monitoring_dir is False
    assert plan.has_data_dir is False
    assert plan.include_data is False


def test_uninstall_plan_persona_defaults():
    """UninstallPlan has correct persona field defaults."""
    plan = UninstallPlan()
    assert plan.persona_dir is None
    assert plan.persona_count == 0


def test_uninstall_result_success():
    """Result is success when no errors."""
    result = UninstallResult()
    assert result.success is True

    result.actions.append("did something")
    assert result.success is True

    result.warnings.append("something minor")
    assert result.success is True


def test_uninstall_result_failure():
    """Result is failure when errors present."""
    result = UninstallResult()
    result.errors.append("something broke")
    assert result.success is False


# ---------------------------------------------------------------------------
# build_uninstall_plan
# ---------------------------------------------------------------------------


def test_build_plan_empty_system(tmp_path):
    """Plan on a clean system finds nothing to remove."""
    target = _make_target(tmp_path)

    with (
        patch("a_sdlc.uninstall.Installer") as MockInstaller,  # noqa: N806
        patch("a_sdlc.uninstall.MONITORING_DIR", tmp_path / "monitoring"),
        patch("a_sdlc.core.database.get_data_dir", return_value=tmp_path / "data"),
    ):
        mock_inst = MockInstaller.return_value
        mock_inst.target_dir = tmp_path / "commands" / "sdlc"
        mock_inst.target_dir.mkdir(parents=True, exist_ok=True)

        plan = build_uninstall_plan(targets=[target])
        assert plan.has_asdlc_mcp is False
        assert plan.has_serena_mcp is False
        assert plan.skill_template_count == 0
        assert plan.has_monitoring_hook is False
        assert plan.has_monitoring_dir is False
        assert plan.has_data_dir is False


def test_build_plan_full_system(tmp_path):
    """Plan detects all installed components."""
    target = _make_target(tmp_path)

    # Create mcp_config_path with asdlc MCP
    target.mcp_config_path.write_text(json.dumps({
        "mcpServers": {"asdlc": {"command": "uvx", "args": ["a-sdlc", "serve"]}}
    }))

    # Create settings_path with serena, playwright, hook, env
    target.settings_path.write_text(json.dumps({
        "mcpServers": {"serena": {"command": "uvx"}, "playwright": {"command": "npx"}},
        "hooks": {
            "Stop": [
                {"matcher": "", "hooks": [{"type": "command", "command": "uv run langfuse-hook.py"}]}
            ]
        },
        "environment": {
            "OTEL_METRICS_EXPORTER": "otlp",
            "LANGFUSE_SECRET_KEY": "sk-lf-test",
        },
    }))

    # Create skill template dir with files
    skill_dir = tmp_path / "commands" / "sdlc"
    skill_dir.mkdir(parents=True)
    (skill_dir / "init.md").write_text("# init")
    (skill_dir / "scan.md").write_text("# scan")

    # Create monitoring dir
    monitoring_dir = tmp_path / "monitoring"
    monitoring_dir.mkdir()

    # Create data dir
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    with (
        patch("a_sdlc.uninstall.Installer") as MockInstaller,  # noqa: N806
        patch("a_sdlc.uninstall.MONITORING_DIR", monitoring_dir),
        patch("a_sdlc.core.database.get_data_dir", return_value=data_dir),
    ):
        mock_inst = MockInstaller.return_value
        mock_inst.target_dir = skill_dir

        plan = build_uninstall_plan(include_data=True, targets=[target])

        assert plan.has_asdlc_mcp is True
        assert plan.has_serena_mcp is True
        assert plan.has_playwright_mcp is True
        assert plan.remove_serena is False
        assert plan.remove_playwright is False
        assert plan.skill_template_count == 2
        assert plan.has_monitoring_hook is True
        assert plan.monitoring_hook_indices == [0]
        assert len(plan.managed_env_keys) == 2
        assert plan.has_monitoring_dir is True
        assert plan.has_data_dir is True
        assert plan.include_data is True


def test_build_plan_malformed_claude_json(tmp_path):
    """Plan handles malformed mcp_config_path gracefully."""
    target = _make_target(tmp_path)
    target.mcp_config_path.write_text("not json")

    with (
        patch("a_sdlc.uninstall.Installer") as MockInstaller,  # noqa: N806
        patch("a_sdlc.uninstall.MONITORING_DIR", tmp_path / "mon"),
        patch("a_sdlc.core.database.get_data_dir", return_value=tmp_path / "data"),
    ):
        mock_inst = MockInstaller.return_value
        mock_inst.target_dir = tmp_path / "cmds"
        mock_inst.target_dir.mkdir(parents=True)

        plan = build_uninstall_plan(targets=[target])
        assert plan.has_asdlc_mcp is False


def test_build_plan_detects_personas(tmp_path):
    """build_uninstall_plan() detects persona files in agents dir."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "sdlc-architect.md").write_text("# arch")
    (agents_dir / "sdlc-qa-engineer.md").write_text("# qa")
    (agents_dir / "custom-agent.md").write_text("# custom")  # Should NOT be counted

    target = _make_target(tmp_path)
    # target.agents_dir is already tmp_path / "agents" from _make_target

    with (
        patch("a_sdlc.uninstall.Installer") as MockInstaller,  # noqa: N806
        patch("a_sdlc.uninstall.MONITORING_DIR", tmp_path / "mon"),
        patch("a_sdlc.core.database.get_data_dir", return_value=tmp_path / "data"),
    ):
        mock_inst = MockInstaller.return_value
        mock_inst.target_dir = tmp_path / "cmds"
        mock_inst.target_dir.mkdir(parents=True)

        plan = build_uninstall_plan(targets=[target])
        assert plan.persona_count == 2  # Only sdlc-*.md files
        assert plan.persona_dir == agents_dir


def test_build_plan_no_personas_when_dir_missing(tmp_path):
    """build_uninstall_plan() reports 0 personas when agents dir missing."""
    # Create target with nonexistent agents_dir
    target = CLITarget(
        name="claude",
        display_name="Claude Code",
        home_dir=tmp_path / ".claude",
        mcp_config_path=tmp_path / "claude.json",
        settings_path=tmp_path / "claude-settings.json",
        commands_dir=tmp_path / "commands" / "sdlc",
        agents_dir=tmp_path / "no_agents",
        context_file="CLAUDE.md",
    )

    with (
        patch("a_sdlc.uninstall.Installer") as MockInstaller,  # noqa: N806
        patch("a_sdlc.uninstall.MONITORING_DIR", tmp_path / "mon"),
        patch("a_sdlc.core.database.get_data_dir", return_value=tmp_path / "data"),
    ):
        mock_inst = MockInstaller.return_value
        mock_inst.target_dir = tmp_path / "cmds"
        mock_inst.target_dir.mkdir(parents=True)

        plan = build_uninstall_plan(targets=[target])
        assert plan.persona_count == 0
        assert plan.persona_dir is None


# ---------------------------------------------------------------------------
# _remove_asdlc_mcp
# ---------------------------------------------------------------------------


def test_remove_asdlc_mcp_present(tmp_path):
    """Removes asdlc key from target mcp_config_path."""
    target = _make_target(tmp_path)
    target.mcp_config_path.write_text(json.dumps({
        "mcpServers": {
            "asdlc": {"command": "uvx"},
            "other": {"command": "node"},
        }
    }))

    plan = UninstallPlan(has_asdlc_mcp=True, targets=[target])
    result = UninstallResult()

    _remove_asdlc_mcp(plan, result)

    assert len(result.actions) == 1
    assert len(result.errors) == 0

    data = json.loads(target.mcp_config_path.read_text())
    assert "asdlc" not in data["mcpServers"]
    assert "other" in data["mcpServers"]


def test_remove_asdlc_mcp_not_present():
    """Skips when asdlc not present."""
    plan = UninstallPlan(has_asdlc_mcp=False)
    result = UninstallResult()

    _remove_asdlc_mcp(plan, result)
    assert len(result.actions) == 0
    assert len(result.errors) == 0


def test_remove_asdlc_mcp_io_error(tmp_path):
    """Records error on IO failure."""
    target = _make_target(tmp_path)
    # Create an mcp_config_path that exists but contains invalid JSON
    target.mcp_config_path.write_text("not json")

    plan = UninstallPlan(has_asdlc_mcp=True, targets=[target])
    result = UninstallResult()

    _remove_asdlc_mcp(plan, result)

    assert len(result.errors) == 1


# ---------------------------------------------------------------------------
# _remove_settings_entries
# ---------------------------------------------------------------------------


def test_remove_settings_serena_only(tmp_path):
    """Removes only serena MCP from settings."""
    settings = {
        "mcpServers": {"serena": {"command": "uvx"}, "context7": {"command": "npx"}},
    }

    plan = UninstallPlan(has_serena_mcp=True, remove_serena=True)
    result = UninstallResult()

    saved_settings = {}

    def mock_save(s):
        saved_settings.update(s)

    with (
        patch("a_sdlc.uninstall.load_claude_settings", return_value=settings),
        patch("a_sdlc.uninstall.save_claude_settings", side_effect=mock_save),
    ):
        _remove_settings_entries(plan, result)

    assert "serena" not in saved_settings["mcpServers"]
    assert "context7" in saved_settings["mcpServers"]
    assert any("serena" in a for a in result.actions)


def test_remove_settings_serena_kept_when_not_opted_in():
    """Serena is preserved when user declines removal."""
    settings = {
        "mcpServers": {"serena": {"command": "uvx"}, "context7": {"command": "npx"}},
    }

    plan = UninstallPlan(has_serena_mcp=True, remove_serena=False)
    result = UninstallResult()

    with (
        patch("a_sdlc.uninstall.load_claude_settings", return_value=settings),
        patch("a_sdlc.uninstall.save_claude_settings") as mock_save,
    ):
        _remove_settings_entries(plan, result)

    mock_save.assert_not_called()
    assert not any("serena" in a for a in result.actions)


def test_remove_settings_playwright(tmp_path):
    """Removes playwright MCP when user opts in."""
    settings = {
        "mcpServers": {"playwright": {"command": "npx"}, "context7": {"command": "npx"}},
    }

    plan = UninstallPlan(has_playwright_mcp=True, remove_playwright=True)
    result = UninstallResult()

    saved_settings = {}

    def mock_save(s):
        saved_settings.update(s)

    with (
        patch("a_sdlc.uninstall.load_claude_settings", return_value=settings),
        patch("a_sdlc.uninstall.save_claude_settings", side_effect=mock_save),
    ):
        _remove_settings_entries(plan, result)

    assert "playwright" not in saved_settings["mcpServers"]
    assert "context7" in saved_settings["mcpServers"]
    assert any("playwright" in a for a in result.actions)


def test_remove_settings_hooks(tmp_path):
    """Removes only langfuse hook entries, preserves others."""
    settings = {
        "hooks": {
            "Stop": [
                {"matcher": "", "hooks": [{"type": "command", "command": "other-hook.sh"}]},
                {"matcher": "", "hooks": [{"type": "command", "command": "uv run langfuse-hook.py"}]},
            ]
        },
    }

    plan = UninstallPlan(has_monitoring_hook=True, monitoring_hook_indices=[1])
    result = UninstallResult()

    saved_settings = {}

    def mock_save(s):
        saved_settings.update(s)

    with (
        patch("a_sdlc.uninstall.load_claude_settings", return_value=settings),
        patch("a_sdlc.uninstall.save_claude_settings", side_effect=mock_save),
    ):
        _remove_settings_entries(plan, result)

    assert len(saved_settings["hooks"]["Stop"]) == 1
    assert "other-hook.sh" in saved_settings["hooks"]["Stop"][0]["hooks"][0]["command"]


def test_remove_settings_hooks_cleans_empty_structure():
    """Removes hooks and Stop key when all hooks are removed."""
    settings = {
        "hooks": {
            "Stop": [
                {"matcher": "", "hooks": [{"type": "command", "command": "uv run langfuse-hook.py"}]},
            ]
        },
    }

    plan = UninstallPlan(has_monitoring_hook=True, monitoring_hook_indices=[0])
    result = UninstallResult()

    saved_settings = {}

    def mock_save(s):
        saved_settings.update(s)

    with (
        patch("a_sdlc.uninstall.load_claude_settings", return_value=settings),
        patch("a_sdlc.uninstall.save_claude_settings", side_effect=mock_save),
    ):
        _remove_settings_entries(plan, result)

    assert "hooks" not in saved_settings


def test_remove_settings_env_vars():
    """Removes managed env vars, preserves others."""
    settings = {
        "environment": {
            "OTEL_METRICS_EXPORTER": "otlp",
            "LANGFUSE_SECRET_KEY": "sk-lf-test",
            "MY_CUSTOM_VAR": "keep-me",
        },
    }

    plan = UninstallPlan(
        managed_env_keys=["OTEL_METRICS_EXPORTER", "LANGFUSE_SECRET_KEY"]
    )
    result = UninstallResult()

    saved_settings = {}

    def mock_save(s):
        saved_settings.update(s)

    with (
        patch("a_sdlc.uninstall.load_claude_settings", return_value=settings),
        patch("a_sdlc.uninstall.save_claude_settings", side_effect=mock_save),
    ):
        _remove_settings_entries(plan, result)

    assert "OTEL_METRICS_EXPORTER" not in saved_settings["environment"]
    assert "LANGFUSE_SECRET_KEY" not in saved_settings["environment"]
    assert saved_settings["environment"]["MY_CUSTOM_VAR"] == "keep-me"


def test_remove_settings_env_cleans_empty():
    """Removes environment key when all vars removed."""
    settings = {
        "environment": {"OTEL_METRICS_EXPORTER": "otlp"},
    }

    plan = UninstallPlan(managed_env_keys=["OTEL_METRICS_EXPORTER"])
    result = UninstallResult()

    saved_settings = {}

    def mock_save(s):
        saved_settings.update(s)

    with (
        patch("a_sdlc.uninstall.load_claude_settings", return_value=settings),
        patch("a_sdlc.uninstall.save_claude_settings", side_effect=mock_save),
    ):
        _remove_settings_entries(plan, result)

    assert "environment" not in saved_settings


def test_remove_settings_empty_settings():
    """No-op when settings are empty."""
    plan = UninstallPlan(has_serena_mcp=True)
    result = UninstallResult()

    with patch("a_sdlc.uninstall.load_claude_settings", return_value={}):
        _remove_settings_entries(plan, result)

    assert len(result.actions) == 0
    assert len(result.errors) == 0


def test_remove_settings_save_failure():
    """Records error when save fails."""
    settings = {
        "mcpServers": {"serena": {"command": "uvx"}},
    }

    plan = UninstallPlan(has_serena_mcp=True, remove_serena=True)
    result = UninstallResult()

    with (
        patch("a_sdlc.uninstall.load_claude_settings", return_value=settings),
        patch(
            "a_sdlc.uninstall.save_claude_settings",
            side_effect=OSError("disk full"),
        ),
    ):
        _remove_settings_entries(plan, result)

    assert len(result.errors) == 1
    assert "disk full" in result.errors[0]


# ---------------------------------------------------------------------------
# _remove_skill_templates
# ---------------------------------------------------------------------------


def test_remove_skill_templates(tmp_path):
    """Calls Installer.uninstall() and records action."""
    plan = UninstallPlan(
        skill_template_dir=tmp_path / "sdlc",
        skill_template_count=5,
    )
    result = UninstallResult()

    with patch("a_sdlc.uninstall.Installer") as MockInstaller:  # noqa: N806
        MockInstaller.return_value.uninstall.return_value = 5
        _remove_skill_templates(plan, result)

    assert any("5 skill template" in a for a in result.actions)


def test_remove_skill_templates_none():
    """Skips when no templates."""
    plan = UninstallPlan(skill_template_dir=None, skill_template_count=0)
    result = UninstallResult()

    _remove_skill_templates(plan, result)
    assert len(result.actions) == 0


def test_remove_skill_templates_error():
    """Records error on exception."""
    plan = UninstallPlan(
        skill_template_dir=Path("/some/dir"),
        skill_template_count=3,
    )
    result = UninstallResult()

    with patch("a_sdlc.uninstall.Installer") as MockInstaller:  # noqa: N806
        MockInstaller.return_value.uninstall.side_effect = OSError("perm denied")
        _remove_skill_templates(plan, result)

    assert len(result.errors) == 1


# ---------------------------------------------------------------------------
# _remove_personas
# ---------------------------------------------------------------------------


def test_remove_personas_delegates_to_installer():
    """_remove_personas delegates to Installer.uninstall_personas()."""
    plan = UninstallPlan(
        persona_dir=Path("/some/agents"),
        persona_count=5,
    )
    result = UninstallResult()

    with patch("a_sdlc.uninstall.Installer") as MockInstaller:  # noqa: N806
        MockInstaller.return_value.uninstall_personas.return_value = 5
        _remove_personas(plan, result)

    assert any("5 persona" in a for a in result.actions)


def test_remove_personas_skips_when_none():
    """_remove_personas no-ops when persona_count is 0."""
    plan = UninstallPlan(persona_dir=None, persona_count=0)
    result = UninstallResult()

    _remove_personas(plan, result)
    assert len(result.actions) == 0


def test_remove_personas_handles_error():
    """_remove_personas records error on failure."""
    plan = UninstallPlan(
        persona_dir=Path("/some/agents"),
        persona_count=3,
    )
    result = UninstallResult()

    with patch("a_sdlc.uninstall.Installer") as MockInstaller:  # noqa: N806
        MockInstaller.return_value.uninstall_personas.side_effect = OSError("perm denied")
        _remove_personas(plan, result)

    assert len(result.errors) == 1
    assert "persona" in result.errors[0].lower()


def test_remove_personas_skips_when_dir_set_but_count_zero():
    """_remove_personas no-ops when persona_dir is set but count is 0."""
    plan = UninstallPlan(persona_dir=Path("/some/agents"), persona_count=0)
    result = UninstallResult()

    _remove_personas(plan, result)
    assert len(result.actions) == 0


# ---------------------------------------------------------------------------
# _remove_monitoring
# ---------------------------------------------------------------------------


def test_remove_monitoring_with_docker(tmp_path):
    """Stops Docker and removes monitoring dir."""
    monitoring_dir = tmp_path / "monitoring"
    monitoring_dir.mkdir()
    (monitoring_dir / "docker-compose.yaml").write_text("version: '3'")

    plan = UninstallPlan(has_monitoring_dir=True, monitoring_dir=monitoring_dir)
    result = UninstallResult()

    with (
        patch("a_sdlc.uninstall.MONITORING_DIR", monitoring_dir),
        patch("a_sdlc.uninstall.shutil.which", return_value="/usr/bin/docker"),
        patch("a_sdlc.uninstall.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        _remove_monitoring(plan, result)

    mock_run.assert_called_once()
    assert not monitoring_dir.exists()
    assert any("Stopped" in a for a in result.actions)
    assert any("Removed monitoring" in a for a in result.actions)


def test_remove_monitoring_no_docker(tmp_path):
    """Removes monitoring dir even without Docker."""
    monitoring_dir = tmp_path / "monitoring"
    monitoring_dir.mkdir()

    plan = UninstallPlan(has_monitoring_dir=True, monitoring_dir=monitoring_dir)
    result = UninstallResult()

    with (
        patch("a_sdlc.uninstall.MONITORING_DIR", monitoring_dir),
        patch("a_sdlc.uninstall.shutil.which", return_value=None),
    ):
        _remove_monitoring(plan, result)

    assert not monitoring_dir.exists()
    assert any("Removed monitoring" in a for a in result.actions)


def test_remove_monitoring_docker_timeout(tmp_path):
    """Warns on Docker timeout, still removes dir."""
    monitoring_dir = tmp_path / "monitoring"
    monitoring_dir.mkdir()
    (monitoring_dir / "docker-compose.yaml").write_text("version: '3'")

    plan = UninstallPlan(has_monitoring_dir=True, monitoring_dir=monitoring_dir)
    result = UninstallResult()

    with (
        patch("a_sdlc.uninstall.MONITORING_DIR", monitoring_dir),
        patch("a_sdlc.uninstall.shutil.which", return_value="/usr/bin/docker"),
        patch(
            "a_sdlc.uninstall.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=60),
        ),
    ):
        _remove_monitoring(plan, result)

    assert not monitoring_dir.exists()
    assert len(result.warnings) == 1


def test_remove_monitoring_not_present():
    """Skips when no monitoring dir."""
    plan = UninstallPlan(has_monitoring_dir=False)
    result = UninstallResult()

    _remove_monitoring(plan, result)
    assert len(result.actions) == 0


# ---------------------------------------------------------------------------
# _remove_data_dir
# ---------------------------------------------------------------------------


def test_remove_data_dir(tmp_path):
    """Removes entire data directory."""
    data_dir = tmp_path / ".a-sdlc"
    data_dir.mkdir()
    (data_dir / "data.db").write_text("fake db")
    (data_dir / "content").mkdir()

    plan = UninstallPlan(has_data_dir=True, data_dir=data_dir, include_data=True)
    result = UninstallResult()

    _remove_data_dir(plan, result)

    assert not data_dir.exists()
    assert any("Removed data directory" in a for a in result.actions)


def test_remove_data_dir_not_present():
    """Skips when data dir does not exist."""
    plan = UninstallPlan(has_data_dir=False, data_dir=None)
    result = UninstallResult()

    _remove_data_dir(plan, result)
    assert len(result.actions) == 0


def test_remove_data_dir_error(tmp_path):
    """Records error on removal failure."""
    plan = UninstallPlan(has_data_dir=True, data_dir=tmp_path / "nope")
    result = UninstallResult()

    with patch("a_sdlc.uninstall.shutil.rmtree", side_effect=OSError("locked")):
        _remove_data_dir(plan, result)

    assert len(result.errors) == 1


# ---------------------------------------------------------------------------
# execute_uninstall (integration)
# ---------------------------------------------------------------------------


def test_execute_uninstall_full(tmp_path):
    """Full uninstall with all components."""
    # Set up claude.json
    claude_json = tmp_path / "claude.json"
    claude_json.write_text(json.dumps({
        "mcpServers": {"asdlc": {"command": "uvx"}}
    }))

    # Set up settings
    settings = {
        "mcpServers": {"serena": {"command": "uvx"}},
        "hooks": {
            "Stop": [
                {"matcher": "", "hooks": [{"type": "command", "command": "langfuse-hook.py"}]}
            ]
        },
        "environment": {"OTEL_METRICS_EXPORTER": "otlp"},
    }

    saved_settings = {}

    def mock_save(s):
        saved_settings.update(s)

    # Monitoring dir
    monitoring_dir = tmp_path / "monitoring"
    monitoring_dir.mkdir()

    # Data dir
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "data.db").write_text("fake")

    plan = UninstallPlan(
        has_asdlc_mcp=True,
        has_serena_mcp=True,
        remove_serena=True,
        skill_template_dir=tmp_path / "sdlc",
        skill_template_count=3,
        has_monitoring_hook=True,
        monitoring_hook_indices=[0],
        managed_env_keys=["OTEL_METRICS_EXPORTER"],
        has_monitoring_dir=True,
        monitoring_dir=monitoring_dir,
        has_data_dir=True,
        data_dir=data_dir,
        include_data=True,
    )

    with (
        patch("a_sdlc.uninstall.get_claude_settings_path", return_value=claude_json),
        patch("a_sdlc.uninstall.load_claude_settings", return_value=settings),
        patch("a_sdlc.uninstall.save_claude_settings", side_effect=mock_save),
        patch("a_sdlc.uninstall.Installer") as MockInstaller,  # noqa: N806
        patch("a_sdlc.uninstall.MONITORING_DIR", monitoring_dir),
        patch("a_sdlc.uninstall.shutil.which", return_value=None),
    ):
        MockInstaller.return_value.uninstall.return_value = 3

        result = execute_uninstall(plan)

    assert result.success is True
    assert len(result.actions) >= 4
    assert not data_dir.exists()


def test_execute_uninstall_no_data():
    """Uninstall without --include-data preserves data dir."""
    plan = UninstallPlan(
        has_data_dir=True,
        data_dir=Path("/fake/data"),
        include_data=False,
    )

    with (
        patch("a_sdlc.uninstall._remove_asdlc_mcp"),
        patch("a_sdlc.uninstall._remove_settings_entries"),
        patch("a_sdlc.uninstall._remove_skill_templates"),
        patch("a_sdlc.uninstall._remove_personas"),
        patch("a_sdlc.uninstall._remove_monitoring"),
        patch("a_sdlc.uninstall._remove_data_dir") as mock_remove_data,
    ):
        execute_uninstall(plan)
        mock_remove_data.assert_not_called()


def test_execute_uninstall_with_data():
    """Uninstall with --include-data calls _remove_data_dir."""
    plan = UninstallPlan(include_data=True)

    with (
        patch("a_sdlc.uninstall._remove_asdlc_mcp"),
        patch("a_sdlc.uninstall._remove_settings_entries"),
        patch("a_sdlc.uninstall._remove_skill_templates"),
        patch("a_sdlc.uninstall._remove_personas"),
        patch("a_sdlc.uninstall._remove_monitoring"),
        patch("a_sdlc.uninstall._remove_data_dir") as mock_remove_data,
    ):
        execute_uninstall(plan)
        mock_remove_data.assert_called_once()


def test_execute_uninstall_calls_remove_personas():
    """execute_uninstall includes _remove_personas phase."""
    plan = UninstallPlan(persona_dir=Path("/agents"), persona_count=3)

    with (
        patch("a_sdlc.uninstall._remove_asdlc_mcp"),
        patch("a_sdlc.uninstall._remove_settings_entries"),
        patch("a_sdlc.uninstall._remove_skill_templates"),
        patch("a_sdlc.uninstall._remove_personas") as mock_remove_personas,
        patch("a_sdlc.uninstall._remove_monitoring"),
    ):
        execute_uninstall(plan)
        mock_remove_personas.assert_called_once()


# ---------------------------------------------------------------------------
# Agent Teams env var in managed keys
# ---------------------------------------------------------------------------


def test_agent_teams_env_in_managed_keys():
    """Agent Teams env var is included in ALL_MANAGED_ENV_KEYS for cleanup."""
    from a_sdlc.uninstall import ALL_MANAGED_ENV_KEYS

    assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" in ALL_MANAGED_ENV_KEYS


def test_uninstall_removes_agent_teams_env(tmp_path):
    """Uninstall removes CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS from settings.json."""
    settings = {
        "environment": {
            "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
            "MY_CUSTOM_VAR": "keep-me",
        },
    }

    plan = UninstallPlan(
        managed_env_keys=["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"]
    )
    result = UninstallResult()

    saved_settings = {}

    def mock_save(s):
        saved_settings.update(s)

    with (
        patch("a_sdlc.uninstall.load_claude_settings", return_value=settings),
        patch("a_sdlc.uninstall.save_claude_settings", side_effect=mock_save),
    ):
        _remove_settings_entries(plan, result)

    assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" not in saved_settings["environment"]
    assert saved_settings["environment"]["MY_CUSTOM_VAR"] == "keep-me"


def test_build_plan_detects_agent_teams_env(tmp_path):
    """build_uninstall_plan() detects CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS."""
    target = _make_target(tmp_path)
    target.settings_path.write_text(json.dumps({
        "environment": {
            "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
        },
    }))

    with (
        patch("a_sdlc.uninstall.Installer") as MockInstaller,  # noqa: N806
        patch("a_sdlc.uninstall.MONITORING_DIR", tmp_path / "monitoring"),
        patch("a_sdlc.core.database.get_data_dir", return_value=tmp_path / "data"),
    ):
        mock_inst = MockInstaller.return_value
        mock_inst.target_dir = tmp_path / "commands" / "sdlc"
        mock_inst.target_dir.mkdir(parents=True, exist_ok=True)

        plan = build_uninstall_plan(targets=[target])
        assert "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS" in plan.managed_env_keys
