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
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from a_sdlc import __version__
from a_sdlc.artifacts import get_artifact_plugin_manager
from a_sdlc.installer import (
    Installer,
    check_claude_code_installed,
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
    check_docker_available,
    configure_langfuse_keys,
    setup_monitoring,
    verify_monitoring_setup,
    check_services_health,
    MONITORING_DIR,
)
from a_sdlc.sonarqube_setup import (
    check_scanner_available,
    generate_code_quality_artifact,
    run_scanner,
    setup_sonarqube,
    verify_sonarqube_setup,
)
from a_sdlc.plugins import get_plugin_manager

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
    "--transport", "-t",
    type=click.Choice(["stdio", "streamable-http"]),
    default="stdio",
    help="Transport type (default: stdio for Claude Code)"
)
@click.option(
    "--host",
    default="127.0.0.1",
    help="Host for HTTP transport"
)
@click.option(
    "--port",
    default=8765,
    type=int,
    help="Port for HTTP transport"
)
def serve(transport: str, host: str, port: int) -> None:
    """Start the a-sdlc MCP server.

    Runs the MCP server that provides tools for managing
    PRDs, tasks, and sprints through Claude Code.

    Examples:

        a-sdlc serve                    # Start with stdio (for Claude Code)
        a-sdlc serve -t streamable-http # Start HTTP server for debugging
    """
    from a_sdlc.server import run_server

    if transport == "stdio":
        # Don't print anything for stdio - it would interfere with MCP protocol
        run_server(transport="stdio")
    else:
        console.print(f"[cyan]Starting a-sdlc MCP server on http://{host}:{port}/mcp[/cyan]")
        run_server(transport="streamable-http")


@main.command()
@click.option(
    "--list", "list_skills",
    is_flag=True,
    help="List all installed skill templates"
)
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Force reinstall of all templates"
)
@click.option(
    "--target",
    type=click.Path(path_type=Path),
    default=None,
    help="Custom target directory (default: ~/.claude/commands/sdlc/)"
)
@click.option(
    "--with-serena",
    is_flag=True,
    help="Also install and configure Serena MCP server"
)
@click.option(
    "--with-monitoring",
    is_flag=True,
    help="Set up monitoring stack (Langfuse + SigNoz)"
)
@click.option(
    "--with-sonarqube",
    is_flag=True,
    help="Set up SonarQube code analysis integration"
)
@click.option(
    "--upgrade",
    is_flag=True,
    help="Force-refresh templates, migrate DB, update MCP config"
)
def install(list_skills: bool, force: bool, target: Path | None, with_serena: bool, with_monitoring: bool, with_sonarqube: bool, upgrade: bool) -> None:
    """Deploy skill templates to Claude Code.

    Installs the /sdlc:* commands into your Claude Code configuration,
    making them available for use in any project.

    Examples:

        a-sdlc install                    # Install all templates
        a-sdlc install --list             # List installed templates
        a-sdlc install --force            # Reinstall all templates
        a-sdlc install --upgrade          # Force-refresh templates + migrate DB + update MCP
        a-sdlc install --with-serena      # Also set up Serena MCP
        a-sdlc install --with-monitoring  # Also set up monitoring
    """
    installer = Installer(target_dir=target)

    if list_skills:
        _list_installed_skills(installer)
        return

    if upgrade:
        _run_upgrade(installer)
        return

    try:
        installed = installer.install(force=force)

        console.print()
        console.print(Panel(
            f"[green]Successfully installed {len(installed)} skill templates![/green]\n\n"
            f"Skills location: [cyan]{installer.target_dir}[/cyan]\n"
            f"MCP server: [cyan]Configured in ~/.claude.json[/cyan]\n\n"
            "[bold]Getting Started[/bold]\n"
            "  /sdlc:init                  Initialize project\n"
            "  /sdlc:scan                  Full repo scan → generate artifacts\n"
            "  /sdlc:help                  List all commands\n\n"
            "[bold]PRD Workflow[/bold]\n"
            "  /sdlc:ideate \"<idea>\"       Explore idea → PRDs\n"
            "  /sdlc:prd-generate \"<desc>\" Create PRD via interactive Q&A\n"
            "  /sdlc:prd-architect \"<id>\"  Generate design document\n"
            "  /sdlc:prd-split \"<id>\"      Decompose PRD into tasks\n\n"
            "[bold]Execution[/bold]\n"
            "  /sdlc:sprint-create         Create a sprint\n"
            "  /sdlc:sprint-run            Execute tasks in dependency order\n"
            "  /sdlc:task-start <id>       Start a task\n\n"
            "[bold]Analysis[/bold]\n"
            "  /sdlc:investigate \"<issue>\" Root cause analysis\n"
            "  /sdlc:pr-feedback           Process PR review comments\n"
            "  /sdlc:sonar-scan            SonarQube scan & auto-fix\n\n"
            "[dim]Run /sdlc:help in Claude Code for the full command reference.[/dim]",
            title="[bold]Installation Complete[/bold]",
            border_style="green"
        ))

        # Set up Serena MCP if requested
        if with_serena:
            console.print()
            _setup_serena_mcp(force=force)

        # Set up monitoring if requested
        if with_monitoring:
            console.print()
            _setup_monitoring(force=force)

        # Set up SonarQube if requested
        if with_sonarqube:
            console.print()
            _setup_sonarqube_interactive(force=force)

    except Exception as e:
        console.print(f"[red]Error during installation: {e}[/red]")
        sys.exit(1)


def _run_upgrade(installer: Installer) -> None:
    """Execute the full upgrade workflow: templates, DB migration, MCP config.

    Args:
        installer: Installer instance to use for template operations.
    """
    from a_sdlc.core.database import SCHEMA_VERSION, Database

    console.print()
    console.print("[bold cyan]Running upgrade...[/bold cyan]")
    console.print()

    # 1. Record pre-upgrade template version
    _, old_template_ver, current_template_ver = installer.check_template_version()

    # 2. Force-refresh templates (also refreshes MCP config via install)
    try:
        installed = installer.install(force=True)
        templates_status = f"refreshed ({old_template_ver} -> {current_template_ver}), {len(installed)} templates"
    except Exception as e:
        console.print(f"[red]Error refreshing templates: {e}[/red]")
        sys.exit(1)

    # 3. Trigger DB migration check (Database.__init__ runs auto-migration with backup)
    try:
        db = Database()
        db_status = f"schema v{SCHEMA_VERSION} (current)"
    except RuntimeError as e:
        console.print(f"[red]Database migration failed: {e}[/red]")
        sys.exit(1)

    # 4. Force-refresh MCP config
    try:
        mcp_result = configure_mcp_server(force=True)
        mcp_status = mcp_result.get("status", "updated")
    except Exception as e:
        console.print(f"[red]Error updating MCP config: {e}[/red]")
        sys.exit(1)

    # 5. Display upgrade summary
    console.print(Panel(
        "[green]Upgrade completed successfully![/green]\n\n"
        f"[bold]Templates:[/bold]  {templates_status}\n"
        f"[bold]Database:[/bold]   {db_status}\n"
        f"[bold]MCP config:[/bold] {mcp_status}",
        title="[bold]Upgrade Summary[/bold]",
        border_style="green"
    ))


@main.command()
def setup():
    """Interactive setup wizard for new users.

    Guides you through prerequisite checks, template installation,
    and MCP server configuration in one step.

    Examples:

        a-sdlc setup    # Run the interactive setup wizard
    """
    # Step 1: Welcome banner
    console.print()
    console.print(Panel(
        "[bold]Welcome to a-sdlc Setup Wizard[/bold]\n\n"
        "This wizard will:\n"
        "  1. Check prerequisites (Python, uv, Claude Code)\n"
        "  2. Install skill templates to ~/.claude/commands/sdlc/\n"
        "  3. Configure the asdlc MCP server in ~/.claude.json\n"
        "  4. Validate the installation",
        title="[bold cyan]a-sdlc[/bold cyan]",
        border_style="cyan"
    ))
    console.print()

    # Step 2: Run prerequisite checks
    console.print("[bold]Step 1: Checking prerequisites...[/bold]")
    console.print()

    checks = []
    has_critical_failure = False

    # Python version
    py_ok, py_msg = check_python_version()
    checks.append(("Python >= 3.10", py_ok, py_msg, True))
    if not py_ok:
        has_critical_failure = True

    # uv/uvx availability
    uv_ok, uv_msg = check_uv_available()
    checks.append(("uv / uvx", uv_ok, uv_msg, False))

    # Claude Code
    claude_ok, claude_msg = check_claude_code_installed()
    checks.append(("Claude Code", claude_ok, claude_msg, True))
    if not claude_ok:
        has_critical_failure = True

    # Display prerequisite table
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

    # Step 3: If any critical check fails, show fix instructions and exit
    if has_critical_failure:
        console.print("[red]Critical prerequisites not met. Please fix the following:[/red]")
        console.print()
        for name, passed, detail, critical in checks:
            if not passed and critical:
                console.print(f"  [red]{name}[/red]: {detail}")
                if "Python" in name:
                    console.print("  [dim]Fix: Install Python 3.10+ from https://www.python.org/downloads/[/dim]")
                elif "Claude" in name:
                    console.print("  [dim]Fix: Install Claude Code from https://docs.anthropic.com/en/docs/claude-code[/dim]")
        console.print()
        sys.exit(1)

    if not uv_ok:
        console.print("[yellow]Warning: uv/uvx not found. MCP server may not work without it.[/yellow]")
        console.print("[dim]Fix: curl -LsSf https://astral.sh/uv/install.sh | sh[/dim]")
        console.print()

    # Step 4: Install templates + MCP config
    console.print("[bold]Step 2: Installing skill templates...[/bold]")
    console.print()

    installer = Installer()

    # Step 5: Check if templates already exist; ask to force-refresh
    force = False
    installed_skills = installer.list_installed()
    if installed_skills:
        console.print(f"[yellow]Found {len(installed_skills)} existing skill templates.[/yellow]")
        if click.confirm("  Overwrite with latest templates?", default=False):
            force = True
        console.print()

    try:
        installed = installer.install(force=force)
        console.print(f"  Installed [green]{len(installed)}[/green] skill templates to [cyan]{installer.target_dir}[/cyan]")
    except Exception as e:
        console.print(f"[red]Error during installation: {e}[/red]")
        sys.exit(1)

    console.print()

    # Step 6: Validate installation
    console.print("[bold]Step 3: Validating installation...[/bold]")
    console.print()

    validation_ok = True

    # Check MCP config
    settings_path = get_claude_settings_path()
    mcp_configured = False
    if settings_path.exists():
        try:
            import json
            settings = json.loads(settings_path.read_text())
            mcp_configured = "asdlc" in settings.get("mcpServers", {})
        except (json.JSONDecodeError, KeyError):
            pass

    if mcp_configured:
        console.print("  [green]PASS[/green] asdlc MCP server configured in ~/.claude.json")
    else:
        console.print("  [red]FAIL[/red] asdlc MCP server not found in ~/.claude.json")
        validation_ok = False

    # Check data directory
    data_dir = Path.home() / ".a-sdlc"
    if data_dir.exists():
        console.print(f"  [green]PASS[/green] Data directory exists: {data_dir}")
    else:
        console.print(f"  [yellow]WARN[/yellow] Data directory not yet created: {data_dir}")
        console.print("  [dim]This is normal — it will be created on first use.[/dim]")

    # Check templates directory
    if installer.target_dir.exists():
        template_count = len(list(installer.target_dir.glob("*.md")))
        console.print(f"  [green]PASS[/green] {template_count} skill templates in {installer.target_dir}")
    else:
        console.print(f"  [red]FAIL[/red] Templates directory missing: {installer.target_dir}")
        validation_ok = False

    console.print()

    if not validation_ok:
        console.print("[red]Validation failed. Please check the errors above.[/red]")
        sys.exit(1)

    # Step 7: Success summary with next steps
    console.print(Panel(
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
        border_style="green"
    ))


def _list_installed_skills(installer: Installer) -> None:
    """Display table of installed skill templates."""
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
        table.add_row(
            f"/sdlc:{skill['name']}",
            skill['file'],
            "Installed"
        )

    console.print(table)


def _setup_serena_mcp(force: bool = False) -> bool:
    """Set up Serena MCP server.

    Returns:
        True if setup succeeded, False otherwise.
    """
    console.print(Panel(
        "[bold]Setting up Serena MCP Server[/bold]\n\n"
        "Serena provides semantic code analysis capabilities\n"
        "that power the /sdlc:scan and /sdlc:update commands.",
        border_style="blue"
    ))

    success, message, verification = setup_serena(force=force)

    if success:
        console.print(f"[green]{message}[/green]")
        console.print()

        if verification:
            table = Table(title="Serena MCP Setup")
            table.add_column("Check", style="cyan")
            table.add_column("Status")

            table.add_row(
                "Package Installer",
                f"[green]{verification.get('installer_method', 'N/A')}[/green]"
            )
            table.add_row(
                "Claude Settings",
                "[green]Configured[/green]" if verification.get("configured_in_settings") else "[yellow]Not configured[/yellow]"
            )
            table.add_row(
                "Settings File",
                f"[dim]{verification.get('settings_file', 'N/A')}[/dim]"
            )

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
    console.print(Panel(
        "[bold]Setting up Monitoring Stack[/bold]\n\n"
        "This will install:\n"
        "  - Langfuse (conversation tracing)\n"
        "  - SigNoz (OTEL metrics & logs)\n\n"
        f"Files: [cyan]{MONITORING_DIR}[/cyan]",
        border_style="blue"
    ))

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
                "[green]Installed[/green]" if verification.get("files_ready") else "[red]Missing[/red]"
            )
            table.add_row(
                "SigNoz",
                "[green]Cloned[/green]" if verification.get("signoz_cloned") else "[red]Not cloned[/red]"
            )
            table.add_row(
                "Stop Hook",
                "[green]Registered[/green]" if verification.get("hook_registered") else "[yellow]Not registered[/yellow]"
            )
            table.add_row(
                "OTEL Environment",
                "[green]Configured[/green]" if verification.get("otel_configured") else "[yellow]Not configured[/yellow]"
            )
            table.add_row(
                "Langfuse API Keys",
                "[green]Configured[/green]" if verification.get("langfuse_keys_configured") else "[yellow]Not yet (run: a-sdlc monitoring configure)[/yellow]"
            )

            console.print(table)

        console.print()
        console.print("[bold]Next steps:[/bold]")
        console.print(f"  1. Start services:   [cyan]a-sdlc monitoring start[/cyan]")
        console.print(f"  2. Open Langfuse:    [cyan]http://localhost:13000[/cyan]")
        console.print(f"     Login:            admin@langfuse.local / changeme123")
        console.print(f"     Go to Settings > API Keys > Create")
        console.print(f"  3. Configure keys:   [cyan]a-sdlc monitoring configure[/cyan]")
        console.print(f"  4. Restart Claude Code")

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
    help="Also remove project data (~/.a-sdlc/ including PRDs, tasks, database)"
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview what would be removed without making changes"
)
@click.option(
    "-y", "--yes",
    is_flag=True,
    help="Skip confirmation prompt"
)
def uninstall(include_data: bool, dry_run: bool, yes: bool) -> None:
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

    plan = build_uninstall_plan(include_data=include_data)

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
        console.print(Panel(
            "\n".join(f"[green]  {a}[/green]" for a in result.actions),
            title="[bold]Actions Taken[/bold]",
            border_style="green",
        ))

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
    console.print("  - Per-project [cyan].sdlc/[/cyan] directories must be removed manually from each repo.")


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
        "Remove from settings.json" if plan.has_serena_mcp else "Skip",
    )
    table.add_row(
        "Skill templates",
        f"[green]{plan.skill_template_count} files[/green]" if plan.skill_template_count else "[dim]None[/dim]",
        f"Delete {plan.skill_template_count} templates" if plan.skill_template_count else "Skip",
    )
    table.add_row(
        "Monitoring hook",
        "[green]Found[/green]" if plan.has_monitoring_hook else "[dim]Not found[/dim]",
        "Remove from settings.json" if plan.has_monitoring_hook else "Skip",
    )
    table.add_row(
        "OTEL/Langfuse env vars",
        f"[green]{len(plan.managed_env_keys)} keys[/green]" if plan.managed_env_keys else "[dim]None[/dim]",
        f"Remove {len(plan.managed_env_keys)} key(s)" if plan.managed_env_keys else "Skip",
    )
    table.add_row(
        "Monitoring files",
        f"[green]{plan.monitoring_dir}[/green]" if plan.has_monitoring_dir else "[dim]Not found[/dim]",
        "Delete directory" if plan.has_monitoring_dir else "Skip",
    )
    table.add_row(
        "Project data",
        f"[green]{plan.data_dir}[/green]" if plan.has_data_dir else "[dim]Not found[/dim]",
        "[red]Delete directory[/red]" if plan.include_data and plan.has_data_dir
        else "[dim]Preserved (use --include-data)[/dim]" if plan.has_data_dir
        else "Skip",
    )

    console.print(table)


def _plan_has_work(plan) -> bool:
    """Check if the plan has anything to do."""
    return any([
        plan.has_asdlc_mcp,
        plan.has_serena_mcp,
        plan.skill_template_count > 0,
        plan.has_monitoring_hook,
        plan.managed_env_keys,
        plan.has_monitoring_dir,
        plan.include_data and plan.has_data_dir,
    ])


@main.command("setup-mcp")
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Force reconfigure even if already set up"
)
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
    console.print(Panel(
        "[bold]Langfuse API Key Configuration[/bold]\n\n"
        "Get your keys from http://localhost:13000\n"
        "  Login: admin@langfuse.local / changeme123\n"
        "  Go to: Settings > API Keys > Create",
        border_style="blue"
    ))

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
    console.print(Panel(
        "[bold]Monitoring Status[/bold]",
        border_style="blue"
    ))

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
        "http://localhost:13000"
    )

    signoz_ok = health.get("signoz_reachable", False)
    health_table.add_row(
        "SigNoz",
        "[green]Running[/green]" if signoz_ok else "[red]Not reachable[/red]",
        "http://localhost:8080"
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

    console.print(Panel(
        "[bold]Setting up SonarQube Integration[/bold]\n\n"
        "This will configure code analysis with your SonarQube instance.\n"
        "You'll need:\n"
        "  - SonarQube host URL\n"
        "  - Authentication token\n"
        "  - Project key",
        border_style="blue"
    ))

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
                else "[yellow]Not found[/yellow]"
            )
            table.add_row(
                "Connection",
                "[green]Connected[/green]"
                if verification.get("sonarqube_reachable")
                else "[yellow]Not reachable[/yellow]"
            )
            table.add_row(
                "Project Key",
                f"[green]{project_key}[/green]"
                if verification.get("project_key_configured")
                else "[yellow]Not set[/yellow]"
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
    console.print(Panel(
        "[bold]SonarQube Integration Status[/bold]",
        border_style="blue"
    ))

    verification = verify_sonarqube_setup()

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Details", style="dim")

    scanner_ok = verification.get("scanner_available", False)
    table.add_row(
        "Scanner",
        "[green]Available[/green]" if scanner_ok else "[yellow]Not found[/yellow]",
        "pysonar" if scanner_ok else "Install with: uv tool install pysonar"
    )

    table.add_row(
        "Host URL",
        "[green]Configured[/green]" if verification.get("host_url_configured") else "[yellow]Not set[/yellow]",
        ""
    )

    table.add_row(
        "Token",
        "[green]Configured[/green]" if verification.get("token_configured") else "[yellow]Not set[/yellow]",
        ""
    )

    table.add_row(
        "Project Key",
        "[green]Configured[/green]" if verification.get("project_key_configured") else "[yellow]Not set[/yellow]",
        ""
    )

    reachable = verification.get("sonarqube_reachable", False)
    table.add_row(
        "Connection",
        "[green]Connected[/green]" if reachable else "[yellow]Not reachable[/yellow]",
        str(verification.get("connection_message", ""))
    )

    ready = verification.get("ready", False)
    table.add_row(
        "Overall",
        "[green]Ready[/green]" if ready else "[yellow]Not ready[/yellow]",
        ""
    )

    console.print(table)

    if not ready:
        console.print()
        console.print("[dim]Run [cyan]a-sdlc sonarqube configure[/cyan] to set up.[/dim]")


@main.command()
def doctor() -> None:
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
    - Database accessibility and schema version
    """
    console.print(Panel(
        "[bold]a-sdlc System Diagnostics[/bold]",
        border_style="blue"
    ))

    checks = []

    # Python version check
    py_version = sys.version_info
    py_ok = py_version >= (3, 10)
    checks.append({
        "name": "Python Version",
        "status": "pass" if py_ok else "fail",
        "detail": f"{py_version.major}.{py_version.minor}.{py_version.micro}"
                 if py_ok else f"{py_version.major}.{py_version.minor}.{py_version.micro} (requires >= 3.10). Fix: install Python 3.10+"
    })

    # uv/uvx availability check
    uv_ok, uv_msg = check_uv_available()
    checks.append({
        "name": "uv/uvx",
        "status": "pass" if uv_ok else "fail",
        "detail": uv_msg if uv_ok else f"Not found. Fix: install from https://docs.astral.sh/uv/"
    })

    # Claude Code config directory
    claude_dir = Path.home() / ".claude"
    claude_ok = claude_dir.exists()
    checks.append({
        "name": "Claude Code Config",
        "status": "pass" if claude_ok else "warn",
        "detail": str(claude_dir) if claude_ok else "Not found. Fix: install Claude Code from https://claude.ai/code"
    })

    # asdlc MCP server in ~/.claude.json
    settings_path = get_claude_settings_path()
    try:
        if settings_path.exists():
            with open(settings_path) as f:
                claude_settings = json.load(f)
            mcp_ok = "asdlc" in claude_settings.get("mcpServers", {})
        else:
            mcp_ok = False
    except (json.JSONDecodeError, OSError):
        mcp_ok = False
    checks.append({
        "name": "asdlc MCP Server",
        "status": "pass" if mcp_ok else "warn",
        "detail": "Configured in ~/.claude.json" if mcp_ok else "Not found. Fix: run a-sdlc install"
    })

    # Commands directory
    commands_dir = claude_dir / "commands" / "sdlc"
    commands_ok = commands_dir.exists()
    checks.append({
        "name": "Skill Templates",
        "status": "pass" if commands_ok else "warn",
        "detail": f"{len(list(commands_dir.glob('*.md')))} installed" if commands_ok else "Not installed. Fix: run a-sdlc install"
    })

    # Template version check
    try:
        installer = Installer()
        tpl_up_to_date, tpl_installed, tpl_current = installer.check_template_version()
        if tpl_up_to_date:
            tpl_status, tpl_detail = "pass", f"v{tpl_installed} (current)"
        else:
            tpl_status, tpl_detail = "warn", f"v{tpl_installed} installed, v{tpl_current} available. Fix: run a-sdlc install --force"
    except Exception:
        tpl_status, tpl_detail = "warn", "Cannot check. Fix: run a-sdlc install"
    checks.append({
        "name": "Template Version",
        "status": tpl_status,
        "detail": tpl_detail
    })

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

    checks.append({
        "name": "Serena MCP",
        "status": serena_status,
        "detail": serena_detail
    })

    # Plugin manager
    pm = get_plugin_manager()
    plugins = pm.list_plugins()
    checks.append({
        "name": "Plugins Available",
        "status": "pass",
        "detail": ", ".join(plugins) if plugins else "None"
    })

    # Monitoring checks
    docker_ok = check_docker_available()
    checks.append({
        "name": "Docker",
        "status": "pass" if docker_ok else "warn",
        "detail": "Available" if docker_ok else "Not found. Fix: install Docker from https://docs.docker.com/get-docker/"
    })

    mon_verification = verify_monitoring_setup()

    checks.append({
        "name": "Monitoring Files",
        "status": "pass" if mon_verification.get("files_ready") else "warn",
        "detail": "Installed" if mon_verification.get("files_ready") else "Not installed. Fix: run a-sdlc install --with-monitoring"
    })

    checks.append({
        "name": "Langfuse Hook",
        "status": "pass" if mon_verification.get("hook_registered") else "warn",
        "detail": "Registered" if mon_verification.get("hook_registered") else "Not registered. Fix: run a-sdlc install --with-monitoring"
    })

    checks.append({
        "name": "OTEL Environment",
        "status": "pass" if mon_verification.get("otel_configured") else "warn",
        "detail": "Configured" if mon_verification.get("otel_configured") else "Not configured. Fix: run a-sdlc install --with-monitoring"
    })

    if mon_verification.get("files_ready"):
        health = check_services_health()
        langfuse_ok = health.get("langfuse_reachable", False)
        signoz_ok = health.get("signoz_reachable", False)

        checks.append({
            "name": "Langfuse Service",
            "status": "pass" if langfuse_ok else "warn",
            "detail": "http://localhost:13000" if langfuse_ok else "Not reachable. Fix: run a-sdlc monitoring start"
        })
        checks.append({
            "name": "SigNoz Service",
            "status": "pass" if signoz_ok else "warn",
            "detail": "http://localhost:8080" if signoz_ok else "Not reachable. Fix: run a-sdlc monitoring start"
        })

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

    checks.append({
        "name": "SonarQube",
        "status": sq_status,
        "detail": sq_detail
    })

    # Database accessibility check
    from a_sdlc.core.database import Database, SCHEMA_VERSION
    import sqlite3
    db = None  # type: ignore[assignment]
    try:
        db = Database()
        db_path = db.db_path
        db_accessible = Path(db_path).exists() if str(db_path) != ":memory:" else True
        checks.append({
            "name": "Database Accessible",
            "status": "pass" if db_accessible else "fail",
            "detail": str(db_path) if db_accessible else f"Database file not found at {db_path}. Fix: run a-sdlc install"
        })
    except Exception as e:
        checks.append({
            "name": "Database Accessible",
            "status": "fail",
            "detail": f"Cannot open database: {e}. Fix: check ~/.a-sdlc/ permissions or run a-sdlc install"
        })

    # Database schema version check
    try:
        if db is not None:
            with sqlite3.connect(db.db_path) as conn:
                actual = conn.execute("SELECT version FROM schema_version").fetchone()[0]
            if actual == SCHEMA_VERSION:
                schema_status, schema_detail = "pass", f"v{actual} (current)"
            else:
                schema_status, schema_detail = "warn", f"v{actual} (expected v{SCHEMA_VERSION}). Fix: run a-sdlc install --upgrade"
        else:
            schema_status, schema_detail = "fail", "Skipped (database not accessible). Fix: resolve database issue above"
    except Exception as e:
        schema_status, schema_detail = "fail", f"Cannot check: {e}. Fix: run a-sdlc install --upgrade"

    checks.append({
        "name": "Database schema version",
        "status": schema_status,
        "detail": schema_detail
    })

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
        sys.exit(1)


@main.group()
def plugins() -> None:
    """Manage task storage plugins.

    Plugins allow tasks to be stored in different backends:
    - local: File-based storage in .sdlc/tasks/ (default)
    - linear: Sync with Linear issue tracker
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
        "local": "File-based task storage in .sdlc/tasks/",
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
    "--type", "-t",
    "plugin_type",
    type=click.Choice(["task", "artifact"]),
    default=None,
    help="Plugin type (task or artifact). Auto-detected if not specified."
)
@click.option(
    "--global", "-g",
    "save_global",
    is_flag=True,
    help="Save to global config (~/.config/a-sdlc/) instead of project config (.sdlc/)"
)
def plugins_enable(plugin_name: str, plugin_type: str | None, save_global: bool) -> None:
    """Enable a specific plugin.

    PLUGIN_NAME: Name of the plugin to enable (e.g., 'jira', 'confluence')

    By default, saves to project config (.sdlc/config.yaml).
    Use --global to save to user-wide config (~/.config/a-sdlc/config.yaml).
    """
    pm = get_plugin_manager()
    apm = get_artifact_plugin_manager()
    target = "global" if save_global else "project"

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
    "--global", "-g",
    "save_global",
    is_flag=True,
    help="Save to global config (~/.config/a-sdlc/) instead of project config (.sdlc/)"
)
def plugins_configure(plugin_name: str, save_global: bool) -> None:
    """Configure a plugin interactively.

    PLUGIN_NAME: Name of the plugin to configure (task plugins: local, linear, jira; artifact plugins: confluence)

    By default, saves to project config (.sdlc/config.yaml).
    Use --global to save to user-wide config (~/.config/a-sdlc/config.yaml).
    """
    pm = get_plugin_manager()
    apm = get_artifact_plugin_manager()
    target = "global" if save_global else "project"

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


def _configure_linear_plugin(pm: object, target: str = "project") -> None:
    """Interactive configuration for Linear plugin."""
    location = "global config" if target == "global" else "project config"
    console.print(Panel(
        f"[bold]Linear Plugin Configuration[/bold]\n\n"
        f"Saving to: {location}\n\n"
        "You'll need:\n"
        "  - Linear API key (from Settings > API)\n"
        "  - Team ID (visible in team URL)",
        border_style="blue"
    ))

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


def _configure_jira_plugin(pm: object, target: str = "project") -> None:
    """Interactive configuration for Jira plugin."""
    location = "global config" if target == "global" else "project config"
    console.print(Panel(
        f"[bold]Jira Cloud Plugin Configuration[/bold]\n\n"
        f"Saving to: {location}\n\n"
        "You'll need:\n"
        "  - Atlassian site URL (e.g., https://company.atlassian.net)\n"
        "  - Atlassian account email\n"
        "  - API token (from https://id.atlassian.com/manage-profile/security/api-tokens)\n"
        "  - Jira project key (e.g., 'PROJ')",
        border_style="blue"
    ))

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


def _configure_confluence_plugin(apm: object, target: str = "project") -> None:
    """Interactive configuration for Confluence plugin."""
    location = "global config" if target == "global" else "project config"
    console.print(Panel(
        f"[bold]Confluence Cloud Plugin Configuration[/bold]\n\n"
        f"Saving to: {location}\n\n"
        "You'll need:\n"
        "  - Atlassian site URL (e.g., https://company.atlassian.net)\n"
        "  - Atlassian account email\n"
        "  - API token (from https://id.atlassian.com/manage-profile/security/api-tokens)\n"
        "  - Confluence space key (e.g., 'PROJ')\n"
        "  - Optional: Parent page ID for SDLC documentation",
        border_style="blue"
    ))

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
    from a_sdlc.artifacts.local import LocalArtifactPlugin
    from a_sdlc.artifacts.base import Artifact

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
            time_diff = (_to_naive_utc(artifact.updated_at) - _to_naive_utc(remote.updated_at)).total_seconds()

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
            and abs((_to_naive_utc(a.updated_at) - _to_naive_utc(remote_artifacts_map[a.id].updated_at)).total_seconds()) < 60
        )
        local_newer = sum(
            1
            for a in local_artifacts
            if a.id in remote_artifacts_map
            and (_to_naive_utc(a.updated_at) - _to_naive_utc(remote_artifacts_map[a.id].updated_at)).total_seconds() >= 60
        )
        not_published = sum(
            1 for a in local_artifacts if a.id not in remote_artifacts_map and not a.external_id
        )

        console.print(f"In sync: {in_sync} | Local newer: {local_newer} | Not published: {not_published}")

        if local_newer > 0:
            console.print()
            console.print("Run [cyan]a-sdlc artifacts push[/cyan] to sync local changes to Confluence.")
    else:
        published = sum(1 for a in local_artifacts if a.external_id)
        console.print(f"Published: {published}/{len(local_artifacts)} artifacts")
        console.print("[dim](Confluence not configured - showing local status only)[/dim]")


@artifacts.command("push")
@click.argument("artifact_name", required=False)
@click.option("--force", "-f", is_flag=True, help="Force republish all artifacts")
@click.option("--dry-run", is_flag=True, help="Show what would be published without actually publishing")
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
        local_artifacts = [a for a in local_artifacts if a.id == artifact_name or a.id == artifact_name.replace(".md", "")]
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
        remote_artifacts = [a for a in remote_artifacts if a.id == artifact_name or a.id == artifact_name.replace(".md", "")]
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
            console.print("[yellow]Warning: The following local artifacts will be overwritten:[/yellow]")
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
            remote_prds = confluence.list_prds()
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
    console.print(Panel(
        f"[bold]{prd_obj.title}[/bold]\n\n"
        f"ID: {prd_obj.id}\n"
        f"Version: {prd_obj.version}\n"
        f"Updated: {prd_obj.updated_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"Confluence: {prd_obj.external_url or 'Not synced'}",
        title="PRD Info",
        border_style="blue",
    ))

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
        prd_obj = confluence.pull_prd(title)
    except KeyError:
        console.print(f"[red]PRD not found in Confluence: {title}[/red]")
        console.print()
        console.print("Available PRDs in Confluence:")
        for remote_prd in confluence.list_prds():
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
        content = filepath.read_text()
        prd_obj = PRD.from_file(str(filepath), content)

        # Store in local storage first
        local = LocalPRDPlugin({"prds_dir": str(prds_dir)})
        local.store_prd(prd_obj)
    else:
        # It's a PRD ID
        local = LocalPRDPlugin({"prds_dir": str(prds_dir)})
        prd_obj = local.get_prd(prd_id_or_file)

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
    existing = confluence.get_prd_page(prd_obj.title)
    if existing and not force:
        console.print(f"[yellow]PRD already exists in Confluence: {prd_obj.title}[/yellow]")
        console.print("Use [cyan]--force[/cyan] to update.")
        sys.exit(1)

    # Push to Confluence
    action = "Updating" if existing else "Creating"
    console.print(f"{action} PRD in Confluence: {prd_obj.title}...")

    try:
        page_id = confluence.push_prd(prd_obj)
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

            confluence.delete_prd(title)
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
            for s in sections.keys():
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
            console.print(f"\n[dim]Current content:[/dim]")
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
                console.print(
                    "\n[dim]Enter new content (press Ctrl+D or Ctrl+Z when done):[/dim]"
                )
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

        console.print(f"\n[bold]🔢 Version Bump[/bold]")
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
    console.print(f"\n[bold]📊 Changes:[/bold]")
    console.print(f"  - Version: {old_version} → {prd_obj.version}")
    if not fix:
        console.print(f"  - Sections modified: {len(sections_modified)}")
    console.print(f"  - Change type: {bump_type.title()}")

    console.print(f"\n[bold]🔗 Next steps:[/bold]")
    console.print(f"  - View: [cyan]a-sdlc prd show {prd_id}[/cyan]")

    # Optional Confluence push
    if push:
        try:
            apm = get_artifact_plugin_manager()
            confluence = apm.get_plugin("confluence")

            console.print(f"\n[cyan]Pushing to Confluence...[/cyan]")
            page_id = confluence.push_prd(prd_obj)

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
    from a_sdlc.plugins.local import LocalPlugin

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
            context[artifact_name] = artifact_path.read_text()
            console.print(f"   [green]✓[/green] {artifact_name}")
        else:
            console.print(
                f"   [yellow]⚠[/yellow] {artifact_name} not found (run /sdlc:scan)"
            )

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

    # Save tasks locally
    pm = get_plugin_manager()
    local = LocalPlugin({"path": ".sdlc/tasks"})

    saved_ids = []
    for task in tasks:
        task_id = local.create_task(task)
        saved_ids.append(task_id)

    console.print(
        f"\n[green]✓ Saved {len(saved_ids)} tasks to .sdlc/tasks/active/[/green]"
    )

    # Optional sync
    provider = pm.get_enabled_plugin()
    should_sync = sync or (
        provider in ["jira", "linear"]
        and click.confirm(f"\nSync to {provider.title()}?", default=False)
    )

    if should_sync:
        _sync_tasks_to_external(pm, tasks, saved_ids)

    # Display summary
    console.print(f"\n[bold green]✅ Task splitting complete[/bold green]")
    console.print(f"\n[bold]📊 Summary:[/bold]")
    console.print(f"  - PRD: {prd_id}")
    console.print(f"  - Tasks created: {len(tasks)}")
    components = set(t.component for t in tasks if t.component)
    console.print(f"  - Components: {len(components)}")
    console.print(f"\n[bold]🔗 Next steps:[/bold]")
    console.print(f"  - View tasks: [cyan]a-sdlc task list[/cyan]")
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
            priority = (
                TaskPriority.HIGH if task_counter <= 3 else TaskPriority.MEDIUM
            )
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
            from a_sdlc.plugins.jira import JiraPlugin

            plugin = pm.get_plugin("jira")

            console.print(f"\n[cyan]Syncing {len(tasks)} tasks to Jira...[/cyan]")

            for task in tasks:
                external_id = plugin.create_task(task)
                console.print(f"  ✓ {task.id} → {external_id}")

            console.print(f"[green]✓ All tasks synced to Jira[/green]")

        elif provider == "linear":
            console.print("[yellow]Linear sync not yet implemented[/yellow]")
            console.print("Use manual instructions from task output")

    except Exception as e:
        console.print(f"[red]Sync failed: {e}[/red]")
        console.print("Tasks saved locally. Sync manually with:")
        console.print(f"  [cyan]a-sdlc task sync[/cyan]")


# =============================================================================
# Task CLI Commands (using SQLite database)
# =============================================================================


@main.command("tasks")
@click.option("--status", "-s", type=click.Choice(["pending", "in_progress", "completed", "blocked"]), help="Filter by status")
@click.option("--sprint", help="Filter by sprint ID")
def tasks_list(status: str | None, sprint: str | None) -> None:
    """List tasks for the current project.

    Examples:

        a-sdlc tasks                    # All tasks
        a-sdlc tasks --status pending   # Pending tasks only
        a-sdlc tasks --sprint SPRINT-01 # Tasks in sprint
    """
    from a_sdlc.storage import get_storage

    storage = get_storage()

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
    from a_sdlc.storage import get_storage

    storage = get_storage()
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

    console.print(Panel(
        f"[bold]{task['title']}[/bold]\n\n"
        f"Status: {status_icons.get(task['status'], task['status'])}\n"
        f"Priority: {task.get('priority', 'medium').title()}\n"
        f"Component: {task.get('component') or 'N/A'}\n"
        f"Sprint: {task.get('sprint_id') or 'None'}\n"
        f"PRD: {task.get('prd_id') or 'None'}\n"
        f"Created: {task['created_at']}\n"
        f"Updated: {task['updated_at']}",
        title=f"[cyan]{task['id']}[/cyan]",
        border_style="blue"
    ))

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
    from a_sdlc.storage import get_storage

    storage = get_storage()
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
        from a_sdlc.ui import stop_server, PID_FILE
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


@main.command("complete")
@click.argument("task_id")
def complete_task_cmd(task_id: str) -> None:
    """Mark a task as completed.

    TASK_ID: Task identifier (e.g., TASK-001)

    Examples:

        a-sdlc complete TASK-001
    """
    from a_sdlc.storage import get_storage

    storage = get_storage()
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
@click.option("--api-key", prompt="Linear API Key (from Settings > API)", hide_input=True, help="Linear API key")
@click.option("--team-id", prompt="Team ID (e.g., ENG, PROD)", help="Team identifier (e.g., 'ENG')")
@click.option("--default-project", default=None, help="Optional default project name")
def connect_linear(api_key: str, team_id: str, default_project: str | None) -> None:
    """Configure Linear integration for the current project.

    Linear API key can be generated from Settings > API in Linear.

    Examples:

        a-sdlc connect linear --api-key <key> --team-id ENG
        a-sdlc connect linear  # Interactive prompts
    """
    from a_sdlc.storage import get_storage

    storage = get_storage()
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
    console.print("  - Or link a sprint: [cyan]/sdlc:sprint-link SPRINT-01 linear <cycle-id>[/cyan]")


@connect.command("jira")
@click.option("--url", prompt="Atlassian Site URL (e.g., https://company.atlassian.net)", help="e.g., https://company.atlassian.net")
@click.option("--email", prompt="Atlassian Email (e.g., user@company.com)", help="Your Atlassian account email")
@click.option("--api-token", prompt="API Token (from id.atlassian.com/manage-profile/security/api-tokens)", hide_input=True, help="Atlassian API token")
@click.option("--project-key", prompt="Jira Project Key (e.g., PROJ, ENG)", help="Jira project key (e.g., 'PROJ')")
@click.option("--issue-type", default="Task", help="Default issue type")
def connect_jira(url: str, email: str, api_token: str, project_key: str, issue_type: str) -> None:
    """Configure Jira integration for the current project.

    API token can be generated from https://id.atlassian.com/manage-profile/security/api-tokens

    Examples:

        a-sdlc connect jira --url https://company.atlassian.net --email user@example.com --project-key PROJ
        a-sdlc connect jira  # Interactive prompts
    """
    from a_sdlc.storage import get_storage

    storage = get_storage()
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
@click.option("--url", prompt="Atlassian Site URL (e.g., https://company.atlassian.net)", help="e.g., https://company.atlassian.net")
@click.option("--email", prompt="Atlassian Email (e.g., user@company.com)", help="Your Atlassian account email")
@click.option("--api-token", prompt="API Token (from id.atlassian.com/manage-profile/security/api-tokens)", hide_input=True, help="Atlassian API token")
@click.option("--space-key", prompt="Confluence Space Key (e.g., PROJ, DOCS, ENG)", help="Space key (e.g., 'PROJ')")
@click.option("--parent-page-id", default=None, help="Optional parent page ID for SDLC docs")
@click.option("--page-prefix", default="[SDLC]", help="Page title prefix (default: '[SDLC]')")
def connect_confluence(url: str, email: str, api_token: str, space_key: str, parent_page_id: str | None, page_prefix: str) -> None:
    """Configure Confluence integration for the current project.

    API token can be generated from https://id.atlassian.com/manage-profile/security/api-tokens

    Examples:

        a-sdlc connect confluence --url https://company.atlassian.net --email user@example.com --space-key PROJ
        a-sdlc connect confluence  # Interactive prompts
    """
    from a_sdlc.storage import get_storage

    storage = get_storage()
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
@click.option("--token", prompt="GitHub Personal Access Token", hide_input=True, help="GitHub PAT with 'repo' scope")
@click.option("--global", "-g", "save_global", is_flag=True, help="Save globally (~/.config/a-sdlc/) instead of project-level")
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
        console.print(f"[green]✓ GitHub integration configured globally (authenticated as @{user['login']})[/green]")
        console.print("[dim]Token saved to ~/.config/a-sdlc/config.yaml[/dim]")
    else:
        from a_sdlc.storage import get_storage

        storage = get_storage()
        cwd = str(Path.cwd())
        project = storage.get_project_by_path(cwd)

        if not project:
            console.print("[yellow]No project found for current directory.[/yellow]")
            console.print("Run [cyan]/sdlc:init[/cyan] first, or use [cyan]--global[/cyan] for cross-project config.")
            sys.exit(1)

        storage.set_external_config(project["id"], "github", {"token": token})
        console.print(f"[green]✓ GitHub integration configured for {project['name']} (authenticated as @{user['login']})[/green]")

    console.print()
    console.print("Next steps:")
    console.print("  - Get PR feedback: [cyan]/sdlc:pr-feedback[/cyan]")


@main.command("disconnect")
@click.argument("system", type=click.Choice(["linear", "jira", "confluence", "github"]))
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.option("--global", "-g", "remove_global", is_flag=True, help="Remove global config (~/.config/a-sdlc/) instead of project-level (github only)")
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
            console.print(f"[yellow]--global flag is only supported for github.[/yellow]")
            sys.exit(1)

        from a_sdlc.server.github import delete_global_github_config

        if not yes:
            if not click.confirm("Remove global GitHub configuration?"):
                console.print("Aborted.")
                return

        if delete_global_github_config():
            console.print("[green]✓ Global GitHub integration removed[/green]")
        else:
            console.print("[yellow]No global GitHub configuration found.[/yellow]")
        return

    from a_sdlc.storage import get_storage

    storage = get_storage()
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

    if not yes:
        if not click.confirm(f"Remove {system.title()} integration from {project['name']}?"):
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
    from a_sdlc.storage import get_storage

    storage = get_storage()
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
            config_display = f"Project: {cfg.get('project_key', 'N/A')} at {cfg.get('base_url', 'N/A')}"

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
        console.print(f"[dim]Global GitHub config: Token: {masked} (~/.config/a-sdlc/config.yaml)[/dim]")
        console.print()

    # Show sync mappings summary
    mappings = storage.list_sync_mappings()
    if mappings:
        sprint_mappings = [m for m in mappings if m["entity_type"] == "sprint"]
        task_mappings = [m for m in mappings if m["entity_type"] == "task"]
        console.print(f"[dim]Linked: {len(sprint_mappings)} sprint(s), {len(task_mappings)} task(s)[/dim]")


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
    from a_sdlc.storage import get_storage
    from a_sdlc.server.sync import ExternalSyncService, JiraClient

    storage = get_storage()
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
    sync_service = ExternalSyncService(db)

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
                console.print(f"  Sprint: {active_sprint.get('name', 'Unknown')} (ID: {active_sprint['id']})")
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
        console.print("[yellow]Provide --board to list sprints, or --sprint to import directly.[/yellow]")
        console.print()
        console.print("Examples:")
        console.print("  [cyan]a-sdlc sync jira pull --board 123[/cyan]              # List sprints")
        console.print("  [cyan]a-sdlc sync jira pull --board 123 --active[/cyan]     # Pull active")
        console.print("  [cyan]a-sdlc sync jira pull --sprint 456[/cyan]             # Pull specific")
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
        console.print(f"  [cyan]a-sdlc sync jira pull --board {board_id} --active[/cyan]  # Active sprint")
        console.print(f"  [cyan]a-sdlc sync jira pull --sprint <ID>[/cyan]               # Specific sprint")

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
    from a_sdlc.storage import get_storage
    from a_sdlc.server.sync import ExternalSyncService

    storage = get_storage()
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
        console.print(f"[cyan]Dry run:[/cyan] Would push {len(prds)} PRD(s) to Jira sprint {mapping['external_id']}")
        for prd in prds:
            prd_mapping = storage.get_sync_mapping("prd", prd["id"], "jira")
            action = "Update" if prd_mapping else "Create"
            console.print(f"  {action}: {prd['title']}")
        return

    try:
        sync_service = ExternalSyncService(db)
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
    from a_sdlc.storage import get_storage

    storage = get_storage()
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
                    console.print(f"  [green]✓[/green] {prd['title']} → {prd_mapping['external_id']}")
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
    from a_sdlc.storage import get_storage
    from a_sdlc.server.sync import ExternalSyncService, LinearClient

    storage = get_storage()
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
    sync_service = ExternalSyncService(db)

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
                console.print(f"  Cycle: {active_cycle.get('name', 'Unknown')} (ID: {active_cycle['id']})")
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
    from a_sdlc.storage import get_storage
    from a_sdlc.server.sync import ExternalSyncService

    storage = get_storage()
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
        console.print(f"[cyan]Dry run:[/cyan] Would push {len(prds)} PRD(s) to Linear cycle {mapping['external_id'][:12]}...")
        for prd in prds:
            prd_mapping = storage.get_sync_mapping("prd", prd["id"], "linear")
            action = "Update" if prd_mapping else "Create"
            console.print(f"  {action}: {prd['title']}")
        return

    try:
        sync_service = ExternalSyncService(db)
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
    from a_sdlc.storage import get_storage

    storage = get_storage()
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
                    console.print(f"  [green]✓[/green] {prd['title']} → {prd_mapping['external_id'][:12]}...")
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
    from a_sdlc.storage import get_storage

    storage = get_storage()
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
        status_icon = "[green]created[/green]" if result["status"] == "created" else "[yellow]exists[/yellow]"
        init_files_status.append(f"  {status_icon}: {result['path']}")
    init_files_display = "\n".join(init_files_status)

    console.print(Panel(
        f"[green]Project '{project_name}' initialized![/green]\n\n"
        f"ID: {project['id']}\n"
        f"Path: {project['path']}\n\n"
        f"Generated files:\n{init_files_display}\n\n"
        "Next steps:\n"
        "  [cyan]/sdlc:scan[/cyan]     - Generate documentation artifacts\n"
        "  [cyan]/sdlc:prd[/cyan]      - Create a PRD\n"
        "  [cyan]/sdlc:task[/cyan]     - Create tasks",
        title="[bold]a-sdlc Initialized[/bold]",
        border_style="green"
    ))


if __name__ == "__main__":
    main()
