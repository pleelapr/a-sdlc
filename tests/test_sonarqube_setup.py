"""Tests for SonarQube setup module."""

import json
from unittest.mock import MagicMock, patch

from a_sdlc.sonarqube_setup import (
    DEFAULT_FIX_SEVERITIES,
    _api_request,
    _format_quality_report,
    check_scanner_available,
    check_sonarqube_reachable,
    configure_connection,
    configure_project,
    generate_code_quality_artifact,
    get_issues,
    get_metrics,
    get_quality_gate_status,
    load_sonarqube_config,
    run_scanner,
    save_sonarqube_config,
    setup_sonarqube,
    verify_sonarqube_setup,
)

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------


def test_check_scanner_pysonar_available():
    """pysonar found on PATH."""
    with patch("a_sdlc.sonarqube_setup.shutil.which") as mock_which:
        mock_which.side_effect = lambda cmd: "/usr/local/bin/pysonar" if cmd == "pysonar" else None
        ok, method = check_scanner_available()
        assert ok is True
        assert method == "pysonar"


def test_check_scanner_nothing_available():
    """pysonar not available."""
    with patch("a_sdlc.sonarqube_setup.shutil.which", return_value=None):
        ok, method = check_scanner_available()
        assert ok is False
        assert "pysonar not found" in method
        assert "uv tool install" in method


def test_check_sonarqube_reachable_up():
    """SonarQube reachable and UP."""
    with patch("a_sdlc.sonarqube_setup._api_request") as mock_api:
        mock_api.return_value = (True, {"status": "UP"})
        ok, msg = check_sonarqube_reachable("http://localhost:9000", "token123")
        assert ok is True
        assert "running" in msg


def test_check_sonarqube_reachable_down():
    """SonarQube reachable but not UP."""
    with patch("a_sdlc.sonarqube_setup._api_request") as mock_api:
        mock_api.return_value = (True, {"status": "STARTING"})
        ok, msg = check_sonarqube_reachable("http://localhost:9000", "token123")
        assert ok is False
        assert "not ready" in msg


def test_check_sonarqube_unreachable():
    """SonarQube not reachable."""
    with patch("a_sdlc.sonarqube_setup._api_request") as mock_api:
        mock_api.return_value = (False, "Connection refused")
        ok, msg = check_sonarqube_reachable("http://localhost:9000", "token123")
        assert ok is False
        assert "Cannot reach" in msg


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_load_config_empty(tmp_path):
    """Load config returns empty dict when no files exist."""
    with patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", tmp_path / "nonexistent.yaml"):
        config = load_sonarqube_config(project_dir=tmp_path)
    assert config == {}


def test_load_config_global_only(tmp_path):
    """Load config reads global config."""
    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("sonarqube:\n  host_url: http://localhost:9000\n  token: abc\n")

    with patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg):
        config = load_sonarqube_config(project_dir=tmp_path)

    assert config["host_url"] == "http://localhost:9000"
    assert config["token"] == "abc"


def test_load_config_project_overrides_global(tmp_path):
    """Project config overrides global config."""
    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("sonarqube:\n  host_url: http://global:9000\n  token: global-token\n")

    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text("sonarqube:\n  host_url: http://project:9000\n  project_key: my-project\n")

    with patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg):
        config = load_sonarqube_config(project_dir=tmp_path)

    assert config["host_url"] == "http://project:9000"
    assert config["token"] == "global-token"
    assert config["project_key"] == "my-project"


def test_save_config_global(tmp_path):
    """Save config to global location."""
    global_cfg = tmp_path / "config.yaml"

    with (
        patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg),
        patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_DIR", tmp_path),
    ):
        ok, msg = save_sonarqube_config({"host_url": "http://localhost:9000"}, target="global")

    assert ok is True
    assert global_cfg.exists()
    import yaml
    data = yaml.safe_load(global_cfg.read_text())
    assert data["sonarqube"]["host_url"] == "http://localhost:9000"


def test_save_config_project(tmp_path):
    """Save config to project location."""
    ok, msg = save_sonarqube_config(
        {"project_key": "my-project"},
        target="project",
        project_dir=tmp_path,
    )

    assert ok is True
    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    assert project_cfg.exists()
    import yaml
    data = yaml.safe_load(project_cfg.read_text())
    assert data["sonarqube"]["project_key"] == "my-project"


def test_save_config_merges_existing(tmp_path):
    """Save config merges with existing config."""
    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text("sonarqube:\n  project_key: old-key\n  sources: src\n")

    ok, msg = save_sonarqube_config(
        {"project_key": "new-key"},
        target="project",
        project_dir=tmp_path,
    )

    assert ok is True
    import yaml
    data = yaml.safe_load(project_cfg.read_text())
    assert data["sonarqube"]["project_key"] == "new-key"
    assert data["sonarqube"]["sources"] == "src"


def test_configure_connection_success():
    """Configure connection with valid server."""
    with (
        patch("a_sdlc.sonarqube_setup.check_sonarqube_reachable") as mock_reach,
        patch("a_sdlc.sonarqube_setup.save_sonarqube_config") as mock_save,
    ):
        mock_reach.return_value = (True, "SonarQube is running")
        mock_save.return_value = (True, "Saved")
        ok, msg = configure_connection("http://localhost:9000", "token123")

    assert ok is True
    assert "configured" in msg.lower() or "running" in msg.lower()


def test_configure_connection_unreachable():
    """Configure connection fails when server unreachable."""
    with patch("a_sdlc.sonarqube_setup.check_sonarqube_reachable") as mock_reach:
        mock_reach.return_value = (False, "Cannot reach server")
        ok, msg = configure_connection("http://localhost:9000", "token123")

    assert ok is False
    assert "Cannot reach" in msg


def test_configure_project_defaults(tmp_path):
    """Configure project with default values."""
    ok, msg = configure_project(
        project_key="my-project",
        project_dir=tmp_path,
    )

    assert ok is True
    import yaml
    data = yaml.safe_load((tmp_path / ".sdlc" / "config.yaml").read_text())
    assert data["sonarqube"]["project_key"] == "my-project"
    assert data["sonarqube"]["sources"] == "src"
    assert data["sonarqube"]["fix_severities"] == DEFAULT_FIX_SEVERITIES


def test_configure_project_custom_severities(tmp_path):
    """Configure project with custom fix severities."""
    ok, msg = configure_project(
        project_key="my-project",
        fix_severities=["BLOCKER", "CRITICAL"],
        project_dir=tmp_path,
    )

    assert ok is True
    import yaml
    data = yaml.safe_load((tmp_path / ".sdlc" / "config.yaml").read_text())
    assert data["sonarqube"]["fix_severities"] == ["BLOCKER", "CRITICAL"]


# ---------------------------------------------------------------------------
# Scanner execution
# ---------------------------------------------------------------------------


def test_run_scanner_success(tmp_path):
    """Run scanner via pysonar successfully."""
    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text(
        "sonarqube:\n"
        "  token: mytoken\n"
        "  host_url: http://localhost:9000\n"
        "  project_key: my-project\n"
    )

    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("")

    with (
        patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg),
        patch("a_sdlc.sonarqube_setup.check_scanner_available", return_value=(True, "pysonar")),
        patch("a_sdlc.sonarqube_setup.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok, msg = run_scanner(project_dir=tmp_path)

    assert ok is True
    assert "completed" in msg.lower()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "pysonar"
    assert "--sonar-host-url=http://localhost:9000" in cmd
    assert "--sonar-token=mytoken" in cmd
    assert "--sonar-project-key=my-project" in cmd


def test_run_scanner_with_extra_args(tmp_path):
    """Extra args are appended to pysonar command."""
    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text(
        "sonarqube:\n"
        "  token: mytoken\n"
        "  host_url: http://localhost:9000\n"
        "  project_key: my-project\n"
    )

    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("")

    with (
        patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg),
        patch("a_sdlc.sonarqube_setup.check_scanner_available", return_value=(True, "pysonar")),
        patch("a_sdlc.sonarqube_setup.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ok, msg = run_scanner(project_dir=tmp_path, extra_args=["--sonar-sources=src"])

    assert ok is True
    cmd = mock_run.call_args[0][0]
    assert "--sonar-sources=src" in cmd


def test_run_scanner_fails(tmp_path):
    """Scanner returns non-zero exit code."""
    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text(
        "sonarqube:\n"
        "  token: mytoken\n"
        "  host_url: http://localhost:9000\n"
        "  project_key: my-project\n"
    )

    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("")

    with (
        patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg),
        patch("a_sdlc.sonarqube_setup.check_scanner_available", return_value=(True, "pysonar")),
        patch("a_sdlc.sonarqube_setup.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Analysis failed")
        ok, msg = run_scanner(project_dir=tmp_path)

    assert ok is False
    assert "failed" in msg.lower()


def test_run_scanner_timeout(tmp_path):
    """Scanner times out."""
    import subprocess as real_subprocess

    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text(
        "sonarqube:\n"
        "  token: mytoken\n"
        "  host_url: http://localhost:9000\n"
        "  project_key: my-project\n"
    )

    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("")

    with (
        patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg),
        patch("a_sdlc.sonarqube_setup.check_scanner_available", return_value=(True, "pysonar")),
        patch("a_sdlc.sonarqube_setup.subprocess.run", side_effect=real_subprocess.TimeoutExpired("pysonar", 600)),
    ):
        ok, msg = run_scanner(project_dir=tmp_path)

    assert ok is False
    assert "timed out" in msg.lower()


def test_run_scanner_no_token(tmp_path):
    """Scanner fails without token."""
    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("")

    with patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg):
        ok, msg = run_scanner(project_dir=tmp_path)

    assert ok is False
    assert "token" in msg.lower()


def test_run_scanner_needs_host_url(tmp_path):
    """Scanner fails without host_url."""
    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text("sonarqube:\n  token: mytoken\n")

    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("")

    with patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg):
        ok, msg = run_scanner(project_dir=tmp_path)

    assert ok is False
    assert "host_url" in msg.lower()


def test_run_scanner_needs_project_key(tmp_path):
    """Scanner fails without project_key."""
    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text("sonarqube:\n  token: mytoken\n  host_url: http://localhost:9000\n")

    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("")

    with patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg):
        ok, msg = run_scanner(project_dir=tmp_path)

    assert ok is False
    assert "project_key" in msg.lower()


# ---------------------------------------------------------------------------
# API requests
# ---------------------------------------------------------------------------


def test_api_request_success():
    """Successful API request."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"status": "UP"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("a_sdlc.sonarqube_setup.urllib.request.urlopen", return_value=mock_response):
        ok, data = _api_request("http://localhost:9000", "/api/system/status", "token123")

    assert ok is True
    assert data["status"] == "UP"


def test_api_request_with_params():
    """API request with query parameters."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"result": "ok"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("a_sdlc.sonarqube_setup.urllib.request.urlopen", return_value=mock_response) as mock_open:
        ok, data = _api_request(
            "http://localhost:9000", "/api/test", "token123",
            params={"key": "value"},
        )

    assert ok is True
    # Check URL includes params
    call_args = mock_open.call_args[0][0]
    assert "key=value" in call_args.full_url


def test_api_request_http_error():
    """API request returns HTTP error."""
    import urllib.error
    with patch(
        "a_sdlc.sonarqube_setup.urllib.request.urlopen",
        side_effect=urllib.error.HTTPError(
            "http://localhost:9000", 401, "Unauthorized", {}, None
        ),
    ):
        ok, msg = _api_request("http://localhost:9000", "/api/test", "bad-token")

    assert ok is False
    assert "401" in msg


def test_api_request_connection_error():
    """API request with connection failure."""
    import urllib.error
    with patch(
        "a_sdlc.sonarqube_setup.urllib.request.urlopen",
        side_effect=urllib.error.URLError("Connection refused"),
    ):
        ok, msg = _api_request("http://localhost:9000", "/api/test", "token123")

    assert ok is False
    assert "Connection error" in msg


def test_get_quality_gate_status_success():
    """Fetch quality gate status."""
    with patch("a_sdlc.sonarqube_setup._api_request") as mock_api:
        mock_api.return_value = (True, {
            "projectStatus": {"status": "OK", "conditions": []}
        })
        ok, data = get_quality_gate_status("http://localhost:9000", "token", "my-project")

    assert ok is True
    assert data["status"] == "OK"


def test_get_quality_gate_status_failure():
    """Quality gate fetch fails."""
    with patch("a_sdlc.sonarqube_setup._api_request") as mock_api:
        mock_api.return_value = (False, "Not found")
        ok, data = get_quality_gate_status("http://localhost:9000", "token", "bad-project")

    assert ok is False
    assert "error" in data


def test_get_issues_success():
    """Fetch issues with severity filter."""
    with patch("a_sdlc.sonarqube_setup._api_request") as mock_api:
        mock_api.return_value = (True, {
            "issues": [
                {"severity": "CRITICAL", "message": "SQL injection", "component": "proj:src/db.py", "line": 42, "type": "VULNERABILITY"},
                {"severity": "MAJOR", "message": "Unused variable", "component": "proj:src/utils.py", "line": 10, "type": "CODE_SMELL"},
            ]
        })
        ok, issues = get_issues(
            "http://localhost:9000", "token", "my-project",
            severities=["CRITICAL", "MAJOR"],
        )

    assert ok is True
    assert len(issues) == 2
    assert issues[0]["severity"] == "CRITICAL"
    # Check params were passed correctly
    call_params = mock_api.call_args[1]["params"]
    assert "CRITICAL,MAJOR" in call_params["severities"]


def test_get_issues_failure():
    """Issues fetch fails."""
    with patch("a_sdlc.sonarqube_setup._api_request") as mock_api:
        mock_api.return_value = (False, "Not found")
        ok, issues = get_issues("http://localhost:9000", "token", "bad-project")

    assert ok is False
    assert issues == []


def test_get_metrics_success():
    """Fetch project metrics."""
    with patch("a_sdlc.sonarqube_setup._api_request") as mock_api:
        mock_api.return_value = (True, {
            "component": {
                "measures": [
                    {"metric": "bugs", "value": "3"},
                    {"metric": "coverage", "value": "78.3"},
                ]
            }
        })
        ok, metrics = get_metrics("http://localhost:9000", "token", "my-project")

    assert ok is True
    assert metrics["bugs"] == "3"
    assert metrics["coverage"] == "78.3"


def test_get_metrics_failure():
    """Metrics fetch fails."""
    with patch("a_sdlc.sonarqube_setup._api_request") as mock_api:
        mock_api.return_value = (False, "Error")
        ok, metrics = get_metrics("http://localhost:9000", "token", "my-project")

    assert ok is False
    assert "error" in metrics


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def test_format_quality_report():
    """Format a complete quality report."""
    quality_gate = {"status": "OK"}
    metrics = {"bugs": "3", "vulnerabilities": "0", "code_smells": "24", "coverage": "78.3"}
    issues = [
        {"severity": "CRITICAL", "message": "SQL injection", "component": "proj:src/handler.py", "line": 45, "type": "VULNERABILITY"},
        {"severity": "MAJOR", "message": "Unused import", "component": "proj:src/utils.py", "line": 1, "type": "CODE_SMELL"},
    ]

    report = _format_quality_report(quality_gate, metrics, issues, "my-project", "http://localhost:9000")

    assert "# Code Quality Report" in report
    assert "my-project" in report
    assert "Quality Gate: OK" in report
    assert "Bugs" in report
    assert "3" in report
    assert "CRITICAL (1)" in report
    assert "SQL injection" in report
    assert "src/handler.py" in report
    assert "MAJOR (1)" in report


def test_format_quality_report_no_issues():
    """Report with no issues."""
    report = _format_quality_report({}, {}, [], "my-project", "http://localhost:9000")
    assert "No open issues found" in report


def test_generate_artifact_success(tmp_path):
    """Generate code-quality.md artifact."""
    # Set up config
    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text(
        "sonarqube:\n"
        "  host_url: http://localhost:9000\n"
        "  token: mytoken\n"
        "  project_key: my-project\n"
    )

    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("")

    with (
        patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg),
        patch("a_sdlc.sonarqube_setup.get_quality_gate_status", return_value=(True, {"status": "OK"})),
        patch("a_sdlc.sonarqube_setup.get_metrics", return_value=(True, {"bugs": "0"})),
        patch("a_sdlc.sonarqube_setup.get_issues", return_value=(True, [])),
    ):
        ok, msg = generate_code_quality_artifact(project_dir=tmp_path)

    assert ok is True
    artifact = tmp_path / ".sdlc" / "artifacts" / "code-quality.md"
    assert artifact.exists()
    content = artifact.read_text()
    assert "Code Quality Report" in content


def test_generate_artifact_not_configured(tmp_path):
    """Artifact generation fails without config."""
    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("")

    with patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg):
        ok, msg = generate_code_quality_artifact(project_dir=tmp_path)

    assert ok is False
    assert "not fully configured" in msg


def test_generate_artifact_api_failure(tmp_path):
    """Artifact generation handles complete API failure."""
    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text(
        "sonarqube:\n"
        "  host_url: http://localhost:9000\n"
        "  token: mytoken\n"
        "  project_key: my-project\n"
    )

    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("")

    with (
        patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg),
        patch("a_sdlc.sonarqube_setup.get_quality_gate_status", return_value=(False, {"error": "connection refused"})),
        patch("a_sdlc.sonarqube_setup.get_metrics", return_value=(False, {"error": "connection refused"})),
        patch("a_sdlc.sonarqube_setup.get_issues", return_value=(False, [])),
    ):
        ok, msg = generate_code_quality_artifact(project_dir=tmp_path)

    assert ok is False
    assert "Failed to fetch" in msg


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def test_verify_setup_unconfigured(tmp_path):
    """Verify returns not ready when unconfigured."""
    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text("")

    with patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg):
        results = verify_sonarqube_setup(project_dir=tmp_path)

    assert results["ready"] is False
    assert results["host_url_configured"] is False
    assert results["token_configured"] is False


def test_verify_setup_configured(tmp_path):
    """Verify returns ready when fully configured."""
    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text(
        "sonarqube:\n"
        "  project_key: my-project\n"
        "  sources: src\n"
    )

    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text(
        "sonarqube:\n"
        "  host_url: http://localhost:9000\n"
        "  token: mytoken\n"
    )

    with (
        patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg),
        patch("a_sdlc.sonarqube_setup.check_scanner_available", return_value=(True, "pysonar")),
        patch("a_sdlc.sonarqube_setup.check_sonarqube_reachable", return_value=(True, "Running")),
    ):
        results = verify_sonarqube_setup(project_dir=tmp_path)

    assert results["ready"] is True
    assert results["scanner_available"] is True
    assert results["sonarqube_reachable"] is True


def test_verify_setup_no_scanner(tmp_path):
    """Verify shows scanner not available."""
    global_cfg = tmp_path / "global" / "config.yaml"
    global_cfg.parent.mkdir(parents=True)
    global_cfg.write_text(
        "sonarqube:\n"
        "  host_url: http://localhost:9000\n"
        "  token: mytoken\n"
    )

    project_cfg = tmp_path / ".sdlc" / "config.yaml"
    project_cfg.parent.mkdir(parents=True)
    project_cfg.write_text("sonarqube:\n  project_key: proj\n")

    with (
        patch("a_sdlc.sonarqube_setup.GLOBAL_CONFIG_PATH", global_cfg),
        patch("a_sdlc.sonarqube_setup.check_scanner_available", return_value=(False, "Not found")),
        patch("a_sdlc.sonarqube_setup.check_sonarqube_reachable", return_value=(True, "Running")),
    ):
        results = verify_sonarqube_setup(project_dir=tmp_path)

    assert results["ready"] is False
    assert results["scanner_available"] is False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def test_setup_sonarqube_success(tmp_path):
    """Full setup succeeds."""
    with (
        patch("a_sdlc.sonarqube_setup.check_scanner_available", return_value=(True, "pysonar")),
        patch("a_sdlc.sonarqube_setup.configure_connection", return_value=(True, "Connected")),
        patch("a_sdlc.sonarqube_setup.configure_project", return_value=(True, "Configured")),
        patch("a_sdlc.sonarqube_setup.verify_sonarqube_setup", return_value={"ready": True}),
    ):
        ok, msg, verification = setup_sonarqube(
            host_url="http://localhost:9000",
            token="token123",
            project_key="my-project",
            project_dir=tmp_path,
        )

    assert ok is True
    assert verification["ready"] is True


def test_setup_sonarqube_no_scanner():
    """Setup fails without scanner."""
    with patch("a_sdlc.sonarqube_setup.check_scanner_available", return_value=(False, "Not found")):
        ok, msg, verification = setup_sonarqube(
            host_url="http://localhost:9000",
            token="token123",
            project_key="my-project",
        )

    assert ok is False
    assert verification == {}


def test_setup_sonarqube_connection_fails():
    """Setup fails when connection test fails."""
    with (
        patch("a_sdlc.sonarqube_setup.check_scanner_available", return_value=(True, "pysonar")),
        patch("a_sdlc.sonarqube_setup.configure_connection", return_value=(False, "Cannot connect")),
    ):
        ok, msg, verification = setup_sonarqube(
            host_url="http://localhost:9000",
            token="bad-token",
            project_key="my-project",
        )

    assert ok is False
    assert "Cannot connect" in msg


def test_setup_sonarqube_with_custom_severities(tmp_path):
    """Setup passes custom fix_severities."""
    with (
        patch("a_sdlc.sonarqube_setup.check_scanner_available", return_value=(True, "pysonar")),
        patch("a_sdlc.sonarqube_setup.configure_connection", return_value=(True, "Connected")),
        patch("a_sdlc.sonarqube_setup.configure_project") as mock_configure,
        patch("a_sdlc.sonarqube_setup.verify_sonarqube_setup", return_value={"ready": True}),
    ):
        mock_configure.return_value = (True, "Configured")
        ok, msg, verification = setup_sonarqube(
            host_url="http://localhost:9000",
            token="token123",
            project_key="my-project",
            fix_severities=["BLOCKER"],
            project_dir=tmp_path,
        )

    assert ok is True
    mock_configure.assert_called_once_with(
        project_key="my-project",
        sources="src",
        exclusions=None,
        fix_severities=["BLOCKER"],
        project_dir=tmp_path,
    )
