"""Tests for monitoring setup module."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a_sdlc.monitoring_setup import (
    HOOK_COMMAND,
    OTEL_ENV_VARS,
    _generate_docker_compose,
    _generate_langfuse_env,
    _hook_already_registered,
    check_docker_available,
    check_git_available,
    check_services_health,
    clone_signoz,
    configure_langfuse_keys,
    install_monitoring_files,
    setup_monitoring,
    update_settings_environment,
    update_settings_hooks,
    verify_monitoring_setup,
)


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------


def test_check_docker_available_missing():
    """Docker not available when binary not found."""
    with patch("a_sdlc.monitoring_setup.shutil.which", return_value=None):
        assert check_docker_available() is False


def test_check_docker_available_no_compose():
    """Docker available but compose subcommand fails."""
    with (
        patch("a_sdlc.monitoring_setup.shutil.which", return_value="/usr/bin/docker"),
        patch("a_sdlc.monitoring_setup.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=1)
        assert check_docker_available() is False


def test_check_docker_available_ok():
    """Docker + compose both available."""
    with (
        patch("a_sdlc.monitoring_setup.shutil.which", return_value="/usr/bin/docker"),
        patch("a_sdlc.monitoring_setup.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        assert check_docker_available() is True


def test_check_git_available():
    """Git availability depends on shutil.which."""
    with patch("a_sdlc.monitoring_setup.shutil.which", return_value="/usr/bin/git"):
        assert check_git_available() is True

    with patch("a_sdlc.monitoring_setup.shutil.which", return_value=None):
        assert check_git_available() is False


# ---------------------------------------------------------------------------
# Secret generation
# ---------------------------------------------------------------------------


def test_generate_langfuse_env_has_random_secrets():
    """Each call should produce different secrets."""
    env1 = _generate_langfuse_env()
    env2 = _generate_langfuse_env()

    # Extract NEXTAUTH_SECRET values
    def _extract(text, key):
        for line in text.splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1]
        return None

    assert _extract(env1, "NEXTAUTH_SECRET") != _extract(env2, "NEXTAUTH_SECRET")
    assert _extract(env1, "ENCRYPTION_KEY") != _extract(env2, "ENCRYPTION_KEY")
    assert _extract(env1, "SALT") != _extract(env2, "SALT")


def test_generate_langfuse_env_has_required_keys():
    """Env file should contain all required configuration."""
    env = _generate_langfuse_env()
    required = [
        "NEXTAUTH_SECRET=",
        "ENCRYPTION_KEY=",
        "SALT=",
        "DATABASE_URL=",
        "CLICKHOUSE_URL=",
        "REDIS_HOST=",
        "LANGFUSE_S3_EVENT_UPLOAD_BUCKET=",
        "LANGFUSE_INIT_USER_EMAIL=",
    ]
    for key in required:
        assert key in env, f"Missing {key} in langfuse.env"


def test_generate_docker_compose_includes():
    """Top-level compose should include both SigNoz and Langfuse."""
    compose = _generate_docker_compose()
    assert "signoz/deploy/docker/docker-compose.yaml" in compose
    assert "langfuse-compose.yaml" in compose


# ---------------------------------------------------------------------------
# File installation
# ---------------------------------------------------------------------------


def test_install_monitoring_files(tmp_path: Path):
    """Install creates all expected files."""
    monitoring_dir = tmp_path / "monitoring"

    with (
        patch("a_sdlc.monitoring_setup.MONITORING_DIR", monitoring_dir),
        patch("a_sdlc.monitoring_setup.LANGFUSE_COMPOSE_PATH", monitoring_dir / "langfuse-compose.yaml"),
        patch("a_sdlc.monitoring_setup.LANGFUSE_HOOK_PATH", monitoring_dir / "langfuse-hook.py"),
        patch("a_sdlc.monitoring_setup.LANGFUSE_ENV_PATH", monitoring_dir / "langfuse.env"),
        patch("a_sdlc.monitoring_setup.DOCKER_COMPOSE_PATH", monitoring_dir / "docker-compose.yaml"),
    ):
        success, message = install_monitoring_files()

        assert success is True
        assert monitoring_dir.exists()
        assert (monitoring_dir / "langfuse-compose.yaml").exists()
        assert (monitoring_dir / "langfuse-hook.py").exists()
        assert (monitoring_dir / "langfuse.env").exists()
        assert (monitoring_dir / "docker-compose.yaml").exists()


def test_install_monitoring_files_skip_existing(tmp_path: Path):
    """Without force, existing files are not overwritten."""
    monitoring_dir = tmp_path / "monitoring"
    monitoring_dir.mkdir(parents=True)

    env_file = monitoring_dir / "langfuse.env"
    env_file.write_text("ORIGINAL_CONTENT")

    with (
        patch("a_sdlc.monitoring_setup.MONITORING_DIR", monitoring_dir),
        patch("a_sdlc.monitoring_setup.LANGFUSE_COMPOSE_PATH", monitoring_dir / "langfuse-compose.yaml"),
        patch("a_sdlc.monitoring_setup.LANGFUSE_HOOK_PATH", monitoring_dir / "langfuse-hook.py"),
        patch("a_sdlc.monitoring_setup.LANGFUSE_ENV_PATH", env_file),
        patch("a_sdlc.monitoring_setup.DOCKER_COMPOSE_PATH", monitoring_dir / "docker-compose.yaml"),
    ):
        success, _ = install_monitoring_files(force=False)
        assert success is True
        assert env_file.read_text() == "ORIGINAL_CONTENT"


def test_install_monitoring_files_force_overwrites(tmp_path: Path):
    """With force, existing files are overwritten."""
    monitoring_dir = tmp_path / "monitoring"
    monitoring_dir.mkdir(parents=True)

    env_file = monitoring_dir / "langfuse.env"
    env_file.write_text("ORIGINAL_CONTENT")

    with (
        patch("a_sdlc.monitoring_setup.MONITORING_DIR", monitoring_dir),
        patch("a_sdlc.monitoring_setup.LANGFUSE_COMPOSE_PATH", monitoring_dir / "langfuse-compose.yaml"),
        patch("a_sdlc.monitoring_setup.LANGFUSE_HOOK_PATH", monitoring_dir / "langfuse-hook.py"),
        patch("a_sdlc.monitoring_setup.LANGFUSE_ENV_PATH", env_file),
        patch("a_sdlc.monitoring_setup.DOCKER_COMPOSE_PATH", monitoring_dir / "docker-compose.yaml"),
    ):
        success, _ = install_monitoring_files(force=True)
        assert success is True
        assert env_file.read_text() != "ORIGINAL_CONTENT"


# ---------------------------------------------------------------------------
# SigNoz clone
# ---------------------------------------------------------------------------


def test_clone_signoz_already_exists(tmp_path: Path):
    """Skip clone if directory already exists."""
    target = tmp_path / "signoz"
    target.mkdir()

    success, msg = clone_signoz(target_dir=target, force=False)
    assert success is True
    assert "already cloned" in msg


def test_clone_signoz_runs_git(tmp_path: Path):
    """Clone invokes git with correct arguments."""
    target = tmp_path / "signoz"

    with patch("a_sdlc.monitoring_setup.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        success, _ = clone_signoz(target_dir=target, tag="v0.110.1")

        assert success is True
        call_args = mock_run.call_args[0][0]
        assert "git" in call_args
        assert "--depth" in call_args
        assert "v0.110.1" in call_args


def test_clone_signoz_failure(tmp_path: Path):
    """Clone failure reports error."""
    target = tmp_path / "signoz"

    with patch("a_sdlc.monitoring_setup.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="auth failed")
        success, msg = clone_signoz(target_dir=target)

        assert success is False
        assert "git clone failed" in msg


# ---------------------------------------------------------------------------
# Settings hooks
# ---------------------------------------------------------------------------


def test_hook_already_registered_empty():
    """No hooks registered in empty settings."""
    assert _hook_already_registered({}) is False


def test_hook_already_registered_present():
    """Detects existing langfuse hook."""
    hook_path = str(Path.home() / ".a-sdlc" / "monitoring" / "langfuse-hook.py")
    settings = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": f"uv run {hook_path}"}
                    ],
                }
            ]
        }
    }
    assert _hook_already_registered(settings) is True


def test_hook_already_registered_other_hooks():
    """Other hooks don't trigger false positive."""
    settings = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [
                        {"type": "command", "command": "some-other-hook.py"}
                    ],
                }
            ]
        }
    }
    assert _hook_already_registered(settings) is False


def test_update_settings_hooks_empty(tmp_path: Path):
    """Adds hook to empty settings."""
    settings_file = tmp_path / ".claude" / "settings.json"

    with patch("a_sdlc.monitoring_setup.load_claude_settings", return_value={}):
        saved = {}

        def mock_save(s):
            saved.update(s)

        with patch("a_sdlc.monitoring_setup.save_claude_settings", side_effect=mock_save):
            success, msg = update_settings_hooks()

            assert success is True
            assert "registered" in msg
            assert len(saved["hooks"]["Stop"]) == 1
            assert "langfuse-hook.py" in saved["hooks"]["Stop"][0]["hooks"][0]["command"]


def test_update_settings_hooks_preserves_existing(tmp_path: Path):
    """Existing hooks are preserved when adding langfuse."""
    existing = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": "existing-hook.sh"}],
                }
            ]
        }
    }

    with patch("a_sdlc.monitoring_setup.load_claude_settings", return_value=existing):
        saved = {}

        def mock_save(s):
            saved.update(s)

        with patch("a_sdlc.monitoring_setup.save_claude_settings", side_effect=mock_save):
            success, _ = update_settings_hooks()

            assert success is True
            stop_hooks = saved["hooks"]["Stop"]
            assert len(stop_hooks) == 2
            # Original hook preserved
            assert stop_hooks[0]["hooks"][0]["command"] == "existing-hook.sh"
            # New hook added
            assert "langfuse-hook.py" in stop_hooks[1]["hooks"][0]["command"]


def test_update_settings_hooks_skip_duplicate(tmp_path: Path):
    """Does not add duplicate hook entry."""
    existing = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": HOOK_COMMAND}],
                }
            ]
        }
    }

    with patch("a_sdlc.monitoring_setup.load_claude_settings", return_value=existing):
        with patch("a_sdlc.monitoring_setup.save_claude_settings") as mock_save:
            success, msg = update_settings_hooks(force=False)

            assert success is True
            assert "already registered" in msg
            mock_save.assert_not_called()


def test_update_settings_hooks_force_replaces(tmp_path: Path):
    """Force removes old hook and adds fresh one."""
    existing = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": "uv run /old/path/langfuse-hook.py"}],
                }
            ]
        }
    }

    with patch("a_sdlc.monitoring_setup.load_claude_settings", return_value=existing):
        saved = {}

        def mock_save(s):
            saved.update(s)

        with patch("a_sdlc.monitoring_setup.save_claude_settings", side_effect=mock_save):
            success, _ = update_settings_hooks(force=True)

            assert success is True
            stop_hooks = saved["hooks"]["Stop"]
            assert len(stop_hooks) == 1
            assert HOOK_COMMAND in stop_hooks[0]["hooks"][0]["command"]


# ---------------------------------------------------------------------------
# Settings environment
# ---------------------------------------------------------------------------


def test_update_settings_environment_empty(tmp_path: Path):
    """Adds all OTEL vars to empty settings."""
    with patch("a_sdlc.monitoring_setup.load_claude_settings", return_value={}):
        saved = {}

        def mock_save(s):
            saved.update(s)

        with patch("a_sdlc.monitoring_setup.save_claude_settings", side_effect=mock_save):
            success, msg = update_settings_environment()

            assert success is True
            env = saved["environment"]
            for key in OTEL_ENV_VARS:
                assert key in env
                assert env[key] == OTEL_ENV_VARS[key]


def test_update_settings_environment_skip_existing(tmp_path: Path):
    """Without force, existing env vars are not overwritten."""
    existing = {
        "environment": {
            "CLAUDE_CODE_ENABLE_TELEMETRY": "0",  # User set to 0
            "SOME_OTHER_VAR": "keep",
        }
    }

    with patch("a_sdlc.monitoring_setup.load_claude_settings", return_value=existing):
        saved = {}

        def mock_save(s):
            saved.update(s)

        with patch("a_sdlc.monitoring_setup.save_claude_settings", side_effect=mock_save):
            success, _ = update_settings_environment(force=False)

            assert success is True
            env = saved["environment"]
            # Existing value preserved
            assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "0"
            # Other OTEL vars added
            assert env["OTEL_METRICS_EXPORTER"] == "otlp"
            # Unrelated var preserved
            assert env["SOME_OTHER_VAR"] == "keep"


def test_update_settings_environment_force(tmp_path: Path):
    """With force, all OTEL vars are overwritten."""
    existing = {
        "environment": {
            "CLAUDE_CODE_ENABLE_TELEMETRY": "0",
        }
    }

    with patch("a_sdlc.monitoring_setup.load_claude_settings", return_value=existing):
        saved = {}

        def mock_save(s):
            saved.update(s)

        with patch("a_sdlc.monitoring_setup.save_claude_settings", side_effect=mock_save):
            success, _ = update_settings_environment(force=True)

            assert success is True
            assert saved["environment"]["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"


def test_update_settings_environment_already_configured():
    """All OTEL vars already set returns 'already configured'."""
    existing = {"environment": dict(OTEL_ENV_VARS)}

    with patch("a_sdlc.monitoring_setup.load_claude_settings", return_value=existing):
        with patch("a_sdlc.monitoring_setup.save_claude_settings") as mock_save:
            success, msg = update_settings_environment(force=False)

            assert success is True
            assert "already configured" in msg
            mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Langfuse key configuration
# ---------------------------------------------------------------------------


def test_configure_langfuse_keys(tmp_path: Path):
    """Keys are written to settings environment."""
    with patch("a_sdlc.monitoring_setup.load_claude_settings", return_value={}):
        saved = {}

        def mock_save(s):
            saved.update(s)

        with patch("a_sdlc.monitoring_setup.save_claude_settings", side_effect=mock_save):
            success, _ = configure_langfuse_keys(
                secret_key="sk-lf-test",
                public_key="pk-lf-test",
                host="http://localhost:13000",
            )

            assert success is True
            env = saved["environment"]
            assert env["LANGFUSE_SECRET_KEY"] == "sk-lf-test"
            assert env["LANGFUSE_PUBLIC_KEY"] == "pk-lf-test"
            assert env["LANGFUSE_HOST"] == "http://localhost:13000"


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def test_verify_monitoring_setup_nothing_installed(tmp_path: Path):
    """Verification when nothing is installed."""
    with (
        patch("a_sdlc.monitoring_setup.MONITORING_DIR", tmp_path / "nonexistent"),
        patch("a_sdlc.monitoring_setup.LANGFUSE_COMPOSE_PATH", tmp_path / "nonexistent" / "a"),
        patch("a_sdlc.monitoring_setup.LANGFUSE_HOOK_PATH", tmp_path / "nonexistent" / "b"),
        patch("a_sdlc.monitoring_setup.LANGFUSE_ENV_PATH", tmp_path / "nonexistent" / "c"),
        patch("a_sdlc.monitoring_setup.DOCKER_COMPOSE_PATH", tmp_path / "nonexistent" / "d"),
        patch("a_sdlc.monitoring_setup.SIGNOZ_DIR", tmp_path / "nonexistent" / "e"),
        patch("a_sdlc.monitoring_setup.load_claude_settings", return_value={}),
    ):
        result = verify_monitoring_setup()

        assert result["files_ready"] is False
        assert result["settings_ready"] is False
        assert result["ready"] is False


def test_verify_monitoring_setup_fully_configured(tmp_path: Path):
    """Verification when everything is in place."""
    monitoring_dir = tmp_path / "monitoring"
    monitoring_dir.mkdir(parents=True)

    # Create all expected files
    for name in ["langfuse-compose.yaml", "langfuse-hook.py", "langfuse.env", "docker-compose.yaml"]:
        (monitoring_dir / name).write_text("content")
    signoz_dir = monitoring_dir / "signoz"
    signoz_dir.mkdir()

    settings = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": HOOK_COMMAND}],
                }
            ]
        },
        "environment": {
            **OTEL_ENV_VARS,
            "LANGFUSE_SECRET_KEY": "sk-lf-test",
            "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
        },
    }

    with (
        patch("a_sdlc.monitoring_setup.MONITORING_DIR", monitoring_dir),
        patch("a_sdlc.monitoring_setup.LANGFUSE_COMPOSE_PATH", monitoring_dir / "langfuse-compose.yaml"),
        patch("a_sdlc.monitoring_setup.LANGFUSE_HOOK_PATH", monitoring_dir / "langfuse-hook.py"),
        patch("a_sdlc.monitoring_setup.LANGFUSE_ENV_PATH", monitoring_dir / "langfuse.env"),
        patch("a_sdlc.monitoring_setup.DOCKER_COMPOSE_PATH", monitoring_dir / "docker-compose.yaml"),
        patch("a_sdlc.monitoring_setup.SIGNOZ_DIR", signoz_dir),
        patch("a_sdlc.monitoring_setup.load_claude_settings", return_value=settings),
    ):
        result = verify_monitoring_setup()

        assert result["files_ready"] is True
        assert result["settings_ready"] is True
        assert result["ready"] is True
        assert result["langfuse_keys_configured"] is True


# ---------------------------------------------------------------------------
# Full orchestrator
# ---------------------------------------------------------------------------


def test_setup_monitoring_no_docker():
    """Setup fails without Docker."""
    with patch("a_sdlc.monitoring_setup.check_docker_available", return_value=False):
        success, msg, _ = setup_monitoring()
        assert success is False
        assert "Docker" in msg


def test_setup_monitoring_no_git():
    """Setup fails without git."""
    with (
        patch("a_sdlc.monitoring_setup.check_docker_available", return_value=True),
        patch("a_sdlc.monitoring_setup.check_git_available", return_value=False),
    ):
        success, msg, _ = setup_monitoring()
        assert success is False
        assert "git" in msg.lower()


def test_setup_monitoring_full_success(tmp_path: Path):
    """Full setup orchestration succeeds."""
    with (
        patch("a_sdlc.monitoring_setup.check_docker_available", return_value=True),
        patch("a_sdlc.monitoring_setup.check_git_available", return_value=True),
        patch("a_sdlc.monitoring_setup.install_monitoring_files", return_value=(True, "Files installed")),
        patch("a_sdlc.monitoring_setup.clone_signoz", return_value=(True, "SigNoz cloned")),
        patch("a_sdlc.monitoring_setup.update_settings_hooks", return_value=(True, "Hook registered")),
        patch("a_sdlc.monitoring_setup.update_settings_environment", return_value=(True, "Env set")),
        patch("a_sdlc.monitoring_setup.verify_monitoring_setup", return_value={"ready": True}),
    ):
        success, msg, verification = setup_monitoring()

        assert success is True
        assert "Files installed" in msg
        assert verification["ready"] is True


# ---------------------------------------------------------------------------
# Service health checks
# ---------------------------------------------------------------------------


def test_check_services_health_both_reachable():
    """Both Langfuse and SigNoz reachable."""
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.return_value = MagicMock()
        result = check_services_health()

        assert result["langfuse_reachable"] is True
        assert result["signoz_reachable"] is True
        assert result["services_running"] is True
        assert result["langfuse_url"] == "http://localhost:13000"
        assert result["signoz_url"] == "http://localhost:8080"


def test_check_services_health_none_reachable():
    """Neither service reachable."""
    import urllib.error

    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("Connection refused"),
    ):
        result = check_services_health()

        assert result["langfuse_reachable"] is False
        assert result["signoz_reachable"] is False
        assert result["services_running"] is False


def test_check_services_health_partial():
    """Only Langfuse reachable, SigNoz down."""
    import urllib.error

    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call (Langfuse) succeeds
            return MagicMock()
        # Second call (SigNoz) fails
        raise urllib.error.URLError("Connection refused")

    with patch("urllib.request.urlopen", side_effect=side_effect):
        result = check_services_health()

        assert result["langfuse_reachable"] is True
        assert result["signoz_reachable"] is False
        assert result["services_running"] is False


def test_check_services_health_os_error():
    """OSError (e.g., network timeout) handled gracefully."""
    with patch(
        "urllib.request.urlopen",
        side_effect=OSError("Network unreachable"),
    ):
        result = check_services_health()

        assert result["langfuse_reachable"] is False
        assert result["signoz_reachable"] is False
        assert result["services_running"] is False


# ---------------------------------------------------------------------------
# Setup orchestrator error paths
# ---------------------------------------------------------------------------


def test_setup_monitoring_install_files_failure():
    """Setup reports file installation failure."""
    with (
        patch("a_sdlc.monitoring_setup.check_docker_available", return_value=True),
        patch("a_sdlc.monitoring_setup.check_git_available", return_value=True),
        patch("a_sdlc.monitoring_setup.install_monitoring_files", return_value=(False, "Permission denied")),
    ):
        success, msg, _ = setup_monitoring()
        assert success is False
        assert "Permission denied" in msg


def test_setup_monitoring_clone_signoz_failure():
    """Setup reports SigNoz clone failure."""
    with (
        patch("a_sdlc.monitoring_setup.check_docker_available", return_value=True),
        patch("a_sdlc.monitoring_setup.check_git_available", return_value=True),
        patch("a_sdlc.monitoring_setup.install_monitoring_files", return_value=(True, "OK")),
        patch("a_sdlc.monitoring_setup.clone_signoz", return_value=(False, "git clone failed")),
    ):
        success, msg, _ = setup_monitoring()
        assert success is False
        assert "git clone failed" in msg


# ---------------------------------------------------------------------------
# Langfuse hook: load_env_from_settings
# ---------------------------------------------------------------------------


def _import_hook_module():
    """Import the langfuse-hook.py script as a module."""
    import importlib.util

    hook_path = Path(__file__).parent.parent / "src" / "a_sdlc" / "monitoring_files" / "langfuse-hook.py"
    spec = importlib.util.spec_from_file_location("langfuse_hook", hook_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_hook_load_env_from_settings(tmp_path: Path):
    """Hook loads LANGFUSE_* vars from settings.json when not in env."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({
        "environment": {
            "LANGFUSE_SECRET_KEY": "sk-lf-test",
            "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
            "LANGFUSE_HOST": "http://localhost:13000",
            "UNRELATED_VAR": "should-be-ignored",
        }
    }))

    mod = _import_hook_module()

    # Ensure LANGFUSE vars are NOT in the environment
    env_backup = {}
    for key in ["LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_HOST"]:
        env_backup[key] = os.environ.pop(key, None)

    try:
        with patch.object(mod, "SETTINGS_PATH", settings_file):
            mod.load_env_from_settings()

        assert os.environ["LANGFUSE_SECRET_KEY"] == "sk-lf-test"
        assert os.environ["LANGFUSE_PUBLIC_KEY"] == "pk-lf-test"
        assert os.environ["LANGFUSE_HOST"] == "http://localhost:13000"
        # Non-LANGFUSE vars should not be loaded
        assert "UNRELATED_VAR" not in os.environ
    finally:
        # Restore original env
        for key, val in env_backup.items():
            if val is not None:
                os.environ[key] = val
            else:
                os.environ.pop(key, None)


def test_hook_load_env_no_override(tmp_path: Path):
    """Hook does not override existing env vars."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({
        "environment": {
            "LANGFUSE_SECRET_KEY": "sk-from-settings",
        }
    }))

    mod = _import_hook_module()

    os.environ["LANGFUSE_SECRET_KEY"] = "sk-from-env"
    try:
        with patch.object(mod, "SETTINGS_PATH", settings_file):
            mod.load_env_from_settings()

        # Env var should NOT be overwritten
        assert os.environ["LANGFUSE_SECRET_KEY"] == "sk-from-env"
    finally:
        os.environ.pop("LANGFUSE_SECRET_KEY", None)


def test_hook_load_env_missing_settings(tmp_path: Path):
    """Hook handles missing settings.json gracefully."""
    mod = _import_hook_module()

    with patch.object(mod, "SETTINGS_PATH", tmp_path / "nonexistent.json"):
        # Should not raise
        mod.load_env_from_settings()


def test_hook_load_env_invalid_json(tmp_path: Path):
    """Hook handles corrupt settings.json gracefully."""
    settings_file = tmp_path / "settings.json"
    settings_file.write_text("not valid json{{{")

    mod = _import_hook_module()

    with patch.object(mod, "SETTINGS_PATH", settings_file):
        # Should not raise
        mod.load_env_from_settings()


# ---------------------------------------------------------------------------
# Langfuse hook: message helpers
# ---------------------------------------------------------------------------


def test_hook_get_content_from_message_wrapper():
    """get_content extracts from {message: {content: ...}} wrapper."""
    mod = _import_hook_module()
    msg = {"message": {"content": "hello"}}
    assert mod.get_content(msg) == "hello"


def test_hook_get_content_direct():
    """get_content extracts from {content: ...} directly."""
    mod = _import_hook_module()
    msg = {"content": "direct"}
    assert mod.get_content(msg) == "direct"


def test_hook_get_content_none():
    """get_content returns None for non-dict or missing content."""
    mod = _import_hook_module()
    assert mod.get_content("not a dict") is None
    assert mod.get_content({}) is None


def test_hook_is_tool_result_true():
    """is_tool_result detects tool_result blocks."""
    mod = _import_hook_module()
    msg = {"message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}
    assert mod.is_tool_result(msg) is True


def test_hook_is_tool_result_false():
    """is_tool_result returns False for text-only content."""
    mod = _import_hook_module()
    msg = {"message": {"content": [{"type": "text", "text": "hello"}]}}
    assert mod.is_tool_result(msg) is False


def test_hook_is_tool_result_string():
    """is_tool_result returns False for string content."""
    mod = _import_hook_module()
    msg = {"message": {"content": "just text"}}
    assert mod.is_tool_result(msg) is False


def test_hook_get_tool_calls():
    """get_tool_calls extracts tool_use blocks."""
    mod = _import_hook_module()
    msg = {
        "message": {
            "content": [
                {"type": "text", "text": "Let me search"},
                {"type": "tool_use", "id": "t1", "name": "Grep", "input": {"pattern": "foo"}},
                {"type": "tool_use", "id": "t2", "name": "Read", "input": {"path": "/a.py"}},
            ]
        }
    }
    tools = mod.get_tool_calls(msg)
    assert len(tools) == 2
    assert tools[0]["name"] == "Grep"
    assert tools[1]["name"] == "Read"


def test_hook_get_tool_calls_empty():
    """get_tool_calls returns empty list for text-only message."""
    mod = _import_hook_module()
    msg = {"message": {"content": "no tools"}}
    assert mod.get_tool_calls(msg) == []


def test_hook_get_text_content_string():
    """get_text_content extracts string content."""
    mod = _import_hook_module()
    msg = {"message": {"content": "hello world"}}
    assert mod.get_text_content(msg) == "hello world"


def test_hook_get_text_content_list():
    """get_text_content extracts text from content blocks."""
    mod = _import_hook_module()
    msg = {
        "message": {
            "content": [
                {"type": "text", "text": "part1"},
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {}},
                {"type": "text", "text": "part2"},
            ]
        }
    }
    assert mod.get_text_content(msg) == "part1\npart2"


def test_hook_get_text_content_empty():
    """get_text_content returns empty string for missing content."""
    mod = _import_hook_module()
    assert mod.get_text_content({}) == ""


# ---------------------------------------------------------------------------
# Langfuse hook: merge_assistant_parts
# ---------------------------------------------------------------------------


def test_hook_merge_assistant_parts():
    """Merges multiple assistant parts with same message ID."""
    mod = _import_hook_module()
    parts = [
        {"message": {"id": "msg1", "content": [{"type": "text", "text": "Hello"}]}},
        {"message": {"id": "msg1", "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]}},
    ]
    merged = mod.merge_assistant_parts(parts)
    content = mod.get_content(merged)
    assert len(content) == 2
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "tool_use"


def test_hook_merge_assistant_parts_empty():
    """Merging empty list returns empty dict."""
    mod = _import_hook_module()
    assert mod.merge_assistant_parts([]) == {}


def test_hook_merge_assistant_parts_string_content():
    """Merging parts with string content wraps in text blocks."""
    mod = _import_hook_module()
    parts = [
        {"message": {"id": "msg1", "content": "first part"}},
        {"message": {"id": "msg1", "content": "second part"}},
    ]
    merged = mod.merge_assistant_parts(parts)
    content = mod.get_content(merged)
    assert len(content) == 2
    assert content[0] == {"type": "text", "text": "first part"}
    assert content[1] == {"type": "text", "text": "second part"}


# ---------------------------------------------------------------------------
# Langfuse hook: turn grouping (process_transcript)
# ---------------------------------------------------------------------------


def _make_transcript_lines(entries):
    """Helper: convert list of dicts to JSONL string."""
    return "\n".join(json.dumps(e) for e in entries)


def test_hook_turn_grouping_basic(tmp_path: Path):
    """Groups user -> assistant into a single turn and calls create_trace."""
    mod = _import_hook_module()

    entries = [
        {"type": "user", "message": {"role": "user", "content": "What is 2+2?"}},
        {"type": "assistant", "message": {"role": "assistant", "id": "a1", "model": "claude-opus-4-6", "content": [{"type": "text", "text": "4"}]}},
    ]
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(_make_transcript_lines(entries))

    traces_created = []

    def mock_create_trace(langfuse, session_id, turn_num, user_msg, assistant_msgs, tool_results):
        traces_created.append({
            "turn_num": turn_num,
            "user_text": mod.get_text_content(user_msg),
            "assistant_count": len(assistant_msgs),
            "tool_results_count": len(tool_results),
        })

    with patch.object(mod, "create_trace", mock_create_trace):
        with patch.object(mod, "save_state"):
            state = {}
            turns = mod.process_transcript(None, "session-1", str(transcript), state)

    assert turns == 1
    assert len(traces_created) == 1
    assert traces_created[0]["turn_num"] == 1
    assert traces_created[0]["user_text"] == "What is 2+2?"
    assert traces_created[0]["assistant_count"] == 1


def test_hook_turn_grouping_multiple_turns(tmp_path: Path):
    """Multiple user-assistant pairs create multiple turns."""
    mod = _import_hook_module()

    entries = [
        {"type": "user", "message": {"role": "user", "content": "Hello"}},
        {"type": "assistant", "message": {"role": "assistant", "id": "a1", "model": "claude", "content": "Hi!"}},
        {"type": "user", "message": {"role": "user", "content": "How are you?"}},
        {"type": "assistant", "message": {"role": "assistant", "id": "a2", "model": "claude", "content": "Good!"}},
    ]
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(_make_transcript_lines(entries))

    traces_created = []

    def mock_create_trace(langfuse, session_id, turn_num, user_msg, assistant_msgs, tool_results):
        traces_created.append({"turn_num": turn_num})

    with patch.object(mod, "create_trace", mock_create_trace):
        with patch.object(mod, "save_state"):
            state = {}
            turns = mod.process_transcript(None, "session-1", str(transcript), state)

    assert turns == 2
    assert traces_created[0]["turn_num"] == 1
    assert traces_created[1]["turn_num"] == 2


def test_hook_turn_grouping_tool_results_stay_with_turn(tmp_path: Path):
    """Tool results (type=user with tool_result blocks) stay in the current turn."""
    mod = _import_hook_module()

    entries = [
        {"type": "user", "message": {"role": "user", "content": "Read file.py"}},
        {"type": "assistant", "message": {"role": "assistant", "id": "a1", "model": "claude", "content": [
            {"type": "text", "text": "Let me read that"},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"path": "file.py"}},
        ]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "file contents here"},
        ]}},
        {"type": "assistant", "message": {"role": "assistant", "id": "a2", "model": "claude", "content": "Here's what I found"}},
        {"type": "user", "message": {"role": "user", "content": "Thanks!"}},
        {"type": "assistant", "message": {"role": "assistant", "id": "a3", "model": "claude", "content": "You're welcome!"}},
    ]
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(_make_transcript_lines(entries))

    traces_created = []

    def mock_create_trace(langfuse, session_id, turn_num, user_msg, assistant_msgs, tool_results):
        traces_created.append({
            "turn_num": turn_num,
            "tool_results_count": len(tool_results),
            "assistant_count": len(assistant_msgs),
        })

    with patch.object(mod, "create_trace", mock_create_trace):
        with patch.object(mod, "save_state"):
            state = {}
            turns = mod.process_transcript(None, "session-1", str(transcript), state)

    assert turns == 2
    # First turn has tool results
    assert traces_created[0]["tool_results_count"] == 1
    assert traces_created[0]["assistant_count"] == 2
    # Second turn has no tool results
    assert traces_created[1]["tool_results_count"] == 0


def test_hook_turn_grouping_assistant_merging(tmp_path: Path):
    """Multiple assistant entries with same message ID are merged."""
    mod = _import_hook_module()

    entries = [
        {"type": "user", "message": {"role": "user", "content": "Do something"}},
        {"type": "assistant", "message": {"role": "assistant", "id": "a1", "model": "claude", "content": [{"type": "text", "text": "Part 1"}]}},
        {"type": "assistant", "message": {"role": "assistant", "id": "a1", "model": "claude", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}},
    ]
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(_make_transcript_lines(entries))

    traces_created = []

    def mock_create_trace(langfuse, session_id, turn_num, user_msg, assistant_msgs, tool_results):
        traces_created.append({"assistant_count": len(assistant_msgs)})

    with patch.object(mod, "create_trace", mock_create_trace):
        with patch.object(mod, "save_state"):
            state = {}
            turns = mod.process_transcript(None, "session-1", str(transcript), state)

    assert turns == 1
    # Two parts with same ID merged into one assistant message
    assert traces_created[0]["assistant_count"] == 1


def test_hook_turn_grouping_incremental(tmp_path: Path):
    """Incremental processing resumes from last_line."""
    mod = _import_hook_module()

    entries = [
        {"type": "user", "message": {"role": "user", "content": "First"}},
        {"type": "assistant", "message": {"role": "assistant", "id": "a1", "model": "claude", "content": "Response 1"}},
        {"type": "user", "message": {"role": "user", "content": "Second"}},
        {"type": "assistant", "message": {"role": "assistant", "id": "a2", "model": "claude", "content": "Response 2"}},
    ]
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(_make_transcript_lines(entries))

    traces_created = []

    def mock_create_trace(langfuse, session_id, turn_num, user_msg, assistant_msgs, tool_results):
        traces_created.append({"turn_num": turn_num})

    # Simulate already processed first 2 lines
    with patch.object(mod, "create_trace", mock_create_trace):
        with patch.object(mod, "save_state"):
            state = {"session-1": {"last_line": 2, "turn_count": 1}}
            turns = mod.process_transcript(None, "session-1", str(transcript), state)

    assert turns == 1
    # Turn number continues from previous state
    assert traces_created[0]["turn_num"] == 2


def test_hook_turn_grouping_no_new_lines(tmp_path: Path):
    """No processing when all lines already consumed."""
    mod = _import_hook_module()

    entries = [
        {"type": "user", "message": {"role": "user", "content": "Hello"}},
        {"type": "assistant", "message": {"role": "assistant", "id": "a1", "model": "claude", "content": "Hi"}},
    ]
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(_make_transcript_lines(entries))

    state = {"session-1": {"last_line": 2, "turn_count": 1}}
    turns = mod.process_transcript(None, "session-1", str(transcript), state)
    assert turns == 0


def test_hook_state_roundtrip(tmp_path: Path):
    """State save/load roundtrips correctly."""
    mod = _import_hook_module()

    state_file = tmp_path / "state.json"
    with patch.object(mod, "STATE_FILE", state_file):
        # Initially empty
        assert mod.load_state() == {}

        # Save and reload
        mod.save_state({"session-1": {"last_line": 10, "turn_count": 3}})
        loaded = mod.load_state()
        assert loaded["session-1"]["last_line"] == 10
        assert loaded["session-1"]["turn_count"] == 3


# ---------------------------------------------------------------------------
# Langfuse hook: create_trace tool matching
# ---------------------------------------------------------------------------


def test_hook_create_trace_matches_tool_results():
    """create_trace matches tool_use.id with tool_result.tool_use_id."""
    mod = _import_hook_module()

    user_msg = {"type": "user", "message": {"role": "user", "content": "Read file.py"}}
    assistant_msgs = [
        {"message": {"role": "assistant", "id": "a1", "model": "claude", "content": [
            {"type": "text", "text": "Reading..."},
            {"type": "tool_use", "id": "tool-123", "name": "Read", "input": {"path": "file.py"}},
        ]}},
    ]
    tool_results = [
        {"message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tool-123", "content": "file contents"},
        ]}},
    ]

    # Mock langfuse with context managers
    mock_span = MagicMock()
    mock_span.__enter__ = MagicMock(return_value=mock_span)
    mock_span.__exit__ = MagicMock(return_value=False)

    mock_langfuse = MagicMock()
    mock_langfuse.start_as_current_span.return_value = mock_span
    mock_langfuse.start_as_current_observation.return_value = mock_span

    mod.create_trace(mock_langfuse, "session-1", 1, user_msg, assistant_msgs, tool_results)

    # Verify tool span was created with matched output
    span_calls = mock_langfuse.start_as_current_span.call_args_list
    # First call is the turn span, second is the tool span
    assert len(span_calls) == 2
    tool_span_call = span_calls[1]
    assert tool_span_call.kwargs["name"] == "Tool: Read"
    assert tool_span_call.kwargs["input"] == {"path": "file.py"}

    # The tool span.update should have been called with the matched output
    mock_span.update.assert_any_call(output="file contents")
