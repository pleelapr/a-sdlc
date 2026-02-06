"""
SonarQube code analysis integration.

Handles:
- Detecting pysonar availability
- Validating connection to SonarQube/SonarCloud instances
- Managing configuration in ~/.config/a-sdlc/config.yaml + .sdlc/config.yaml
- Running pysonar scanner
- Fetching analysis results via SonarQube Web API
- Generating code-quality.md artifact
"""

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

GLOBAL_CONFIG_DIR = Path.home() / ".config" / "a-sdlc"
GLOBAL_CONFIG_PATH = GLOBAL_CONFIG_DIR / "config.yaml"

DEFAULT_FIX_SEVERITIES = ["BLOCKER", "CRITICAL", "MAJOR"]


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------


def check_scanner_available() -> tuple[bool, str]:
    """Detect pysonar availability.

    Returns:
        Tuple of (available, message) where message is "pysonar" on success
        or an error message on failure.
    """
    if shutil.which("pysonar"):
        return True, "pysonar"

    return False, "pysonar not found. Install with: uv tool install pysonar"


def check_sonarqube_reachable(host_url: str, token: str) -> tuple[bool, str]:
    """Check if SonarQube instance is reachable.

    Sends GET /api/system/status to verify the instance is up.

    Args:
        host_url: SonarQube base URL (e.g., http://localhost:9000)
        token: Authentication token

    Returns:
        Tuple of (reachable, message)
    """
    success, result = _api_request(host_url, "/api/system/status", token)
    if not success:
        return False, f"Cannot reach SonarQube at {host_url}: {result}"

    status = result.get("status", "UNKNOWN")
    if status == "UP":
        return True, f"SonarQube is running at {host_url} (status: {status})"

    return False, f"SonarQube at {host_url} is not ready (status: {status})"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_sonarqube_config(project_dir: Path | None = None) -> dict:
    """Load SonarQube configuration, merging global and project configs.

    Global config (~/.config/a-sdlc/config.yaml) provides host_url and token.
    Project config (.sdlc/config.yaml) provides project_key, sources, etc.
    Project config values override global config values.

    Args:
        project_dir: Project root directory. If None, uses cwd.

    Returns:
        Merged configuration dict.
    """
    config: dict = {}

    # Load global config
    if GLOBAL_CONFIG_PATH.exists():
        try:
            raw = yaml.safe_load(GLOBAL_CONFIG_PATH.read_text()) or {}
            config.update(raw.get("sonarqube", {}))
        except (yaml.YAMLError, OSError):
            pass

    # Load project config
    if project_dir is None:
        project_dir = Path.cwd()

    project_config_path = project_dir / ".sdlc" / "config.yaml"
    if project_config_path.exists():
        try:
            raw = yaml.safe_load(project_config_path.read_text()) or {}
            project_sq = raw.get("sonarqube", {})
            if project_sq:
                config.update(project_sq)
        except (yaml.YAMLError, OSError):
            pass

    return config


def save_sonarqube_config(
    config: dict,
    target: str = "global",
    project_dir: Path | None = None,
) -> tuple[bool, str]:
    """Save SonarQube configuration to the appropriate config file.

    Args:
        config: Configuration dict with sonarqube settings.
        target: "global" for ~/.config/a-sdlc/config.yaml,
                "project" for .sdlc/config.yaml
        project_dir: Project root directory for project target. If None, uses cwd.

    Returns:
        Tuple of (success, message)
    """
    try:
        if target == "global":
            config_path = GLOBAL_CONFIG_PATH
            GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        else:
            if project_dir is None:
                project_dir = Path.cwd()
            config_path = project_dir / ".sdlc" / "config.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config to merge
        existing: dict = {}
        if config_path.exists():
            try:
                existing = yaml.safe_load(config_path.read_text()) or {}
            except yaml.YAMLError:
                existing = {}

        existing.setdefault("sonarqube", {}).update(config)

        config_path.write_text(yaml.dump(existing, default_flow_style=False))
        return True, f"Configuration saved to {config_path}"

    except OSError as e:
        return False, f"Failed to save configuration: {e}"


def configure_connection(
    host_url: str,
    token: str,
) -> tuple[bool, str]:
    """Validate connection and save to global config.

    Args:
        host_url: SonarQube base URL
        token: Authentication token

    Returns:
        Tuple of (success, message)
    """
    # Validate connection first
    reachable, msg = check_sonarqube_reachable(host_url, token)
    if not reachable:
        return False, msg

    # Save to global config
    success, save_msg = save_sonarqube_config(
        {"host_url": host_url, "token": token},
        target="global",
    )
    if not success:
        return False, save_msg

    return True, f"Connection configured: {msg}"


def configure_project(
    project_key: str,
    sources: str = "src",
    exclusions: str | None = None,
    fix_severities: list[str] | None = None,
    project_dir: Path | None = None,
) -> tuple[bool, str]:
    """Save project-level SonarQube configuration.

    Args:
        project_key: SonarQube project key
        sources: Source directories (comma-separated)
        exclusions: Exclusion patterns (comma-separated)
        fix_severities: Severity levels for auto-fix
        project_dir: Project root directory

    Returns:
        Tuple of (success, message)
    """
    config: dict = {
        "project_key": project_key,
        "sources": sources,
    }

    if exclusions is not None:
        config["exclusions"] = exclusions

    if fix_severities is not None:
        config["fix_severities"] = fix_severities
    else:
        config["fix_severities"] = DEFAULT_FIX_SEVERITIES

    return save_sonarqube_config(config, target="project", project_dir=project_dir)


# ---------------------------------------------------------------------------
# Scanner execution
# ---------------------------------------------------------------------------


def run_scanner(
    project_dir: Path | None = None,
    extra_args: list[str] | None = None,
) -> tuple[bool, str]:
    """Run pysonar to analyze the project.

    Args:
        project_dir: Project root directory. If None, uses cwd.
        extra_args: Additional arguments to pass to pysonar.

    Returns:
        Tuple of (success, message)
    """
    if project_dir is None:
        project_dir = Path.cwd()

    config = load_sonarqube_config(project_dir)
    token = config.get("token")
    if not token:
        return False, "Token not configured. Run: a-sdlc sonarqube configure"

    host_url = config.get("host_url")
    if not host_url:
        return False, "host_url not configured. Run: a-sdlc sonarqube configure"

    project_key = config.get("project_key")
    if not project_key:
        return False, "project_key not configured. Run: a-sdlc sonarqube configure"

    available, msg = check_scanner_available()
    if not available:
        return False, msg

    cmd = [
        "pysonar",
        f"--sonar-host-url={host_url}",
        f"--sonar-token={token}",
        f"--sonar-project-key={project_key}",
    ]
    if extra_args:
        cmd.extend(extra_args)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=600,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            return False, f"Scanner failed (exit {result.returncode}): {stderr}"

        return True, "Scan completed successfully"

    except subprocess.TimeoutExpired:
        return False, "Scanner timed out (>10 minutes)"
    except FileNotFoundError as e:
        return False, f"Scanner not found: {e}"


# ---------------------------------------------------------------------------
# API requests
# ---------------------------------------------------------------------------


def _api_request(
    host_url: str,
    endpoint: str,
    token: str,
    params: dict | None = None,
) -> tuple[bool, dict | str]:
    """Make an authenticated request to the SonarQube API.

    Uses HTTP Basic auth with token as username and empty password.

    Args:
        host_url: SonarQube base URL
        endpoint: API endpoint (e.g., "/api/system/status")
        token: Authentication token
        params: Query parameters

    Returns:
        Tuple of (success, response_data_or_error_message)
    """
    url = f"{host_url.rstrip('/')}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url)
    # SonarQube uses token as username with empty password for basic auth
    import base64
    credentials = base64.b64encode(f"{token}:".encode()).decode()
    req.add_header("Authorization", f"Basic {credentials}")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return True, data
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, f"Connection error: {e.reason}"
    except (json.JSONDecodeError, OSError) as e:
        return False, f"Request failed: {e}"


def get_quality_gate_status(
    host_url: str,
    token: str,
    project_key: str,
) -> tuple[bool, dict]:
    """Get quality gate status for a project.

    Args:
        host_url: SonarQube base URL
        token: Authentication token
        project_key: SonarQube project key

    Returns:
        Tuple of (success, quality_gate_data)
    """
    success, result = _api_request(
        host_url,
        "/api/qualitygates/project_status",
        token,
        params={"projectKey": project_key},
    )
    if not success:
        return False, {"error": result}

    return True, result.get("projectStatus", result)


def get_issues(
    host_url: str,
    token: str,
    project_key: str,
    severities: list[str] | None = None,
    types: list[str] | None = None,
    page_size: int = 100,
) -> tuple[bool, list[dict]]:
    """Get issues for a project.

    Args:
        host_url: SonarQube base URL
        token: Authentication token
        project_key: SonarQube project key
        severities: Filter by severity (BLOCKER, CRITICAL, MAJOR, MINOR, INFO)
        types: Filter by type (BUG, VULNERABILITY, CODE_SMELL)
        page_size: Number of issues per page

    Returns:
        Tuple of (success, list_of_issues)
    """
    params: dict = {
        "componentKeys": project_key,
        "ps": str(page_size),
        "statuses": "OPEN,CONFIRMED,REOPENED",
    }

    if severities:
        params["severities"] = ",".join(severities)
    if types:
        params["types"] = ",".join(types)

    success, result = _api_request(
        host_url,
        "/api/issues/search",
        token,
        params=params,
    )
    if not success:
        return False, []

    return True, result.get("issues", [])


def get_metrics(
    host_url: str,
    token: str,
    project_key: str,
    metric_keys: list[str] | None = None,
) -> tuple[bool, dict]:
    """Get metrics for a project.

    Args:
        host_url: SonarQube base URL
        token: Authentication token
        project_key: SonarQube project key
        metric_keys: Specific metrics to fetch

    Returns:
        Tuple of (success, metrics_dict)
    """
    if metric_keys is None:
        metric_keys = [
            "bugs",
            "vulnerabilities",
            "code_smells",
            "coverage",
            "duplicated_lines_density",
            "ncloc",
            "sqale_index",
            "reliability_rating",
            "security_rating",
            "sqale_rating",
        ]

    success, result = _api_request(
        host_url,
        "/api/measures/component",
        token,
        params={
            "component": project_key,
            "metricKeys": ",".join(metric_keys),
        },
    )
    if not success:
        return False, {"error": result}

    # Flatten measures into a simple dict
    measures = {}
    component = result.get("component", {})
    for measure in component.get("measures", []):
        measures[measure["metric"]] = measure.get("value", "N/A")

    return True, measures


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def generate_code_quality_artifact(
    project_dir: Path | None = None,
) -> tuple[bool, str]:
    """Fetch SonarQube results and generate code-quality.md artifact.

    Reads configuration, calls SonarQube API, and writes formatted
    report to .sdlc/artifacts/code-quality.md.

    Args:
        project_dir: Project root directory. If None, uses cwd.

    Returns:
        Tuple of (success, message)
    """
    if project_dir is None:
        project_dir = Path.cwd()

    config = load_sonarqube_config(project_dir)
    host_url = config.get("host_url")
    token = config.get("token")
    project_key = config.get("project_key")

    if not all([host_url, token, project_key]):
        return False, "SonarQube not fully configured. Run: a-sdlc sonarqube configure"

    # Fetch data from API
    qg_ok, quality_gate = get_quality_gate_status(host_url, token, project_key)
    metrics_ok, metrics = get_metrics(host_url, token, project_key)
    issues_ok, issues = get_issues(host_url, token, project_key)

    if not qg_ok and not metrics_ok and not issues_ok:
        return False, f"Failed to fetch results from SonarQube: {quality_gate.get('error', 'unknown error')}"

    # Generate report
    report = _format_quality_report(
        quality_gate if qg_ok else {},
        metrics if metrics_ok else {},
        issues if issues_ok else [],
        project_key,
        host_url,
    )

    # Write artifact
    artifacts_dir = project_dir / ".sdlc" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifacts_dir / "code-quality.md"

    try:
        artifact_path.write_text(report)
        return True, f"Code quality report generated: {artifact_path}"
    except OSError as e:
        return False, f"Failed to write artifact: {e}"


def _format_quality_report(
    quality_gate: dict,
    metrics: dict,
    issues: list[dict],
    project_key: str,
    host_url: str,
) -> str:
    """Format SonarQube results into a markdown report.

    Args:
        quality_gate: Quality gate status data
        metrics: Metrics dict
        issues: List of issue dicts
        project_key: Project key
        host_url: SonarQube host URL

    Returns:
        Formatted markdown report string
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    qg_status = quality_gate.get("status", "UNKNOWN")

    lines = [
        "# Code Quality Report",
        f"**Project:** {project_key} | **Analyzed:** {now} | **Source:** {host_url}",
        "",
        f"## Quality Gate: {qg_status}",
        "",
    ]

    # Metrics table
    if metrics:
        lines.extend([
            "## Key Metrics",
            "| Metric | Value |",
            "|--------|-------|",
        ])
        metric_labels = {
            "bugs": "Bugs",
            "vulnerabilities": "Vulnerabilities",
            "code_smells": "Code Smells",
            "coverage": "Coverage (%)",
            "duplicated_lines_density": "Duplicated Lines (%)",
            "ncloc": "Lines of Code",
            "sqale_index": "Technical Debt (min)",
            "reliability_rating": "Reliability Rating",
            "security_rating": "Security Rating",
            "sqale_rating": "Maintainability Rating",
        }
        for key, label in metric_labels.items():
            if key in metrics:
                lines.append(f"| {label} | {metrics[key]} |")
        lines.append("")

    # Issues by severity
    if issues:
        severity_order = ["BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"]
        issues_by_severity: dict[str, list[dict]] = {}
        for issue in issues:
            sev = issue.get("severity", "UNKNOWN")
            issues_by_severity.setdefault(sev, []).append(issue)

        lines.append("## Issues by Severity")
        lines.append("")

        for severity in severity_order:
            sev_issues = issues_by_severity.get(severity, [])
            if not sev_issues:
                continue

            lines.append(f"### {severity} ({len(sev_issues)})")
            lines.append("| File | Line | Message | Type |")
            lines.append("|------|------|---------|------|")

            for issue in sev_issues:
                component = issue.get("component", "")
                # Strip project key prefix from component path
                file_path = component.split(":")[-1] if ":" in component else component
                line_num = issue.get("line", "—")
                message = issue.get("message", "").replace("|", "\\|")
                issue_type = issue.get("type", "")
                lines.append(f"| {file_path} | {line_num} | {message} | {issue_type} |")

            lines.append("")

    if not issues:
        lines.extend([
            "## Issues",
            "",
            "No open issues found.",
            "",
        ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_sonarqube_setup(
    project_dir: Path | None = None,
) -> dict[str, bool | str]:
    """Verify SonarQube configuration and connectivity.

    Args:
        project_dir: Project root directory. If None, uses cwd.

    Returns:
        Dict with verification results for each component.
    """
    results: dict[str, bool | str] = {}

    config = load_sonarqube_config(project_dir)

    # Scanner availability
    scanner_ok, _scanner_msg = check_scanner_available()
    results["scanner_available"] = scanner_ok

    # Global config
    results["host_url_configured"] = bool(config.get("host_url"))
    results["token_configured"] = bool(config.get("token"))

    # Project config
    results["project_key_configured"] = bool(config.get("project_key"))
    results["sources_configured"] = bool(config.get("sources"))

    # Connection test (only if configured)
    if config.get("host_url") and config.get("token"):
        reachable, msg = check_sonarqube_reachable(
            config["host_url"], config["token"]
        )
        results["sonarqube_reachable"] = reachable
        results["connection_message"] = msg
    else:
        results["sonarqube_reachable"] = False
        results["connection_message"] = "Not configured"

    # Overall readiness
    results["ready"] = bool(
        results["scanner_available"]
        and results["host_url_configured"]
        and results["token_configured"]
        and results["project_key_configured"]
    )

    return results


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def setup_sonarqube(
    host_url: str,
    token: str,
    project_key: str,
    sources: str = "src",
    exclusions: str | None = None,
    fix_severities: list[str] | None = None,
    project_dir: Path | None = None,
) -> tuple[bool, str, dict]:
    """Complete SonarQube setup: validate and configure.

    Args:
        host_url: SonarQube base URL
        token: Authentication token
        project_key: SonarQube project key
        sources: Source directories
        exclusions: Exclusion patterns
        fix_severities: Severity levels for auto-fix
        project_dir: Project root directory

    Returns:
        Tuple of (success, message, verification_results)
    """
    messages = []

    # Check scanner prerequisites
    scanner_ok, scanner_info = check_scanner_available()
    if not scanner_ok:
        return False, scanner_info, {}

    messages.append(f"Scanner available: {scanner_info}")

    # Validate connection
    success, msg = configure_connection(host_url, token)
    if not success:
        return False, msg, {}
    messages.append(msg)

    # Configure project
    success, msg = configure_project(
        project_key=project_key,
        sources=sources,
        exclusions=exclusions,
        fix_severities=fix_severities,
        project_dir=project_dir,
    )
    if not success:
        return False, msg, {}
    messages.append(msg)

    # Verify
    verification = verify_sonarqube_setup(project_dir=project_dir)

    return True, "\n".join(messages), verification
