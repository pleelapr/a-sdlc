"""
Main CLI for a-sdlc package.

Provides commands for:
- install: Deploy skill templates to Claude Code
- uninstall: Remove all a-sdlc components
- setup-mcp: Install and configure Serena MCP
- doctor: System diagnostics
- plugins: Plugin management
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from alembic.config import Config as AlembicConfig

    from a_sdlc.artifacts import ArtifactPluginManager
    from a_sdlc.plugins import PluginManager

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from a_sdlc import __version__
from a_sdlc.artifacts import get_artifact_plugin_manager
from a_sdlc.cli_targets import detect_targets, resolve_targets
from a_sdlc.installer import (
    Installer,
    check_python_version,
    check_uv_available,
    configure_mcp_server,
    get_claude_settings_path,
)
from a_sdlc.mcp_setup import (
    setup_serena,
    verify_setup,
)
from a_sdlc.monitoring_setup import (
    MONITORING_DIR,
    check_docker_available,
    check_services_health,
    configure_langfuse_keys,
    setup_monitoring,
    verify_monitoring_setup,
)
from a_sdlc.plugins import get_plugin_manager
from a_sdlc.sonarqube_setup import (
    check_scanner_available,
    generate_code_quality_artifact,
    run_scanner,
    setup_sonarqube,
    verify_sonarqube_setup,
)

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="a-sdlc")
def main() -> None:
    """SDLC Automation System for Claude Code.

    Generates and maintains BrainGrid-style documentation artifacts,
    enabling better codebase understanding and streamlined workflows.
    """
    pass


@main.command()
@click.option(
    "--mcp-port",
    default=int(os.environ.get("PORT", os.environ.get("A_SDLC_MCP_PORT", "8765"))),
    type=int,
    help="MCP server port (default: $PORT or $A_SDLC_MCP_PORT or 8765)",
)
@click.option(
    "--ui-port",
    default=int(os.environ.get("A_SDLC_UI_PORT", "3847")),
    type=int,
    help="UI dashboard port (default: $A_SDLC_UI_PORT or 3847)",
)
@click.option(
    "--host",
    default="0.0.0.0",
    help="Bind address (default: 0.0.0.0)",
)
def serve(
    mcp_port: int,
    ui_port: int,
    host: str,
) -> None:
    """Start the combined MCP + UI server.

    Runs the MCP server (streamable-http) and web UI dashboard in a
    single process.  This is the primary way to run a-sdlc.

    For production deployment, use Docker Compose instead:
        docker compose up -d

    Examples:

        a-sdlc serve                                    # Default ports
        a-sdlc serve --mcp-port 9000 --ui-port 9001    # Custom ports
    """
    from a_sdlc.server import run_server

    console.print(
        f"[cyan]Starting combined MCP+UI server "
        f"(MCP: {host}:{mcp_port}, UI: {host}:{ui_port})[/cyan]"
    )
    try:
        run_server(mcp_port=mcp_port, ui_port=ui_port, host=host)
    except SystemExit:
        raise
    except Exception as exc:
        console.print(f"[red]Server error: {exc}[/red]")
        raise SystemExit(1) from exc


@main.command()
@click.option("--list", "list_skills", is_flag=True, help="List all installed skill templates")
@click.option("--force", "-f", is_flag=True, help="Force reinstall of all templates")
@click.option(
    "--target-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Custom target directory (overrides default commands location)",
)
@click.option(
    "--target",
    "cli_target",
    type=click.Choice(["claude", "gemini", "auto"]),
    default="auto",
    help="Target CLI to install for (default: auto-detect)",
)
@click.option(
    "--with-playwright",
    is_flag=True,
    help="Also configure Playwright MCP server for runtime testing",
)
@click.option(
    "--no-agent-teams", is_flag=True, help="Skip enabling Agent Teams experimental feature"
)
@click.option(
    "--url",
    default=None,
    help="MCP server URL for Docker/cloud instances (e.g., http://my-host:19765/mcp)",
)
@click.option(
    "--auth-token",
    default=None,
    help="Bearer token for MCP server authentication (written to client config headers)",
)
def install(
    list_skills: bool,
    force: bool,
    target_dir: Path | None,
    cli_target: str,
    with_playwright: bool,
    no_agent_teams: bool,
    url: str | None,
    auth_token: str | None,
) -> None:
    """Deploy skill templates to Claude Code (non-interactive).

    For interactive setup with optional integrations, use: a-sdlc setup

    Examples:

        a-sdlc install                    # Install all templates (HTTP config)
        a-sdlc install --list             # List installed templates
        a-sdlc install --force            # Reinstall all templates
        a-sdlc install --target claude    # Install for Claude Code only
        a-sdlc install --target gemini    # Install for Gemini CLI only
        a-sdlc install --url http://my-host:19765/mcp  # Docker/cloud instance
        a-sdlc install --url https://example.com/mcp --auth-token mytoken  # With auth
    """
    targets = resolve_targets(cli_target)
    if not targets:
        console.print(
            "[red]No supported CLI tools detected. Install Claude Code or Gemini CLI first.[/red]"
        )
        sys.exit(1)

    if list_skills:
        installer = Installer(target_dir=target_dir, target=targets[0])
        _list_installed_skills(installer)
        return

    try:
        all_installed = []
        all_personas = []
        target_names = []
        for t in targets:
            installer = Installer(target_dir=target_dir, target=t)
            installed = installer.install(force=force, url=url, auth_token=auth_token)
            all_installed.extend(installed)
            personas = installer.list_installed_personas()
            all_personas.extend(personas)
            target_names.append(t.display_name)

        # Configure Agent Teams env var (Claude only)
        agent_teams_status = ""
        if not no_agent_teams and any(t.name == "claude" for t in targets):
            try:
                from a_sdlc.mcp_setup import load_claude_settings, save_claude_settings

                settings = load_claude_settings()
                env = settings.setdefault("environment", {})
                env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"
                save_claude_settings(settings)
                agent_teams_status = "Agent Teams: [cyan]Enabled[/cyan]\n"
            except Exception:
                agent_teams_status = (
                    "Agent Teams: [yellow]Could not configure (settings.json issue)[/yellow]\n"
                )
        elif no_agent_teams:
            agent_teams_status = "Agent Teams: [dim]Skipped (--no-agent-teams)[/dim]\n"

        transport_line = ""
        if url:
            transport_line = f"Transport: [cyan]http[/cyan] → [cyan]{url}[/cyan]\n"
        else:
            transport_line = "Transport: [cyan]http[/cyan]\n"

        targets_str = ", ".join(target_names)
        persona_line = ""
        if all_personas:
            persona_line = f"Personas deployed: [cyan]{len(all_personas)} agent(s)[/cyan]\n"

        console.print()
        console.print(
            Panel(
                f"[green]Successfully installed {len(all_installed)} skill templates![/green]\n"
                f"Targets: [cyan]{targets_str}[/cyan]\n"
                f"{persona_line}"
                f"{transport_line}"
                f"{agent_teams_status}\n"
                "[dim]Run 'a-sdlc doctor' for detailed system diagnostics.[/dim]",
                title="[bold]Installation Complete[/bold]",
                border_style="green",
            )
        )

        if with_playwright:
            _setup_playwright_mcp(force=force)

    except Exception as e:
        console.print(f"[red]Error during installation: {e}[/red]")
        sys.exit(1)


def _setup_playwright_mcp(force: bool = False) -> None:
    """Set up Playwright MCP server for runtime testing."""
    from a_sdlc.playwright_setup import setup_playwright

    console.print("[bold cyan]Setting up Playwright MCP...[/bold cyan]")
    console.print()

    success, message, verification = setup_playwright(force=force)

    if success:
        console.print(
            Panel(
                f"[green]{message}[/green]\n\n"
                "[bold]Playwright MCP is ready![/bold]\n\n"
                "Restart Claude Code to activate runtime testing.",
                title="[bold green]Playwright Setup Complete[/bold green]",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"[red]{message}[/red]\n\n[dim]Fix: Ensure Node.js and npx are installed[/dim]",
                title="[bold red]Playwright Setup Failed[/bold red]",
                border_style="red",
            )
        )


@main.command()
@click.option(
    "--upgrade",
    is_flag=True,
    help="Force-refresh templates, migrate DB, update MCP config, then offer new integrations",
)
def setup(upgrade: bool):
    """Interactive setup wizard.

    First time: guides through prerequisites, installation, and optional integrations.
    Upgrade: force-refreshes everything and offers new integrations.

    Examples:

        a-sdlc setup             # First-time setup wizard
        a-sdlc setup --upgrade   # Update everything + discover new integrations
    """
    import json

    # Step 1: Welcome banner
    console.print()
    if upgrade:
        console.print(
            Panel(
                "[bold]Upgrading a-sdlc[/bold]\n\n"
                "This will:\n"
                "  1. Check prerequisites\n"
                "  2. Force-refresh all skill templates\n"
                "  3. Run database migration (with backup)\n"
                "  4. Update MCP server configuration\n"
                "  5. Offer new optional integrations",
                title="[bold cyan]a-sdlc Upgrade[/bold cyan]",
                border_style="cyan",
            )
        )
    else:
        console.print(
            Panel(
                "[bold]Welcome to a-sdlc Setup Wizard[/bold]\n\n"
                "This wizard will:\n"
                "  1. Check prerequisites (Python, uv, Claude Code)\n"
                "  2. Install skill templates\n"
                "  3. Configure the asdlc MCP server\n"
                "  4. Offer optional integrations (Serena, monitoring, etc.)\n"
                "  5. Validate the installation",
                title="[bold cyan]a-sdlc[/bold cyan]",
                border_style="cyan",
            )
        )
    console.print()

    # Step 2: Prerequisite checks
    console.print("[bold]Step 1: Checking prerequisites...[/bold]")
    console.print()

    checks = []
    has_critical_failure = False

    py_ok, py_msg = check_python_version()
    checks.append(("Python >= 3.10", py_ok, py_msg, True))
    if not py_ok:
        has_critical_failure = True

    uv_ok, uv_msg = check_uv_available()
    checks.append(("uv / uvx", uv_ok, uv_msg, False))

    detected = detect_targets()
    cli_ok = len(detected) > 0
    cli_msg = ", ".join(t.display_name for t in detected) if detected else "None found"
    checks.append(("CLI Targets", cli_ok, cli_msg, True))
    if not cli_ok:
        has_critical_failure = True

    table = Table(show_header=True, header_style="bold")
    table.add_column("Prerequisite", style="cyan")
    table.add_column("Status")
    table.add_column("Details", style="dim")

    for name, passed, detail, _critical in checks:
        if passed:
            status_str = "[green]PASS[/green]"
        elif _critical:
            status_str = "[red]FAIL[/red]"
        else:
            status_str = "[yellow]WARN[/yellow]"
        table.add_row(name, status_str, detail)

    console.print(table)
    console.print()

    if has_critical_failure:
        console.print("[red]Critical prerequisites not met. Please fix the following:[/red]")
        console.print()
        for name, passed, detail, critical in checks:
            if not passed and critical:
                console.print(f"  [red]{name}[/red]: {detail}")
                if "Python" in name:
                    console.print(
                        "  [dim]Fix: Install Python 3.10+ from https://www.python.org/downloads/[/dim]"
                    )
                elif "CLI" in name:
                    console.print(
                        "  [dim]Fix: Install Claude Code from https://claude.ai/code or Gemini CLI[/dim]"
                    )
        console.print()
        sys.exit(1)

    if not uv_ok:
        console.print(
            "[yellow]Warning: uv/uvx not found. MCP server may not work without it.[/yellow]"
        )
        console.print("[dim]Fix: curl -LsSf https://astral.sh/uv/install.sh | sh[/dim]")
        console.print()

    # Step 3: Install templates
    console.print("[bold]Step 2: Installing skill templates...[/bold]")
    console.print()

    installer = Installer()

    if upgrade:
        # Upgrade mode: force-refresh
        force = True
        _, old_ver, new_ver = installer.check_template_version()
        console.print(f"  Upgrading templates: {old_ver} -> {new_ver}")
    else:
        # Fresh install: ask if existing templates should be overwritten
        force = False
        installed_skills = installer.list_installed()
        if installed_skills:
            console.print(
                f"[yellow]Found {len(installed_skills)} existing skill templates.[/yellow]"
            )
            if click.confirm("  Overwrite with latest templates?", default=False):
                force = True
            console.print()

    try:
        installed = installer.install(force=force)
        console.print(
            f"  Installed [green]{len(installed)}[/green] skill templates to [cyan]{installer.target_dir}[/cyan]"
        )
    except Exception as e:
        console.print(f"[red]Error during installation: {e}[/red]")
        sys.exit(1)

    console.print()

    # Step 3b: DB migration + MCP refresh (upgrade only)
    if upgrade:
        console.print("[bold]Step 2b: Upgrading database and MCP config...[/bold]")
        console.print()

        try:
            from a_sdlc.storage import init_storage

            storage = init_storage()
            storage.list_projects()  # Verify connectivity
            console.print("  [green]PASS[/green] Database connected via configured backend")
        except Exception as e:
            console.print(f"  [red]FAIL[/red] Database connection failed: {e}")
            console.print("  Fix: check A_SDLC_DATABASE_URL or run docker compose up -d")
            sys.exit(1)

        try:
            configure_mcp_server(force=True)
            console.print("  [green]PASS[/green] MCP config refreshed")
        except Exception as e:
            console.print(f"  [red]FAIL[/red] MCP config update failed: {e}")
            sys.exit(1)

        console.print()

    # Step 4: Validate installation
    console.print("[bold]Step 3: Validating installation...[/bold]")
    console.print()

    validation_ok = True

    settings_path = get_claude_settings_path()
    mcp_servers = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
            mcp_servers = settings.get("mcpServers", {})
        except (json.JSONDecodeError, KeyError):
            pass

    if "asdlc" in mcp_servers:
        console.print("  [green]PASS[/green] asdlc MCP server configured in ~/.claude.json")
    else:
        console.print("  [red]FAIL[/red] asdlc MCP server not found in ~/.claude.json")
        validation_ok = False

    data_dir = Path.home() / ".a-sdlc"
    if data_dir.exists():
        console.print(f"  [green]PASS[/green] Data directory exists: {data_dir}")
    else:
        console.print(f"  [yellow]WARN[/yellow] Data directory not yet created: {data_dir}")
        console.print("  [dim]This is normal — it will be created on first use.[/dim]")

    if installer.target_dir.exists():
        template_count = len(list(installer.target_dir.glob("*.md")))
        console.print(
            f"  [green]PASS[/green] {template_count} skill templates in {installer.target_dir}"
        )
    else:
        console.print(f"  [red]FAIL[/red] Templates directory missing: {installer.target_dir}")
        validation_ok = False

    console.print()

    if not validation_ok:
        console.print("[red]Validation failed. Please check the errors above.[/red]")
        sys.exit(1)

    # Step 5: Optional components — detect what's already installed, only ask about missing ones
    console.print("[bold]Step 4: Optional integrations[/bold]")
    console.print()

    serena_installed = "serena" in mcp_servers
    if serena_installed:
        console.print("  [green]Serena MCP[/green] (already configured)")
    elif click.confirm("  Set up Serena MCP? (semantic code analysis)", default=True):
        console.print()
        _setup_serena_mcp(force=force)
    console.print()

    monitoring_installed = (
        "langfuse" in mcp_servers
        or (Path.home() / ".a-sdlc" / "docker-compose.monitoring.yml").exists()
    )
    if monitoring_installed:
        console.print("  [green]Monitoring[/green] (already configured)")
    elif click.confirm("  Set up monitoring? (Langfuse + SigNoz)", default=False):
        console.print()
        _setup_monitoring(force=force)
    console.print()

    sonarqube_installed = (Path.home() / ".config" / "a-sdlc" / "config.yaml").exists()
    if sonarqube_installed:
        console.print("  [green]SonarQube[/green] (already configured)")
    elif click.confirm("  Set up SonarQube? (code quality analysis)", default=False):
        console.print()
        _setup_sonarqube_interactive(force=force)
    console.print()

    playwright_installed = "playwright" in mcp_servers
    if playwright_installed:
        console.print("  [green]Playwright MCP[/green] (already configured)")
    elif click.confirm("  Set up Playwright MCP? (browser testing)", default=False):
        console.print()
        _setup_playwright_mcp(force=force)
    console.print()

    # Step 6: Success summary
    if upgrade:
        console.print(
            Panel(
                "[green]Upgrade complete![/green]\n\n"
                "[dim]Run 'a-sdlc doctor' to verify system health.[/dim]",
                title="[bold green]Upgrade Complete[/bold green]",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                "[green]Setup complete![/green]\n\n"
                "[bold]Next Steps[/bold]\n"
                "  1. Open a project in Claude Code\n"
                "  2. Run [cyan]/sdlc:init[/cyan] to initialize SDLC tracking\n"
                "  3. Run [cyan]/sdlc:help[/cyan] for all available commands\n\n"
                "[bold]Quick Start[/bold]\n"
                "  /sdlc:init                  Initialize project\n"
                "  /sdlc:scan                  Analyze codebase\n"
                "  /sdlc:prd-generate          Create a PRD\n"
                "  /sdlc:prd-split             Decompose PRD into tasks\n"
                "  /sdlc:sprint-run            Execute sprint tasks\n\n"
                "[dim]Run 'a-sdlc doctor' for detailed system diagnostics.[/dim]",
                title="[bold green]Setup Complete[/bold green]",
                border_style="green",
            )
        )


def _list_installed_skills(installer: Installer) -> None:
    """Display table of installed skill templates and personas."""
    skills = installer.list_installed()

    if not skills:
        console.print("[yellow]No skill templates installed.[/yellow]")
        console.print("Run [cyan]a-sdlc install[/cyan] to install them.")
        return

    table = Table(title="Installed Skill Templates")
    table.add_column("Skill", style="cyan")
    table.add_column("File", style="dim")
    table.add_column("Status", style="green")

    for skill in skills:
        table.add_row(f"/sdlc:{skill['name']}", skill["file"], "Installed")

    console.print(table)

    # Persona agents
    personas = installer.list_installed_personas()
    if personas:
        console.print()
        persona_table = Table(title="Installed Persona Agents")
        persona_table.add_column("Persona", style="cyan")
        persona_table.add_column("File", style="dim")
        persona_table.add_column("Status", style="green")

        for p in personas:
            persona_table.add_row(p["name"], p["file"], "Installed")

        console.print(persona_table)


def _setup_serena_mcp(force: bool = False) -> bool:
    """Set up Serena MCP server.

    Returns:
        True if setup succeeded, False otherwise.
    """
    console.print(
        Panel(
            "[bold]Setting up Serena MCP Server[/bold]\n\n"
            "Serena provides semantic code analysis capabilities\n"
            "that power the /sdlc:scan and /sdlc:update commands.",
            border_style="blue",
        )
    )

    success, message, verification = setup_serena(force=force)

    if success:
        console.print(f"[green]{message}[/green]")
        console.print()

        if verification:
            table = Table(title="Serena MCP Setup")
            table.add_column("Check", style="cyan")
            table.add_column("Status")

            table.add_row(
                "Package Installer", f"[green]{verification.get('installer_method', 'N/A')}[/green]"
            )
            table.add_row(
                "Claude Settings",
                "[green]Configured[/green]"
                if verification.get("configured_in_settings")
                else "[yellow]Not configured[/yellow]",
            )
            table.add_row("Settings File", f"[dim]{verification.get('settings_file', 'N/A')}[/dim]")

            console.print(table)

        return True
    else:
        console.print(f"[red]{message}[/red]")
        return False


def _setup_monitoring(force: bool = False) -> bool:
    """Set up monitoring stack (Langfuse + SigNoz).

    Returns:
        True if setup succeeded, False otherwise.
    """
    console.print(
        Panel(
            "[bold]Setting up Monitoring Stack[/bold]\n\n"
            "This will install:\n"
            "  - Langfuse (conversation tracing)\n"
            "  - SigNoz (OTEL metrics & logs)\n\n"
            f"Files: [cyan]{MONITORING_DIR}[/cyan]",
            border_style="blue",
        )
    )

    success, message, verification = setup_monitoring(force=force)

    if success:
        console.print(f"[green]{message}[/green]")
        console.print()

        if verification:
            table = Table(title="Monitoring Setup")
            table.add_column("Check", style="cyan")
            table.add_column("Status")

            table.add_row(
                "Monitoring Files",
                "[green]Installed[/green]"
                if verification.get("files_ready")
                else "[red]Missing[/red]",
            )
            table.add_row(
                "SigNoz",
                "[green]Cloned[/green]"
                if verification.get("signoz_cloned")
                else "[red]Not cloned[/red]",
            )
            table.add_row(
                "Stop Hook",
                "[green]Registered[/green]"
                if verification.get("hook_registered")
                else "[yellow]Not registered[/yellow]",
            )
            table.add_row(
                "OTEL Environment",
                "[green]Configured[/green]"
                if verification.get("otel_configured")
                else "[yellow]Not configured[/yellow]",
            )
            table.add_row(
                "Langfuse API Keys",
                "[green]Configured[/green]"
                if verification.get("langfuse_keys_configured")
                else "[yellow]Not yet (run: a-sdlc monitoring configure)[/yellow]",
            )

            console.print(table)

        console.print()
        console.print("[bold]Next steps:[/bold]")
        console.print("  1. Start services:   [cyan]a-sdlc monitoring start[/cyan]")
        console.print("  2. Open Langfuse:    [cyan]http://localhost:13000[/cyan]")
        console.print("     Login:            admin@langfuse.local / changeme123")
        console.print("     Go to Settings > API Keys > Create")
        console.print("  3. Configure keys:   [cyan]a-sdlc monitoring configure[/cyan]")
        console.print("  4. Restart Claude Code")

        return True
    else:
        console.print(f"[red]{message}[/red]")
        return False


# =============================================================================
# Uninstall Command
# =============================================================================


@main.command()
@click.option(
    "--include-data",
    is_flag=True,
    help="Also remove project data (~/.a-sdlc/ including PRDs, tasks, database)",
)
@click.option(
    "--dry-run", is_flag=True, help="Preview what would be removed without making changes"
)
@click.option("-y", "--yes", is_flag=True, help="Skip confirmation prompt")
@click.option(
    "--target",
    "cli_target",
    type=click.Choice(["claude", "gemini", "auto"]),
    default="auto",
    help="Target CLI to uninstall from (default: auto-detect)",
)
def uninstall(include_data: bool, dry_run: bool, yes: bool, cli_target: str) -> None:
    """Remove all a-sdlc components from the system.

    By default, preserves project data (PRDs, tasks, database).
    Use --include-data for a complete wipe.

    The Python package itself is not uninstalled; run
    `uv tool uninstall a-sdlc` or `pip uninstall a-sdlc` separately.

    \b
    Examples:
        a-sdlc uninstall                  # Remove tooling, keep data
        a-sdlc uninstall --include-data   # Remove everything
        a-sdlc uninstall --dry-run        # Preview changes
        a-sdlc uninstall -y               # Skip confirmation
    """
    from a_sdlc.uninstall import build_uninstall_plan, execute_uninstall

    targets = resolve_targets(cli_target)
    plan = build_uninstall_plan(include_data=include_data, targets=targets if targets else None)

    # Ask about optional MCP servers (they may have been installed independently)
    if not dry_run and not yes:
        if plan.has_serena_mcp:
            plan.remove_serena = click.confirm(
                "  Also remove Serena MCP? (you may use it independently)", default=False
            )
        if plan.has_playwright_mcp:
            plan.remove_playwright = click.confirm(
                "  Also remove Playwright MCP? (you may use it independently)", default=False
            )
        if plan.has_serena_mcp or plan.has_playwright_mcp:
            console.print()
    elif yes:
        # -y flag: remove everything
        plan.remove_serena = plan.has_serena_mcp
        plan.remove_playwright = plan.has_playwright_mcp

    # Display plan
    _display_uninstall_plan(plan)

    if dry_run:
        console.print()
        console.print("[yellow]Dry run — no changes made.[/yellow]")
        return

    # Nothing to do?
    if not _plan_has_work(plan):
        console.print()
        console.print("[green]Nothing to uninstall.[/green]")
        return

    # Confirmation
    if not yes:
        console.print()
        if include_data:
            console.print(
                "[bold red]WARNING: --include-data will permanently delete "
                "all PRDs, tasks, and the database.[/bold red]"
            )
        confirmed = click.confirm("Proceed with uninstall?", default=False)
        if not confirmed:
            console.print("[dim]Cancelled.[/dim]")
            return

    # Execute
    result = execute_uninstall(plan)

    # Display results
    console.print()
    if result.actions:
        console.print(
            Panel(
                "\n".join(f"[green]  {a}[/green]" for a in result.actions),
                title="[bold]Actions Taken[/bold]",
                border_style="green",
            )
        )

    if result.warnings:
        for w in result.warnings:
            console.print(f"[yellow]  Warning: {w}[/yellow]")

    if result.errors:
        for e in result.errors:
            console.print(f"[red]  Error: {e}[/red]")
        sys.exit(1)

    console.print()
    console.print("[green]Uninstall complete.[/green]")
    console.print()
    console.print("[dim]Notes:[/dim]")
    console.print("  - To remove the Python package: [cyan]uv tool uninstall a-sdlc[/cyan]")
    console.print(
        "  - Per-project [cyan].sdlc/[/cyan] directories must be removed manually from each repo."
    )


def _display_uninstall_plan(plan) -> None:
    """Display a table summarizing what will be removed."""
    table = Table(title="Uninstall Plan")
    table.add_column("Component", style="cyan")
    table.add_column("Status")
    table.add_column("Action")

    table.add_row(
        "asdlc MCP server",
        "[green]Found[/green]" if plan.has_asdlc_mcp else "[dim]Not found[/dim]",
        "Remove from ~/.claude.json" if plan.has_asdlc_mcp else "Skip",
    )
    table.add_row(
        "serena MCP server",
        "[green]Found[/green]" if plan.has_serena_mcp else "[dim]Not found[/dim]",
        "Remove from settings.json"
        if plan.remove_serena
        else "[dim]Keep (user choice)[/dim]"
        if plan.has_serena_mcp
        else "Skip",
    )
    table.add_row(
        "playwright MCP server",
        "[green]Found[/green]" if plan.has_playwright_mcp else "[dim]Not found[/dim]",
        "Remove from settings.json"
        if plan.remove_playwright
        else "[dim]Keep (user choice)[/dim]"
        if plan.has_playwright_mcp
        else "Skip",
    )
    table.add_row(
        "Skill templates",
        f"[green]{plan.skill_template_count} files[/green]"
        if plan.skill_template_count
        else "[dim]None[/dim]",
        f"Delete {plan.skill_template_count} templates" if plan.skill_template_count else "Skip",
    )
    table.add_row(
        "Persona agents",
        f"[green]{plan.persona_count} files[/green]" if plan.persona_count else "[dim]None[/dim]",
        f"Remove {plan.persona_count} from ~/.claude/agents/" if plan.persona_count else "Skip",
    )
    table.add_row(
        "Monitoring hook",
        "[green]Found[/green]" if plan.has_monitoring_hook else "[dim]Not found[/dim]",
        "Remove from settings.json" if plan.has_monitoring_hook else "Skip",
    )
    table.add_row(
        "OTEL/Langfuse env vars",
        f"[green]{len(plan.managed_env_keys)} keys[/green]"
        if plan.managed_env_keys
        else "[dim]None[/dim]",
        f"Remove {len(plan.managed_env_keys)} key(s)" if plan.managed_env_keys else "Skip",
    )
    table.add_row(
        "Monitoring files",
        f"[green]{plan.monitoring_dir}[/green]"
        if plan.has_monitoring_dir
        else "[dim]Not found[/dim]",
        "Delete directory" if plan.has_monitoring_dir else "Skip",
    )
    table.add_row(
        "Project data",
        f"[green]{plan.data_dir}[/green]" if plan.has_data_dir else "[dim]Not found[/dim]",
        "[red]Delete directory[/red]"
        if plan.include_data and plan.has_data_dir
        else "[dim]Preserved (use --include-data)[/dim]"
        if plan.has_data_dir
        else "Skip",
    )

    console.print(table)


def _plan_has_work(plan) -> bool:
    """Check if the plan has anything to do."""
    return any(
        [
            plan.has_asdlc_mcp,
            plan.has_serena_mcp,
            plan.skill_template_count > 0,
            plan.persona_count > 0,
            plan.has_monitoring_hook,
            plan.managed_env_keys,
            plan.has_monitoring_dir,
            plan.include_data and plan.has_data_dir,
        ]
    )


@main.command("setup-mcp")
@click.option("--force", "-f", is_flag=True, help="Force reconfigure even if already set up")
def setup_mcp(force: bool) -> None:
    """Install and configure Serena MCP for Claude Code.

    This configures the Serena MCP server in your Claude Code settings,
    enabling semantic code analysis for the /sdlc:* commands.

    Serena is run on-demand via uvx or pipx, so no permanent
    installation is required.

    Examples:

        a-sdlc setup-mcp           # Set up Serena MCP
        a-sdlc setup-mcp --force   # Force reconfigure
    """
    success = _setup_serena_mcp(force=force)
    if not success:
        sys.exit(1)

    console.print()
    console.print("[green]Serena MCP is ready![/green]")
    console.print()
    console.print("Next steps:")
    console.print("  1. Restart Claude Code to load the new MCP server")
    console.print("  2. Run [cyan]/sdlc:init[/cyan] in your project")
    console.print("  3. Run [cyan]/sdlc:scan[/cyan] to generate artifacts")


# =============================================================================
# Monitoring Commands
# =============================================================================


@main.group()
def monitoring() -> None:
    """Manage monitoring stack (Langfuse + SigNoz).

    Provides commands to configure, start, stop, and check the
    monitoring stack for Claude Code observability.

    \b
      a-sdlc monitoring configure   Set Langfuse API keys
      a-sdlc monitoring start       Start Docker services
      a-sdlc monitoring stop        Stop Docker services
      a-sdlc monitoring status      Check services health
    """
    pass


@monitoring.command("configure")
def monitoring_configure() -> None:
    """Configure Langfuse API keys interactively.

    After starting the monitoring stack, log in to Langfuse at
    http://localhost:13000 (admin@langfuse.local / changeme123),
    create API keys under Settings > API Keys, then run this command.

    Examples:

        a-sdlc monitoring configure
    """
    console.print(
        Panel(
            "[bold]Langfuse API Key Configuration[/bold]\n\n"
            "Get your keys from http://localhost:13000\n"
            "  Login: admin@langfuse.local / changeme123\n"
            "  Go to: Settings > API Keys > Create",
            border_style="blue",
        )
    )

    secret_key = click.prompt("Langfuse Secret Key (sk-lf-...)", hide_input=True)
    public_key = click.prompt("Langfuse Public Key (pk-lf-...)")
    host = click.prompt("Langfuse Host", default="http://localhost:13000")

    success, message = configure_langfuse_keys(secret_key, public_key, host)

    if success:
        console.print(f"[green]{message}[/green]")
        console.print()
        console.print("Restart Claude Code for the keys to take effect.")
    else:
        console.print(f"[red]{message}[/red]")
        sys.exit(1)


@monitoring.command("start")
def monitoring_start() -> None:
    """Start monitoring Docker services.

    Runs `docker compose up -d` in ~/.a-sdlc/monitoring/.

    Examples:

        a-sdlc monitoring start
    """
    import subprocess

    if not MONITORING_DIR.exists():
        console.print("[red]Monitoring not installed.[/red]")
        console.print("Run [cyan]a-sdlc install --with-monitoring[/cyan] first.")
        sys.exit(1)

    compose_file = MONITORING_DIR / "docker-compose.yaml"
    if not compose_file.exists():
        console.print("[red]docker-compose.yaml not found.[/red]")
        console.print("Run [cyan]a-sdlc install --with-monitoring --force[/cyan] to reinstall.")
        sys.exit(1)

    console.print("[bold]Starting monitoring services...[/bold]")
    console.print(f"[dim]Working directory: {MONITORING_DIR}[/dim]")
    console.print()

    result = subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=str(MONITORING_DIR),
    )

    if result.returncode == 0:
        console.print()
        console.print("[green]Monitoring services started![/green]")
        console.print()
        console.print("Dashboards:")
        console.print("  Langfuse: [cyan]http://localhost:13000[/cyan]")
        console.print("  SigNoz:   [cyan]http://localhost:8080[/cyan]")
    else:
        console.print()
        console.print("[red]Failed to start services.[/red]")
        sys.exit(1)


@monitoring.command("stop")
def monitoring_stop() -> None:
    """Stop monitoring Docker services.

    Runs `docker compose down` in ~/.a-sdlc/monitoring/.

    Examples:

        a-sdlc monitoring stop
    """
    import subprocess

    if not MONITORING_DIR.exists():
        console.print("[yellow]Monitoring directory not found. Nothing to stop.[/yellow]")
        return

    console.print("[bold]Stopping monitoring services...[/bold]")

    result = subprocess.run(
        ["docker", "compose", "down"],
        cwd=str(MONITORING_DIR),
    )

    if result.returncode == 0:
        console.print("[green]Monitoring services stopped.[/green]")
    else:
        console.print("[red]Failed to stop services.[/red]")
        sys.exit(1)


@monitoring.command("status")
def monitoring_status() -> None:
    """Show monitoring setup and services health.

    Checks file installation, settings configuration,
    and whether Docker services are reachable.

    Examples:

        a-sdlc monitoring status
    """
    console.print(Panel("[bold]Monitoring Status[/bold]", border_style="blue"))

    # Setup verification
    verification = verify_monitoring_setup()

    setup_table = Table(title="Setup")
    setup_table.add_column("Component", style="cyan")
    setup_table.add_column("Status")

    setup_checks = [
        ("Monitoring Files", verification.get("files_ready", False)),
        ("SigNoz Clone", verification.get("signoz_cloned", False)),
        ("Stop Hook", verification.get("hook_registered", False)),
        ("OTEL Environment", verification.get("otel_configured", False)),
        ("Langfuse API Keys", verification.get("langfuse_keys_configured", False)),
    ]

    for name, ok in setup_checks:
        status = "[green]OK[/green]" if ok else "[yellow]Not configured[/yellow]"
        setup_table.add_row(name, status)

    console.print(setup_table)
    console.print()

    # Services health
    health = check_services_health()

    health_table = Table(title="Services")
    health_table.add_column("Service", style="cyan")
    health_table.add_column("Status")
    health_table.add_column("URL", style="dim")

    langfuse_ok = health.get("langfuse_reachable", False)
    health_table.add_row(
        "Langfuse",
        "[green]Running[/green]" if langfuse_ok else "[red]Not reachable[/red]",
        "http://localhost:13000",
    )

    signoz_ok = health.get("signoz_reachable", False)
    health_table.add_row(
        "SigNoz",
        "[green]Running[/green]" if signoz_ok else "[red]Not reachable[/red]",
        "http://localhost:8080",
    )

    console.print(health_table)

    if not langfuse_ok or not signoz_ok:
        console.print()
        console.print("[dim]Run [cyan]a-sdlc monitoring start[/cyan] to start services.[/dim]")


# =============================================================================
# SonarQube Commands
# =============================================================================


def _setup_sonarqube_interactive(force: bool = False) -> bool:
    """Interactive SonarQube setup.

    Returns:
        True if setup succeeded, False otherwise.
    """
    # Install pysonar if not available
    scanner_ok, _ = check_scanner_available()
    if not scanner_ok:
        import subprocess

        console.print("[cyan]Installing pysonar scanner...[/cyan]")
        result = subprocess.run(
            ["uv", "tool", "install", "pysonar"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(f"[red]Failed to install pysonar: {result.stderr.strip()}[/red]")
            return False
        console.print("[green]pysonar installed successfully.[/green]")
        console.print()

    console.print(
        Panel(
            "[bold]Setting up SonarQube Integration[/bold]\n\n"
            "This will configure code analysis with your SonarQube instance.\n"
            "You'll need:\n"
            "  - SonarQube host URL\n"
            "  - Authentication token\n"
            "  - Project key",
            border_style="blue",
        )
    )

    host_url = click.prompt("SonarQube host URL", default="http://localhost:9000")
    token = click.prompt("Authentication token", hide_input=True)
    project_key = click.prompt("Project key")
    sources = click.prompt("Source directories", default="src")
    exclusions = click.prompt("Exclusion patterns (comma-separated, empty for none)", default="")
    fix_input = click.prompt(
        "Fix severity threshold",
        default="BLOCKER,CRITICAL,MAJOR",
    )
    fix_severities = [s.strip() for s in fix_input.split(",") if s.strip()]

    success, message, verification = setup_sonarqube(
        host_url=host_url,
        token=token,
        project_key=project_key,
        sources=sources,
        exclusions=exclusions or None,
        fix_severities=fix_severities,
    )

    if success:
        console.print(f"[green]{message}[/green]")
        console.print()

        if verification:
            table = Table(title="SonarQube Setup")
            table.add_column("Check", style="cyan")
            table.add_column("Status")

            table.add_row(
                "Scanner",
                "[green]Available[/green]"
                if verification.get("scanner_available")
                else "[yellow]Not found[/yellow]",
            )
            table.add_row(
                "Connection",
                "[green]Connected[/green]"
                if verification.get("sonarqube_reachable")
                else "[yellow]Not reachable[/yellow]",
            )
            table.add_row(
                "Project Key",
                f"[green]{project_key}[/green]"
                if verification.get("project_key_configured")
                else "[yellow]Not set[/yellow]",
            )

            console.print(table)

        console.print()
        console.print("[bold]Next steps:[/bold]")
        console.print("  1. Run scan:     [cyan]a-sdlc sonarqube scan[/cyan]")
        console.print("  2. View results: [cyan]a-sdlc sonarqube results[/cyan]")
        console.print("  3. Auto-fix:     [cyan]/sdlc:sonar-scan[/cyan] (in Claude Code)")

        return True
    else:
        console.print(f"[red]{message}[/red]")
        return False


@main.group()
def sonarqube() -> None:
    """SonarQube code analysis integration.

    Configure, run, and view SonarQube analysis results.
    Use `/sdlc:sonar-scan` in Claude Code for automated scan + fix.
    """
    pass


@sonarqube.command("configure")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing configuration")
def sonarqube_configure(force: bool) -> None:
    """Configure SonarQube connection and project settings.

    Interactive setup that validates the connection before saving.

    Examples:

        a-sdlc sonarqube configure
        a-sdlc sonarqube configure --force
    """
    _setup_sonarqube_interactive(force=force)


@sonarqube.command("scan")
def sonarqube_scan() -> None:
    """Run pysonar to analyze the project.

    Executes pysonar scanner with configured settings.

    Examples:

        a-sdlc sonarqube scan
    """
    console.print("[cyan]Running SonarQube scanner...[/cyan]")

    success, message = run_scanner()

    if success:
        console.print(f"[green]{message}[/green]")
        console.print()
        console.print("Run [cyan]a-sdlc sonarqube results[/cyan] to fetch and view results.")
    else:
        console.print(f"[red]{message}[/red]")
        sys.exit(1)


@sonarqube.command("results")
def sonarqube_results() -> None:
    """Fetch analysis results and generate code-quality.md artifact.

    Calls the SonarQube API to retrieve quality gate status, metrics,
    and issues, then writes a formatted report to .sdlc/artifacts/code-quality.md.

    Examples:

        a-sdlc sonarqube results
    """
    console.print("[cyan]Fetching SonarQube results...[/cyan]")

    success, message = generate_code_quality_artifact()

    if success:
        console.print(f"[green]{message}[/green]")
    else:
        console.print(f"[red]{message}[/red]")
        sys.exit(1)


@sonarqube.command("status")
def sonarqube_status() -> None:
    """Show SonarQube setup verification and analysis status.

    Examples:

        a-sdlc sonarqube status
    """
    console.print(Panel("[bold]SonarQube Integration Status[/bold]", border_style="blue"))

    verification = verify_sonarqube_setup()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Details", style="dim")

    scanner_ok = verification.get("scanner_available", False)
    table.add_row(
        "Scanner",
        "[green]Available[/green]" if scanner_ok else "[yellow]Not found[/yellow]",
        "pysonar" if scanner_ok else "Install with: uv tool install pysonar",
    )

    table.add_row(
        "Host URL",
        "[green]Configured[/green]"
        if verification.get("host_url_configured")
        else "[yellow]Not set[/yellow]",
        "",
    )

    table.add_row(
        "Token",
        "[green]Configured[/green]"
        if verification.get("token_configured")
        else "[yellow]Not set[/yellow]",
        "",
    )

    table.add_row(
        "Project Key",
        "[green]Configured[/green]"
        if verification.get("project_key_configured")
        else "[yellow]Not set[/yellow]",
        "",
    )

    reachable = verification.get("sonarqube_reachable", False)
    table.add_row(
        "Connection",
        "[green]Connected[/green]" if reachable else "[yellow]Not reachable[/yellow]",
        str(verification.get("connection_message", "")),
    )

    ready = verification.get("ready", False)
    table.add_row("Overall", "[green]Ready[/green]" if ready else "[yellow]Not ready[/yellow]", "")

    console.print(table)

    if not ready:
        console.print()
        console.print("[dim]Run [cyan]a-sdlc sonarqube configure[/cyan] to set up.[/dim]")


def _doctor_live_mode() -> None:
    """Continuously poll the health endpoint every 2 seconds with color-coded output.

    Shows: status, uptime, active connections, last error, memory.
    Exits cleanly on Ctrl+C.
    """
    import time as _time
    import urllib.request

    health_url = "http://127.0.0.1:8765/health"
    click.echo("Live health monitor — polling every 2s  (Ctrl+C to exit)")
    click.echo()

    try:
        while True:
            try:
                req = urllib.request.Request(health_url, method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode())

                status = data.get("status", "unknown")
                uptime = data.get("uptime_seconds", 0)
                conns = data.get("active_connections", 0)
                memory = data.get("memory_mb", 0)
                last_err = data.get("last_error")
                version = data.get("version", "?")

                # Color-code by status
                if status == "healthy":
                    status_styled = click.style(status, fg="green", bold=True)
                elif status == "degraded":
                    status_styled = click.style(status, fg="yellow", bold=True)
                else:
                    status_styled = click.style(status, fg="red", bold=True)

                # Format uptime
                _h, _rem = divmod(int(uptime), 3600)
                _m, _s = divmod(_rem, 60)
                uptime_str = f"{_h}h {_m}m {_s}s"

                # Format last error
                err_str = "none"
                if last_err:
                    err_str = click.style(
                        f"{last_err.get('type', '?')}: {last_err.get('message', '?')}",
                        fg="red",
                    )

                timestamp = click.style(
                    datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    fg="cyan",
                )
                click.echo(
                    f"[{timestamp}] {status_styled}  "
                    f"v{version}  "
                    f"up {uptime_str}  "
                    f"conns={conns}  "
                    f"mem={memory}MB  "
                    f"err={err_str}"
                )
            except Exception:
                timestamp = click.style(
                    datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    fg="cyan",
                )
                status_styled = click.style("unreachable", fg="red", bold=True)
                click.echo(f"[{timestamp}] {status_styled}  Cannot reach {health_url}")

            _time.sleep(2)
    except KeyboardInterrupt:
        click.echo()
        click.echo("Stopped.")


@main.command()
@click.option(
    "--check-consistency",
    is_flag=True,
    default=False,
    help="Check data consistency across all projects (orphaned files, phantom records).",
)
@click.option(
    "--repair",
    is_flag=True,
    default=False,
    help="Repair detected inconsistencies (implies --check-consistency).",
)
@click.option(
    "--live",
    is_flag=True,
    default=False,
    help="Continuously poll the health endpoint every 2s with color-coded status.",
)
def doctor(check_consistency: bool, repair: bool, live: bool) -> None:
    """Run system diagnostics.

    Checks for:
    - Python version compatibility
    - uv/uvx availability
    - Claude Code configuration
    - asdlc MCP server configuration
    - Skill templates and version
    - Serena MCP server
    - Installed plugins
    - Docker and monitoring services
    - SonarQube configuration
    - Server process, port reachability, health endpoint, log file
    - Database accessibility and schema version
    - Data consistency (with --check-consistency)

    Use --live to continuously monitor the health endpoint with color-coded output.
    """
    # --live mode: continuous health polling
    if live:
        _doctor_live_mode()
        return

    # --repair implies --check-consistency
    if repair:
        check_consistency = True
    console.print(Panel("[bold]a-sdlc System Diagnostics[/bold]", border_style="blue"))

    checks = []

    # Python version check
    py_version = sys.version_info
    py_ok = py_version >= (3, 10)
    checks.append(
        {
            "name": "Python Version",
            "status": "pass" if py_ok else "fail",
            "detail": f"{py_version.major}.{py_version.minor}.{py_version.micro}"
            if py_ok
            else f"{py_version.major}.{py_version.minor}.{py_version.micro} (requires >= 3.10). Fix: install Python 3.10+",
        }
    )

    # uv/uvx availability check
    uv_ok, uv_msg = check_uv_available()
    checks.append(
        {
            "name": "uv/uvx",
            "status": "pass" if uv_ok else "fail",
            "detail": uv_msg
            if uv_ok
            else "Not found. Fix: install from https://docs.astral.sh/uv/",
        }
    )

    # CLI targets detection
    detected = detect_targets()
    if detected:
        checks.append(
            {
                "name": "CLI Targets",
                "status": "pass",
                "detail": ", ".join(t.display_name for t in detected),
            }
        )
    else:
        checks.append(
            {
                "name": "CLI Targets",
                "status": "warn",
                "detail": "No supported CLI found. Install Claude Code or Gemini CLI.",
            }
        )

    # Per-target MCP config checks
    for t in detected:
        try:
            if t.mcp_config_path.exists():
                with open(t.mcp_config_path, encoding="utf-8") as f:
                    target_settings = json.load(f)
                has_mcp = "asdlc" in target_settings.get("mcpServers", {})
            else:
                has_mcp = False
        except (json.JSONDecodeError, OSError):
            has_mcp = False
        checks.append(
            {
                "name": f"{t.display_name} MCP",
                "status": "pass" if has_mcp else "warn",
                "detail": f"asdlc configured in {t.mcp_config_path}"
                if has_mcp
                else f"Not found. Fix: run a-sdlc install --target {t.name}",
            }
        )

    # Legacy asdlc MCP server check (for backward compatibility)
    settings_path = get_claude_settings_path()
    try:
        if settings_path.exists():
            with open(settings_path, encoding="utf-8") as f:
                claude_settings = json.load(f)
            mcp_ok = "asdlc" in claude_settings.get("mcpServers", {})
        else:
            mcp_ok = False
    except (json.JSONDecodeError, OSError):
        mcp_ok = False
    checks.append(
        {
            "name": "asdlc MCP Server",
            "status": "pass" if mcp_ok else "warn",
            "detail": "Configured in ~/.claude.json"
            if mcp_ok
            else "Not found. Fix: run a-sdlc install",
        }
    )

    # Commands directory (use Claude's default path for backward compatibility)
    claude_dir = Path.home() / ".claude"
    commands_dir = claude_dir / "commands" / "sdlc"
    commands_ok = commands_dir.exists()
    checks.append(
        {
            "name": "Skill Templates",
            "status": "pass" if commands_ok else "warn",
            "detail": f"{len(list(commands_dir.glob('*.md')))} installed"
            if commands_ok
            else "Not installed. Fix: run a-sdlc install",
        }
    )

    # Template version check
    try:
        installer = Installer()
        tpl_up_to_date, tpl_installed, tpl_current = installer.check_template_version()
        if tpl_up_to_date:
            tpl_status, tpl_detail = "pass", f"v{tpl_installed} (current)"
        else:
            tpl_status, tpl_detail = (
                "warn",
                f"v{tpl_installed} installed, v{tpl_current} available. Fix: run a-sdlc install --force",
            )
    except Exception:
        tpl_status, tpl_detail = "warn", "Cannot check. Fix: run a-sdlc install"
    checks.append({"name": "Template Version", "status": tpl_status, "detail": tpl_detail})

    # Serena MCP check
    serena_verification = verify_setup()
    serena_ok = serena_verification.get("ready", False)
    serena_configured = serena_verification.get("configured_in_settings", False)
    serena_installer = serena_verification.get("installer_method", "none")

    if serena_ok:
        serena_detail = f"Configured ({serena_installer})"
        serena_status = "pass"
    elif serena_configured:
        serena_detail = "Configured but installer not found. Fix: run a-sdlc setup-mcp"
        serena_status = "warn"
    else:
        serena_detail = "Not configured. Fix: run a-sdlc setup-mcp"
        serena_status = "warn"

    checks.append({"name": "Serena MCP", "status": serena_status, "detail": serena_detail})

    # Plugin manager
    pm = get_plugin_manager()
    plugins = pm.list_plugins()
    checks.append(
        {
            "name": "Plugins Available",
            "status": "pass",
            "detail": ", ".join(plugins) if plugins else "None",
        }
    )

    # Monitoring checks
    docker_ok = check_docker_available()
    checks.append(
        {
            "name": "Docker",
            "status": "pass" if docker_ok else "warn",
            "detail": "Available"
            if docker_ok
            else "Not found. Fix: install Docker from https://docs.docker.com/get-docker/",
        }
    )

    mon_verification = verify_monitoring_setup()

    checks.append(
        {
            "name": "Monitoring Files",
            "status": "pass" if mon_verification.get("files_ready") else "warn",
            "detail": "Installed"
            if mon_verification.get("files_ready")
            else "Not installed. Fix: run a-sdlc install --with-monitoring",
        }
    )

    checks.append(
        {
            "name": "Langfuse Hook",
            "status": "pass" if mon_verification.get("hook_registered") else "warn",
            "detail": "Registered"
            if mon_verification.get("hook_registered")
            else "Not registered. Fix: run a-sdlc install --with-monitoring",
        }
    )

    checks.append(
        {
            "name": "OTEL Environment",
            "status": "pass" if mon_verification.get("otel_configured") else "warn",
            "detail": "Configured"
            if mon_verification.get("otel_configured")
            else "Not configured. Fix: run a-sdlc install --with-monitoring",
        }
    )

    if mon_verification.get("files_ready"):
        health = check_services_health()
        langfuse_ok = health.get("langfuse_reachable", False)
        signoz_ok = health.get("signoz_reachable", False)

        checks.append(
            {
                "name": "Langfuse Service",
                "status": "pass" if langfuse_ok else "warn",
                "detail": "http://localhost:13000"
                if langfuse_ok
                else "Not reachable. Fix: run a-sdlc monitoring start",
            }
        )
        checks.append(
            {
                "name": "SigNoz Service",
                "status": "pass" if signoz_ok else "warn",
                "detail": "http://localhost:8080"
                if signoz_ok
                else "Not reachable. Fix: run a-sdlc monitoring start",
            }
        )

    # SonarQube checks
    sq_verification = verify_sonarqube_setup()
    sq_ready = sq_verification.get("ready", False)

    if sq_ready:
        sq_detail = "Configured (pysonar available)"
        sq_status = "pass"
    elif sq_verification.get("host_url_configured"):
        sq_detail = "Partially configured. Fix: run a-sdlc sonarqube configure"
        sq_status = "warn"
    else:
        sq_detail = "Not configured. Fix: run a-sdlc sonarqube configure"
        sq_status = "warn"

    checks.append({"name": "SonarQube", "status": sq_status, "detail": sq_detail})

    # Playwright MCP check
    from a_sdlc.playwright_setup import verify_setup as verify_playwright_setup

    pw_verification = verify_playwright_setup()
    pw_ready = pw_verification.get("ready", False)
    pw_configured = pw_verification.get("configured_in_settings", False)

    if pw_ready:
        pw_detail = "Configured (npx available)"
        pw_status = "pass"
    elif pw_configured:
        pw_detail = "Configured but npx not found. Fix: install Node.js"
        pw_status = "warn"
    else:
        pw_detail = "Not configured. Fix: run a-sdlc install --with-playwright"
        pw_status = "warn"

    checks.append(
        {
            "name": "Playwright MCP",
            "status": pw_status,
            "detail": pw_detail,
        }
    )

    # Persona agents check
    try:
        persona_installer = Installer()
        personas = persona_installer.list_installed_personas()
        persona_count = len(personas)
        if persona_count >= 7:
            checks.append(
                {
                    "name": "Persona Agents",
                    "status": "pass",
                    "detail": f"{persona_count} personas deployed to ~/.claude/agents/",
                }
            )
        elif persona_count > 0:
            checks.append(
                {
                    "name": "Persona Agents",
                    "status": "warn",
                    "detail": f"Only {persona_count}/7 personas deployed. Fix: a-sdlc install --force",
                }
            )
        else:
            checks.append(
                {
                    "name": "Persona Agents",
                    "status": "warn",
                    "detail": "No personas found. Fix: a-sdlc install",
                }
            )
    except Exception:
        checks.append(
            {
                "name": "Persona Agents",
                "status": "warn",
                "detail": "Could not check personas. Fix: a-sdlc install",
            }
        )

    # ---- Server process checks ----
    import os as _os
    import socket as _socket

    from a_sdlc.server import _MCP_PID_FILE

    _asdlc_dir = Path.home() / ".a-sdlc"

    # 1. Server PID check
    _server_pid: int | None = None
    if _MCP_PID_FILE.exists():
        try:
            _server_pid = int(_MCP_PID_FILE.read_text().strip())
            _os.kill(_server_pid, 0)
            checks.append(
                {
                    "name": "Server Process",
                    "status": "pass",
                    "detail": f"Running (PID: {_server_pid})",
                }
            )
        except (ValueError, OSError):
            checks.append(
                {
                    "name": "Server Process",
                    "status": "warn",
                    "detail": "Stale PID file. Fix: delete ~/.a-sdlc/mcp.pid or restart the server",
                }
            )
            _server_pid = None
    else:
        checks.append(
            {
                "name": "Server Process",
                "status": "warn",
                "detail": "Not running. Fix: run docker compose up -d or a-sdlc serve",
            }
        )

    # 2. Port reachability checks
    for _port_name, _port_num in [("MCP Port (8765)", 8765), ("UI Port (3847)", 3847)]:
        try:
            with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as _sock:
                _sock.settimeout(2)
                _port_reachable = _sock.connect_ex(("127.0.0.1", _port_num)) == 0
        except OSError:
            _port_reachable = False
        checks.append(
            {
                "name": _port_name,
                "status": "pass" if _port_reachable else "warn",
                "detail": f"Listening on 127.0.0.1:{_port_num}"
                if _port_reachable
                else "Not reachable. Fix: run docker compose up -d or a-sdlc serve",
            }
        )

    # 3. Health endpoint check
    try:
        import urllib.request

        _health_req = urllib.request.Request("http://127.0.0.1:8765/health", method="GET")
        with urllib.request.urlopen(_health_req, timeout=3) as _resp:
            if _resp.status == 200:
                _health_body = json.loads(_resp.read().decode())
                _h_status = _health_body.get("status", "unknown")
                _h_version = _health_body.get("version", "?")
                checks.append(
                    {
                        "name": "Health Endpoint",
                        "status": "pass",
                        "detail": f"status={_h_status}, version={_h_version}",
                    }
                )
            else:
                checks.append(
                    {
                        "name": "Health Endpoint",
                        "status": "warn",
                        "detail": f"HTTP {_resp.status}. Server may be unhealthy",
                    }
                )
    except Exception:
        checks.append(
            {
                "name": "Health Endpoint",
                "status": "warn",
                "detail": "Unreachable at http://127.0.0.1:8765/health. Fix: run docker compose up -d or a-sdlc serve",
            }
        )

    # 4. Log file check
    _server_log = _asdlc_dir / "server.log"
    if _server_log.exists():
        _log_writable = _os.access(_server_log, _os.W_OK)
        checks.append(
            {
                "name": "Server Log",
                "status": "pass" if _log_writable else "warn",
                "detail": str(_server_log)
                if _log_writable
                else f"{_server_log} (not writable). Fix: check file permissions",
            }
        )
    else:
        checks.append(
            {
                "name": "Server Log",
                "status": "warn",
                "detail": f"Not found at {_server_log}. Created on first server start",
            }
        )

    # 5. Docker container status (when Docker mode detected)
    if _os.environ.get("A_SDLC_DOCKER") == "1":
        import subprocess as _sp

        try:
            _docker_result = _sp.run(
                ["docker", "ps", "--filter", "name=a-sdlc", "--format", "{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if _docker_result.returncode == 0 and _docker_result.stdout.strip():
                _container_status = _docker_result.stdout.strip().split("\n")[0]
                checks.append(
                    {
                        "name": "Docker Container",
                        "status": "pass",
                        "detail": _container_status,
                    }
                )
            else:
                checks.append(
                    {
                        "name": "Docker Container",
                        "status": "warn",
                        "detail": "No a-sdlc container running. Fix: docker compose up -d",
                    }
                )
        except Exception:
            checks.append(
                {
                    "name": "Docker Container",
                    "status": "warn",
                    "detail": "Cannot query Docker. Fix: ensure Docker is running",
                }
            )

    # Database accessibility check
    from a_sdlc.storage import init_storage

    try:
        storage = init_storage()
        # Verify DB is reachable by running a lightweight query
        storage.list_projects()
        checks.append(
            {
                "name": "Database Accessible",
                "status": "pass",
                "detail": "Connected via configured backend",
            }
        )
    except Exception as e:
        checks.append(
            {
                "name": "Database Accessible",
                "status": "fail",
                "detail": f"Cannot connect to database: {e}. Fix: check A_SDLC_DATABASE_URL or run docker compose up -d",
            }
        )

    # Database schema version check (via Alembic)
    try:
        from a_sdlc.core.storage_config import get_storage_config

        cfg = get_storage_config()
        db_url = cfg.database_url
        if db_url:
            from alembic.runtime.migration import MigrationContext
            from sqlalchemy import create_engine

            engine = create_engine(db_url)
            with engine.connect() as conn:
                context = MigrationContext.configure(conn)
                current_rev = context.get_current_revision()
            engine.dispose()
            if current_rev:
                schema_status, schema_detail = "pass", f"Alembic revision: {current_rev}"
            else:
                schema_status, schema_detail = (
                    "warn",
                    "No Alembic revision found. Fix: run a-sdlc db migrate",
                )
        else:
            schema_status, schema_detail = (
                "warn",
                "No database URL configured. Fix: set A_SDLC_DATABASE_URL",
            )
    except Exception as e:
        schema_status, schema_detail = (
            "fail",
            f"Cannot check schema: {e}. Fix: run a-sdlc db migrate",
        )

    checks.append(
        {"name": "Database schema version", "status": schema_status, "detail": schema_detail}
    )

    # Display results
    table = Table(show_header=True, header_style="bold")
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Details", style="dim")

    all_ok = True
    has_warnings = False
    for check in checks:
        status = check["status"]
        if status == "pass":
            status_str = "[green]PASS[/green]"
        elif status == "warn":
            status_str = "[yellow]WARN[/yellow]"
            has_warnings = True
        else:
            status_str = "[red]FAIL[/red]"
            all_ok = False

        table.add_row(check["name"], status_str, check["detail"])

    console.print(table)
    console.print()

    if all_ok and not has_warnings:
        console.print("[green]All checks passed![/green]")
    elif all_ok:
        console.print("[yellow]Passed with warnings. Some features may be limited.[/yellow]")
    else:
        console.print("[red]Some checks failed. Please address the issues above.[/red]")
        if not check_consistency:
            sys.exit(1)

    # Consistency check (--check-consistency / --repair)
    if check_consistency:
        from a_sdlc.storage import HybridStorage

        console.print()
        console.print(Panel("[bold]Data Consistency Check[/bold]", border_style="blue"))

        storage = HybridStorage()
        projects = storage.list_projects()

        if not projects:
            console.print("[dim]No projects registered.[/dim]")
        else:
            has_inconsistencies = False

            for project in projects:
                project_id = project["id"]
                project_name = project.get("name", project_id)
                result = storage.consistency_check(project_id)

                orphaned = result["orphaned_files"]
                phantoms = result["phantom_records"]
                total = result["total_entities"]

                if not orphaned and not phantoms:
                    console.print(
                        f"  [green]✓[/green] {project_name} ({project_id}): "
                        f"{total} entities, no inconsistencies"
                    )
                    continue

                has_inconsistencies = True
                console.print(
                    f"  [red]✗[/red] {project_name} ({project_id}): "
                    f"{total} entities, "
                    f"{len(orphaned)} orphaned file(s), "
                    f"{len(phantoms)} phantom record(s)"
                )

                for item in orphaned:
                    console.print(
                        f"    [yellow]orphaned {item['entity_type']}[/yellow]: "
                        f"{item['id']} ({item['file_path']})"
                    )

                for item in phantoms:
                    console.print(
                        f"    [yellow]phantom {item['entity_type']}[/yellow]: "
                        f"{item['id']} (DB record, no file)"
                    )

                # Repair if requested
                if repair and (orphaned or phantoms):
                    fix_count = len(orphaned) + len(phantoms)
                    if click.confirm(f"  Repair {fix_count} inconsistencies in {project_name}?"):
                        repair_result = storage.repair_consistency(project_id, dry_run=False)
                        console.print(
                            f"    [green]Repaired:[/green] "
                            f"{repair_result['repaired_orphans']} orphaned file(s), "
                            f"{repair_result['repaired_phantoms']} phantom record(s)"
                        )
                    else:
                        console.print("    [dim]Skipped.[/dim]")

            console.print()
            if has_inconsistencies:
                if not repair:
                    console.print(
                        "[yellow]Inconsistencies found. Run with --repair to fix.[/yellow]"
                    )
                sys.exit(1)
            else:
                console.print("[green]All projects consistent.[/green]")


@main.command("build-extension")
@click.option(
    "--output",
    "-o",
    default="./dist/gemini-extension/",
    type=click.Path(path_type=Path),
    help="Output directory for the extension (default: ./dist/gemini-extension/)",
)
def build_extension(output: Path) -> None:
    """Build a Gemini CLI extension package for distribution.

    Generates a complete Gemini CLI extension directory containing
    transpiled TOML commands, MCP server manifest, and context file.

    Examples:

        a-sdlc build-extension                      # Build in ./dist/gemini-extension/
        a-sdlc build-extension -o /tmp/my-ext       # Build in custom directory
    """
    from a_sdlc.gemini_extension import build_extension_dir

    try:
        output = output.resolve()
        ext_dir = build_extension_dir(output)

        # Count transpiled commands
        commands_dir = ext_dir / "commands" / "sdlc"
        toml_count = len(list(commands_dir.glob("*.toml"))) if commands_dir.exists() else 0
        manifest_path = ext_dir / "gemini-extension.json"

        console.print()
        console.print(
            Panel(
                f"[green]Extension built successfully![/green]\n\n"
                f"Directory: [cyan]{ext_dir}[/cyan]\n"
                f"Commands:  [cyan]{toml_count} TOML files[/cyan]\n"
                f"Manifest:  [cyan]{manifest_path}[/cyan]\n\n"
                f"[bold]Install with:[/bold]\n"
                f"  gemini extensions install --path={ext_dir}",
                title="[bold]Gemini CLI Extension[/bold]",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(f"[red]Error building extension: {e}[/red]")
        sys.exit(1)


@main.group()
def plugins() -> None:
    """Manage sync plugins.

    Plugins allow tasks to be synced with external systems:
    - linear: Sync with Linear issue tracker
    - jira: Sync with Jira Cloud issue tracker
    """
    pass


@plugins.command("list")
def plugins_list() -> None:
    """List available plugins."""
    pm = get_plugin_manager()
    apm = get_artifact_plugin_manager()

    # Task plugins table
    task_table = Table(title="Task Plugins")
    task_table.add_column("Plugin", style="cyan")
    task_table.add_column("Status")
    task_table.add_column("Description", style="dim")

    task_descriptions = {
        "linear": "Sync tasks with Linear issue tracker",
        "jira": "Sync tasks with Jira Cloud issue tracker",
    }

    enabled_task = pm.get_enabled_plugin()

    for plugin in pm.list_plugins():
        is_enabled = plugin == enabled_task
        status = "[green]Enabled[/green]" if is_enabled else "[dim]Available[/dim]"
        task_table.add_row(plugin, status, task_descriptions.get(plugin, ""))

    console.print(task_table)
    console.print()

    # Artifact plugins table
    artifact_table = Table(title="Artifact Plugins")
    artifact_table.add_column("Plugin", style="cyan")
    artifact_table.add_column("Status")
    artifact_table.add_column("Description", style="dim")

    artifact_descriptions = {
        "local": "File-based artifact storage in .sdlc/artifacts/",
        "confluence": "Publish artifacts to Confluence Cloud wiki pages",
    }

    enabled_artifact = apm.get_enabled_plugin()

    for plugin in apm.list_plugins():
        is_enabled = plugin == enabled_artifact
        status = "[green]Enabled[/green]" if is_enabled else "[dim]Available[/dim]"
        artifact_table.add_row(plugin, status, artifact_descriptions.get(plugin, ""))

    console.print(artifact_table)


@plugins.command("enable")
@click.argument("plugin_name")
@click.option(
    "--type",
    "-t",
    "plugin_type",
    type=click.Choice(["task", "artifact"]),
    default=None,
    help="Plugin type (task or artifact). Auto-detected if not specified.",
)
@click.option(
    "--global",
    "-g",
    "save_global",
    is_flag=True,
    help="Save to global config (~/.config/a-sdlc/) instead of project config (.sdlc/)",
)
def plugins_enable(plugin_name: str, plugin_type: str | None, save_global: bool) -> None:
    """Enable a specific plugin.

    PLUGIN_NAME: Name of the plugin to enable (e.g., 'jira', 'confluence')

    By default, saves to project config (.sdlc/config.yaml).
    Use --global to save to user-wide config (~/.config/a-sdlc/config.yaml).
    """
    pm = get_plugin_manager()
    apm = get_artifact_plugin_manager()
    target = cast(Literal["global", "project"], "global" if save_global else "project")

    # Auto-detect plugin type if not specified
    if plugin_type is None:
        if plugin_name in pm.list_plugins():
            plugin_type = "task"
        elif plugin_name in apm.list_plugins():
            plugin_type = "artifact"
        else:
            console.print(f"[red]Unknown plugin: {plugin_name}[/red]")
            console.print(f"Task plugins: {', '.join(pm.list_plugins())}")
            console.print(f"Artifact plugins: {', '.join(apm.list_plugins())}")
            sys.exit(1)

    try:
        location = "global config" if save_global else "project config"

        if plugin_type == "task":
            pm.enable_plugin(plugin_name, target=target)
            console.print(f"[green]Task plugin '{plugin_name}' enabled in {location}.[/green]")

            if plugin_name == "linear":
                console.print()
                console.print("Next steps:")
                console.print("  1. Run [cyan]a-sdlc plugins configure linear[/cyan]")
                console.print("  2. Set your Linear API key and team settings")
            elif plugin_name == "jira":
                console.print()
                console.print("Next steps:")
                console.print("  1. Run [cyan]a-sdlc plugins configure jira[/cyan]")
                console.print("  2. Set your Atlassian site URL, credentials, and project key")
        else:
            apm.enable_plugin(plugin_name, target=target)
            console.print(f"[green]Artifact plugin '{plugin_name}' enabled in {location}.[/green]")

            if plugin_name == "confluence":
                console.print()
                console.print("Next steps:")
                console.print("  1. Run [cyan]a-sdlc plugins configure confluence[/cyan]")
                console.print("  2. Set your Atlassian site URL, credentials, and space key")

    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@plugins.command("configure")
@click.argument("plugin_name")
@click.option(
    "--global",
    "-g",
    "save_global",
    is_flag=True,
    help="Save to global config (~/.config/a-sdlc/) instead of project config (.sdlc/)",
)
def plugins_configure(plugin_name: str, save_global: bool) -> None:
    """Configure a plugin interactively.

    PLUGIN_NAME: Name of the plugin to configure (task plugins: local, linear, jira; artifact plugins: confluence)

    By default, saves to project config (.sdlc/config.yaml).
    Use --global to save to user-wide config (~/.config/a-sdlc/config.yaml).
    """
    pm = get_plugin_manager()
    apm = get_artifact_plugin_manager()
    target = cast(Literal["global", "project"], "global" if save_global else "project")

    # Check if it's a task plugin
    if plugin_name in pm.list_plugins():
        if plugin_name == "local":
            console.print("[dim]Local plugin has no configuration options.[/dim]")
            return

        if plugin_name == "linear":
            _configure_linear_plugin(pm, target=target)
            return

        if plugin_name == "jira":
            _configure_jira_plugin(pm, target=target)
            return

    # Check if it's an artifact plugin
    if plugin_name in apm.list_plugins():
        if plugin_name == "local":
            console.print("[dim]Local artifact plugin has no configuration options.[/dim]")
            return

        if plugin_name == "confluence":
            _configure_confluence_plugin(apm, target=target)
            return

    console.print(f"[red]Unknown plugin: {plugin_name}[/red]")
    console.print(f"Task plugins: {', '.join(pm.list_plugins())}")
    console.print(f"Artifact plugins: {', '.join(apm.list_plugins())}")
    sys.exit(1)


def _configure_linear_plugin(
    pm: "PluginManager", target: Literal["global", "project"] = "project"
) -> None:
    """Interactive configuration for Linear plugin."""
    location = "global config" if target == "global" else "project config"
    console.print(
        Panel(
            f"[bold]Linear Plugin Configuration[/bold]\n\n"
            f"Saving to: {location}\n\n"
            "You'll need:\n"
            "  - Linear API key (from Settings > API)\n"
            "  - Team ID (visible in team URL)",
            border_style="blue",
        )
    )

    api_key = click.prompt("Linear API Key", hide_input=True)
    team_id = click.prompt("Team ID (e.g., 'ENG')")
    default_project = click.prompt("Default Project Name (optional)", default="")

    config = {
        "api_key": api_key,
        "team_id": team_id,
        "default_project": default_project or None,
        "sync_on_create": True,
        "sync_on_complete": True,
    }

    pm.configure_plugin("linear", config, target=target)
    console.print(f"[green]Linear plugin configured in {location}![/green]")


def _configure_jira_plugin(
    pm: "PluginManager", target: Literal["global", "project"] = "project"
) -> None:
    """Interactive configuration for Jira plugin."""
    location = "global config" if target == "global" else "project config"
    console.print(
        Panel(
            f"[bold]Jira Cloud Plugin Configuration[/bold]\n\n"
            f"Saving to: {location}\n\n"
            "You'll need:\n"
            "  - Atlassian site URL (e.g., https://company.atlassian.net)\n"
            "  - Atlassian account email\n"
            "  - API token (from https://id.atlassian.com/manage-profile/security/api-tokens)\n"
            "  - Jira project key (e.g., 'PROJ')",
            border_style="blue",
        )
    )

    base_url = click.prompt("Atlassian Site URL (e.g., https://company.atlassian.net)")
    email = click.prompt("Atlassian Email")
    api_token = click.prompt("API Token", hide_input=True)
    project_key = click.prompt("Jira Project Key (e.g., 'PROJ')")
    issue_type = click.prompt("Default Issue Type", default="Task")

    config = {
        "base_url": base_url.rstrip("/"),
        "email": email,
        "api_token": api_token,
        "project_key": project_key,
        "issue_type": issue_type,
        "sync_on_create": True,
        "sync_on_complete": True,
    }

    pm.configure_plugin("jira", config, target=target)
    console.print(f"[green]Jira plugin configured in {location}![/green]")


def _configure_confluence_plugin(
    apm: "ArtifactPluginManager", target: Literal["global", "project"] = "project"
) -> None:
    """Interactive configuration for Confluence plugin."""
    location = "global config" if target == "global" else "project config"
    console.print(
        Panel(
            f"[bold]Confluence Cloud Plugin Configuration[/bold]\n\n"
            f"Saving to: {location}\n\n"
            "You'll need:\n"
            "  - Atlassian site URL (e.g., https://company.atlassian.net)\n"
            "  - Atlassian account email\n"
            "  - API token (from https://id.atlassian.com/manage-profile/security/api-tokens)\n"
            "  - Confluence space key (e.g., 'PROJ')\n"
            "  - Optional: Parent page ID for SDLC documentation",
            border_style="blue",
        )
    )

    base_url = click.prompt("Atlassian Site URL (e.g., https://company.atlassian.net)")
    email = click.prompt("Atlassian Email")
    api_token = click.prompt("API Token", hide_input=True)
    space_key = click.prompt("Confluence Space Key (e.g., 'PROJ')")
    parent_page_id = click.prompt("Parent Page ID (optional, press Enter to skip)", default="")
    page_title_prefix = click.prompt("Page Title Prefix", default="[SDLC]")

    config = {
        "base_url": base_url.rstrip("/"),
        "email": email,
        "api_token": api_token,
        "space_key": space_key,
        "parent_page_id": parent_page_id or None,
        "page_title_prefix": page_title_prefix,
    }

    apm.configure_plugin("confluence", config, target=target)
    console.print(f"[green]Confluence plugin configured in {location}![/green]")


# =============================================================================
# Artifacts Commands (sync with Confluence)
# =============================================================================


@main.group()
def artifacts() -> None:
    """Manage and sync documentation artifacts.

    Artifacts are generated by /sdlc:scan and stored in .sdlc/artifacts/.
    Use these commands to sync with Confluence:

    \b
      a-sdlc artifacts status   Show sync status
      a-sdlc artifacts push     Push local → Confluence
      a-sdlc artifacts pull     Pull Confluence → local
    """
    pass


def _to_naive_utc(dt: datetime) -> datetime:
    """Convert datetime to naive UTC for safe comparison."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


@artifacts.command("status")
def artifacts_status() -> None:
    """Show sync status of artifacts.

    Compares local artifacts with Confluence to show what needs syncing.
    """
    from a_sdlc.artifacts.base import Artifact
    from a_sdlc.artifacts.local import LocalArtifactPlugin

    artifacts_dir = Path.cwd() / ".sdlc" / "artifacts"

    if not artifacts_dir.exists():
        console.print("[yellow]No artifacts found. Run /sdlc:scan first.[/yellow]")
        return

    local = LocalArtifactPlugin({"artifacts_dir": str(artifacts_dir)})
    local_artifacts = local.list_artifacts()

    if not local_artifacts:
        console.print("[yellow]No artifacts found in .sdlc/artifacts/[/yellow]")
        return

    # Try to get Confluence data for comparison
    remote_artifacts_map: dict[str, Artifact] = {}
    confluence_available = False

    try:
        apm = get_artifact_plugin_manager()
        confluence = apm.get_plugin("confluence")
        remote_list = confluence.list_artifacts()
        remote_artifacts_map = {a.id: a for a in remote_list}
        confluence_available = True
    except Exception:
        # Confluence not configured or unavailable - show local-only status
        pass

    # Build comparison table
    table = Table(title="Artifact Sync Status")
    table.add_column("Artifact", style="cyan")
    table.add_column("Local", style="dim")
    if confluence_available:
        table.add_column("Remote", style="dim")
    table.add_column("Status")
    if confluence_available:
        table.add_column("URL", style="dim", max_width=40)

    for artifact in local_artifacts:
        local_time = artifact.updated_at.strftime("%Y-%m-%d %H:%M")
        remote = remote_artifacts_map.get(artifact.id)

        if not confluence_available:
            # Fallback: show local-only status
            if artifact.external_id:
                status = "[green]✓ Published[/green]"
            else:
                status = "[yellow]○ Not published[/yellow]"
            table.add_row(artifact.id, local_time, status)
        elif remote:
            remote_time = remote.updated_at.strftime("%Y-%m-%d %H:%M")
            # Compare timestamps (with 60-second tolerance)
            time_diff = (
                _to_naive_utc(artifact.updated_at) - _to_naive_utc(remote.updated_at)
            ).total_seconds()

            if abs(time_diff) < 60:
                status = "[green]✓ In sync[/green]"
            elif time_diff > 0:
                status = "[yellow]⬆ Local newer[/yellow]"
            else:
                status = "[cyan]⬇ Remote newer[/cyan]"

            url = remote.external_url or "-"
            # Truncate URL for display
            if len(url) > 40:
                url = url[:37] + "..."
            table.add_row(artifact.id, local_time, remote_time, status, url)
        else:
            # Local has external_id but not found in remote
            if artifact.external_id:
                status = "[red]✗ Missing remote[/red]"
            else:
                status = "[yellow]○ Not published[/yellow]"
            table.add_row(artifact.id, local_time, "-", status, "-")

    console.print(table)

    # Check for remote-only artifacts
    if confluence_available:
        local_ids = {a.id for a in local_artifacts}
        remote_only = [a for a in remote_artifacts_map.values() if a.id not in local_ids]

        if remote_only:
            console.print()
            console.print("[cyan]Remote-only artifacts (not in local):[/cyan]")
            for artifact in remote_only:
                console.print(f"  • {artifact.id}")

    # Summary
    console.print()
    if confluence_available:
        in_sync = sum(
            1
            for a in local_artifacts
            if a.id in remote_artifacts_map
            and abs(
                (
                    _to_naive_utc(a.updated_at)
                    - _to_naive_utc(remote_artifacts_map[a.id].updated_at)
                ).total_seconds()
            )
            < 60
        )
        local_newer = sum(
            1
            for a in local_artifacts
            if a.id in remote_artifacts_map
            and (
                _to_naive_utc(a.updated_at) - _to_naive_utc(remote_artifacts_map[a.id].updated_at)
            ).total_seconds()
            >= 60
        )
        not_published = sum(
            1 for a in local_artifacts if a.id not in remote_artifacts_map and not a.external_id
        )

        console.print(
            f"In sync: {in_sync} | Local newer: {local_newer} | Not published: {not_published}"
        )

        if local_newer > 0:
            console.print()
            console.print(
                "Run [cyan]a-sdlc artifacts push[/cyan] to sync local changes to Confluence."
            )
    else:
        published = sum(1 for a in local_artifacts if a.external_id)
        console.print(f"Published: {published}/{len(local_artifacts)} artifacts")
        console.print("[dim](Confluence not configured - showing local status only)[/dim]")


@artifacts.command("push")
@click.argument("artifact_name", required=False)
@click.option("--force", "-f", is_flag=True, help="Force republish all artifacts")
@click.option(
    "--dry-run", is_flag=True, help="Show what would be published without actually publishing"
)
def artifacts_push(artifact_name: str | None, force: bool, dry_run: bool) -> None:
    """Push local artifacts to Confluence.

    Similar to 'git push' - uploads local artifacts to Confluence.

    \b
    Examples:
      a-sdlc artifacts push              Push unpublished artifacts
      a-sdlc artifacts push architecture Push specific artifact
      a-sdlc artifacts push --force      Republish all artifacts
      a-sdlc artifacts push --dry-run    Preview what would be published
    """
    from a_sdlc.artifacts.local import LocalArtifactPlugin

    artifacts_dir = Path.cwd() / ".sdlc" / "artifacts"

    if not artifacts_dir.exists():
        console.print("[red]No artifacts found. Run /sdlc:scan first.[/red]")
        sys.exit(1)

    # Get local artifacts
    local = LocalArtifactPlugin({"artifacts_dir": str(artifacts_dir)})
    local_artifacts = local.list_artifacts()

    if not local_artifacts:
        console.print("[yellow]No artifacts found in .sdlc/artifacts/[/yellow]")
        return

    # Filter by name if specified
    if artifact_name:
        local_artifacts = [
            a
            for a in local_artifacts
            if a.id == artifact_name or a.id == artifact_name.replace(".md", "")
        ]
        if not local_artifacts:
            console.print(f"[red]Artifact not found: {artifact_name}[/red]")
            sys.exit(1)

    # Filter to unpublished unless --force
    if not force:
        to_publish = [a for a in local_artifacts if not a.external_id]
        if not to_publish and not artifact_name:
            console.print("[green]All artifacts already published.[/green]")
            console.print("Use [cyan]--force[/cyan] to republish.")
            return
        if artifact_name:
            to_publish = local_artifacts  # Republish specific artifact
    else:
        to_publish = local_artifacts

    if dry_run:
        console.print("[bold]Dry run - would publish:[/bold]")
        for artifact in to_publish:
            action = "Update" if artifact.external_id else "Create"
            console.print(f"  {action}: {artifact.id} ({artifact.title})")
        return

    # Get Confluence plugin
    apm = get_artifact_plugin_manager()
    try:
        confluence = apm.get_plugin("confluence")
    except Exception as e:
        console.print(f"[red]Failed to initialize Confluence plugin: {e}[/red]")
        console.print("Run [cyan]a-sdlc plugins configure confluence[/cyan] first.")
        sys.exit(1)

    # Publish artifacts
    console.print(f"[bold]Publishing {len(to_publish)} artifact(s) to Confluence...[/bold]")
    console.print()

    success = 0
    failed = 0

    for artifact in to_publish:
        try:
            action = "Updating" if artifact.external_id else "Creating"
            console.print(f"  {action} {artifact.id}...", end=" ")

            confluence.store_artifact(artifact)

            # Update local metadata with external link
            local.update_external_link(
                artifact.id,
                artifact.external_id or "",
                artifact.external_url or "",
            )

            console.print("[green]✓[/green]")
            if artifact.external_url:
                console.print(f"    [dim]{artifact.external_url}[/dim]")
            success += 1

        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            failed += 1

    console.print()
    console.print(f"[bold]Done:[/bold] {success} published, {failed} failed")


@artifacts.command("pull")
@click.argument("artifact_name", required=False)
@click.option("--force", "-f", is_flag=True, help="Overwrite local artifacts")
@click.option("--dry-run", is_flag=True, help="Show what would be pulled without actually pulling")
def artifacts_pull(artifact_name: str | None, force: bool, dry_run: bool) -> None:
    """Pull artifacts from Confluence to local.

    Similar to 'git pull' - downloads artifacts from Confluence.

    Note: This overwrites local .sdlc/artifacts/ files with Confluence content.
    The content format may differ slightly due to markdown/ADF conversion.

    \b
    Examples:
      a-sdlc artifacts pull              Pull all artifacts
      a-sdlc artifacts pull architecture Pull specific artifact
      a-sdlc artifacts pull --dry-run    Preview what would be pulled
    """
    from a_sdlc.artifacts.local import LocalArtifactPlugin

    artifacts_dir = Path.cwd() / ".sdlc" / "artifacts"

    # Get Confluence plugin
    apm = get_artifact_plugin_manager()
    try:
        confluence = apm.get_plugin("confluence")
    except Exception as e:
        console.print(f"[red]Failed to initialize Confluence plugin: {e}[/red]")
        console.print("Run [cyan]a-sdlc plugins configure confluence[/cyan] first.")
        sys.exit(1)

    # Get artifacts from Confluence
    console.print("Fetching artifacts from Confluence...")
    try:
        remote_artifacts = confluence.list_artifacts()
    except Exception as e:
        console.print(f"[red]Failed to fetch from Confluence: {e}[/red]")
        sys.exit(1)

    if not remote_artifacts:
        console.print("[yellow]No SDLC artifacts found in Confluence.[/yellow]")
        return

    # Filter by name if specified
    if artifact_name:
        remote_artifacts = [
            a
            for a in remote_artifacts
            if a.id == artifact_name or a.id == artifact_name.replace(".md", "")
        ]
        if not remote_artifacts:
            console.print(f"[red]Artifact not found in Confluence: {artifact_name}[/red]")
            sys.exit(1)

    if dry_run:
        console.print("[bold]Dry run - would pull:[/bold]")
        for artifact in remote_artifacts:
            console.print(f"  {artifact.id} ({artifact.title})")
            if artifact.external_url:
                console.print(f"    [dim]{artifact.external_url}[/dim]")
        return

    # Check for local artifacts that would be overwritten
    local = LocalArtifactPlugin({"artifacts_dir": str(artifacts_dir)})
    local_artifacts = {a.id: a for a in local.list_artifacts()}

    if not force:
        conflicts = [a for a in remote_artifacts if a.id in local_artifacts]
        if conflicts:
            console.print(
                "[yellow]Warning: The following local artifacts will be overwritten:[/yellow]"
            )
            for artifact in conflicts:
                console.print(f"  - {artifact.id}")
            console.print()
            if not click.confirm("Continue?"):
                console.print("Aborted.")
                return

    # Pull artifacts
    console.print(f"[bold]Pulling {len(remote_artifacts)} artifact(s) from Confluence...[/bold]")
    console.print()

    success = 0
    failed = 0

    for artifact in remote_artifacts:
        try:
            console.print(f"  Pulling {artifact.id}...", end=" ")

            # Store locally
            local.store_artifact(artifact)

            console.print("[green]✓[/green]")
            success += 1

        except Exception as e:
            console.print(f"[red]✗ {e}[/red]")
            failed += 1

    console.print()
    console.print(f"[bold]Done:[/bold] {success} pulled, {failed} failed")


# =============================================================================
# PRD Commands (Product Requirements Documents)
# =============================================================================


@main.group()
def prd() -> None:
    """Manage Product Requirements Documents (PRDs).

    PRDs are stored locally in .sdlc/prds/ and can be synced with Confluence.
    Each project can have multiple PRDs for different features.

    \b
      a-sdlc prd list           List available PRDs (local and Confluence)
      a-sdlc prd show <id>      Display PRD content
      a-sdlc prd pull <title>   Pull specific PRD from Confluence
      a-sdlc prd push <file>    Push local PRD to Confluence
    """
    pass


@prd.command("list")
@click.option("--local", "-l", "local_only", is_flag=True, help="Show only local PRDs")
@click.option("--remote", "-r", "remote_only", is_flag=True, help="Show only Confluence PRDs")
def prd_list(local_only: bool, remote_only: bool) -> None:
    """List PRDs (local and Confluence).

    Shows all PRDs available locally and in Confluence,
    with sync status indicators.
    """
    from a_sdlc.artifacts.prd_local import LocalPRDPlugin

    prds_dir = Path.cwd() / ".sdlc" / "prds"

    # Get local PRDs
    local = LocalPRDPlugin({"prds_dir": str(prds_dir)})
    local_prds = local.list_prds() if not remote_only else []

    # Get Confluence PRDs
    remote_prds: list[dict] = []
    confluence_available = False

    if not local_only:
        apm = get_artifact_plugin_manager()
        try:
            confluence = apm.get_plugin("confluence")
            remote_prds = confluence.list_prds()  # type: ignore[attr-defined]  # Confluence subclass method
            confluence_available = True
        except Exception:
            if remote_only:
                console.print("[red]Confluence not configured.[/red]")
                console.print("Run [cyan]a-sdlc plugins configure confluence[/cyan] first.")
                sys.exit(1)

    # Build combined view
    table = Table(title="Product Requirements Documents")
    table.add_column("ID", style="cyan")
    table.add_column("Title")
    table.add_column("Local", justify="center")
    table.add_column("Confluence", justify="center")

    # Track seen PRDs
    seen_ids: set[str] = set()

    # Add local PRDs
    for prd_obj in local_prds:
        seen_ids.add(prd_obj.id)

        local_status = "[green]✓[/green]"
        remote_status = "[green]✓[/green]" if prd_obj.external_id else "[dim]-[/dim]"

        table.add_row(prd_obj.id, prd_obj.title, local_status, remote_status)

    # Add remote PRDs not in local
    from a_sdlc.artifacts.prd import _slugify

    for remote_prd in remote_prds:
        prd_id = _slugify(remote_prd["title"])
        if prd_id not in seen_ids:
            table.add_row(
                prd_id,
                remote_prd["title"],
                "[dim]-[/dim]",
                "[green]✓[/green]",
            )

    console.print(table)

    # Summary
    console.print()
    console.print(f"Local: {len(local_prds)} PRD(s)")

    if confluence_available:
        console.print(f"Confluence: {len(remote_prds)} PRD(s)")
    else:
        console.print("[dim]Confluence: Not configured[/dim]")


@prd.command("show")
@click.argument("prd_id")
def prd_show(prd_id: str) -> None:
    """Display PRD content.

    PRD_ID: The ID (slug) of the PRD to display.

    \b
    Examples:
      a-sdlc prd show feature-auth
      a-sdlc prd show payment-system
    """
    from a_sdlc.artifacts.prd_local import LocalPRDPlugin

    prds_dir = Path.cwd() / ".sdlc" / "prds"
    local = LocalPRDPlugin({"prds_dir": str(prds_dir)})

    prd_obj = local.get_prd(prd_id)

    if not prd_obj:
        console.print(f"[red]PRD not found: {prd_id}[/red]")
        console.print()
        console.print("Available PRDs:")
        for p in local.list_prds():
            console.print(f"  - {p.id}")
        sys.exit(1)

    # Display PRD info
    console.print(
        Panel(
            f"[bold]{prd_obj.title}[/bold]\n\n"
            f"ID: {prd_obj.id}\n"
            f"Version: {prd_obj.version}\n"
            f"Updated: {prd_obj.updated_at.strftime('%Y-%m-%d %H:%M')}\n"
            f"Confluence: {prd_obj.external_url or 'Not synced'}",
            title="PRD Info",
            border_style="blue",
        )
    )

    console.print()
    console.print(prd_obj.content)


@prd.command("pull")
@click.argument("title")
@click.option("--force", "-f", is_flag=True, help="Overwrite local PRD if exists")
def prd_pull(title: str, force: bool) -> None:
    """Pull specific PRD from Confluence.

    TITLE: The title of the PRD in Confluence.

    Downloads a PRD from Confluence and saves it locally in .sdlc/prds/.
    The PRD content is converted from Confluence storage format to Markdown.

    \b
    Examples:
      a-sdlc prd pull "Feature Auth"
      a-sdlc prd pull "Payment System" --force
    """
    from a_sdlc.artifacts.prd import _slugify
    from a_sdlc.artifacts.prd_local import LocalPRDPlugin

    prds_dir = Path.cwd() / ".sdlc" / "prds"

    # Get Confluence plugin
    apm = get_artifact_plugin_manager()
    try:
        confluence = apm.get_plugin("confluence")
    except Exception as e:
        console.print(f"[red]Failed to initialize Confluence plugin: {e}[/red]")
        console.print("Run [cyan]a-sdlc plugins configure confluence[/cyan] first.")
        sys.exit(1)

    # Check if local PRD exists
    local = LocalPRDPlugin({"prds_dir": str(prds_dir)})
    prd_id = _slugify(title)

    if local.exists(prd_id) and not force:
        console.print(f"[yellow]Local PRD already exists: {prd_id}[/yellow]")
        console.print("Use [cyan]--force[/cyan] to overwrite.")
        sys.exit(1)

    # Pull from Confluence
    console.print(f"Pulling PRD: {title}...")

    try:
        prd_obj = confluence.pull_prd(title)  # type: ignore[attr-defined]  # Confluence subclass method
    except KeyError:
        console.print(f"[red]PRD not found in Confluence: {title}[/red]")
        console.print()
        console.print("Available PRDs in Confluence:")
        for remote_prd in confluence.list_prds():  # type: ignore[attr-defined]  # Confluence subclass method
            console.print(f"  - {remote_prd['title']}")
        sys.exit(1)
    except RuntimeError as e:
        console.print(f"[red]Failed to pull PRD: {e}[/red]")
        sys.exit(1)

    # Save locally
    local.store_prd(prd_obj)

    console.print(f"[green]PRD saved to: .sdlc/prds/{prd_obj.id}.md[/green]")

    if prd_obj.external_url:
        console.print(f"[dim]Source: {prd_obj.external_url}[/dim]")


@prd.command("push")
@click.argument("prd_id_or_file")
@click.option("--force", "-f", is_flag=True, help="Update existing Confluence page")
def prd_push(prd_id_or_file: str, force: bool) -> None:
    """Push local PRD to Confluence.

    PRD_ID_OR_FILE: Either a PRD ID (slug) or a file path.

    Uploads a local PRD to Confluence under the PRDs folder.
    Creates a new page or updates an existing one.

    \b
    Examples:
      a-sdlc prd push feature-auth
      a-sdlc prd push .sdlc/prds/payment-system.md
      a-sdlc prd push feature-auth --force
    """
    from a_sdlc.artifacts.prd import PRD
    from a_sdlc.artifacts.prd_local import LocalPRDPlugin

    prds_dir = Path.cwd() / ".sdlc" / "prds"

    # Determine if it's a file path or PRD ID
    if Path(prd_id_or_file).exists():
        # It's a file path
        filepath = Path(prd_id_or_file)
        content = filepath.read_text(encoding="utf-8")
        prd_obj = PRD.from_file(str(filepath), content)

        # Store in local storage first
        local = LocalPRDPlugin({"prds_dir": str(prds_dir)})
        local.store_prd(prd_obj)
    else:
        # It's a PRD ID
        local = LocalPRDPlugin({"prds_dir": str(prds_dir)})
        prd_obj = local.get_prd(prd_id_or_file)  # type: ignore[assignment]  # Narrowed by null check below

        if not prd_obj:
            console.print(f"[red]PRD not found: {prd_id_or_file}[/red]")
            console.print()
            console.print("Available PRDs:")
            for p in local.list_prds():
                console.print(f"  - {p.id}")
            sys.exit(1)

    # Get Confluence plugin
    apm = get_artifact_plugin_manager()
    try:
        confluence = apm.get_plugin("confluence")
    except Exception as e:
        console.print(f"[red]Failed to initialize Confluence plugin: {e}[/red]")
        console.print("Run [cyan]a-sdlc plugins configure confluence[/cyan] first.")
        sys.exit(1)

    # Check if page exists in Confluence
    existing = confluence.get_prd_page(prd_obj.title)  # type: ignore[attr-defined]  # Confluence subclass method
    if existing and not force:
        console.print(f"[yellow]PRD already exists in Confluence: {prd_obj.title}[/yellow]")
        console.print("Use [cyan]--force[/cyan] to update.")
        sys.exit(1)

    # Push to Confluence
    action = "Updating" if existing else "Creating"
    console.print(f"{action} PRD in Confluence: {prd_obj.title}...")

    try:
        page_id = confluence.push_prd(prd_obj)  # type: ignore[attr-defined]  # Confluence subclass method
    except RuntimeError as e:
        console.print(f"[red]Failed to push PRD: {e}[/red]")
        sys.exit(1)

    # Update local metadata with external link
    local.update_external_link(
        prd_obj.id,
        prd_obj.external_id or page_id,
        prd_obj.external_url or "",
    )

    console.print("[green]PRD pushed successfully![/green]")

    if prd_obj.external_url:
        console.print(f"URL: {prd_obj.external_url}")


@prd.command("delete")
@click.argument("prd_id")
@click.option("--local", "-l", "local_only", is_flag=True, help="Delete only local PRD")
@click.option("--remote", "-r", "remote_only", is_flag=True, help="Delete only from Confluence")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def prd_delete(prd_id: str, local_only: bool, remote_only: bool, yes: bool) -> None:
    """Delete a PRD.

    PRD_ID: The ID (slug) of the PRD to delete.

    By default, deletes from both local and Confluence.
    Use --local or --remote to delete from only one location.

    \b
    Examples:
      a-sdlc prd delete feature-auth
      a-sdlc prd delete feature-auth --local
      a-sdlc prd delete feature-auth --remote
    """
    from a_sdlc.artifacts.prd_local import LocalPRDPlugin

    prds_dir = Path.cwd() / ".sdlc" / "prds"
    local = LocalPRDPlugin({"prds_dir": str(prds_dir)})

    # Confirm deletion
    if not yes:
        locations = []
        if not remote_only:
            locations.append("local")
        if not local_only:
            locations.append("Confluence")
        location_str = " and ".join(locations)

        if not click.confirm(f"Delete PRD '{prd_id}' from {location_str}?"):
            console.print("Aborted.")
            return

    # Delete from local
    if not remote_only:
        try:
            local.delete_prd(prd_id)
            console.print(f"[green]Deleted local PRD: {prd_id}[/green]")
        except KeyError:
            if local_only:
                console.print(f"[red]Local PRD not found: {prd_id}[/red]")
                sys.exit(1)
            else:
                console.print(f"[dim]Local PRD not found: {prd_id}[/dim]")

    # Delete from Confluence
    if not local_only:
        apm = get_artifact_plugin_manager()
        try:
            confluence = apm.get_plugin("confluence")

            # Find PRD in Confluence
            prd_obj = local.get_prd(prd_id)
            title = prd_obj.title if prd_obj else prd_id.replace("-", " ").title()

            confluence.delete_prd(title)  # type: ignore[attr-defined]  # Confluence subclass method
            console.print(f"[green]Deleted from Confluence: {title}[/green]")

        except KeyError:
            if remote_only:
                console.print(f"[red]PRD not found in Confluence: {prd_id}[/red]")
                sys.exit(1)
            else:
                console.print(f"[dim]PRD not found in Confluence: {prd_id}[/dim]")
        except Exception as e:
            console.print(f"[red]Failed to delete from Confluence: {e}[/red]")
            if remote_only:
                sys.exit(1)


@prd.command("update")
@click.argument("prd_id")
@click.option("--section", "-s", help="Update specific section only")
@click.option(
    "--version",
    "-v",
    type=click.Choice(["patch", "minor", "major"]),
    help="Version bump type (auto-detect if not specified)",
)
@click.option("--fix", is_flag=True, help="Quick fix mode for typos and formatting")
@click.option("--push", is_flag=True, help="Push to Confluence after update")
def prd_update(
    prd_id: str, section: str | None, version: str | None, fix: bool, push: bool
) -> None:
    """Update an existing PRD interactively.

    PRD_ID: The ID (slug) of the PRD to update.

    Opens an interactive session to update PRD sections with AI-assisted suggestions.

    \b
    Examples:
      a-sdlc prd update feature-auth
      a-sdlc prd update feature-auth -s Goals
      a-sdlc prd update feature-auth --fix
      a-sdlc prd update feature-auth --push
    """
    from a_sdlc.artifacts.prd import bump_version, detect_change_type
    from a_sdlc.artifacts.prd_local import LocalPRDPlugin

    prds_dir = Path.cwd() / ".sdlc" / "prds"
    local = LocalPRDPlugin({"prds_dir": str(prds_dir)})

    # Load PRD
    prd_obj = local.get_prd(prd_id)
    if not prd_obj:
        console.print(f"[red]PRD not found: {prd_id}[/red]")
        available = local.list_prds()
        if available:
            console.print("\n[dim]Available PRDs:[/dim]")
            for p in available:
                console.print(f"  - {p.id}")
        console.print("\nRun: [cyan]a-sdlc prd list[/cyan]")
        sys.exit(1)

    console.print(f"[bold]Updating PRD:[/bold] {prd_obj.title}")
    console.print(f"[dim]Current version: {prd_obj.version}[/dim]\n")

    # Store original content for change detection
    original_content = prd_obj.content

    # Get sections
    sections = prd_obj.get_sections()
    if not sections:
        console.print("[yellow]No sections found in PRD[/yellow]")
        sys.exit(1)

    # Filter to specific section if requested
    if section:
        if section not in sections:
            console.print(f"[red]Section not found: {section}[/red]")
            console.print("\n[dim]Available sections:[/dim]")
            for s in sections:
                console.print(f"  - {s}")
            sys.exit(1)
        sections_to_update = {section: sections[section]}
    else:
        sections_to_update = sections

    # Quick fix mode
    if fix:
        console.print("[cyan]Quick fix mode: Auto-detecting issues...[/cyan]\n")
        # For MVP, just prompt once for changes
        console.print("Enter your fixes (or press Enter to skip):")
        user_input = click.prompt("Changes", default="", show_default=False)

        if user_input.strip():
            # Simple approach: append changes as note
            prd_obj.content += f"\n\n---\n**Update Notes**: {user_input}\n"
            change_type = "patch"
        else:
            console.print("No changes made.")
            sys.exit(0)
    else:
        # Section-by-section review
        sections_modified = []

        for section_name, content in sections_to_update.items():
            console.print(f"[bold cyan]━━━ Section: {section_name} ━━━[/bold cyan]")
            console.print("\n[dim]Current content:[/dim]")
            # Show first 200 chars
            preview = content[:200] + ("..." if len(content) > 200 else "")
            console.print(preview)
            console.print()

            action = click.prompt(
                "Action",
                type=click.Choice(["keep", "edit", "skip"]),
                default="keep",
                show_default=True,
            )

            if action == "edit":
                console.print("\n[dim]Enter new content (press Ctrl+D or Ctrl+Z when done):[/dim]")
                try:
                    new_content = click.edit(content)
                    if new_content and new_content.strip() != content.strip():
                        prd_obj.update_section_content(section_name, new_content.strip())
                        sections_modified.append(section_name)
                        console.print(f"[green]✓ Updated {section_name}[/green]\n")
                    else:
                        console.print("[dim]No changes made to section[/dim]\n")
                except Exception as e:
                    console.print(f"[red]Failed to edit section: {e}[/red]\n")
            elif action == "skip":
                console.print("[dim]Skipped[/dim]\n")
            else:  # keep
                console.print("[dim]Kept unchanged[/dim]\n")

        if not sections_modified:
            console.print("[yellow]No sections were modified[/yellow]")
            sys.exit(0)

        # Detect change type
        change_type = detect_change_type(original_content, prd_obj.content)

    # Version bump
    old_version = prd_obj.version

    if version:
        # User specified version bump
        bump_type = version
    else:
        # Auto-suggest based on change type
        if change_type == "structural":
            suggested = "major"
        elif change_type == "content":
            suggested = "minor"
        else:
            suggested = "patch"

        console.print("\n[bold]🔢 Version Bump[/bold]")
        console.print(f"Current: {old_version}")
        console.print(f"Suggested: {suggested.upper()} → {bump_version(old_version, suggested)}")

        bump_type = click.prompt(
            "Confirm bump type",
            type=click.Choice(["patch", "minor", "major"]),
            default=suggested,
            show_default=True,
        )

    # Apply version bump
    prd_obj.bump_version_auto(bump_type)

    # Save PRD
    local.store_prd(prd_obj)

    # Track update history
    if fix:
        sections_modified = ["Quick fix"]
        summary = "Quick fixes and formatting"
    else:
        summary = click.prompt(
            "\nBrief summary of changes",
            default=f"Updated {len(sections_modified)} section(s)",
            show_default=True,
        )

    local.add_update_history(
        prd_id=prd_id,
        version=prd_obj.version,
        change_type=bump_type,
        sections_modified=sections_modified,
        summary=summary,
    )

    # Display summary
    console.print(f"\n[green]✅ PRD updated: .sdlc/prds/{prd_id}.md[/green]")
    console.print("\n[bold]📊 Changes:[/bold]")
    console.print(f"  - Version: {old_version} → {prd_obj.version}")
    if not fix:
        console.print(f"  - Sections modified: {len(sections_modified)}")
    console.print(f"  - Change type: {bump_type.title()}")

    console.print("\n[bold]🔗 Next steps:[/bold]")
    console.print(f"  - View: [cyan]a-sdlc prd show {prd_id}[/cyan]")

    # Optional Confluence push
    if push:
        try:
            apm = get_artifact_plugin_manager()
            confluence = apm.get_plugin("confluence")

            console.print("\n[cyan]Pushing to Confluence...[/cyan]")
            page_id = confluence.push_prd(prd_obj)  # type: ignore[attr-defined]  # Confluence subclass method

            local.update_external_link(
                prd_obj.id,
                prd_obj.external_id or page_id,
                prd_obj.external_url or "",
            )

            console.print("[green]✓ Pushed to Confluence[/green]")
            if prd_obj.external_url:
                console.print(f"  URL: {prd_obj.external_url}")
        except Exception as e:
            console.print(f"\n[yellow]Confluence push failed: {e}[/yellow]")
            console.print("PRD updated locally. Push manually with:")
            console.print(f"  [cyan]a-sdlc prd push {prd_id}[/cyan]")
    else:
        console.print(f"  - Push: [cyan]a-sdlc prd push {prd_id}[/cyan]")


@prd.command("split")
@click.argument("prd_id")
@click.option(
    "--granularity",
    "-g",
    type=click.Choice(["coarse", "medium", "fine"]),
    default="medium",
    help="Task detail level",
)
@click.option("--sync", is_flag=True, help="Auto-sync to configured task system")
@click.option(
    "--format",
    "-f",
    type=click.Choice(["interactive", "json", "markdown"]),
    default="interactive",
    help="Output format",
)
def prd_split(prd_id: str, granularity: str, sync: bool, format: str) -> None:
    """Split PRD into actionable tasks with dependencies.

    PRD_ID: The ID (slug) of the PRD to split.

    Analyzes PRD requirements and generates user stories with granular tasks.
    Cross-references with project artifacts (architecture, data model, workflows).

    \b
    Examples:
      a-sdlc prd split feature-auth
      a-sdlc prd split feature-auth --granularity fine
      a-sdlc prd split feature-auth --sync
      a-sdlc prd split feature-auth --format json > tasks.json
    """
    from a_sdlc.artifacts.prd_local import LocalPRDPlugin
    from a_sdlc.artifacts.task_generator import parse_requirements_from_prd

    # Load PRD
    prds_dir = Path.cwd() / ".sdlc" / "prds"
    prd_plugin = LocalPRDPlugin({"prds_dir": str(prds_dir)})

    prd_obj = prd_plugin.get_prd(prd_id)
    if not prd_obj:
        console.print(f"[red]PRD not found: {prd_id}[/red]")
        available = prd_plugin.list_prds()
        if available:
            console.print("\n[dim]Available PRDs:[/dim]")
            for p in available:
                console.print(f"  - {p.id}")
        sys.exit(1)

    console.print(f"[bold]Splitting PRD:[/bold] {prd_obj.title}")
    console.print(f"[dim]Version: {prd_obj.version}[/dim]\n")

    # Load artifacts for context
    artifacts_dir = Path.cwd() / ".sdlc" / "artifacts"
    context = {}

    console.print("[cyan]📂 Loading project artifacts...[/cyan]")
    for artifact_name in [
        "architecture",
        "data-model",
        "key-workflows",
        "codebase-summary",
    ]:
        artifact_path = artifacts_dir / f"{artifact_name}.md"
        if artifact_path.exists():
            context[artifact_name] = artifact_path.read_text(encoding="utf-8")
            console.print(f"   [green]✓[/green] {artifact_name}")
        else:
            console.print(f"   [yellow]⚠[/yellow] {artifact_name} not found (run /sdlc:scan)")

    console.print()

    # Parse PRD sections
    sections = prd_obj.get_sections()

    # Extract requirements
    requirements = parse_requirements_from_prd(sections)
    console.print(f"[cyan]📋 Found {len(requirements)} requirements[/cyan]")

    if not requirements:
        console.print(
            "[yellow]No requirements found in PRD. Add Functional Requirements or Non-Functional Requirements section.[/yellow]"
        )
        sys.exit(1)

    # Ask clarifying questions (if interactive)
    answers = {"granularity": granularity}
    if format == "interactive":
        answers = _ask_clarification_questions(prd_obj, requirements, granularity)

    # Generate tasks
    console.print("\n[cyan]🤖 Generating tasks...[/cyan]")
    tasks = _generate_tasks_from_prd(prd_obj, context, requirements, answers)

    console.print(f"[green]✓[/green] Generated {len(tasks)} tasks\n")

    # Display tasks
    if format == "json":
        import json

        print(json.dumps([task.to_dict() for task in tasks], indent=2))
        return
    elif format == "markdown":
        for task in tasks:
            print(f"## {task.id}: {task.title}\n")
            print(f"**Component**: {task.component}")
            print(f"**Priority**: {task.priority.value}")
            deps = ", ".join(task.dependencies) if task.dependencies else "None"
            print(f"**Dependencies**: {deps}")
            print(f"\n{task.description}\n")
        return

    # Interactive review
    _display_task_summary(tasks)

    if not click.confirm("\nAccept tasks?", default=True):
        console.print("[yellow]Task generation cancelled[/yellow]")
        return

    # Save tasks via storage layer
    from a_sdlc.storage import init_storage

    pm = get_plugin_manager()
    storage = init_storage()
    project = storage.get_project_by_path(str(Path.cwd()))

    saved_ids = []
    if project:
        for task in tasks:
            task_data = storage.create_task(
                title=task.title,
                project_id=project["id"],
                priority=task.priority.value
                if hasattr(task.priority, "value")
                else str(task.priority),
                component=task.component or "",
            )
            if task_data:
                saved_ids.append(task_data["id"])
    else:
        console.print(
            "[yellow]No project found for current directory — tasks not saved to database.[/yellow]"
        )

    console.print(f"\n[green]✓ Saved {len(saved_ids)} tasks[/green]")

    # Optional sync
    provider = pm.get_enabled_plugin()
    should_sync = sync or (
        provider in ["jira", "linear"]
        and click.confirm(f"\nSync to {provider.title()}?", default=False)
    )

    if should_sync:
        _sync_tasks_to_external(pm, tasks, saved_ids)

    # Display summary
    console.print("\n[bold green]✅ Task splitting complete[/bold green]")
    console.print("\n[bold]📊 Summary:[/bold]")
    console.print(f"  - PRD: {prd_id}")
    console.print(f"  - Tasks created: {len(tasks)}")
    components = {t.component for t in tasks if t.component}
    console.print(f"  - Components: {len(components)}")
    console.print("\n[bold]🔗 Next steps:[/bold]")
    console.print("  - View tasks: [cyan]a-sdlc task list[/cyan]")
    if saved_ids:
        console.print(f"  - Start work: [cyan]a-sdlc task start {saved_ids[0]}[/cyan]")


def _ask_clarification_questions(prd_obj, requirements, granularity):
    """Ask user clarifying questions about task generation."""
    console.print("[bold cyan]🤔 Clarification Questions[/bold cyan]\n")

    answers = {}

    # Question 1: Confirm granularity
    answers["granularity"] = click.prompt(
        "Task granularity",
        type=click.Choice(["coarse", "medium", "fine"]),
        default=granularity,
        show_default=True,
    )

    # Question 2: Priority strategy
    console.print("\nPriority assignment:")
    console.print("  - uniform: All tasks same priority")
    console.print("  - dependency: Earlier tasks higher priority")
    console.print("  - manual: Review each task priority")
    answers["priority_strategy"] = click.prompt(
        "Strategy",
        type=click.Choice(["uniform", "dependency", "manual"]),
        default="dependency",
        show_default=True,
    )

    return answers


def _generate_tasks_from_prd(prd_obj, context, requirements, answers):
    """Generate tasks from PRD (MVP: simple template-based generation)."""
    from a_sdlc.plugins.base import Task, TaskPriority, TaskStatus

    tasks = []
    task_counter = 1

    # For MVP Phase 1: Create one task per requirement
    for req_id, req_desc in requirements:
        # Determine priority based on strategy
        if answers.get("priority_strategy") == "uniform":
            priority = TaskPriority.MEDIUM
        elif answers.get("priority_strategy") == "dependency":
            # Earlier tasks get higher priority
            priority = TaskPriority.HIGH if task_counter <= 3 else TaskPriority.MEDIUM
        else:
            priority = TaskPriority.MEDIUM

        task = Task(
            id=f"TASK-{task_counter:03d}",
            title=f"Implement {req_id}: {req_desc[:50]}",
            description=req_desc,
            status=TaskStatus.PENDING,
            priority=priority,
            requirement_id=req_id,
            component="TBD",  # Will be enhanced in Phase 2 with AI
            dependencies=[],
            files_to_modify=[],
            implementation_steps=[
                "Review requirement details",
                "Design implementation approach",
                "Implement functionality",
                "Write tests",
                "Document changes",
            ],
            success_criteria=[
                f"{req_id} requirements met",
                "Tests passing",
                "Code reviewed",
            ],
        )
        tasks.append(task)
        task_counter += 1

    return tasks


def _display_task_summary(tasks):
    """Display generated tasks in organized format."""
    table = Table(title="Generated Tasks")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Component", style="yellow")
    table.add_column("Priority", style="magenta")
    table.add_column("Dependencies", style="dim")

    for task in tasks:
        deps = ", ".join(task.dependencies) if task.dependencies else "None"
        table.add_row(
            task.id,
            task.title[:50],
            task.component or "N/A",
            task.priority.value,
            deps,
        )

    console.print(table)


def _sync_tasks_to_external(pm, tasks, task_ids):
    """Sync tasks to Jira or Linear."""
    provider = pm.get_enabled_plugin()

    try:
        if provider == "jira":
            plugin = pm.get_plugin("jira")

            console.print(f"\n[cyan]Syncing {len(tasks)} tasks to Jira...[/cyan]")

            for task in tasks:
                external_id = plugin.create_task(task)
                console.print(f"  ✓ {task.id} → {external_id}")

            console.print("[green]✓ All tasks synced to Jira[/green]")

        elif provider == "linear":
            console.print("[yellow]Linear sync not yet implemented[/yellow]")
            console.print("Use manual instructions from task output")

    except Exception as e:
        console.print(f"[red]Sync failed: {e}[/red]")
        console.print("Tasks saved locally. Sync manually with:")
        console.print("  [cyan]a-sdlc task sync[/cyan]")


# =============================================================================
# Task CLI Commands
# =============================================================================


@main.command("tasks")
@click.option(
    "--status",
    "-s",
    type=click.Choice(["pending", "in_progress", "completed", "blocked"]),
    help="Filter by status",
)
@click.option("--sprint", help="Filter by sprint ID")
def tasks_list(status: str | None, sprint: str | None) -> None:
    """List tasks for the current project.

    Examples:

        a-sdlc tasks                    # All tasks
        a-sdlc tasks --status pending   # Pending tasks only
        a-sdlc tasks --sprint SPRINT-01 # Tasks in sprint
    """
    from a_sdlc.storage import init_storage

    storage = init_storage()

    # Get current project
    cwd = str(Path.cwd())
    project = storage.get_project_by_path(cwd)

    if not project:
        console.print("[yellow]No project found for current directory.[/yellow]")
        console.print("Run [cyan]/sdlc:init[/cyan] in Claude Code first.")
        return

    tasks = storage.list_tasks(project["id"], status=status, sprint_id=sprint)

    if not tasks:
        console.print("[dim]No tasks found.[/dim]")
        return

    # Group by status
    by_status: dict[str, list] = {}
    for task in tasks:
        s = task["status"]
        if s not in by_status:
            by_status[s] = []
        by_status[s].append(task)

    # Display
    console.print(f"\n[bold]Tasks for {project['name']}[/bold]\n")

    status_icons = {
        "pending": "🔴",
        "in_progress": "⏳",
        "completed": "✅",
        "blocked": "🚫",
    }

    priority_colors = {
        "critical": "red bold",
        "high": "red",
        "medium": "yellow",
        "low": "dim",
    }

    for s in ["in_progress", "pending", "blocked", "completed"]:
        if s not in by_status:
            continue

        icon = status_icons.get(s, "○")
        console.print(f"{icon} [bold]{s.replace('_', ' ').title()}[/bold] ({len(by_status[s])})")

        for task in by_status[s]:
            priority = task.get("priority", "medium")
            color = priority_colors.get(priority, "")
            sprint_info = f"[dim][{task['sprint_id']}][/dim]" if task.get("sprint_id") else ""

            console.print(f"  [{color}]{task['id']}[/{color}]  {task['title'][:50]}  {sprint_info}")

        console.print()


@main.command("show")
@click.argument("task_id")
def show_task(task_id: str) -> None:
    """Show task details.

    TASK_ID: Task identifier (e.g., TASK-001)

    Examples:

        a-sdlc show TASK-001
        a-sdlc show TASK-002
    """
    from a_sdlc.storage import init_storage

    storage = init_storage()
    task = storage.get_task(task_id)

    if not task:
        console.print(f"[red]Task not found: {task_id}[/red]")
        sys.exit(1)

    # Display task details
    status_icons = {
        "pending": "🔴 Pending",
        "in_progress": "⏳ In Progress",
        "completed": "✅ Completed",
        "blocked": "🚫 Blocked",
    }

    console.print(
        Panel(
            f"[bold]{task['title']}[/bold]\n\n"
            f"Status: {status_icons.get(task['status'], task['status'])}\n"
            f"Priority: {task.get('priority', 'medium').title()}\n"
            f"Component: {task.get('component') or 'N/A'}\n"
            f"Sprint: {task.get('sprint_id') or 'None'}\n"
            f"PRD: {task.get('prd_id') or 'None'}\n"
            f"Created: {task['created_at']}\n"
            f"Updated: {task['updated_at']}",
            title=f"[cyan]{task['id']}[/cyan]",
            border_style="blue",
        )
    )

    if task.get("description"):
        console.print("\n[bold]Description:[/bold]")
        console.print(task["description"])

    if task.get("data"):
        console.print("\n[bold]Additional Data:[/bold]")
        import json

        console.print(json.dumps(task["data"], indent=2))


@main.command("start")
@click.argument("task_id")
def start_task_cmd(task_id: str) -> None:
    """Mark a task as in-progress.

    TASK_ID: Task identifier (e.g., TASK-001)

    Examples:

        a-sdlc start TASK-001
    """
    from a_sdlc.storage import init_storage

    storage = init_storage()
    task = storage.update_task(task_id, status="in_progress")

    if not task:
        console.print(f"[red]Task not found: {task_id}[/red]")
        sys.exit(1)

    console.print(f"[green]Task started: {task_id}[/green]")
    console.print(f"[dim]{task['title']}[/dim]")


@main.group(invoke_without_command=True)
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", "-p", default=3847, type=int, help="Port to bind to")
@click.pass_context
def ui(ctx: click.Context, host: str, port: int) -> None:
    """Web UI dashboard for viewing and managing PRDs, tasks, and sprints.

    Examples:

        a-sdlc ui                    # Start on http://localhost:3847
        a-sdlc ui --port 8000        # Custom port
        a-sdlc ui stop               # Stop running server
    """
    # If no subcommand is given, start the server
    if ctx.invoked_subcommand is None:
        try:
            from a_sdlc.ui import run_server
        except ImportError:
            console.print("[red]Web UI dependencies not installed.[/red]")
            console.print("Install with: [cyan]pip install 'a-sdlc[ui]'[/cyan]")
            sys.exit(1)

        console.print(f"[green]Starting a-sdlc dashboard on http://{host}:{port}[/green]")
        console.print("[dim]Press Ctrl+C to stop[/dim]")
        run_server(host=host, port=port)


@ui.command("stop")
def ui_stop() -> None:
    """Stop the running UI server.

    Stops any a-sdlc UI server that was started in the background.

    Examples:

        a-sdlc ui stop
    """
    try:
        from a_sdlc.ui import PID_FILE, stop_server
    except ImportError:
        console.print("[red]Web UI dependencies not installed.[/red]")
        console.print("Install with: [cyan]pip install 'a-sdlc[ui]'[/cyan]")
        sys.exit(1)

    if stop_server():
        console.print("[green]UI server stopped.[/green]")
    else:
        console.print("[yellow]No UI server running.[/yellow]")
        if PID_FILE.exists():
            console.print(f"[dim]Cleaned up stale PID file: {PID_FILE}[/dim]")


# =============================================================================
# Utility Functions
# =============================================================================


def _health_check_with_retry(
    url: str,
    retries: int = 3,
    backoff_delays: tuple[float, ...] = (0.5, 1.0, 2.0),
) -> bool | str:
    """Perform an HTTP health check with exponential backoff retry.

    Tries to GET the given URL up to ``retries`` times, waiting with
    exponential backoff between attempts.

    Returns:
        True if the health check succeeds (HTTP 200).
        False if all retries are exhausted (server unreachable).
        A string with error details if the server responds but unhealthily.
    """
    import time as _time
    import urllib.request

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return True
                return f"HTTP {resp.status}"
        except Exception:
            if attempt < retries - 1:
                delay = backoff_delays[min(attempt, len(backoff_delays) - 1)]
                _time.sleep(delay)
    return False


@main.command("complete")
@click.argument("task_id")
def complete_task_cmd(task_id: str) -> None:
    """Mark a task as completed.

    TASK_ID: Task identifier (e.g., TASK-001)

    Examples:

        a-sdlc complete TASK-001
    """
    from a_sdlc.storage import init_storage

    storage = init_storage()
    task = storage.update_task(task_id, status="completed")

    if not task:
        console.print(f"[red]Task not found: {task_id}[/red]")
        sys.exit(1)

    console.print(f"[green]Task completed: {task_id} ✅[/green]")
    console.print(f"[dim]{task['title']}[/dim]")


# =============================================================================
# External Integration Commands
# =============================================================================


@main.group()
def connect() -> None:
    """Configure external system integrations.

    Connect to Linear, Jira, Confluence, or GitHub for sync and PR feedback.

    \b
      a-sdlc connect linear      Configure Linear integration
      a-sdlc connect jira        Configure Jira integration
      a-sdlc connect confluence  Configure Confluence integration
      a-sdlc connect github      Configure GitHub integration (PR feedback)
    """
    pass


@connect.command("linear")
@click.option(
    "--api-key",
    prompt="Linear API Key (from Settings > API)",
    hide_input=True,
    help="Linear API key",
)
@click.option("--team-id", prompt="Team ID (e.g., ENG, PROD)", help="Team identifier (e.g., 'ENG')")
@click.option("--default-project", default=None, help="Optional default project name")
def connect_linear(api_key: str, team_id: str, default_project: str | None) -> None:
    """Configure Linear integration for the current project.

    Linear API key can be generated from Settings > API in Linear.

    Examples:

        a-sdlc connect linear --api-key <key> --team-id ENG
        a-sdlc connect linear  # Interactive prompts
    """
    from a_sdlc.storage import init_storage

    storage = init_storage()
    cwd = str(Path.cwd())
    project = storage.get_project_by_path(cwd)

    if not project:
        console.print("[yellow]No project found for current directory.[/yellow]")
        console.print("Run [cyan]/sdlc:init[/cyan] in Claude Code first.")
        sys.exit(1)

    config = {
        "api_key": api_key,
        "team_id": team_id,
        "default_project": default_project,
    }

    storage.set_external_config(project["id"], "linear", config)

    console.print(f"[green]✓ Linear integration configured for {project['name']}[/green]")
    console.print(f"[dim]Team: {team_id}[/dim]")
    console.print()
    console.print("Next steps:")
    console.print("  - Import a cycle: [cyan]/sdlc:sprint-import linear[/cyan]")
    console.print(
        "  - Or link a sprint: [cyan]/sdlc:sprint-link SPRINT-01 linear <cycle-id>[/cyan]"
    )


@connect.command("jira")
@click.option(
    "--url",
    prompt="Atlassian Site URL (e.g., https://company.atlassian.net)",
    help="e.g., https://company.atlassian.net",
)
@click.option(
    "--email",
    prompt="Atlassian Email (e.g., user@company.com)",
    help="Your Atlassian account email",
)
@click.option(
    "--api-token",
    prompt="API Token (from id.atlassian.com/manage-profile/security/api-tokens)",
    hide_input=True,
    help="Atlassian API token",
)
@click.option(
    "--project-key",
    prompt="Jira Project Key (e.g., PROJ, ENG)",
    help="Jira project key (e.g., 'PROJ')",
)
@click.option("--issue-type", default="Task", help="Default issue type")
def connect_jira(url: str, email: str, api_token: str, project_key: str, issue_type: str) -> None:
    """Configure Jira integration for the current project.

    API token can be generated from https://id.atlassian.com/manage-profile/security/api-tokens

    Examples:

        a-sdlc connect jira --url https://company.atlassian.net --email user@example.com --project-key PROJ
        a-sdlc connect jira  # Interactive prompts
    """
    from a_sdlc.storage import init_storage

    storage = init_storage()
    cwd = str(Path.cwd())
    project = storage.get_project_by_path(cwd)

    if not project:
        console.print("[yellow]No project found for current directory.[/yellow]")
        console.print("Run [cyan]/sdlc:init[/cyan] in Claude Code first.")
        sys.exit(1)

    config = {
        "base_url": url.rstrip("/"),
        "email": email,
        "api_token": api_token,
        "project_key": project_key,
        "issue_type": issue_type,
    }

    storage.set_external_config(project["id"], "jira", config)

    console.print(f"[green]✓ Jira integration configured for {project['name']}[/green]")
    console.print(f"[dim]Project: {project_key} at {url}[/dim]")
    console.print()
    console.print("Next steps:")
    console.print("  - Import a sprint: [cyan]/sdlc:sprint-import jira --board-id <id>[/cyan]")
    console.print("  - Or link a sprint: [cyan]/sdlc:sprint-link SPRINT-01 jira <sprint-id>[/cyan]")


@connect.command("confluence")
@click.option(
    "--url",
    prompt="Atlassian Site URL (e.g., https://company.atlassian.net)",
    help="e.g., https://company.atlassian.net",
)
@click.option(
    "--email",
    prompt="Atlassian Email (e.g., user@company.com)",
    help="Your Atlassian account email",
)
@click.option(
    "--api-token",
    prompt="API Token (from id.atlassian.com/manage-profile/security/api-tokens)",
    hide_input=True,
    help="Atlassian API token",
)
@click.option(
    "--space-key",
    prompt="Confluence Space Key (e.g., PROJ, DOCS, ENG)",
    help="Space key (e.g., 'PROJ')",
)
@click.option("--parent-page-id", default=None, help="Optional parent page ID for SDLC docs")
@click.option("--page-prefix", default="[SDLC]", help="Page title prefix (default: '[SDLC]')")
def connect_confluence(
    url: str,
    email: str,
    api_token: str,
    space_key: str,
    parent_page_id: str | None,
    page_prefix: str,
) -> None:
    """Configure Confluence integration for the current project.

    API token can be generated from https://id.atlassian.com/manage-profile/security/api-tokens

    Examples:

        a-sdlc connect confluence --url https://company.atlassian.net --email user@example.com --space-key PROJ
        a-sdlc connect confluence  # Interactive prompts
    """
    from a_sdlc.storage import init_storage

    storage = init_storage()
    cwd = str(Path.cwd())
    project = storage.get_project_by_path(cwd)

    if not project:
        console.print("[yellow]No project found for current directory.[/yellow]")
        console.print("Run [cyan]/sdlc:init[/cyan] in Claude Code first.")
        sys.exit(1)

    config = {
        "base_url": url.rstrip("/"),
        "email": email,
        "api_token": api_token,
        "space_key": space_key,
        "parent_page_id": parent_page_id,
        "page_title_prefix": page_prefix,
    }

    storage.set_external_config(project["id"], "confluence", config)

    console.print(f"[green]✓ Confluence integration configured for {project['name']}[/green]")
    console.print(f"[dim]Space: {space_key} at {url}[/dim]")
    console.print()
    console.print("Next steps:")
    console.print("  - Push artifacts: [cyan]a-sdlc artifacts push[/cyan]")
    console.print("  - Push PRDs: [cyan]a-sdlc prd push <prd-id>[/cyan]")


@connect.command("github")
@click.option(
    "--token",
    prompt="GitHub Personal Access Token",
    hide_input=True,
    help="GitHub PAT with 'repo' scope",
)
@click.option(
    "--global",
    "-g",
    "save_global",
    is_flag=True,
    help="Save globally (~/.config/a-sdlc/) instead of project-level",
)
def connect_github(token: str, save_global: bool) -> None:
    """Configure GitHub integration for PR feedback retrieval.

    The token is validated before storing. By default, saves to the current project.
    Use --global to save to ~/.config/a-sdlc/config.yaml for cross-project use.

    Examples:

        a-sdlc connect github --token ghp_xxx
        a-sdlc connect github --global
        a-sdlc connect github  # Interactive prompt
    """
    from a_sdlc.server.github import (
        GitHubClient,
        save_global_github_config,
    )

    # Validate token
    try:
        client = GitHubClient(token)
        user = client.validate_token()
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    if save_global:
        save_global_github_config({"token": token})
        console.print(
            f"[green]✓ GitHub integration configured globally (authenticated as @{user['login']})[/green]"
        )
        console.print("[dim]Token saved to ~/.config/a-sdlc/config.yaml[/dim]")
    else:
        from a_sdlc.storage import init_storage

        storage = init_storage()
        cwd = str(Path.cwd())
        project = storage.get_project_by_path(cwd)

        if not project:
            console.print("[yellow]No project found for current directory.[/yellow]")
            console.print(
                "Run [cyan]/sdlc:init[/cyan] first, or use [cyan]--global[/cyan] for cross-project config."
            )
            sys.exit(1)

        storage.set_external_config(project["id"], "github", {"token": token})
        console.print(
            f"[green]✓ GitHub integration configured for {project['name']} (authenticated as @{user['login']})[/green]"
        )

    console.print()
    console.print("Next steps:")
    console.print("  - Get PR feedback: [cyan]/sdlc:pr-feedback[/cyan]")


@main.command("disconnect")
@click.argument("system", type=click.Choice(["linear", "jira", "confluence", "github"]))
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.option(
    "--global",
    "-g",
    "remove_global",
    is_flag=True,
    help="Remove global config (~/.config/a-sdlc/) instead of project-level (github only)",
)
def disconnect(system: str, yes: bool, remove_global: bool) -> None:
    """Remove an external system integration.

    SYSTEM: The integration to remove ('linear', 'jira', 'confluence', or 'github')

    Examples:

        a-sdlc disconnect linear
        a-sdlc disconnect jira -y
        a-sdlc disconnect confluence
        a-sdlc disconnect github
        a-sdlc disconnect github --global
    """
    if remove_global:
        if system != "github":
            console.print("[yellow]--global flag is only supported for github.[/yellow]")
            sys.exit(1)

        from a_sdlc.server.github import delete_global_github_config

        if not yes and not click.confirm("Remove global GitHub configuration?"):
            console.print("Aborted.")
            return

        if delete_global_github_config():
            console.print("[green]✓ Global GitHub integration removed[/green]")
        else:
            console.print("[yellow]No global GitHub configuration found.[/yellow]")
        return

    from a_sdlc.storage import init_storage

    storage = init_storage()
    cwd = str(Path.cwd())
    project = storage.get_project_by_path(cwd)

    if not project:
        console.print("[yellow]No project found for current directory.[/yellow]")
        sys.exit(1)

    # Check if configured
    config = storage.get_external_config(project["id"], system)
    if not config:
        console.print(f"[yellow]{system.title()} integration not configured.[/yellow]")
        return

    if not yes and not click.confirm(
        f"Remove {system.title()} integration from {project['name']}?"
    ):
        console.print("Aborted.")
        return

    storage.delete_external_config(project["id"], system)
    console.print(f"[green]✓ {system.title()} integration removed from {project['name']}[/green]")


@main.command("integrations")
def integrations() -> None:
    """List configured external integrations for the current project.

    Shows all connected external systems (Linear, Jira) with their configuration.

    Examples:

        a-sdlc integrations
    """
    from a_sdlc.storage import init_storage

    storage = init_storage()
    cwd = str(Path.cwd())
    project = storage.get_project_by_path(cwd)

    if not project:
        console.print("[yellow]No project found for current directory.[/yellow]")
        console.print("Run [cyan]/sdlc:init[/cyan] in Claude Code first.")
        return

    configs = storage.list_external_configs(project["id"])

    console.print(f"\n[bold]Integrations for {project['name']}[/bold]\n")

    if not configs:
        console.print("[dim]No integrations configured.[/dim]")
        console.print()
        console.print("Configure integrations:")
        console.print("  - [cyan]a-sdlc connect linear[/cyan]")
        console.print("  - [cyan]a-sdlc connect jira[/cyan]")
        console.print("  - [cyan]a-sdlc connect github[/cyan]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("System", style="cyan")
    table.add_column("Configuration")
    table.add_column("Last Updated", style="dim")

    for config in configs:
        cfg = config.get("config", {})

        # Format config display (mask sensitive data)
        if config["system"] == "linear":
            config_display = f"Team: {cfg.get('team_id', 'N/A')}"
        elif config["system"] == "confluence":
            config_display = f"Space: {cfg.get('space_key', 'N/A')} at {cfg.get('base_url', 'N/A')}"
        elif config["system"] == "github":
            token_val = cfg.get("token", "")
            masked = f"***{token_val[-4:]}" if len(token_val) >= 4 else "***"
            config_display = f"Token: {masked}"
        else:  # jira
            config_display = (
                f"Project: {cfg.get('project_key', 'N/A')} at {cfg.get('base_url', 'N/A')}"
            )

        table.add_row(
            config["system"].title(),
            config_display,
            config.get("updated_at", "N/A")[:16],
        )

    console.print(table)
    console.print()

    # Show global GitHub config if configured
    from a_sdlc.server.github import load_global_github_config

    global_gh = load_global_github_config()
    if global_gh:
        token_val = global_gh.get("token", "")
        masked = f"***{token_val[-4:]}" if len(token_val) >= 4 else "***"
        console.print(
            f"[dim]Global GitHub config: Token: {masked} (~/.config/a-sdlc/config.yaml)[/dim]"
        )
        console.print()

    # Show sync mappings summary
    mappings = storage.list_sync_mappings()
    if mappings:
        sprint_mappings = [m for m in mappings if m["entity_type"] == "sprint"]
        task_mappings = [m for m in mappings if m["entity_type"] == "task"]
        console.print(
            f"[dim]Linked: {len(sprint_mappings)} sprint(s), {len(task_mappings)} task(s)[/dim]"
        )


# =============================================================================
# Sync Commands
# =============================================================================


@main.group()
def sync() -> None:
    """Sync sprints with external systems (Jira, Linear).

    Pull sprints from external systems as local sprints with PRDs,
    or push local changes back to the external system.

    \b
    Commands:
      a-sdlc sync jira pull     Pull sprint from Jira
      a-sdlc sync jira push     Push sprint to Jira
      a-sdlc sync jira status   Show sync status
      a-sdlc sync linear pull   Pull cycle from Linear
      a-sdlc sync linear push   Push sprint to Linear
      a-sdlc sync linear status Show sync status
    """
    pass


# -----------------------------------------------------------------------------
# Jira Sync Commands
# -----------------------------------------------------------------------------


@sync.group()
def jira() -> None:
    """Sync with Jira.

    \b
    Examples:
      a-sdlc sync jira pull --board 123 --active
      a-sdlc sync jira push SPRINT-01
      a-sdlc sync jira status
    """
    pass


@jira.command("pull")
@click.option("--active", is_flag=True, help="Pull active sprint (default if no --sprint)")
@click.option("--sprint", "sprint_id", help="Specific Jira sprint ID")
@click.option("--board", "board_id", help="Jira board ID")
@click.option("--dry-run", is_flag=True, help="Preview what would be imported")
def jira_pull(active: bool, sprint_id: str | None, board_id: str | None, dry_run: bool) -> None:
    """Pull sprint from Jira as local sprint with PRDs.

    Jira issues are imported as PRDs. Subtasks are appended to PRD content
    as markdown checklists.

    Default behavior: Pulls the active sprint if --board is provided.
    If --sprint is specified, pulls that specific sprint (ignores --active).

    \b
    Examples:
      a-sdlc sync jira pull --board 123                # List available sprints
      a-sdlc sync jira pull --board 123 --active       # Pull active sprint
      a-sdlc sync jira pull --sprint 456               # Pull specific sprint
      a-sdlc sync jira pull --sprint 456 --dry-run     # Preview import
    """
    from a_sdlc.server.sync import ExternalSyncService, JiraClient
    from a_sdlc.storage import init_storage

    storage = init_storage()
    cwd = str(Path.cwd())
    project = storage.get_project_by_path(cwd)

    if not project:
        console.print("[yellow]No project found for current directory.[/yellow]")
        console.print("Run [cyan]/sdlc:init[/cyan] in Claude Code first.")
        sys.exit(1)

    config = storage.get_external_config(project["id"], "jira")
    if not config:
        console.print("[red]Jira not configured.[/red]")
        console.print("Run [cyan]a-sdlc connect jira[/cyan] first.")
        sys.exit(1)

    cfg = config["config"]
    client = JiraClient(cfg["base_url"], cfg["email"], cfg["api_token"], cfg["project_key"])
    sync_service = ExternalSyncService(storage.db, storage.content_mgr)

    # If sprint_id is provided, import specific sprint
    if sprint_id:
        if dry_run:
            console.print(f"[cyan]Dry run:[/cyan] Would import Jira sprint {sprint_id}")
            jira_sprint = client.get_sprint(sprint_id)
            if jira_sprint:
                console.print(f"  Sprint: {jira_sprint.get('name', 'Unknown')}")
                issues = client.get_sprint_issues(sprint_id)
                console.print(f"  Issues: {len(issues)}")
            else:
                console.print("[red]Sprint not found.[/red]")
            return

        try:
            result = sync_service.import_jira_sprint(project["id"], sprint_id, board_id)
            console.print(f"[green]✓ Imported sprint as {result['sprint']['id']}[/green]")
            console.print(f"  Title: {result['sprint']['title']}")
            console.print(f"  PRDs imported: {result['prds_count']}")
        except Exception as e:
            console.print(f"[red]Failed to import sprint: {e}[/red]")
            sys.exit(1)
        return

    # If active flag with board_id, import active sprint
    if active and board_id:
        if dry_run:
            console.print(f"[cyan]Dry run:[/cyan] Would import active sprint from board {board_id}")
            active_sprint = client.get_active_sprint(board_id)
            if active_sprint:
                console.print(
                    f"  Sprint: {active_sprint.get('name', 'Unknown')} (ID: {active_sprint['id']})"
                )
                issues = client.get_sprint_issues(str(active_sprint["id"]))
                console.print(f"  Issues: {len(issues)}")
            else:
                console.print("[yellow]No active sprint found.[/yellow]")
            return

        try:
            result = sync_service.import_jira_active_sprint(project["id"], board_id)
            console.print(f"[green]✓ Imported active sprint as {result['sprint']['id']}[/green]")
            console.print(f"  Title: {result['sprint']['title']}")
            console.print(f"  PRDs imported: {result['prds_count']}")
        except Exception as e:
            console.print(f"[red]Failed to import active sprint: {e}[/red]")
            sys.exit(1)
        return

    # Otherwise, list available sprints
    if not board_id:
        console.print(
            "[yellow]Provide --board to list sprints, or --sprint to import directly.[/yellow]"
        )
        console.print()
        console.print("Examples:")
        console.print(
            "  [cyan]a-sdlc sync jira pull --board 123[/cyan]              # List sprints"
        )
        console.print("  [cyan]a-sdlc sync jira pull --board 123 --active[/cyan]     # Pull active")
        console.print(
            "  [cyan]a-sdlc sync jira pull --sprint 456[/cyan]             # Pull specific"
        )
        return

    # List sprints from board
    try:
        sprints = client.list_sprints(board_id)

        if not sprints:
            console.print(f"[yellow]No sprints found for board {board_id}.[/yellow]")
            return

        table = Table(title=f"Sprints for Board {board_id}")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("State")
        table.add_column("Goal", style="dim", max_width=40)

        for sprint in sprints:
            state = sprint.get("state", "")
            state_style = "green" if state == "active" else "dim"
            table.add_row(
                str(sprint["id"]),
                sprint.get("name", ""),
                f"[{state_style}]{state}[/{state_style}]",
                (sprint.get("goal", "") or "")[:40],
            )

        console.print(table)
        console.print()
        console.print("To import:")
        console.print(
            f"  [cyan]a-sdlc sync jira pull --board {board_id} --active[/cyan]  # Active sprint"
        )
        console.print(
            "  [cyan]a-sdlc sync jira pull --sprint <ID>[/cyan]               # Specific sprint"
        )

    except Exception as e:
        console.print(f"[red]Failed to list sprints: {e}[/red]")
        sys.exit(1)


@jira.command("push")
@click.argument("sprint_id")
@click.option("--dry-run", is_flag=True, help="Preview what would be pushed")
@click.option("--force", "-f", is_flag=True, help="Overwrite remote changes")
def jira_push(sprint_id: str, dry_run: bool, force: bool) -> None:
    """Push local sprint to linked Jira sprint.

    Updates Jira issues with changes from local PRDs.

    \b
    Examples:
      a-sdlc sync jira push SPRINT-01
      a-sdlc sync jira push SPRINT-01 --dry-run
    """
    from a_sdlc.server.sync import ExternalSyncService
    from a_sdlc.storage import init_storage

    storage = init_storage()
    cwd = str(Path.cwd())
    project = storage.get_project_by_path(cwd)

    if not project:
        console.print("[yellow]No project found for current directory.[/yellow]")
        sys.exit(1)

    config = storage.get_external_config(project["id"], "jira")
    if not config:
        console.print("[red]Jira not configured.[/red]")
        console.print("Run [cyan]a-sdlc connect jira[/cyan] first.")
        sys.exit(1)

    # Check sprint is linked
    mapping = storage.get_sync_mapping("sprint", sprint_id, "jira")
    if not mapping:
        console.print(f"[red]Sprint {sprint_id} is not linked to Jira.[/red]")
        console.print("Use [cyan]a-sdlc sync jira pull[/cyan] to import from Jira first.")
        sys.exit(1)

    if dry_run:
        prds = storage.get_sprint_prds(sprint_id)
        console.print(
            f"[cyan]Dry run:[/cyan] Would push {len(prds)} PRD(s) to Jira sprint {mapping['external_id']}"
        )
        for prd in prds:
            prd_mapping = storage.get_sync_mapping("prd", prd["id"], "jira")
            action = "Update" if prd_mapping else "Create"
            console.print(f"  {action}: {prd['title']}")
        return

    try:
        sync_service = ExternalSyncService(storage.db, storage.content_mgr)
        result = sync_service.sync_sprint_to_jira(project["id"], sprint_id)

        console.print(f"[green]✓ Pushed to Jira sprint {result['jira_sprint_id']}[/green]")
        console.print(f"  Updated: {result['prds_updated']}")
        console.print(f"  Created: {result['prds_created']}")

        if result.get("errors"):
            console.print("[yellow]Errors:[/yellow]")
            for err in result["errors"]:
                console.print(f"  - {err}")

    except Exception as e:
        console.print(f"[red]Failed to push: {e}[/red]")
        sys.exit(1)


@jira.command("status")
@click.argument("sprint_id", required=False)
def jira_status(sprint_id: str | None) -> None:
    """Show Jira sync status for sprints.

    \b
    Examples:
      a-sdlc sync jira status              # All linked sprints
      a-sdlc sync jira status SPRINT-01    # Specific sprint
    """
    from a_sdlc.storage import init_storage

    storage = init_storage()
    cwd = str(Path.cwd())
    project = storage.get_project_by_path(cwd)

    if not project:
        console.print("[yellow]No project found for current directory.[/yellow]")
        return

    config = storage.get_external_config(project["id"], "jira")
    if not config:
        console.print("[dim]Jira not configured.[/dim]")
        return

    if sprint_id:
        # Show specific sprint status
        mapping = storage.get_sync_mapping("sprint", sprint_id, "jira")
        if not mapping:
            console.print(f"[yellow]Sprint {sprint_id} is not linked to Jira.[/yellow]")
            return

        sprint = storage.get_sprint(sprint_id)
        assert sprint is not None  # Sprint must exist if sync mapping exists
        prds = storage.get_sprint_prds(sprint_id)

        console.print(f"\n[bold]Sprint: {sprint['title']}[/bold]")
        console.print(f"Local ID: {sprint_id}")
        console.print(f"Jira Sprint ID: {mapping['external_id']}")
        console.print(f"Sync Status: {mapping.get('sync_status', 'unknown')}")
        console.print(f"Last Synced: {mapping.get('last_synced', 'Never')}")
        console.print(f"PRDs: {len(prds)}")

        # Show PRD sync status
        if prds:
            console.print("\nPRD Sync Status:")
            for prd in prds:
                prd_mapping = storage.get_sync_mapping("prd", prd["id"], "jira")
                if prd_mapping:
                    console.print(
                        f"  [green]✓[/green] {prd['title']} → {prd_mapping['external_id']}"
                    )
                else:
                    console.print(f"  [dim]-[/dim] {prd['title']} (not linked)")
    else:
        # Show all linked sprints
        mappings = storage.list_sync_mappings("sprint", "jira")

        if not mappings:
            console.print("[dim]No sprints linked to Jira.[/dim]")
            console.print()
            console.print("To link a sprint:")
            console.print("  [cyan]a-sdlc sync jira pull --board <id> --active[/cyan]")
            return

        table = Table(title="Jira-Linked Sprints")
        table.add_column("Local Sprint", style="cyan")
        table.add_column("Jira Sprint ID")
        table.add_column("Status")
        table.add_column("Last Synced", style="dim")

        for m in mappings:
            sprint = storage.get_sprint(m["local_id"])
            if sprint:
                table.add_row(
                    f"{m['local_id']} ({sprint['title']})",
                    m["external_id"],
                    m.get("sync_status", "unknown"),
                    (m.get("last_synced") or "Never")[:16],
                )

        console.print(table)


# -----------------------------------------------------------------------------
# Linear Sync Commands
# -----------------------------------------------------------------------------


@sync.group()
def linear() -> None:
    """Sync with Linear.

    \b
    Examples:
      a-sdlc sync linear pull --active
      a-sdlc sync linear push SPRINT-01
      a-sdlc sync linear status
    """
    pass


@linear.command("pull")
@click.option("--active", is_flag=True, help="Pull active cycle (default)")
@click.option("--cycle", "cycle_id", help="Specific Linear cycle ID")
@click.option("--team", "team_id", help="Team ID (uses configured default if not specified)")
@click.option("--dry-run", is_flag=True, help="Preview what would be imported")
def linear_pull(active: bool, cycle_id: str | None, team_id: str | None, dry_run: bool) -> None:
    """Pull cycle from Linear as local sprint with PRDs.

    Linear issues are imported as PRDs. Sub-issues are appended to PRD content
    as markdown checklists.

    Default behavior: Pulls the active cycle.
    If --cycle is specified, pulls that specific cycle.

    \b
    Examples:
      a-sdlc sync linear pull                          # List available cycles
      a-sdlc sync linear pull --active                 # Pull active cycle
      a-sdlc sync linear pull --cycle <id>             # Pull specific cycle
      a-sdlc sync linear pull --cycle <id> --dry-run   # Preview import
    """
    from a_sdlc.server.sync import ExternalSyncService, LinearClient
    from a_sdlc.storage import init_storage

    storage = init_storage()
    cwd = str(Path.cwd())
    project = storage.get_project_by_path(cwd)

    if not project:
        console.print("[yellow]No project found for current directory.[/yellow]")
        console.print("Run [cyan]/sdlc:init[/cyan] in Claude Code first.")
        sys.exit(1)

    config = storage.get_external_config(project["id"], "linear")
    if not config:
        console.print("[red]Linear not configured.[/red]")
        console.print("Run [cyan]a-sdlc connect linear[/cyan] first.")
        sys.exit(1)

    cfg = config["config"]
    effective_team_id = team_id or cfg["team_id"]
    client = LinearClient(cfg["api_key"], effective_team_id)
    sync_service = ExternalSyncService(storage.db, storage.content_mgr)

    # If cycle_id is provided, import specific cycle
    if cycle_id:
        if dry_run:
            console.print(f"[cyan]Dry run:[/cyan] Would import Linear cycle {cycle_id}")
            cycle = client.get_cycle(cycle_id)
            if cycle:
                console.print(f"  Cycle: {cycle.get('name', 'Unknown')}")
                issues = cycle.get("issues", {}).get("nodes", [])
                console.print(f"  Issues: {len(issues)}")
            else:
                console.print("[red]Cycle not found.[/red]")
            return

        try:
            result = sync_service.import_linear_cycle(project["id"], cycle_id)
            console.print(f"[green]✓ Imported cycle as {result['sprint']['id']}[/green]")
            console.print(f"  Title: {result['sprint']['title']}")
            console.print(f"  PRDs imported: {result['prds_count']}")
        except Exception as e:
            console.print(f"[red]Failed to import cycle: {e}[/red]")
            sys.exit(1)
        return

    # If active flag, import active cycle
    if active:
        if dry_run:
            console.print("[cyan]Dry run:[/cyan] Would import active cycle")
            active_cycle = client.get_active_cycle()
            if active_cycle:
                console.print(
                    f"  Cycle: {active_cycle.get('name', 'Unknown')} (ID: {active_cycle['id']})"
                )
                issues = active_cycle.get("issues", {}).get("nodes", [])
                console.print(f"  Issues: {len(issues)}")
            else:
                console.print("[yellow]No active cycle found.[/yellow]")
            return

        try:
            result = sync_service.import_linear_active_cycle(project["id"])
            console.print(f"[green]✓ Imported active cycle as {result['sprint']['id']}[/green]")
            console.print(f"  Title: {result['sprint']['title']}")
            console.print(f"  PRDs imported: {result['prds_count']}")
        except Exception as e:
            console.print(f"[red]Failed to import active cycle: {e}[/red]")
            sys.exit(1)
        return

    # Otherwise, list available cycles
    try:
        cycles = client.list_cycles()

        if not cycles:
            console.print("[yellow]No cycles found.[/yellow]")
            return

        table = Table(title="Linear Cycles")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Progress")
        table.add_column("Issues")

        for cycle in cycles:
            progress = cycle.get("progress", 0)
            issues_count = len(cycle.get("issues", {}).get("nodes", []))
            table.add_row(
                cycle["id"][:12] + "...",
                cycle.get("name", f"Cycle {cycle.get('number', '')}"),
                f"{progress:.0%}",
                str(issues_count),
            )

        console.print(table)
        console.print()
        console.print("To import:")
        console.print("  [cyan]a-sdlc sync linear pull --active[/cyan]       # Active cycle")
        console.print("  [cyan]a-sdlc sync linear pull --cycle <ID>[/cyan]   # Specific cycle")

    except Exception as e:
        console.print(f"[red]Failed to list cycles: {e}[/red]")
        sys.exit(1)


@linear.command("push")
@click.argument("sprint_id")
@click.option("--dry-run", is_flag=True, help="Preview what would be pushed")
@click.option("--force", "-f", is_flag=True, help="Overwrite remote changes")
def linear_push(sprint_id: str, dry_run: bool, force: bool) -> None:
    """Push local sprint to linked Linear cycle.

    Updates Linear issues with changes from local PRDs.

    \b
    Examples:
      a-sdlc sync linear push SPRINT-01
      a-sdlc sync linear push SPRINT-01 --dry-run
    """
    from a_sdlc.server.sync import ExternalSyncService
    from a_sdlc.storage import init_storage

    storage = init_storage()
    cwd = str(Path.cwd())
    project = storage.get_project_by_path(cwd)

    if not project:
        console.print("[yellow]No project found for current directory.[/yellow]")
        sys.exit(1)

    config = storage.get_external_config(project["id"], "linear")
    if not config:
        console.print("[red]Linear not configured.[/red]")
        console.print("Run [cyan]a-sdlc connect linear[/cyan] first.")
        sys.exit(1)

    # Check sprint is linked
    mapping = storage.get_sync_mapping("sprint", sprint_id, "linear")
    if not mapping:
        console.print(f"[red]Sprint {sprint_id} is not linked to Linear.[/red]")
        console.print("Use [cyan]a-sdlc sync linear pull[/cyan] to import from Linear first.")
        sys.exit(1)

    if dry_run:
        prds = storage.get_sprint_prds(sprint_id)
        console.print(
            f"[cyan]Dry run:[/cyan] Would push {len(prds)} PRD(s) to Linear cycle {mapping['external_id'][:12]}..."
        )
        for prd in prds:
            prd_mapping = storage.get_sync_mapping("prd", prd["id"], "linear")
            action = "Update" if prd_mapping else "Create"
            console.print(f"  {action}: {prd['title']}")
        return

    try:
        sync_service = ExternalSyncService(storage.db, storage.content_mgr)
        result = sync_service.sync_sprint_to_linear(project["id"], sprint_id)

        console.print(f"[green]✓ Pushed to Linear cycle {result['cycle_id'][:12]}...[/green]")
        console.print(f"  Updated: {result['prds_updated']}")
        console.print(f"  Created: {result['prds_created']}")

        if result.get("errors"):
            console.print("[yellow]Errors:[/yellow]")
            for err in result["errors"]:
                console.print(f"  - {err}")

    except Exception as e:
        console.print(f"[red]Failed to push: {e}[/red]")
        sys.exit(1)


@linear.command("status")
@click.argument("sprint_id", required=False)
def linear_status(sprint_id: str | None) -> None:
    """Show Linear sync status for sprints.

    \b
    Examples:
      a-sdlc sync linear status              # All linked sprints
      a-sdlc sync linear status SPRINT-01    # Specific sprint
    """
    from a_sdlc.storage import init_storage

    storage = init_storage()
    cwd = str(Path.cwd())
    project = storage.get_project_by_path(cwd)

    if not project:
        console.print("[yellow]No project found for current directory.[/yellow]")
        return

    config = storage.get_external_config(project["id"], "linear")
    if not config:
        console.print("[dim]Linear not configured.[/dim]")
        return

    if sprint_id:
        # Show specific sprint status
        mapping = storage.get_sync_mapping("sprint", sprint_id, "linear")
        if not mapping:
            console.print(f"[yellow]Sprint {sprint_id} is not linked to Linear.[/yellow]")
            return

        sprint = storage.get_sprint(sprint_id)
        assert sprint is not None  # Sprint must exist if sync mapping exists
        prds = storage.get_sprint_prds(sprint_id)

        console.print(f"\n[bold]Sprint: {sprint['title']}[/bold]")
        console.print(f"Local ID: {sprint_id}")
        console.print(f"Linear Cycle ID: {mapping['external_id'][:12]}...")
        console.print(f"Sync Status: {mapping.get('sync_status', 'unknown')}")
        console.print(f"Last Synced: {mapping.get('last_synced', 'Never')}")
        console.print(f"PRDs: {len(prds)}")

        # Show PRD sync status
        if prds:
            console.print("\nPRD Sync Status:")
            for prd in prds:
                prd_mapping = storage.get_sync_mapping("prd", prd["id"], "linear")
                if prd_mapping:
                    console.print(
                        f"  [green]✓[/green] {prd['title']} → {prd_mapping['external_id'][:12]}..."
                    )
                else:
                    console.print(f"  [dim]-[/dim] {prd['title']} (not linked)")
    else:
        # Show all linked sprints
        mappings = storage.list_sync_mappings("sprint", "linear")

        if not mappings:
            console.print("[dim]No sprints linked to Linear.[/dim]")
            console.print()
            console.print("To link a sprint:")
            console.print("  [cyan]a-sdlc sync linear pull --active[/cyan]")
            return

        table = Table(title="Linear-Linked Sprints")
        table.add_column("Local Sprint", style="cyan")
        table.add_column("Linear Cycle ID")
        table.add_column("Status")
        table.add_column("Last Synced", style="dim")

        for m in mappings:
            sprint = storage.get_sprint(m["local_id"])
            if sprint:
                table.add_row(
                    f"{m['local_id']} ({sprint['title']})",
                    m["external_id"][:12] + "...",
                    m.get("sync_status", "unknown"),
                    (m.get("last_synced") or "Never")[:16],
                )

        console.print(table)


@main.command("init")
@click.option("--name", "-n", default=None, help="Project name (defaults to folder name)")
def init_project_cmd(name: str | None) -> None:
    """Initialize a project for SDLC tracking.

    Creates a project entry in the local database for the current directory.
    This is required before using other SDLC commands.

    Examples:

        a-sdlc init                    # Use folder name
        a-sdlc init --name "My Project"  # Custom name
    """
    from a_sdlc.storage import init_storage

    storage = init_storage()
    cwd = str(Path.cwd())

    # Check if already exists
    existing = storage.get_project_by_path(cwd)
    if existing:
        console.print(f"[yellow]Project already initialized: {existing['name']}[/yellow]")
        console.print(f"[dim]ID: {existing['id']}[/dim]")
        return

    # Generate project ID from folder name
    folder_name = Path(cwd).name
    project_id = folder_name.lower().replace(" ", "-").replace("_", "-")
    project_name = name or folder_name

    project = storage.create_project(project_id, project_name, cwd)

    # Generate CLAUDE.md, lesson-learn.md, and global lesson-learn.md
    from a_sdlc.core.init_files import generate_init_files

    init_results = generate_init_files(Path(cwd), project_name)
    init_files_status = []
    for result in init_results["results"]:
        status_icon = (
            "[green]created[/green]" if result["status"] == "created" else "[yellow]exists[/yellow]"
        )
        init_files_status.append(f"  {status_icon}: {result['path']}")
    init_files_display = "\n".join(init_files_status)

    console.print(
        Panel(
            f"[green]Project '{project_name}' initialized![/green]\n\n"
            f"ID: {project['id']}\n"
            f"Path: {project['path']}\n\n"
            f"Generated files:\n{init_files_display}\n\n"
            "Next steps:\n"
            "  [cyan]/sdlc:scan[/cyan]     - Generate documentation artifacts\n"
            "  [cyan]/sdlc:prd[/cyan]      - Create a PRD\n"
            "  [cyan]/sdlc:task[/cyan]     - Create tasks",
            title="[bold]a-sdlc Initialized[/bold]",
            border_style="green",
        )
    )


@main.command("projects")
def project_list() -> None:
    """List all registered projects."""
    from a_sdlc.storage import init_storage

    db = init_storage().db
    projects = db.get_all_projects_with_stats()
    if not projects:
        console.print("[yellow]No projects found.[/yellow]")
        return

    table = Table(title="Projects")
    table.add_column("Shortname", style="cyan")
    table.add_column("Name")
    table.add_column("Path", style="dim")
    table.add_column("PRDs", justify="right")
    table.add_column("Tasks", justify="right")
    table.add_column("Sprints", justify="right")
    table.add_column("Active Sprint")

    for p in projects:
        table.add_row(
            p["shortname"],
            p["name"],
            p.get("path", ""),
            str(p.get("total_prds", 0)),
            str(p.get("total_tasks", 0)),
            str(p.get("total_sprints", 0)),
            p.get("active_sprint_title") or "-",
        )
    console.print(table)


@main.group()
def quality() -> None:
    """Quality tracking and verification commands.

    \b
      a-sdlc quality coverage [PRD_ID]           Show requirement coverage
      a-sdlc quality verify [PRD_ID]             Show AC verification status
      a-sdlc quality gaps [SPRINT_ID]            Full gap analysis (PASS/FAIL)
      a-sdlc quality reclassify REQ_ID           Update requirement depth
      a-sdlc quality skip-challenge CHALLENGE_ID  Skip a challenge round
      a-sdlc quality resolve-escalation OBJ_ID   Resolve escalated objection
      a-sdlc quality waive REQ_ID                Waive a requirement
    """
    pass


@quality.command("coverage")
@click.argument("prd_id", required=False)
def quality_coverage(prd_id: str | None) -> None:
    """Show requirement coverage for a PRD or all PRDs."""
    from a_sdlc.storage import HybridStorage

    storage = HybridStorage()
    project = storage.get_most_recent_project()
    if not project:
        console.print("[red]No project found.[/red]")
        return

    # Determine which PRDs to report on
    if prd_id:
        prd_ids = [prd_id]
    else:
        prds = storage.list_prds(project["id"])
        prd_ids = [p["id"] for p in prds]

    if not prd_ids:
        console.print("[yellow]No PRDs found.[/yellow]")
        return

    table = Table(title="Requirement Coverage")
    table.add_column("PRD", style="cyan")
    table.add_column("Total", justify="right")
    table.add_column("Linked", justify="right")
    table.add_column("Orphaned", justify="right")
    table.add_column("Coverage %", justify="right")

    for pid in prd_ids:
        try:
            stats = storage.get_coverage_stats(pid)
            total = stats["total"]
            linked = stats["linked"]
            orphaned = stats.get("orphaned", total - linked)
            pct = round((linked / total) * 100, 1) if total > 0 else 100.0
            style = "green" if pct >= 100 else "yellow" if pct >= 80 else "red"
            table.add_row(
                pid,
                str(total),
                str(linked),
                str(orphaned),
                f"[{style}]{pct}%[/{style}]",
            )
        except Exception as exc:
            table.add_row(pid, "-", "-", "-", f"[red]Error: {exc}[/red]")

    console.print(table)


@quality.command("verify")
@click.argument("prd_id", required=False)
def quality_verify(prd_id: str | None) -> None:
    """Show acceptance criteria verification status."""
    from a_sdlc.storage import HybridStorage

    storage = HybridStorage()
    project = storage.get_most_recent_project()
    if not project:
        console.print("[red]No project found.[/red]")
        return

    if prd_id:
        prd_ids = [prd_id]
    else:
        prds = storage.list_prds(project["id"])
        prd_ids = [p["id"] for p in prds]

    if not prd_ids:
        console.print("[yellow]No PRDs found.[/yellow]")
        return

    table = Table(title="AC Verification Status")
    table.add_column("Req ID", style="cyan")
    table.add_column("Summary")
    table.add_column("Depth")
    table.add_column("Verified", justify="center")

    total_acs = 0
    verified_count = 0

    for pid in prd_ids:
        try:
            ac_reqs = storage.get_requirements(pid, req_type="AC")
            for req in ac_reqs:
                total_acs += 1
                tasks = storage.get_requirement_tasks(req["id"])
                verified = False
                for t in tasks:
                    verifications = storage.get_ac_verifications(t["id"])
                    for v in verifications:
                        if v.get("requirement_id") == req["id"]:
                            verified = True
                            break
                    if verified:
                        break
                if verified:
                    verified_count += 1
                status_str = "[green]Yes[/green]" if verified else "[red]No[/red]"
                table.add_row(
                    req["id"],
                    req.get("summary", ""),
                    req.get("depth", "structural"),
                    status_str,
                )
        except Exception as exc:
            console.print(f"[red]Error reading PRD {pid}: {exc}[/red]")

    console.print(table)
    pct = round((verified_count / total_acs) * 100, 1) if total_acs > 0 else 100.0
    console.print(f"\nVerified: {verified_count}/{total_acs} ({pct}%)")


@quality.command("gaps")
@click.argument("sprint_id", required=False)
def quality_gaps(sprint_id: str | None) -> None:
    """Run full gap analysis for a sprint. Shows PASS/FAIL verdict."""
    from a_sdlc.storage import HybridStorage

    storage = HybridStorage()
    project = storage.get_most_recent_project()
    if not project:
        console.print("[red]No project found.[/red]")
        return

    if not sprint_id:
        # Find active sprint
        sprints = storage.list_sprints(project["id"])
        active = [s for s in sprints if s.get("status") == "active"]
        if active:
            sprint_id = active[0]["id"]
        elif sprints:
            sprint_id = sprints[-1]["id"]
        else:
            console.print("[yellow]No sprints found.[/yellow]")
            return

    prds = storage.get_sprint_prds(sprint_id)
    if not prds:
        console.print(f"[yellow]No PRDs in sprint {sprint_id}.[/yellow]")
        return

    # Aggregate stats
    total_reqs = 0
    linked_reqs = 0
    orphaned_list: list[dict] = []
    unverified_list: list[dict] = []
    total_acs = 0
    verified_acs = 0

    for prd in prds:
        pid = prd["id"]
        try:
            stats = storage.get_coverage_stats(pid)
            total_reqs += stats["total"]
            linked_reqs += stats["linked"]

            orphaned = storage.get_orphaned_requirements(pid)
            for r in orphaned:
                orphaned_list.append({"prd_id": pid, **r})

            ac_reqs = storage.get_requirements(pid, req_type="AC")
            for req in ac_reqs:
                total_acs += 1
                tasks = storage.get_requirement_tasks(req["id"])
                verified = False
                for t in tasks:
                    verifications = storage.get_ac_verifications(t["id"])
                    for v in verifications:
                        if v.get("requirement_id") == req["id"]:
                            verified = True
                            break
                    if verified:
                        break
                if verified:
                    verified_acs += 1
                else:
                    unverified_list.append({"prd_id": pid, **req})
        except Exception as exc:
            console.print(f"[red]Error analysing PRD {pid}: {exc}[/red]")

    coverage_pct = round((linked_reqs / total_reqs) * 100, 1) if total_reqs > 0 else 100.0
    verification_pct = round((verified_acs / total_acs) * 100, 1) if total_acs > 0 else 100.0
    quality_pass = coverage_pct >= 100.0 and verification_pct >= 100.0

    verdict = "[green]PASS[/green]" if quality_pass else "[red]FAIL[/red]"
    console.print(Panel(f"Sprint {sprint_id} Quality: {verdict}", expand=False))

    console.print(f"\nCoverage: {linked_reqs}/{total_reqs} ({coverage_pct}%)")
    console.print(f"Verification: {verified_acs}/{total_acs} ({verification_pct}%)")

    if orphaned_list:
        console.print("\n[bold]Orphaned Requirements:[/bold]")
        for r in orphaned_list:
            console.print(
                f"  - {r.get('req_number', r.get('id', '?'))}: "
                f"{r.get('summary', '')} (PRD: {r['prd_id']})"
            )

    if unverified_list:
        console.print("\n[bold]Unverified ACs:[/bold]")
        for r in unverified_list:
            console.print(
                f"  - {r.get('req_number', r.get('id', '?'))}: "
                f"{r.get('summary', '')} (PRD: {r['prd_id']})"
            )


@quality.command("reclassify")
@click.argument("req_id")
@click.option(
    "--depth",
    type=click.Choice(["structural", "behavioral", "negative"]),
    required=True,
    help="New depth classification",
)
def quality_reclassify(req_id: str, depth: str) -> None:
    """Update the depth classification of a requirement."""
    from a_sdlc.storage import HybridStorage

    storage = HybridStorage()
    req = storage.get_requirement(req_id)
    if not req:
        console.print(f"[red]Requirement not found: {req_id}[/red]")
        return

    old_depth = req.get("depth", "structural")
    storage.upsert_requirement(
        id=req["id"],
        prd_id=req["prd_id"],
        req_type=req["req_type"],
        req_number=req["req_number"],
        summary=req.get("summary", ""),
        depth=depth,
    )
    console.print(f"[green]Reclassified {req_id}: {old_depth} -> {depth}[/green]")


@quality.command("skip-challenge")
@click.argument("challenge_id")
@click.option("--reason", required=True, help="Reason for skipping the challenge")
def quality_skip_challenge(challenge_id: str, reason: str) -> None:
    """Skip a challenge round and record in audit log."""
    from a_sdlc.storage import HybridStorage

    storage = HybridStorage()
    project = storage.get_most_recent_project()
    if not project:
        console.print("[red]No project found.[/red]")
        return

    # Parse challenge_id as "artifact_type:artifact_id:round_number"
    parts = challenge_id.split(":")
    if len(parts) != 3:
        console.print(
            "[red]Invalid challenge ID format. "
            "Expected: artifact_type:artifact_id:round_number[/red]"
        )
        return

    artifact_type, artifact_id, round_str = parts
    try:
        round_number = int(round_str)
    except ValueError:
        console.print(f"[red]Invalid round number: {round_str}[/red]")
        return

    try:
        result = storage.update_challenge_round(
            artifact_type,
            artifact_id,
            round_number,
            verdict="skipped",
            status="skipped",
        )
        if not result:
            console.print(f"[red]Challenge round not found: {challenge_id}[/red]")
            return
    except Exception as exc:
        console.print(f"[red]Failed to skip challenge: {exc}[/red]")
        return

    storage.append_audit_log(
        project["id"],
        "challenge_skipped",
        "success",
        target_entity=challenge_id,
        details={"reason": reason},
    )
    console.print(f"[green]Challenge {challenge_id} skipped. Reason: {reason}[/green]")


@quality.command("resolve-escalation")
@click.argument("objection_id")
@click.option("--resolution", required=True, help="Resolution text for the escalation")
def quality_resolve_escalation(objection_id: str, resolution: str) -> None:
    """Resolve a user-escalated objection."""
    from a_sdlc.storage import HybridStorage

    storage = HybridStorage()
    project = storage.get_most_recent_project()
    if not project:
        console.print("[red]No project found.[/red]")
        return

    # Parse objection_id as "artifact_type:artifact_id:round_number"
    parts = objection_id.split(":")
    if len(parts) != 3:
        console.print(
            "[red]Invalid objection ID format. "
            "Expected: artifact_type:artifact_id:round_number[/red]"
        )
        return

    artifact_type, artifact_id, round_str = parts
    try:
        round_number = int(round_str)
    except ValueError:
        console.print(f"[red]Invalid round number: {round_str}[/red]")
        return

    try:
        result = storage.update_challenge_round(
            artifact_type,
            artifact_id,
            round_number,
            responses=resolution,
            verdict="resolved",
            status="resolved",
        )
        if not result:
            console.print(f"[red]Challenge round not found: {objection_id}[/red]")
            return
    except Exception as exc:
        console.print(f"[red]Failed to resolve escalation: {exc}[/red]")
        return

    storage.append_audit_log(
        project["id"],
        "escalation_resolved",
        "success",
        target_entity=objection_id,
        details={"resolution": resolution},
    )
    console.print(f"[green]Escalation {objection_id} resolved.[/green]")


@quality.command("waive")
@click.argument("req_id")
@click.option("--reason", required=True, help="Justification for waiving the requirement")
@click.option("--sprint-id", default=None, help="Sprint ID to scope the waiver")
def quality_waive(req_id: str, reason: str, sprint_id: str | None) -> None:
    """Waive a requirement with justification."""
    from a_sdlc.storage import HybridStorage

    storage = HybridStorage()
    project = storage.get_most_recent_project()
    if not project:
        console.print("[red]No project found.[/red]")
        return

    req = storage.get_requirement(req_id)
    if not req:
        console.print(f"[red]Requirement not found: {req_id}[/red]")
        return

    storage.append_audit_log(
        project["id"],
        "requirement_waived",
        "success",
        target_entity=req_id,
        details={
            "reason": reason,
            "sprint_id": sprint_id,
            "req_number": req.get("req_number", ""),
            "summary": req.get("summary", ""),
        },
    )
    console.print(f"[green]Requirement {req_id} waived. Reason: {reason}[/green]")


# =============================================================================
# Server Log Viewer
# =============================================================================

_SERVER_LOG_PATH = Path.home() / ".a-sdlc" / "server.log"

_LOG_LEVEL_COLORS: dict[str, str] = {
    "DEBUG": "blue",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "red",
}

_LOG_LEVEL_PRIORITY: dict[str, int] = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


def _format_log_line(line: str, level_filter: str | None) -> str | None:
    """Parse a JSON log line and return a formatted string, or None to skip.

    Non-JSON lines are returned as-is (dimmed) unless a level filter is active.
    """
    line = line.rstrip()
    if not line:
        return None

    try:
        entry = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        # Non-JSON line (old format) — show as-is unless filtering by level
        if level_filter:
            return None
        return click.style(line, dim=True)

    level = entry.get("level", "INFO").upper()

    # Apply level filter
    if level_filter:
        min_priority = _LOG_LEVEL_PRIORITY.get(level_filter.upper(), 0)
        line_priority = _LOG_LEVEL_PRIORITY.get(level, 0)
        if line_priority < min_priority:
            return None

    ts = entry.get("ts", "")
    # Shorten ISO timestamp for display: keep date + time, drop timezone offset
    if ts and "T" in ts:
        ts = ts.replace("T", " ")
        # Strip trailing +00:00 or Z
        if ts.endswith("+00:00"):
            ts = ts[:-6]
        elif ts.endswith("Z"):
            ts = ts[:-1]

    event = entry.get("event", "")
    color = _LOG_LEVEL_COLORS.get(level, "white")
    level_tag = click.style(f"[{level:<7s}]", fg=color)
    ts_tag = click.style(ts, dim=True)

    parts = [ts_tag, level_tag, event]

    # Append extra structured fields
    tool = entry.get("tool")
    if tool:
        parts.append(click.style(f"tool={tool}", dim=True))
    duration = entry.get("duration_ms")
    if duration is not None:
        parts.append(click.style(f"{duration}ms", dim=True))
    status = entry.get("status")
    if status:
        parts.append(click.style(f"status={status}", dim=True))
    error_msg = entry.get("error_message")
    if error_msg:
        parts.append(click.style(f"err={error_msg}", fg="red"))

    return " ".join(parts)


@main.command("logs")
@click.option("--follow", "-f", is_flag=True, help="Stream new log entries in real-time")
@click.option(
    "--level",
    "-l",
    "level_filter",
    type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
    default=None,
    help="Minimum log level to display",
)
@click.option(
    "--lines",
    "-n",
    "num_lines",
    type=int,
    default=50,
    show_default=True,
    help="Number of recent lines to show",
)
def logs_cmd(follow: bool, level_filter: str | None, num_lines: int) -> None:
    """View server log entries with optional filtering and streaming.

    Reads JSON-formatted log entries from ~/.a-sdlc/server.log and displays
    them with color-coded severity levels.

    Examples:

    \b
        a-sdlc logs                  # Show last 50 entries
        a-sdlc logs -n 100           # Show last 100 entries
        a-sdlc logs --level error    # Show only ERROR and above
        a-sdlc logs --follow         # Stream new entries (Ctrl+C to stop)
        a-sdlc logs -f -l warning    # Stream warnings and errors
    """
    log_file = _SERVER_LOG_PATH

    if not log_file.exists():
        click.echo(
            f"No log file found at {log_file}\n"
            "The server log is created when the MCP server runs.\n"
            "Start the server with: a-sdlc serve"
        )
        return

    # Read and display the last N lines
    try:
        with open(log_file, encoding="utf-8") as f:
            all_lines = f.readlines()
    except OSError as e:
        click.echo(f"Error reading log file: {e}", err=True)
        sys.exit(1)

    if not all_lines:
        click.echo("Log file is empty.")
        return

    tail_lines = all_lines[-num_lines:] if len(all_lines) > num_lines else all_lines
    displayed = 0
    for line in tail_lines:
        formatted = _format_log_line(line, level_filter)
        if formatted is not None:
            click.echo(formatted)
            displayed += 1

    if displayed == 0 and level_filter:
        click.echo(f"No log entries found at level '{level_filter.upper()}' or above.")

    if not follow:
        return

    # Follow mode: poll for new lines
    click.echo(click.style("--- following (Ctrl+C to stop) ---", dim=True))
    import time

    try:
        with open(log_file, encoding="utf-8") as f:
            # Seek to end of file
            f.seek(0, 2)
            while True:
                new_line = f.readline()
                if new_line:
                    formatted = _format_log_line(new_line, level_filter)
                    if formatted is not None:
                        click.echo(formatted)
                else:
                    time.sleep(0.5)
    except KeyboardInterrupt:
        click.echo(click.style("\nStopped.", dim=True))


# =============================================================================
# Database migration commands
# =============================================================================


def _get_alembic_config() -> "AlembicConfig":
    """Build an Alembic Config pointing at the package's alembic directory.

    The alembic.ini lives at the project/package root. We resolve it
    relative to *this* file so it works regardless of the user's cwd.
    The database URL is injected from ``StorageConfig`` so that
    environment variables, project config, and global config are
    respected.
    """
    import alembic.config

    from a_sdlc.core.storage_config import load_storage_config

    # alembic.ini is at the repo root (two levels up from src/a_sdlc/)
    package_dir = Path(__file__).resolve().parent  # src/a_sdlc/
    repo_root = package_dir.parent.parent  # repo root
    ini_path = repo_root / "alembic.ini"

    if not ini_path.exists():
        # Fallback: check if installed as a package (alembic dir might be
        # located relative to site-packages or via importlib)
        import importlib.resources

        try:
            ref = importlib.resources.files("a_sdlc").joinpath("../../alembic.ini")
            ini_path = Path(str(ref))
        except (TypeError, FileNotFoundError):
            pass

    cfg = alembic.config.Config(str(ini_path))

    # Override the script_location to an absolute path so Alembic finds
    # the migrations regardless of the user's cwd.
    script_dir = ini_path.parent / "alembic"
    cfg.set_main_option("script_location", str(script_dir))

    # Inject database URL from StorageConfig
    try:
        storage_config = load_storage_config(validate=False)
        cfg.set_main_option("sqlalchemy.url", storage_config.database_url)
    except Exception:
        pass  # Fall through to alembic.ini default

    return cfg


def _check_server_running() -> bool:
    """Check if the MCP server is running.

    Returns True if a running server was detected via PID file.
    """
    try:
        from a_sdlc.server import _MCP_PID_FILE
    except ImportError:
        return False

    if not _MCP_PID_FILE.exists():
        return False

    try:
        pid = int(_MCP_PID_FILE.read_text().strip())
        import os as _os

        _os.kill(pid, 0)  # Check if process is alive
        return True
    except (ValueError, OSError, ProcessLookupError):
        return False


def _mask_db_url(url: str) -> str:
    """Mask the password in a database URL for display.

    Replaces the password component with ``***`` so URLs can be printed
    safely in logs and terminal output.
    """
    try:
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(url)
        if parsed.password:
            netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@", 1)
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    return url


@main.group()
def db() -> None:
    """Database migration management.

    Manage Alembic database migrations for the a-sdlc storage layer.

    \b
      a-sdlc db status     Show current migration state
      a-sdlc db migrate    Apply pending migrations
      a-sdlc db rollback   Revert migrations
      a-sdlc db import     Import data from legacy SQLite
    """
    pass


@db.command("status")
def db_status() -> None:
    """Show current database migration state.

    Displays the current Alembic revision, the latest available
    revision (head), and the number of pending migrations.

    Examples:

    \b
        a-sdlc db status
    """
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine

    from a_sdlc.core.storage_config import load_storage_config

    try:
        storage_config = load_storage_config(validate=False)
    except Exception as exc:
        console.print(f"[red]Failed to load storage config: {exc}[/red]")
        sys.exit(1)

    db_url = storage_config.database_url
    console.print(f"[dim]Database: {db_url}[/dim]")
    console.print()

    try:
        cfg = _get_alembic_config()
        script = ScriptDirectory.from_config(cfg)
    except Exception as exc:
        console.print(f"[red]Failed to load Alembic configuration: {exc}[/red]")
        sys.exit(1)

    # Get head revision(s)
    heads = script.get_heads()
    head_rev = heads[0] if heads else None

    # Connect and get current revision
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            current_rev = context.get_current_revision()
        engine.dispose()
    except Exception as exc:
        console.print(f"[red]Failed to connect to database: {exc}[/red]")
        sys.exit(1)

    # Count pending migrations
    pending = 0
    if current_rev != head_rev:
        try:
            if current_rev is None:
                # All migrations are pending
                pending = len(list(script.walk_revisions()))
            else:
                # Count revisions between current and head
                for _rev in script.walk_revisions(head_rev, current_rev):
                    if _rev.revision != current_rev:
                        pending += 1
        except Exception:
            pending = -1  # Unknown

    # Display status
    current_display = current_rev[:12] if current_rev else "[yellow]None (not initialized)[/yellow]"
    head_display = head_rev[:12] if head_rev else "[yellow]None[/yellow]"

    status_color = "green" if current_rev == head_rev else "yellow"
    status_text = "Up to date" if current_rev == head_rev else f"{pending} pending"

    console.print(
        Panel(
            f"Current revision: [cyan]{current_display}[/cyan]\n"
            f"Head revision:    [cyan]{head_display}[/cyan]\n"
            f"Status:           [{status_color}]{status_text}[/{status_color}]",
            title="[bold]Migration Status[/bold]",
            border_style="blue",
        )
    )


@db.command("migrate")
@click.option(
    "--revision",
    "-r",
    default="head",
    show_default=True,
    help="Target revision to migrate to",
)
def db_migrate(revision: str) -> None:
    """Apply pending database migrations.

    Runs Alembic upgrade to the specified revision (defaults to head,
    applying all pending migrations).

    Examples:

    \b
        a-sdlc db migrate              # Apply all pending migrations
        a-sdlc db migrate -r head      # Same as above
        a-sdlc db migrate -r abc123    # Migrate to a specific revision
    """
    import alembic.command

    if _check_server_running():
        console.print(
            "[yellow]Warning: MCP server appears to be running. "
            "Consider stopping it before running migrations.[/yellow]"
        )
        if not click.confirm("Continue anyway?", default=False):
            console.print("[dim]Aborted.[/dim]")
            return

    try:
        cfg = _get_alembic_config()
    except Exception as exc:
        console.print(f"[red]Failed to load Alembic configuration: {exc}[/red]")
        sys.exit(1)

    console.print(f"[bold]Migrating database to revision: {revision}[/bold]")

    try:
        alembic.command.upgrade(cfg, revision)
        console.print(f"[green]Successfully migrated to {revision}.[/green]")
    except Exception as exc:
        console.print(f"[red]Migration failed: {exc}[/red]")
        sys.exit(1)


@db.command("rollback")
@click.option(
    "--revision",
    "-r",
    default="-1",
    show_default=True,
    help="Target revision to rollback to (use relative like -1 or absolute revision id)",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt",
)
def db_rollback(revision: str, yes: bool) -> None:
    """Revert database migrations.

    Runs Alembic downgrade to the specified revision. Defaults to
    reverting exactly one migration step (-1).

    Examples:

    \b
        a-sdlc db rollback             # Revert one migration step
        a-sdlc db rollback -r -2       # Revert two steps
        a-sdlc db rollback -r base     # Revert all migrations
        a-sdlc db rollback -y          # Skip confirmation
    """
    import alembic.command

    if _check_server_running():
        console.print(
            "[yellow]Warning: MCP server appears to be running. "
            "Consider stopping it before running rollback.[/yellow]"
        )
        if not click.confirm("Continue anyway?", default=False):
            console.print("[dim]Aborted.[/dim]")
            return

    if not yes:
        console.print(f"[yellow]This will downgrade the database to revision: {revision}[/yellow]")
        if not click.confirm("Are you sure?", default=False):
            console.print("[dim]Aborted.[/dim]")
            return

    try:
        cfg = _get_alembic_config()
    except Exception as exc:
        console.print(f"[red]Failed to load Alembic configuration: {exc}[/red]")
        sys.exit(1)

    console.print(f"[bold]Rolling back database to revision: {revision}[/bold]")

    try:
        alembic.command.downgrade(cfg, revision)
        console.print(f"[green]Successfully rolled back to {revision}.[/green]")
    except Exception as exc:
        console.print(f"[red]Rollback failed: {exc}[/red]")
        sys.exit(1)


def _resolve_source_url(source: str | None) -> str:
    """Convert a user-provided source string to a SQLAlchemy URL.

    - ``None`` -> default ``sqlite:///<data_dir>/data.db``
    - Strings starting with ``postgresql://``, ``postgres://``, or ``sqlite:///``
      are returned as-is (already valid SQLAlchemy URLs).
    - Otherwise treated as a local file path and wrapped in ``sqlite:///``.
    """
    if source is None:
        from a_sdlc.core.content import get_data_dir

        return f"sqlite:///{get_data_dir() / 'data.db'}"
    if source.startswith(("postgresql://", "postgres://", "sqlite:///")):
        return source
    return f"sqlite:///{Path(source).resolve()}"


@db.command("import")
@click.option(
    "--source",
    type=str,
    default=None,
    help="Source database (path or URL, default: auto-detect ~/.a-sdlc/data.db)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Allow import into a non-empty target database",
)
@click.option(
    "--skip-content",
    is_flag=True,
    help="Skip content file migration",
)
@click.option(
    "--merge",
    is_flag=True,
    help="Merge into existing data (bump conflicting IDs instead of overwriting)",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt",
)
@click.option("--source-s3-bucket", default=None, help="Source S3 bucket (for PG source)")
@click.option("--source-s3-endpoint", default=None, help="Source S3 endpoint URL")
@click.option("--source-s3-access-key", default=None, help="Source S3 access key")
@click.option("--source-s3-secret-key", default=None, help="Source S3 secret key")
def db_import(
    source: str | None,
    force: bool,
    skip_content: bool,
    merge: bool,
    yes: bool,
    source_s3_bucket: str | None,
    source_s3_endpoint: str | None,
    source_s3_access_key: str | None,
    source_s3_secret_key: str | None,
) -> None:
    """Import data from a source database.

    Migrates all data from a source database (SQLite or PostgreSQL) to
    the configured target database.  Use --merge to incrementally add
    data without overwriting existing records.

    Examples:

    \b
        a-sdlc db import                           # Auto-detect SQLite source
        a-sdlc db import --source /path/data.db    # Explicit SQLite path
        a-sdlc db import --source postgresql://host/db  # PG to PG
        a-sdlc db import --source postgresql://host/db \\
            --source-s3-bucket old-bucket \\
            --source-s3-endpoint http://old-minio:9000
        a-sdlc db import --merge                   # Merge without overwriting
        a-sdlc db import --skip-content            # Skip .md file migration
        a-sdlc db import --force -y                # Force, no confirmation
    """
    from a_sdlc.core.content import get_data_dir
    from a_sdlc.core.db_import import (
        DataImporter,
        PreflightError,
        count_content_files,
        get_source_summary,
    )
    from a_sdlc.core.storage_config import load_storage_config

    # 1. Resolve source database URL
    source_url = _resolve_source_url(source)
    source_is_pg = source_url.startswith(("postgresql://", "postgres://"))

    # For SQLite sources, check file existence early
    if not source_is_pg:
        source_path = Path(source_url.replace("sqlite:///", "", 1))
        if not source_path.exists():
            console.print(f"[red]Source database not found: {source_path}[/red]")
            sys.exit(1)

    # 2. Show source summary
    summary = get_source_summary(source_url)
    if not summary.get("exists"):
        display = source_url if source_is_pg else source_url.replace("sqlite:///", "", 1)
        console.print(f"[red]Source database not found: {display}[/red]")
        sys.exit(1)

    schema_ver = summary.get("schema_version")
    total_rows = summary.get("total_rows", 0)
    source_type = summary.get("type", "Unknown")

    source_table = Table(title="Source Database", border_style="blue")
    source_table.add_column("Property", style="cyan")
    source_table.add_column("Value")
    source_table.add_row("Type", source_type)
    source_table.add_row(
        "URL",
        _mask_db_url(source_url) if source_is_pg else source_url.replace("sqlite:///", "", 1),
    )
    source_table.add_row(
        "Schema version", str(schema_ver) if schema_ver else "[yellow]Unknown[/yellow]"
    )
    source_table.add_row("Total rows", str(total_rows))

    # Add per-entity counts
    for table_name in [
        "projects",
        "sprints",
        "prds",
        "tasks",
        "designs",
        "worktrees",
        "reviews",
        "requirements",
    ]:
        count = summary.get(table_name)
        if count is not None and count > 0:
            source_table.add_row(f"  {table_name}", str(count))

    console.print(source_table)
    console.print()

    # 3. Count content files
    content_count = 0
    source_content_backend = None

    if not skip_content:
        if source_is_pg:
            # For PG sources, content is in S3 — need source S3 config
            if source_s3_bucket:
                from a_sdlc.core.content import S3ContentBackend

                source_content_backend = S3ContentBackend(
                    bucket=source_s3_bucket,
                    endpoint_url=source_s3_endpoint,
                    access_key=source_s3_access_key,
                    secret_key=source_s3_secret_key,
                )
                content_count = count_content_files(backend=source_content_backend)
            else:
                console.print(
                    "[dim]No --source-s3-bucket provided; "
                    "skipping content migration for PG source.[/dim]"
                )
        else:
            content_dir = get_data_dir() / "content"
            content_count = count_content_files(content_dir)

        if content_count > 0:
            console.print(f"[dim]Content files found: {content_count}[/dim]")
        elif not source_is_pg or source_s3_bucket:
            console.print("[dim]No content files found for migration.[/dim]")
        console.print()

    # 4. Resolve target database URL
    try:
        storage_config = load_storage_config(validate=False)
        target_url = storage_config.database_url
    except Exception:
        target_url = None

    if not target_url:
        target_url = click.prompt(
            "Target database URL (e.g. postgresql://user:pass@host/db)",
            type=str,
        )

    masked_url = _mask_db_url(target_url)

    # 5. Resolve target S3 config if content migration needed
    migrate_content = not skip_content and content_count > 0
    target_content_backend = None
    source_content_dir_path: Path | None = None

    if migrate_content:
        try:
            storage_config = load_storage_config(validate=False)
            s3_bucket = getattr(storage_config, "s3_bucket", None)
        except Exception:
            s3_bucket = None

        if not s3_bucket:
            console.print("[yellow]S3 configuration needed for content migration.[/yellow]")
            s3_bucket = click.prompt("S3 bucket name")
            s3_endpoint = click.prompt("S3 endpoint URL (e.g. http://localhost:9000)")
            s3_access_key = click.prompt("S3 access key")
            s3_secret_key = click.prompt("S3 secret key", hide_input=True)

            from a_sdlc.core.content import S3ContentBackend

            target_content_backend = S3ContentBackend(
                bucket=s3_bucket,
                endpoint_url=s3_endpoint,
                access_key=s3_access_key,
                secret_key=s3_secret_key,
            )
        else:
            from a_sdlc.core.content import S3ContentBackend

            target_content_backend = S3ContentBackend(
                bucket=s3_bucket,
                endpoint_url=getattr(storage_config, "s3_endpoint", None),
                access_key=getattr(storage_config, "s3_access_key", None),
                secret_key=getattr(storage_config, "s3_secret_key", None),
            )

        # Source content dir only needed for local filesystem sources
        if not source_is_pg:
            source_content_dir_path = get_data_dir() / "content"

    # 6. Show summary panel
    mode = (
        "[cyan]merge[/cyan] (bump conflicting IDs)"
        if merge
        else "[cyan]import[/cyan] (full replacement)"
    )
    source_display = (
        _mask_db_url(source_url) if source_is_pg else source_url.replace("sqlite:///", "", 1)
    )
    panel_text = f"Source:  {source_display}\nTarget:  {masked_url}\nMode:    {mode}\nRows:    {total_rows}\n"
    if migrate_content:
        panel_text += f"Content: {content_count} files\n"
    if force and not merge:
        panel_text += "Force:   [yellow]Yes (will overwrite existing data)[/yellow]\n"

    console.print(
        Panel(panel_text.rstrip(), title="[bold]Import Summary[/bold]", border_style="blue")
    )
    console.print()

    # 7. Confirm
    if not yes and not click.confirm("Proceed with import?", default=False):
        console.print("[dim]Aborted.[/dim]")
        return

    # 8. Build importer and run
    importer: DataImporter
    if merge:
        from a_sdlc.core.db_merge import DataMerger

        importer = DataMerger(
            source_url=source_url,
            target_url=target_url,
            migrate_content=migrate_content,
            target_content_backend=target_content_backend,
            source_content_backend=source_content_backend,
            source_content_dir=source_content_dir_path,
        )
    else:
        importer = DataImporter(
            source_url=source_url,
            target_url=target_url,
            force=force,
            migrate_content=migrate_content,
            target_content_backend=target_content_backend,
            source_content_backend=source_content_backend,
            source_content_dir=source_content_dir_path,
        )

    # Progress callback
    from rich.progress import BarColumn, Progress, TextColumn

    progress = Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    )
    progress_tasks: dict[str, object] = {}

    def on_progress(table: str, current: int, total: int) -> None:
        if table not in progress_tasks:
            progress_tasks[table] = progress.add_task(table, total=total)
        progress.update(progress_tasks[table], completed=current)

    importer.progress_callback = on_progress

    try:
        with progress:
            import_result = importer.run()
    except PreflightError as exc:
        console.print(f"[red]Pre-flight check failed: {exc}[/red]")
        sys.exit(1)
    except Exception as exc:
        console.print(f"[red]Import failed: {exc}[/red]")
        sys.exit(1)

    # 9. Display results
    if import_result.success:
        console.print(f"\n[green]{import_result.summary()}[/green]")
        if import_result.rows_remapped:
            console.print(f"[cyan]  Remapped IDs: {import_result.rows_remapped}[/cyan]")
            for tbl, cnt in import_result.id_remap_summary.items():
                console.print(f"[dim]    {tbl}: {cnt}[/dim]")
        if import_result.rows_skipped:
            console.print(f"[yellow]  Skipped (duplicates): {import_result.rows_skipped}[/yellow]")
    else:
        console.print(f"\n[red]{import_result.summary()}[/red]")
        sys.exit(1)

    if import_result.warnings:
        for w in import_result.warnings:
            console.print(f"[yellow]  Warning: {w}[/yellow]")


if __name__ == "__main__":
    main()
