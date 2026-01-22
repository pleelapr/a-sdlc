"""
Main CLI for a-sdlc package.

Provides commands for:
- install: Deploy skill templates to Claude Code
- setup-mcp: Install and configure Serena MCP
- doctor: System diagnostics
- plugins: Plugin management
"""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from a_sdlc import __version__
from a_sdlc.installer import Installer
from a_sdlc.mcp_setup import (
    setup_serena,
    verify_setup,
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
def install(list_skills: bool, force: bool, target: Path | None, with_serena: bool) -> None:
    """Deploy skill templates to Claude Code.

    Installs the /sdlc:* commands into your Claude Code configuration,
    making them available for use in any project.

    Examples:

        a-sdlc install                # Install all templates
        a-sdlc install --list         # List installed templates
        a-sdlc install --force        # Reinstall all templates
        a-sdlc install --with-serena  # Also set up Serena MCP
    """
    installer = Installer(target_dir=target)

    if list_skills:
        _list_installed_skills(installer)
        return

    try:
        installed = installer.install(force=force)

        console.print()
        console.print(Panel(
            f"[green]Successfully installed {len(installed)} skill templates![/green]\n\n"
            f"Location: [cyan]{installer.target_dir}[/cyan]\n\n"
            "Available commands:\n"
            "  /sdlc:init   - Initialize .sdlc/ for a project\n"
            "  /sdlc:scan   - Generate all artifacts\n"
            "  /sdlc:update - Incremental artifact updates\n"
            "  /sdlc:prd    - PRD ingestion pipeline\n"
            "  /sdlc:task   - Task management\n"
            "  /sdlc:status - Show artifact freshness\n"
            "  /sdlc:help   - List all commands",
            title="[bold]Installation Complete[/bold]",
            border_style="green"
        ))

        # Set up Serena MCP if requested
        if with_serena:
            console.print()
            _setup_serena_mcp(force=force)

    except Exception as e:
        console.print(f"[red]Error during installation: {e}[/red]")
        sys.exit(1)


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


@main.command()
def doctor() -> None:
    """Run system diagnostics.

    Checks for:
    - Python version compatibility
    - Claude Code configuration
    - Serena MCP server
    - Installed plugins
    - Template integrity
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
    })

    # Claude Code config directory
    claude_dir = Path.home() / ".claude"
    claude_ok = claude_dir.exists()
    checks.append({
        "name": "Claude Code Config",
        "status": "pass" if claude_ok else "warn",
        "detail": str(claude_dir) if claude_ok else "Not found (will be created)"
    })

    # Commands directory
    commands_dir = claude_dir / "commands" / "sdlc"
    commands_ok = commands_dir.exists()
    checks.append({
        "name": "Skill Templates",
        "status": "pass" if commands_ok else "warn",
        "detail": f"{len(list(commands_dir.glob('*.md')))} installed" if commands_ok else "Not installed"
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
        serena_detail = "Configured but installer not found"
        serena_status = "warn"
    else:
        serena_detail = "Not configured. Run: a-sdlc setup-mcp"
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
    available = pm.list_plugins()

    table = Table(title="Available Plugins")
    table.add_column("Plugin", style="cyan")
    table.add_column("Status")
    table.add_column("Description", style="dim")

    descriptions = {
        "local": "File-based task storage in .sdlc/tasks/",
        "linear": "Sync tasks with Linear issue tracker",
    }

    enabled = pm.get_enabled_plugin()

    for plugin in available:
        is_enabled = plugin == enabled
        status = "[green]Enabled[/green]" if is_enabled else "[dim]Available[/dim]"
        table.add_row(plugin, status, descriptions.get(plugin, ""))

    console.print(table)


@plugins.command("enable")
@click.argument("plugin_name")
def plugins_enable(plugin_name: str) -> None:
    """Enable a specific plugin.

    PLUGIN_NAME: Name of the plugin to enable (e.g., 'linear')
    """
    pm = get_plugin_manager()

    try:
        pm.enable_plugin(plugin_name)
        console.print(f"[green]Plugin '{plugin_name}' enabled successfully.[/green]")

        if plugin_name == "linear":
            console.print()
            console.print("Next steps:")
            console.print("  1. Run [cyan]a-sdlc plugins configure linear[/cyan]")
            console.print("  2. Set your Linear API key and team settings")
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@plugins.command("configure")
@click.argument("plugin_name")
def plugins_configure(plugin_name: str) -> None:
    """Configure a plugin interactively.

    PLUGIN_NAME: Name of the plugin to configure
    """
    pm = get_plugin_manager()

    if plugin_name not in pm.list_plugins():
        console.print(f"[red]Unknown plugin: {plugin_name}[/red]")
        sys.exit(1)

    if plugin_name == "local":
        console.print("[dim]Local plugin has no configuration options.[/dim]")
        return

    if plugin_name == "linear":
        _configure_linear_plugin(pm)
        return

    console.print(f"[yellow]No configuration available for '{plugin_name}'.[/yellow]")


def _configure_linear_plugin(pm: object) -> None:
    """Interactive configuration for Linear plugin."""
    console.print(Panel(
        "[bold]Linear Plugin Configuration[/bold]\n\n"
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

    pm.configure_plugin("linear", config)
    console.print("[green]Linear plugin configured successfully![/green]")


if __name__ == "__main__":
    main()
