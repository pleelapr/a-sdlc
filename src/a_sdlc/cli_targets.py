"""
CLI target registry for multi-CLI support.

Defines CLITarget dataclass and detection/resolution functions
for supporting multiple AI CLIs (Claude Code, Gemini CLI).
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CLITarget:
    """Configuration for an AI CLI target."""

    name: str  # "claude" | "gemini"
    display_name: str  # "Claude Code" | "Gemini CLI"
    home_dir: Path
    mcp_config_path: Path  # Where MCP servers are registered
    settings_path: Path  # Where settings.json lives
    commands_dir: Path  # Where skill templates are deployed
    agents_dir: Path | None  # Where persona agents live (None if unsupported)
    context_file: str  # "CLAUDE.md" | "GEMINI.md"


CLAUDE_TARGET = CLITarget(
    name="claude",
    display_name="Claude Code",
    home_dir=Path.home() / ".claude",
    mcp_config_path=Path.home() / ".claude.json",
    settings_path=Path.home() / ".claude" / "settings.json",
    commands_dir=Path.home() / ".claude" / "commands" / "sdlc",
    agents_dir=Path.home() / ".claude" / "agents",
    context_file="CLAUDE.md",
)

GEMINI_TARGET = CLITarget(
    name="gemini",
    display_name="Gemini CLI",
    home_dir=Path.home() / ".gemini",
    mcp_config_path=Path.home() / ".gemini" / "settings.json",
    settings_path=Path.home() / ".gemini" / "settings.json",
    commands_dir=Path.home() / ".gemini" / "commands" / "sdlc",
    agents_dir=None,
    context_file="GEMINI.md",
)

ALL_TARGETS = [CLAUDE_TARGET, GEMINI_TARGET]


def detect_targets() -> list[CLITarget]:
    """Return targets whose home_dir exists on this system."""
    return [t for t in ALL_TARGETS if t.home_dir.exists()]


def resolve_targets(target_name: str | None) -> list[CLITarget]:
    """Resolve --target flag value to a list of CLITarget objects.

    Args:
        target_name: "claude", "gemini", "auto", or None.
            None and "auto" both delegate to detect_targets().

    Returns:
        List of matching CLITarget objects.

    Raises:
        ValueError: If target_name is not recognized.
    """
    if target_name is None or target_name == "auto":
        return detect_targets()

    for target in ALL_TARGETS:
        if target.name == target_name:
            return [target]

    valid = ", ".join(t.name for t in ALL_TARGETS)
    raise ValueError(f"Unknown target '{target_name}'. Valid targets: {valid}, auto")
