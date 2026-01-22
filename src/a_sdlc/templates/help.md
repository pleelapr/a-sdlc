# /sdlc:help - List Available Commands

Display all available SDLC skills with descriptions and usage examples.

## Purpose

Quick reference for all `/sdlc:*` commands without leaving Claude Code.

## Execution Steps

### 1. Display Command Reference

Output the complete command list with descriptions.

## Output Format

```
╭──────────────────────────────────────────────────────────╮
│                    SDLC Commands                          │
╰──────────────────────────────────────────────────────────╯

📚 Core Commands

  /sdlc:init     Initialize .sdlc/ directory structure
  /sdlc:scan     Full repo scan → generate all artifacts
  /sdlc:update   Incremental update of stale artifacts
  /sdlc:status   Show artifact freshness

📋 Requirements & Tasks

  /sdlc:prd      PRD ingestion → draft requirements
  /sdlc:task     Requirements → actionable tasks

📖 Help

  /sdlc:help     Show this command reference
```

## Command Details

| Command | Purpose | Common Usage |
|---------|---------|--------------|
| `/sdlc:init` | Initialize SDLC structure | Run once per project |
| `/sdlc:scan` | Generate all 5 artifacts | After major changes |
| `/sdlc:update` | Refresh stale artifacts | Regular maintenance |
| `/sdlc:status` | Check what needs updating | Before starting work |
| `/sdlc:prd` | Process product requirements | When PRD is ready |
| `/sdlc:task` | Manage implementation tasks | During development |

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--brief` | Compact one-line descriptions | false |

## Examples

```
/sdlc:help           # Full command reference
/sdlc:help --brief   # Compact list
```

## Brief Output Mode

```
/sdlc:help --brief

SDLC Commands: init | scan | update | status | prd | task | help
```

## Quick Start Workflow

```
1. /sdlc:init      # Initialize (once)
2. /sdlc:scan      # Generate artifacts
3. /sdlc:status    # Check freshness
4. /sdlc:update    # Refresh as needed
```

## Notes

- All commands work in the project root directory
- Run `/sdlc:status` to see what needs attention
- See README.md for full documentation
